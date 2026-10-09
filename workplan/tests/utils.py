"""Shared fixtures and helpers for the Workplan test suite.

All records use the `_Test Workplan` prefix and are created check-before-create, inside the transaction
of the test class (FrappeTestCase rolls it back after the class). All dates are derived from the current
year, because the app works on the current and the next year (`frappe.utils.getdate().year`).
"""

import datetime
from contextlib import contextmanager
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, getdate

PREFIX = "_Test Workplan"
COMPANY = f"{PREFIX} Company"
COMPANY_ABBR = "_TWPC"
HOLIDAY_LIST = f"{PREFIX} Holidays"

# automatically allocated and calculated from the workplans, no carry forward
LEAVE_TYPE = f"{PREFIX} Vacation"
# automatically allocated and calculated, with carry forward (max. 5 days)
CARRY_LEAVE_TYPE = f"{PREFIX} Carry Vacation"
CARRY_MAX_DAYS = 5
# not automatically allocated, holidays count as leave days
INCLUSIVE_LEAVE_TYPE = f"{PREFIX} Inclusive Leave"

POLICY_30 = f"{PREFIX} Policy 30"
POLICY_24 = f"{PREFIX} Policy 24"
CARRY_POLICY = f"{PREFIX} Carry Policy"
CARRY_ANNUAL = 20

MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = range(7)

FULL_TIME = (8, 8, 8, 8, 8)
PART_TIME_24 = (8, 4, 8, 4, 0)
HALF_TIME = (4, 4, 4, 4, 4)
ZERO_HOURS = (0, 0, 0, 0, 0)


# ---------------------------------------------------------------- dates


def this_year() -> int:
	return getdate().year


def first_day(year: int) -> datetime.date:
	return datetime.date(year, 1, 1)


def last_day(year: int) -> datetime.date:
	return datetime.date(year, 12, 31)


def nth_weekday(year: int, month: int, weekday: int, n: int = 1) -> datetime.date:
	"""n-th given weekday (0 = Monday) of a month, e.g. nth_weekday(2026, 3, MONDAY) = first Monday of March"""
	first = datetime.date(year, month, 1)
	return first + datetime.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def custom_holiday(year: int) -> datetime.date:
	"""A non weekend holiday in the test holiday list: the first Wednesday of June"""
	return nth_weekday(year, 6, WEDNESDAY)


def days_in_year(start, end) -> int:
	return (getdate(end) - getdate(start)).days + 1


@contextmanager
def frozen_today(date):
	"""Lets frappe.utils.getdate()/nowdate()/today() return the given date (freezegun is not a hard
	dependency of the bench, so the frappe helper FrappeTestCase.freeze_time cannot be relied upon)."""
	fake_now = datetime.datetime.combine(getdate(date), datetime.time(0, 30))
	with mock.patch("frappe.utils.data.now_datetime", return_value=fake_now):
		yield


# ---------------------------------------------------------------- expected values


def expected_allocation(segments, year: int) -> float:
	"""Reference implementation of the allocation formula:
	sum over workplans of `fraction_of_year * annual_allocation * weekly_hours / 40` within the year,
	where fraction_of_year = days / 365. segments: [(start, end or None, weekly_hours, annual_allocation)]"""
	total = 0.0
	for start, end, weekly_hours, annual in segments:
		start = max(getdate(start), first_day(year))
		end = min(getdate(end) if end else last_day(year), last_day(year))
		if end < start:
			continue
		total += days_in_year(start, end) / 365 * annual * weekly_hours / 40
	return total


def expected_leave_days(plan, from_date, to_date, holidays=(), include_holidays=False) -> float:
	"""Reference implementation of the leave day calculation: day by day, hours of the workplan valid on
	that day (0 if none), weekends/holidays count 0 unless include_holidays, divided by 8."""
	hours = 0.0
	day = getdate(from_date)
	holidays = {getdate(d) for d in holidays}
	while day <= getdate(to_date):
		if day.weekday() < 5 and (include_holidays or day not in holidays):
			for row in plan:
				start, end, week = row[0], row[1], row[2]
				if getdate(start) <= day and (not end or day <= getdate(end)):
					hours += week[day.weekday()]
					break
		day = add_days(day, 1)
	return hours / 8


# ---------------------------------------------------------------- fixtures


def ensure_fixtures():
	"""Creates the shared master data if it does not exist yet."""
	year = this_year()
	_ensure_gender("Male")
	_ensure_company()
	_ensure_holiday_list(year)
	_ensure_leave_type(
		LEAVE_TYPE,
		custom_automatic_allocation=1,
		custom_automatic_allocation_calculation_=1,
		is_carry_forward=0,
		include_holiday=0,
	)
	_ensure_leave_type(
		CARRY_LEAVE_TYPE,
		custom_automatic_allocation=1,
		custom_automatic_allocation_calculation_=1,
		is_carry_forward=1,
		maximum_carry_forwarded_leaves=CARRY_MAX_DAYS,
		include_holiday=0,
	)
	_ensure_leave_type(
		INCLUSIVE_LEAVE_TYPE,
		custom_automatic_allocation=0,
		custom_automatic_allocation_calculation_=0,
		is_carry_forward=0,
		include_holiday=1,
		allow_negative=1,
	)
	_ensure_leave_policy(POLICY_30, {LEAVE_TYPE: 30})
	_ensure_leave_policy(POLICY_24, {LEAVE_TYPE: 24})
	_ensure_leave_policy(CARRY_POLICY, {CARRY_LEAVE_TYPE: CARRY_ANNUAL})
	# applications in the past of the current year must be possible
	frappe.db.set_single_value("HR Settings", "restrict_backdated_leave_application", 0)


def _ensure_gender(gender):
	if not frappe.db.exists("Gender", gender):
		frappe.get_doc({"doctype": "Gender", "gender": gender}).insert(ignore_permissions=True)


def _ensure_company():
	if frappe.db.exists("Company", COMPANY):
		return
	frappe.get_doc(
		{
			"doctype": "Company",
			"company_name": COMPANY,
			"abbr": COMPANY_ABBR,
			"default_currency": "EUR",
			"country": "Germany",
			"chart_of_accounts": "Standard",
		}
	).insert(ignore_permissions=True)


def _ensure_holiday_list(year):
	"""Weekends of the current and the next year plus one holiday on a weekday per year."""
	if frappe.db.exists("Holiday List", HOLIDAY_LIST):
		holiday_list = frappe.get_doc("Holiday List", HOLIDAY_LIST)
		if getdate(holiday_list.from_date) == first_day(year) and getdate(holiday_list.to_date) == last_day(
			year + 1
		):
			return
		frappe.delete_doc("Holiday List", HOLIDAY_LIST, force=True, ignore_permissions=True)

	holidays = []
	day = first_day(year)
	while day <= last_day(year + 1):
		if day.weekday() >= SATURDAY:
			holidays.append({"holiday_date": day, "description": "Weekend", "weekly_off": 1})
		elif day in (custom_holiday(year), custom_holiday(year + 1)):
			holidays.append({"holiday_date": day, "description": f"{PREFIX} Holiday", "weekly_off": 0})
		day = add_days(day, 1)

	frappe.get_doc(
		{
			"doctype": "Holiday List",
			"holiday_list_name": HOLIDAY_LIST,
			"from_date": first_day(year),
			"to_date": last_day(year + 1),
			"holidays": holidays,
		}
	).insert(ignore_permissions=True)


def _ensure_leave_type(name, **values):
	if frappe.db.exists("Leave Type", name):
		doc = frappe.get_doc("Leave Type", name)
	else:
		doc = frappe.get_doc({"doctype": "Leave Type", "leave_type_name": name})
	doc.update({"max_leaves_allowed": 0, "allow_negative": 0, "is_lwp": 0, **values})
	doc.save(ignore_permissions=True)


def _ensure_leave_policy(title, allocations: dict):
	if get_policy(title):
		return
	policy = frappe.get_doc(
		{
			"doctype": "Leave Policy",
			"title": title,
			"leave_policy_details": [
				{"leave_type": leave_type, "annual_allocation": annual}
				for leave_type, annual in allocations.items()
			],
		}
	)
	policy.insert(ignore_permissions=True)
	policy.submit()


def get_policy(title):
	return frappe.db.get_value("Leave Policy", {"title": title, "docstatus": 1}, "name")


# ---------------------------------------------------------------- employees


def workplan_row(start, end=None, hours=FULL_TIME, policy=POLICY_30):
	monday, tuesday, wednesday, thursday, friday = hours
	return {
		"start": getdate(start),
		"end": getdate(end) if end else None,
		"monday": monday,
		"tuesday": tuesday,
		"wednesday": wednesday,
		"thursday": thursday,
		"friday": friday,
		"policy": get_policy(policy),
	}


def make_employee(label, workplans, status="Active"):
	"""Creates an employee together with its workplans (custom_workplans is mandatory, so the allocation
	hooks already run on insert). workplans: list of workplan_row() dicts."""
	employee = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": f"{PREFIX} {label}",
			"last_name": "Employee",
			"gender": "Male",
			"date_of_birth": getdate("1990-01-01"),
			"date_of_joining": first_day(this_year() - 3),
			"status": status,
			"company": COMPANY,
			"holiday_list": HOLIDAY_LIST,
			"custom_workplans": workplans,
		}
	)
	employee.insert(ignore_permissions=True)
	return employee


def sorted_workplans(employee_doc):
	return sorted(employee_doc.custom_workplans, key=lambda w: getdate(w.start))


def set_hours(workplan, hours):
	workplan.monday, workplan.tuesday, workplan.wednesday, workplan.thursday, workplan.friday = hours


# ---------------------------------------------------------------- allocations / ledger


def get_allocation(employee, leave_type, year):
	name = frappe.db.get_value(
		"Leave Allocation",
		{
			"employee": employee,
			"leave_type": leave_type,
			"docstatus": 1,
			"from_date": ("<=", last_day(year)),
			"to_date": (">=", first_day(year)),
		},
	)
	return frappe.get_doc("Leave Allocation", name) if name else None


def ledger_entries(transaction_name):
	return frappe.get_all(
		"Leave Ledger Entry",
		filters={"transaction_name": transaction_name, "docstatus": 1},
		fields=["name", "from_date", "to_date", "leaves", "is_carry_forward", "is_expired"],
		order_by="creation asc, leaves desc",
	)


def ledger_sum(transaction_name, **filters):
	return flt(
		sum(
			e.leaves
			for e in ledger_entries(transaction_name)
			if all(e.get(key) == value for key, value in filters.items())
		),
		3,
	)


# ---------------------------------------------------------------- leave applications


def fill_leave_days(leave_application):
	"""Emulates the desk form: the HRMS form script sets total_leave_days via the (overridden) whitelisted
	get_number_of_leave_days, the workplan client script then calls get_number_of_leave_days_leave_application
	and applies the fractional values."""
	from workplan.workplan.overrides.leave_application import (
		get_number_of_leave_days,
		get_number_of_leave_days_leave_application,
	)

	la = leave_application
	la.total_leave_days = get_number_of_leave_days(la.employee, la.leave_type, la.from_date, la.to_date)
	result = get_number_of_leave_days_leave_application(la.employee, la.leave_type, la.from_date, la.to_date)
	la.custom_fractional_day_value = result["fractional_value"]
	if result["fractional_value"]:
		la.total_leave_days = result["total_leave_days"]
		la.custom_last_workday_date = result["date"]
		la.custom_last_workday_weekday = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"][
			result["weekday"]
		]
		total_hours = flt(result["fractional_work"]) * 8
		la.custom_hours_to_work = int(total_hours)
		la.custom_minutes_to_work = int((total_hours - int(total_hours)) * 60)
	return result


def make_leave_application(employee, leave_type, from_date, to_date, fill=True):
	leave_application = frappe.get_doc(
		{
			"doctype": "Leave Application",
			"employee": employee,
			"leave_type": leave_type,
			"from_date": getdate(from_date),
			"to_date": getdate(to_date),
			"status": "Open",
			"company": COMPANY,
			"description": PREFIX,
		}
	)
	if fill:
		fill_leave_days(leave_application)
	return leave_application


def approve(leave_application):
	leave_application.reload()
	leave_application.status = "Approved"
	leave_application.submit()
	return leave_application


def make_approved_leave_application(employee, leave_type, from_date, to_date):
	leave_application = make_leave_application(employee, leave_type, from_date, to_date)
	leave_application.insert(ignore_permissions=True)
	return approve(leave_application)


class WorkplanTestCase(FrappeTestCase):
	"""Creates the shared fixtures once per class (rolled back by FrappeTestCase after the class)."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		ensure_fixtures()
		cls.year = this_year()
		cls.next_year = cls.year + 1

	def assertFloatEqual(self, first, second, places=3, msg=None):
		self.assertAlmostEqual(flt(first), flt(second), places=places, msg=msg)
