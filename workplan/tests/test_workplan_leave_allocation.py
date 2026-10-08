from unittest import mock

import frappe
from frappe.utils import add_days, flt, getdate
from hrms.hr.doctype.leave_allocation.leave_allocation import LeaveAllocation, LessAllocationError

from workplan.tests.utils import (
	CARRY_ANNUAL,
	CARRY_LEAVE_TYPE,
	CARRY_MAX_DAYS,
	CARRY_POLICY,
	FULL_TIME,
	HALF_TIME,
	LEAVE_TYPE,
	MONDAY,
	PART_TIME_24,
	POLICY_24,
	POLICY_30,
	ZERO_HOURS,
	WorkplanTestCase,
	expected_allocation,
	first_day,
	frozen_today,
	get_allocation,
	last_day,
	ledger_entries,
	ledger_sum,
	make_approved_leave_application,
	make_employee,
	make_leave_application,
	nth_weekday,
	set_hours,
	sorted_workplans,
	workplan_row,
)
from workplan.workplan.overrides import new_allocations_cronjob
from workplan.workplan.overrides.leave_allocation_new import (
	calc_allocation_value,
	get_carry_forward_days,
	update_allocation_for_year,
)
from workplan.workplan.overrides.supress_leave_allocation_validation import CustomLeaveAllocation


class TestAutomaticAllocation(WorkplanTestCase):
	def assertAllocation(self, employee, leave_type, year, expected):
		allocation = get_allocation(employee, leave_type, year)
		self.assertIsNotNone(allocation, f"no {leave_type} allocation for {year}")
		self.assertEqual(getdate(allocation.from_date), first_day(year))
		self.assertEqual(getdate(allocation.to_date), last_day(year))
		self.assertFloatEqual(allocation.new_leaves_allocated, expected)
		self.assertFloatEqual(allocation.total_leaves_allocated, expected)
		# the ledger always matches the allocated value
		self.assertFloatEqual(ledger_sum(allocation.name), expected)
		return allocation

	def test_full_time_gets_full_policy(self):
		employee = make_employee("Full Time", [workplan_row(first_day(self.year))])
		segments = [(first_day(self.year), None, 40, 30)]
		for year in (self.year, self.next_year):
			self.assertAllocation(employee.name, LEAVE_TYPE, year, expected_allocation(segments, year))
		# 30 days in a year with 365 days
		self.assertFloatEqual(expected_allocation([(first_day(2026), None, 40, 30)], 2026), 30)
		# leave types which are not part of the policy are not allocated
		self.assertIsNone(get_allocation(employee.name, CARRY_LEAVE_TYPE, self.year))

	def test_part_time_is_pro_rated(self):
		employee = make_employee("24h", [workplan_row(first_day(self.year), hours=PART_TIME_24)])
		segments = [(first_day(self.year), None, 24, 30)]
		for year in (self.year, self.next_year):
			allocation = self.assertAllocation(
				employee.name, LEAVE_TYPE, year, expected_allocation(segments, year)
			)
			full_time = expected_allocation([(first_day(self.year), None, 40, 30)], year)
			self.assertFloatEqual(allocation.new_leaves_allocated, 0.6 * full_time)
		# 24h/week with a 30 day policy yields 18 days in a year with 365 days
		self.assertFloatEqual(expected_allocation([(first_day(2026), None, 24, 30)], 2026), 18)

	def test_two_workplans_are_time_weighted(self):
		mid_year = getdate(f"{self.year}-06-30")
		employee = make_employee(
			"Two Workplans",
			[
				workplan_row(first_day(self.year), mid_year, FULL_TIME, POLICY_30),
				workplan_row(add_days(mid_year, 1), None, HALF_TIME, POLICY_24),
			],
		)
		segments = [
			(first_day(self.year), mid_year, 40, 30),
			(add_days(mid_year, 1), None, 20, 24),
		]
		expected_this_year = expected_allocation(segments, self.year)
		# fraction_of_year * annual_allocation * hours / 40 per workplan, e.g. in 2026:
		self.assertFloatEqual(
			expected_allocation(
				[
					(getdate("2026-01-01"), getdate("2026-06-30"), 40, 30),
					(getdate("2026-07-01"), None, 20, 24),
				],
				2026,
			),
			30 * (181 / 365) * 1 + 24 * (184 / 365) * 0.5,
		)
		self.assertAllocation(employee.name, LEAVE_TYPE, self.year, expected_this_year)
		self.assertAllocation(
			employee.name, LEAVE_TYPE, self.next_year, expected_allocation(segments, self.next_year)
		)

		value, carry_forward = calc_allocation_value(employee, first_day(self.year), LEAVE_TYPE)
		self.assertFloatEqual(value, expected_this_year)
		self.assertEqual(carry_forward, 0)

	def test_workplan_starting_during_the_year(self):
		start = getdate(f"{self.year}-07-01")
		employee = make_employee("Mid Year Start", [workplan_row(start)])
		self.assertAllocation(employee.name, LEAVE_TYPE, self.year, 30 * (184 / 365))
		self.assertAllocation(
			employee.name,
			LEAVE_TYPE,
			self.next_year,
			expected_allocation([(start, None, 40, 30)], self.next_year),
		)

	def test_hours_change_updates_allocation_with_delta_entry(self):
		employee = make_employee("Hours Change", [workplan_row(first_day(self.year))])
		before = {
			year: get_allocation(employee.name, LEAVE_TYPE, year) for year in (self.year, self.next_year)
		}

		set_hours(employee.custom_workplans[0], PART_TIME_24)
		employee.save()

		for year in (self.year, self.next_year):
			old_value = expected_allocation([(first_day(self.year), None, 40, 30)], year)
			new_value = expected_allocation([(first_day(self.year), None, 24, 30)], year)
			allocation = self.assertAllocation(employee.name, LEAVE_TYPE, year, new_value)
			# the existing allocation is updated in place, the ledger gets a delta entry
			self.assertEqual(allocation.name, before[year].name)
			self.assertEqual(
				[flt(e.leaves, 3) for e in ledger_entries(allocation.name)],
				[flt(old_value, 3), flt(new_value - old_value, 3)],
			)

	def test_saving_unchanged_employee_is_idempotent(self):
		employee = make_employee("Resave", [workplan_row(first_day(self.year), hours=PART_TIME_24)])
		allocation = get_allocation(employee.name, LEAVE_TYPE, self.year)
		entries_before = ledger_entries(allocation.name)

		employee.reload()
		employee.save()

		self.assertEqual(len(ledger_entries(allocation.name)), len(entries_before))
		self.assertFloatEqual(
			get_allocation(employee.name, LEAVE_TYPE, self.year).new_leaves_allocated,
			expected_allocation([(first_day(self.year), None, 24, 30)], self.year),
		)


class TestZeroHoursWorkplan(WorkplanTestCase):
	def test_zero_hours_without_leave_removes_allocations(self):
		employee = make_employee("Zero Hours", [workplan_row(first_day(self.year))])
		allocations = [
			get_allocation(employee.name, LEAVE_TYPE, year) for year in (self.year, self.next_year)
		]

		set_hours(employee.custom_workplans[0], ZERO_HOURS)
		employee.save()

		for allocation in allocations:
			# cancelled (ledger entries reversed by HRMS) and deleted
			self.assertFalse(frappe.db.exists("Leave Allocation", allocation.name))
			self.assertEqual(ledger_entries(allocation.name), [])
			self.assertFalse(frappe.db.exists("Leave Ledger Entry", {"transaction_name": allocation.name}))
		for year in (self.year, self.next_year):
			self.assertIsNone(get_allocation(employee.name, LEAVE_TYPE, year))
			value, _ = calc_allocation_value(employee, first_day(year), LEAVE_TYPE)
			self.assertEqual(value, 0)

		# setting the hours again creates new allocations
		employee.reload()
		set_hours(employee.custom_workplans[0], FULL_TIME)
		employee.save()
		for year in (self.year, self.next_year):
			allocation = get_allocation(employee.name, LEAVE_TYPE, year)
			self.assertFloatEqual(
				allocation.new_leaves_allocated,
				expected_allocation([(first_day(self.year), None, 40, 30)], year),
			)
			self.assertFloatEqual(ledger_sum(allocation.name), allocation.new_leaves_allocated)

	def test_workplan_ending_this_year_removes_next_year_allocation(self):
		employee = make_employee("Ends This Year", [workplan_row(first_day(self.year))])
		next_year_allocation = get_allocation(employee.name, LEAVE_TYPE, self.next_year)
		self.assertIsNotNone(next_year_allocation)

		employee.custom_workplans[0].end = last_day(self.year)
		employee.save()

		self.assertFalse(frappe.db.exists("Leave Allocation", next_year_allocation.name))
		self.assertIsNone(get_allocation(employee.name, LEAVE_TYPE, self.next_year))
		self.assertFloatEqual(get_allocation(employee.name, LEAVE_TYPE, self.year).new_leaves_allocated, 30)

	def test_update_allocation_for_year_with_zero_value_cancels_allocation(self):
		employee = make_employee("Zero Direct", [workplan_row(first_day(self.year))])
		allocation = get_allocation(employee.name, LEAVE_TYPE, self.next_year)
		# no workplan covers the next year any more (in memory only, as the patch/cron would see it)
		employee.custom_workplans[0].end = last_day(self.year)

		update_allocation_for_year(employee, first_day(self.next_year), getdate())

		self.assertFalse(frappe.db.exists("Leave Allocation", allocation.name))
		self.assertEqual(ledger_entries(allocation.name), [])
		# nothing to remove: no error
		update_allocation_for_year(employee, first_day(self.next_year), getdate())

	def test_zero_hours_with_approved_leave_is_rejected(self):
		employee = make_employee("Zero Hours Approved", [workplan_row(first_day(self.year))])
		monday = nth_weekday(self.year, 3, MONDAY)
		application = make_approved_leave_application(employee.name, LEAVE_TYPE, monday, add_days(monday, 2))
		allocation = get_allocation(employee.name, LEAVE_TYPE, self.year)

		employee.reload()
		set_hours(employee.custom_workplans[0], ZERO_HOURS)
		with self.assertRaisesRegex(frappe.ValidationError, "allocation of 0 days") as error:
			employee.save()
		self.assertIn(application.name, str(error.exception))

		# nothing was changed
		self.assertEqual(get_allocation(employee.name, LEAVE_TYPE, self.year).name, allocation.name)
		self.assertFloatEqual(ledger_sum(allocation.name), 30)
		self.assertFloatEqual(ledger_sum(application.name), -3)
		self.assertFloatEqual(
			frappe.db.get_value("Leave Application", application.name, "total_leave_days"), 3
		)

	def test_zero_hours_with_approved_leave_next_year_is_rejected(self):
		employee = make_employee("Zero Hours Next Year", [workplan_row(first_day(self.year))])
		monday = nth_weekday(self.next_year, 3, MONDAY)
		make_approved_leave_application(employee.name, LEAVE_TYPE, monday, monday)

		# ending the workplan this year leaves no workplan (allocation 0) for the approved leave next year
		employee.reload()
		employee.custom_workplans[0].end = last_day(self.year)
		with self.assertRaisesRegex(frappe.ValidationError, f"allocation of 0 days.*{self.next_year}"):
			employee.save()

	def test_zero_hours_with_rejected_leave_is_allowed(self):
		employee = make_employee("Zero Hours Rejected", [workplan_row(first_day(self.year))])
		monday = nth_weekday(self.year, 3, MONDAY)
		application = make_leave_application(employee.name, LEAVE_TYPE, monday, add_days(monday, 2))
		application.insert()
		application.reload()
		application.status = "Rejected"
		application.submit()

		employee.reload()
		set_hours(employee.custom_workplans[0], ZERO_HOURS)
		employee.save()

		self.assertIsNone(get_allocation(employee.name, LEAVE_TYPE, self.year))
		self.assertEqual(ledger_entries(application.name), [])


class TestCustomLeaveAllocation(WorkplanTestCase):
	def setUp(self):
		self.employee = make_employee("Allocation Override", [workplan_row(first_day(self.year))])
		self.allocation = get_allocation(self.employee.name, LEAVE_TYPE, self.year)

	def test_controller_is_overridden(self):
		self.assertIsInstance(self.allocation, CustomLeaveAllocation)

	def test_validate_against_leave_applications_is_suppressed(self):
		monday = nth_weekday(self.year, 3, MONDAY)
		make_approved_leave_application(self.employee.name, LEAVE_TYPE, monday, add_days(monday, 4))
		self.allocation.reload()
		self.allocation.total_leaves_allocated = 1

		# stock HRMS would refuse an allocation below the approved leave days ...
		with self.assertRaises(LessAllocationError):
			LeaveAllocation.validate_against_leave_applications(self.allocation)
		# ... Workplan validates this itself on the Employee (validate_used_days)
		self.assertIsNone(self.allocation.validate_against_leave_applications())

	def test_update_after_submit_creates_single_delta_entry(self):
		self.allocation.new_leaves_allocated = 25
		self.allocation.save()

		# exactly one delta entry: the HRMS on_update_after_submit is replaced by the doc_event
		self.assertEqual([flt(e.leaves, 3) for e in ledger_entries(self.allocation.name)], [30, -5])
		self.allocation.reload()
		self.assertFloatEqual(self.allocation.total_leaves_allocated, 25)
		self.assertFloatEqual(ledger_sum(self.allocation.name), 25)

	def test_custom_carried_forward_creates_carry_forward_entry(self):
		self.allocation.custom_carried_forward = 3
		self.allocation.new_leaves_allocated = 33
		self.allocation.save()

		entries = ledger_entries(self.allocation.name)
		carry_forward_entries = [e for e in entries if e.is_carry_forward]
		self.assertEqual(len(carry_forward_entries), 1)
		self.assertFloatEqual(carry_forward_entries[0].leaves, 3)
		self.assertEqual(getdate(carry_forward_entries[0].from_date), first_day(self.year))
		self.assertEqual(getdate(carry_forward_entries[0].to_date), last_day(self.year))
		self.assertFloatEqual(ledger_sum(self.allocation.name, is_carry_forward=0), 30)
		self.assertFloatEqual(ledger_sum(self.allocation.name), 33)

		# saving again does not create another carry forward entry
		self.allocation.reload()
		self.allocation.save()
		self.assertEqual(len(ledger_entries(self.allocation.name)), len(entries))

		# further changes only add a delta to the regular (not carried forward) leaves
		self.allocation.reload()
		self.allocation.new_leaves_allocated = 35
		self.allocation.save()
		self.assertFloatEqual(ledger_sum(self.allocation.name, is_carry_forward=1), 3)
		self.assertFloatEqual(ledger_sum(self.allocation.name, is_carry_forward=0), 32)


class TestCarryForward(WorkplanTestCase):
	def setUp(self):
		self.employee = make_employee(
			"Carry Forward", [workplan_row(first_day(self.year), policy=CARRY_POLICY)]
		)
		monday = nth_weekday(self.year, 3, MONDAY)
		# 3 days taken, more unused leaves than the maximum carry forward
		make_approved_leave_application(self.employee.name, CARRY_LEAVE_TYPE, monday, add_days(monday, 2))
		self.allocated = expected_allocation([(first_day(self.year), None, 40, CARRY_ANNUAL)], self.year)
		self.expected_carry_forward = min(self.allocated - 3, CARRY_MAX_DAYS)

	def test_no_carry_forward_without_previous_allocation(self):
		allocation = get_allocation(self.employee.name, CARRY_LEAVE_TYPE, self.year)
		self.assertFloatEqual(allocation.new_leaves_allocated, self.allocated)
		self.assertFloatEqual(flt(allocation.custom_carried_forward), 0)
		# the next year allocation is created without carry forward as long as that year has not started
		allocation = get_allocation(self.employee.name, CARRY_LEAVE_TYPE, self.next_year)
		self.assertFloatEqual(
			allocation.new_leaves_allocated,
			expected_allocation([(first_day(self.year), None, 40, CARRY_ANNUAL)], self.next_year),
		)
		self.assertFalse(any(e.is_carry_forward for e in ledger_entries(allocation.name)))

	def test_unused_leaves_are_carried_forward_into_next_year(self):
		self.assertGreater(self.allocated - 3, CARRY_MAX_DAYS)
		next_year_allocated = expected_allocation(
			[(first_day(self.year), None, 40, CARRY_ANNUAL)], self.next_year
		)
		allocation = get_allocation(self.employee.name, CARRY_LEAVE_TYPE, self.next_year)

		with frozen_today(first_day(self.next_year)):
			employee = frappe.get_doc("Employee", self.employee.name)
			# limited by maximum_carry_forwarded_leaves
			self.assertFloatEqual(
				get_carry_forward_days(employee, CARRY_LEAVE_TYPE, last_day(self.year), self.next_year),
				self.expected_carry_forward,
			)

			update_allocation_for_year(employee, first_day(self.next_year), getdate())

			allocation.reload()
			self.assertFloatEqual(
				allocation.new_leaves_allocated, next_year_allocated + self.expected_carry_forward
			)
			self.assertFloatEqual(flt(allocation.custom_carried_forward), self.expected_carry_forward)
			self.assertFloatEqual(
				ledger_sum(allocation.name, is_carry_forward=1), self.expected_carry_forward
			)
			self.assertFloatEqual(ledger_sum(allocation.name, is_carry_forward=0), next_year_allocated)

			# once booked, the carry forward entry is the source of truth
			self.assertFloatEqual(
				get_carry_forward_days(employee, CARRY_LEAVE_TYPE, last_day(self.year), self.next_year),
				self.expected_carry_forward,
			)

			# running it again changes nothing
			entries = ledger_entries(allocation.name)
			update_allocation_for_year(employee, first_day(self.next_year), getdate())
			self.assertEqual(len(ledger_entries(allocation.name)), len(entries))
			allocation.reload()
			self.assertFloatEqual(
				allocation.new_leaves_allocated, next_year_allocated + self.expected_carry_forward
			)

	def test_carry_forward_without_maximum_carries_all_unused_leaves(self):
		frappe.db.set_value("Leave Type", CARRY_LEAVE_TYPE, "maximum_carry_forwarded_leaves", 0)
		self.addCleanup(
			frappe.db.set_value,
			"Leave Type",
			CARRY_LEAVE_TYPE,
			"maximum_carry_forwarded_leaves",
			CARRY_MAX_DAYS,
		)
		with frozen_today(first_day(self.next_year)):
			employee = frappe.get_doc("Employee", self.employee.name)
			self.assertFloatEqual(
				get_carry_forward_days(employee, CARRY_LEAVE_TYPE, last_day(self.year), self.next_year),
				self.allocated - 3,
			)


class TestNewAllocationsCronjob(WorkplanTestCase):
	def test_allocate_all_next_year(self):
		active = make_employee("Cron Active", [workplan_row(first_day(self.year), hours=PART_TIME_24)])
		carry = make_employee("Cron Carry", [workplan_row(first_day(self.year), policy=CARRY_POLICY)])
		monday = nth_weekday(self.year, 3, MONDAY)
		make_approved_leave_application(carry.name, CARRY_LEAVE_TYPE, monday, add_days(monday, 2))
		inactive = make_employee("Cron Inactive", [workplan_row(first_day(self.year))])
		frappe.db.set_value("Employee", inactive.name, "status", "Inactive")
		test_employees = {active.name, carry.name, inactive.name}

		real_update_all_allocations = new_allocations_cronjob.update_all_allocations
		called_for = []

		def update_test_employees_only(employee_doc, method):
			# other employees on the site are not touched by this test
			called_for.append(employee_doc.name)
			if employee_doc.name in test_employees:
				real_update_all_allocations(employee_doc, method)

		year_after_next = self.next_year + 1
		# the cron job runs on January 1st
		with (
			frozen_today(first_day(self.next_year)),
			mock.patch.object(
				new_allocations_cronjob, "update_all_allocations", side_effect=update_test_employees_only
			),
		):
			new_allocations_cronjob.allocate_all_next_year()

		self.assertIn(active.name, called_for)
		self.assertIn(carry.name, called_for)
		self.assertNotIn(inactive.name, called_for)

		# allocations for the new "next year"
		allocation = get_allocation(active.name, LEAVE_TYPE, year_after_next)
		self.assertIsNotNone(allocation)
		self.assertFloatEqual(
			allocation.new_leaves_allocated,
			expected_allocation([(first_day(self.year), None, 24, 30)], year_after_next),
		)
		self.assertFloatEqual(ledger_sum(allocation.name), allocation.new_leaves_allocated)
		self.assertIsNone(get_allocation(inactive.name, LEAVE_TYPE, year_after_next))

		# the new current year got the carry forward
		allocation = get_allocation(carry.name, CARRY_LEAVE_TYPE, self.next_year)
		carried_forward = min(
			expected_allocation([(first_day(self.year), None, 40, CARRY_ANNUAL)], self.year) - 3,
			CARRY_MAX_DAYS,
		)
		self.assertFloatEqual(flt(allocation.custom_carried_forward), carried_forward)
		self.assertFloatEqual(
			allocation.new_leaves_allocated,
			expected_allocation([(first_day(self.year), None, 40, CARRY_ANNUAL)], self.next_year)
			+ carried_forward,
		)
		self.assertFloatEqual(ledger_sum(allocation.name), allocation.new_leaves_allocated)
		self.assertIsNotNone(get_allocation(carry.name, CARRY_LEAVE_TYPE, year_after_next))
