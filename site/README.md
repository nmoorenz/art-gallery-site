# Site

A plain Three.js frontend (CDN import map, no build step) plus a small set
of static pages. No build tooling -- every file here is served as-is.

## Pages

- **`index.html`** -- the 3D gallery. Fetches `manifest.json` and groups
  pieces by `category` into a hub-and-spoke layout: a circular hub with
  one corridor per category radiating outward at an evenly spaced angle,
  each corridor growing in length as more art is added to it. Each
  corridor entrance carries a floating label with the category name.
  `era` is a tag shown on each piece; it does not affect layout. Desktop
  and touch both use click-and-drag/touch-drag to look around. On desktop,
  WASD walks (A/D strafe) and the up/down arrows also walk, while the
  left/right arrows turn in place instead of strafing; touch uses the
  joystick to walk. Click/tap a piece for an info panel (name,
  date, era, medium, description, full-resolution image).
- **`login.html`** -- sends the browser to the Cognito Hosted UI.
- **`upload.html`** -- admin/superadmin-only upload form: photo picker
  with live preview, category tiles and era chips (from
  `gallery-taxonomy.js`), a name field ("What's it called?"), an optional
  description field ("What do you want to say about it?"), and a date. On
  submit it resizes the photo to thumb (1000px) and full (2000px) JPEGs in
  the browser via canvas, uploads all three sizes straight to S3 using
  presigned URLs, then registers the piece through the API.
- **`admin.html`** -- superadmin-only category/era editor. Lists every
  piece from `manifest.json` with editable category/era dropdowns and a
  per-row Save button.

## Access control

Three tiers, enforced server-side (not just hidden in the UI):

- **superadmin** -- can edit any existing piece's category/era via
  `admin.html`.
- **admin** -- can upload new pieces via `upload.html`.
- **viewer** -- anyone else logged in; can browse only.

Mapped to two Cognito groups (`superadmin`, `admin`); no group membership
means viewer.

Logging in redirects through `/auth/callback`, which issues CloudFront
signed cookies (gating `/photos/*`) and a separate `id_token` cookie
(gating `/api/*`). A visitor without a valid signed cookie is shown
`login.html` instead of a raw error.

## Data

`photos/manifest.json` in S3 is the single source of truth for the
gallery and both admin pages. `upload.html` and `admin.html` read and
write it through the `pieces-api` Lambda behind `/api/*`:

- `POST /api/upload-url` -- presigned S3 PUT URLs for a new piece's images
- `POST /api/pieces` -- registers a new piece
- `PATCH /api/pieces/{id}` -- edits an existing piece's category/era

## Supporting files

- **`config.js`** -- `MANIFEST_URL`, the Cognito domain/client ID,
  and the auth redirect URI. Committed with local-dev placeholders; the
  real values are generated at deploy time into a separate, gitignored
  file (see [`scripts/README.md`](../scripts/README.md#deploy_sitepy)) --
  never hand-edit this file for production.
- **`gallery-taxonomy.js`** -- the shared category/era lists `upload.html`
  and `admin.html` both use.
- **`style.css`**, **`upload.css`**, **`admin.css`** -- per-page styling.

## Local preview

From the repo root:

```
python scripts/build_local_preview.py
cd site && python -m http.server 8000
```

Open http://localhost:8000. The gallery, controls, and info panel all
work with no login. `upload.html` and `admin.html` load and render too
(`admin.html` reads the same local `manifest.json`), but any actual save
fails with a friendly error -- `pieces-api` only exists once deployed
behind CloudFront.
