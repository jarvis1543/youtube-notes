#!/usr/bin/env python3
"""Build the GitHub Pages home (../index.html) from categories.json, topics.json and each folder's content.json.

categories.json nests up to three levels: {대분류: {중분류: {소분류: [folder names]}}}. A video can stop at
any level: "_videos" lists the folders that sit on that 대분류 or 중분류 itself.
Folders not listed anywhere show up under "아직 분류가 없는 영상" so a new digest never goes missing.
Fetches each video's YouTube upload date once (yt-dlp) into uploads.json; same-channel videos sort by it.
Also puts the password lock into every document page (see protect_pages).
Run: python3 .pages/build_home.py
"""
import datetime as dt
import html
import json
import re
import shutil
import subprocess
import unicodedata
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor
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


def load_uploads(videos):
    """YouTube upload date per folder (YYYY-MM-DD). Missing ones are fetched with yt-dlp, then frozen
    in uploads.json; entries for deleted folders drop out. Sets v["uploaded"] ("" when unknown)."""
    path = HERE / "uploads.json"
    ups = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    missing = [n for n, v in videos.items() if not ups.get(n) and v["vid"]]

    def fetch(name):
        try:
            r = subprocess.run(
                ["yt-dlp", "--skip-download", "--no-warnings", "--print", "%(upload_date)s",
                 "https://www.youtube.com/watch?v=" + videos[name]["vid"]],
                capture_output=True, text=True, timeout=120)
            d = (r.stdout.strip().splitlines() or [""])[-1]
        except (subprocess.SubprocessError, OSError):
            d = ""
        return name, (f"{d[:4]}-{d[4:6]}-{d[6:8]}" if re.fullmatch(r"\d{8}", d) else "")

    if missing:
        if shutil.which("yt-dlp"):
            with ThreadPoolExecutor(8) as ex:
                for name, d in ex.map(fetch, missing):
                    if d:
                        ups[name] = d
                    else:
                        print(f"warn: no upload date for {name}")
        else:
            print(f"warn: yt-dlp not found, {len(missing)} videos have no upload date")
    ups = {n: ups[n] for n in sorted(videos) if ups.get(n)}
    path.write_text(json.dumps(ups, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for name, v in videos.items():
        v["uploaded"] = ups.get(name, "")


# "2편", "3부", "Part 2", "EP.3", "#4" — breaks ties between videos uploaded the same day.
EPISODE = re.compile(r"(\d+)\s*(?:편|부|화|강)(?![가-힣])|\b(?:part|ep\.?|episode)\s*(\d+)|#(\d+)", re.I)


def episode(title):
    m = EPISODE.search(title)
    return int(next(g for g in m.groups() if g)) if m else 0


def upload_order(v):
    """Oldest upload first, so a channel's series reads 1편 → 2편; unknown dates go last."""
    return (v["uploaded"] or "9999", episode(v["title"]), v["title"])


def card(v, cat_label=None, show_channel=True, extra_q=""):
    href = "./" + quote(v["folder"]) + "/"
    thumb = f'https://i.ytimg.com/vi/{esc(v["vid"])}/mqdefault.jpg' if v["vid"] else ""
    search = " ".join([v["title"], v["subtitle"], v["channel"], cat_label or "", extra_q]).lower()
    meta = []
    if show_channel:
        meta.append(f'<span class="ch">{esc(v["channel"])}</span>')
    if v["duration"]:
        meta.append(f'<span>{esc(v["duration"])}</span>')
    if v.get("uploaded"):
        meta.append(f'<span>{esc(v["uploaded"].replace("-", "."))} 업로드</span>')
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
    """Same-channel videos (2+) go in one box, oldest upload first; the rest share a plain grid."""
    by_ch = OrderedDict()
    for v in vs:
        by_ch.setdefault(v["channel"], []).append(v)
    out, singles = [], []
    for ch, items in by_ch.items():
        if len(items) > 1:
            items.sort(key=upload_order)
            cards = "".join(card(v, show_channel=False, extra_q=cat_of[v["folder"]]) for v in items)
            out.append(
                f'<div class="chgroup" data-group><div class="chhead">{esc(ch)}'
                f'<span class="n">{len(items)}</span></div><div class="grid">{cards}</div></div>'
            )
        else:
            singles.extend(items)
    if singles:
        out.append('<div class="grid" data-group>' + "".join(card(v, extra_q=cat_of[v["folder"]]) for v in singles) + "</div>")
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


DIRECT = "_videos"  # categories.json key: folders placed on that level itself, not in a child


def cat_parts(node):
    """(folders placed here, child categories) of one categories.json node. A bare list holds folders only."""
    if isinstance(node, list):
        return node, OrderedDict()
    return node.get(DIRECT, []), OrderedDict((k, v) for k, v in node.items() if k != DIRECT)


def place_videos(node, path, videos, cat_of):
    """Fill cat_of with "대분류 › 중분류 › 소분류" (as deep as the folder sits) for every listed folder."""
    here, kids = cat_parts(node)
    for f in here:
        f = unicodedata.normalize("NFC", f)
        if f in cat_of:
            print(f"warn: categories.json lists {f} twice")
        if f in videos:
            cat_of[f] = " › ".join(path)
    if kids and len(path) == 3:
        print(f"warn: categories.json goes deeper than 소분류 under {' › '.join(path)}")
    for name, child in kids.items():
        place_videos(child, path + [name], videos, cat_of)


def cat_section(name, node, level, sec_id, videos, cat_of):
    """One category as <section>: 1 = 대분류 (with a 중분류 table of contents), 2 = 중분류, 3 = 소분류.
    Folders placed on the category itself come first, then its children. Returns (html, n_videos)."""
    here, kids = cat_parts(node)
    vs = sorted((videos[f] for f in (unicodedata.normalize("NFC", f) for f in here) if f in videos),
                key=lambda v: v["channel"])
    parts, toc, n = [], [], len(vs)
    for j, (kid, child) in enumerate(kids.items()):
        kid_id = f"{sec_id}-{j}"
        h, k = cat_section(kid, child, level + 1, kid_id, videos, cat_of)
        if k:
            parts.append(h)
            toc.append(f'<a href="#{kid_id}">{esc(kid)}<span class="n">{k}</span></a>')
            n += k
    if not n:
        return "", 0
    cls, head = {1: ("big", f"<h2>{esc(name)}<span class=\"n\">{n}</span></h2>"),
                 2: ("mid", f"<h3>{esc(name)}<span class=\"n\">{n}</span></h3>")}.get(
        level, ("sub", f'<h4 class="subh">{esc(name)}<span class="n">{n}</span></h4>'))
    if level == 1 and toc:
        head += f'<nav class="toc">{"".join(toc)}</nav>'
    body = (channel_blocks(vs, cat_of) if vs else "") + "".join(parts)
    return f'<section class="{cls}" id="{sec_id}" data-sec>{head}{body}</section>', n


def topic_view(videos):
    """topics.json: per big category, a list of {id, title, about, videos} — tight groups of similar
    videos, each meant to become one combined study page later. Returns (nav, html, n_topics)."""
    path = HERE / "topics.json"
    topics = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict) if path.exists() else {}
    nav, secs, grouped, n_topics = [], [], set(), 0
    for i, (big, groups) in enumerate(topics.items()):
        boxes, n_big = [], 0
        for t in groups:
            names = [unicodedata.normalize("NFC", f) for f in t["videos"]]
            for f in names:
                if f not in videos:
                    print(f"warn: topics.json '{t['id']}' lists a missing folder: {f}")
            vs = sorted((videos[f] for f in names if f in videos), key=upload_order)
            if not vs:
                continue
            grouped.update(v["folder"] for v in vs)
            n_topics += 1
            n_big += len(vs)
            cards = "".join(card(v, extra_q=t["title"]) for v in vs)
            boxes.append(
                f'<div class="tpgroup" id="t-{esc(t["id"])}" data-group><div class="tphead">{esc(t["title"])}'
                f'<span class="n">{len(vs)}</span></div><p class="tpabout">{esc(t.get("about", ""))}</p>'
                f'<div class="grid">{cards}</div></div>'
            )
        if boxes:
            sid = f"t{i}"
            nav.append(f'<a href="#{sid}">{esc(big)}<span class="n">{len(boxes)}</span></a>')
            secs.append(
                f'<section class="big" id="{sid}" data-sec><h2>{esc(big)}<span class="n">묶음 {len(boxes)}</span></h2>'
                f'{"".join(boxes)}</section>'
            )
    loose = sorted((v for n, v in videos.items() if n not in grouped), key=lambda v: (v["channel"], upload_order(v)))
    if loose:
        nav.append(f'<a href="#t-loose">아직 묶음이 없는 영상<span class="n">{len(loose)}</span></a>')
        secs.append(
            f'<section class="big" id="t-loose" data-sec><h2>아직 묶음이 없는 영상<span class="n">{len(loose)}</span></h2>'
            f'<p class="tpabout">비슷한 영상이 하나 더 생기면 묶음으로 옮겨요.</p>'
            f'<div class="grid" data-group>{"".join(card(v) for v in loose)}</div></section>'
        )
    return "".join(nav), "".join(secs), n_topics


def main():
    videos = load_videos()
    load_uploads(videos)
    cats =json.loads((HERE / "categories.json").read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
    cat_of = {}
    for big, node in cats.items():
        place_videos(node, [big], videos, cat_of)
    rest = sorted((f for f in videos if f not in cat_of), key=lambda f: (videos[f]["channel"], upload_order(videos[f])))
    for f in rest:
        cat_of[f] = "분류 없음"

    # category view
    nav, sections = [], []
    for i, (big, node) in enumerate(cats.items()):
        sid = f"c{i}"
        h, n = cat_section(big, node, 1, sid, videos, cat_of)
        if n:
            nav.append(f'<a href="#{sid}">{esc(big)}<span class="n">{n}</span></a>')
            sections.append(h)
    if rest:
        nav.append(f'<a href="#c-loose">아직 분류가 없는 영상<span class="n">{len(rest)}</span></a>')
        sections.append(
            f'<section class="big" id="c-loose" data-sec><h2>아직 분류가 없는 영상<span class="n">{len(rest)}</span></h2>'
            f'<p class="tpabout">맞는 분류가 생기면 그 자리로 옮겨요.</p>'
            f'{channel_blocks([videos[f] for f in rest], cat_of)}</section>'
        )

    # channel view
    by_ch = defaultdict(list)
    for v in videos.values():
        by_ch[v["channel"]].append(v)
    ch_sorted = sorted(by_ch.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))
    ch_html = []
    for ch, vs in ch_sorted:
        vs.sort(key=upload_order)
        cards ="".join(card(v, cat_label=cat_of[v["folder"]].split(" › ")[-1], show_channel=False) for v in vs)
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

    topic_nav, topic_html, n_topics = topic_view(videos)

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
        .replace("{{TOPIC_NAV}}", topic_nav)
        .replace("{{TOPIC_VIEW}}", topic_html)
        .replace("{{CHANNEL_VIEW}}", "".join(ch_html))
        .replace("{{TIME_VIEW}}", "".join(time_html))
    )
    (ROOT / "index.html").write_text(out, encoding="utf-8")
    changed = protect_pages(videos, pw_hash)
    print(f"document pages {'locked' if pw_hash else 'unlocked'}: {changed} changed")
    print(f"index.html: {len(videos)} videos, {len(cats)} categories, {n_topics} topics, {len(by_ch)} channels"
          + (f", 아직 분류가 없는 영상 {len(rest)}: {rest}" if rest else ""))


if __name__ == "__main__":
    main()
