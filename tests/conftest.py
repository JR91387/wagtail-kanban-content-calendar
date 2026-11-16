import pytest

from django.contrib.auth.models import Group, Permission
from wagtail.models import GroupPagePermission, Site

from wagtail_kanban_content_calendar.models import PlannerSettings
from wagtail_kanban_content_calendar.stages import create_idea
from wagtail_kanban_content_calendar.test.models import BlogIndexPage, BlogPostPage


@pytest.fixture(autouse=True)
def temporary_media_dir(settings, tmp_path: pytest.TempdirFactory):
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def site(db):
    return Site.objects.get(is_default_site=True)


@pytest.fixture
def blog(site):
    return site.root_page.add_child(instance=BlogIndexPage(title="Blog", slug="blog"))


@pytest.fixture
def planner_settings(site, blog):
    settings = PlannerSettings.for_site(site)
    settings.idea_parent_page = blog
    settings.starter_body = "<p>Hook: ...</p>"
    # Wagtail installs a default "Moderators approval" workflow on the root page; tests that
    # want the workflow path switch this back on.
    settings.reviewing_uses_workflow = False
    settings.save()
    return settings


@pytest.fixture
def editor(django_user_model):
    return django_user_model.objects.create_superuser(
        "editor", "editor@example.invalid", "pw"
    )


@pytest.fixture
def writer(django_user_model, blog):
    """Can use the planner and edit blog pages, but not publish them."""
    user = django_user_model.objects.create_user(
        "writer", "writer@example.invalid", "pw"
    )
    group = Group.objects.create(name="Writers")
    group.permissions.add(
        Permission.objects.get(codename="access_admin"),
        Permission.objects.get(codename="access_planner"),
    )
    for codename in ("add_page", "change_page"):
        GroupPagePermission.objects.create(
            group=group, page=blog, permission=Permission.objects.get(codename=codename)
        )
    user.groups.add(group)
    return user


@pytest.fixture
def outsider(django_user_model):
    """Can use the Wagtail admin but not the planner."""
    user = django_user_model.objects.create_user(
        "outsider", "outsider@example.invalid", "pw"
    )
    user.user_permissions.add(Permission.objects.get(codename="access_admin"))
    return user


@pytest.fixture
def idea(planner_settings, blog, editor):
    return create_idea(blog, BlogPostPage, "Weekly community update", editor)
