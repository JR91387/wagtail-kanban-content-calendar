# FAQ

**Does it work with my blog app?** Yes, if its posts are Wagtail pages with a rich-text or StreamField body. Name
the page model in `WAGTAIL_KANBAN_PAGE_MODELS`.

**Does it change my page models?** No. The planner keeps its own small table, one row per page.

**Why didn't my scheduled page go live?** Wagtail publishes scheduled pages only when its `publish_scheduled`
command runs. The board, calendar and dashboard warn when one is more than 15 minutes overdue.

**Who can move cards?** Users with "Can use the content planner", and then only as far as Wagtail's own page
permissions allow: editing, publishing, unpublishing and cancelling workflows each need the usual rights.

**Is anything ever deleted?** No. Cancelled is a stage; the page stays a draft.

**Does it work without JavaScript?** Yes. Every card has a plain Move form, and the filters work as a plain form.
