"""The only module that knows which Wagtail version is installed (7.4 LTS or 8.x).

Everything else in the add-on is the same on every supported Wagtail; each name used is guarded by
tests/test_wagtail_contract.py.
"""

from django.conf import settings


# Wagtail 8.0 made the Page model swappable; 7.4 has no such setting.
PAGE_MODEL = getattr(settings, "WAGTAIL_PAGE_MODEL", "wagtailcore.Page")

try:
    from wagtail.actions.workflow import CancelWorkflowAction, SubmitWorkflowAction
except ImportError:  # Wagtail 7.4: the same steps the page editor's buttons run.
    SubmitWorkflowAction = CancelWorkflowAction = None


def submit_workflow(page, user):
    if SubmitWorkflowAction:
        SubmitWorkflowAction(page, user=user).execute()
    else:
        page.get_workflow().start(page, user)


def cancel_workflow(page, user):
    if CancelWorkflowAction:
        CancelWorkflowAction(page, user=user).execute()
    else:
        page.current_workflow_state.cancel(user=user)
