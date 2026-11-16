"""The Board and Calendar filters, shown in Wagtail's own filter drilldown.

WagtailFilterSet adds Wagtail's locale filter by itself when WAGTAIL_I18N_ENABLED is on and more than one
locale exists.
"""

import django_filters

from django import forms
from django.utils.translation import gettext_lazy as _
from wagtail.admin.filters import WagtailFilterSet
from wagtail.models import Page, Site

from .conf import model_label, tracked_models


ALL_SITES = "all"


def site_choices():
    return [(ALL_SITES, _("All sites"))] + [
        (str(site.pk), site.site_name or site.hostname)
        for site in Site.objects.order_by("site_name", "hostname")
    ]


def page_type_choices():
    return [
        (model_label(m), m._meta.verbose_name.capitalize()) for m in tracked_models()
    ]


class PlannerFilterSet(WagtailFilterSet):
    site = django_filters.ChoiceFilter(
        label=_("Site"),
        choices=site_choices,
        empty_label=None,
        widget=forms.RadioSelect,
        method="filter_site",
    )
    page_type = django_filters.ChoiceFilter(
        label=_("Page type"),
        choices=page_type_choices,
        empty_label=_("All"),
        widget=forms.RadioSelect,
        method="filter_page_type",
    )
    mine = django_filters.BooleanFilter(
        label=_("My pages only"),
        widget=forms.CheckboxInput,
        initial=False,  # unticked is the default, so Wagtail shows no "active filter" for it
        method="filter_mine",
    )

    class Meta:
        model = Page
        fields = []

    def __init__(self, data=None, *args, default_site=None, **kwargs):
        # No site in the URL means the current site. "All sites" is an explicit value, so it survives
        # Wagtail dropping empty parameters from the address bar.
        if default_site and data is not None and "site" not in data:
            data = data.copy()
            data["site"] = str(default_site.pk)
        super().__init__(data, *args, **kwargs)
        if default_site:
            self.form.fields["site"].initial = str(default_site.pk)

    def filter_site(self, queryset, name, value):
        if value == ALL_SITES:
            return queryset
        return queryset.descendant_of(Site.objects.get(pk=value).root_page)

    def filter_page_type(self, queryset, name, value):
        model = next(m for m in tracked_models() if model_label(m) == value)
        return queryset.type(model)

    def filter_mine(self, queryset, name, value):
        return queryset.filter(owner=self.request.user) if value else queryset

    def selected_site(self):
        """The chosen Site, or None for all sites."""
        value = self.form.cleaned_data.get("site") if self.is_valid() else None
        if not value or value == ALL_SITES:
            return None
        return Site.objects.get(pk=value)


class BoardFilterSet(PlannerFilterSet):
    cancelled = django_filters.BooleanFilter(
        label=_("Show cancelled"),
        widget=forms.CheckboxInput,
        initial=False,  # unticked is the default, so Wagtail shows no "active filter" for it
        method="keep_all",
    )

    def keep_all(self, queryset, name, value):
        # Cancelled cards are always fetched; this only opens or closes the board's Cancelled section.
        return queryset
