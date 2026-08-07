# year-of-systems

52 weeks, one life system per week, across seven areas: Physical Health, Mind,
Relationships, Emotions, Money, Career, Environment.

A local-only web app. No API key, no CDN, no webfont, no analytics, no outbound request
of any kind. Python stdlib + SQLite + three static files. It runs on OpenHost, in Docker
on the Mac, or as a bare `python3 app.py`.

## Why it tracks installs and not daily checkboxes

`Habits.md` tracked 20 weeks of manual daily ticks and scored **0/7 every single week**.
That experiment is settled, so this app does not repeat it.

The unit here is **"this system is installed"** — a once-a-week state change that stays
changed. There is no daily grid to feed. A system that needs daily maintenance in order
to stay true is the thing this app exists to replace, so it is not the thing this app is.

The failure mode in the *other* direction is an install-only list that quietly accumulates
systems which stopped running months ago. So anything installed more than 30 days ago and
not confirmed since surfaces in a **"still running?"** queue on the Now tab. *Dropped* is
a first-class state, not a failure — a short honest list beats a long list of lies.

## Where it runs

| | 24/7 | HTTPS | Reachable from iPhone |
|---|---|---|---|
| **OpenHost zone** (recommended) | yes | yes, real cert | anywhere |
| Mac via Docker | no — the Mac sleeps (`pmset sleep=1`, `womp=0`) | no | LAN only, while awake |

The Mac copy is the dev loop. OpenHost is the home. A tracker that cannot answer when you
pick up your phone is not a tracker.

### Deploy to OpenHost

```bash
oh app deploy https://github.com/CarlKho-Minerva/year-of-systems --wait
oh app status year-of-systems
oh app logs year-of-systems --follow
```

Lands at `https://year-of-systems.carl.selfhost.imbue.com/`, behind the router's owner
login. After pushing changes:

```bash
oh app reload year-of-systems --update --wait
```

`openhost.toml` requests `sqlite = ["main"]`, so the database lives in the backed-up
permanent tier at `OPENHOST_SQLITE_MAIN`. It deliberately does **not** use the archive
tier — the OpenHost docs warn that its close-to-open consistency can corrupt a SQLite WAL.

No route is listed in `public_paths`, so nothing is reachable without logging in. Do not
add `"/"` there; a year of private notes would be on the open internet.

### Run on the Mac

```bash
docker compose up -d --build      # http://localhost:8765
# or, with no Docker at all:
python3 app.py                    # http://localhost:8765
```

## iPhone home screen

1. Open the app URL in Safari (Chrome cannot install to the home screen on iOS).
2. Share → **Add to Home Screen**.
3. Launch it from the icon. It opens standalone — no browser chrome, own icon.

On the OpenHost URL you may have to log in once *inside* the installed app: iOS gives a
home-screen web app its own storage, so it does not always inherit the Safari session.
Once only.

Offline caching needs a secure context. On the OpenHost HTTPS URL the service worker
registers and the app opens instantly with no signal. Over plain `http://` on the LAN it
will not register — Add to Home Screen still works, the app just needs the network. That
failure is logged to the console and swallowed; it never takes the app down.

## Loading your own 52 systems

Weeks 1–7 ship filled in as **generic starter examples** — one per category, so nothing
is blank and every field has a worked example. They carry a `starter — replace` badge.
They are not anyone's course curriculum; overwrite each as you reach it.

Weeks 8–52 are empty slots with a rotating category, editable in the app.

To bulk-load, write markdown and push it:

```markdown
## Week 3 — The five-name list
category: relations
tool: A note
minutes: 15

Relationships decay silently and on no schedule, so they lose every contest
against work that has a deadline.

- Write the five people you want to still be close to in five years.
- Note the date you last had a real conversation with each.
```

```bash
python3 seed_from_markdown.py my-systems.md --dry-run   # parse and show, send nothing
python3 seed_from_markdown.py my-systems.md             # against localhost:8765
python3 seed_from_markdown.py my-systems.md --overwrite # replace weeks that already have a title
```

It refuses to overwrite a week that already has a title unless you pass `--overwrite`,
and exits non-zero if any item was rejected. A silent partial import is exactly the
failure this system is built not to have.

The seeder posts to `/api/import`, which sits behind owner login on OpenHost — run it
against a local instance and move the SQLite file, or paste into the UI.

## Getting the data out

Nothing is trapped. Settings → Export, or:

- `GET /api/export.md` — markdown, drops straight into the vault
- `GET /api/export.json` — full state

Both are also linked from the app's OpenHost dashboard page.

## Layout

```
app.py                  HTTP server + SQLite + JSON API   (stdlib only)
systems.json            week 1-7 starter seed; 8-52 generated as empty slots
make_icons.py           generates the PWA icons from code, no Pillow
seed_from_markdown.py   bulk import tool
openhost.toml           OpenHost manifest
Dockerfile              alpine + interpreter, no dependency install step
docker-compose.yml      local Mac run
static/                 index.html, app.js, styles.css, sw.js, manifest, icons
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/state` | everything the UI needs, one call |
| POST | `/api/system/{1-52}` | patch any field, status, or steps; returns fresh state |
| POST | `/api/settings` | `{"start_date": "YYYY-MM-DD"}`, snaps to that Monday |
| POST | `/api/import` | `{"systems": [...], "overwrite": bool}` → per-week report |
| GET | `/api/export.md` · `/api/export.json` | downloads |
| GET | `/healthz` | health check, wired to `[routing].health_check` |

## What is not here

The Year of Systems course content itself — its videos, lesson text, and scripts — is Ben
Meer's copyrighted material and is not reproduced or redistributed here. This repo is the
scaffolding: the week structure, the seven categories, and a place to keep your own notes
on what you actually installed and whether it stuck.
