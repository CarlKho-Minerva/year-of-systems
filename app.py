#!/usr/bin/env python3
"""Year of Systems — local 52-week systems tracker. Stdlib only, no network calls.

WHY NOTHING LEAVES THE BOX: the brief was "everything must be able to run locally".
There is no API key, no CDN, no font fetch, no analytics. The container has no reason
to talk to the internet and does not. That is also what makes the iPhone PWA work on a
plane.

WHY INSTALLS AND NOT DAILY CHECKBOXES: Habits.md tracked 20 weeks of manual daily ticks
and scored 0/7 every single week. That experiment is settled. The unit here is therefore
"this system is installed", which is a once-per-week state change that stays changed, not
a grid that has to be fed every morning. A system that needs daily maintenance to stay
true is the thing this app exists to replace, so it must not be the thing this app is.

WHY THE REVIEW QUEUE EXISTS: an install-only tracker rots in the other direction — it
accumulates systems that stopped running months ago and quietly becomes a list of lies.
`review_due` surfaces anything installed more than REVIEW_AFTER_DAYS ago that has not
been confirmed since. Dropping a system is a first-class, non-shameful state.
"""
import json, os, re, sqlite3, sys, logging, mimetypes, threading
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("yos")

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")

# Storage resolution, most-specific first. OPENHOST_SQLITE_MAIN is the path OpenHost
# provisions for `sqlite = ["main"]`; honouring it is what makes the app's data land in
# the backed-up tier instead of somewhere that vanishes on rebuild. Falling back to a
# repo-local ./data keeps `python3 app.py` working on the Mac with no env at all.
DB_PATH = (os.environ.get("OPENHOST_SQLITE_MAIN")
           or os.path.join(os.environ.get("OPENHOST_APP_DATA_DIR")
                           or os.environ.get("YOS_DATA")
                           or os.path.join(HERE, "data"), "yos.db"))
DATA_DIR = os.path.dirname(DB_PATH)
SEED_PATH = os.path.join(HERE, "systems.json")
PORT = int(os.environ.get("YOS_PORT") or os.environ.get("PORT") or "8765")
REVIEW_AFTER_DAYS = 30

STATUSES = ("planned", "installed", "dropped")

CATEGORIES = [
    {"key": "physical", "label": "Physical Health", "hue": 142},
    {"key": "mind",     "label": "Mind",            "hue": 262},
    {"key": "relations","label": "Relationships",   "hue": 340},
    {"key": "emotions", "label": "Emotions",        "hue": 28},
    {"key": "money",    "label": "Money",           "hue": 168},
    {"key": "career",   "label": "Career",          "hue": 210},
    {"key": "environ",  "label": "Environment",     "hue": 48},
]
CAT_KEYS = [c["key"] for c in CATEGORIES]

_lock = threading.Lock()


# ---------------------------------------------------------------- storage

def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def init_db():
    db = connect()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS systems (
        week        INTEGER PRIMARY KEY,
        category    TEXT NOT NULL,
        title       TEXT NOT NULL DEFAULT '',
        why         TEXT NOT NULL DEFAULT '',
        steps       TEXT NOT NULL DEFAULT '[]',   -- json: [{"text":..,"done":bool}]
        tool        TEXT NOT NULL DEFAULT '',
        minutes     INTEGER NOT NULL DEFAULT 0,
        notes       TEXT NOT NULL DEFAULT '',
        source      TEXT NOT NULL DEFAULT '',     -- 'starter' | 'course' | 'mine'
        status      TEXT NOT NULL DEFAULT 'planned',
        installed_on TEXT,
        reviewed_on  TEXT,
        updated_at   TEXT
    );
    CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT NOT NULL);

    -- The course reader. Content lives HERE, in SQLite on the zone, and never in the
    -- git repo: the repo is public, and the lesson text is Ben Meer's copyrighted
    -- material. Keeping the two apart is a structural guarantee, not a habit to
    -- remember — there is no code path that writes a lesson body to a file in the repo.
    CREATE TABLE IF NOT EXISTS modules (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        position INTEGER NOT NULL DEFAULT 0,
        title    TEXT NOT NULL,
        source_url TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS lessons (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        module_id INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
        position  INTEGER NOT NULL DEFAULT 0,
        title     TEXT NOT NULL,
        body      TEXT NOT NULL DEFAULT '',
        video_url TEXT NOT NULL DEFAULT '',
        assets    TEXT NOT NULL DEFAULT '[]',  -- json: [{"name":..,"url":..}]
        source_url TEXT NOT NULL DEFAULT '',
        week      INTEGER,                     -- optional link into systems.week
        notes     TEXT NOT NULL DEFAULT '',
        updated_at TEXT
    );
    CREATE INDEX IF NOT EXISTS lessons_by_module ON lessons(module_id, position);
    CREATE UNIQUE INDEX IF NOT EXISTS lessons_by_source ON lessons(source_url)
        WHERE source_url <> '';
    """)
    db.commit()

    # Seed only the rows that do not exist yet, so re-running never clobbers real work.
    # WHY: seeding is idempotent by construction rather than by a flag file, because a
    # flag file is one `rm -rf data/` away from silently wiping a year of entries.
    seed = json.load(open(SEED_PATH)) if os.path.exists(SEED_PATH) else {"systems": []}
    by_week = {int(s["week"]): s for s in seed.get("systems", [])}
    have = {r["week"] for r in db.execute("SELECT week FROM systems")}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for wk in range(1, 53):
        if wk in have:
            continue
        s = by_week.get(wk, {})
        db.execute(
            "INSERT INTO systems (week,category,title,why,steps,tool,minutes,notes,source,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (wk,
             s.get("category") or CAT_KEYS[(wk - 1) % len(CAT_KEYS)],
             s.get("title", ""), s.get("why", ""),
             json.dumps([{"text": t, "done": False} for t in s.get("steps", [])]),
             s.get("tool", ""), int(s.get("minutes") or 0), "",
             s.get("source", ""), now))
    db.execute("INSERT OR IGNORE INTO settings (k,v) VALUES ('start_date',?)",
               (monday_of(date.today()).isoformat(),))
    db.commit()
    db.close()


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def get_setting(db, k, default=""):
    r = db.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


# ---------------------------------------------------------------- domain

def current_week(start_iso: str) -> int:
    """Week 1 is the week containing start_date. Clamped to 1..52.

    Past 52 the year is over; we clamp rather than wrap so the UI can say "year
    complete" instead of silently restarting and making week 53 look like week 1.
    """
    try:
        start = date.fromisoformat(start_iso)
    except (ValueError, TypeError):
        start = monday_of(date.today())
    delta = (monday_of(date.today()) - monday_of(start)).days // 7
    return max(1, min(52, delta + 1))


def row_to_system(r, today: date):
    steps = json.loads(r["steps"] or "[]")
    done = sum(1 for s in steps if s.get("done"))
    review_due = False
    if r["status"] == "installed":
        anchor = r["reviewed_on"] or r["installed_on"]
        if anchor:
            try:
                review_due = (today - date.fromisoformat(anchor)).days >= REVIEW_AFTER_DAYS
            except ValueError:
                review_due = False
    return {
        "week": r["week"], "category": r["category"], "title": r["title"],
        "why": r["why"], "steps": steps, "steps_done": done, "steps_total": len(steps),
        "tool": r["tool"], "minutes": r["minutes"], "notes": r["notes"],
        "source": r["source"], "status": r["status"],
        "installed_on": r["installed_on"], "reviewed_on": r["reviewed_on"],
        "review_due": review_due,
        "filled": bool(r["title"].strip()),
    }


def build_state():
    db = connect()
    start = get_setting(db, "start_date", monday_of(date.today()).isoformat())
    today = date.today()
    systems = [row_to_system(r, today)
               for r in db.execute("SELECT * FROM systems ORDER BY week")]
    db.close()
    wk = current_week(start)
    installed = [s for s in systems if s["status"] == "installed"]
    return {
        "categories": CATEGORIES,
        "systems": systems,
        "settings": {"start_date": start, "review_after_days": REVIEW_AFTER_DAYS},
        "today": today.isoformat(),
        "current_week": wk,
        "week_of": (monday_of(date.fromisoformat(start)) + timedelta(weeks=wk - 1)).isoformat(),
        "stats": {
            "installed": len(installed),
            "dropped": sum(1 for s in systems if s["status"] == "dropped"),
            "filled": sum(1 for s in systems if s["filled"]),
            "review_due": sum(1 for s in systems if s["review_due"]),
            "minutes_saved_setup": sum(s["minutes"] for s in installed),
        },
    }


def update_system(week: int, patch: dict):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    today = date.today().isoformat()
    with _lock:
        db = connect()
        cur = db.execute("SELECT * FROM systems WHERE week=?", (week,)).fetchone()
        if cur is None:
            db.close()
            raise KeyError(week)

        fields, vals = [], []

        def put(col, val):
            fields.append(f"{col}=?")
            vals.append(val)

        if "title" in patch:    put("title", str(patch["title"])[:200])
        if "why" in patch:      put("why", str(patch["why"])[:4000])
        if "tool" in patch:     put("tool", str(patch["tool"])[:200])
        if "notes" in patch:    put("notes", str(patch["notes"])[:20000])
        if "minutes" in patch:
            try:
                put("minutes", max(0, min(10000, int(patch["minutes"] or 0))))
            except (TypeError, ValueError):
                pass
        if "category" in patch and patch["category"] in CAT_KEYS:
            put("category", patch["category"])
        if "source" in patch and patch["source"] in ("", "starter", "course", "mine"):
            put("source", patch["source"])
        if "steps" in patch and isinstance(patch["steps"], list):
            clean = [{"text": str(s.get("text", ""))[:500], "done": bool(s.get("done"))}
                     for s in patch["steps"][:40] if str(s.get("text", "")).strip()]
            put("steps", json.dumps(clean))

        if "status" in patch:
            st = patch["status"]
            if st not in STATUSES:
                db.close()
                raise ValueError(f"bad status {st!r}")
            put("status", st)
            # Stamp the install date the first time only; re-confirming a running system
            # must not reset its age, or the review queue can never fire.
            if st == "installed":
                if not cur["installed_on"]:
                    put("installed_on", today)
                put("reviewed_on", today)
            elif st == "planned":
                put("installed_on", None)
                put("reviewed_on", None)

        if "reviewed" in patch and patch["reviewed"]:
            put("reviewed_on", today)

        if not fields:
            db.close()
            return
        put("updated_at", now)
        vals.append(week)
        db.execute(f"UPDATE systems SET {','.join(fields)} WHERE week=?", vals)
        db.commit()
        db.close()


# ---------------------------------------------------------------- course reader

def course_tree():
    """Modules + lesson stubs. Deliberately omits lesson bodies.

    The whole course is far too big to ship to a phone on every tab switch, and the list
    view never needs the text. Bodies are fetched one lesson at a time.
    """
    db = connect()
    mods = [dict(r) for r in db.execute("SELECT * FROM modules ORDER BY position, id")]
    rows = db.execute(
        "SELECT id, module_id, position, title, week, video_url,"
        " length(body) AS body_len, length(notes) AS notes_len, assets"
        " FROM lessons ORDER BY position, id").fetchall()
    db.close()
    by_mod = {}
    for r in rows:
        by_mod.setdefault(r["module_id"], []).append({
            "id": r["id"], "position": r["position"], "title": r["title"],
            "week": r["week"], "has_video": bool(r["video_url"]),
            "has_body": bool(r["body_len"]), "has_notes": bool(r["notes_len"]),
            "assets": len(json.loads(r["assets"] or "[]")),
        })
    for m in mods:
        m["lessons"] = by_mod.get(m["id"], [])
    total = len(rows)
    return {
        "modules": mods,
        "stats": {
            "modules": len(mods), "lessons": total,
            "with_body": sum(1 for r in rows if r["body_len"]),
            "with_notes": sum(1 for r in rows if r["notes_len"]),
        },
    }


def get_lesson(lid: int):
    db = connect()
    r = db.execute("SELECT * FROM lessons WHERE id=?", (lid,)).fetchone()
    if r is None:
        db.close()
        raise KeyError(lid)
    m = db.execute("SELECT title FROM modules WHERE id=?", (r["module_id"],)).fetchone()
    sib = [dict(x) for x in db.execute(
        "SELECT id, title FROM lessons WHERE module_id=? ORDER BY position, id",
        (r["module_id"],))]
    db.close()
    d = dict(r)
    d["assets"] = json.loads(d["assets"] or "[]")
    d["module_title"] = m["title"] if m else ""
    idx = next((i for i, x in enumerate(sib) if x["id"] == lid), -1)
    d["prev_id"] = sib[idx - 1]["id"] if idx > 0 else None
    d["next_id"] = sib[idx + 1]["id"] if 0 <= idx < len(sib) - 1 else None
    return d


def update_lesson(lid: int, patch: dict):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock:
        db = connect()
        if db.execute("SELECT 1 FROM lessons WHERE id=?", (lid,)).fetchone() is None:
            db.close()
            raise KeyError(lid)
        fields, vals = [], []
        if "notes" in patch:
            fields.append("notes=?")
            vals.append(str(patch["notes"])[:100000])
        if "week" in patch:
            w = patch["week"]
            if w in (None, "", 0):
                fields.append("week=?")
                vals.append(None)
            else:
                w = int(w)
                if not 1 <= w <= 52:
                    db.close()
                    raise ValueError("week must be 1-52 or empty")
                fields.append("week=?")
                vals.append(w)
        if not fields:
            db.close()
            return
        fields.append("updated_at=?")
        vals.extend([now, lid])
        db.execute(f"UPDATE lessons SET {','.join(fields)} WHERE id=?", vals)
        db.commit()
        db.close()


def import_course(body):
    """Ingest a scraped course tree.

    Notes are NEVER overwritten. A re-scrape after the course is updated must not be able
    to destroy what Carl wrote — that is the one irreplaceable thing in this database.
    Lessons are matched on source_url, so a re-run updates in place instead of duplicating.
    """
    mods = body.get("modules")
    if not isinstance(mods, list):
        raise ValueError('expected {"modules": [{"title":..,"lessons":[...]}, ...]}')
    report = {"modules": 0, "lessons_new": 0, "lessons_updated": 0, "notes_preserved": 0}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock:
        db = connect()
        for mi, m in enumerate(mods):
            mtitle = str(m.get("title", "")).strip() or f"Module {mi + 1}"
            murl = str(m.get("source_url", ""))
            row = db.execute("SELECT id FROM modules WHERE title=?", (mtitle,)).fetchone()
            if row:
                mid = row["id"]
                db.execute("UPDATE modules SET position=?, source_url=? WHERE id=?", (mi, murl, mid))
            else:
                cur = db.execute("INSERT INTO modules (position,title,source_url) VALUES (?,?,?)",
                                 (mi, mtitle, murl))
                mid = cur.lastrowid
            report["modules"] += 1

            for li, l in enumerate(m.get("lessons", [])):
                ltitle = str(l.get("title", "")).strip() or f"Lesson {li + 1}"
                lurl = str(l.get("source_url", ""))
                assets = json.dumps([{"name": str(a.get("name", ""))[:200],
                                      "url": str(a.get("url", ""))[:2000]}
                                     for a in (l.get("assets") or [])][:50])
                existing = db.execute(
                    "SELECT id, notes FROM lessons WHERE source_url=? AND source_url<>''",
                    (lurl,)).fetchone()
                if existing is None:
                    existing = db.execute(
                        "SELECT id, notes FROM lessons WHERE module_id=? AND title=?",
                        (mid, ltitle)).fetchone()
                vals = (mid, li, ltitle, str(l.get("body", "")), str(l.get("video_url", "")),
                        assets, lurl, now)
                if existing:
                    db.execute(
                        "UPDATE lessons SET module_id=?, position=?, title=?, body=?,"
                        " video_url=?, assets=?, source_url=?, updated_at=? WHERE id=?",
                        vals + (existing["id"],))
                    report["lessons_updated"] += 1
                    if existing["notes"]:
                        report["notes_preserved"] += 1
                else:
                    db.execute(
                        "INSERT INTO lessons (module_id,position,title,body,video_url,"
                        "assets,source_url,updated_at) VALUES (?,?,?,?,?,?,?,?)", vals)
                    report["lessons_new"] += 1
        db.commit()
        db.close()
    log.info("course import: %s", report)
    report["course"] = course_tree()
    return report


def export_notes():
    """Export YOUR notes, with lesson titles for context — not the lesson bodies.

    Deliberate: the export is meant to land in the Obsidian vault, and the vault syncs to
    iCloud and sits next to git repos. Carl's own writing belongs there. Ben Meer's
    lesson text does not leave this database, so there is no way to accidentally commit
    or publish it by running an export.
    """
    c = course_tree()
    db = connect()
    notes = {r["id"]: r["notes"] for r in db.execute("SELECT id, notes FROM lessons")}
    db.close()
    out = ["# Course notes", "",
           f"Exported: {date.today().isoformat()}  ",
           f"{c['stats']['with_notes']} of {c['stats']['lessons']} lessons annotated", "",
           "> Your notes only. Lesson text stays in the app database and is not exported.", ""]
    for m in c["modules"]:
        wrote_header = False
        for l in m["lessons"]:
            body = (notes.get(l["id"]) or "").strip()
            if not body:
                continue
            if not wrote_header:
                out += [f"## {m['title']}", ""]
                wrote_header = True
            wk = f" (week {l['week']})" if l["week"] else ""
            out += [f"### {l['title']}{wk}", "", body, ""]
    if c["stats"]["with_notes"] == 0:
        out += ["*No notes written yet.*", ""]
    return "\n".join(out) + "\n"


def export_markdown():
    """Markdown export exists because every other record Carl keeps is markdown.

    An app that can only be read through its own UI is a silo; this one can always be
    dumped back into the vault, which is where the durable copy belongs.
    """
    st = build_state()
    labels = {c["key"]: c["label"] for c in CATEGORIES}
    out = ["# Year of Systems", "",
           f"Start date: {st['settings']['start_date']}  ",
           f"Exported: {st['today']}  ",
           f"Installed: {st['stats']['installed']}/52  ",
           f"Dropped: {st['stats']['dropped']}", ""]
    for s in st["systems"]:
        if not s["filled"] and s["status"] == "planned":
            continue
        mark = {"installed": "x", "dropped": "-", "planned": " "}[s["status"]]
        title = s["title"] or "(unnamed)"
        out.append(f"## [{mark}] Week {s['week']} — {title}")
        out.append(f"*{labels.get(s['category'], s['category'])}*"
                   + (f" · {s['minutes']} min setup" if s["minutes"] else "")
                   + (f" · {s['tool']}" if s["tool"] else ""))
        if s["installed_on"]:
            out.append(f"Installed {s['installed_on']}"
                       + (f", last confirmed {s['reviewed_on']}" if s["reviewed_on"] else ""))
        out.append("")
        if s["why"]:
            out.append(s["why"])
            out.append("")
        if s["steps"]:
            for stp in s["steps"]:
                out.append(f"- [{'x' if stp['done'] else ' '}] {stp['text']}")
            out.append("")
        if s["notes"]:
            out.append("**Notes**")
            out.append("")
            out.append(s["notes"])
            out.append("")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    server_version = "yos"

    def log_message(self, fmt, *a):
        log.info("%s %s", self.address_string(), fmt % a)

    # -- helpers

    def _send(self, code, body: bytes, ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # No third-party anything, ever. If a future edit adds a CDN link this policy
        # breaks it loudly in the console instead of silently phoning home.
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _err(self, code, msg):
        log.warning("%s -> %s %s", self.path, code, msg)
        self._json({"error": msg}, code)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 2_000_000:
            return {}
        return json.loads(self.rfile.read(n) or b"{}")

    # -- routes

    def do_GET(self):
        p = urlparse(self.path)
        path = p.path
        try:
            if path == "/healthz":
                return self._json({"ok": True, "db": os.path.exists(DB_PATH)})
            if path == "/api/state":
                return self._json(build_state())
            if path == "/api/course":
                return self._json(course_tree())
            m = re.fullmatch(r"/api/lesson/(\d+)", path)
            if m:
                return self._json(get_lesson(int(m.group(1))))
            if path == "/api/export.json":
                return self._send(200, json.dumps(build_state(), indent=2).encode(),
                                  "application/json",
                                  {"Content-Disposition": 'attachment; filename="year-of-systems.json"'})
            if path == "/api/export.md":
                return self._send(200, export_markdown().encode(), "text/markdown; charset=utf-8",
                                  {"Content-Disposition": 'attachment; filename="year-of-systems.md"'})
            if path == "/api/export-notes.md":
                return self._send(200, export_notes().encode(), "text/markdown; charset=utf-8",
                                  {"Content-Disposition": 'attachment; filename="course-notes.md"'})
            return self._static(path)
        except KeyError as e:
            return self._err(404, f"no such lesson: {e}")
        except Exception as e:  # noqa: BLE001 - never 200 on an unhandled error
            log.exception("GET %s failed", path)
            return self._err(500, str(e))

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        p = urlparse(self.path)
        try:
            body = self._body()
        except json.JSONDecodeError as e:
            return self._err(400, f"bad json: {e}")
        try:
            m = re.fullmatch(r"/api/system/(\d+)", p.path)
            if m:
                wk = int(m.group(1))
                if not 1 <= wk <= 52:
                    return self._err(404, "week out of range")
                update_system(wk, body)
                return self._json(build_state())
            if p.path == "/api/settings":
                if "start_date" in body:
                    try:
                        d = date.fromisoformat(str(body["start_date"]))
                    except ValueError:
                        return self._err(400, "start_date must be YYYY-MM-DD")
                    with _lock:
                        db = connect()
                        db.execute("INSERT INTO settings (k,v) VALUES ('start_date',?)"
                                   " ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                                   (monday_of(d).isoformat(),))
                        db.commit()
                        db.close()
                return self._json(build_state())
            if p.path == "/api/import":
                return self._json(do_import(body))
            m = re.fullmatch(r"/api/lesson/(\d+)", p.path)
            if m:
                update_lesson(int(m.group(1)), body)
                return self._json(get_lesson(int(m.group(1))))
            if p.path == "/api/course/import":
                return self._json(import_course(body))
            return self._err(404, "no such endpoint")
        except KeyError as e:
            return self._err(404, f"no such week: {e}")
        except ValueError as e:
            return self._err(400, str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("POST %s failed", p.path)
            return self._err(500, str(e))

    def _static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC, rel))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            # Unknown paths fall back to the shell so the SPA can deep-link.
            full = os.path.join(STATIC, "index.html")
            if not os.path.isfile(full):
                return self._err(404, "not found")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.endswith(".webmanifest"):
            ctype = "application/manifest+json"
        with open(full, "rb") as f:
            data = f.read()
        # The service worker must never be served stale or it can pin a broken build.
        cache = "no-cache" if full.endswith(("sw.js", "index.html")) else "max-age=300"
        self._send(200, data, ctype, {"Cache-Control": cache})


def do_import(body):
    """Bulk-fill weeks from a list. Used by seed_from_markdown.py and manual paste.

    Returns a per-week report rather than a bare count: a silent partial import is the
    exact failure this system is built to not have.
    """
    items = body.get("systems")
    if not isinstance(items, list):
        raise ValueError("expected {\"systems\": [...]}")
    overwrite = bool(body.get("overwrite"))
    report = {"updated": [], "skipped": [], "rejected": []}
    db = connect()
    existing = {r["week"]: r["title"] for r in db.execute("SELECT week,title FROM systems")}
    db.close()
    for it in items:
        try:
            wk = int(it.get("week"))
        except (TypeError, ValueError):
            report["rejected"].append({"item": str(it)[:80], "why": "no valid week"})
            continue
        if not 1 <= wk <= 52:
            report["rejected"].append({"week": wk, "why": "out of range 1-52"})
            continue
        if existing.get(wk, "").strip() and not overwrite:
            report["skipped"].append(wk)
            continue
        patch = {k: it[k] for k in ("title", "why", "tool", "minutes", "category", "notes")
                 if k in it}
        if isinstance(it.get("steps"), list):
            patch["steps"] = [{"text": s, "done": False} if isinstance(s, str) else s
                              for s in it["steps"]]
        patch["source"] = it.get("source", "course")
        update_system(wk, patch)
        report["updated"].append(wk)
    log.info("import: %d updated, %d skipped, %d rejected",
             len(report["updated"]), len(report["skipped"]), len(report["rejected"]))
    report["state"] = build_state()
    return report


def main():
    init_db()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log.info("year-of-systems on http://0.0.0.0:%d  (db=%s)", PORT, DB_PATH)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
        srv.shutdown()


if __name__ == "__main__":
    main()
