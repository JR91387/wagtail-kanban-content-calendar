from django import forms
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel, PageChooserPanel
from wagtail.contrib.settings.models import BaseSiteSetting, register_setting
from wagtail.fields import RichTextField


class Stage(models.TextChoices):
    IDEA = "idea", _("Idea")
    UP_NEXT = "up_next", _("Up next")
    WRITING = "writing", _("Writing")
    REVIEWING = "reviewing", _("Reviewing")
    READY = "ready", _("Ready to publish")
    PUBLISHED = "published", _("Published")
    CANCELLED = "cancelled", _("Cancelled")


# Stages that only the planner knows about. Published always comes from Wagtail (the page is live),
# and a workflow or a scheduled revision overrides what is stored here (see stages.stage_for).
STORED_STAGES = [s for s in Stage if s != Stage.PUBLISHED]


class PlannerEntry(models.Model):
    """The planner's own state for one page. The page itself is never changed by this table."""

    page = models.OneToOneField(
        "wagtailcore.Page", on_delete=models.CASCADE, related_name="planner_entry"
    )
    stage = models.CharField(
        max_length=20,
        choices=[(s.value, s.label) for s in STORED_STAGES],
        default=Stage.IDEA,
    )
    # Bumped on every planner write; part of the token a card echoes (stages.card_token).
    version = models.PositiveIntegerField(default=0)
    target_date = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = _("planner entry")
        verbose_name_plural = _("planner entries")
        ordering = ["-updated_at"]
        permissions = [("access_planner", _("Can use the content planner"))]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(stage__in=[s.value for s in STORED_STAGES]),
                name="wkcc_plannerentry_stage_valid",
            ),
        ]

    def __str__(self):
        return f"{self.page} ({self.get_stage_display()})"


def tracked_page_type_choices():
    from .conf import model_label, tracked_models

    return [("", _("First tracked type"))] + [
        (model_label(m), m._meta.verbose_name.capitalize()) for m in tracked_models()
    ]


class Weekday(models.IntegerChoices):
    MONDAY = 0, _("Monday")
    SUNDAY = 6, _("Sunday")


@register_setting(icon="calendar-alt")
class PlannerSettings(BaseSiteSetting):
    idea_parent_page = models.ForeignKey(
        "wagtailcore.Page",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name=_("where new ideas go"),
        help_text=_("New ideas are created as draft pages under this page."),
    )
    default_page_type = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("default page type"),
        help_text=_("Page type the New idea form starts with."),
    )
    starter_body = RichTextField(
        blank=True,
        verbose_name=_("starter template"),
        help_text=_("New ideas start with this body."),
    )
    week_starts_on = models.PositiveSmallIntegerField(
        choices=Weekday.choices,
        default=Weekday.SUNDAY,
        verbose_name=_("week starts on"),
    )
    show_cancelled = models.BooleanField(
        default=False, verbose_name=_("show cancelled cards on the board")
    )
    reviewing_uses_workflow = models.BooleanField(
        default=True,
        verbose_name=_("reviewing uses a Wagtail workflow when the section has one"),
    )

    panels = [
        PageChooserPanel("idea_parent_page"),
        FieldPanel(
            "default_page_type", widget=forms.Select(choices=tracked_page_type_choices)
        ),
        FieldPanel("starter_body"),
        FieldPanel("week_starts_on"),
        FieldPanel("show_cancelled"),
        FieldPanel("reviewing_uses_workflow"),
    ]

    class Meta:
        verbose_name = _("content planner")
