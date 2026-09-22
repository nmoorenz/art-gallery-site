# example/

Committed sample data, in exactly the shape `photos/` (gitignored, your
real data) is expected to be in:

- `artwork.csv` -- one row per image: `id,name,date,category,era,medium,description,group_id,label`.
  Rows that share a non-empty `group_id` become one piece with multiple
  images (say, the front and back of a page) -- each row still keeps its
  own `id` and file, so grouping never means renaming anything. `label`
  is an optional per-image caption ("Front", "Back", ...). See
  [`../scripts/README.md`](../scripts/README.md#sync_gallerypy) for the
  full rule.
- `<id>.jpg` -- one image per row, matching that row's `id` column.

20 real, public-domain paintings and prints (5 each from Rembrandt, Monet,
Van Gogh, and Hokusai -- all long out of copyright), one `category` per
artist so each gets its own corridor. Images are downsized (500px) JPEGs
sourced from Wikimedia Commons; descriptions are original one-liners, not
copied from anywhere.

## Local preview

From the repo root:

```
python scripts/build_local_preview.py
cd site && python -m http.server 8000
```

Open http://localhost:8000. This reads `example/artwork.csv` and its
images, and writes `site/manifest.json` plus `site/sample-photos/` (both
gitignored) for the frontend to serve. Re-run it any time; it always
rebuilds from `example/` from scratch.

## Using your own data instead

Copy this folder's shape into a `photos/` folder at the repo root
(`photos/artwork.csv` + `photos/<id>.<ext>`) -- gitignored, so it never
gets committed. See [`../scripts/README.md`](../scripts/README.md) for
`sync_gallery.py`, which uploads from there to S3.
