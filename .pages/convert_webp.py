#!/usr/bin/env python3
"""Convert one video folder's assets/*.png to WebP and point every page file at the new names.

    python3 .pages/convert_webp.py [--keep-png] <folder> [<folder> ...]

For each PNG in <folder>/assets it writes a WebP next to it (cwebp, quality 82, same
setting as capture_frames.py), rewrites `assets/<name>.png` to `assets/<name>.webp` in
index.html, sections/*.html, content.json, summary.md, and widgets/*.js, checks that
every assets/ image the page uses exists and that no PNG reference is left, and only
then deletes the PNGs. Safe to rerun: a folder with no PNGs is reported as done.
--keep-png stops before the delete, so the caller can check the WebPs and remove the
PNGs itself.

Prints one JSON line per folder: converted count, MB before/after, and `problems`
(empty list = fine). Exits 1 if any folder has problems; its PNGs are kept.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

QUALITY = 82
PAGE_FILES = ("index.html", "content.json", "summary.md", "sections/*.html", "widgets/*.js")


def page_files(folder: Path) -> list[Path]:
    out: list[Path] = []
    for pat in PAGE_FILES:
        out += sorted(folder.glob(pat))
    return [p for p in out if p.is_file()]


def convert(folder: Path, keep_png: bool = False) -> dict:
    assets = folder / "assets"
    pngs = sorted(assets.glob("*.png")) if assets.is_dir() else []
    res = {"folder": folder.name, "converted": 0, "mb_before": 0.0, "mb_after": 0.0,
           "refs_rewritten": 0, "problems": []}
    if not pngs:
        res["note"] = "no PNGs left"
        return res

    for png in pngs:
        webp = png.with_suffix(".webp")
        proc = subprocess.run(["cwebp", "-quiet", "-q", str(QUALITY), "-m", "6", str(png), "-o", str(webp)],
                              capture_output=True, text=True)
        if proc.returncode != 0 or not webp.exists() or webp.stat().st_size == 0:
            res["problems"].append(f"cwebp failed: {png.name}: {proc.stderr.strip()[:120]}")
            continue
        res["converted"] += 1
        res["mb_before"] += png.stat().st_size / 1e6
        res["mb_after"] += webp.stat().st_size / 1e6
    if res["problems"]:
        return res

    names = {p.stem for p in pngs}
    ref = re.compile(r"(assets/)([^\"'\s()<>]+?)\.png\b")

    def swap(m: re.Match) -> str:
        return f"{m.group(1)}{m.group(2)}.webp" if m.group(2) in names else m.group(0)

    for f in page_files(folder):
        text = f.read_text(encoding="utf-8")
        new, n = ref.subn(swap, text)
        if new != text:
            f.write_text(new, encoding="utf-8")
            res["refs_rewritten"] += n

    for f in page_files(folder):
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"assets/[^\"'\s()<>]+?\.png\b", text):
            res["problems"].append(f"PNG reference left in {f.relative_to(folder)}: {m.group(0)}")
        if f.name == "index.html":
            for m in re.finditer(r"assets/([^\"'\s()<>]+?\.webp)\b", text):
                if not (assets / m.group(1)).exists():
                    res["problems"].append(f"missing image: assets/{m.group(1)}")
    if res["problems"]:
        return res

    if keep_png:
        res["png_kept"] = len(pngs)
    else:
        for png in pngs:
            png.unlink()
    res["mb_before"] = round(res["mb_before"], 1)
    res["mb_after"] = round(res["mb_after"], 1)
    return res


def main() -> None:
    args = sys.argv[1:]
    keep_png = "--keep-png" in args
    args = [a for a in args if a != "--keep-png"]
    if not args:
        sys.exit(__doc__)
    bad = False
    for arg in args:
        folder = Path(arg).expanduser().resolve()
        if not (folder / "index.html").exists():
            print(json.dumps({"folder": arg, "problems": ["no index.html here"]}, ensure_ascii=False))
            bad = True
            continue
        res = convert(folder, keep_png)
        bad |= bool(res["problems"])
        print(json.dumps(res, ensure_ascii=False))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
