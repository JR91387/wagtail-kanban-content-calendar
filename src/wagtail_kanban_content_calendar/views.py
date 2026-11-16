import calendar
import datetime
import logging

from dataclasses import dataclass
from functools import cached_property

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.generic import FormView, TemplateView, View
from wagtail.admin.views.generic.base import BaseListingView, WagtailAdminTemplateMixin
from wagtail.models import Page, PageLogEntry, Site

from .conf import PERMISSION, is_tracked, model_label, tracked_models
from .filters import BoardFilterSet, PlannerFilterSet
from .models import PlannerSettings, Stage
from .stages import (
    OVERDUE_AFTER,
    PlannerError,
    StaleCardError,
    card_token,
    create_idea,
    entry_for,
    go_live_at,
    move,
    overdue_message,
    overdue_pages,
    planner_pages,
    set_target_date,
    stage_for,
    undo_message,
    with_planner_state,
)


BOARD_STAGES = [
    Stage.IDEA,
    Stage.UP_NEXT,
    Stage.WRITING,
    Stage.REVIEWING,
    Stage.READY,
    Stage.PUBLISHED,
]
PUBLISHED_DAYS = 30

logger = logging.getLogger(__name__)


# A target date this close (or already past) is called out on the card.
TARGET_SOON = datetime.timedelta(days=2)


@dataclass
class Card:
    page: Page
    stage: Stage
    go_live_at: datetime.datetime | None
    target_date: datetime.date | None
    user: object = None
    # Set only in the All-sites view, where each card names its site.
    site_name: str = ""
    # Set only on multilingual sites when no locale is chosen, where each card names its language.
    locale_code: str = ""

    @property
    def token(self):
        return card_token(self.page)

    @property
    def undo_message(self):
        return undo_message(self.page)

    @property
    def pills(self):
        """What a title-only card calls out, as (kind, text): kind "warning" or "info". Usually nothing."""
        pills = []
        page = self.page
        if page.locked and self.user and page.locked_by_id != self.user.pk:
            who = page.locked_by.get_short_name() or page.locked_by.get_username()
            pills.append(("warning", _("Locked by %(who)s") % {"who": who}))
        if self.go_live_at and self.go_live_at < timezone.now() - OVERDUE_AFTER:
            pills.append(("warning", _("Overdue")))
        elif self.go_live_at and self.stage == Stage.READY:
            when = timezone.localtime(self.go_live_at)
            pills.append(("info", date_format(when, "M j, H:i")))
        elif self.target_date and self.stage not in (Stage.PUBLISHED, Stage.CANCELLED):
            today = timezone.localdate()
            if self.target_date < today:
                pills.append(("warning", _("Past target")))
            elif self.target_date == today:
                pills.append(("info", _("Due today")))
            elif self.target_date <= today + TARGET_SOON:
                pills.append(
                    (
                        "info",
                        _("Due %(day)s") % {"day": date_format(self.target_date, "D")},
                    )
                )
        return pills


def card_for(page, user=None, site_name="", locale_code=""):
    entry = entry_for(page)
    return Card(
        page,
        stage_for(page),
        go_live_at(page),
        entry.target_date if entry else None,
        user,
        site_name,
        locale_code,
    )


class PlannerViewMixin(WagtailAdminTemplateMixin):
    header_icon = "calendar-alt"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_perm(PERMISSION):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumbs_items(self):
        return [
            *self.breadcrumbs_items,
            {
                "url": reverse("wagtail_kanban_content_calendar:board"),
                "label": _("Content planner"),
            },
            {"url": "", "label": self.get_page_title()},
        ]

    def request_site(self):
        return (
            Site.find_for_request(self.request)
            or Site.objects.order_by("-is_default_site", "pk").first()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # In the All-sites view (site None), per-site settings come from the site being browsed.
        settings_site = self.site or self.request_site()
        context |= {
            "site": self.site,
            "planner_settings": PlannerSettings.for_site(settings_site),
            "move_choices": [
                (s.value, s.label) for s in [*BOARD_STAGES, Stage.CANCELLED]
            ],
            "new_idea_form": NewIdeaForm(site=settings_site),
            "schedule_form": ScheduleForm(),
        }
        return context


class PlannerListingView(PlannerViewMixin, BaseListingView):
    """Board and Calendar: Wagtail's listing view, for its header search, filter drilldown and in-place
    refresh (w-swap on #listing-results). The "results" are the board columns or the calendar grid."""

    filterset_class = PlannerFilterSet
    is_searchable = True
    search_fields = ["title"]
    # Plain title matching: the planner's annotated queryset must stay a queryset.
    search_backend_name = None
    paginate_by = None

    def get_filterset_kwargs(self):
        return {**super().get_filterset_kwargs(), "default_site": self.request_site()}

    @cached_property
    def site(self):
        return self.filters.selected_site()

    def get_base_queryset(self):
        return planner_pages(self.request.user)

    @cached_property
    def site_roots(self):
        """(root url_path, site name), most specific first: Wagtail's cached site root paths."""
        names = {s.pk: s.site_name or s.hostname for s in Site.objects.all()}
        return [
            (root.root_path, names[root.site_id]) for root in Site.get_site_root_paths()
        ]

    def card(self, page):
        site_name = ""
        if self.site is None:
            site_name = next(
                (
                    name
                    for root, name in self.site_roots
                    if page.url_path.startswith(root)
                ),
                "",
            )
        locale_code = ""
        if self.filters.filters.get("locale") and not self.request.GET.get("locale"):
            locale_code = page.locale.language_code
        return card_for(page, self.request.user, site_name, locale_code)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["all_sites"] = self.site is None
        if not self.results_only:
            root = self.site.root_page if self.site else None
            overdue = overdue_pages(self.request.user, root).count()
            if overdue:
                messages.warning(self.request, overdue_message(overdue))
        return context


class BoardView(PlannerListingView):
    template_name = "wagtail_kanban_content_calendar/board.html"
    results_template_name = (
        "wagtail_kanban_content_calendar/includes/board_content.html"
    )
    index_url_name = "wagtail_kanban_content_calendar:board"
    index_results_url_name = "wagtail_kanban_content_calendar:board_results"
    filterset_class = BoardFilterSet
    page_title = gettext_lazy("Board")

    def get_base_queryset(self):
        published_since = timezone.now() - datetime.timedelta(days=PUBLISHED_DAYS)
        return (
            super()
            .get_base_queryset()
            .exclude(live=True, last_published_at__lt=published_since)
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        settings = context["planner_settings"]
        show_cancelled = self.request.GET.get(
            "cancelled", "on" if settings.show_cancelled else ""
        ) in ("on", "true", "1")
        columns = {stage: [] for stage in [*BOARD_STAGES, Stage.CANCELLED]}
        for page in context["object_list"]:
            card = self.card(page)
            columns[card.stage].append(card)
        context |= {
            "columns": [(stage, columns[stage]) for stage in BOARD_STAGES],
            "cancelled": columns[Stage.CANCELLED],
            "show_cancelled": show_cancelled,
            "published_days": PUBLISHED_DAYS,
        }
        return context


class CalendarView(PlannerListingView):
    template_name = "wagtail_kanban_content_calendar/calendar.html"
    results_template_name = (
        "wagtail_kanban_content_calendar/includes/calendar_content.html"
    )
    index_url_name = "wagtail_kanban_content_calendar:calendar"
    index_results_url_name = "wagtail_kanban_content_calendar:calendar_results"
    page_title = gettext_lazy("Calendar")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        week_starts_on = context["planner_settings"].week_starts_on
        today = timezone.localdate()
        mode = "week" if self.request.GET.get("view") == "week" else "month"
        try:
            anchor = datetime.date.fromisoformat(self.request.GET.get("date", ""))
        except ValueError:
            anchor = today
        cal = calendar.Calendar(firstweekday=week_starts_on)
        weeks = cal.monthdatescalendar(anchor.year, anchor.month)
        if mode == "week":
            weeks = [next(w for w in weeks if anchor in w)]
            prev_date, next_date = (
                anchor - datetime.timedelta(days=7),
                anchor + datetime.timedelta(days=7),
            )
        else:
            first = anchor.replace(day=1)
            prev_date = (first - datetime.timedelta(days=1)).replace(day=1)
            next_date = (first + datetime.timedelta(days=32)).replace(day=1)
        start, end = weeks[0][0], weeks[-1][-1]

        by_day, no_date, no_target = {}, [], []
        for page in context["object_list"]:
            card = self.card(page)
            if card.stage == Stage.PUBLISHED:
                day, kind = (
                    timezone.localdate(page.last_published_at)
                    if page.last_published_at
                    else None,
                    "published",
                )
            elif card.go_live_at:
                day, kind = timezone.localdate(card.go_live_at), "scheduled"
            elif card.target_date:
                day, kind = card.target_date, "target"
            else:
                if card.stage == Stage.READY:
                    no_date.append(card)
                elif card.stage != Stage.CANCELLED:
                    no_target.append(card)
                continue
            if day and start <= day <= end:
                by_day.setdefault(day, []).append((kind, card))
        # Calendar navigation keeps the current filters.
        query = self.request.GET.copy()
        for name in ("view", "date", "_w_filter_fragment"):
            query.pop(name, None)
        context |= {
            "mode": mode,
            "anchor": anchor,
            "today": today,
            "weeks": [[(day, by_day.get(day, [])) for day in week] for week in weeks],
            "weekday_names": [
                calendar.day_abbr[(week_starts_on + i) % 7] for i in range(7)
            ],
            "prev_date": prev_date,
            "next_date": next_date,
            "filter_query": query.urlencode(),
            "ready_no_date": no_date,
            "no_target": no_target,
        }
        return context


class CardView(PlannerViewMixin, TemplateView):
    template_name = "wagtail_kanban_content_calendar/card.html"

    def get_template_names(self):
        if self.request.GET.get("partial"):
            return ["wagtail_kanban_content_calendar/includes/card_detail.html"]
        return [self.template_name]

    def get_page_title(self):
        return self.page.title

    def dispatch(self, request, *args, **kwargs):
        self.page = tracked_page_or_404(kwargs["page_id"])
        if not self.page.permissions_for_user(request.user).can_edit():
            raise PermissionDenied
        self.site = self.page.get_site()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        page = with_planner_state(Page.objects.filter(pk=self.page.pk).specific()).get()
        confirm = self.request.GET.get("move")
        edit_url = reverse("wagtailadmin_pages:edit", args=[page.pk])
        context |= {
            "card": card_for(page, self.request.user),
            "confirm_stage": Stage(confirm) if confirm in Stage.values else None,
            "confirm_next": safe_next(self.request, self.request.GET.get("next"))
            or edit_url,
            # The quick view is fetched into a dialog; its Move… form returns to the board.
            "move_next": reverse("wagtail_kanban_content_calendar:board")
            if self.request.GET.get("partial")
            else self.request.get_full_path(),
            "edit_url": edit_url,
            "log_entries": PageLogEntry.objects.filter(page=page)
            .select_related("user")
            .order_by("-timestamp")[:5],
        }
        return context


class NewIdeaForm(forms.Form):
    title = forms.CharField(label=gettext_lazy("Title"), max_length=255)
    page_type = forms.ChoiceField(label=gettext_lazy("Page type"))
    target_date = forms.DateField(
        label=gettext_lazy("Target date"),
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    site = forms.ModelChoiceField(
        label=gettext_lazy("Site"),
        queryset=Site.objects.order_by("site_name", "hostname"),
        empty_label=None,
    )

    def __init__(self, *args, site=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["page_type"].choices = [
            (model_label(m), m._meta.verbose_name.capitalize())
            for m in tracked_models()
        ]
        if self.fields["site"].queryset.count() == 1:
            self.fields["site"].widget = forms.HiddenInput()
        if site is not None:
            self.fields["site"].initial = site.pk
            default = PlannerSettings.for_site(site).default_page_type.lower()
            if default:
                self.fields["page_type"].initial = default

    def page_model(self):
        return next(
            m
            for m in tracked_models()
            if model_label(m) == self.cleaned_data["page_type"]
        )


class NewIdeaView(PlannerViewMixin, FormView):
    form_class = NewIdeaForm
    template_name = "wagtail_kanban_content_calendar/new_idea.html"
    page_title = gettext_lazy("New idea")

    def get_form_kwargs(self):
        self.site = self.request_site()
        return {**super().get_form_kwargs(), "site": self.site}

    def form_valid(self, form):
        site = form.cleaned_data["site"]
        settings = PlannerSettings.for_site(site)
        parent = (
            settings.idea_parent_page.specific if settings.idea_parent_page else None
        )
        if parent is None:
            form.add_error(
                None,
                _("Choose where new ideas go in Settings > Content planner first."),
            )
            return self.form_invalid(form)
        model = form.page_model()
        if model not in parent.specific_class.creatable_subpage_models():
            form.add_error(
                "page_type",
                _("“%(type)s” pages can't be added under “%(parent)s”.")
                % {"type": model._meta.verbose_name, "parent": parent.title},
            )
            return self.form_invalid(form)
        page = create_idea(
            parent,
            model,
            form.cleaned_data["title"],
            self.request.user,
            form.cleaned_data["target_date"],
        )
        messages.success(
            self.request, _("Idea “%(title)s” created.") % {"title": page.title}
        )
        return redirect(
            f"{reverse('wagtail_kanban_content_calendar:board')}?site={site.pk}"
        )


class ScheduleForm(forms.Form):
    go_live_at = forms.DateTimeField(
        label=gettext_lazy("Go-live"),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )
    expire_at = forms.DateTimeField(
        label=gettext_lazy("Expiry (optional)"),
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )
    token = forms.CharField(widget=forms.HiddenInput)

    def clean_go_live_at(self):
        value = self.cleaned_data["go_live_at"]
        if value <= timezone.now():
            raise forms.ValidationError(
                _(
                    "Go-live must be in the future. To publish straight away, move it to Published."
                )
            )
        return value


class MoveForm(forms.Form):
    to = forms.ChoiceField(choices=[(s.value, s.label) for s in Stage])
    token = forms.CharField()


def tracked_page_or_404(page_id):
    """The page, if it exists and is a type the planner tracks; the planner acts on nothing else."""
    page = get_object_or_404(Page, pk=page_id).specific
    if not is_tracked(page):
        raise Http404
    return page


def safe_next(request, url):
    """`url` if it points back into this site, else None."""
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}):
        return url
    return None


class CardActionView(View):
    """Base for POST endpoints on one card: answers JSON to the board's script, redirects otherwise."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_perm(PERMISSION):
            raise PermissionDenied
        self.page = tracked_page_or_404(kwargs["page_id"])
        self.data = request.POST
        return super().dispatch(request, *args, **kwargs)

    def wants_json(self):
        return "application/json" in self.request.headers.get("Accept", "")

    def next_url(self):
        return safe_next(self.request, self.data.get("next")) or reverse(
            "wagtail_kanban_content_calendar:board"
        )

    def respond(self, ok, message, status=200, stage=None):
        if self.wants_json():
            # The board script shows the message in Wagtail's message bar.
            return JsonResponse(
                {"ok": ok, "message": message, "stage": stage}, status=status
            )
        (messages.success if ok else messages.error)(self.request, message)
        return redirect(self.next_url())

    def needs_confirmation(self, to_stage):
        """A move that undoes Wagtail state runs only with confirm=1; returns the refusal, or None.

        The board script confirms in a dialog first; without the script, the editor gets the card's
        confirm page.
        """
        if self.data.get("confirm") == "1":
            return None
        message = undo_message(self.page)
        if not message or Stage(to_stage) == stage_for(self.page):
            return None
        if self.wants_json():
            return JsonResponse(
                {"ok": False, "message": message, "confirm": True}, status=400
            )
        query = urlencode({"move": Stage(to_stage).value, "next": self.next_url()})
        card = reverse("wagtail_kanban_content_calendar:card", args=[self.page.pk])
        return redirect(f"{card}?{query}")

    def refuse(self, error, status, to_stage, token):
        logger.warning(
            "Planner move refused (%s): page=%s user=%s to=%s token=%s: %s",
            status,
            self.page.pk,
            self.request.user.pk,
            to_stage,
            token,
            error,
        )
        message = str(error) or _("You don't have permission for that move.")
        return self.respond(False, message, status=status)

    def run(self, action, to_stage, token):
        """Run a stages write and turn its refusals into 409 / 403 / 400 answers."""
        try:
            return action(), None
        except StaleCardError as error:
            return None, self.refuse(error, 409, to_stage, token)
        except PermissionDenied as error:
            return None, self.refuse(error, 403, to_stage, token)
        except PlannerError as error:
            return None, self.refuse(error, 400, to_stage, token)

    def run_move(self, to_stage, token, **kwargs):
        stage, refused = self.run(
            lambda: move(self.page, to_stage, self.request.user, token, **kwargs),
            to_stage,
            token,
        )
        if refused:
            return refused
        return self.respond(
            True,
            _("“%(title)s” is now %(stage)s.")
            % {"title": self.page.title, "stage": stage.label},
            stage=stage.value,
        )


class MoveView(CardActionView):
    def post(self, request, page_id):
        # The editor's Publish-menu items post with Wagtail's w-action controller, which sends only the
        # CSRF token and `next`; the move itself is in the URL.
        self.data = request.POST.copy()
        for name in ("to", "token", "confirm"):
            if name not in self.data and name in request.GET:
                self.data[name] = request.GET[name]
        form = MoveForm(self.data)
        if not form.is_valid():
            return self.respond(False, _("That move wasn't understood."), status=400)
        to_stage = form.cleaned_data["to"]
        return self.needs_confirmation(to_stage) or self.run_move(
            to_stage, form.cleaned_data["token"]
        )


class ScheduleView(CardActionView):
    def post(self, request, page_id):
        form = ScheduleForm(request.POST)
        if not form.is_valid():
            return self.respond(
                False,
                " ".join(e for errors in form.errors.values() for e in errors),
                status=400,
            )
        return self.needs_confirmation(Stage.READY) or self.run_move(
            Stage.READY,
            form.cleaned_data["token"],
            go_live_at=form.cleaned_data["go_live_at"],
            expire_at=form.cleaned_data["expire_at"],
        )


class TargetDateView(CardActionView):
    def post(self, request, page_id):
        try:
            raw = request.POST.get("target_date", "")
            value = datetime.date.fromisoformat(raw) if raw else None
        except ValueError:
            return self.respond(False, _("That date wasn't understood."), status=400)
        token = request.POST.get("token", "")
        _page, refused = self.run(
            lambda: set_target_date(self.page, request.user, token, value),
            "target_date",
            token,
        )
        if refused:
            return refused
        return self.respond(
            True, _("Target date for “%(title)s” set.") % {"title": self.page.title}
        )
