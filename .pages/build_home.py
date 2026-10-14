#!/usr/bin/env python3
"""Build the GitHub Pages home (../index.html) from categories.json and each folder's content.json.

Folders not listed in categories.json land in "미분류" so a new digest never goes missing.
Run: python3 .pages/build_home.py
"""
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
            "title": c.get("title", d.name),
            "subtitle": c.get("subtitle", ""),
            "channel": (c.get("channel") or "채널 미상").strip(),
            "duration": c.get("duration", ""),
            "vid": c.get("video_id") or (m.group(1) if m else ""),
        }
    return videos


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

    tpl = (HERE / "home_template.html").read_text(encoding="utf-8")
    out = (
        tpl.replace("{{COUNT}}", str(len(videos)))
        .replace("{{CATS}}", str(len(cats)))
        .replace("{{CHANNELS}}", str(len(by_ch)))
        .replace("{{NAV}}", "".join(nav))
        .replace("{{CATEGORY_VIEW}}", "".join(sections))
        .replace("{{CHANNEL_VIEW}}", "".join(ch_html))
    )
    (ROOT / "index.html").write_text(out, encoding="utf-8")
    print(f"index.html: {len(videos)} videos, {len(cats)} categories, {len(by_ch)} channels"
          + (f", 미분류 {len(rest)}: {rest}" if rest else ""))


if __name__ == "__main__":
    main()
