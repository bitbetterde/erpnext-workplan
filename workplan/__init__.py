__version__ = "0.0.6"

from workplan.utils import ensure_patches

# Monkey patching HRMS functions which are not class methods and therefore cannot be extended/overridden.
# Also registered as before_request/before_job/before_migrate hook, see hooks.py.
ensure_patches()
