import frappe
from frappe.utils import add_days, flt, getdate
from hrms.hr.doctype.leave_application.leave_application import (
	InsufficientLeaveBalanceError,
	get_leave_balance_on,
	get_leave_details,
)

from workplan.tests.utils import (
	FRIDAY,
	FULL_TIME,
	INCLUSIVE_LEAVE_TYPE,
	LEAVE_TYPE,
	MONDAY,
	PART_TIME_24,
	WEDNESDAY,
	WorkplanTestCase,
	approve,
	custom_holiday,
	expected_allocation,
	expected_leave_days,
	first_day,
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
from workplan.workplan.overrides.leave_application import (
	get_fractional_leave_details,
	get_leaves_for_period,
	get_number_of_leave_day_for_employee_doc,
	get_number_of_leave_days,
	get_number_of_leave_days_leave_application,
	get_weekdays_diff,
)
from workplan.workplan.overrides.leave_application_validation import CustomLeaveApplication


def balance(employee, leave_type, date):
	return get_leave_balance_on(
		employee,
		leave_type,
		getdate(date),
		last_day(getdate(date).year),
		consider_all_leaves_in_the_allocation_period=True,
		for_consumption=True,
	)


class TestLeaveDays(WorkplanTestCase):
	def test_get_weekdays_diff(self):
		monday = nth_weekday(self.year, 3, MONDAY)
		self.assertEqual(get_weekdays_diff(monday, monday), [1, 0, 0, 0, 0, 0, 0])
		self.assertEqual(get_weekdays_diff(monday, add_days(monday, 2)), [1, 1, 1, 0, 0, 0, 0])
		self.assertEqual(get_weekdays_diff(monday, add_days(monday, 13)), [2, 2, 2, 2, 2, 2, 2])
		friday = add_days(monday, 4)
		# Friday to Monday wraps around the weekend
		self.assertEqual(get_weekdays_diff(friday, add_days(friday, 3)), [1, 0, 0, 0, 1, 1, 1])
		self.assertEqual(get_weekdays_diff(monday, add_days(monday, 15)), [3, 3, 2, 2, 2, 2, 2])

	def test_leave_days_use_workplan_hours(self):
		plan = [(first_day(self.year), None, PART_TIME_24)]
		employee = make_employee("Leave Days", [workplan_row(first_day(self.year), hours=PART_TIME_24)])
		monday = nth_weekday(self.year, 3, MONDAY)

		cases = {
			# Mon 8h + Tue 4h + Wed 8h
			(monday, add_days(monday, 2)): 2.5,
			# whole week: 24h
			(monday, add_days(monday, 6)): 3,
			# Friday has 0 hours
			(add_days(monday, 4), add_days(monday, 4)): 0,
			(add_days(monday, 4), add_days(monday, 7)): 1,
		}
		for (from_date, to_date), expected in cases.items():
			self.assertFloatEqual(
				get_number_of_leave_days(employee.name, LEAVE_TYPE, from_date, to_date), expected
			)
			self.assertFloatEqual(expected_leave_days(plan, from_date, to_date), expected)
			self.assertFloatEqual(
				get_number_of_leave_day_for_employee_doc(employee, LEAVE_TYPE, from_date, to_date), expected
			)

	def test_holidays_are_excluded_unless_leave_type_includes_them(self):
		employee = make_employee("Holidays", [workplan_row(first_day(self.year), hours=FULL_TIME)])
		holiday = custom_holiday(self.year)
		self.assertEqual(holiday.weekday(), WEDNESDAY)
		monday = add_days(holiday, -2)
		sunday = add_days(holiday, 4)

		self.assertFloatEqual(get_number_of_leave_days(employee.name, LEAVE_TYPE, monday, sunday), 4)
		self.assertFloatEqual(get_number_of_leave_days(employee.name, LEAVE_TYPE, holiday, holiday), 0)
		# include_holiday: the holiday counts, the weekend has no workplan hours anyway
		self.assertFloatEqual(
			get_number_of_leave_days(employee.name, INCLUSIVE_LEAVE_TYPE, monday, sunday), 5
		)

	def test_leave_days_across_workplans(self):
		boundary = nth_weekday(self.year, 7, WEDNESDAY)
		gap_end = add_days(boundary, 7)
		plan = [
			(first_day(self.year), boundary, FULL_TIME),
			(add_days(boundary, 1), gap_end, PART_TIME_24),
			# one week without workplan
			(add_days(gap_end, 8), None, (2, 2, 2, 2, 2)),
		]
		employee = make_employee(
			"Across Workplans", [workplan_row(start, end, hours) for start, end, hours in plan]
		)
		from_date = add_days(boundary, -2)

		for to_date in (add_days(boundary, 2), add_days(gap_end, 1), add_days(gap_end, 14)):
			expected = expected_leave_days(plan, from_date, to_date)
			self.assertFloatEqual(
				get_number_of_leave_days(employee.name, LEAVE_TYPE, from_date, to_date), expected
			)
			self.assertFloatEqual(
				get_number_of_leave_day_for_employee_doc(employee, LEAVE_TYPE, from_date, to_date), expected
			)
		# Mon + Tue + Wed full time, Thu 4h + Fri 0h part time
		self.assertFloatEqual(
			get_number_of_leave_days(employee.name, LEAVE_TYPE, from_date, add_days(boundary, 2)), 3.5
		)

	def test_leave_days_outside_workplan_raise(self):
		employee = make_employee("No Workplan", [workplan_row(nth_weekday(self.year, 3, MONDAY))])
		with self.assertRaisesRegex(frappe.ValidationError, "Workplan for already applied Vacation missing"):
			get_number_of_leave_days(
				employee.name, LEAVE_TYPE, first_day(self.year), add_days(first_day(self.year), 3)
			)

	def test_whitelisted_method_is_overridden(self):
		self.assertEqual(
			frappe.get_hooks("override_whitelisted_methods").get(
				"hrms.hr.doctype.leave_application.leave_application.get_number_of_leave_days"
			),
			["workplan.workplan.overrides.leave_application.get_number_of_leave_days"],
		)


class TestLeaveApplication(WorkplanTestCase):
	def setUp(self):
		self.employee = make_employee("Applicant", [workplan_row(first_day(self.year), hours=PART_TIME_24)])
		self.allocated = expected_allocation([(first_day(self.year), None, 24, 30)], self.year)
		self.monday = nth_weekday(self.year, 3, MONDAY)

	def test_insert_and_submit(self):
		application = make_leave_application(
			self.employee.name, LEAVE_TYPE, self.monday, add_days(self.monday, 2)
		)
		self.assertIsInstance(application, CustomLeaveApplication)
		self.assertFloatEqual(application.total_leave_days, 2.5)
		self.assertIsNone(application.custom_fractional_day_value)
		application.insert()
		self.assertFloatEqual(application.total_leave_days, 2.5)

		details = get_leave_details(self.employee.name, self.monday)["leave_allocation"][LEAVE_TYPE]
		self.assertFloatEqual(details["leaves_pending_approval"], 2.5)
		self.assertFloatEqual(details["leaves_taken"], 0)

		approve(application)
		self.assertEqual(application.docstatus, 1)

		entries = ledger_entries(application.name)
		self.assertEqual(len(entries), 1)
		self.assertFloatEqual(entries[0].leaves, -2.5)
		self.assertEqual(getdate(entries[0].from_date), self.monday)
		self.assertEqual(getdate(entries[0].to_date), add_days(self.monday, 2))

		self.assertEqual(
			{
				key: flt(value, 3)
				for key, value in balance(self.employee.name, LEAVE_TYPE, self.monday).items()
			},
			{
				"leave_balance": flt(self.allocated - 2.5, 3),
				"leave_balance_for_consumption": flt(self.allocated - 2.5, 3),
			},
		)
		details = get_leave_details(self.employee.name, self.monday)["leave_allocation"][LEAVE_TYPE]
		self.assertFloatEqual(details["total_leaves"], self.allocated)
		self.assertFloatEqual(details["leaves_taken"], 2.5)
		self.assertFloatEqual(details["leaves_pending_approval"], 0)
		self.assertFloatEqual(details["remaining_leaves"], self.allocated - 2.5)
		self.assertFloatEqual(details["expired_leaves"], 0)

	def test_total_leave_days_must_be_set_by_client(self):
		application = make_leave_application(
			self.employee.name, LEAVE_TYPE, self.monday, add_days(self.monday, 2), fill=False
		)
		with self.assertRaisesRegex(frappe.ValidationError, "Something went wrong"):
			application.insert()

		# a value not matching the workplan is rejected as well
		application.total_leave_days = 3
		with self.assertRaisesRegex(frappe.ValidationError, "Something went wrong"):
			application.insert()

	def test_application_on_days_without_hours(self):
		friday = add_days(self.monday, 4)
		application = make_leave_application(self.employee.name, LEAVE_TYPE, friday, friday)
		self.assertFloatEqual(application.total_leave_days, 0)
		with self.assertRaisesRegex(frappe.ValidationError, "are holidays"):
			application.insert()

	def test_application_outside_workplan_is_rejected(self):
		end = getdate(f"{self.year}-06-30")
		employee = make_employee("Workplan Ends", [workplan_row(first_day(self.year), end, PART_TIME_24)])
		july = nth_weekday(self.year, 7, MONDAY)
		for from_date, to_date in ((july, add_days(july, 1)), (add_days(end, -3), add_days(end, 3))):
			application = make_leave_application(employee.name, LEAVE_TYPE, from_date, to_date, fill=False)
			application.total_leave_days = 1
			with self.assertRaisesRegex(frappe.ValidationError, "ausserhalb von Workplans"):
				application.insert()

	def test_application_across_adjacent_workplans_is_accepted(self):
		end = nth_weekday(self.year, 4, WEDNESDAY)
		employee = make_employee(
			"Adjacent Workplans",
			[
				workplan_row(first_day(self.year), end, FULL_TIME),
				workplan_row(add_days(end, 1), None, PART_TIME_24),
			],
		)
		application = make_leave_application(employee.name, LEAVE_TYPE, add_days(end, -2), add_days(end, 2))
		application.insert()
		# Mon-Wed 8h, Thu 4h, Fri 0h
		self.assertFloatEqual(application.total_leave_days, 3.5)

	def test_insufficient_balance(self):
		from_date = nth_weekday(self.year, 8, MONDAY)
		to_date = add_days(from_date, 7 * 10 - 1)
		requested = get_number_of_leave_days(self.employee.name, LEAVE_TYPE, from_date, to_date)
		self.assertGreater(requested, self.allocated + 1)

		# far beyond the balance: no fractional day possible
		self.assertEqual(
			get_number_of_leave_days_leave_application(self.employee.name, LEAVE_TYPE, from_date, to_date),
			{
				"fractional_value": None,
				"fractional_work": None,
				"total_leave_days": None,
				"date": None,
				"weekday": None,
			},
		)
		self.assertEqual(
			get_fractional_leave_details(self.employee.name, LEAVE_TYPE, from_date, to_date),
			(None, None, None, None),
		)

		application = make_leave_application(self.employee.name, LEAVE_TYPE, from_date, to_date)
		self.assertFloatEqual(application.total_leave_days, requested)
		with self.assertRaises(InsufficientLeaveBalanceError):
			application.insert()

	def test_no_fractional_day_within_balance(self):
		result = get_number_of_leave_days_leave_application(
			self.employee.name, LEAVE_TYPE, self.monday, add_days(self.monday, 2)
		)
		self.assertEqual(set(result.values()), {None})

	def test_fractional_leave_day(self):
		make_approved_leave_application(self.employee.name, LEAVE_TYPE, self.monday, add_days(self.monday, 2))
		available = flt(
			balance(self.employee.name, LEAVE_TYPE, self.monday)["leave_balance_for_consumption"], 3
		)
		self.assertFloatEqual(available, self.allocated - 2.5)

		# five full weeks (15 days) plus a Monday (8h = 1 day)
		from_date = nth_weekday(self.year, 9, MONDAY)
		to_date = add_days(from_date, 35)
		requested = get_number_of_leave_days(self.employee.name, LEAVE_TYPE, from_date, to_date)
		self.assertFloatEqual(requested, 16)
		# the balance covers all but a part of the last day (Monday, 8h)
		fractional_value = 1 + available - requested
		self.assertTrue(0 < fractional_value < 1)

		result = get_number_of_leave_days_leave_application(
			self.employee.name, LEAVE_TYPE, from_date, to_date
		)
		self.assertFloatEqual(result["fractional_value"], fractional_value)
		self.assertFloatEqual(result["fractional_work"], 1 - fractional_value)
		self.assertFloatEqual(result["total_leave_days"], available)
		self.assertEqual(getdate(result["date"]), to_date)
		self.assertEqual(result["weekday"], MONDAY)

		total, fractional_work, last_workday, fractional = get_fractional_leave_details(
			self.employee.name, LEAVE_TYPE, from_date, to_date
		)
		self.assertFloatEqual(total, available)
		self.assertFloatEqual(fractional_work, 1 - fractional_value)
		self.assertEqual(getdate(last_workday), to_date)
		self.assertFloatEqual(fractional, fractional_value)

		application = make_leave_application(self.employee.name, LEAVE_TYPE, from_date, to_date)
		self.assertFloatEqual(application.total_leave_days, available)
		self.assertFloatEqual(application.custom_fractional_day_value, fractional_value)
		self.assertEqual(application.custom_last_workday_weekday, "Monday")
		self.assertEqual(application.custom_hours_to_work, int((1 - fractional_value) * 8))
		application.insert()
		self.assertFloatEqual(application.total_leave_days, available)
		self.assertEqual(getdate(application.custom_last_workday_date), to_date)

		approve(application)
		self.assertFloatEqual(ledger_sum(application.name), -available)
		self.assertFloatEqual(
			balance(self.employee.name, LEAVE_TYPE, from_date)["leave_balance_for_consumption"], 0
		)
		details = get_leave_details(self.employee.name, from_date)["leave_allocation"][LEAVE_TYPE]
		self.assertFloatEqual(details["leaves_taken"], self.allocated)
		self.assertFloatEqual(details["remaining_leaves"], 0)
		# the fractional application counts with its fractional value
		self.assertFloatEqual(
			get_number_of_leave_days(self.employee.name, LEAVE_TYPE, from_date, to_date), available
		)

	def test_workplan_change_recalculates_approved_application(self):
		application = make_approved_leave_application(
			self.employee.name, LEAVE_TYPE, self.monday, add_days(self.monday, 2)
		)
		self.assertFloatEqual(application.total_leave_days, 2.5)

		# Tuesday 4h -> 8h
		self.employee.reload()
		set_hours(self.employee.custom_workplans[0], (8, 8, 8, 4, 0))
		self.employee.save()

		application.reload()
		self.assertFloatEqual(application.total_leave_days, 3)
		self.assertEqual([flt(e.leaves, 3) for e in ledger_entries(application.name)], [-2.5, -0.5])
		self.assertFloatEqual(ledger_sum(application.name), -application.total_leave_days)

		allocated = expected_allocation([(first_day(self.year), None, 28, 30)], self.year)
		self.assertFloatEqual(
			get_allocation(self.employee.name, LEAVE_TYPE, self.year).new_leaves_allocated, allocated
		)
		details = get_leave_details(self.employee.name, self.monday)["leave_allocation"][LEAVE_TYPE]
		self.assertFloatEqual(details["total_leaves"], allocated)
		self.assertFloatEqual(details["leaves_taken"], 3)
		self.assertFloatEqual(details["remaining_leaves"], allocated - 3)
		self.assertFloatEqual(
			balance(self.employee.name, LEAVE_TYPE, self.monday)["leave_balance"], allocated - 3
		)

		# Monday 8h -> 4h
		self.employee.reload()
		set_hours(self.employee.custom_workplans[0], (4, 8, 8, 4, 0))
		self.employee.save()
		application.reload()
		self.assertFloatEqual(application.total_leave_days, 2.5)
		self.assertEqual(len(ledger_entries(application.name)), 3)
		self.assertFloatEqual(ledger_sum(application.name), -2.5)

	def test_workplan_change_recalculates_open_application(self):
		application = make_leave_application(
			self.employee.name, LEAVE_TYPE, self.monday, add_days(self.monday, 2)
		)
		application.insert()

		self.employee.reload()
		set_hours(self.employee.custom_workplans[0], FULL_TIME)
		self.employee.save()

		application.reload()
		self.assertFloatEqual(application.total_leave_days, 3)
		# not approved: no ledger entries
		self.assertEqual(ledger_entries(application.name), [])

	def test_new_workplan_row_keeps_existing_applications(self):
		application = make_approved_leave_application(
			self.employee.name, LEAVE_TYPE, self.monday, add_days(self.monday, 2)
		)
		mid_year = getdate(f"{self.year}-06-30")
		self.employee.reload()
		self.employee.custom_workplans[0].end = mid_year
		self.employee.append("custom_workplans", workplan_row(add_days(mid_year, 1), None, (8, 8, 8, 4, 0)))
		self.employee.save()

		self.assertEqual(len(sorted_workplans(self.employee)), 2)
		application.reload()
		self.assertFloatEqual(application.total_leave_days, 2.5)
		self.assertFloatEqual(ledger_sum(application.name), -2.5)
		self.assertFloatEqual(
			get_allocation(self.employee.name, LEAVE_TYPE, self.year).new_leaves_allocated,
			expected_allocation(
				[(first_day(self.year), mid_year, 24, 30), (add_days(mid_year, 1), None, 28, 30)], self.year
			),
		)


class TestGetLeavesForPeriod(WorkplanTestCase):
	def test_multiple_ledger_entries_of_one_application_are_counted_once(self):
		employee = make_employee(
			"Leaves For Period", [workplan_row(first_day(self.year), hours=PART_TIME_24)]
		)
		monday = nth_weekday(self.year, 3, MONDAY)
		application = make_approved_leave_application(employee.name, LEAVE_TYPE, monday, add_days(monday, 2))
		other_monday = nth_weekday(self.year, 4, MONDAY)
		make_approved_leave_application(employee.name, LEAVE_TYPE, other_monday, add_days(other_monday, 6))
		self.assertFloatEqual(
			get_leaves_for_period(employee.name, LEAVE_TYPE, first_day(self.year), last_day(self.year)), -5.5
		)

		# the workplan change adds a second ledger entry for the first application
		employee.reload()
		set_hours(employee.custom_workplans[0], (8, 8, 8, 4, 0))
		employee.save()
		self.assertEqual(len(ledger_entries(application.name)), 2)

		# recalculated with the current workplan, every application only once: 3 + 3.5
		self.assertFloatEqual(
			get_leaves_for_period(employee.name, LEAVE_TYPE, first_day(self.year), last_day(self.year)), -6.5
		)
		# HRMS uses the patched function as well
		import hrms.hr.doctype.leave_application.leave_application as hrms_leave_application

		self.assertFloatEqual(
			hrms_leave_application.get_leaves_for_period(
				employee.name, LEAVE_TYPE, first_day(self.year), last_day(self.year)
			),
			-6.5,
		)
		# only the part within the period is counted (Tue 8h + Wed 8h of the first application)
		self.assertFloatEqual(
			get_leaves_for_period(employee.name, LEAVE_TYPE, add_days(monday, 1), last_day(self.year)), -5.5
		)

	def test_period_without_leave(self):
		employee = make_employee("No Leaves", [workplan_row(first_day(self.year))])
		self.assertEqual(
			get_leaves_for_period(employee.name, LEAVE_TYPE, first_day(self.year), last_day(self.year)), 0
		)
