import frappe
from frappe.utils import getdate
from frappe.utils.fixtures import sync_fixtures

from workplan.workplan.overrides.leave_allocation_new import (
	update_allocation_for_year,
)


# 55 ohne workplan oder stunden 0, 60(!) ohne policy fuer vacation
def execute():
	sync_fixtures()
	leave_types = frappe.get_all("Leave Type")
	for lt in leave_types:
		leave_type_doc = frappe.get_doc("Leave Type", lt)
		if lt == "Vacation":
			leave_type_doc.custom_automatic_allocation_calculation_ = 1
			leave_type_doc.custom_automatic_allocation = 1
		elif leave_type_doc.is_compensatory == 1:
			leave_type_doc.custom_automatic_allocation = 1
		leave_type_doc.save()

	frappe.local.workplan_patch_running = True
	print("Migrating Workplans")
	# for all employees
	#   insert workplan to custom_workplans
	current_year = getdate().year
	first_day_next_year = getdate(f"{current_year + 1}-01-01")
	first_day_this_year = getdate(f"{current_year}-01-01")
	leave_types = frappe.get_all("Leave Type")
	leave_type = "Vacation"
	employees = frappe.get_all("Employee", filters={"status": "Active"})
	for e in employees:
		employee_doc = frappe.get_doc("Employee", e.name)
		work_hours = sum(
			[
				employee_doc.custom_monday,
				employee_doc.custom_tuesday,
				employee_doc.custom_wednesday,
				employee_doc.custom_thursday,
				employee_doc.custom_friday,
			]
		)
		# nur anlegen wenn es workplan gibt mit workhours > 0 und es eine policy gibt
		policy = get_leave_policy(e.name, leave_type)
		if work_hours and policy:
			employee_doc = frappe.get_doc("Employee", e.name)
			if not employee_doc.custom_workplans:
				employee_doc.append(
					"custom_workplans",
					{
						"start": first_day_this_year,
						"policy": policy,
						"monday": employee_doc.custom_monday,
						"tuesday": employee_doc.custom_tuesday,
						"wednesday": employee_doc.custom_wednesday,
						"thursday": employee_doc.custom_thursday,
						"friday": employee_doc.custom_friday,
					},
				)
				employee_doc.save()

		today = getdate()
		update_allocation_for_year(employee_doc, first_day_next_year, today)

		frappe.local.workplan_patch_running = False


def get_leave_policy(employee, leave_type):
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
		(employee, leave_type, today),
		as_dict=True,
	)
	if assignments:
		return assignments[0].name
	return None
