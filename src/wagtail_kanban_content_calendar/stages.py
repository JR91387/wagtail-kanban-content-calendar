"""Stage rules: which stage a page is in, and moving it. Every move is Wagtail's own action.

Wagtail's state wins over the planner's stored stage: a live page is Published, a page in a workflow is
Reviewing, a page with a scheduled revision is Ready to publish. Only the rest comes from PlannerEntry.
"""

import datetime

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import CharField, OuterRef, Subquery
from django.db.models.functions import Cast
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from wagtail.actions.publish_page_revision import PublishPageRevisionAction
from wagtail.actions.unpublish_page import UnpublishPageAction
from wagtail.fields import StreamField
from wagtail.locks import BasicLock
from wagtail.log_actions import log
from wagtail.models import Page, Revision
from wagtail.permission_policies.pages import PagePermissionPolicy

from .compat import cancel_workflow, submit_workflow
from .conf import model_config, tracked_models
from .models import PlannerEntry, PlannerSettings, Stage


LOG_ACTION = "wagtail_kanban_content_calendar.move"


class PlannerError(Exception):
    """A move that can't happen as asked. The message is shown to the editor."""


class StaleCardError(PlannerError):
    """The page changed after the board was loaded (optimistic concurrency)."""


def stale_message(page):
    return _(
        "“%(title)s” changed since you loaded the board. Reload to see the latest."
    ) % {"title": page.title}


def card_token(page):
    """What a card echoes back on every write: the page's latest revision and the planner entry's version.

    Content edits bump the first, planner writes (stage, target date) bump the second, so a write from a
    stale board is refused either way.
    """
    entry = entry_for(page)
    return f"{page.latest_revision_id or 0}:{entry.version if entry else 0}"


def with_planner_state(pages):
    """Annotate a page queryset with what stage_for needs, so a board of N cards costs a fixed number of queries."""
    scheduled = Revision.page_revisions.exclude(
        approved_go_live_at__isnull=True
    ).filter(object_id=Cast(OuterRef("pk"), output_field=CharField()))
    return (
        pages.prefetch_workflow_states()
        .annotate_approved_schedule()
        .annotate(
            planner_go_live_at=Subquery(scheduled.values("approved_go_live_at")[:1])
        )
        .select_related(
            "planner_entry", "latest_revision", "owner", "locked_by", "locale"
        )
    )


def planner_pages(user, root=None, model=None):
    """Tracked pages `user` can edit (Wagtail's own rule, as SQL), optionally under one site's root page."""
    models = [model] if model else tracked_models()
    if not models:
        return Page.objects.none()
    editable = PagePermissionPolicy().instances_user_has_any_permission_for(
        user, ["change"]
    )
    pages = Page.objects.type(*models).filter(pk__in=editable.values("pk"))
    if root is not None:
        pages = pages.descendant_of(root)
    return with_planner_state(pages)


# Wagtail clears a revision's approved go-live when publish_scheduled publishes it; one still set this
# long after its time means the command isn't running.
OVERDUE_AFTER = datetime.timedelta(minutes=15)


def overdue_pages(user, root=None):
    """Scheduled pages whose go-live passed OVERDUE_AFTER ago and that Wagtail hasn't published."""
    return planner_pages(user, root).filter(
        planner_go_live_at__lt=timezone.now() - OVERDUE_AFTER
    )


def entry_for(page):
    try:
        return page.planner_entry
    except PlannerEntry.DoesNotExist:
        return None


def stage_for(page):
    if page.live:
        return Stage.PUBLISHED
    if page.workflow_in_progress:
        return Stage.REVIEWING
    if page.approved_schedule:
        return Stage.READY
    entry = entry_for(page)
    return Stage(entry.stage) if entry else Stage.WRITING


def go_live_at(page):
    """When a scheduled page goes live, or None."""
    if hasattr(page, "planner_go_live_at"):
        return page.planner_go_live_at
    revision = page.scheduled_revision
    return revision.approved_go_live_at if revision else None


def _store(page, user, **fields):
    """Write the planner's own state and bump its version. Callers hold the page row lock."""
    entry, created = PlannerEntry.objects.get_or_create(
        page=page, defaults={**fields, "updated_by": user}
    )
    if not created:
        for name, value in fields.items():
            setattr(entry, name, value)
        entry.updated_by = user
        entry.version += 1
        entry.save()
    return entry


def _unschedule(page, user):
    """Same as the editor's "Cancel scheduled publish": clear approved_go_live_at on the revision."""
    revision = page.scheduled_revision
    if revision:
        revision.approved_go_live_at = None
        revision.save(user=user, update_fields=["approved_go_live_at"])


def _leave_wagtail_state(page, current, user):
    """Undo whatever Wagtail state the current stage depends on, so the stored stage applies."""
    if current == Stage.READY:
        _unschedule(page, user)
    elif current == Stage.REVIEWING and page.current_workflow_state:
        cancel_workflow(page, user)


def _locked_for_writing(page, user, expected_token):
    """Lock the page row and check the token, edit rights and Wagtail's page lock. Call inside a transaction."""
    page = Page.objects.select_for_update().get(pk=page.pk).specific
    if card_token(page) != str(expected_token):
        raise StaleCardError(stale_message(page))
    perms = page.permissions_for_user(user)
    if not perms.can_edit():
        raise PermissionDenied(_("You can't edit “%(title)s”.") % {"title": page.title})
    # Only an editor's lock blocks the planner. Wagtail also reports a scheduled page or one in a workflow
    # as locked; leaving those states is checked in move() with Wagtail's own unschedule / cancel rights.
    lock = page.get_lock()
    if isinstance(lock, BasicLock) and lock.for_user(user):
        raise PermissionDenied(
            _("“%(title)s” is locked by %(who)s.")
            % {"title": page.title, "who": lock.get_locked_by(user)}
        )
    return page, perms


def undoes(page):
    """The Wagtail state a move out of the page's current stage takes away, or None.

    "unpublish", "unschedule" or "cancel_workflow": these moves are confirmed before they run.
    """
    stage = stage_for(page)
    if stage == Stage.PUBLISHED:
        return "unpublish"
    if stage == Stage.REVIEWING and page.workflow_in_progress:
        return "cancel_workflow"
    if stage == Stage.READY and page.approved_schedule:
        return "unschedule"
    return None


def overdue_message(count):
    return ngettext(
        "%(count)s scheduled page is past its go-live time and isn't published. Wagtail publishes "
        "scheduled pages only when its publish_scheduled command runs: ask whoever runs the site to "
        "set it up.",
        "%(count)s scheduled pages are past their go-live time and aren't published. Wagtail "
        "publishes scheduled pages only when its publish_scheduled command runs: ask whoever runs "
        "the site to set it up.",
        count,
    ) % {"count": count}


def undo_message(page):
    """What moving the page out of its current stage takes away, said to the editor before they confirm."""
    undo = undoes(page)
    title = page.title
    if undo == "unpublish":
        return _(
            "This unpublishes “%(title)s”: it stops being visible on the site. "
            "You can publish it again from the page editor."
        ) % {"title": title}
    if undo == "unschedule":
        return _("This cancels the scheduled publish of “%(title)s”.") % {
            "title": title
        }
    if undo == "cancel_workflow":
        return _("This cancels the review workflow on “%(title)s”.") % {"title": title}
    return ""


@transaction.atomic
def move(page, to_stage, user, expected_token, go_live_at=None, expire_at=None):
    """Move a page to a stage; returns the stage it ends up in.

    Raises StaleCardError if the page or its planner entry changed since the caller read `card_token`,
    PermissionDenied when the user may not do what the move needs (Wagtail's own rules: edit, publish,
    unpublish, unschedule, cancel workflow, page lock), and PlannerError for a move that doesn't apply.
    Every check runs before any Wagtail action, so a refused move changes nothing.
    """
    page, perms = _locked_for_writing(page, user, expected_token)
    to_stage = Stage(to_stage)
    current = stage_for(page)
    if to_stage == current and go_live_at is None:
        return current
    if current == Stage.PUBLISHED and to_stage == Stage.CANCELLED:
        raise PlannerError(
            _(
                "A published page can't be cancelled. Move it back to Writing to unpublish it first."
            )
        )
    if (
        current == Stage.REVIEWING
        and page.workflow_in_progress
        and to_stage in (Stage.READY, Stage.PUBLISHED)
    ):
        raise PlannerError(
            _("“%(title)s” is in a workflow. Approve it there first.")
            % {"title": page.title}
        )

    if to_stage in (Stage.READY, Stage.PUBLISHED) and not perms.can_publish():
        raise PermissionDenied(
            _("You can't publish “%(title)s”.") % {"title": page.title}
        )
    undo = undoes(page)
    if undo == "unpublish" and not perms.can_unpublish():
        raise PermissionDenied(
            _("You can't unpublish “%(title)s”.") % {"title": page.title}
        )
    if undo == "unschedule" and not perms.can_unschedule():
        raise PermissionDenied(
            _("You can't cancel the scheduled publish of “%(title)s”.")
            % {"title": page.title}
        )
    if undo == "cancel_workflow" and not page.current_workflow_state.user_can_cancel(
        user
    ):
        raise PermissionDenied(
            _("You can't cancel the workflow on “%(title)s”.") % {"title": page.title}
        )

    if current == Stage.PUBLISHED:
        UnpublishPageAction(page, user=user).execute()
    else:
        _leave_wagtail_state(page, current, user)

    settings = PlannerSettings.for_site(page.get_site()) if page.get_site() else None
    if (
        to_stage == Stage.REVIEWING
        and (settings is None or settings.reviewing_uses_workflow)
        and page.get_workflow()
    ):
        submit_workflow(page, user)
    elif to_stage == Stage.PUBLISHED or (to_stage == Stage.READY and go_live_at):
        page.go_live_at = go_live_at if to_stage == Stage.READY else None
        if expire_at:
            page.expire_at = expire_at
        revision = page.save_revision(user=user, log_action=True)
        PublishPageRevisionAction(revision, user=user).execute()
    # Published is never stored (Wagtail's live flag is the truth). Keeping Ready means a page unpublished
    # outside the planner comes back as Ready to publish rather than as an idea.
    _store(page, user, stage=to_stage if to_stage != Stage.PUBLISHED else Stage.READY)

    log(
        instance=page,
        action=LOG_ACTION,
        user=user,
        data={"from": current.value, "to": to_stage.value},
    )
    page.refresh_from_db()
    return stage_for(page)


@transaction.atomic
def set_target_date(page, user, expected_token, value):
    """Set or clear a card's target date, with the same checks as a move."""
    page, _perms = _locked_for_writing(page, user, expected_token)
    stage = stage_for(page)
    # A published page's entry keeps Ready, as in move().
    entry = entry_for(page)
    fields = {"target_date": value}
    if entry is None:
        fields["stage"] = Stage.READY if stage == Stage.PUBLISHED else stage
    _store(page, user, **fields)
    return page


def starter_value(page_model, html):
    """The starter text in the shape the page type's body field expects."""
    config = model_config(page_model)
    field = page_model._meta.get_field(config["body_field"])
    if isinstance(field, StreamField):
        return [(config["starter_block"], html)] if html else []
    return html


@transaction.atomic
def create_idea(parent, page_model, title, user, target_date=None):
    """A new draft page under `parent`, body from the site's starter template, stage Idea."""
    if not parent.permissions_for_user(user).can_add_subpage():
        raise PermissionDenied(
            _("You can't add pages under “%(title)s”.") % {"title": parent.title}
        )
    settings = PlannerSettings.for_site(parent.get_site())
    page = page_model(title=title, live=False, owner=user)
    setattr(
        page,
        model_config(page_model)["body_field"],
        starter_value(page_model, settings.starter_body),
    )
    parent.add_child(instance=page)
    page.save_revision(user=user, log_action=True)
    PlannerEntry.objects.create(
        page=page, stage=Stage.IDEA, target_date=target_date, updated_by=user
    )
    log(
        instance=page,
        action=LOG_ACTION,
        user=user,
        data={"from": "", "to": Stage.IDEA.value},
    )
    return page
