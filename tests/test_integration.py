import datetime

from django.contrib.auth import get_user_model
from django.core import checks
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from wagtail import hooks
from wagtail.models import Page, Revision

from wagtail_kanban_content_calendar.conf import check_config
from wagtail_kanban_content_calendar.models import Stage
from wagtail_kanban_content_calendar.stages import (
    card_token,
    move,
    planner_pages,
    stage_for,
)
from wagtail_kanban_content_calendar.views import BOARD_STAGES


def tok(page):
    """The token a freshly loaded card would echo."""
    return card_token(Page.objects.get(pk=page.pk))


def test_menu_shows_board_and_calendar_to_planner_users(client, editor, idea):
    client.force_login(editor)
    html = client.get(reverse("wagtailadmin_home")).content.decode()
    assert reverse("wagtail_kanban_content_calendar:board") in html
    assert reverse("wagtail_kanban_content_calendar:calendar") in html


def test_menu_hidden_without_the_permission(client, outsider):
    client.force_login(outsider)
    html = client.get(reverse("wagtailadmin_home")).content.decode()
    assert reverse("wagtail_kanban_content_calendar:board") not in html


def test_editor_shows_planner_entry_and_publish_menu_moves(client, editor, idea):
    client.force_login(editor)
    html = client.get(
        reverse("wagtailadmin_pages:edit", args=[idea.pk])
    ).content.decode()
    assert "Planner: Idea" in html
    assert "Move to Up next" in html
    assert "Move to Reviewing" in html
    assert "Cancel this idea" in html


def test_publish_menu_hides_moves_that_do_not_apply(client, editor, idea):
    move(idea, Stage.PUBLISHED, editor, tok(idea))
    client.force_login(editor)
    html = client.get(
        reverse("wagtailadmin_pages:edit", args=[idea.pk])
    ).content.decode()
    assert "Planner: Published" in html
    assert "Cancel this idea" not in html


def test_untracked_pages_get_nothing(client, editor, blog, planner_settings):
    client.force_login(editor)
    html = client.get(
        reverse("wagtailadmin_pages:edit", args=[blog.pk])
    ).content.decode()
    assert "Planner:" not in html
    assert "Move to Reviewing" not in html


def test_dashboard_panel_lists_up_next(client, editor, idea):
    move(idea, Stage.UP_NEXT, editor, tok(idea))
    client.force_login(editor)
    html = client.get(reverse("wagtailadmin_home")).content.decode()
    assert 'id="content-planner' in html or "content-planner" in html
    assert "Weekly community update" in html


def test_hooks_are_registered():
    for name in (
        "register_admin_viewset",
        "register_page_header_buttons",
        "register_page_listing_more_buttons",
        "register_page_action_menu_item",
        "construct_homepage_panels",
        "construct_homepage_summary_items",
        "register_log_actions",
        "insert_editor_js",
    ):
        assert any(
            fn.__module__ == "wagtail_kanban_content_calendar.wagtail_hooks"
            for fn in hooks.get_hooks(name)
        ), name


def test_config_check_passes_for_the_test_project():
    assert [e for e in check_config() if e.level >= checks.ERROR] == []


@override_settings(
    WAGTAIL_KANBAN_PAGE_MODELS={
        "wagtail_kanban_content_calendar_test.BlogPostPage": {"body_field": "missing"},
        "nope.Nothing": {},
    }
)
def test_config_check_reports_bad_settings():
    ids = sorted(e.id for e in check_config())
    assert ids == ["wkcc.E002", "wkcc.E004"]


def edit_page(client, page):
    return client.get(
        reverse("wagtailadmin_pages:edit", args=[page.pk])
    ).content.decode()


def test_publish_menu_moves_post_in_place_and_return_to_the_editor(
    client, editor, idea
):
    client.force_login(editor)
    html = edit_page(client, idea)
    assert 'data-controller="w-action"' in html
    move_url = reverse("wagtail_kanban_content_calendar:move", args=[idea.pk])
    assert f'data-w-action-url-value="{move_url}?to=up_next' in html
    edit_url = reverse("wagtailadmin_pages:edit", args=[idea.pk])
    # What Wagtail's w-action controller sends: the CSRF token and `next`; the move is in the URL.
    response = client.post(
        f"{move_url}?to=up_next&token={tok(idea)}",
        {"next": f"http://testserver{edit_url}"},
    )
    assert response.status_code == 302
    assert response["Location"] == f"http://testserver{edit_url}"
    assert stage_for(Page.objects.get(pk=idea.pk)) == Stage.UP_NEXT


def test_publish_menu_asks_in_a_dialog_before_undoing_wagtail_state(
    client, editor, idea, planner_settings
):
    planner_settings.reviewing_uses_workflow = True
    planner_settings.save()
    move(idea, Stage.REVIEWING, editor, tok(idea))
    client.force_login(editor)
    html = edit_page(client, idea)
    assert 'id="wkcc-cancel-confirm"' in html
    assert "cancels the review workflow" in html
    assert "confirm=1" in html


def test_publish_menu_follows_wagtail_on_scheduled_pages(client, editor, idea):
    # Wagtail treats a scheduled page as locked and hides Publish-menu actions; so do we.
    when = timezone.now() + datetime.timedelta(days=2)
    move(idea, Stage.READY, editor, tok(idea), go_live_at=when)
    client.force_login(editor)
    assert "Cancel this idea" not in edit_page(client, idea)


def test_editor_gets_the_stage_tag_for_tracked_pages_only(client, editor, idea, blog):
    client.force_login(editor)
    html = edit_page(client, idea)
    assert 'data-wkcc-stage-label="Planner: Idea"' in html
    assert "js/stage-tag.js" in html
    assert "data-wkcc-stage-label" not in edit_page(client, blog)


def test_dashboard_tile_counts_this_weeks_schedule(client, editor, idea):
    move(
        idea,
        Stage.READY,
        editor,
        tok(idea),
        go_live_at=timezone.now() + datetime.timedelta(days=2),
    )
    client.force_login(editor)
    html = client.get(reverse("wagtailadmin_home")).content.decode()
    assert "1 scheduled this week" in html
    assert "Up next (" in html  # the panel keeps Up next; the tile shows something else


def test_overdue_schedule_is_flagged_everywhere(client, editor, idea):

    move(
        idea,
        Stage.READY,
        editor,
        tok(idea),
        go_live_at=timezone.now() + datetime.timedelta(days=2),
    )
    # As if publish_scheduled never ran: the approved go-live is an hour ago.
    Revision.page_revisions.filter(object_id=str(idea.pk)).exclude(
        approved_go_live_at=None
    ).update(approved_go_live_at=timezone.now() - datetime.timedelta(hours=1))
    client.force_login(editor)
    for name in ("board", "calendar"):
        html = client.get(
            reverse(f"wagtail_kanban_content_calendar:{name}")
        ).content.decode()
        assert "publish_scheduled" in html, name
    home = client.get(reverse("wagtailadmin_home")).content.decode()
    assert "publish_scheduled" in home
    assert "1 scheduled page overdue" in home


def test_planner_demo_builds_every_stage(db):
    call_command("planner_demo")
    demo = get_user_model().objects.get(username="demo")
    stages = {stage_for(p) for p in planner_pages(demo)}
    assert set(BOARD_STAGES) | {Stage.CANCELLED} <= stages
