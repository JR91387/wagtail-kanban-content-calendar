# Changelog

## 0.2.0 (2026-11-16)

First version prepared for public release.

- **Licence:** MIT.
- **Supported versions:** Wagtail 7.4 LTS and later, Django 5.2 and later, Python 3.11 and later. Tested on
  Wagtail 7.4 (Django 5.2, 6.0) and 8.1 (Django 6.1), and against Wagtail `main`.
- **All sites:** the Board and Calendar show the current site by default, any other site, or all sites at once,
  where each card names its site. New idea asks which site when there is more than one. The dashboard shows the
  site being browsed and links to the All-sites board.
- **Multilingual sites:** Wagtail's own locale filter appears when `WAGTAIL_I18N_ENABLED` is on; while no locale
  is chosen, each card names its language.
- **Built from more of Wagtail:** the menu is a `ViewSetGroup`; Board and Calendar use Wagtail's listing view, so
  search, filters and in-place refresh come from Wagtail's own header and `w-swap`; the quick view shows Wagtail's
  page status.
- **Wording follows Wagtail:** "Ready to publish" and "Published" (stored code `published`), "page" for "post".
- **Security:** the planner acts only on tracked page types (404 otherwise); no inline event handlers, so strict
  Content Security Policies work.
- **Faster page listings:** the "Planner: <stage>" entries cost one query per listing, not one per page.
- Removed the unused `PlannerEntry.sort_order` field. The initial migration was edited in place, as no earlier
  version was ever released.
- Contributing and security guides, CI and publishing workflows.

## 0.1.1 (2026-11-09)

- Moves check Wagtail's own rights before acting: cancelling a scheduled publish needs publish rights, cancelling
  a workflow needs Wagtail's cancel right, and a page locked by another editor can't be moved or re-dated.
- Unpublish, unschedule and workflow-cancel moves ask for confirmation.
- Cards echo the page's latest revision and the planner entry's version, so writes from a stale board are refused.
- The planner shows only pages the user can edit, filtered in SQL; query counts don't grow with the number of pages.
- Publish-menu moves run in place and return to the editor; the board and calendar update in place.
- The editor header shows "Planner: <stage>"; the dashboard tile shows "scheduled this week".
- Overdue scheduled pages (Wagtail's `publish_scheduled` not running) are flagged.
- Title-only cards, with labels only when something needs attention.

## 0.1.0 (2026-11-09)

First working version: Board with six stage columns plus Cancelled, card quick view, New idea from a per-site
starter text, Calendar month and week views with drag to schedule or set a target date, Publish-menu moves, a
dashboard panel and tile, per-site settings, and the `WAGTAIL_KANBAN_PAGE_MODELS` setting with a system check.
