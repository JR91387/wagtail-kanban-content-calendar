# Contributing

Bug reports and pull requests are welcome. For a larger change, open an issue first so we can agree on the
approach.

## Set up

```bash
git clone https://github.com/JR91387/wagtail-kanban-content-calendar.git
cd wagtail-kanban-content-calendar
python -m venv .venv && . .venv/bin/activate
pip install -e . --group dev
npm install                       # prettier and stylelint, with Wagtail's own config
```

## Test and lint

```bash
pytest                            # SQLite
DATABASE_URL=postgres://user:pass@localhost:5432/db pytest
uvx --with tox-uv tox             # every supported Wagtail and Django version
ruff check . && ruff format --check .
npm run lint
python testmanage.py check
python testmanage.py makemigrations --check --dry-run
```

A demo project is included: `python testmanage.py migrate && python testmanage.py createcachetable &&
python testmanage.py planner_demo`, then `python testmanage.py runserver` and log in as `demo` / `demo-password`.

## What a pull request needs

- Tests for the behaviour it changes. Moves must stay Wagtail's own actions (`tests/test_invariants.py`).
- Wagtail's admin building blocks only: templates, documented hooks, the admin's Stimulus controllers and colour
  tokens. No front-end build step, no new JavaScript dependencies.
- No inline event handlers in templates; everything works without JavaScript.
- If it uses a Wagtail name the add-on didn't use before, add a check to `tests/test_wagtail_contract.py`. If that
  name differs between supported Wagtail versions, route it through `compat.py`.
- A line in `CHANGELOG.md`.

## Supported versions

Every Wagtail release that still receives security fixes, from the oldest LTS up
([Wagtail's release schedule](https://github.com/wagtail/wagtail/wiki/Release-schedule)), with the Django and
Python versions each supports. When a Wagtail LTS reaches end of life, the next release raises the floor.

## Deprecations

From the first public release on, a renamed or removed setting, field, URL or template keeps working for one
further release and raises a `DeprecationWarning` that names its replacement. The change is listed in
`CHANGELOG.md`.
