"""Every Wagtail name the add-on relies on, checked the way the add-on uses it.

When a Wagtail upgrade renames or changes one of these, this file fails first and names it. Names that
differ between supported Wagtail versions go through compat.py.
"""

import inspect

import pytest

from django.template import Context, Template
from wagtail.actions.publish_page_revision import PublishPageRevisionAction
from wagtail.actions.unpublish_page import UnpublishPageAction
from wagtail.admin.action_menu import ActionMenuItem
from wagtail.admin.filters import WagtailFilterSet
from wagtail.admin.site_summary import SummaryItem
from wagtail.admin.ui.components import Component
from wagtail.admin.views.generic.base import BaseListingView, WagtailAdminTemplateMixin
from wagtail.admin.viewsets.base import ViewSet, ViewSetGroup
from wagtail.admin.widgets import Button
from wagtail.locks import BasicLock
from wagtail.models import Page, Revision
from wagtail.permission_policies.pages import PagePermissionPolicy

from wagtail_kanban_content_calendar import compat
from wagtail_kanban_content_calendar.stages import card_token


def test_page_queryset_annotations(idea):
    page = (
        Page.objects.filter(pk=idea.pk)
        .prefetch_workflow_states()
        .annotate_approved_schedule()
        .get()
    )
    assert page.approved_schedule is False
    assert page.workflow_in_progress is False


def test_revision_manager_and_scheduled_revision(idea):
    assert Revision.page_revisions.filter(object_id=str(idea.pk)).exists()
    assert idea.scheduled_revision is None


def test_permission_policy_and_tester(idea, editor):
    editable = PagePermissionPolicy().instances_user_has_any_permission_for(
        editor, ["change"]
    )
    assert editable.filter(pk=idea.pk).exists()
    tester = idea.permissions_for_user(editor)
    for name in (
        "can_edit",
        "can_publish",
        "can_unpublish",
        "can_unschedule",
        "can_add_subpage",
    ):
        assert callable(getattr(tester, name)), name


def test_basic_lock(idea, editor):
    idea.locked, idea.locked_by = True, editor
    idea.save()
    lock = idea.get_lock()
    assert isinstance(lock, BasicLock)
    assert lock.for_user(editor) is False


def test_publish_and_unpublish_actions(idea, editor):
    revision = idea.save_revision(user=editor)
    PublishPageRevisionAction(revision, user=editor).execute()
    idea.refresh_from_db()
    assert idea.live
    UnpublishPageAction(idea, user=editor).execute()
    idea.refresh_from_db()
    assert not idea.live


def test_workflow_submit_and_cancel_through_compat(idea, editor, planner_settings):
    assert (
        idea.get_workflow() is not None
    )  # Wagtail's default "Moderators approval" on the root page
    idea.save_revision(user=editor)
    compat.submit_workflow(idea, editor)
    idea.refresh_from_db()
    assert idea.workflow_in_progress
    assert idea.current_workflow_state.user_can_cancel(editor)
    compat.cancel_workflow(idea, editor)
    idea.refresh_from_db()
    assert not idea.workflow_in_progress


def test_page_status_string(idea):
    assert idea.status_string == "draft"


def test_status_template_tag():
    html = Template(
        '{% load wagtailadmin_tags %}{% status "draft" classname="w-status--primary" %}'
    ).render(Context())
    assert 'class="w-status w-status--primary"' in html and "draft" in html


@pytest.mark.parametrize(
    ("cls", "method"),
    [
        (ViewSet, "get_urlpatterns"),
        (ViewSetGroup, "get_menu_item"),
        (BaseListingView, "get_base_queryset"),
        (BaseListingView, "get_filterset_kwargs"),
        (WagtailAdminTemplateMixin, "get_breadcrumbs_items"),
        (ActionMenuItem, "is_shown"),
        (SummaryItem, "get_context_data"),
        (Component, "get_context_data"),
    ],
)
def test_admin_classes_keep_the_methods_the_addon_overrides(cls, method):
    assert callable(getattr(cls, method)), f"{cls.__name__}.{method}"


def test_viewset_group_items_and_listing_attributes():
    assert hasattr(ViewSetGroup, "items")
    for name in (
        "results_only",
        "filterset_class",
        "is_searchable",
        "search_fields",
        "search_backend_name",
    ):
        assert hasattr(BaseListingView, name), name


def test_filterset_takes_a_request():
    assert "request" in inspect.signature(WagtailFilterSet.__init__).parameters


def test_button_signature_has_what_the_addon_passes():
    params = inspect.signature(Button.__init__).parameters
    for name in ("label", "url", "icon_name", "attrs", "priority"):
        assert name in params, name


def test_card_token_reads_latest_revision(idea):
    assert card_token(idea).startswith(f"{idea.latest_revision_id}:")
