import functools
import inspect

# HRMS module level functions that are replaced by Workplan's implementation. They are plain functions
# (not methods of the Leave Application controller), so they cannot be overridden via hooks.
PATCHED_HRMS_FUNCTIONS = ("get_number_of_leave_days", "get_leaves_for_period")

# attribute on the HRMS module that keeps the original functions, so that patching stays idempotent
# even if this module gets reloaded
_ORIGINALS_ATTR = "_workplan_original_functions"


def _get_hrms_leave_application_module():
	import hrms.hr.doctype.leave_application.leave_application as hrms_leave_application

	return hrms_leave_application


def ensure_patches(*args, **kwargs):
	"""Replace the HRMS leave day functions with Workplan's implementation.

	Idempotent, safe to call any number of times. Called when the `workplan` package is imported and
	additionally registered as `before_request`, `before_job` and `before_migrate` hook, because Frappe
	caches the hooks and therefore does not necessarily import the app before HRMS code runs.
	Accepts and ignores any arguments (`before_job` hooks are called with `method`, `kwargs` and
	`transaction_type`)."""
	from workplan.workplan.overrides import leave_application as workplan_leave_application

	hrms_leave_application = _get_hrms_leave_application_module()
	originals = getattr(hrms_leave_application, _ORIGINALS_ATTR, None)
	if originals is None:
		originals = {}
		setattr(hrms_leave_application, _ORIGINALS_ATTR, originals)

	for function_name in PATCHED_HRMS_FUNCTIONS:
		replacement = getattr(workplan_leave_application, function_name)
		current = getattr(hrms_leave_application, function_name)
		if current is replacement:
			continue
		if not _is_workplan_function(current):
			originals.setdefault(function_name, current)
		setattr(hrms_leave_application, function_name, replacement)


def get_original_hrms_function(function_name: str):
	"""Returns the unpatched HRMS implementation of a patched function."""
	ensure_patches()
	return getattr(_get_hrms_leave_application_module(), _ORIGINALS_ATTR)[function_name]


def _is_workplan_function(function) -> bool:
	return (getattr(function, "__module__", None) or "").startswith("workplan.")


@functools.cache
def hrms_supports_leave_application_arg() -> bool:
	"""Whether the installed HRMS version accepts the `leave_application` argument in
	`get_leave_balance_on` (used for the permission check of leave approvers, added in HRMS 15.64)."""
	from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on

	try:
		return "leave_application" in inspect.signature(get_leave_balance_on).parameters
	except (TypeError, ValueError):
		return False


def leave_application_kwargs(leave_application: str | None) -> dict:
	"""Keyword arguments to forward the leave application to HRMS' `get_leave_balance_on`, if supported."""
	if leave_application and hrms_supports_leave_application_arg():
		return {"leave_application": leave_application}
	return {}
