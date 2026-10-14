#!/usr/bin/env python3
"""Delete one digested video: its folder and every entry in .pages/*.json, then rebuild the home.

  python3 .pages/remove_video.py "<제목 일부 또는 폴더 이름>"         # list matches only
  python3 .pages/remove_video.py "<제목 일부 또는 폴더 이름>" --yes   # delete when exactly one matches

Matches against the folder name and the content.json title, ignoring case, spaces and punctuation.
Exit 1 = no match, 2 = several matches (nothing deleted). Git commit/push is left to the caller.
"""
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def norm(s):
    s = unicodedata.normalize("NFC", s).lower()
    return re.sub(r"[\W_]+", "", s)


def candidates():
    for d in sorted(ROOT.iterdir()):
        cj = d / "content.json"
        if d.is_dir() and not d.name.startswith(".") and cj.exists():
            title = json.loads(cj.read_text(encoding="utf-8")).get("title", "")
            yield unicodedata.normalize("NFC", d.name), d, title


def load(name):
    p = HERE / name
    return p, (json.loads(p.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict) if p.exists() else None)


def save(p, data):
    indent = 1 if p.name in ("dates.json", "uploads.json") else 2  # match build_home.py's own output
    p.write_text(json.dumps(data, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8")


def main():
    args = [a for a in sys.argv[1:] if a != "--yes"]
    if len(args) != 1:
        sys.exit(__doc__)
    q = norm(args[0])
    hits = [(n, d, t) for n, d, t in candidates() if q and (q in norm(n) or q in norm(t))]
    if not hits:
        print("no match")
        sys.exit(1)
    for n, _, t in hits:
        print(f"{n}\t{t}")
    if len(hits) > 1:
        print(f"{len(hits)} matches, nothing deleted")
        sys.exit(2)
    if "--yes" not in sys.argv:
        print("dry run: add --yes to delete")
        return

    name, folder, _ = hits[0]
    shutil.rmtree(folder)

    p, cats = load("categories.json")
    for big in list(cats):
        for sub in list(cats[big]):
            cats[big][sub] = [f for f in cats[big][sub] if unicodedata.normalize("NFC", f) != name]
            if not cats[big][sub]:
                del cats[big][sub]
        if not cats[big]:
            del cats[big]
    save(p, cats)

    p, topics = load("topics.json")
    if topics:
        for big in list(topics):
            for t in topics[big]:
                t["videos"] = [f for f in t["videos"] if unicodedata.normalize("NFC", f) != name]
                if len(t["videos"]) == 1:
                    print(f"note: topic '{t['id']}' now has one video; merge it elsewhere or delete it")
            topics[big] = [t for t in topics[big] if t["videos"]]
            if not topics[big]:
                del topics[big]
        save(p, topics)

    for fname in ("dates.json", "uploads.json"):
        p, data = load(fname)
        if data and name in data:
            del data[name]
            save(p, data)

    print(f"deleted: {name}", flush=True)
    subprocess.run([sys.executable, str(HERE / "build_home.py")], check=True)


if __name__ == "__main__":
    main()
