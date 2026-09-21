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
- `photos/artwork.csv` -- one row per piece:
  `id,name,date,category,era,medium,description`. `category` decides
  which room/corridor a piece is shown in; `era` is just a tag. Copy
  `example/artwork.csv` to `photos/artwork.csv` and fill in your own rows.
- `photos/<id>.<ext>` -- one image per piece (jpg/jpeg/png), matching the
  `id` column, alongside `artwork.csv`.

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
`photos/artwork.csv`. `delete` drops the piece from the manifest; add
`--photos` to remove its images from S3 as well. Both `rename` and `delete`
report what they would do until you pass `--yes`.

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
