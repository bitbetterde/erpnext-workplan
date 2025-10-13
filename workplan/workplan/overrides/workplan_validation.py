import frappe
from frappe.utils import flt, getdate
from hrms.hr.doctype.leave_application.leave_application import get_approved_leaves_for_period

from workplan.workplan.overrides.leave_allocation_new import (
	calc_allocation_value,
	get_current_workplan,
	get_next_workplan,
	resolve_end,
)
from workplan.workplan.overrides.leave_application import (
	get_number_of_leave_day_for_employee_doc,
	get_number_of_leave_days,
	get_number_of_leave_days_for_workplan,
)


def validate_workplans(doc, method):
	validate_end_after_start(doc)
	validate_workplan_overlaps(doc)
	validate_used_days(doc)
	validate_workplan_changes(doc)


def validate_workplan_overlaps(doc):
	workplans = sorted(doc.custom_workplans, key=lambda w: getdate(w.start))

	for i, wp in enumerate(workplans):
		start = getdate(wp.start)
		end = getdate(wp.end) if wp.end else None

		if not end:
			end = getdate("9999-12-31")

		for j in range(i + 1, len(workplans)):
			wp2 = workplans[j]
			start2 = getdate(wp2.start)
			end2 = getdate(wp2.end) if wp2.end else None
			if not end2:
				end2 = getdate("9999-12-31")

			if (start <= end2) and (start2 <= end):
				frappe.throw(f"Work plan periods overlap: " f"({start}–{end}) and ({start2}–{end2})")


def validate_end_after_start(doc):
	for wp in doc.custom_workplans:
		if wp.end:
			if wp.start > wp.end:
				frappe.throw(
					"End of a work plan cannot be before start. An open end is possible by leaving the field 'End' empty."
				)


def validate_used_days(doc):
	leave_types = frappe.get_all("Leave Type")
	for lt in leave_types:
		leave_type_doc = frappe.get_doc("Leave Type", lt.name)
		if (
			leave_type_doc.custom_automatic_allocation
			and leave_type_doc.custom_automatic_allocation_calculation_
		):
			validate_used_days_for_year(doc, getdate().year, leave_type_doc.name)
			validate_used_days_for_year(doc, getdate().year + 1, leave_type_doc.name)


def validate_used_days_for_year(doc, year, leave_type):
	from_date = getdate(f"{year}-01-01")
	to_date = getdate(f"{year}-12-31")

	applications = frappe.get_all(
		"Leave Application",
		filters={
			"employee": doc.name,
			"from_date": (">=", from_date),
			"to_date": ("<=", to_date),
			"leave_type": leave_type,
			"docstatus": "1",
		},
		fields=["name", "from_date", "to_date", "leave_type", "total_leave_days"],
	)
	if not applications:
		return

	leaves_taken = 0
	for application in applications:
		leaves_taken += get_number_of_leave_day_for_employee_doc(
			doc, leave_type, application.from_date, application.to_date
		)

	new_allocation = calc_allocation_value(doc, from_date, leave_type)
	if flt(leaves_taken) > flt(new_allocation):
		frappe.throw(
			frappe._(
				"Total allocated leave days for workplans {0} cannot be less than already approved leaves {1} for the period"
			).format(new_allocation, leaves_taken),
		)


def validate_workplan_changes(doc):
	current_year = getdate().year
	old_doc = doc.get_doc_before_save()
	new_wps = {wp.name: wp for wp in doc.custom_workplans}

	if old_doc:
		old_wps = {wp.name: wp for wp in old_doc.custom_workplans}

		for name, new_wp in new_wps.items():
			if old_doc:
				old_wp = old_wps.get(name)

			# start for new workplan
			if not old_wp:
				if getdate(new_wp.start).year < current_year:
					frappe.throw(
						f"{name}: Start Date of new worplan is {new_wp.start} but cannot be before {current_year}."
					)
				continue

			# start
			if getdate(new_wp.start) != getdate(old_wp.start):
				if getdate(old_wp.start).year < current_year:
					frappe.throw(
						f"Start date cannot be changed because the old start date {old_wp.start} is before  {current_year}."
					)
				if getdate(new_wp.start).year < current_year:
					frappe.throw(f"New start date {new_wp.start} cannot be before {current_year}.")

			# end
			if getdate(new_wp.end) != getdate(old_wp.end):
				if old_wp.end:
					if getdate(old_wp.end).year < current_year:
						frappe.throw(
							f"End date cannot be changed to {new_wp.end} because the old end date is before {current_year}."
						)
				else:
					if new_wp.end:
						if getdate(new_wp.end) < getdate(f"{current_year-1}-12-31"):
							frappe.throw(
								f"End date {new_wp.end} is not possible. Earliest possible end date is {current_year-1}-12-31."
							)

			# hours
			weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday"]
			for day in weekdays:
				if getattr(old_wp, day) != getattr(new_wp, day):
					if getdate(old_wp.start).year < current_year:
						frappe.throw(f"Workhours before {current_year} cannot be changed.")
					break

		# deleted
		for name, old_wp in old_wps.items():
			if name not in new_wps:
				if getdate(old_wp.start).year < current_year:
					frappe.throw(
						f"Workplan with start date {old_wp.start} cannot be deleted because start date is before {current_year}."
					)
	else:
		for name, new_wp in new_wps.items():
			if getdate(new_wp.start).year < current_year:
				frappe.throw(
					f"{name}: Start Date of new worplan is {new_wp.start} but cannot be before {current_year}."
				)
