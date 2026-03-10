import datetime
import math

import frappe
import hrms
from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee
from frappe.utils import add_days, cint, date_diff, flt, getdate
from hrms.hr.doctype.leave_application.leave_application import (
	get_allocation_expiry_for_cf_leaves,
	get_leave_balance_on,
	get_leave_entries,
	get_leaves_pending_approval_for_period,
)
from hrms.hr.doctype.leave_ledger_entry.leave_ledger_entry import create_leave_ledger_entry
from hrms.utils.holiday_list import get_holiday_dates_between

from workplan.workplan.overrides.leave_allocation_new import get_current_workplan, get_next_workplan


def get_number_of_leave_working_days(
	employee: str,
	leave_type: str,
	from_date: datetime.date,
	to_date: datetime.date,
) -> float:
	"""Returns number of leave days between 2 dates after considering holidays
	(Based on the include_holiday setting in Leave Type). Does not consider wether the employee actually works on the days as per their workplan"""

	print(f"get_number_of_leave_days {employee} {leave_type} {from_date} {to_date}")
	number_of_weekdays = get_weekdays_diff(from_date, to_date)

	print(f"number_of_weekdays {number_of_weekdays} {from_date} { to_date}")

	if not frappe.db.get_value("Leave Type", leave_type, "include_holiday"):
		print(f"Leave Type {leave_type} not includes holidays as leaves")
		holiday_list_local = get_holiday_list_for_employee(employee)
		holidays_between_from_to: list[datetime.date] = get_holiday_dates_between(
			holiday_list_local, from_date.isoformat(), to_date.isoformat()
		)
		for holiday in holidays_between_from_to:
			number_of_weekdays[holiday.weekday()] = (
				number_of_weekdays[holiday.weekday()] - 1 if number_of_weekdays[holiday.weekday()] > 0 else 0
			)
	else:
		print(f"Leave Type {leave_type} includes holidays as leaves")
	return number_of_weekdays


def get_number_of_leave_days_for_workplan(
	employee_doc,
	leave_type: str,
	from_date: datetime.date,
	to_date: datetime.date,
	workplan,
) -> float:
	"""Returns number of leave days between 2 dates after considering half day and holidays
	(Based on the include_holiday setting in Leave Type)"""

	print(f"get_number_of_leave_days {employee_doc.name} {leave_type} {from_date} {to_date}")
	number_of_weekdays = get_weekdays_diff(from_date, to_date)

	print(f"number_of_weekdays {number_of_weekdays} {from_date} { to_date}")

	if not frappe.db.get_value("Leave Type", leave_type, "include_holiday"):
		print(f"Leave Type {leave_type} not includes holidays as leaves")
		holiday_list_local = get_holiday_list_for_employee(employee_doc.name)
		holidays_between_from_to: list[datetime.date] = get_holiday_dates_between(
			holiday_list_local, from_date.isoformat(), to_date.isoformat()
		)
		for holiday in holidays_between_from_to:
			number_of_weekdays[holiday.weekday()] = (
				number_of_weekdays[holiday.weekday()] - 1 if number_of_weekdays[holiday.weekday()] > 0 else 0
			)
	else:
		print(f"Leave Type {leave_type} includes holidays as leaves")

	sum_working_hours = 0
	for i, days in enumerate(number_of_weekdays):
		match i:
			case 0:
				sum_working_hours += workplan.monday * days
			case 1:
				sum_working_hours += workplan.tuesday * days
			case 2:
				sum_working_hours += workplan.wednesday * days
			case 3:
				sum_working_hours += workplan.thursday * days
			case 4:
				sum_working_hours += workplan.friday * days

	existing_leave_application = frappe.get_all(
		"Leave Application",
		filters={
			"from_date": from_date,
			"to_date": to_date,
			"employee": employee_doc.name,
			"status": ["in", ["Draft", "Open", "Pending", "Approved"]],
		},
	)

	if existing_leave_application:
		leave_application_doc = frappe.get_doc("Leave Application", existing_leave_application[0])
		work_hours, _ = get_last_workday_with_hours(employee_doc, from_date, to_date)

		# fractional leave >= work_hours that day
		if (flt(leave_application_doc.custom_fractional_day_value) * 8) >= work_hours:
			return sum_working_hours / 8

		if flt(leave_application_doc.custom_fractional_day_value) > 0:
			return (
				sum_working_hours / 8
				- work_hours / 8
				+ flt(leave_application_doc.custom_fractional_day_value)
			)
	return sum_working_hours / 8


@frappe.whitelist()
def get_fractional_leave_details(
	employee: str, leave_type: str, from_date: datetime.date, to_date: datetime.date
):
	employee_doc = frappe.get_doc("Employee", employee)
	leave_days_requested = get_number_of_leave_day_for_employee_doc(
		employee_doc, leave_type, from_date, to_date
	)
	leave_balance = get_leave_balance_on(
		employee,
		leave_type,
		from_date,
		to_date,
		consider_all_leaves_in_the_allocation_period=True,
		for_consumption=True,
	)
	leave_balance_for_consumption = flt(leave_balance.get("leave_balance_for_consumption"), 3)

	work_hours, last_workday_date = get_last_workday_with_hours(employee_doc, from_date, to_date)

	date1 = getdate(f"{from_date.year}-01-01")
	date2 = getdate(f"{to_date.year}-12-31")

	pending_approval = get_leaves_pending_approval_for_period(employee, leave_type, date1, date2)

	leave_balance_for_application = leave_balance_for_consumption - pending_approval

	remaining_leave = leave_balance_for_application - leave_days_requested

	# remaining_leave is negative when balance is insufficient (shortfall).
	# (-work_hours / 8) converts the last workday to the same negative scale.
	# If the shortfall is larger than the full last workday, working 0h that day still won't cover it —
	# fractional leave can't help, so bail out.
	if work_hours == 0 or remaining_leave >= 0 or (-work_hours) / 8 > remaining_leave:
		return None, None, None, None

	print(f"Leave Balance Requested {leave_days_requested}")
	print(f"Leave Balance available {leave_balance_for_application}")
	fractional_vacation = work_hours / 8 + leave_balance_for_application - leave_days_requested
	fractional_work = work_hours / 8 - fractional_vacation
	return leave_balance_for_application, fractional_work, last_workday_date, fractional_vacation


def get_last_workday_with_hours(employee_doc, from_date, to_date):
	from_date = getdate(from_date)
	to_date = getdate(to_date)
	date_to_check = to_date
	holiday_list_local = get_holiday_list_for_employee(employee_doc.name)
	holidays_dates: list[datetime.date] = get_holiday_dates_between(holiday_list_local, from_date, to_date)
	holidays_dates_set = set(holidays_dates)

	workplan = get_current_workplan(employee_doc, to_date)

	while date_to_check >= from_date:
		is_weekday = date_to_check.weekday() < 5
		is_holiday = date_to_check in holidays_dates_set

		if is_weekday and not is_holiday:
			work_hours = get_work_hours(employee_doc, date_to_check, workplan)
			if work_hours > 0:
				return work_hours, date_to_check

		if workplan and workplan.end:
			if date_to_check < getdate(workplan.start):
				workplan = get_current_workplan(employee_doc, date_to_check)

		date_to_check = add_days(date_to_check, -1)

	return 0, date_to_check


def get_work_hours(employee_doc, date: datetime.date, workplan=None):
	if not workplan:
		workplan = get_current_workplan(employee_doc, date)

	if not workplan:
		return 0

	weekday = date.weekday()
	match weekday:
		case 0:
			return workplan.monday
		case 1:
			return workplan.tuesday
		case 2:
			return workplan.wednesday
		case 3:
			return workplan.thursday
		case 4:
			return workplan.friday
		case _:
			return 0


@frappe.whitelist()
def get_number_of_leave_days(
	employee: str,
	leave_type: str,
	from_date: datetime.date,
	to_date: datetime.date,
	half_day: int | str | None = None,
	half_day_date: datetime.date | str | None = None,
	holiday_list: str | None = None,
) -> float:
	"""Returns number of leave days between 2 dates after considering half day and holidays
	(Based on the include_holiday setting in Leave Type)"""

	employee_doc = frappe.get_doc("Employee", employee)
	return get_number_of_leave_day_for_employee_doc(employee_doc, leave_type, from_date, to_date)


@frappe.whitelist()
def get_number_of_leave_days_leave_application(
	employee: str,
	leave_type: str,
	from_date: datetime.date,
	to_date: datetime.date,
	half_day: int | str | None = None,
	half_day_date: datetime.date | str | None = None,
	holiday_list: str | None = None,
):
	"""Returns number of leave days between 2 dates after considering half day and holidays
	(Based on the include_holiday setting in Leave Type)"""

	leave_balance, fractional_work, last_workday_date, fractional_vacation = get_fractional_leave_details(
		employee, leave_type, from_date, to_date
	)

	return {
		"fractional_value": fractional_vacation,
		"fractional_work": fractional_work,
		"total_leave_days": leave_balance,
		"date": last_workday_date,
		"weekday": last_workday_date.weekday() if last_workday_date else None,
	}


def get_number_of_leave_day_for_employee_doc(
	employee_doc,
	leave_type: str,
	from_date: datetime.date,
	to_date: datetime.date,
) -> float:
	"""Returns number of leave days between 2 dates after considering half day and holidays
	(Based on the include_holiday setting in Leave Type)"""
	workplan = get_current_workplan(employee_doc, from_date)
	result = 0
	start = from_date
	if not workplan:
		# check if there are actually vacations applied for
		frappe.throw(
			"Workplan for already applied Vacation missing. Cancel the Applications in the Workplan before deleting the Workplan itself."
		)
	if workplan.end:
		while workplan.end and getdate(workplan.end) < to_date:
			result += get_number_of_leave_days_for_workplan(
				employee_doc, leave_type, start, workplan.end, workplan
			)
			workplan = get_next_workplan(employee_doc, workplan.end)
			if not workplan:
				# check if there are actually vacations applied for
				frappe.throw(
					"Workplan for already applied Vacation missing. Cancel the Applications in the Workplan before deleting the Workplan itself."
				)
			start = workplan.start

		result += get_number_of_leave_days_for_workplan(employee_doc, leave_type, start, to_date, workplan)
		return result
	else:
		return get_number_of_leave_days_for_workplan(employee_doc, leave_type, start, to_date, workplan)


def get_weekdays_diff(from_date: datetime.date, to_date: datetime.date):
	from_date = getdate(from_date)
	firstWeekday = from_date.weekday()
	numberOfDays = date_diff(to_date, from_date) + 1
	fullWeeks = int(numberOfDays / 7)
	additionalDays = numberOfDays - (fullWeeks * 7)

	result = [fullWeeks, fullWeeks, fullWeeks, fullWeeks, fullWeeks, fullWeeks, fullWeeks]

	for x in range(additionalDays):
		result[(firstWeekday + x) % 7] += 1

	return result


def update_application_days_value(employee_doc, method):
	# recalculate leave days for every application
	current_year = getdate().year
	first_day_this_year = getdate(f"{current_year}-01-01")
	last_day_next_year = getdate(f"{current_year + 1}-12-31")
	applications = frappe.get_all(
		"Leave Application",
		filters={
			"employee": employee_doc.name,
			"from_date": (">=", first_day_this_year),
			"to_date": ("<=", last_day_next_year),
			"docstatus": ("!=", 2),
			"approval_state": ("!=", "Canceled"),
		},
		fields=[
			"name",
			"from_date",
			"to_date",
			"leave_type",
			"total_leave_days",
			"company",
			"custom_fractional_day_value",
		],
	)
	for application in applications:
		print(
			f"Update applications days value for application from {application.from_date} to {application.to_date}"
		)
		work_hours, date = get_last_workday_with_hours(
			employee_doc, application.from_date, application.to_date
		)

		application_doc = frappe.get_doc("Leave Application", application.name)

		if work_hours / 8 <= flt(application.custom_fractional_day_value):
			application_doc.custom_fractional_day_value = 0
			application_doc.custom_last_workday_date = None
			application_doc.custom_last_workday_weekday = None
			application_doc.custom_hours_to_work = None
			application_doc.custom_minutes_to_work = None
		elif flt(application.custom_fractional_day_value) > 0:
			total_hours = work_hours - flt(application.custom_fractional_day_value) * 8
			application_doc.custom_minutes_to_work = math.floor((total_hours - math.floor(total_hours)) * 60)
			application_doc.custom_hours_to_work = math.floor(total_hours)

		application_doc.save()

		new_total_leave_days = get_number_of_leave_days(
			employee_doc.name, application.leave_type, application.from_date, application.to_date
		)

		ledger_entries = frappe.get_all(
			"Leave Ledger Entry",
			filters={
				"transaction_type": "Leave Application",
				"transaction_name": application.name,
				"employee": employee_doc.name,
				"company": application.company,
				"leave_type": application.leave_type,
				"docstatus": 1,
			},
			fields=["SUM(leaves) as total_leaves"],
		)

		if ledger_entries and ledger_entries[0].total_leaves is not None:
			existing_leave_count = ledger_entries[0].total_leaves
		else:
			existing_leave_count = 0

		frappe.db.set_value("Leave Application", application.name, "total_leave_days", new_total_leave_days)
		leaves_to_be_added = (
			flt(
				(new_total_leave_days + existing_leave_count),
			)
			* -1
		)

		if leaves_to_be_added:
			if application_doc.status != "Approved":
				continue

			expiry_date = get_allocation_expiry_for_cf_leaves(
				application_doc.employee,
				application_doc.leave_type,
				application_doc.to_date,
				application_doc.from_date,
			)
			lwp = frappe.db.get_value("Leave Type", application_doc.leave_type, "is_lwp")

			raise_exception = False if frappe.flags.in_patch else True
			holiday_list = (
				get_holiday_list_for_employee(application_doc.employee, raise_exception=raise_exception) or ""
			)

			if expiry_date:
				split_date = expiry_date
			else:
				(
					alloc_on_from_date,
					alloc_on_to_date,
				) = application_doc.get_allocation_based_on_application_dates()
				if application_doc.is_separate_ledger_entry_required(alloc_on_from_date, alloc_on_to_date):
					split_date = alloc_on_from_date.to_date
				else:
					split_date = None

			if split_date:
				# The application spans two ledger entries (split at expiry date or allocation boundary).
				# We must create per-sub-period delta corrections rather than calling HRMS functions
				# that would recreate full entries on top of the existing ones.
				base_filters = {
					"transaction_type": "Leave Application",
					"transaction_name": application.name,
					"employee": employee_doc.name,
					"leave_type": application.leave_type,
					"docstatus": 1,
				}

				pre_entries = frappe.get_all(
					"Leave Ledger Entry",
					filters={**base_filters, "to_date": ("<=", split_date)},
					fields=["SUM(leaves) as total_leaves"],
				)
				existing_pre = pre_entries[0].total_leaves or 0 if pre_entries else 0

				post_entries = frappe.get_all(
					"Leave Ledger Entry",
					filters={**base_filters, "from_date": (">", split_date)},
					fields=["SUM(leaves) as total_leaves"],
				)
				existing_post = post_entries[0].total_leaves or 0 if post_entries else 0

				fractional_value = flt(application_doc.custom_fractional_day_value)
				# `date` is the last workday with hours, computed above from the updated workplan.
				fractional_in_post = fractional_value > 0 and getdate(date) > getdate(split_date)
				fractional_in_pre = fractional_value > 0 and getdate(date) <= getdate(split_date)

				if fractional_in_post:
					# Fractional day is after the split: calculate pre-expiry directly (safe),
					# derive post-expiry to preserve the fractional component.
					new_pre_days = get_number_of_leave_days(
						employee_doc.name,
						application.leave_type,
						application_doc.from_date,
						split_date,
					)
					new_post_days = new_total_leave_days - new_pre_days
				elif fractional_in_pre:
					# Fractional day is before the split: calculate post-expiry directly (safe),
					# derive pre-expiry to preserve the fractional component.
					new_post_days = get_number_of_leave_days(
						employee_doc.name,
						application.leave_type,
						add_days(split_date, 1),
						application_doc.to_date,
					)
					new_pre_days = new_total_leave_days - new_post_days
				else:
					# No fractional day: both sub-period calls are safe.
					new_pre_days = get_number_of_leave_days(
						employee_doc.name,
						application.leave_type,
						application_doc.from_date,
						split_date,
					)
					new_post_days = get_number_of_leave_days(
						employee_doc.name,
						application.leave_type,
						add_days(split_date, 1),
						application_doc.to_date,
					)

				delta_pre = flt(-(new_pre_days + existing_pre))
				delta_post = flt(-(new_post_days + existing_post))

				if delta_pre:
					create_leave_ledger_entry(
						application_doc,
						dict(
							leaves=delta_pre,
							from_date=application_doc.from_date,
							to_date=split_date,
							is_lwp=lwp,
							holiday_list=holiday_list,
						),
						True,
					)
				if delta_post:
					create_leave_ledger_entry(
						application_doc,
						dict(
							leaves=delta_post,
							from_date=add_days(split_date, 1),
							to_date=application_doc.to_date,
							is_lwp=lwp,
							holiday_list=holiday_list,
						),
						True,
					)
			else:
				args = dict(
					leaves=leaves_to_be_added,
					from_date=application_doc.from_date,
					to_date=application_doc.to_date,
					is_lwp=lwp,
					holiday_list=holiday_list,
				)
				create_leave_ledger_entry(application_doc, args, True)


def get_leaves_for_period(
	employee: str,
	leave_type: str,
	from_date: datetime.date,
	to_date: datetime.date,
	skip_expired_leaves: bool = True,
) -> float:
	leave_entries = get_leave_entries(employee, leave_type, from_date, to_date)
	leave_days = 0
	processed_leave_entry_from_dates = set()
	for leave_entry in leave_entries:
		inclusive_period = leave_entry.from_date >= getdate(from_date) and leave_entry.to_date <= getdate(
			to_date
		)

		if inclusive_period and leave_entry.transaction_type == "Leave Encashment":
			leave_days += leave_entry.leaves

		elif (
			inclusive_period
			and leave_entry.transaction_type == "Leave Allocation"
			and leave_entry.is_expired
			and not skip_expired_leaves
		):
			leave_days += leave_entry.leaves

		elif leave_entry.transaction_type == "Leave Application":
			if leave_entry.from_date in processed_leave_entry_from_dates:
				continue
			processed_leave_entry_from_dates.add(leave_entry.from_date)
			if leave_entry.from_date < getdate(from_date):
				leave_entry.from_date = from_date
			if leave_entry.to_date > getdate(to_date):
				leave_entry.to_date = to_date

			half_day = 0
			half_day_date = None
			# fetch half day date for leaves with half days
			if leave_entry.leaves % 1:
				half_day = 1
				half_day_date = frappe.db.get_value(
					"Leave Application", leave_entry.transaction_name, "half_day_date"
				)

			leave_days += (
				get_number_of_leave_days(
					employee,
					leave_type,
					leave_entry.from_date,
					leave_entry.to_date,
					half_day,
					half_day_date,
					holiday_list=leave_entry.holiday_list,
				)
				* -1
			)

	return leave_days
