import datetime

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from workplan.tests.utils import this_year
from workplan.workplan.overrides.leave_allocation_new import (
	calc_workplan_sum,
	fraction_of_year,
	get_current_workplan,
	get_next_workplan,
	resolve_end,
)


def workplan(start, end=None, hours=(8, 8, 8, 8, 8)):
	monday, tuesday, wednesday, thursday, friday = hours
	return frappe._dict(
		start=getdate(start),
		end=getdate(end) if end else None,
		monday=monday,
		tuesday=tuesday,
		wednesday=wednesday,
		thursday=thursday,
		friday=friday,
	)


class TestWorkplanHelpers(FrappeTestCase):
	def setUp(self):
		self.year = this_year()
		self.first = workplan(f"{self.year}-01-01", f"{self.year}-03-31", (8, 4, 8, 4, 0))
		# gap in April
		self.second = workplan(f"{self.year}-05-01", f"{self.year}-08-31", (8, 8, 8, 8, 8))
		self.third = workplan(f"{self.year}-09-01", None, (4, 4, 4, 4, 4))
		# unsorted on purpose
		self.employee = frappe._dict(custom_workplans=[self.third, self.first, self.second])

	def test_calc_workplan_sum(self):
		self.assertEqual(calc_workplan_sum(self.first), 24)
		self.assertEqual(calc_workplan_sum(self.second), 40)
		self.assertEqual(calc_workplan_sum(workplan(f"{self.year}-01-01", hours=(0, 0, 0, 0, 0))), 0)
		self.assertEqual(calc_workplan_sum(workplan(f"{self.year}-01-01", hours=(7.5, 7.5, 7.5, 7.5, 0))), 30)

	def test_get_current_workplan(self):
		y = self.year
		self.assertIs(get_current_workplan(self.employee, f"{y}-01-01"), self.first)
		self.assertIs(get_current_workplan(self.employee, f"{y}-03-31"), self.first)
		self.assertIsNone(get_current_workplan(self.employee, f"{y}-04-15"))
		self.assertIs(get_current_workplan(self.employee, getdate(f"{y}-05-01")), self.second)
		self.assertIs(get_current_workplan(self.employee, f"{y}-08-31"), self.second)
		# open end
		self.assertIs(get_current_workplan(self.employee, f"{y}-09-01"), self.third)
		self.assertIs(get_current_workplan(self.employee, f"{y + 5}-01-01"), self.third)
		self.assertIsNone(get_current_workplan(self.employee, f"{y - 1}-12-31"))
		self.assertIsNone(get_current_workplan(frappe._dict(custom_workplans=[]), f"{y}-01-01"))

	def test_get_next_workplan(self):
		y = self.year
		# the next workplan starting on or after the date
		self.assertIs(get_next_workplan(self.employee, f"{y - 1}-06-01"), self.first)
		self.assertIs(get_next_workplan(self.employee, f"{y}-01-01"), self.first)
		self.assertIs(get_next_workplan(self.employee, f"{y}-03-31"), self.second)
		self.assertIs(get_next_workplan(self.employee, f"{y}-05-01"), self.second)
		self.assertIs(get_next_workplan(self.employee, f"{y}-08-31"), self.third)
		self.assertIsNone(get_next_workplan(self.employee, f"{y}-09-02"))

	def test_resolve_end(self):
		end = getdate(f"{self.year}-06-30")
		self.assertEqual(resolve_end(end, self.year), end)
		self.assertEqual(resolve_end(None, self.year), datetime.date(self.year, 12, 31))
		self.assertEqual(resolve_end(None, self.year + 1), datetime.date(self.year + 1, 12, 31))

	def test_fraction_of_year(self):
		self.assertEqual(fraction_of_year("2026-01-01", "2026-12-31"), 1)
		self.assertEqual(fraction_of_year("2026-01-01", "2026-06-30"), 181 / 365)
		self.assertEqual(fraction_of_year("2026-07-01", "2026-12-31"), 184 / 365)
		self.assertEqual(fraction_of_year(getdate("2026-03-02"), getdate("2026-03-02")), 1 / 365)
		# always based on 365 days, also in leap years
		self.assertEqual(fraction_of_year("2028-01-01", "2028-12-31"), 366 / 365)
