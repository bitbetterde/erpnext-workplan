import frappe
from frappe.utils import getdate


def validate_workplans(doc, method):
	check_end_after_start(doc)
	check_workplan_overlaps(doc)
	check_future_workplan_starts(doc)


def check_workplan_overlaps(doc):
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


def check_future_workplan_starts(doc):
	today = getdate()
	for wp in doc.custom_workplans:
		if wp.is_new():
			start = getdate(wp.start)
			if start < today:
				frappe.throw(f"Neuer Workplan darf frühestens ab heute ({today}) starten.")


def check_end_after_start(doc):
	for wp in doc.custom_workplans:
		if wp.end:
			if wp.start > wp.end:
				frappe.throw(
					"Ende eines Workplans darf nicht vor dem Start sein. Ein offenes Ende ist möglich, indem das Feld leer 'End' bleibt."
				)
