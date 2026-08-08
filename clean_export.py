#!/usr/bin/env python3
"""Clean a raw Kajabi scrape into the shape /api/course/import expects.

WHY A SEPARATE PASS AND NOT A BETTER SCRAPER: the scrape is the expensive, rate-limited,
browser-dependent half. Cleaning is pure text and free to re-run, so bugs get fixed by
editing this file and re-running against the same JSON — not by driving Chrome across 61
pages again.

Two things are stripped:

1. A <style> block Kajabi inlines *inside* the post body. Reading textContent drags raw
   CSS into the lesson.
2. The lesson's own navigation chrome — "Mark As Complete", the next-lesson teaser, the
   lesson title, and the module breadcrumb — which all sit above the real content.

The content boundary is the module-title breadcrumb, the last line of chrome before the
body. Anything before it goes. This is asserted per lesson, and the script exits non-zero
naming any lesson where the anchor was not found rather than silently emitting a body
with CSS in it.
"""
import json, os, re, sys

NAV_NAMES = re.compile(
    r"^(mark as complete|next lesson|previous lesson|great job! keep going!|"
    r"complete and continue|back to course)$", re.I)
CSSISH = re.compile(r"[{}]|^\s*/\*|\*/\s*$|^\s*=+\s*$|^\s*#[A-Za-z ]+$|:\s*[^;]+;\s*$")


def clean_body(raw: str, lesson_title: str, module_title: str):
    """Return (body, how) or (None, reason)."""
    text = raw.replace("\r", "")

    # The breadcrumb is the module title on its own line. Content is everything after the
    # LAST such line, because the module title can also appear inside the nav teaser.
    lines = text.split("\n")
    anchor = None
    for i, ln in enumerate(lines):
        if ln.strip() == module_title.strip():
            anchor = i
    if anchor is not None:
        body = "\n".join(lines[anchor + 1:])
        return tidy(body), "breadcrumb"

    # Fallback: drop the leading run of CSS-ish and nav-ish lines. Used when a module has
    # no breadcrumb (the Graduation module renders differently).
    out, started = [], False
    for ln in lines:
        s = ln.strip()
        if not started:
            if not s or CSSISH.search(ln) or NAV_NAMES.match(s) or s == lesson_title.strip():
                continue
            started = True
        out.append(ln)
    if not started:
        return None, "no content found"
    return tidy("\n".join(out)), "fallback"


def tidy(s: str) -> str:
    # Kajabi's editor emits &nbsp;-only lines. They are not matched by [ \t]+ and so
    # survive as "non-empty" lines, leaving big dead gaps in the rendered lesson.
    s = s.replace(" ", " ").replace("​", "")
    s = re.sub(r"^[ \t]+$", "", s, flags=re.M)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    # Kajabi indents the whole body; strip a uniform leading indent so it reads as prose.
    lines = [ln.rstrip() for ln in s.split("\n")]
    pad = [len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()]
    if pad and min(pad) > 0:
        cut = min(pad)
        lines = [ln[cut:] if ln.strip() else ln for ln in lines]
    return "\n".join(lines).strip()


def clean_assets(assets, lesson_titles):
    out, seen = [], set()
    for a in assets or []:
        name, url = (a.get("name") or "").strip(), (a.get("url") or "").strip()
        if not name or not url or url in seen:
            continue
        if NAV_NAMES.match(name) or name in lesson_titles:
            continue
        if "courses.benmeer.com/products/" in url:   # links back into the course itself
            continue
        seen.add(url)
        out.append({"name": name[:120], "url": url})
    return out


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Downloads/yos-course-export.json")
    dst = sys.argv[2] if len(sys.argv) > 2 else "/tmp/yos-course-clean.json"
    d = json.load(open(src))

    all_titles = {l["title"].strip() for m in d["modules"] for l in m["lessons"]}
    problems, stats = [], {"lessons": 0, "breadcrumb": 0, "fallback": 0, "video_only": 0, "assets": 0}

    for m in d["modules"]:
        for l in m["lessons"]:
            body, how = clean_body(l.get("body", ""), l["title"], m["title"])
            body = body or ""
            # Some lessons are video-only — their page is genuinely all chrome and no
            # prose. An empty body there is the correct answer, not a cleaning failure,
            # so it is only a problem when there is no video to fall back on either.
            if len(body) < 120:
                if l.get("video_url"):
                    stats["video_only"] += 1
                else:
                    problems.append(f'{l["title"]}: no body and no video ({how}, len={len(body)})')
            else:
                stats[how] += 1
            if re.search(r"\.btn\s*\{|=====|!important", body):
                problems.append(f'{l["title"]}: CSS survived cleaning')
            l["body"] = body
            l["assets"] = clean_assets(l.get("assets"), all_titles)
            stats["assets"] += len(l["assets"])
            stats["lessons"] += 1

    json.dump(d, open(dst, "w"), indent=1)
    print(f"wrote {dst}")
    print(f"  lessons {stats['lessons']}  via-breadcrumb {stats['breadcrumb']}  video-only {stats['video_only']}  "
          f"via-fallback {stats['fallback']}  assets {stats['assets']}")

    # Loud failure: a body that silently kept its CSS would be read as the lesson.
    if problems:
        print("\nPROBLEMS:", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        sys.exit(f"\n{len(problems)} lesson(s) did not clean. Fix before importing.")
    print("  all lessons cleaned")


if __name__ == "__main__":
    main()
