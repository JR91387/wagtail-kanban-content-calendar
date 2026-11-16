"""The planner inside Wagtail's existing screens: page header, Publish menu, page listings, dashboard."""

# wagtail-kanban-content-calendar is written and maintained by Jerry Reinitz, a software engineer
# in Tulsa, Oklahoma, and the founder of Reinitz Industries. Jerry builds software that makes
# everyday work easier for the people who use it. More about Jerry and his work: https://JerryReinitz.com

import datetime

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.translation import gettext as _
from wagtail.admin.action_menu import ActionMenuItem
from wagtail.admin.site_summary import SummaryItem
from wagtail.admin.ui.components import Component
from wagtail.admin.widgets import Button
from wagtail.models import Site

from .conf import PERMISSION, is_tracked
from .filters import ALL_SITES
from .models import Stage
from .stages import (
    card_token,
    entry_for,
    go_live_at,
    overdue_message,
    overdue_pages,
    planner_pages,
    stage_for,
    undo_message,
)


def card_url(page, move_to=None):
    url = reverse("wagtail_kanban_content_calendar:card", args=[page.pk])
    return f"{url}?move={move_to.value}" if move_to else url


def planner_button(page, user, priority=80, stage_tag=False):
    """'Planner: <stage>' in the page header and listing ⋯ menus, for tracked pages only.

    With `stage_tag`, the editor's stage-tag script also shows the stage beside the header's status tag.
    """
    if page.pk is None or not is_tracked(page) or not user.has_perm(PERMISSION):
        return []
    stage = stage_for(page)
    label = _("Planner: %(stage)s") % {"stage": stage.label}
    attrs = (
        {
            "data-wkcc-stage-label": label,
            "data-wkcc-stage-description": _("Content planner stage"),
        }
        if stage_tag
        else None
    )
    return [
        Button(
            label,
            card_url(page),
            icon_name="calendar-alt",
            attrs=attrs,
            priority=priority,
        )
    ]


class MoveActionMenuItem(ActionMenuItem):
    """A Publish-menu entry that runs a planner move and comes back to the editor.

    It posts with Wagtail's own `w-action` controller (as the editor's own Unlock button does). A move
    that undoes Wagtail state asks first, in a Wagtail dialog.
    """

    template_name = "wagtail_kanban_content_calendar/action_menu_item.html"
    move_to = None
    allowed_from = ()

    def is_shown(self, context):
        page = context.get("page")
        if context["view"] != "edit" or page is None or context.get("locked_for_user"):
            return False
        if not is_tracked(page) or not context["request"].user.has_perm(PERMISSION):
            return False
        return stage_for(page) in self.allowed_from

    def get_context_data(self, parent_context):
        context = super().get_context_data(parent_context)
        page = parent_context["page"]
        move_url = reverse("wagtail_kanban_content_calendar:move", args=[page.pk])
        query = urlencode({"to": self.move_to.value, "token": card_token(page)})
        context |= {
            "action_url": f"{move_url}?{query}",
            "undo_message": undo_message(page),
            "dialog_id": f"{self.name}-confirm",
        }
        return context


class MoveToUpNextMenuItem(MoveActionMenuItem):
    name = "wkcc-move-up-next"
    label = _("Move to Up next")
    icon_name = "calendar-alt"
    move_to = Stage.UP_NEXT
    allowed_from = (Stage.IDEA,)


class MoveToReviewingMenuItem(MoveActionMenuItem):
    name = "wkcc-move-reviewing"
    label = _("Move to Reviewing")
    icon_name = "calendar-alt"
    move_to = Stage.REVIEWING
    allowed_from = (Stage.IDEA, Stage.UP_NEXT, Stage.WRITING)


class CancelIdeaMenuItem(MoveActionMenuItem):
    name = "wkcc-cancel"
    label = _("Cancel this idea")
    icon_name = "cross"
    move_to = Stage.CANCELLED
    allowed_from = (
        Stage.IDEA,
        Stage.UP_NEXT,
        Stage.WRITING,
        Stage.REVIEWING,
        Stage.READY,
    )


def request_site_root(request):
    """The dashboard shows the site being browsed, like the Board's default; "All sites" is a link away."""
    site = Site.find_for_request(request)
    return site.root_page if site else None


def dashboard_pages(user, root, today, week_end):
    """Pages the dashboard can show: Up next, or due (scheduled or target) this week. Filtered in SQL."""
    start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
    end = timezone.make_aware(
        datetime.datetime.combine(
            week_end + datetime.timedelta(days=1), datetime.time.min
        )
    )
    return planner_pages(user, root).filter(
        Q(planner_entry__stage=Stage.UP_NEXT)
        | Q(planner_entry__target_date__range=(today, week_end))
        | Q(planner_go_live_at__gte=start, planner_go_live_at__lt=end)
    )


class PlannerPanel(Component):
    name = "content_planner"
    template_name = "wagtail_kanban_content_calendar/home/panel.html"
    order = 120
    limit = 5

    def get_context_data(self, parent_context):
        request = parent_context["request"]
        root = request_site_root(request)
        today = timezone.localdate()
        week_end = today + datetime.timedelta(days=7)
        up_next, this_week = [], []
        for page in dashboard_pages(request.user, root, today, week_end):
            stage = stage_for(page)
            when = go_live_at(page)
            entry = entry_for(page)
            if stage == Stage.UP_NEXT:
                up_next.append((page, entry.target_date if entry else None))
            if when and today <= timezone.localdate(when) <= week_end:
                this_week.append((timezone.localtime(when), page, _("scheduled")))
            elif (
                entry
                and entry.target_date
                and today <= entry.target_date <= week_end
                and stage != Stage.PUBLISHED
            ):
                this_week.append((entry.target_date, page, _("target")))
        this_week.sort(key=lambda row: str(row[0]))
        overdue = overdue_pages(request.user, root).count()
        board_url = reverse("wagtail_kanban_content_calendar:board")
        return {
            "all_sites_url": f"{board_url}?site={ALL_SITES}",
            "overdue_message": overdue_message(overdue) if overdue else "",
            "up_next": up_next[: self.limit],
            "this_week": this_week[: self.limit],
            "board_url": reverse("wagtail_kanban_content_calendar:board"),
            "calendar_url": reverse("wagtail_kanban_content_calendar:calendar"),
        }


class ScheduledSummaryItem(SummaryItem):
    """Posts scheduled to go live in the next 7 days, or how many are overdue (see stages.OVERDUE_AFTER)."""

    order = 450
    template_name = "wagtail_kanban_content_calendar/home/summary_item.html"

    def is_shown(self):
        return self.request.user.has_perm(PERMISSION)

    def get_context_data(self, parent_context):
        user = self.request.user
        root = request_site_root(self.request)
        now = timezone.now()
        return {
            "overdue": overdue_pages(user, root).count(),
            "scheduled": planner_pages(user, root)
            .filter(
                planner_go_live_at__gte=now,
                planner_go_live_at__lt=now + datetime.timedelta(days=7),
            )
            .count(),
            "calendar_url": reverse("wagtail_kanban_content_calendar:calendar"),
        }
