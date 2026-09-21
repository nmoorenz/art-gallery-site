# Art Gallery

A private, walkable 3D gallery for browsing kids' artwork. Visitors log in
with their own account; photos are access-controlled, not just the page.

## Folders

| Folder | Contents |
|---|---|
| [`infrastructure/`](infrastructure/README.md) | Terraform for the AWS resources (S3, CloudFront, Cognito, Lambda) |
| [`scripts/`](scripts/README.md) | Deploy, data-sync, and local-preview tooling |
| [`site/`](site/README.md) | The Three.js frontend, upload form, and admin editor |
| [`example/`](example/README.md) | Committed sample data (CSV + photos) used for local preview |
| `photos/` | Your real artwork data -- gitignored, not part of this repo |

## Getting started

Local preview, no AWS and no login required:

```
python scripts/build_local_preview.py
cd site && python -m http.server 8000
```

Open http://localhost:8000 -- placeholder art, the gallery, controls, and
info panel all work.

To deploy your own copy, start with
[`infrastructure/README.md`](infrastructure/README.md).

## Privacy

This repo is a template. No real domain, AWS account, bucket name, Cognito
identifier, or personal name is committed anywhere in it.

- Deployment-specific values (domain, S3 bucket, AWS CLI profile, Cognito
  domain prefix) live in a local `.env` file, which is gitignored --
  `env.example` shows the shape. `infrastructure/variables.tf` has no
  default for any of them, so a deploy fails before creating anything if
  `.env` isn't filled in.
- Real artwork data (`photos/artwork.csv`, `photos/<id>.<ext>`) is
  gitignored. [`example/`](example/README.md) is committed instead, with
  invented content in the same shape.
- `site/manifest.json`, `site/sample-photos/`, and `build/` are generated
  locally by the scripts in `scripts/` and are also gitignored.
