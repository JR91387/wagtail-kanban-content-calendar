# Design

## Why

Editorial teams often plan content on a separate kanban tool, which drifts from what is actually in the CMS.
This add-on puts the board and the calendar inside the Wagtail admin, on the real pages, so planning and
publishing are the same act. No maintained Wagtail add-on did this.

## Decisions

| # | Decision |
|---|---|
| 1 | **Every card is a real page.** A new idea is a draft page, created from a per-site starter text, and moved through the stages. |
| 2 | **Any page type.** The tracked page models are named in settings (`WAGTAIL_KANBAN_PAGE_MODELS`). The add-on never depends on a particular blog app. |
| 3 | **Wagtail's state comes first.** Live → Published, workflow in progress → Reviewing, scheduled revision → Ready to publish. The add-on stores only what Wagtail has no state for (Idea, Up next, Writing, Cancelled, a target date) in its own table, one row per page. Host page models are never changed. |
| 4 | **Every move is a Wagtail action**: save a revision, submit or cancel a workflow, schedule, publish, unpublish. Each runs as the acting user, under Wagtail's page permissions and locks, and appears in the page history. |
| 5 | **Two views of the same data:** Board and Calendar, each per site or across all sites, with Wagtail's own search, filters and locale filter. |
| 6 | **Built from Wagtail's admin parts:** viewsets, the generic listing view, the admin's Stimulus controllers (`w-swap`, `w-dialog`, `w-action`, `w-submit`), dialogs, status tags, colour tokens and icons. No separate front-end build. |
| 7 | **Cards are title-only.** The column names the stage; a card adds a small label only when something needs attention (overdue, locked, a go-live, a target date due or missed), or to name its site or language where that is ambiguous. The quick view shows Wagtail's own page status. |
| 8 | **Works without JavaScript.** Every card has a plain Move form; moves, schedules and target dates answer a plain form post with a redirect. |
| 9 | **Database field names follow Django's conventions** (`updated_at`, `target_date`), as every Django app does, so the add-on reads like the rest of a Django project. |

## Invariants (each guarded by a test)

| ID | Invariant | Guarded by |
|---|---|---|
| K1 | Wagtail's state wins: live → Published, workflow → Reviewing, scheduled → Ready to publish; the stored stage only otherwise | `tests/test_invariants.py::test_stage_comes_from_wagtail_first` |
| K2 | Every move is Wagtail's own action, so Wagtail logs it | `test_moves_are_wagtails_own_actions` |
| K3 | Wagtail's dialogs and colour tokens only; no inline event handlers | `test_templates_use_wagtails_dialog`, `test_css_colours_are_wagtail_tokens`, `test_templates_have_no_inline_event_handlers`, stylelint colour rules |
| K4 | Everything works without the script | `test_every_card_renders_its_move_form`, `test_plain_form_posts_work_and_redirect` |
| K5 | The planner acts only on tracked pages the user can edit | `tests/test_views.py::test_card_endpoints_refuse_untracked_pages`, `tests/test_scope.py` |
| K6 | Every Wagtail name the add-on uses still exists and behaves as used | `tests/test_wagtail_contract.py` |

## Refusals

A move is refused, and changes nothing, when the page or its card changed since the board loaded (each card
echoes `"<latest revision id>:<planner entry version>"`), when the user lacks the Wagtail permission the move
needs, or when another editor has locked the page. Moves that unpublish, cancel a scheduled publish or cancel a
workflow ask for confirmation first.

See also `INTEGRATION.md` (each screen and the Wagtail hook behind it) and `CONTENT_FLOW.md` (the lifecycle).
