import frappe
from frappe.utils import add_days, getdate
from hrms.hr.doctype.leave_allocation.leave_allocation import get_unused_leaves


def update_all_allocations(employee_doc, method):
	if getattr(frappe.local, "workplan_patch_running", False):
		return
	today = getdate()
	next_year = today.year + 1
	first_day_next_year = getdate(f"{next_year}-01-01")
	first_day_this_year = getdate(f"{today.year}-01-01")
	update_allocation_for_year(employee_doc, first_day_this_year, today)
	update_allocation_for_year(employee_doc, first_day_next_year, today)


def update_allocation_for_year(employee_doc, first_day_of_year_date, today):
	last_day_of_year_date = getdate(f"{first_day_of_year_date.year}-12-31")
	last_day_last_year_date = getdate(f"{first_day_of_year_date.year-1}-12-31")
	leave_types = frappe.get_all("Leave Type")
	for lt in leave_types:
		leave_type_doc = frappe.get_doc("Leave Type", lt.name)
		if leave_type_doc.custom_automatic_allocation and leave_type_doc.is_lwp != 1:
			allocation_name = get_allocation_name(
				employee_doc.name, leave_type_doc.name, last_day_of_year_date
			)
			if leave_type_doc.custom_automatic_allocation_calculation_:
				new_allocation_value = calc_allocation_value(
					employee_doc, first_day_of_year_date, leave_type_doc.name
				)
				if new_allocation_value:
					update_allocation(
						allocation_name,
						new_allocation_value,
						employee_doc.name,
						leave_type_doc.name,
						first_day_of_year_date.year,
					)
				else:
					# no allocation leads to deletion
					frappe.delete_doc("Leave Allocation", allocation_name)
			else:
				if leave_type_doc.is_carry_forward and first_day_of_year_date.year == today.year:
					carry_forward_days = get_carry_forward_days(
						employee_doc, leave_type_doc.name, last_day_last_year_date
					)
					update_allocation(
						allocation_name,
						carry_forward_days,
						employee_doc.name,
						leave_type_doc.name,
						first_day_of_year_date.year,
					)
				else:
					update_allocation(
						allocation_name,
						0,
						employee_doc.name,
						leave_type_doc.name,
						first_day_of_year_date.year,
					)


def get_carry_forward_days(employee_doc, leave_type, carry_forward_from_date):
	from_allocation_name = get_allocation_name(employee_doc.name, leave_type, carry_forward_from_date)
	if from_allocation_name:
		from_allocation_doc = frappe.get_doc("Leave Allocation", from_allocation_name)
		return get_unused_leaves(
			employee_doc.name, leave_type, from_allocation_doc.from_date, from_allocation_doc.to_date
		)
	return 0


def insert_new_allocation(employee_name, leave_type, allocation_value, year):
	end = getdate(f"{year}-12-31")
	start = getdate(f"{year}-01-01")
	allocation_doc = frappe.get_doc(
		{
			"doctype": "Leave Allocation",
			"employee": employee_name,
			"leave_type": leave_type,
			"from_date": start,
			"to_date": end,
			"total_leaves_allocated": allocation_value,
			"new_leaves_allocated": allocation_value,
			"docstatus": 1,
		}
	)
	allocation_doc.insert()


def update_allocation(allocation_name, new_allocated_value, employee_name, leave_type, year):
	if allocation_name:
		allocation_doc = frappe.get_doc("Leave Allocation", allocation_name)
		allocation_doc.new_leaves_allocated = new_allocated_value
		allocation_doc.save()
	else:
		insert_new_allocation(employee_name, leave_type, new_allocated_value, year)


def get_allocation_name(employee_name, leave_type, date):
	allocations = frappe.get_all(
		"Leave Allocation",
		filters={
			"employee": employee_name,
			"leave_type": leave_type,
			"docstatus": 1,
			"from_date": ("<=", date),
			"to_date": (">=", date),
		},
	)
	if allocations:
		return allocations[0].name
	return None


def fraction_of_year(start, end):
	end = getdate(end)
	start = getdate(start)
	days = (end - start).days + 1
	return days / 365


def get_current_workplan(employee_doc, date):
	workplans = employee_doc.custom_workplans
	for w in workplans:
		start = getdate(w.start) if w.start else None
		end = getdate(w.end) if w.end else None
		date = getdate(date)
		if end and start <= date <= end:
			return w
		if start <= date and not end:
			return w
	return None


def get_next_workplan(employee_doc, date):
	date = getdate(date)
	workplans = employee_doc.custom_workplans

	valid_workplans = []
	for w in workplans:
		start = getdate(w.start)
		if start >= date:
			valid_workplans.append((start, w))

	if not valid_workplans:
		return None

	next_workplan = min(valid_workplans, key=lambda x: x[0])[1]
	return next_workplan


def get_policy_value(workplan, leave_type):
	policy = frappe.get_doc("Leave Policy", workplan.policy)
	details = frappe.get_all(
		"Leave Policy Detail",
		filters={
			"parent": policy.name,
			"parenttype": "Leave Policy",
			"parentfield": "leave_policy_details",
			"leave_type": leave_type,
		},
		fields=["annual_allocation"],
	)
	if details:
		return details[0].annual_allocation
	return 0


def resolve_end(end, year):
	if end:
		return end
	return getdate(f"{year}-12-31")


def calc_allocation_value(employee_doc, from_date, leave_type):
	days_allocated = 0
	today = getdate()
	last_day = getdate(f"{from_date.year}-12-31")
	workplan = get_current_workplan(employee_doc, from_date)
	leave_type_doc = frappe.get_doc("Leave Type", leave_type)
	if not workplan:
		workplan = get_next_workplan(employee_doc, from_date)
	if workplan:
		end = resolve_end(workplan.end, from_date.year)
		while workplan and getdate(workplan.start) <= last_day:
			start = getdate(workplan.start)
			if start < from_date:
				start = from_date
			end = resolve_end(workplan.end, from_date.year)
			work_hours = calc_workplan_sum(workplan)
			if add_days(getdate(end), 1).year != from_date.year:
				time_share = fraction_of_year(start, last_day)
			else:
				time_share = fraction_of_year(start, end)

			days_allocated_in_workplan = (
				time_share * get_policy_value(workplan, leave_type) * (work_hours / 40)
			)
			days_allocated += days_allocated_in_workplan
			workplan = get_next_workplan(employee_doc, end)

	allocation_name = get_allocation_name(employee_doc.name, leave_type_doc.name, last_day)

	allocation_doc = None
	if allocation_name:
		allocation_doc = frappe.get_doc("Leave Allocation", allocation_name)

	# if the allocation has carry_forward already set (only human created allocations) no additional carry forward is set
	if (
		leave_type_doc.is_carry_forward
		and from_date.year == today.year
		and not (allocation_doc and allocation_doc.carry_forward == 1)
	):
		last_day_last_year = getdate(f"{from_date.year-1}-12-31")
		carry_forward_days = get_carry_forward_days(employee_doc, leave_type, last_day_last_year)
		days_allocated += carry_forward_days

	if days_allocated:
		return days_allocated
	return 0


def calc_workplan_sum(workplan) -> float:
	return sum([workplan.monday, workplan.tuesday, workplan.wednesday, workplan.thursday, workplan.friday])
