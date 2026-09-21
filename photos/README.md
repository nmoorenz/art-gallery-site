# photos/

Your own art: `artwork.csv` and one image per piece, flat in this folder.
Everything here except this file and `.gitkeep` is gitignored, so nothing
reaches a public repository.

```
photos/
    artwork.csv
    dragon-castle.jpg
    blue-house.png
```

```csv
id,name,date,category,era,medium,description
dragon-castle,Dragon Castle,2024-03-11,Drawings,Age 6,Felt pen,"The dragon lives in the tower."
blue-house,Blue House,2024-05-02,Paintings,Age 6,Watercolour,
```

The image file is matched to a row by its `id` -- `dragon-castle.jpg` for the
row with `id=dragon-castle`. jpg, jpeg and png are all accepted.

```bash
python scripts/sync_gallery.py check     # no AWS, just reports
python scripts/sync_gallery.py sync      # upload and rebuild the manifest
```

`sync` does a full CSV-driven rebuild of `photos/manifest.json`, so it is an
import tool for an initial batch only -- once the site is live, art is added
through the web upload form and edited in `admin.html`.

[`example/`](../example/README.md) has the same layout with sample art.
