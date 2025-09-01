from hrms.hr.doctype.leave_allocation.leave_allocation import LeaveAllocation


class CustomLeaveAllocation(LeaveAllocation):
	def validate_against_leave_applications(self):
		return
