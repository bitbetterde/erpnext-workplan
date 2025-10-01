import frappe

from workplan.workplan.overrides.leave_allocation_new import (
	update_all_allocations,
)


# cronjob auf 1.1.
def allocate_all_next_year():
	employees = frappe.get_all("Employee", filters={"status": "Active"})
	for e in employees:
		employee_doc = frappe.get_doc("Employee", e.name)
		update_all_allocations(employee_doc, None)
