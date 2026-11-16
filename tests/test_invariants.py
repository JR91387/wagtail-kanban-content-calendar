"""The design invariants in docs/DESIGN.md ("Invariants", K1–K4), one guard each."""

import datetime
import itertools
import pathlib
import re

import pytest

from django.urls import reverse
from django.utils import timezone
from wagtail.models import Page, PageLogEntry

from wagtail_kanban_content_calendar.models import STORED_STAGES, PlannerEntry, Stage
from wagtail_kanban_content_calendar.stages import card_token, move, stage_for


PACKAGE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src"
    / "wagtail_kanban_content_calendar"
)


def tok(page):
    return card_token(Page.objects.get(pk=page.pk))


class StubPage:
    """Just the state stage_for reads."""

    def __init__(self, live, workflow, scheduled, stored):
        self.live, self.workflow_in_progress, self.approved_schedule = (
            live,
            workflow,
            scheduled,
        )
        self.stored = stored

    @property
    def planner_entry(self):
        if self.stored is None:
            raise PlannerEntry.DoesNotExist
        return PlannerEntry(stage=self.stored)


# K1: Wagtail's own state wins; the stored stage applies only where Wagtail has none.
@pytest.mark.parametrize(
    "live, workflow, scheduled, stored",
    list(
        itertools.product(
            [True, False], [True, False], [True, False], [*STORED_STAGES, None]
        )
    ),
)
def test_stage_comes_from_wagtail_first(live, workflow, scheduled, stored):
    if live:
        expected = Stage.PUBLISHED
    elif workflow:
        expected = Stage.REVIEWING
    elif scheduled:
        expected = Stage.READY
    else:
        expected = Stage(stored) if stored else Stage.WRITING
    assert stage_for(StubPage(live, workflow, scheduled, stored)) == expected


# K2: every move that changes Wagtail state is Wagtail's own action, so Wagtail logs it.
def actions(page):
    return list(PageLogEntry.objects.filter(page=page).values_list("action", flat=True))


def test_moves_are_wagtails_own_actions(idea, editor, planner_settings):
    planner_settings.reviewing_uses_workflow = True
    planner_settings.save()
    when = timezone.now() + datetime.timedelta(days=2)
    move(idea, Stage.READY, editor, tok(idea), go_live_at=when)
    move(idea, Stage.WRITING, editor, tok(idea))
    move(idea, Stage.REVIEWING, editor, tok(idea))
    move(idea, Stage.WRITING, editor, tok(idea))
    move(idea, Stage.PUBLISHED, editor, tok(idea))
    move(idea, Stage.WRITING, editor, tok(idea))
    logged = actions(idea)
    for wagtail_action in (
        "wagtail.publish.schedule",
        "wagtail.schedule.cancel",
        "wagtail.workflow.start",
        "wagtail.workflow.cancel",
        "wagtail.publish",
        "wagtail.unpublish",
    ):
        assert wagtail_action in logged, wagtail_action
    assert (
        logged.count("wagtail_kanban_content_calendar.move") == 1 + 6
    )  # created, then 6 moves


# K3: Wagtail's dialogs and colour tokens, never our own.
def test_templates_use_wagtails_dialog():
    for template in (PACKAGE / "templates").rglob("*.html"):
        assert "<dialog" not in template.read_text(), template


def test_css_colours_are_wagtail_tokens():
    css = (
        PACKAGE / "static/wagtail_kanban_content_calendar/css/planner.css"
    ).read_text()
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\b(rgba?|hsla?)\(", css)
    assert "var(--w-color-" in css


# K4: every card works without the script: a plain form post, answered with a redirect.
def test_every_card_renders_its_move_form(client, editor, idea):
    client.force_login(editor)
    html = client.get(reverse("wagtail_kanban_content_calendar:board")).content.decode()
    move_url = reverse("wagtail_kanban_content_calendar:move", args=[idea.pk])
    assert f'<form method="post" action="{move_url}"' in html
    assert html.count('class="wkcc-card__move"') == html.count(
        'class="wkcc-card"'
    ) + html.count('class="wkcc-card wkcc-card--cancelled"')


@pytest.mark.parametrize(
    "name, fields",
    [
        ("move", {"to": "writing"}),
        ("target_date", {"target_date": "2026-12-01"}),
        ("schedule", {"go_live_at": "2099-01-01T09:00"}),
    ],
)
def test_plain_form_posts_work_and_redirect(client, editor, idea, name, fields):
    client.force_login(editor)
    board = reverse("wagtail_kanban_content_calendar:board")
    response = client.post(
        reverse(f"wagtail_kanban_content_calendar:{name}", args=[idea.pk]),
        {**fields, "token": tok(idea), "next": board},
    )
    assert response.status_code == 302 and response["Location"] == board
    assert tok(idea) != f"{idea.latest_revision_id}:0"  # the write happened


def test_templates_have_no_inline_event_handlers():
    """Inline handlers break under a strict Content Security Policy; Wagtail's controllers replace them."""
    for template in (PACKAGE / "templates").rglob("*.html"):
        assert not re.search(r"\son[a-z]+=", template.read_text()), template
