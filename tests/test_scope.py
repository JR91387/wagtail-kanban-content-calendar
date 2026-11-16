"""The planner shows only pages the user can edit, at a cost that doesn't grow with the number of pages."""

import pytest

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from wagtail_kanban_content_calendar.stages import create_idea
from wagtail_kanban_content_calendar.test.models import BlogIndexPage, BlogPostPage


def url(name, *args):
    return reverse(f"wagtail_kanban_content_calendar:{name}", args=args)


def queries_for(client, path):
    with CaptureQueriesContext(connection) as captured:
        assert client.get(path).status_code == 200
    return len(captured)


@pytest.mark.parametrize(
    "path",
    [
        url("board"),
        url("calendar"),
        url("calendar") + "?view=week",
        reverse("wagtailadmin_home"),
    ],
)
def test_query_count_does_not_grow_with_pages(
    client, editor, blog, planner_settings, path
):
    client.force_login(editor)
    for n in range(5):
        create_idea(blog, BlogPostPage, f"Post {n}", editor)
    queries_for(
        client, path
    )  # warm Django's content-type cache, so both counts start equal
    small = queries_for(client, path)
    for n in range(5, 45):
        create_idea(blog, BlogPostPage, f"Post {n}", editor)
    assert queries_for(client, path) == small


@pytest.fixture
def private_section(site, editor):
    news = site.root_page.add_child(
        instance=BlogIndexPage(title="Private", slug="private")
    )
    return create_idea(news, BlogPostPage, "Board minutes", editor)


def test_board_and_dashboard_hide_pages_the_user_cannot_edit(
    client, writer, idea, private_section
):
    client.force_login(writer)
    board = client.get(url("board")).content.decode()
    assert "Weekly community update" in board
    assert "Board minutes" not in board
    assert "Board minutes" not in client.get(url("calendar")).content.decode()
    assert (
        "Board minutes" not in client.get(reverse("wagtailadmin_home")).content.decode()
    )


def test_card_of_a_page_the_user_cannot_edit_is_refused(
    client, writer, private_section
):
    client.force_login(writer)
    response = client.get(url("card", private_section.pk) + "?partial=1")
    assert response.status_code == 302
    assert response["Location"] == reverse("wagtailadmin_home")


@pytest.fixture
def second_site(db):
    from wagtail.models import Page, Site

    root = Page.get_first_root_node()
    home = root.add_child(
        instance=BlogIndexPage(title="Second home", slug="second-home")
    )
    return Site.objects.create(
        hostname="second.test", root_page=home, site_name="Second"
    )


@pytest.fixture
def second_site_idea(second_site, editor):
    from wagtail_kanban_content_calendar.models import PlannerSettings
    from wagtail_kanban_content_calendar.stages import create_idea

    blog = second_site.root_page.add_child(
        instance=BlogIndexPage(title="News", slug="news")
    )
    settings = PlannerSettings.for_site(second_site)
    settings.idea_parent_page = blog
    settings.save()
    return create_idea(blog, BlogPostPage, "Second site idea", editor)


def test_board_shows_one_site_by_default(client, editor, idea, second_site_idea):
    client.force_login(editor)
    html = client.get(url("board")).content.decode()
    assert idea.title in html and second_site_idea.title not in html


def test_all_sites_board_lists_every_site_and_names_each(
    client, editor, idea, second_site_idea
):
    client.force_login(editor)
    html = client.get(url("board") + "?site=all").content.decode()
    assert idea.title in html and second_site_idea.title in html
    assert '<span class="w-status">Second</span>' in html


def test_other_site_board(client, editor, idea, second_site, second_site_idea):
    client.force_login(editor)
    html = client.get(url("board") + f"?site={second_site.pk}").content.decode()
    assert second_site_idea.title in html and idea.title not in html
    assert '<span class="w-status">Second</span>' not in html


def test_new_idea_lands_under_the_chosen_sites_parent(
    client, editor, planner_settings, second_site, second_site_idea
):
    client.force_login(editor)
    response = client.post(
        url("new_idea"),
        {
            "title": "Chosen site",
            "page_type": "wagtail_kanban_content_calendar_test.blogpostpage",
            "site": second_site.pk,
        },
    )
    assert response.status_code == 302
    page = BlogPostPage.objects.get(title="Chosen site")
    assert page.get_parent().pk == second_site_idea.get_parent().pk


def test_dashboard_shows_the_browsed_site_and_links_to_all_sites(
    client, editor, idea, second_site_idea
):
    from wagtail_kanban_content_calendar.models import Stage
    from wagtail_kanban_content_calendar.stages import card_token, move

    for page in (idea, second_site_idea):
        move(page, Stage.UP_NEXT, editor, card_token(page))
    client.force_login(editor)
    home = client.get(reverse("wagtailadmin_home")).content.decode()
    # Only the planner panel: Wagtail's own "recent edits" panel lists both pages.
    panel = home.split('class="wkcc-home"')[1].split("Open board")[0]
    assert idea.title in panel and second_site_idea.title not in panel
    assert url("board") + "?site=all" in home


@pytest.fixture
def french_idea(settings, idea, editor):
    from wagtail.models import Locale

    settings.WAGTAIL_I18N_ENABLED = True
    settings.WAGTAIL_CONTENT_LANGUAGES = [("en", "English"), ("fr", "French")]
    french = Locale.objects.create(language_code="fr")
    return create_idea(idea.get_parent(), BlogPostPage, "Idée", editor), french


def test_locale_filter_narrows_the_board_on_multilingual_sites(
    client, editor, french_idea
):
    page, french = french_idea
    page.locale = french
    page.save()
    client.force_login(editor)
    html = client.get(url("board")).content.decode()
    assert (
        'name="locale"' in html
    )  # Wagtail's own locale filter, added by WagtailFilterSet
    assert '<span class="w-status">fr</span>' in html
    narrowed = client.get(url("board") + "?locale=fr").content.decode()
    assert "Idée" in narrowed and "Weekly community update" not in narrowed


def test_page_listing_reads_planner_entries_in_one_query(
    client, editor, blog, planner_settings
):
    """The listing's "Planner: <stage>" entries don't cost a query per page."""
    client.force_login(editor)
    for n in range(12):
        create_idea(blog, BlogPostPage, f"Listed {n}", editor)
    with CaptureQueriesContext(connection) as captured:
        assert (
            client.get(reverse("wagtailadmin_explore", args=[blog.pk])).status_code
            == 200
        )
    planner_queries = [q for q in captured if "plannerentry" in q["sql"]]
    assert len(planner_queries) == 1
