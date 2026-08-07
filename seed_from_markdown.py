#!/usr/bin/env python3
"""Bulk-load weeks from a markdown file into a running instance.

WHY THIS EXISTS: typing 52 systems into a phone is the kind of recurring manual chore
this whole system is built to avoid. Write them once in markdown — the format every other
record here already uses — and push them in.

WHY IT REFUSES TO OVERWRITE BY DEFAULT: a re-run that silently replaces a year of your
own notes with a stale file is unrecoverable. Pass --overwrite when you mean it.

Format (## heading is the only required part):

    ## Week 3 — The five-name list
    category: relations
    tool: A note
    minutes: 15

    Relationships decay silently and on no schedule, so they lose every contest
    against work that has a deadline.

    - Write the five people you want to still be close to in five years.
    - Note the date you last had a real conversation with each.

Usage:
    python3 seed_from_markdown.py my-systems.md
    python3 seed_from_markdown.py my-systems.md --url https://year-of-systems.carl.selfhost.imbue.com --overwrite
"""
import argparse, json, re, sys, urllib.error, urllib.request

HEAD = re.compile(r"^#{1,6}\s*week\s*(\d{1,2})\s*[—\-:.]?\s*(.*)$", re.I)
META = re.compile(r"^(category|tool|minutes|source)\s*:\s*(.+)$", re.I)
BULLET = re.compile(r"^\s*[-*+]\s+(?:\[[ xX]\]\s*)?(.+)$")

CATEGORY_ALIASES = {
    "physical": "physical", "physical health": "physical", "health": "physical", "body": "physical",
    "mind": "mind", "mental": "mind", "focus": "mind",
    "relations": "relations", "relationships": "relations", "social": "relations",
    "emotions": "emotions", "emotional": "emotions", "feelings": "emotions",
    "money": "money", "finance": "money", "finances": "money", "financial": "money",
    "career": "career", "work": "career", "professional": "career",
    "environ": "environ", "environment": "environ", "home": "environ", "space": "environ",
}


def parse(text):
    systems, cur = [], None
    for line in text.splitlines():
        h = HEAD.match(line.strip())
        if h:
            if cur:
                systems.append(cur)
            cur = {"week": int(h.group(1)), "title": h.group(2).strip(),
                   "why": [], "steps": [], "source": "course"}
            continue
        if cur is None:
            continue
        m = META.match(line.strip())
        if m:
            k, v = m.group(1).lower(), m.group(2).strip()
            if k == "minutes":
                digits = re.sub(r"\D", "", v)
                cur["minutes"] = int(digits) if digits else 0
            elif k == "category":
                key = CATEGORY_ALIASES.get(v.lower())
                if key:
                    cur["category"] = key
                else:
                    print(f"  ! week {cur['week']}: unknown category {v!r}, leaving as-is", file=sys.stderr)
            else:
                cur[k] = v
            continue
        b = BULLET.match(line)
        if b:
            cur["steps"].append(b.group(1).strip())
            continue
        if line.strip():
            cur["why"].append(line.strip())
    if cur:
        systems.append(cur)
    for s in systems:
        s["why"] = " ".join(s["why"])
    return systems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--url", default="http://localhost:8765", help="instance base URL")
    ap.add_argument("--overwrite", action="store_true", help="replace weeks that already have a title")
    ap.add_argument("--dry-run", action="store_true", help="parse and print, send nothing")
    a = ap.parse_args()

    systems = parse(open(a.file, encoding="utf-8").read())
    if not systems:
        sys.exit(f"No '## Week N — Title' headings found in {a.file}. Nothing to do.")

    print(f"Parsed {len(systems)} systems from {a.file}:")
    for s in systems:
        print(f"  week {s['week']:>2}  {s['title'][:52]:<52} "
              f"{len(s['steps'])} steps  {s.get('category', '(keep)')}")
    if a.dry_run:
        return

    payload = json.dumps({"systems": systems, "overwrite": a.overwrite}).encode()
    req = urllib.request.Request(a.url.rstrip("/") + "/api/import", data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        sys.exit(f"Import failed: HTTP {e.code} {e.read().decode()[:300]}")
    except urllib.error.URLError as e:
        sys.exit(f"Cannot reach {a.url}: {e.reason}\n"
                 "If the instance is on OpenHost, it sits behind owner login — run this "
                 "against a local instance, or export/import through the UI instead.")

    print(f"\nupdated: {r['updated']}")
    if r["skipped"]:
        print(f"skipped (already had a title, use --overwrite): {r['skipped']}")
    for bad in r["rejected"]:
        print(f"REJECTED {bad}", file=sys.stderr)
    # Loud, non-zero exit on partial success: a silent partial import is the failure mode
    # this whole system is built to not have.
    if r["rejected"]:
        sys.exit(f"\n{len(r['rejected'])} item(s) rejected — see above.")


if __name__ == "__main__":
    main()
