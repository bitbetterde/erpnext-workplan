import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from workplan.workplan.overrides.leave_allocation_new import (
	calc_allocation_value,
	calc_new_allocation_value,
	get_current_days_allocated,
	get_policy_value,
	insert_new_allocation,
)
from workplan.workplan.patches.set_workplans import get_leave_policy


class TestLeaveAllocationUtils(FrappeTestCase):
	def setUp(self):
		self.policy1 = frappe.get_doc(
			{
				"doctype": "Leave Policy",
				"title": "Test Policy",
				"leave_policy_details": [{"leave_type": "Casual Leave", "annual_allocation": 12}],
			}
		).insert()

		self.policy2 = frappe.get_doc(
			{
				"doctype": "Leave Policy",
				"title": "Test Policy",
				"leave_policy_details": [{"leave_type": "Casual Leave", "annual_allocation": 24}],
			}
		).insert()

		self.employee = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": "Max",
				"last_name": "Mustermann",
				"gender": "Male",
				"date_of_birth": getdate("1990-01-01"),
				"status": "Active",
				"date_of_joining": getdate("2026-01-01"),
				"custom_monday": 0,
				"custom_tuesday": 0,
				"custom_wednesday": 0,
				"custom_thursday": 0,
				"custom_friday": 0,
				"custom_workplans": [
					{
						"name": "testwp",
						"start": getdate("2026-01-01"),
						"policy": self.policy1.name,
						"monday": 8,
						"tuesday": 8,
						"wednesday": 8,
						"thursday": 8,
						"friday": 8,
					}
				],
			}
		).insert()

	def test_calc_sum_from_today(self):
		start_date = getdate("2026-01-01")
		days = calc_allocation_value(self.employee, start_date)
		self.assertTrue(days > 0)
		self.assertAlmostEqual(days, 12.0, places=1)

	def test_last_day_equal_no_end(self):
		date = getdate("2026-01-01")
		no_end_result = calc_allocation_value(self.employee, date)
		self.employee.custom_workplans[0].end = getdate("2026-12-31")
		last_day_result = calc_allocation_value(self.employee, date)
		self.assertEqual(no_end_result, last_day_result)

	def test_first_day_equal_running_wp(self):
		date = getdate("2026-01-01")
		first_day_result = calc_allocation_value(self.employee, date)
		date = getdate("2027-01-01")
		running_wp_result = calc_allocation_value(self.employee, date)
		self.assertEqual(first_day_result, running_wp_result)

	def test_work_hours_change(self):
		date = getdate("2026-01-01")
		last_day = getdate("2026-06-30")
		first_day = getdate("2026-07-01")
		self.employee.custom_workplans[0].end = last_day

		new_wp = frappe.get_doc(
			{
				"doctype": "Workplan",
				"start": first_day,
				"policy": self.policy1.name,
				"monday": 4,
				"tuesday": 4,
				"wednesday": 4,
				"thursday": 4,
				"friday": 4,
			}
		)
		new_wp.parent = self.employee.name
		new_wp.parenttype = "Employee"
		new_wp.parentfield = "custom_workplans"
		self.employee.append("custom_workplans", new_wp)
		self.employee.save()

		self.assertAlmostEqual(calc_allocation_value(self.employee, date), 9, 1)
		print(calc_allocation_value(self.employee, date))

	def test_policy_change(self):
		date = getdate("2026-01-01")
		last_day = getdate("2026-06-30")
		first_day = getdate("2026-07-01")
		self.employee.custom_workplans[0].end = last_day

		new_wp = frappe.get_doc(
			{
				"doctype": "Workplan",
				"start": first_day,
				"policy": self.policy2.name,
				"monday": 8,
				"tuesday": 8,
				"wednesday": 8,
				"thursday": 8,
				"friday": 8,
			}
		)
		new_wp.parent = self.employee.name
		new_wp.parenttype = "Employee"
		new_wp.parentfield = "custom_workplans"
		self.employee.append("custom_workplans", new_wp)
		self.employee.save()

		self.assertAlmostEqual(calc_allocation_value(self.employee, date), 18, 1)
		print(calc_allocation_value(self.employee, date))

	def test_policy_and_hours_change(self):
		date = getdate("2026-01-01")
		last_day = getdate("2026-06-30")
		first_day = getdate("2026-07-01")
		self.employee.custom_workplans[0].end = last_day

		new_wp = frappe.get_doc(
			{
				"doctype": "Workplan",
				"start": first_day,
				"policy": self.policy2.name,
				"monday": 2,
				"tuesday": 2,
				"wednesday": 2,
				"thursday": 2,
				"friday": 2,
			}
		)
		new_wp.parent = self.employee.name
		new_wp.parenttype = "Employee"
		new_wp.parentfield = "custom_workplans"
		self.employee.append("custom_workplans", new_wp)
		self.employee.save()

		self.assertAlmostEqual(calc_allocation_value(self.employee, date), 9, 1)
		print(calc_allocation_value(self.employee, date))

	def test_workplan_not_to_end(self):
		date = getdate("2026-01-01")
		last_day = getdate("2026-06-30")
		self.employee.custom_workplans[0].end = last_day
		self.assertAlmostEqual(calc_allocation_value(self.employee, date), 6, 1)
		print(calc_allocation_value(self.employee, date))

	def test_workplan_not_from_start(self):
		last_day = getdate("2026-07-01")
		self.employee.custom_workplans[0].start = last_day
		self.assertAlmostEqual(calc_allocation_value(self.employee, last_day), 6, 1)
		print(calc_allocation_value(self.employee, last_day))

	def test_start_in_future(self):
		date = getdate("2026-01-01")
		last_day = getdate("2026-07-01")
		self.employee.custom_workplans[0].start = last_day
		self.assertAlmostEqual(calc_allocation_value(self.employee, date), 6, 1)
		print(calc_allocation_value(self.employee, last_day))

	def test_pause_between_wp(self):
		date = getdate("2026-01-01")
		last_day = getdate("2026-03-31")
		first_day = getdate("2026-07-01")
		self.employee.custom_workplans[0].end = last_day

		new_wp = frappe.get_doc(
			{
				"doctype": "Workplan",
				"start": first_day,
				"policy": self.policy1.name,
				"monday": 8,
				"tuesday": 8,
				"wednesday": 8,
				"thursday": 8,
				"friday": 8,
			}
		)
		new_wp.parent = self.employee.name
		new_wp.parenttype = "Employee"
		new_wp.parentfield = "custom_workplans"
		self.employee.append("custom_workplans", new_wp)
		self.employee.save()

		self.assertAlmostEqual(calc_allocation_value(self.employee, date), 9, 1)
		print((self.employee, date))
