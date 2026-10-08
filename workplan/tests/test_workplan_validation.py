import frappe
from frappe.utils import add_days, getdate

from workplan.tests.utils import (
	FULL_TIME,
	LEAVE_TYPE,
	MONDAY,
	PART_TIME_24,
	WorkplanTestCase,
	first_day,
	get_allocation,
	last_day,
	make_approved_leave_application,
	make_employee,
	nth_weekday,
	set_hours,
	workplan_row,
)
from workplan.workplan.overrides.workplan_validation import validate_used_days_for_year


class TestWorkplanValidation(WorkplanTestCase):
	def setUp(self):
		self.employee = make_employee("Validation", [workplan_row(first_day(self.year))])

	def test_overlapping_workplans_are_rejected(self):
		self.employee.append(
			"custom_workplans",
			workplan_row(getdate(f"{self.year}-08-01"), getdate(f"{self.year}-08-31"), FULL_TIME),
		)
		with self.assertRaisesRegex(frappe.ValidationError, "Work plan periods overlap"):
			self.employee.save()

	def test_adjacent_workplans_are_accepted(self):
		self.employee.custom_workplans[0].end = getdate(f"{self.year}-07-31")
		self.employee.append(
			"custom_workplans", workplan_row(getdate(f"{self.year}-08-01"), None, PART_TIME_24)
		)
		self.employee.save()
		self.assertEqual(len(self.employee.custom_workplans), 2)

	def test_end_before_start_is_rejected(self):
		self.employee.custom_workplans[0].end = add_days(first_day(self.year), -1)
		with self.assertRaisesRegex(frappe.ValidationError, "End of a work plan cannot be before start"):
			self.employee.save()

	def test_new_workplan_before_current_year_is_rejected(self):
		self.employee.append(
			"custom_workplans", workplan_row(first_day(self.year - 1), last_day(self.year - 1), FULL_TIME)
		)
		with self.assertRaisesRegex(frappe.ValidationError, f"cannot be before {self.year}"):
			self.employee.save()

	def test_new_employee_with_workplan_before_current_year_is_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, f"cannot be before {self.year}"):
			make_employee("Past Workplan", [workplan_row(first_day(self.year - 1))])

	def test_moving_start_before_current_year_is_rejected(self):
		self.employee.custom_workplans[0].start = getdate(f"{self.year - 1}-12-01")
		with self.assertRaisesRegex(frappe.ValidationError, f"cannot be before {self.year}"):
			self.employee.save()

	def test_changing_past_workplan_is_rejected(self):
		# a workplan from the previous year (cannot be created through the validation any more)
		row = self.employee.custom_workplans[0]
		frappe.db.set_value("Workplan", row.name, "start", first_day(self.year - 1))

		self.employee.reload()
		set_hours(self.employee.custom_workplans[0], PART_TIME_24)
		with self.assertRaisesRegex(
			frappe.ValidationError, f"Workhours before {self.year} cannot be changed"
		):
			self.employee.save()

		self.employee.reload()
		self.employee.custom_workplans[0].start = getdate(f"{self.year - 1}-06-01")
		with self.assertRaisesRegex(frappe.ValidationError, "Start date cannot be changed"):
			self.employee.save()

		self.employee.reload()
		self.employee.custom_workplans = []
		self.employee.append("custom_workplans", workplan_row(first_day(self.year)))
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be deleted"):
			self.employee.save()

		# ending it is still possible
		self.employee.reload()
		self.employee.custom_workplans[0].end = last_day(self.year)
		self.employee.save()

	def test_changing_end_of_past_workplan_is_rejected(self):
		row = self.employee.custom_workplans[0]
		frappe.db.set_value(
			"Workplan", row.name, {"start": first_day(self.year - 1), "end": last_day(self.year - 1)}
		)
		self.employee.reload()
		self.employee.custom_workplans[0].end = getdate(f"{self.year - 1}-11-30")
		with self.assertRaisesRegex(frappe.ValidationError, "End date cannot be changed"):
			self.employee.save()

	def test_open_workplan_cannot_end_before_previous_year(self):
		row = self.employee.custom_workplans[0]
		frappe.db.set_value("Workplan", row.name, "start", first_day(self.year - 2))
		self.employee.reload()
		self.employee.custom_workplans[0].end = getdate(f"{self.year - 1}-06-30")
		with self.assertRaisesRegex(frappe.ValidationError, "Earliest possible end date"):
			self.employee.save()

	def test_allocation_below_approved_leave_is_rejected(self):
		monday = nth_weekday(self.year, 2, MONDAY)
		# three full weeks: 15 days
		make_approved_leave_application(self.employee.name, LEAVE_TYPE, monday, add_days(monday, 18))
		allocation = get_allocation(self.employee.name, LEAVE_TYPE, self.year)

		self.employee.reload()
		# ending the workplan in March reduces the allocation to 30 * 90/365 days
		self.employee.custom_workplans[0].end = getdate(f"{self.year}-03-31")
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be less than already approved leaves"):
			self.employee.save()
		self.assertFloatEqual(
			get_allocation(self.employee.name, LEAVE_TYPE, self.year).new_leaves_allocated,
			allocation.new_leaves_allocated,
		)

		# reducing hours reduces the approved leave days as well, so this is allowed
		self.employee.reload()
		set_hours(self.employee.custom_workplans[0], PART_TIME_24)
		self.employee.save()

	def test_validate_used_days_for_year_without_applications(self):
		set_hours(self.employee.custom_workplans[0], (0, 0, 0, 0, 0))
		# no approved applications: nothing to validate, even with an allocation of 0
		self.assertIsNone(validate_used_days_for_year(self.employee, self.year, LEAVE_TYPE))
