from django.apps import apps


def test_app_is_installed():
    config = apps.get_app_config("wagtail_kanban_content_calendar")
    assert config.name == "wagtail_kanban_content_calendar"
