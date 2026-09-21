#!/usr/bin/env python3
"""
Gallery sync CLI: check/sync/download for a single-photo-per-piece art
gallery.

This is a one-time bootstrap/import tool, not the ongoing way art gets
added. Once the site is deployed, uploads go through the web upload form
and category/era edits through admin.html -- both write directly to
photos/manifest.json in S3 via the pieces-api Lambda. `sync` here does a
full CSV-driven REBUILD of manifest.json, so running it after the site has
real uploads on it would overwrite them. Only use it to import an initial
batch of art before anyone starts using the web form.

Data model:
  photos/artwork.csv  one row per piece: id,name,date,category,era,medium,description
                      -- category decides which room/corridor a piece is
                      hung in; era (daycare, year 1, ...) is just a tag
                      shown on the piece and does not affect layout.
                      Gitignored -- see example/ (repo root) for a committed
                      folder in the same shape with invented content; copy
                      its artwork.csv to photos/artwork.csv as a starting
                      point, or start from scratch.
  photos/<id>.<ext>   one image per piece (jpg/jpeg/png), named to match
                      the id column, alongside artwork.csv. Gitignored.

S3 layout (bucket root):
  site/...            the static site (see scripts/deploy_site.sh)
  photos/manifest.json
  photos/<id>/thumb.jpg   in-scene wall texture
  photos/<id>/full.jpg    info-panel / lightbox image
  photos/<id>/orig/<filename>   untouched original, archived, not public

Commands:
  check     Join photos/artwork.csv against the images in photos/ locally.
            No AWS calls.
  sync      Build thumb+full derivatives for every piece, upload everything
            (including manifest.json) to S3 under photos/, and write a local
            copy to photos/manifest.json (gitignored) for your own
            reference.
  download  Print bucket size and pull full-resolution originals from S3
            into photos/ -- for setting up a new machine.
  export    Write the pieces in the deployed manifest back out to a CSV in
            the same shape as photos/artwork.csv, including anything added
            through the web upload form.
  rename    Move a piece's images and manifest entry to a new id.
  delete    Remove a piece from the manifest, optionally with its images.

The last three read and write the deployed photos/manifest.json in place
rather than rebuilding it, so they are safe to use on a live gallery.

Requires a .env (copy env.example) with S3_BUCKET, AWS_REGION, and either
AWS_PROFILE (locally) or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY (CI).
"""
import argparse
import csv
import datetime
import io
import json
import os
import re
import sys
from pathlib import Path

import boto3
from dotenv import load_dotenv
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
PHOTOS_DIR = ROOT / "photos"
CSV_PATH = PHOTOS_DIR / "artwork.csv"
MANIFEST_PATH = PHOTOS_DIR / "manifest.json"
EXAMPLE_DIR = ROOT / "example"
EXAMPLE_CSV = EXAMPLE_DIR / "artwork.csv"

THUMB_MAX = 1000   # in-scene wall texture resolution (longest edge)
FULL_MAX = 2000    # info-panel / lightbox resolution (longest edge)
JPEG_QUALITY = 85

VALID_EXT = {".jpg", ".jpeg", ".png"}


def load_env():
    load_dotenv(ROOT / ".env")
    bucket = os.environ.get("S3_BUCKET")
    region = os.environ.get("AWS_REGION")
    if not bucket or not region:
        sys.exit("Missing S3_BUCKET / AWS_REGION -- copy env.example to .env and fill it in.")
    return bucket, region


def s3_client(region: str):
    profile = os.environ.get("AWS_PROFILE")
    if profile:
        session = boto3.Session(profile_name=profile, region_name=region)
    else:
        session = boto3.Session(region_name=region)  # CI: uses AWS_ACCESS_KEY_ID/SECRET env vars
    return session.client("s3")


def read_rows():
    if not CSV_PATH.exists():
        sys.exit(
            f"Missing {CSV_PATH}\n"
            f"Copy {EXAMPLE_CSV.relative_to(ROOT)} to {CSV_PATH.relative_to(ROOT)} "
            f"(and matching images from {EXAMPLE_DIR.relative_to(ROOT)}/, or your own) "
            f"and fill it in ({PHOTOS_DIR.name}/ is gitignored)."
        )
    with CSV_PATH.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def find_photo(piece_id: str):
    for ext in VALID_EXT:
        candidate = PHOTOS_DIR / f"{piece_id}{ext}"
        if candidate.exists():
            return candidate
    return None


def cmd_check(_args):
    rows = read_rows()
    row_ids = {r["id"] for r in rows}
    photo_ids = {p.stem for p in PHOTOS_DIR.glob("*") if p.suffix.lower() in VALID_EXT}

    missing_photo = sorted(row_ids - photo_ids)
    missing_row = sorted(photo_ids - row_ids)

    print(f"{len(rows)} rows in photos/artwork.csv, {len(photo_ids)} photos in photos/")
    if missing_photo:
        print("WARN: rows with no matching photo:", ", ".join(missing_photo))
    if missing_row:
        print("WARN: photos with no matching CSV row:", ", ".join(missing_row))
    if not missing_photo and not missing_row:
        print("All good -- every row has a photo and every photo has a row.")


def make_derivative(img: Image.Image, max_edge: int) -> bytes:
    img = img.copy()
    img.thumbnail((max_edge, max_edge), Image.LANCZOS)
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


def cmd_sync(_args):
    bucket, region = load_env()
    client = s3_client(region)
    rows = read_rows()

    pieces = []
    for row in rows:
        piece_id = row["id"].strip()
        photo = find_photo(piece_id)
        if not photo:
            print(f"WARN: skipping {piece_id} -- no photo found in photos/")
            continue

        with Image.open(photo) as raw:
            raw = ImageOps.exif_transpose(raw)
            aspect = raw.width / raw.height
            thumb_bytes = make_derivative(raw, THUMB_MAX)
            full_bytes = make_derivative(raw, FULL_MAX)

        thumb_key = f"photos/{piece_id}/thumb.jpg"
        full_key = f"photos/{piece_id}/full.jpg"
        orig_key = f"photos/{piece_id}/orig/{photo.name}"

        client.put_object(Bucket=bucket, Key=thumb_key, Body=thumb_bytes, ContentType="image/jpeg")
        client.put_object(Bucket=bucket, Key=full_key, Body=full_bytes, ContentType="image/jpeg")
        client.upload_file(str(photo), bucket, orig_key)  # untouched original, archived, not in manifest

        pieces.append({
            "id": piece_id,
            "name": row.get("name", "").strip(),
            "date": row.get("date", "").strip(),
            "category": row.get("category", "").strip() or "Uncategorised",
            "era": row.get("era", "").strip(),
            "medium": row.get("medium", "").strip(),
            "description": row.get("description", "").strip(),
            "thumb": f"/{thumb_key}",
            "full": f"/{full_key}",
            "aspect": round(aspect, 4),
        })
        print(f"synced {piece_id} ({row.get('name', '')})")

    # human-readable order: grouped by category, chronological within each
    # (the frontend does its own grouping/sorting from this same data --
    # this is just so manifest.json itself reads sensibly and diffs cleanly)
    pieces.sort(key=lambda p: (p["category"], p["date"]))

    manifest = {
        "generated": datetime.datetime.utcnow().isoformat() + "Z",
        "hallway": {"width": 6, "wallHeight": 3.2, "spacing": 2.4, "margin": 2.2},
        "pieces": pieces,
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    client.put_object(
        Bucket=bucket, Key="photos/manifest.json",
        Body=json.dumps(manifest).encode("utf-8"),
        ContentType="application/json",
        CacheControl="no-cache",
    )
    print(f"\nWrote {MANIFEST_PATH.relative_to(ROOT)} ({len(pieces)} pieces) and uploaded it to s3://{bucket}/photos/manifest.json")
    print("Remember to invalidate the CloudFront distribution for /photos/manifest.json")
    print("if you need viewers to see the update immediately (see infrastructure/README.md).")


def cmd_download(_args):
    bucket, region = load_env()
    client = s3_client(region)

    total_bytes = 0
    paginator = client.get_paginator("list_objects_v2")
    downloaded = 0
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            total_bytes += obj["Size"]
            if "/orig/" in obj["Key"]:
                dest = PHOTOS_DIR / Path(obj["Key"]).name
                dest.parent.mkdir(parents=True, exist_ok=True)
                client.download_file(bucket, obj["Key"], str(dest))
                downloaded += 1

    print(f"Bucket size: {total_bytes / (1024*1024):.1f} MB")
    print(f"Downloaded {downloaded} originals into {PHOTOS_DIR}")


MANIFEST_KEY = "photos/manifest.json"
CSV_COLUMNS = ["id", "name", "date", "category", "era", "medium", "description"]
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def read_manifest(client, bucket):
    """The deployed manifest -- the source of truth once the site is live."""
    try:
        got = client.get_object(Bucket=bucket, Key=MANIFEST_KEY)
    except client.exceptions.NoSuchKey:
        sys.exit(f"No {MANIFEST_KEY} in s3://{bucket} yet -- run `sync` first.")
    return json.loads(got["Body"].read())


def write_manifest(client, bucket, manifest):
    manifest["generated"] = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    manifest["pieces"].sort(key=lambda p: (p.get("category", ""), p.get("date", "")))
    client.put_object(
        Bucket=bucket, Key=MANIFEST_KEY,
        Body=json.dumps(manifest).encode("utf-8"),
        ContentType="application/json",
        CacheControl="no-cache",
    )


def find_piece(manifest, piece_id):
    return next((p for p in manifest.get("pieces", []) if p.get("id") == piece_id), None)


def piece_keys(client, bucket, piece_id):
    """Every object under photos/<id>/ -- thumb, full and the archived orig."""
    paginator = client.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=f"photos/{piece_id}/"):
        keys.extend(obj["Key"] for obj in page.get("Contents", []))
    return sorted(keys)


def cmd_export(args):
    bucket, region = load_env()
    client = s3_client(region)
    manifest = read_manifest(client, bucket)
    pieces = manifest.get("pieces", [])

    target = Path(args.out) if args.out else CSV_PATH
    if target.exists() and not args.force:
        sys.exit(f"{target} already exists -- pass --force to overwrite, or --out somewhere else.")

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for piece in pieces:
            writer.writerow({column: piece.get(column, "") for column in CSV_COLUMNS})
    print(f"Wrote {len(pieces)} piece(s) to {target}")


def cmd_rename(args):
    bucket, region = load_env()
    client = s3_client(region)

    if not ID_PATTERN.match(args.to):
        sys.exit(f"'{args.to}' is not a plain lowercase slug.")

    manifest = read_manifest(client, bucket)
    piece = find_piece(manifest, args.piece)
    if piece is None:
        sys.exit(f"No piece '{args.piece}' in the manifest.")
    if find_piece(manifest, args.to) is not None:
        sys.exit(f"'{args.to}' already exists.")

    for key in piece_keys(client, bucket, args.piece):
        new_key = key.replace(f"photos/{args.piece}/", f"photos/{args.to}/", 1)
        print(f"mv {key} -> {new_key}")
        client.copy_object(Bucket=bucket, Key=new_key, CopySource={"Bucket": bucket, "Key": key})
        client.delete_object(Bucket=bucket, Key=key)

    piece["id"] = args.to
    piece["thumb"] = f"/photos/{args.to}/thumb.jpg"
    piece["full"] = f"/photos/{args.to}/full.jpg"
    write_manifest(client, bucket, manifest)
    print(f"Renamed '{args.piece}' to '{args.to}'. Update the id in photos/artwork.csv too.")


def cmd_delete(args):
    bucket, region = load_env()
    client = s3_client(region)

    manifest = read_manifest(client, bucket)
    piece = find_piece(manifest, args.piece)
    if piece is None:
        sys.exit(f"No piece '{args.piece}' in the manifest.")

    if not args.yes:
        extra = " and delete its images" if args.photos else ""
        print(f"Would remove '{args.piece}' ({piece.get('name', '')}){extra}. Re-run with --yes.")
        return

    manifest["pieces"] = [p for p in manifest["pieces"] if p.get("id") != args.piece]
    if args.photos:
        for key in piece_keys(client, bucket, args.piece):
            print(f"rm {key}")
            client.delete_object(Bucket=bucket, Key=key)

    write_manifest(client, bucket, manifest)
    print(f"Removed '{args.piece}' from the manifest.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="local join check, no AWS").set_defaults(func=cmd_check)
    sub.add_parser("sync", help="build derivatives, upload, rebuild manifest").set_defaults(func=cmd_sync)
    sub.add_parser("download", help="pull originals from S3 to set up a new machine").set_defaults(func=cmd_download)

    p_ex = sub.add_parser("export", help="write the deployed manifest back out to CSV")
    p_ex.add_argument("--out", help="write here instead of photos/artwork.csv")
    p_ex.add_argument("--force", action="store_true", help="overwrite an existing file")
    p_ex.set_defaults(func=cmd_export)

    p_rn = sub.add_parser("rename", help="move a piece's images and manifest entry to a new id")
    p_rn.add_argument("--piece", required=True, help="current piece id")
    p_rn.add_argument("--to", required=True, help="new piece id")
    p_rn.set_defaults(func=cmd_rename)

    p_del = sub.add_parser("delete", help="remove a piece from the manifest")
    p_del.add_argument("--piece", required=True, help="piece id")
    p_del.add_argument("--photos", action="store_true", help="delete its images too")
    p_del.add_argument("--yes", action="store_true", help="actually delete")
    p_del.set_defaults(func=cmd_delete)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
