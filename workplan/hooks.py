app_name = "workplan"
app_title = "Workplan"
app_publisher = "bitbetter GmbH"
app_description = "Adds a workplan for every employee where they can define their planned working hours per work day. This value will then be used for leave calculations."
app_email = "info@bitbetter.de"
app_license = "agpl-3.0"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "workplan",
# 		"logo": "/assets/workplan/logo.png",
# 		"title": "workplan",
# 		"route": "/workplan",
# 		"has_permission": "workplan.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/workplan/css/workplan.css"
# app_include_js = "/assets/workplan/js/workplan.js"

# include js, css files in header of web template
# web_include_css = "/assets/workplan/css/workplan.css"
# web_include_js = "/assets/workplan/js/workplan.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "workplan/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"Leave Application" : "public/js/leave_application.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "workplan/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "workplan.utils.jinja_methods",
# 	"filters": "workplan.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "workplan.install.before_install"
# after_install = "workplan.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "workplan.uninstall.before_uninstall"
# after_uninstall = "workplan.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "workplan.utils.before_app_install"
# after_app_install = "workplan.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "workplan.utils.before_app_uninstall"
# after_app_uninstall = "workplan.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "workplan.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

override_doctype_class = {
	"Leave Application": "workplan.workplan.overrides.leave_application_validation.CustomLeaveApplication",
	"Leave Allocation": "workplan.workplan.overrides.supress_leave_allocation_validation.CustomLeaveAllocation",
}
# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Leave Allocation": {"before_insert": "workplan.workplan.overrides.leave_allocation.update"},
	"Employee": {
		"before_save": "workplan.workplan.overrides.leave_allocation_new.update_all_allocations",
		"validate": "workplan.workplan.overrides.workplan_validation.validate_workplans",
		"on_update": "workplan.workplan.overrides.leave_application.update_application_days_value",
	},
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"cron": {"0 0 1 1 *": ["workplan.workplan.overrides.new_allocations_cronjob.allocate_all_next_year"]}
}
# scheduler_events = {
# 	"all": [
# 		"workplan.tasks.all"
# 	],
# 	"daily": [
# 		"workplan.tasks.daily"
# 	],
# 	"hourly": [
# 		"workplan.tasks.hourly"
# 	],
# 	"weekly": [
# 		"workplan.tasks.weekly"
# 	],
# 	"monthly": [
# 		"workplan.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "workplan.install.before_tests"

# Overriding Methods
# ------------------------------
#
override_whitelisted_methods = {
	"hrms.hr.doctype.leave_application.leave_application.get_number_of_leave_days": "workplan.workplan.overrides.leave_application.get_number_of_leave_days"
}
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "workplan.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["workplan.utils.before_request"]
# after_request = ["workplan.utils.after_request"]

# Job Events
# ----------
# before_job = ["workplan.utils.before_job"]
# after_job = ["workplan.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"workplan.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

fixtures = [
	{"doctype": "Custom Field", "filters": {"module": ["in", ["workplan"]]}},
	{"doctype": "Client Script", "filters": {"module": ["in", ["workplan"]]}},
	# {
	# 	"doctype": "Workflow State"
	# },
	# {
	# 	"doctype": "Workflow"
	# }
]
