import datetime

import frappe
from frappe import _, cint
from frappe.utils import add_days, flt, getdate
from hrms.hr.doctype.leave_application.leave_application import (
	InsufficientLeaveBalanceError,
	LeaveApplication,
	get_leave_allocation_records,
	get_leave_balance_on,
	is_lwp,
	set_employee_name,
	validate_active_employee,
)

from workplan.workplan.overrides.leave_allocation_new import get_current_workplan
from workplan.workplan.overrides.leave_application import (
	get_number_of_leave_days,
	get_number_of_leave_days_leave_application,
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

	def validate_balance_leaves(self):
		precision = cint(frappe.db.get_single_value("System Settings", "float_precision")) or 2

		if self.from_date and self.to_date:
			# calculates with workplan but without possible fractional leave day
			chosen_leave_days = get_number_of_leave_days(
				self.employee,
				self.leave_type,
				self.from_date,
				self.to_date,
				self.half_day,
				self.half_day_date,
			)

			if chosen_leave_days <= 0:
				frappe.throw(
					_(
						"The day(s) on which you are applying for leave are holidays. You need not apply for leave."
					)
				)

			fractional_leave_days = get_number_of_leave_days_leave_application(
				self.employee,
				self.leave_type,
				self.from_date,
				self.to_date,
				self.half_day,
				self.half_day_date,
			)["total_leave_days"]

			chosen_leave_days = flt(chosen_leave_days, 3)
			client_total_leave_days = flt(self.total_leave_days, 3)
			# client must have set total_leave_days to one of the valid values
			valid_totals = {chosen_leave_days}
			if fractional_leave_days is not None:
				valid_totals.add(flt(fractional_leave_days, 3))

			if client_total_leave_days not in valid_totals:
				frappe.throw(_("Something went wrong. Please try again."))

			if not is_lwp(self.leave_type):
				leave_balance = get_leave_balance_on(
					self.employee,
					self.leave_type,
					self.from_date,
					self.to_date,
					consider_all_leaves_in_the_allocation_period=True,
					for_consumption=True,
				)
				leave_balance_for_consumption = flt(
					leave_balance.get("leave_balance_for_consumption"), precision
				)
				if self.status != "Rejected" and (
					leave_balance_for_consumption < self.total_leave_days or not leave_balance_for_consumption
				):
					self.show_insufficient_balance_message(leave_balance_for_consumption)

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
		self.validate_for_self_approval()

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
