import frappe
from frappe.utils import add_days, getdate


def update_all_allocations(employee_doc, method):
	if getattr(frappe.local, "workplan_patch_running", False):
		return
	today = getdate()
	next_year = today.year + 1
	first_day_next_year = getdate(f"{next_year}-01-01")
	leave_type = "Casual Leave"
	update_allocation_for_year(employee_doc, leave_type, today)
	update_allocation_for_year(employee_doc, leave_type, first_day_next_year)


def update_allocation_for_year(employee_doc, leave_type, date):
	new_allocation_value = calc_new_allocation_value(employee_doc, leave_type, date)
	allocation_name = get_allocation_name(employee_doc.name, leave_type, date)
	if allocation_name:
		update_allocation(allocation_name, new_allocation_value)
	elif new_allocation_value:
		if new_allocation_value:
			insert_new_allocation(employee_doc.name, leave_type, new_allocation_value, date.year)
		allocate_other_doctypes(employee_doc.name, date, leave_type)


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


def update_allocation(allocation_name, new_allocated_value):
	allocation_doc = frappe.get_doc("Leave Allocation", allocation_name)
	allocation_doc.new_leaves_allocated = new_allocated_value
	allocation_doc.save()


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


def get_current_days_allocated(employee_doc, leave_type, date):
	allocation_name = get_allocation_name(employee_doc.name, leave_type, date)
	if allocation_name:
		allocation_doc = frappe.get_doc("Leave Allocation", allocation_name)
		return allocation_doc.new_leaves_allocated
	return 0


def calc_share_of_year(start, end):
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
	return details[0].annual_allocation


def resolve_end(end, year):
	if end:
		return end
	return getdate(f"{year}-12-31")


def calc_sum_from_day(employee_doc, start_day):
	days_allocated = 0
	last_day = getdate(f"{start_day.year}-12-31")
	workplan = get_current_workplan(employee_doc, start_day)
	if not workplan:
		workplan = get_next_workplan(employee_doc, start_day)
	if workplan:
		end = resolve_end(workplan.end, start_day.year)
		while workplan and getdate(workplan.start) <= last_day:
			start = getdate(workplan.start)
			if start < start_day:
				start = start_day
			end = resolve_end(workplan.end, start_day.year)
			work_hours = calc_workplan_sum(workplan)
			if add_days(getdate(end), 1).year != start_day.year:
				time_share = calc_share_of_year(start, last_day)
			else:
				time_share = calc_share_of_year(start, end)

			days_allocated_in_time = (
				time_share * get_policy_value(workplan, "Casual Leave") * (work_hours / 40)
			)
			days_allocated += days_allocated_in_time
			workplan = get_next_workplan(employee_doc, end)

	return days_allocated


def calc_new_allocation_value(doc, leave_type, day):
	old = doc.get_doc_before_save()
	if old:
		old_allocation_value_rest_of_year = calc_sum_from_day(old, day)
	else:
		old_allocation_value_rest_of_year = 0
	old_allocation_sum = get_current_days_allocated(doc, leave_type, day)

	new_allocation_value = calc_sum_from_day(doc, day)

	change = new_allocation_value - old_allocation_value_rest_of_year
	new_allocation_sum = old_allocation_sum + change

	# print(old_allocation_value_rest_of_year)
	# print(new_allocation_value)
	# print(old_allocation_sum)
	# print(new_allocation_sum)
	# print(change)
	return new_allocation_sum


def calc_workplan_sum(workplan) -> float:
	return sum([workplan.monday, workplan.tuesday, workplan.wednesday, workplan.thursday, workplan.friday])


def allocate_other_doctypes(employee_name, date, excluded_leave_type):
	leave_types = frappe.get_all("Leave Type")
	for lt in leave_types:
		if (
			lt != excluded_leave_type
			and not get_allocation_name(employee_name, lt.name, date)
			and not lt.name == "Leave Without Pay"
		):
			insert_new_allocation(employee_name, lt.name, 0, date.year)
			insert_new_allocation(employee_name, lt.name, 0, date.year + 1)
