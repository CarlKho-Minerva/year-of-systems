# year-of-systems

52 weeks, one life system per week — plus a reader for the course's 61 lessons.

The course's real shape is **11 modules**, which is *not* the seven areas the sales page
advertises: Course Orientation (5 lessons), Starter Pack (12), Physical Health (5),
Emotions (4), Mind (5), Relationships (4), Career (8), Money (5), Environment (9), Bonus
(3), Graduation (1). Weeks 1–12 are a mixed Starter Pack that cuts across every area, so
the tracker's categories mirror the modules rather than the marketing.

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

## The course reader

The **Course** tab holds the lessons: modules → lessons → body text, video link,
downloadable assets, and a notes field per lesson. Each lesson can be linked to a week,
so the lesson and its "did I actually install this" state are one record. Lessons are
deep-linkable (`#course/12`) and read offline once cached.

**Lesson content lives in SQLite on the zone and never in this repo.** The repo is
public and the lesson text is not mine or yours to redistribute. This is structural, not
a convention: no code path writes a lesson body to a file in the repo, and
`/api/export-notes.md` deliberately exports *your notes only*, with lesson titles for
context, so an export can never carry the course text into the vault or a commit.

Re-importing after the course is updated **never overwrites your notes.** Lessons are
matched on `source_url`, so a re-scrape updates titles and bodies in place and leaves
your writing and week links untouched. That is the one irreplaceable thing in the
database, and the import is built so it cannot be destroyed by a re-run.

```bash
POST /api/course/import
{"modules":[{"title":"...","lessons":[
  {"title":"...","body":"...","video_url":"...","source_url":"...",
   "assets":[{"name":"Workbook","url":"..."}]}]}]}
```

The response reports `lessons_new`, `lessons_updated`, and `notes_preserved`.

## Loading the course

Scrape it with the Claude Chrome extension, clean it, then import:

```bash
# 1. In Chrome, logged into the course: extract via javascript_tool using same-origin
#    fetch (61 pages, not 61 navigations). Paginate EVERY module's category page with
#    ?page=N — the syllabus hides Wk 11-12 behind "Show More" and you silently get 59.
# 2. Clean the scrape. Exits non-zero naming any lesson it could not clean.
python3 clean_export.py ~/Downloads/yos-course-export.json /tmp/yos-course-clean.json

# 3. Import. The `--` is REQUIRED or oh's argparse eats -X.
oh curl -- -sS -X POST -H "Content-Type: application/json" \
  --data-binary @/tmp/yos-course-clean.json \
  "https://year-of-systems.carl.selfhost.imbue.com/api/course/import"
```

A lesson titled `Wk 8: Weekly Meal Plan` **is** week 8, so the import derives the link
from the title and populates the tracker: title, summary, category from the module, and
setup steps parsed from the `Step N:` lines. That is what keeps the reader and the
tracker one system instead of two lists that drift.

Three orientation lessons are video-only and have no body text. That is correct, not a
scrape failure — the cleaner only errors when a lesson has neither text nor video.

To write your own weeks instead, `seed_from_markdown.py` takes
`## Week 3 — Title` headings with optional `category:`/`tool:`/`minutes:` lines, bullet
steps, and prose. It refuses to overwrite a week that already has a title unless you pass
`--overwrite`, and exits non-zero if anything was rejected.

## The weekly nudge

A single recurring Google Calendar event, written through the API — Mondays 08:00,
51 occurrences, through week 52.

```bash
~/.local/venvs/gmail-mcp/bin/python ~/CODELocalProjects/lifeos/gcal.py upsert \
  --key yos-weekly --calendar primary \
  --summary "Year of Systems — install this week's system" \
  --start 2026-08-10T08:00 --rrule "FREQ=WEEKLY;BYDAY=MO;COUNT=51" \
  --tz America/Los_Angeles --url "https://year-of-systems.carl.selfhost.imbue.com/"
```

`--key` makes it idempotent: the event is looked up by that key before writing, so
re-running updates the existing event instead of stacking a duplicate every time.

This replaced two worse designs, in order. First a launchd job writing an Apple Reminder
— Carl runs his life off Google Calendar and does not check a reminders list, so that
landed where he would never see it. Then a generated `.ics`, which was no better: `open`
launches Apple Calendar, still the wrong app, and it interrupts him to do by hand what an
API does silently. Writing to the Google Calendar API is the only version that puts the
nudge where he looks without taking over his screen.

A single RRULE also removes the machinery entirely. A job that must fire 52 times is 52
chances to die silently; a recurrence is evaluated by the calendar itself, so there is no
process to monitor and nothing to rot.

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
clean_export.py         turns a raw Kajabi scrape into importable JSON
seed_from_markdown.py   bulk import tool for your own weeks
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
| GET | `/api/course` | module + lesson tree, **without** bodies (small enough for a phone) |
| GET | `/api/lesson/{id}` | one lesson: body, video, assets, notes, prev/next |
| POST | `/api/lesson/{id}` | `{"notes": "...", "week": 1-52\|null}` |
| POST | `/api/course/import` | full course tree → new/updated/notes-preserved report |
| GET | `/api/export.md` · `/api/export.json` | downloads |
| GET | `/api/export-notes.md` | **your notes only** — never the lesson text |
| GET | `/healthz` | health check, wired to `[routing].health_check` |

## What is not here

The Year of Systems course content itself — its videos, lesson text, and scripts — is Ben
Meer's copyrighted material and is not reproduced or redistributed here. This repo is the
scaffolding: the week structure, the module categories, and a place to keep your own notes
on what you actually installed and whether it stuck. The lessons you import live in SQLite
on your own instance and are never written to this repo.
