import frappe
from frappe.utils import flt, getdate
from hrms.hr.doctype.leave_application.leave_application import get_approved_leaves_for_period

from workplan.workplan.overrides.leave_allocation_new import calc_new_allocation_value, get_allocation_name


def validate_workplans(doc, method):
	validate_end_after_start(doc)
	validate_workplan_overlaps(doc)
	validate_future_workplan_starts(doc)
	validate_used_days(doc)


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
				frappe.throw(
					f"Workplan-Zeiträume überschneiden sich: " f"({start}–{end}) und ({start2}–{end2})"
				)


def validate_future_workplan_starts(doc):
	today = getdate()
	for wp in doc.custom_workplans:
		if wp.is_new():
			start = getdate(wp.start)
			if start < today:
				frappe.throw(f"Neuer Workplan darf frühestens ab heute ({today}) starten.")


def validate_end_after_start(doc):
	for wp in doc.custom_workplans:
		if wp.end:
			if wp.start > wp.end:
				frappe.throw(
					"Ende eines Workplans darf nicht vor dem Start sein. Ein offenes Ende ist möglich, indem das Feld leer 'End' bleibt."
				)


def validate_used_days(doc):
	today = getdate()
	leave_type = "Casual Leave"
	current_year = getdate().year
	from_date = getdate(f"{current_year}-01-01")
	to_date = getdate(f"{current_year}-12-31")
	leaves_taken = get_approved_leaves_for_period(doc.name, leave_type, from_date, to_date)
	new_allocation = calc_new_allocation_value(doc, leave_type, today)
	print(new_allocation)
	if flt(leaves_taken) > flt(new_allocation):
		frappe.throw(
			frappe._(
				"Total allocated leaves {0} cannot be less than already approved leaves {1} for the period"
			).format(new_allocation, leaves_taken),
		)
