import frappe
from frappe.utils import add_days, getdate
from hrms.hr.doctype.leave_application.leave_application import (
	LeaveApplication,
	set_employee_name,
	validate_active_employee,
)

from workplan.workplan.overrides.leave_allocation_new import get_current_workplan


class CustomLeaveApplication(LeaveApplication):
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
			if getdate(workplan.end) >= getdate(self.to_date):
				return
			date = add_days(workplan.end, 1)
			workplan = get_current_workplan(employee, date)

		frappe.throw("Der gewählte Zeitraum darf nicht ausserhalb von Workplans liegen.")
