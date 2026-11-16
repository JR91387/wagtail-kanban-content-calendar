import datetime

import pytest

from django.urls import reverse
from django.utils import timezone
from wagtail.models import Page

from wagtail_kanban_content_calendar.models import PlannerEntry, Stage
from wagtail_kanban_content_calendar.stages import card_token, move, stage_for
from wagtail_kanban_content_calendar.test.models import BlogPostPage


def tok(page):
    """The token a freshly loaded card would echo."""
    return card_token(Page.objects.get(pk=page.pk))


def url(name, *args):
    return reverse(f"wagtail_kanban_content_calendar:{name}", args=args)


@pytest.fixture
def editor_client(client, editor):
    client.force_login(editor)
    return client


@pytest.mark.parametrize("name", ["board", "calendar", "new_idea"])
def test_planner_pages_load_for_editors(editor_client, idea, name):
    assert editor_client.get(url(name)).status_code == 200


def test_week_view_and_card_load(editor_client, idea):
    assert editor_client.get(url("calendar") + "?view=week").status_code == 200
    response = editor_client.get(url("card", idea.pk) + "?partial=1")
    assert response.status_code == 200
    assert "Weekly community update" in response.content.decode()


def test_planner_is_closed_to_users_without_the_permission(client, outsider, idea):
    # Wagtail's admin turns a permission refusal into a redirect to the dashboard with a message.
    client.force_login(outsider)
    response = client.get(url("board"))
    assert response.status_code == 302
    assert response["Location"] == reverse("wagtailadmin_home")
    client.post(url("move", idea.pk), {"to": "writing", "token": tok(idea)})
    assert stage_for(Page.objects.get(pk=idea.pk).specific) == Stage.IDEA


def test_board_puts_each_card_in_its_stage(editor_client, idea, editor):
    move(idea, Stage.WRITING, editor, tok(idea))
    columns = dict(editor_client.get(url("board")).context["columns"])
    assert [card.page.pk for card in columns[Stage.WRITING]] == [idea.pk]
    assert columns[Stage.IDEA] == []


def test_move_endpoint_answers_json(editor_client, idea):
    response = editor_client.post(
        url("move", idea.pk),
        {"to": "up_next", "token": tok(idea)},
        HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 200
    assert response.json()["stage"] == "up_next"


def test_move_endpoint_reports_a_stale_board(editor_client, idea):
    response = editor_client.post(
        url("move", idea.pk),
        {"to": "up_next", "token": "999:0"},
        HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 409
    assert stage_for(Page.objects.get(pk=idea.pk).specific) == Stage.IDEA


def test_move_redirects_only_to_this_site(editor_client, idea):
    response = editor_client.post(
        url("move", idea.pk),
        {
            "to": "up_next",
            "token": tok(idea),
            "next": "https://evil.example/",
        },
    )
    assert response.status_code == 302
    assert response["Location"] == url("board")


def test_schedule_endpoint_schedules_in_the_future_only(editor_client, idea):
    past = (timezone.localtime() - datetime.timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M"
    )
    response = editor_client.post(
        url("schedule", idea.pk),
        {"go_live_at": past, "token": tok(idea)},
        HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 400
    future = (timezone.localtime() + datetime.timedelta(days=2)).strftime(
        "%Y-%m-%dT%H:%M"
    )
    response = editor_client.post(
        url("schedule", idea.pk),
        {"go_live_at": future, "token": tok(idea)},
        HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 200
    assert Page.objects.get(pk=idea.pk).specific.approved_schedule


def test_target_date_endpoint(editor_client, idea):
    response = editor_client.post(
        url("target_date", idea.pk),
        {"target_date": "2026-12-01", "token": tok(idea)},
        HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 200
    assert PlannerEntry.objects.get(page=idea).target_date == datetime.date(2026, 12, 1)


def test_target_date_refuses_a_stale_card(editor_client, idea):
    response = editor_client.post(
        url("target_date", idea.pk),
        {"target_date": "2026-12-01", "token": "999:0"},
        HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 409
    assert PlannerEntry.objects.get(page=idea).target_date is None


def test_new_idea_form_creates_a_draft(editor_client, site, planner_settings):
    response = editor_client.post(
        url("new_idea"),
        {
            "title": "Fresh idea",
            "page_type": "wagtail_kanban_content_calendar_test.blogpostpage",
            "site": site.pk,
        },
    )
    assert response.status_code == 302
    page = BlogPostPage.objects.get(title="Fresh idea")
    assert not page.live and stage_for(page) == Stage.IDEA


def test_new_idea_needs_a_parent_page(editor_client, site, planner_settings):
    planner_settings.idea_parent_page = None
    planner_settings.save()
    response = editor_client.post(
        url("new_idea"),
        {
            "title": "Nowhere",
            "page_type": "wagtail_kanban_content_calendar_test.blogpostpage",
            "site": site.pk,
        },
    )
    assert response.status_code == 200
    assert (
        "Settings &gt; Content planner" in response.content.decode()
        or "Settings > Content planner" in response.content.decode()
    )
    assert not BlogPostPage.objects.filter(title="Nowhere").exists()


def test_calendar_places_scheduled_posts_on_their_day(editor_client, idea, editor):
    when = timezone.now() + datetime.timedelta(days=1)
    move(idea, Stage.READY, editor, tok(idea), go_live_at=when)
    response = editor_client.get(
        url("calendar") + f"?date={timezone.localdate(when).isoformat()}"
    )
    days = {day: items for week in response.context["weeks"] for day, items in week}
    assert [(kind, card.page.pk) for kind, card in days[timezone.localdate(when)]] == [
        ("scheduled", idea.pk)
    ]


def test_refused_moves_are_logged(editor_client, idea, caplog):
    with caplog.at_level("WARNING", logger="wagtail_kanban_content_calendar.views"):
        editor_client.post(
            url("move", idea.pk),
            {"to": "up_next", "token": "999:0"},
            HTTP_ACCEPT="application/json",
        )
    assert f"page={idea.pk}" in caplog.text
    assert "409" in caplog.text


def test_board_hides_posts_older_than_the_window(editor_client, idea, editor):
    move(idea, Stage.PUBLISHED, editor, tok(idea))
    old = timezone.now() - datetime.timedelta(days=60)
    Page.objects.filter(pk=idea.pk).update(last_published_at=old)
    columns = dict(editor_client.get(url("board")).context["columns"])
    assert columns[Stage.PUBLISHED] == []


def test_unpublish_by_move_needs_confirmation(editor_client, idea, editor):
    move(idea, Stage.PUBLISHED, editor, tok(idea))
    response = editor_client.post(
        url("move", idea.pk),
        {"to": "writing", "token": tok(idea)},
        HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 400
    assert response.json()["confirm"] is True
    assert "unpublishes" in response.json()["message"]
    assert Page.objects.get(pk=idea.pk).live
    response = editor_client.post(
        url("move", idea.pk),
        {"to": "writing", "token": tok(idea), "confirm": "1"},
        HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 200
    assert not Page.objects.get(pk=idea.pk).live


def test_without_the_script_an_undoing_move_goes_to_the_confirm_page(
    editor_client, idea, editor
):
    move(idea, Stage.PUBLISHED, editor, tok(idea))
    board = url("board")
    response = editor_client.post(
        url("move", idea.pk), {"to": "writing", "token": tok(idea), "next": board}
    )
    assert response.status_code == 302
    assert response["Location"].startswith(url("card", idea.pk) + "?move=writing")
    page = editor_client.get(response["Location"]).content.decode()
    assert 'name="confirm" value="1"' in page
    assert "unpublishes" in page
    assert Page.objects.get(pk=idea.pk).live


def test_plain_stage_moves_need_no_confirmation(editor_client, idea):
    response = editor_client.post(
        url("move", idea.pk),
        {"to": "writing", "token": tok(idea)},
        HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 200


@pytest.mark.parametrize("name", ["board", "calendar"])
def test_results_url_is_only_the_swappable_part(editor_client, idea, name):
    response = editor_client.get(url(f"{name}_results"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "<html" not in html and "data-page-id" in html


@pytest.mark.parametrize("name", ["board", "calendar"])
def test_wagtail_header_search_and_filters_drive_the_results(editor_client, idea, name):
    html = editor_client.get(url(name)).content.decode()
    assert 'id="filters-drilldown"' in html
    assert f'data-w-swap-src-value="{url(name + "_results")}"' in html
    assert 'id="listing-results"' in html


def test_quick_view_move_form_returns_to_the_board(editor_client, idea):
    html = editor_client.get(url("card", idea.pk) + "?partial=1").content.decode()
    assert f'name="next" value="{url("board")}"' in html
    assert "data-wkcc-move-form" in html


@pytest.mark.parametrize("name", ["move", "schedule", "target_date"])
def test_card_endpoints_refuse_untracked_pages(editor_client, blog, name):
    response = editor_client.post(
        url(name, blog.pk), {"to": "writing", "token": tok(blog), "confirm": "1"}
    )
    assert response.status_code == 404
    assert not PlannerEntry.objects.filter(page=blog).exists()


def test_card_view_refuses_untracked_pages(editor_client, blog):
    assert editor_client.get(url("card", blog.pk)).status_code == 404


@pytest.mark.parametrize("name", ["move", "schedule", "target_date"])
def test_card_endpoints_take_only_a_post(editor_client, idea, name):
    assert editor_client.get(url(name, idea.pk)).status_code == 405


def test_card_endpoints_need_the_csrf_token(client, editor, idea):
    from django.test import Client

    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(editor)
    response = csrf_client.post(
        url("move", idea.pk), {"to": "up_next", "token": tok(idea)}
    )
    assert response.status_code == 403
    assert stage_for(Page.objects.get(pk=idea.pk).specific) == Stage.IDEA


def test_unticked_checkbox_filters_are_not_shown_as_active(editor_client, idea):
    html = editor_client.get(url("board")).content.decode()
    assert "My pages only" in html  # offered in the filter drilldown
    assert "False" not in html.split('id="listing-results"')[1].split("wkcc-board")[0]
