"""Demo content for the test project: a blog with posts in every planner stage, plus a demo editor."""

import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone
from wagtail.models import Site

from wagtail_kanban_content_calendar.models import PlannerSettings, Stage
from wagtail_kanban_content_calendar.stages import card_token, create_idea, move
from wagtail_kanban_content_calendar.test.models import (
    BlogIndexPage,
    BlogPostPage,
    NewsPage,
)


POSTS = [
    ("Spring product roundup", Stage.IDEA, None),
    ("Interview with our new head chef", Stage.IDEA, None),
    ("Five tips for better photos", Stage.IDEA, 9),
    ("Customer story: a year on", Stage.UP_NEXT, 6),
    ("How we test new recipes", Stage.UP_NEXT, None),
    ("Weekly community update", Stage.WRITING, 12),
    ("Behind the scenes at the workshop", Stage.WRITING, None),
    ("Accessibility checklist for editors", Stage.REVIEWING, None),
    ("Summer opening hours", Stage.READY, "scheduled"),
    ("Volunteer day recap", Stage.READY, None),
    ("Welcome to our new website", Stage.PUBLISHED, None),
    ("Holiday gift guide", Stage.CANCELLED, None),
]


class Command(BaseCommand):
    help = "Create demo blog content in every planner stage (idempotent by title)."

    def handle(self, *args, **options):
        user_model = get_user_model()
        editor = user_model.objects.filter(username="demo").first()
        if editor is None:
            editor = user_model.objects.create_superuser(
                "demo", "demo@example.invalid", "demo-password"
            )
        site = Site.objects.get(is_default_site=True)
        site.site_name = "Demo blog"
        site.save()
        blog = BlogIndexPage.objects.first() or site.root_page.add_child(
            instance=BlogIndexPage(title="Blog", slug="blog")
        )
        settings = PlannerSettings.for_site(site)
        settings.idea_parent_page = blog
        settings.starter_body = "<h2>Hook</h2><p>...</p><h2>Main point</h2><p>...</p><h2>Takeaway</h2><p>...</p>"
        settings.reviewing_uses_workflow = False
        settings.save()
        today = timezone.localdate()
        for i, (title, stage, extra) in enumerate(POSTS):
            if (
                BlogPostPage.objects.filter(title=title).exists()
                or NewsPage.objects.filter(title=title).exists()
            ):
                continue
            model = NewsPage if i % 5 == 4 else BlogPostPage
            target = (
                today + datetime.timedelta(days=extra)
                if isinstance(extra, int)
                else None
            )
            page = create_idea(blog, model, title, editor, target_date=target)
            if stage == Stage.IDEA:
                continue
            go_live = (
                timezone.now() + datetime.timedelta(days=4)
                if extra == "scheduled"
                else None
            )
            move(page, stage, editor, card_token(page), go_live_at=go_live)
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo ready: {len(POSTS)} posts on '{site.site_name}'. Log in as demo / demo-password."
            )
        )
