import inspect
from unittest import mock

import frappe
import hrms.hr.doctype.leave_application.leave_application as hrms_leave_application
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days

import workplan.utils
from workplan.tests.utils import (
	LEAVE_TYPE,
	MONDAY,
	PART_TIME_24,
	WorkplanTestCase,
	first_day,
	make_employee,
	make_leave_application,
	nth_weekday,
	workplan_row,
)
from workplan.utils import (
	PATCHED_HRMS_FUNCTIONS,
	ensure_patches,
	get_original_hrms_function,
	hrms_supports_leave_application_arg,
	leave_application_kwargs,
)
from workplan.workplan.overrides import leave_application as workplan_leave_application
from workplan.workplan.overrides import leave_application_validation

WORKPLAN_MODULE = "workplan.workplan.overrides.leave_application"
HRMS_MODULE = "hrms.hr.doctype.leave_application.leave_application"


class TestMonkeyPatch(FrappeTestCase):
	def assertPatched(self):
		for function_name in PATCHED_HRMS_FUNCTIONS:
			function = getattr(hrms_leave_application, function_name)
			self.assertEqual(function.__module__, WORKPLAN_MODULE)
			self.assertIs(function, getattr(workplan_leave_application, function_name))

	def test_hrms_functions_are_patched(self):
		self.assertEqual(hrms_leave_application.get_number_of_leave_days.__module__, WORKPLAN_MODULE)
		self.assertEqual(hrms_leave_application.get_leaves_for_period.__module__, WORKPLAN_MODULE)
		self.assertPatched()

	def test_ensure_patches_is_idempotent(self):
		originals = {name: get_original_hrms_function(name) for name in PATCHED_HRMS_FUNCTIONS}
		for original in originals.values():
			self.assertEqual(original.__module__, HRMS_MODULE)

		ensure_patches()
		ensure_patches()

		self.assertPatched()
		for name, original in originals.items():
			self.assertIs(get_original_hrms_function(name), original)

	def test_ensure_patches_restores_patch(self):
		original = get_original_hrms_function("get_number_of_leave_days")
		with mock.patch.object(hrms_leave_application, "get_number_of_leave_days", original):
			self.assertEqual(hrms_leave_application.get_number_of_leave_days.__module__, HRMS_MODULE)
			ensure_patches()
			self.assertPatched()
			# the original is kept, not replaced by the patched function
			self.assertIs(get_original_hrms_function("get_number_of_leave_days"), original)
		self.assertPatched()

	def test_hooks_are_registered(self):
		for hook in ("before_request", "before_job", "before_migrate"):
			self.assertIn("workplan.utils.ensure_patches", frappe.get_hooks(hook), hook)

	def test_hook_signatures(self):
		# called the way frappe.app (before_request), frappe.utils.background_jobs (before_job) and
		# frappe.migrate (before_migrate) call the hooks
		frappe.call("workplan.utils.ensure_patches")
		frappe.call(
			"workplan.utils.ensure_patches",
			method="frappe.ping",
			kwargs={},
			transaction_type="job",
		)
		frappe.get_attr("workplan.utils.ensure_patches")()
		self.assertPatched()


class TestLeaveApplicationArgument(WorkplanTestCase):
	def test_support_detection(self):
		supported = (
			"leave_application" in inspect.signature(hrms_leave_application.get_leave_balance_on).parameters
		)
		self.assertEqual(hrms_supports_leave_application_arg(), supported)
		# cached
		self.assertIs(hrms_supports_leave_application_arg(), hrms_supports_leave_application_arg())

		self.assertEqual(leave_application_kwargs(None), {})
		with mock.patch.object(workplan.utils, "hrms_supports_leave_application_arg", return_value=True):
			self.assertEqual(leave_application_kwargs("HR-LAP-1"), {"leave_application": "HR-LAP-1"})
			self.assertEqual(leave_application_kwargs(None), {})
		with mock.patch.object(workplan.utils, "hrms_supports_leave_application_arg", return_value=False):
			self.assertEqual(leave_application_kwargs("HR-LAP-1"), {})

	def test_validate_balance_leaves_forwards_leave_application(self):
		employee = make_employee(
			"Leave Application Argument", [workplan_row(first_day(self.year), hours=PART_TIME_24)]
		)
		monday = nth_weekday(self.year, 3, MONDAY)
		application = make_leave_application(employee.name, LEAVE_TYPE, monday, add_days(monday, 2))

		real_get_leave_balance_on = hrms_leave_application.get_leave_balance_on

		def balance_calls(do):
			with (
				mock.patch.object(
					leave_application_validation, "get_leave_balance_on", wraps=real_get_leave_balance_on
				) as validation_mock,
				mock.patch.object(
					workplan_leave_application, "get_leave_balance_on", wraps=real_get_leave_balance_on
				) as fractional_mock,
			):
				do()
			self.assertTrue(validation_mock.called)
			self.assertTrue(fractional_mock.called)
			return [c.kwargs for c in validation_mock.call_args_list + fractional_mock.call_args_list]

		# new application: nothing to forward
		for kwargs in balance_calls(application.insert):
			self.assertNotIn("leave_application", kwargs)

		application.reload()
		application.description = "changed"
		for kwargs in balance_calls(application.save):
			if hrms_supports_leave_application_arg():
				self.assertEqual(kwargs.get("leave_application"), application.name)
			else:
				self.assertNotIn("leave_application", kwargs)

		# HRMS versions without the argument
		application.reload()
		with mock.patch.object(workplan.utils, "hrms_supports_leave_application_arg", return_value=False):
			for kwargs in balance_calls(application.save):
				self.assertNotIn("leave_application", kwargs)

	def test_whitelisted_functions_accept_leave_application(self):
		employee = make_employee(
			"Whitelisted Argument", [workplan_row(first_day(self.year), hours=PART_TIME_24)]
		)
		monday = nth_weekday(self.year, 3, MONDAY)
		application = make_leave_application(employee.name, LEAVE_TYPE, monday, add_days(monday, 2))
		application.insert()

		result = workplan_leave_application.get_number_of_leave_days_leave_application(
			employee.name, LEAVE_TYPE, monday, add_days(monday, 2), leave_application=application.name
		)
		self.assertIsNone(result["fractional_value"])
		self.assertEqual(
			workplan_leave_application.get_fractional_leave_details(
				employee.name, LEAVE_TYPE, monday, add_days(monday, 2), leave_application=application.name
			),
			(None, None, None, None),
		)
