# Scripts

All commands below assume the repo root as the working directory. Copy
`env.example` (repo root) to `.env` and fill it in before using any script
that touches AWS.

## tf.py

Wrapper around `terraform`: loads `.env`, maps the deployment-specific
values to `TF_VAR_*`, adds `-chdir=infrastructure`, and passes every other
argument straight through.

```
python scripts/tf.py init
python scripts/tf.py cert                            first-stage certificate apply
python scripts/tf.py apply
python scripts/tf.py output cloudfront_domain_name
```

`cert` is the only argument tf.py handles itself: it applies the certificate
alone and prints its DNS validation record. Everything else goes through to
terraform untouched.

Fails with a clear message if a required `.env` value is missing, before
calling `terraform` at all. See
[`infrastructure/README.md`](../infrastructure/README.md) for which values
are required. Set `TERRAFORM` to use a terraform binary that is not on PATH.

`tf.py` will not run while `infrastructure/terraform.tfvars` or any
`*.auto.tfvars` exists -- terraform loads those automatically and they
override the values passed from `.env`, silently. It builds any missing
`infrastructure/build/<name>/` bundle before calling terraform.

## deploy_site.py

`python scripts/deploy_site.py` syncs `site/` to the `site/` prefix in S3 and
invalidates CloudFront. It writes the deployed `config.js` from Terraform's
outputs into `build/` and uploads it from there; the committed
`site/config.js` keeps its local-dev placeholders. Run it after an apply, or
after any frontend change. Needs `.env`, terraform and the aws CLI on PATH.

## sync_gallery.py

One-time bootstrap/import tool for artwork metadata and photos -- not the
ongoing way art gets added once the site is live. Uploads and category/era
edits go through the web form and `admin.html` instead (see
[`site/README.md`](../site/README.md)), both of which write straight to
`photos/manifest.json` in S3. Running `sync` after real uploads exist
would overwrite them, since it rebuilds `manifest.json` from the CSV every
time rather than merging.

Data layout (gitignored, not committed -- see
[`example/README.md`](../example/README.md) for a committed folder in the
same shape):
- `photos/artwork.csv` -- one row per image:
  `id,name,date,category,era,medium,description,group_id,label`.
  `category` decides which room/corridor a piece is shown in; `era` is
  just a tag. Rows that share a non-empty `group_id` become one piece
  with several images (front/back of a page, more than one photo of the
  same piece, ...) -- each row keeps its own `id` and file, and only the
  first row in a group's name/date/category/era/medium/description
  columns are used. `label` is an optional per-image caption. Copy
  `example/artwork.csv` to `photos/artwork.csv` and fill in your own rows.
- `photos/<id>.<ext>` -- one image per row (jpg/jpeg/png), matching that
  row's `id` column, alongside `artwork.csv`.

```
python scripts/sync_gallery.py check      # join photos/artwork.csv against the images in photos/, no AWS calls
python scripts/sync_gallery.py sync       # build thumb/full derivatives, upload, rebuild manifest.json
python scripts/sync_gallery.py download   # pull full-resolution originals from S3 into photos/
python scripts/sync_gallery.py export     # write the deployed manifest back out to photos/artwork.csv
python scripts/sync_gallery.py rename --piece OLD --to NEW
python scripts/sync_gallery.py delete --piece ID [--photos] --yes
```

`export`, `rename` and `delete` edit the deployed `photos/manifest.json` in
place rather than rebuilding it, so they are safe on a live gallery --
`export` is how art added through the web upload form gets back into
`photos/artwork.csv` (writing one row per image, with `group_id` filled in
for multi-image pieces). `delete` drops the piece from the manifest,
including every image it has; add `--photos` to remove them from S3 as
well. `rename` only works on a single-image piece -- edit
`photos/manifest.json` by hand to rename a grouped one. Both `rename` and
`delete` report what they would do until you pass `--yes`.

## build_local_preview.py

Builds `site/manifest.json` and `site/sample-photos/` (both gitignored)
from the committed [`example/`](../example/README.md) folder -- no AWS, no
real data, safe to re-run.

```
python scripts/build_local_preview.py
```

## build_lambdas.py

Assembles each function under `infrastructure/lambda/` into
`infrastructure/build/<name>/`: the handler plus its `requirements.txt`,
installed for Lambda's platform (manylinux, cp312). Terraform zips that
directory into `infrastructure/dist/`.

```
python scripts/build_lambdas.py
```

Run it before `terraform apply`, and again after changing a handler or its
`requirements.txt`.
