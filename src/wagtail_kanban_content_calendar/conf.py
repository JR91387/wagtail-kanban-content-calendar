"""Which page types the planner tracks, read from the host's Django settings.

    WAGTAIL_KANBAN_PAGE_MODELS = {
        "blog.BlogPage": {"body_field": "body"},
        "news.NewsPage": {"body_field": "content", "starter_block": "paragraph"},  # StreamField body
    }

`body_field` is where a new idea's starter text goes. For a StreamField body, the text is added as one
block of type `starter_block` (default "paragraph", which must accept rich text / HTML).
"""

from django.apps import apps
from django.conf import settings
from django.core import checks
from django.core.exceptions import FieldDoesNotExist
from wagtail.fields import RichTextField, StreamField
from wagtail.models import Page


SETTING = "WAGTAIL_KANBAN_PAGE_MODELS"
PERMISSION = "wagtail_kanban_content_calendar.access_planner"


def raw_config():
    return getattr(settings, SETTING, {})


def tracked_models():
    """Tracked page classes, in the order the setting lists them."""
    return [apps.get_model(label) for label in raw_config()]


def model_label(model):
    return model._meta.label_lower


def model_config(model):
    """Settings for one tracked model; keys are matched case-insensitively ("blog.BlogPage" == "blog.blogpage")."""
    for label, config in raw_config().items():
        if label.lower() == model_label(model):
            return {"starter_block": "paragraph", **config}
    raise LookupError(f"{model_label(model)} is not listed in {SETTING}")


def is_tracked(page):
    return page.specific_class in tracked_models()


@checks.register()
def check_config(app_configs=None, **kwargs):
    errors = []
    if not apps.is_installed("wagtail.contrib.settings"):
        errors.append(
            checks.Error(
                "The content planner needs 'wagtail.contrib.settings' in INSTALLED_APPS.",
                id="wkcc.E001",
            )
        )
    config = raw_config()
    if not config:
        errors.append(
            checks.Warning(
                f"{SETTING} is empty, so the content planner tracks no page types.",
                id="wkcc.W001",
            )
        )
    for label, options in config.items():
        try:
            model = apps.get_model(label)
        except (LookupError, ValueError):
            errors.append(
                checks.Error(
                    f"{SETTING}: '{label}' is not an installed model.", id="wkcc.E002"
                )
            )
            continue
        if not issubclass(model, Page):
            errors.append(
                checks.Error(
                    f"{SETTING}: '{label}' is not a Wagtail page type.", id="wkcc.E003"
                )
            )
            continue
        field_name = options.get("body_field")
        try:
            field = model._meta.get_field(field_name or "")
        except FieldDoesNotExist:
            errors.append(
                checks.Error(
                    f"{SETTING}: '{label}' has no field '{field_name}' (set 'body_field').",
                    id="wkcc.E004",
                )
            )
            continue
        if not isinstance(field, RichTextField | StreamField):
            errors.append(
                checks.Error(
                    f"{SETTING}: '{label}.{field_name}' must be a RichTextField or StreamField.",
                    id="wkcc.E005",
                )
            )
    return errors
