import frappe
from frappe import _
from hrms.hr.doctype.leave_application.leave_application import (
	InsufficientLeaveBalanceError,
	LeaveApplication,
	get_leave_allocation_records,
)


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
				msg = _("Warning: Insufficient leave balance for Leave Type {0}.").format(
					frappe.bold(self.leave_type)
				)

			frappe.msgprint(msg, title=_("Warning"), indicator="orange")
		else:
			frappe.throw(
				_("Insufficient leave balance for Leave Type {0}").format(frappe.bold(self.leave_type)),
				exc=InsufficientLeaveBalanceError,
				title=_("Insufficient Balance"),
			)
