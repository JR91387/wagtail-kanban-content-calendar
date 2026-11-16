"""Test-only page types: plain Wagtail pages, so the planner is tested without any particular blog app."""

from wagtail import blocks
from wagtail.admin.panels import FieldPanel
from wagtail.fields import RichTextField, StreamField
from wagtail.models import Page


class BlogIndexPage(Page):
    subpage_types = [
        "wagtail_kanban_content_calendar_test.BlogPostPage",
        "wagtail_kanban_content_calendar_test.NewsPage",
    ]


class BlogPostPage(Page):
    body = RichTextField(blank=True)

    content_panels = [*Page.content_panels, FieldPanel("body")]
    parent_page_types = ["wagtail_kanban_content_calendar_test.BlogIndexPage"]


class NewsPage(Page):
    body = StreamField([("paragraph", blocks.RichTextBlock())], blank=True)

    content_panels = [*Page.content_panels, FieldPanel("body")]
    parent_page_types = ["wagtail_kanban_content_calendar_test.BlogIndexPage"]
