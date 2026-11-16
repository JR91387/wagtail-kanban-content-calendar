# Installation

Requires Python 3.11+, Django 5.2+ and Wagtail 7.4 LTS or later.

1. `pip install wagtail-kanban-content-calendar`
2. Add to `INSTALLED_APPS`, with Wagtail's settings app:

   ```python
   INSTALLED_APPS = [
       # ...
       "wagtail.contrib.settings",
       "wagtail_kanban_content_calendar",
   ]
   ```

3. Name the page types to track and the field a new idea's starter text goes into:

   ```python
   WAGTAIL_KANBAN_PAGE_MODELS = {
       "blog.BlogPage": {"body_field": "body"},  # RichTextField
       "news.NewsPage": {
           "body_field": "content",
           "starter_block": "paragraph",
       },  # StreamField
   }
   ```

4. `python manage.py migrate`, then `python manage.py check` (it reports a misconfigured setting).
5. In the admin: **Settings → Groups**, give editors **"Can use the content planner"**; **Settings → Content
   planner**, choose *Where new ideas go* for each site.
6. Run Wagtail's `publish_scheduled` command every few minutes (for example from cron). Scheduled pages go live
   only when it runs; the planner warns when a scheduled page is more than 15 minutes overdue.
