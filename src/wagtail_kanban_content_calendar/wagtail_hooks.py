from django.contrib.auth.models import Permission
from django.templatetags.static import static
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.admin.menu import MenuItem
from wagtail.admin.viewsets.base import ViewSet, ViewSetGroup
from wagtail.log_actions import LogFormatter

from . import integration, views
from .conf import PERMISSION
from .models import Stage
from .stages import LOG_ACTION


class PlannerMenuItem(MenuItem):
    def is_shown(self, request):
        return request.user.has_perm(PERMISSION)


class BoardViewSet(ViewSet):
    """All planner screens and endpoints, under one URL namespace; its menu item opens the Board."""

    name = "wagtail_kanban_content_calendar"
    url_prefix = "content-planner"
    menu_label = _("Board")
    icon = "table"
    menu_item_class = PlannerMenuItem

    def get_urlpatterns(self):
        return [
            path("board/", views.BoardView.as_view(), name="board"),
            path(
                "board/results/",
                views.BoardView.as_view(results_only=True),
                name="board_results",
            ),
            path("calendar/", views.CalendarView.as_view(), name="calendar"),
            path(
                "calendar/results/",
                views.CalendarView.as_view(results_only=True),
                name="calendar_results",
            ),
            path("ideas/new/", views.NewIdeaView.as_view(), name="new_idea"),
            path("card/<int:page_id>/", views.CardView.as_view(), name="card"),
            path("card/<int:page_id>/move/", views.MoveView.as_view(), name="move"),
            path(
                "card/<int:page_id>/schedule/",
                views.ScheduleView.as_view(),
                name="schedule",
            ),
            path(
                "card/<int:page_id>/target-date/",
                views.TargetDateView.as_view(),
                name="target_date",
            ),
        ]


class CalendarViewSet(ViewSet):
    """The Calendar's menu item. Its view lives in BoardViewSet, so every planner URL shares one namespace."""

    name = "wagtail_kanban_content_calendar_calendar"
    menu_label = _("Calendar")
    icon = "date"
    menu_item_class = PlannerMenuItem

    @property
    def menu_url(self):
        return reverse("wagtail_kanban_content_calendar:calendar")

    def get_urlpatterns(self):
        return []


class PlannerViewSetGroup(ViewSetGroup):
    items = (BoardViewSet, CalendarViewSet)
    menu_label = _("Content planner")
    menu_icon = "calendar-alt"
    menu_order = 350
    add_to_admin_menu = True


@hooks.register("register_admin_viewset")
def register_planner_viewsets():
    return PlannerViewSetGroup()


@hooks.register("register_permissions")
def register_planner_permission():
    return Permission.objects.filter(
        content_type__app_label="wagtail_kanban_content_calendar",
        codename="access_planner",
    )


@hooks.register("register_log_actions")
def register_planner_log_actions(actions):
    @actions.register_action(LOG_ACTION)
    class PlannerMoveFormatter(LogFormatter):
        label = _("Planner stage change")

        def format_message(self, log_entry):
            data = log_entry.data
            to_label = Stage(data["to"]).label if data.get("to") else ""
            if not data.get("from"):
                return _("Planner: created as %(to)s") % {"to": to_label}
            return _("Planner: %(from)s → %(to)s") % {
                "from": Stage(data["from"]).label,
                "to": to_label,
            }


@hooks.register("register_page_header_buttons")
def planner_header_button(page, user, view_name=None, next_url=None):
    return integration.planner_button(page, user, stage_tag=view_name == "edit")


@hooks.register("insert_editor_js")
def planner_editor_js():
    return format_html(
        '<script src="{}" defer></script>',
        static("wagtail_kanban_content_calendar/js/stage-tag.js"),
    )


@hooks.register("register_page_listing_more_buttons")
def planner_listing_button(page, user, next_url=None, **kwargs):
    return integration.planner_button(page, user)


@hooks.register("register_page_action_menu_item")
def planner_up_next_menu_item():
    return integration.MoveToUpNextMenuItem(order=60)


@hooks.register("register_page_action_menu_item")
def planner_reviewing_menu_item():
    return integration.MoveToReviewingMenuItem(order=61)


@hooks.register("register_page_action_menu_item")
def planner_cancel_menu_item():
    return integration.CancelIdeaMenuItem(order=62)


@hooks.register("construct_homepage_panels")
def planner_dashboard_panel(request, panels):
    if request.user.has_perm(PERMISSION):
        panels.append(integration.PlannerPanel())


@hooks.register("construct_homepage_summary_items")
def planner_summary_item(request, items):
    items.append(integration.ScheduledSummaryItem(request))


@hooks.register("construct_explorer_page_queryset")
def planner_listing_queryset(parent_page, pages, request):
    # The listing's "Planner: <stage>" entries read each page's planner entry; fetch them in the same query.
    return pages.prefetch_related("planner_entry")
