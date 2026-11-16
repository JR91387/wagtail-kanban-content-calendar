"""A card is its title; pills appear only when something needs attention."""

import datetime

from django.urls import reverse
from django.utils import timezone
from wagtail.models import Page, Revision

from wagtail_kanban_content_calendar.models import PlannerEntry, Stage
from wagtail_kanban_content_calendar.stages import card_token, move, with_planner_state
from wagtail_kanban_content_calendar.views import card_for


def pills(page, user):
    loaded = with_planner_state(Page.objects.filter(pk=page.pk)).get()
    return card_for(loaded, user).pills


def tok(page):
    return card_token(Page.objects.get(pk=page.pk))


def test_a_plain_card_has_no_pills_and_shows_only_its_title(client, editor, idea):
    assert pills(idea, editor) == []
    client.force_login(editor)
    html = client.get(reverse("wagtail_kanban_content_calendar:board")).content.decode()
    card = html[html.index('class="wkcc-card"') : html.index("</article>")]
    assert "Weekly community update" in card
    for detail in ("Blog post page", "Edited", "Target ", "Go-live", "In workflow"):
        assert detail not in card


def test_scheduled_ready_card_shows_its_go_live(idea, editor):
    when = timezone.now() + datetime.timedelta(days=3)
    move(idea, Stage.READY, editor, tok(idea), go_live_at=when)
    [(kind, text)] = pills(idea, editor)
    assert kind == "info" and timezone.localtime(when).strftime("%b") in text


def test_overdue_go_live_is_a_warning(idea, editor):
    move(
        idea,
        Stage.READY,
        editor,
        tok(idea),
        go_live_at=timezone.now() + datetime.timedelta(days=3),
    )
    Revision.page_revisions.filter(object_id=str(idea.pk)).exclude(
        approved_go_live_at=None
    ).update(approved_go_live_at=timezone.now() - datetime.timedelta(hours=1))
    assert pills(idea, editor) == [("warning", "Overdue")]


def test_locked_by_someone_else_is_a_warning(idea, editor, writer):
    Page.objects.filter(pk=idea.pk).update(locked=True, locked_by=editor)
    assert pills(idea, writer) == [("warning", "Locked by editor")]
    assert pills(idea, editor) == []  # your own lock isn't news


def test_target_dates_only_when_close_or_missed(idea, editor):
    today = timezone.localdate()
    cases = [
        (today + datetime.timedelta(days=10), []),
        (
            today + datetime.timedelta(days=1),
            [("info", f"Due {today + datetime.timedelta(days=1):%a}")],
        ),
        (today, [("info", "Due today")]),
        (today - datetime.timedelta(days=1), [("warning", "Past target")]),
    ]
    for target, expected in cases:
        PlannerEntry.objects.filter(page=idea).update(target_date=target)
        assert pills(idea, editor) == expected, target


def test_published_cards_ignore_target_dates(idea, editor):
    PlannerEntry.objects.filter(page=idea).update(
        target_date=timezone.localdate() - datetime.timedelta(days=3)
    )
    move(idea, Stage.PUBLISHED, editor, tok(idea))
    assert pills(idea, editor) == []


def test_every_card_keeps_a_move_button(client, editor, idea):
    client.force_login(editor)
    html = client.get(reverse("wagtail_kanban_content_calendar:board")).content.decode()
    assert 'aria-label="Move “Weekly community update”"' in html


def test_quick_view_shows_wagtails_own_status(client, editor, idea):
    from django.urls import reverse

    client.force_login(editor)
    html = client.get(
        reverse("wagtail_kanban_content_calendar:card", args=[idea.pk]) + "?partial=1"
    ).content.decode()
    assert 'class="w-status w-status--primary"' in html
    assert ">draft<" in html.replace("\n", "").replace(" ", "")
