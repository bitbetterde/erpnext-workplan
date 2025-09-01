import uuid

import frappe
import frappe.utils
from frappe.utils import getdate

from workplan.workplan.overrides.leave_allocation_new import (
	allocate_other_doctypes,
	get_allocation_name,
	insert_new_allocation,
	update_allocation_for_year,
)


def execute():
	if getattr(frappe.local, "workplan_patch_running", False):
		return
	print("Migrating Workplans")
	# for all employees
	#   insert workplan to custom_workplans
	next_year = getdate().year + 1
	first_day_next_year = getdate(f"{next_year}-01-01")
	leave_types = frappe.get_all("Leave Type")

	employees = frappe.get_all("Employee")
	for e in employees:
		frappe.local.workplan_patch_running = True
		today = getdate()
		leave_type = "Casual Leave"
		employee_doc = frappe.get_doc("Employee", e.name)
		policy = get_leave_policy(e.name, leave_type)

		if policy:
			employee_doc.append(
				"custom_workplans",
				{
					"start": today,
					"policy": policy,
					"monday": employee_doc.custom_monday,
					"tuesday": employee_doc.custom_tuesday,
					"wednesday": employee_doc.custom_wednesday,
					"thursday": employee_doc.custom_thursday,
					"friday": employee_doc.custom_friday,
				},
			)
			employee_doc.save()

		update_allocation_for_year(employee_doc, leave_type, first_day_next_year)
		for lt in leave_types:
			if lt.name != leave_type:
				allocation_name = get_allocation_name(employee_doc.name, leave_type, first_day_next_year)
				if not allocation_name:
					insert_new_allocation(employee_doc.name, leave_type, 0, next_year)
		frappe.local.workplan_patch_running = False


def get_leave_policy(employee, leave_policy):
	today = getdate()
	assignments = frappe.db.sql(
		"""
        SELECT lp.name
        FROM `tabEmployee` e
        JOIN `tabLeave Policy Assignment` lpa
            ON lpa.employee = e.name
        JOIN `tabLeave Policy` lp
            ON lpa.leave_policy = lp.name
        JOIN `tabLeave Policy Detail` lpd
            ON lpd.parent = lp.name
        WHERE e.name = %s
        AND lpd.leave_type = %s
        AND lpa.docstatus = 1
        AND %s BETWEEN lpa.effective_from AND lpa.effective_to;
        """,
		(employee, leave_policy, today),
		as_dict=True,
	)
	if assignments:
		return assignments[0].name
	return None
