#!/usr/bin/env python3
"""Build the GitHub Pages home (../index.html) from categories.json and each folder's content.json.

Folders not listed in categories.json land in "미분류" so a new digest never goes missing.
Also puts the password lock into every document page (see protect_pages).
Run: python3 .pages/build_home.py
"""
import datetime as dt
import html
import json
import re
import unicodedata
from collections import OrderedDict, defaultdict
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
EXCLUDE = {"skill-dev", ".claude", ".pages", ".git"}

# Blocks right-click and the devtools / view-source shortcuts. Browser menus still open devtools.
GUARD_JS = """  document.addEventListener('contextmenu', function(e){ e.preventDefault(); });
  document.addEventListener('keydown', function(e){
    var c = e.code, mod = e.ctrlKey || e.metaKey;
    if (e.key === 'F12' ||
        (mod && e.shiftKey && (c === 'KeyI' || c === 'KeyJ' || c === 'KeyC')) ||
        (e.metaKey && e.altKey && (c === 'KeyI' || c === 'KeyJ' || c === 'KeyC' || c === 'KeyU')) ||
        (mod && c === 'KeyU')) {
      e.preventDefault(); e.stopPropagation();
    }
  }, true);"""

# Injected right after <head> of every document page. The page stays hidden (even with JS off)
# until the stored unlock value matches; otherwise it is sent to the home lock screen.
LOCK_START, LOCK_END = "<!-- yn-lock:start -->", "<!-- yn-lock:end -->"
DOC_LOCK = LOCK_START + """
<style id="yn-lock">html{display:none !important}</style>
<script>
(function(){
  var ok = false;
  try { ok = localStorage.getItem('yn-unlock') === "{hash}"; } catch (e) {}
  if (ok) { var s = document.getElementById('yn-lock'); s.parentNode.removeChild(s); return; }
  location.replace(new URL('../', location.href).pathname + '?next=' + encodeURIComponent(location.pathname + location.search + location.hash));
})();
{guard}
</script>
""" + LOCK_END


def esc(s):
    return html.escape(str(s or ""), quote=True)


def load_videos():
    videos = {}
    for d in sorted(ROOT.iterdir()):
        if not d.is_dir() or d.name in EXCLUDE or d.name.startswith("."):
            continue
        cj, page = d / "content.json", d / "index.html"
        if not (cj.exists() and page.exists()):
            continue
        c = json.loads(cj.read_text(encoding="utf-8"))
        m = re.search(r"[?&]v=([\w-]{11})", c.get("video_url", "")) or re.search(r"([\w-]{11})$", c.get("video_id", ""))
        name = unicodedata.normalize("NFC", d.name)  # macOS may hand back NFD names
        videos[name] = {
            "folder": name,
            "page": page,
            "dir": d,
            "title": c.get("title", d.name),
            "subtitle": c.get("subtitle", ""),
            "channel": (c.get("channel") or "채널 미상").strip(),
            "duration": c.get("duration", ""),
            "vid": c.get("video_id") or (m.group(1) if m else ""),
        }
    return videos


WEEKDAYS = "월화수목금토일"


def load_dates(videos):
    """When each video was digested. First seen = folder creation time, then frozen in dates.json
    so rebuilding a digest or cloning the repo elsewhere never reshuffles the order."""
    path = HERE / "dates.json"
    dates = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for name, v in videos.items():
        if name not in dates:
            st = v["dir"].stat()
            ts = getattr(st, "st_birthtime", st.st_mtime)
            dates[name] = dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")
    path.write_text(json.dumps(dict(sorted(dates.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return dates


def card(v, cat_label=None, show_channel=True):
    href = "./" + quote(v["folder"]) + "/"
    thumb = f'https://i.ytimg.com/vi/{esc(v["vid"])}/mqdefault.jpg' if v["vid"] else ""
    search = " ".join([v["title"], v["subtitle"], v["channel"], cat_label or ""]).lower()
    meta = []
    if show_channel:
        meta.append(f'<span class="ch">{esc(v["channel"])}</span>')
    if v["duration"]:
        meta.append(f'<span>{esc(v["duration"])}</span>')
    tag = f'<span class="tag">{esc(cat_label)}</span>' if cat_label else ""
    img = f'<img src="{thumb}" alt="" loading="lazy">' if thumb else ""
    return (
        f'<a class="card" href="{href}" data-q="{esc(search)}">'
        f'<div class="thumb">{img}</div>'
        f'<div class="body">{tag}<h4>{esc(v["title"])}</h4>'
        f'<p>{esc(v["subtitle"])}</p>'
        f'<div class="meta">{" · ".join(meta)}</div></div></a>'
    )


def channel_blocks(vs, cat_of):
    """Same-channel videos (2+) go in one box; the rest share a plain grid."""
    by_ch = OrderedDict()
    for v in vs:
        by_ch.setdefault(v["channel"], []).append(v)
    out, singles = [], []
    for ch, items in by_ch.items():
        if len(items) > 1:
            cards = "".join(card(v, show_channel=False) for v in items)
            out.append(
                f'<div class="chgroup" data-group><div class="chhead">{esc(ch)}'
                f'<span class="n">{len(items)}</span></div><div class="grid">{cards}</div></div>'
            )
        else:
            singles.extend(items)
    if singles:
        out.append('<div class="grid" data-group>' + "".join(card(v) for v in singles) + "</div>")
    return "".join(out)


def protect_pages(videos, pw_hash):
    """Put the lock (or remove it when there is no password) in every document page. Safe to rerun."""
    block = re.compile(re.escape(LOCK_START) + r".*?" + re.escape(LOCK_END) + r"\n?", re.S)
    changed = 0
    for v in videos.values():
        page = v["page"]
        src = page.read_text(encoding="utf-8")
        out = block.sub("", src)
        if pw_hash:
            snippet = DOC_LOCK.replace("{hash}", pw_hash).replace("{guard}", GUARD_JS) + "\n"
            # after <meta charset> so the charset stays inside the first 1024 bytes; else right after <head>
            out, n = re.subn(r"(<meta charset[^>]*>\n?)", lambda m: m.group(1) + snippet, out, count=1, flags=re.I)
            if not n:
                out, n = re.subn(r"(<head[^>]*>\n?)", lambda m: m.group(1) + snippet, out, count=1, flags=re.I)
            if not n:
                raise SystemExit(f"no <head> in {page}")
        if out != src:
            page.write_text(out, encoding="utf-8")
            changed += 1
    return changed


def main():
    videos = load_videos()
    cats = json.loads((HERE / "categories.json").read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
    placed, cat_of = set(), {}
    for big, subs in cats.items():
        for sub, folders in subs.items():
            for f in folders:
                f = unicodedata.normalize("NFC", f)
                if f in videos:
                    placed.add(f)
                    cat_of[f] = f"{big} › {sub}"
    rest = [f for f in videos if f not in placed]
    if rest:
        cats["미분류"] = OrderedDict([("새로 추가된 영상", rest)])
        for f in rest:
            cat_of[f] = "미분류"

    # category view
    nav, sections = [], []
    for i, (big, subs) in enumerate(cats.items()):
        sid = f"c{i}"
        n_big = sum(1 for fs in subs.values() for f in fs if unicodedata.normalize("NFC", f) in videos)
        nav.append(f'<a href="#{sid}">{esc(big)}<span class="n">{n_big}</span></a>')
        parts = []
        for sub, folders in subs.items():
            vs = [videos[unicodedata.normalize("NFC", f)] for f in folders if unicodedata.normalize("NFC", f) in videos]
            if not vs:
                continue
            vs.sort(key=lambda v: v["channel"])
            parts.append(
                f'<section class="sub" data-sec><h3>{esc(sub)}<span class="n">{len(vs)}</span></h3>'
                f"{channel_blocks(vs, cat_of)}</section>"
            )
        sections.append(
            f'<section class="big" id="{sid}" data-sec><h2>{esc(big)}<span class="n">{n_big}</span></h2>{"".join(parts)}</section>'
        )

    # channel view
    by_ch = defaultdict(list)
    for v in videos.values():
        by_ch[v["channel"]].append(v)
    ch_sorted = sorted(by_ch.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))
    ch_html = []
    for ch, vs in ch_sorted:
        cards = "".join(card(v, cat_label=cat_of[v["folder"]].split(" › ")[-1], show_channel=False) for v in vs)
        ch_html.append(
            f'<section class="chsec" data-sec><h3>{esc(ch)}<span class="n">{len(vs)}</span></h3>'
            f'<div class="grid" data-group>{cards}</div></section>'
        )

    # time view: newest first, one group per day (the page can flip the order)
    dates = load_dates(videos)
    by_day = defaultdict(list)
    for name, v in videos.items():
        by_day[dates[name][:10]].append(v)
    time_html = []
    for day in sorted(by_day, reverse=True):
        vs = sorted(by_day[day], key=lambda v: dates[v["folder"]], reverse=True)
        d = dt.date.fromisoformat(day)
        label = f"{d.year}년 {d.month}월 {d.day}일 ({WEEKDAYS[d.weekday()]})"
        cards = "".join(card(v, cat_label=cat_of[v["folder"]].split(" › ")[-1]) for v in vs)
        time_html.append(
            f'<section class="chsec" data-sec><h3>{label}<span class="n">{len(vs)}</span></h3>'
            f'<div class="grid" data-group>{cards}</div></section>'
        )

    tpl = (HERE / "home_template.html").read_text(encoding="utf-8")
    # SHA-256 of the home password, one line. Empty or missing = no lock screen.
    hash_file = HERE / "password.sha256"
    pw_hash = hash_file.read_text(encoding="utf-8").strip() if hash_file.exists() else ""
    out = (
        tpl.replace("{{PW_HASH}}", pw_hash)
        .replace("{{LOCK_CLASS}}", ' class="locked"' if pw_hash else "")
        .replace("{{GUARD_JS}}", GUARD_JS)
        .replace("{{COUNT}}", str(len(videos)))
        .replace("{{CATS}}", str(len(cats)))
        .replace("{{CHANNELS}}", str(len(by_ch)))
        .replace("{{NAV}}", "".join(nav))
        .replace("{{CATEGORY_VIEW}}", "".join(sections))
        .replace("{{CHANNEL_VIEW}}", "".join(ch_html))
        .replace("{{TIME_VIEW}}", "".join(time_html))
    )
    (ROOT / "index.html").write_text(out, encoding="utf-8")
    changed = protect_pages(videos, pw_hash)
    print(f"document pages {'locked' if pw_hash else 'unlocked'}: {changed} changed")
    print(f"index.html: {len(videos)} videos, {len(cats)} categories, {len(by_ch)} channels"
          + (f", 미분류 {len(rest)}: {rest}" if rest else ""))


if __name__ == "__main__":
    main()
