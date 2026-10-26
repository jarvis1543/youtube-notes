#!/usr/bin/env python3
"""Build one 합본 (a study page combining several digested videos) into <guide folder>/index.html.

A 합본 lives in its own root folder, guide-<id>/, laid out like a video folder:
  guide.json        title, subtitle, videos ({slug: video folder}), keypoints, terms, acronyms,
                    sections, optional extra sources and footer
  sections/NN.html  section bodies, written with youtube-digest's HTML snippets
  widgets/*.js      drawn figures, if any (listed in guide.json "scripts")
  assets/           captures, named <slug>-frame-XXXX.webp
It has guide.json instead of content.json, so build_home.py lists it as a 합본, not a video.

What this adds on top of youtube-digest's build_page.py:
  - copies every assets/<slug>-frame-XXXX.webp the sections use from <video folder>/assets/frame-XXXX.webp,
    and drops copies no section uses any more
  - fills the single-video fields (channel, duration, video link) and puts every video first in the
    sources, in "videos" order
  - points the header button at the source list instead of one video
Run: python3 .pages/build_guide.py guide-<id>     then python3 .pages/build_home.py
     python3 .pages/build_guide.py guide-<id> --frames   lists every capture the listed videos have
     (src to paste, caption link, alt) to pick from while writing; builds nothing
"""
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SKILL = Path.home() / ".claude/skills/youtube-digest"
ASSET = re.compile(r"assets/([a-z0-9]+)-frame-([0-9]+)\.webp")


def seconds(stamp):
    parts = [int(p) for p in str(stamp).split(":")]
    return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))


def stamp(t):
    h, m, s = t // 3600, t % 3600 // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def list_frames(videos):
    for slug, (d, c) in videos.items():
        print(f"## {slug} — {c['title']}")
        page = (d / "index.html").read_text(encoding="utf-8")
        for fig in re.findall(r"<figure\b(?:(?!</figure>).)*</figure>", page, re.S):
            img = re.search(r'src="assets/frame-([0-9]+)\.webp"[^>]*alt="([^"]*)"', fig)
            t = re.search(r"t=(\d+)s", fig)
            if img and t:
                print(f"assets/{slug}-frame-{img.group(1)}.webp  {c['video_url']}&amp;t={t.group(1)}s  "
                      f"{stamp(int(t.group(1)))}  {img.group(2)}")


def main():
    args = [a for a in sys.argv[1:] if a != "--frames"]
    if len(args) != 1:
        sys.exit(__doc__)
    folder = (ROOT / args[0]).resolve()
    spec = json.loads((folder / "guide.json").read_text(encoding="utf-8"))
    videos = {}
    for slug, name in spec["videos"].items():
        d = ROOT / unicodedata.normalize("NFC", name)
        if not (d / "content.json").exists():
            sys.exit(f"error: guide.json videos.{slug}: no digested folder {name}")
        videos[slug] = (d, json.loads((d / "content.json").read_text(encoding="utf-8")))
    if "--frames" in sys.argv:
        return list_frames(videos)

    # captures: copy what the sections use, drop what they no longer use
    used = set()
    for sec in spec["sections"]:
        used.update(ASSET.findall((folder / sec["html_file"]).read_text(encoding="utf-8")))
    assets = folder / "assets"
    assets.mkdir(exist_ok=True)
    for slug, frame in sorted(used):
        if slug not in videos:
            sys.exit(f"error: assets/{slug}-frame-{frame}.webp: '{slug}' is not in guide.json videos")
        dst = assets / f"{slug}-frame-{frame}.webp"
        if not dst.exists():
            src = videos[slug][0] / "assets" / f"frame-{frame}.webp"
            if not src.exists():
                sys.exit(f"error: {src} not found")
            shutil.copy2(src, dst)
    keep = {f"{s}-frame-{f}.webp" for s, f in used}
    for f in assets.iterdir():
        if f.name not in keep:
            f.unlink()

    total = sum(seconds(c.get("duration") or 0) for _, c in videos.values())
    channels = {(c.get("channel") or "").strip() for _, c in videos.values()}
    build = dict(spec)
    build.update({
        "channel": f"유튜브 채널 {len(channels)}곳",
        "duration": f"{len(videos)}편 · 모두 약 {round(total / 3600)}시간",
        "video_url": "#sources",
        "video_id": "",
        "sources": [{"title": f"{c['title']} — {c.get('channel', '')}", "url": c["video_url"]}
                    for _, c in videos.values()] + spec.get("sources", []),
    })
    tmp = folder / ".build.json"   # build_page.py reads html_file paths relative to its input
    tmp.write_text(json.dumps(build, ensure_ascii=False), encoding="utf-8")
    try:
        r = subprocess.run([sys.executable, str(SKILL / "scripts/build_page.py"), str(tmp),
                            "--template", str(SKILL / "assets/template.html"),
                            "--out", str(folder / "index.html")])
    finally:
        tmp.unlink()
    if r.returncode:
        sys.exit(r.returncode)

    page = folder / "index.html"
    src = page.read_text(encoding="utf-8")
    out, n = re.subn(r'<a class="src-btn" href="#sources"[^>]*>\s*원본 영상 보러 가기 →\s*</a>',
                     f'<a class="src-btn" href="#sources">원본 영상 {len(videos)}편 목록 ↓</a>', src)
    if not n:
        print("warn: header button not found; check the youtube-digest template", file=sys.stderr)
    page.write_text(out, encoding="utf-8")
    print(f"guide: {folder.name}, {len(videos)} videos, {len(keep)} captures")


if __name__ == "__main__":
    main()
