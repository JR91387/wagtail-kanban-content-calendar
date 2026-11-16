# Integration map: how the add-on plugs into Wagtail

**No Wagtail code is changed, overridden or patched.** Everything below is a documented hook, a public class, or
the add-on's own app, following patterns other Wagtail add-ons already use. Host page models are never touched.

Checked against Wagtail **7.4 LTS** and **8.1**. The one module that differs between them is `compat.py`;
`tests/test_wagtail_contract.py` guards every Wagtail name used. Hooks reference:
https://docs.wagtail.org/en/stable/reference/hooks.html

## Screen → Wagtail integration point

| # | Screen or feature | Wagtail hook or API |
|---|---|---|
| 1 | "Content planner" menu with Board and Calendar | `register_admin_viewset` returning a `ViewSetGroup` of two `ViewSet`s (`wagtail_hooks.py`) |
| 2 | Board and Calendar screens | `BaseListingView`: Wagtail's header search, filter drilldown and in-place refresh of `#listing-results` (`w-swap`); results-only URLs for the refresh |
| 3 | Filters: site (or all sites), page type, my pages, show cancelled, locale | `WagtailFilterSet` (`filters.py`); Wagtail adds its own `LocaleFilter` when `WAGTAIL_I18N_ENABLED` is on and more than one locale exists |
| 4 | Quick view, New idea, Schedule and confirm dialogs | Wagtail's `{% dialog %}` component (`w-dialog`); the quick view loads through `w-swap` |
| 5 | Moves between stages | Wagtail's own actions: `save_revision`, `PublishPageRevisionAction`, `UnpublishPageAction`, scheduled publishing (go-live on the revision), workflow submit and cancel (`compat.py`). Permissions from `PagePermissionTester`; page locks from `page.get_lock()` |
| 6 | Stored stage for Idea / Up next / Writing / Cancelled, and target dates | The add-on's own `PlannerEntry` table, one row per page |
| 7 | Stage history | `register_log_actions`: entries in Wagtail's page log, shown in the page's History tab and the site history report |
| 8 | "Planner: <stage>" in the page header ⋯ menu and page listings | `register_page_header_buttons`, `register_page_listing_more_buttons`; `construct_explorer_page_queryset` prefetches the planner entries |
| 9 | Stage tag in the editor header | `insert_editor_js` loads `stage-tag.js`, which copies the ⋯ entry (#8) into a `page-status-tag` beside the side-panel toggles. **This is the only place that reads Wagtail's markup**; if the header has no toggles it does nothing and the ⋯ entry remains. Guarded by the browser check |
| 10 | Move to Up next / Move to Reviewing / Cancel this idea in the Publish menu | `register_page_action_menu_item` with `ActionMenuItem` subclasses, posting with Wagtail's `w-action` controller |
| 11 | Settings → Content planner, per site | `wagtail.contrib.settings`: `BaseSiteSetting` with `@register_setting` |
| 12 | Which page types are tracked | The Django setting `WAGTAIL_KANBAN_PAGE_MODELS`, validated by a system check |
| 13 | Dashboard panel (Up next, This week) and "scheduled this week" tile | `construct_homepage_panels` (a `Component`) and `construct_homepage_summary_items` (a `SummaryItem`), scoped to the site being browsed |
| 14 | Who may use the planner | `register_permissions` ("Can use the content planner") plus Wagtail's page permissions |
| 15 | Reviewing | Wagtail workflows when the page's section has one (per-site setting); otherwise a stored stage |
| 16 | Page status in the quick view | Wagtail's `{% status %}` tag with `page.status_string` |
| 17 | Messages after a move | The `w-messages:add` event on Wagtail's message bar |

## Gaps in Wagtail and how the design avoids them

| # | Gap | Design choice |
|---|---|---|
| 1 | No hook adds a custom side panel to the page editor | Show the stage in the header (#9) and move it from the Publish menu (#10). Wagtail's Status panel keeps showing workflow and schedule state |
| 2 | Page listings can't get a new column from a hook | The listing ⋯ menu (#8), and the Board as the overview |
| 3 | Some page types refuse to save with an empty body | New ideas start from the per-site starter text (#11) |
| 4 | Wagtail has no "cancelled" state | Cancelled lives in the add-on's table (#6); the page stays a draft and is never deleted |

## Out of bounds, by design

- Overriding Wagtail admin templates, monkey-patching Wagtail classes, or adding fields to host page models.
- A separate front-end build inside the admin.
