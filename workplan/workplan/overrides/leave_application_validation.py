import frappe
from frappe import _
from frappe.utils import add_days, getdate
from hrms.hr.doctype.leave_application.leave_application import (
	InsufficientLeaveBalanceError,
	LeaveApplication,
	get_leave_allocation_records,
	set_employee_name,
	validate_active_employee,
)

from workplan.workplan.overrides.leave_allocation_new import get_current_workplan


class CustomLeaveApplication(LeaveApplication):
	def show_insufficient_balance_message(self, leave_balance_for_consumption: float) -> None:
		allocation = get_leave_allocation_records(self.employee, self.from_date, self.leave_type)
		if allocation[self.leave_type] and allocation[self.leave_type].total_leaves_allocated == 0:
			return
		# core show_insufficient_balance_message function
		alloc_on_from_date, alloc_on_to_date = self.get_allocation_based_on_application_dates()

		if frappe.db.get_value("Leave Type", self.leave_type, "allow_negative"):
			if leave_balance_for_consumption != self.leave_balance:
				msg = _("Warning: Insufficient leave balance for Leave Type {0} in this allocation.").format(
					frappe.bold(self.leave_type)
				)
				msg += "<br><br>"
				msg += _(
					"Actual balances aren't available because the leave application spans over different leave allocations. You can still apply for leaves which would be compensated during the next allocation."
				)
			else:
				msg = frappe._("Warning: Insufficient leave balance for Leave Type {0}.").format(
					frappe.bold(self.leave_type)
				)

			frappe.msgprint(msg, title=_("Warning"), indicator="orange")
		else:
			frappe.throw(
				frappe._("Insufficient leave balance for Leave Type {0}").format(
					frappe.bold(self.leave_type)
				),
				exc=InsufficientLeaveBalanceError,
				title=_("Insufficient Balance"),
			)

	def validate(self):
		# custom validate function
		self.validate_active_workplan()

		# core validate functions
		validate_active_employee(self.employee)
		set_employee_name(self)
		self.validate_dates()
		self.validate_balance_leaves()
		self.validate_leave_overlap()
		self.validate_max_days()
		self.show_block_day_warning()
		self.validate_block_days()
		self.validate_salary_processed_days()
		self.validate_attendance()
		self.set_half_day_date()
		if frappe.db.get_value("Leave Type", self.leave_type, "is_optional_leave"):
			self.validate_optional_leave()
		self.validate_applicable_after()

	def validate_active_workplan(self):
		employee = frappe.get_doc("Employee", self.employee)

		date = self.from_date
		workplan = get_current_workplan(employee, date)
		while workplan:
			if not workplan.end:
				return
			if getdate(workplan.end) >= getdate(self.to_date):
				return
			date = add_days(workplan.end, 1)
			workplan = get_current_workplan(employee, date)

		frappe.throw("Der gewählte Zeitraum darf nicht ausserhalb von Workplans liegen.")
