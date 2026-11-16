import datetime

import pytest

from django.core.exceptions import PermissionDenied
from django.utils import timezone
from wagtail.models import Page, PageLogEntry

from wagtail_kanban_content_calendar.models import PlannerEntry, Stage
from wagtail_kanban_content_calendar.stages import (
    LOG_ACTION,
    PlannerError,
    StaleCardError,
    card_token,
    create_idea,
    move,
    set_target_date,
    stage_for,
)
from wagtail_kanban_content_calendar.test.models import BlogPostPage, NewsPage


def tok(page):
    """The token a freshly loaded card would echo."""
    return card_token(Page.objects.get(pk=page.pk))


def fresh(page):
    return Page.objects.get(pk=page.pk).specific


def step(page, to, user, **kwargs):
    move(page, to, user, tok(page), **kwargs)
    return fresh(page)


def test_new_idea_is_a_draft_with_the_starter_body(idea):
    page = fresh(idea)
    assert stage_for(page) == Stage.IDEA
    assert not page.live
    assert page.body == "<p>Hook: ...</p>"
    assert page.latest_revision is not None


def test_starter_body_goes_into_a_streamfield_as_one_block(
    planner_settings, blog, editor
):
    page = create_idea(blog, NewsPage, "Stream", editor)
    assert [block.block_type for block in fresh(page).body] == ["paragraph"]


def test_planner_only_stages_are_stored(idea, editor):
    for stage in (Stage.UP_NEXT, Stage.WRITING, Stage.REVIEWING, Stage.READY):
        page = step(idea, stage, editor)
        assert stage_for(page) == stage
        assert not page.live


def test_scheduling_uses_wagtail_go_live(idea, editor):
    when = timezone.now() + datetime.timedelta(days=3)
    page = step(idea, Stage.READY, editor, go_live_at=when)
    assert stage_for(page) == Stage.READY
    assert page.approved_schedule
    assert page.scheduled_revision.approved_go_live_at == when
    assert not page.live


def test_leaving_ready_cancels_the_schedule(idea, editor):
    page = step(
        idea,
        Stage.READY,
        editor,
        go_live_at=timezone.now() + datetime.timedelta(days=3),
    )
    page = step(page, Stage.WRITING, editor)
    assert stage_for(page) == Stage.WRITING
    assert not page.approved_schedule


def test_posting_publishes_and_moving_back_unpublishes(idea, editor):
    page = step(idea, Stage.PUBLISHED, editor)
    assert page.live and stage_for(page) == Stage.PUBLISHED
    page = step(page, Stage.WRITING, editor)
    assert not page.live and stage_for(page) == Stage.WRITING


def test_published_pages_cannot_be_cancelled(idea, editor):
    page = step(idea, Stage.PUBLISHED, editor)
    with pytest.raises(PlannerError):
        move(page, Stage.CANCELLED, editor, tok(page))


def test_cancel_never_deletes(idea, editor):
    page = step(idea, Stage.CANCELLED, editor)
    assert Page.objects.filter(pk=page.pk).exists()
    assert PlannerEntry.objects.get(page=page).stage == Stage.CANCELLED


def test_stale_revision_is_refused_and_changes_nothing(idea, editor):
    with pytest.raises(StaleCardError):
        move(idea, Stage.UP_NEXT, editor, "999:0")
    assert stage_for(fresh(idea)) == Stage.IDEA


def test_reviewing_starts_the_wagtail_workflow_when_enabled(
    idea, editor, planner_settings
):
    planner_settings.reviewing_uses_workflow = True
    planner_settings.save()
    page = step(idea, Stage.REVIEWING, editor)
    assert page.workflow_in_progress
    assert stage_for(page) == Stage.REVIEWING
    with pytest.raises(PlannerError):
        move(page, Stage.READY, editor, tok(page))
    page = step(page, Stage.CANCELLED, editor)
    assert not page.workflow_in_progress
    assert stage_for(page) == Stage.CANCELLED


def test_writer_can_move_drafts_but_not_publish(idea, writer):
    page = step(idea, Stage.WRITING, writer)
    assert stage_for(page) == Stage.WRITING
    with pytest.raises(PermissionDenied):
        move(page, Stage.PUBLISHED, writer, tok(page))
    with pytest.raises(PermissionDenied):
        move(page, Stage.READY, writer, tok(page))


def test_every_move_is_logged(idea, editor):
    step(idea, Stage.UP_NEXT, editor)
    step(idea, Stage.WRITING, editor)
    moves = list(
        PageLogEntry.objects.filter(page=idea, action=LOG_ACTION)
        .order_by("timestamp")
        .values_list("data", flat=True)
    )
    assert moves == [
        {"from": "", "to": "idea"},
        {"from": "idea", "to": "up_next"},
        {"from": "up_next", "to": "writing"},
    ]


def test_pages_made_outside_the_planner_default_to_writing(
    blog, editor, planner_settings
):
    page = blog.add_child(instance=BlogPostPage(title="Made in the editor", live=False))
    assert stage_for(fresh(page)) == Stage.WRITING


def test_history_shows_a_readable_message(idea, editor):
    step(idea, Stage.UP_NEXT, editor)
    entry = PageLogEntry.objects.filter(page=idea, action=LOG_ACTION).latest(
        "timestamp"
    )
    assert entry.message == "Planner: Idea → Up next"


def test_page_without_revisions_can_be_moved(blog, editor, planner_settings):
    page = blog.add_child(instance=BlogPostPage(title="No revision yet", live=False))
    assert fresh(page).latest_revision_id is None
    move(page, Stage.UP_NEXT, editor, "0:0")
    assert stage_for(fresh(page)) == Stage.UP_NEXT


def test_writer_cannot_cancel_a_scheduled_publish(idea, editor, writer):
    # Wagtail lets only users who can publish cancel a scheduled publish.
    when = timezone.now() + datetime.timedelta(days=3)
    page = step(idea, Stage.READY, editor, go_live_at=when)
    with pytest.raises(PermissionDenied):
        move(page, Stage.WRITING, writer, tok(page))
    assert fresh(page).approved_schedule


def test_writer_cannot_cancel_someone_elses_workflow(
    idea, editor, writer, planner_settings
):
    planner_settings.reviewing_uses_workflow = True
    planner_settings.save()
    page = step(idea, Stage.REVIEWING, editor)
    with pytest.raises(PermissionDenied):
        move(page, Stage.WRITING, writer, tok(page))
    assert fresh(page).workflow_in_progress


def test_another_editors_lock_blocks_the_planner(idea, editor, writer):
    Page.objects.filter(pk=idea.pk).update(locked=True, locked_by=editor)
    with pytest.raises(PermissionDenied, match="locked"):
        move(idea, Stage.WRITING, writer, tok(idea))
    with pytest.raises(PermissionDenied, match="locked"):
        set_target_date(idea, writer, tok(idea), datetime.date(2026, 12, 1))
    assert stage_for(fresh(idea)) == Stage.IDEA
    # The editor who holds the lock can still move it.
    assert step(idea, Stage.WRITING, editor) and stage_for(fresh(idea)) == Stage.WRITING


def test_stage_only_moves_from_a_stale_board_are_refused(idea, editor):
    # Two boards loaded the same card; neither move creates a page revision.
    loaded = tok(idea)
    move(idea, Stage.UP_NEXT, editor, loaded)
    with pytest.raises(StaleCardError):
        move(idea, Stage.CANCELLED, editor, loaded)
    assert stage_for(fresh(idea)) == Stage.UP_NEXT


def test_target_date_from_a_stale_card_is_refused(idea, editor):
    loaded = tok(idea)
    set_target_date(idea, editor, loaded, datetime.date(2026, 12, 1))
    with pytest.raises(StaleCardError):
        set_target_date(idea, editor, loaded, datetime.date(2026, 12, 24))
    with pytest.raises(StaleCardError):
        move(idea, Stage.WRITING, editor, loaded)
    assert PlannerEntry.objects.get(page=idea).target_date == datetime.date(2026, 12, 1)
