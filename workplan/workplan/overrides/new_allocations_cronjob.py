import frappe
from frappe.utils import getdate

from workplan.workplan.overrides.leave_allocation_new import (
	get_allocation_name,
	get_current_days_allocated,
	insert_new_allocation,
	update_allocation,
	update_allocation_for_year,
)


# cronjob auf 1.1.
def allocate_all_next_year():
	frappe.utils.logger.set_log_level("DEBUG")
	logger = frappe.logger("workplan")

	logger.info(" Test Cronjob wurde gestartet veraenderter string")
	# leave_type = 'Casual Leave'
	# next_year = getdate().year + 2
	# first_day_next_year = getdate(f"{next_year}-01-01")
	# today = getdate(f"{next_year-1}-01-01")
	# last_day_last_year = getdate(f"{next_year-2}-12-31")
	# leave_types = frappe.get_all('Leave Type')
	# employees = frappe.get_all('Employee')
	# for e in employees:
	#     employee_doc = frappe.get_doc('Employee', e.name)
	#     # update_allocation_for_year(employee_doc, leave_type, first_day_next_year)
	#     # carry_forward_allocation(employee_doc, leave_type, today, last_day_last_year)
	#     for lt in leave_types:
	#         if lt.name != leave_type:
	#             simple_allocate_for_year(employee_doc, lt.name, next_year, today, last_day_last_year)


def simple_allocate_for_year(employee_doc, leave_type, next_year, today, last_day_last_year):
	insert_new_allocation(employee_doc.name, leave_type, 0, next_year)
	carry_forward_allocation(employee_doc, leave_type, today, last_day_last_year)


def carry_forward_allocation(employee_doc, leave_type, today, last_day_last_year):
	allocation_doc = get_allocation_name(employee_doc.name, leave_type, today)
	current_days_allocated = get_current_days_allocated(employee_doc, leave_type, today)
	days_past_allocation = get_unused_days_allocated(employee_doc, leave_type, last_day_last_year)
	if allocation_doc:
		update_allocation(allocation_doc, current_days_allocated + days_past_allocation)


def get_unused_days_allocated(employee_doc, leave_type, date):
	allocation_name = get_allocation_name(employee_doc.name, leave_type, date)
	if allocation_name:
		allocation_doc = frappe.get_doc("Leave Allocation", allocation_name)
		return allocation_doc.unused_leaves
	return 0
