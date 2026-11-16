# Settings

## Developer setting

| Setting | Default | What it does |
|---|---|---|
| `WAGTAIL_KANBAN_PAGE_MODELS` | `{}` | Page models to track: `"app_label.ModelName": {"body_field": ..., "starter_block": ...}`. `body_field` must be a RichTextField or StreamField; `starter_block` (default `paragraph`) is the StreamField block a new idea's text goes into. |

## Per site: Settings → Content planner

| Option | What it does |
|---|---|
| Where new ideas go | The parent page new ideas are created under |
| Default page type | The type the New idea form starts with |
| Starter template | The body every new idea starts with |
| Week starts on | Sunday or Monday |
| Show cancelled cards on the board | Opens the Cancelled section by default |
| Reviewing uses a Wagtail workflow | Moving to Reviewing submits the page to its section's workflow; off makes Reviewing a plain stage |
