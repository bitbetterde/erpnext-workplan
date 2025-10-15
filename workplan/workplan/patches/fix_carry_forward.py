import frappe
from frappe.utils import getdate

from workplan.workplan.overrides.leave_allocation_new import update_allocation_for_year


def execute():
	employees = frappe.get_all("Employee")
	for employee in employees:
		employee_doc = frappe.get_doc("Employee", employee)
		if employee_doc.custom_workplans:
			today = getdate()
			first_day_this_year = getdate(f"{today.year}-01-01")
			update_allocation_for_year(employee_doc, first_day_this_year, today)
