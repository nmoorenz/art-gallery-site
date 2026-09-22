#!/usr/bin/env python3
"""
Builds a local preview of the gallery from the committed example/ folder --
no AWS, no real data required. Reads example/artwork.csv and its matching
example/<id>.<ext> images, and writes site/manifest.json plus
site/sample-photos/ (both gitignored) so `python -m http.server` in site/
can serve them.

Rows that share a non-empty group_id become one piece with multiple images
(see example/README.md) -- same grouping rule as scripts/sync_gallery.py.

Usage:
    python scripts/build_local_preview.py

Safe to re-run; overwrites site/sample-photos/ and site/manifest.json.
Not part of the real sync pipeline -- see sync_gallery.py for that, and
example/README.md for what's in example/ and why.
"""
import csv
import json
import sys
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_DIR = ROOT / "example"
EXAMPLE_CSV = EXAMPLE_DIR / "artwork.csv"
SITE = ROOT / "site"
OUT_PHOTOS = SITE / "sample-photos"

VALID_EXT = {".jpg", ".jpeg", ".png"}


def find_photo(piece_id: str):
    for ext in VALID_EXT:
        candidate = EXAMPLE_DIR / f"{piece_id}{ext}"
        if candidate.exists():
            return candidate
    return None


def group_rows(rows):
    """Group CSV rows into pieces: rows sharing a non-empty group_id become
    one piece with multiple images (in CSV order); every other row is its
    own single-image piece. Returns a list of (piece_id, [row, ...])."""
    groups = []
    index_of = {}
    for row in rows:
        gid = (row.get("group_id") or "").strip()
        if gid:
            if gid not in index_of:
                index_of[gid] = len(groups)
                groups.append((gid, []))
            groups[index_of[gid]][1].append(row)
        else:
            groups.append((row["id"].strip(), [row]))
    return groups


def main():
    if not EXAMPLE_CSV.exists():
        sys.exit(f"Missing {EXAMPLE_CSV} -- is the example/ folder intact?")

    OUT_PHOTOS.mkdir(parents=True, exist_ok=True)
    with EXAMPLE_CSV.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    pieces = []
    for _gid, group in group_rows(rows):
        images = []
        piece_meta = None
        for row in group:
            piece_id = row["id"].strip()
            photo = find_photo(piece_id)
            if not photo:
                print(f"WARN: skipping {piece_id} -- no photo found in {EXAMPLE_DIR}/")
                continue

            dest = OUT_PHOTOS / f"{piece_id}.jpg"
            with Image.open(photo) as img:
                img = ImageOps.exif_transpose(img)
                aspect = img.width / img.height
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(dest, "JPEG", quality=90)

            images.append({
                "id": piece_id,
                "label": (row.get("label") or "").strip(),
                "thumb": f"sample-photos/{dest.name}",
                "full": f"sample-photos/{dest.name}",
                "aspect": round(aspect, 4),
            })
            if piece_meta is None:
                piece_meta = row

        if not images:
            continue

        pieces.append({
            "id": images[0]["id"],
            "name": piece_meta.get("name", "").strip(),
            "date": piece_meta.get("date", "").strip(),
            "category": piece_meta.get("category", "").strip() or "Uncategorised",
            "era": piece_meta.get("era", "").strip(),
            "medium": piece_meta.get("medium", "").strip(),
            "description": piece_meta.get("description", "").strip(),
            "images": images,
        })

    pieces.sort(key=lambda p: (p["category"], p["date"]))
    manifest = {
        "generated": "local-preview",
        "hallway": {"width": 6, "wallHeight": 3.2, "spacing": 2.4, "margin": 2.2},
        "pieces": pieces,
    }
    (SITE / "manifest.json").write_text(json.dumps(manifest, indent=2))

    categories = sorted({p["category"] for p in pieces})
    image_count = sum(len(p["images"]) for p in pieces)
    print(f"Wrote {len(pieces)} sample piece(s) ({image_count} image(s)) across {len(categories)} categories ({', '.join(categories)})")
    print(f"to {OUT_PHOTOS} and site/manifest.json")


if __name__ == "__main__":
    main()
