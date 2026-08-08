#!/usr/bin/env python3
"""Emit a single recurring calendar event for the weekly systems session.

WHY A CALENDAR EVENT AND NOT A REMINDER: Carl runs his life off Google Calendar and does
not check a reminders list. A nudge that lands only in Apple Reminders is a nudge he may
never see, which makes it worse than no nudge — it looks like coverage and isn't.

WHY ONE RECURRING EVENT AND NOT A WEEKLY JOB: a scheduled job that fires 52 times is 52
chances to die silently, which is the exact failure this whole system exists to prevent.
An RRULE is evaluated by the calendar itself. There is no process to monitor, no
heartbeat to check, and nothing to rot when a path changes or the laptop is shut.

Opening the .ics lets Calendar ask which calendar to file it under, so the choice of
calendar stays with Carl rather than being guessed here.

Usage:
    python3 make_calendar.py                 # reads start date from the live zone
    python3 make_calendar.py 2026-08-03      # or pass it explicitly
"""
import json, subprocess, sys, urllib.request
from datetime import date, datetime, timedelta

APP_URL = "https://year-of-systems.carl.selfhost.imbue.com/"
OUT = "/tmp/year-of-systems.ics"
HOUR, MINUTE = 8, 0


def start_date_from_app():
    """Ask the app, so the calendar and the tracker cannot disagree about week 1."""
    try:
        out = subprocess.run(["oh", "curl", "--", "-sS", APP_URL + "api/state"],
                             capture_output=True, text=True, timeout=30)
        return json.loads(out.stdout)["settings"]["start_date"]
    except Exception as e:
        print(f"could not read start_date from the app ({type(e).__name__}); "
              f"pass it as an argument", file=sys.stderr)
        return None


def esc(s):
    return s.replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\n", r"\n")


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else start_date_from_app()
    if not start:
        sys.exit(2)
    d0 = date.fromisoformat(start)
    monday = d0 - timedelta(days=d0.weekday())

    # First occurrence is the next Monday that has not already passed, so importing this
    # mid-year does not backfill a pile of events into the past.
    today = date.today()
    first = monday
    while first < today:
        first += timedelta(weeks=1)
    week_no = (first - monday).days // 7 + 1
    remaining = 52 - week_no + 1
    if remaining < 1:
        sys.exit("The 52 weeks are already over — nothing to schedule.")

    dtstart = datetime.combine(first, datetime.min.time()).replace(hour=HOUR, minute=MINUTE)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    desc = ("One system this week. Set it up once, it runs for years.\\n\\n"
            "Open the week, follow the setup steps, then mark it installed:\\n" + APP_URL)

    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//year-of-systems//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:year-of-systems-weekly-{monday.isoformat()}@somach.life",
        f"DTSTAMP:{stamp}",
        f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%S')}",
        f"DTEND:{(dtstart + timedelta(minutes=30)).strftime('%Y%m%dT%H%M%S')}",
        f"RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT={remaining}",
        f"SUMMARY:{esc('Year of Systems — install this week’s system')}",
        f"DESCRIPTION:{desc}",
        f"URL:{APP_URL}",
        "BEGIN:VALARM", "TRIGGER:PT0M", "ACTION:DISPLAY",
        f"DESCRIPTION:{esc('Year of Systems')}", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR",
    ]
    # RFC 5545 requires CRLF; Calendar.app is forgiving but Google Calendar is not always.
    open(OUT, "w", newline="").write("\r\n".join(lines) + "\r\n")

    print(f"wrote {OUT}")
    print(f"  week 1 Monday : {monday}")
    print(f"  first event   : {first} 08:00  (week {week_no})")
    print(f"  occurrences   : {remaining}  (through week 52)")
    print(f"\nOpen it to file it under a calendar of your choice:\n  open {OUT}")


if __name__ == "__main__":
    main()
