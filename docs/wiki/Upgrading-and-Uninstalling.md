# Upgrading and uninstalling

- **The add-on**: `pip install -U wagtail-kanban-content-calendar`, then `python manage.py migrate`. See the
  changelog for what changed.
- **Wagtail**: the add-on uses only documented hooks and public APIs and changes no Wagtail code, templates or
  models. Each release is tested on the oldest supported Wagtail LTS, the latest release and Wagtail `main`.
- **Removing it**: `python manage.py migrate wagtail_kanban_content_calendar zero`, then take it out of
  `INSTALLED_APPS`. Your pages are untouched; the add-on never stores anything on them.
