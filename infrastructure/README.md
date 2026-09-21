# Infrastructure

Terraform that provisions:

- An S3 bucket holding the static site (`site/` prefix) and the private
  photos + datastore (`photos/` prefix)
- A CloudFront distribution serving the site (public), the photos (behind
  CloudFront signed cookies), the login callback (`/auth/*`), and the
  upload/edit API (`/api/*`) from that one bucket
- An ACM certificate for the custom domain
- A Cognito User Pool + Hosted UI, with `superadmin` and `admin` groups --
  anyone authenticated but in neither group is a plain viewer
- Two Lambda functions: `auth-callback` (OAuth callback, issues signed
  cookies) and `pieces-api` (presigned uploads, category/era edits)
- The IAM roles and SSM parameters those Lambdas need

All commands below assume the repo root as the working directory.

## Required configuration

Copy `env.example` (repo root) to `.env` and fill in:

| `.env` key | Terraform variable | Notes |
|---|---|---|
| `S3_BUCKET` | `bucket_name` | Must be globally unique |
| `DOMAIN_NAME` | `domain_name` | Custom domain the gallery is served on |
| `AWS_PROFILE` | `aws_profile` | AWS CLI profile to deploy with |
| `COGNITO_DOMAIN_PREFIX` | `cognito_domain_prefix` | Must be globally unique |
| `AWS_REGION` | `aws_region` | Optional -- `variables.tf` sets the default |

None of those four required variables has a default in `variables.tf`, so
`terraform plan`/`apply` fails immediately if any are missing rather than
creating a partial deployment. `aws_region` and `project_tag` default in
`variables.tf`.

`aws_region` defaults to `ap-southeast-2`. The region must support Lambda
function URLs. `ap-southeast-6` does not.

There is no `terraform.tfvars`, and `tf.py` will not run while one exists.
Set values in `.env`, or change a default in `variables.tf`.

`tf.py` builds any missing Lambda bundle before calling terraform.

Every Terraform command goes through `scripts/tf.py`, which loads `.env`,
maps those values to `TF_VAR_*`, and adds `-chdir=infrastructure`:

```
python scripts/tf.py <any terraform subcommand and args>
```

## First-time deploy

1. `python scripts/tf.py init`

2. The ACM certificate needs a DNS record added by hand before it
   validates, so the first apply is two steps:
   ```
   python scripts/tf.py cert
   ```
   `cert` applies the certificate alone and prints its validation record.
   Add that CNAME at your DNS registrar (name -> value), wait for it to
   resolve, then:
   ```
   python scripts/tf.py apply
   ```
   This finishes validating the cert and creates everything else.

   `python scripts/build_lambdas.py` runs on its own whenever a bundle is
   missing; run it by hand after changing a handler or a
   `requirements.txt`, since an existing bundle is left alone.

3. Point the domain at CloudFront:
   ```
   python scripts/tf.py output cloudfront_domain_name
   ```
   Add a CNAME (or ALIAS/ANAME, for a bare domain) for `DOMAIN_NAME` to
   that value. Propagation after a change can take 5-15 minutes.

4. Deploy the frontend -- see
   [`scripts/README.md`](../scripts/README.md#deploy_sitepy).

5. Create a Cognito user per person, then add them to a group:
   ```
   set -a; source .env; set +a

   aws cognito-idp admin-create-user \
     --user-pool-id "$(python scripts/tf.py output -raw cognito_user_pool_id)" \
     --username someone@example.com \
     --user-attributes Name=email,Value=someone@example.com Name=email_verified,Value=true \
     --profile "$AWS_PROFILE"

   aws cognito-idp admin-add-user-to-group \
     --user-pool-id "$(python scripts/tf.py output -raw cognito_user_pool_id)" \
     --username someone@example.com --group-name admin \
     --profile "$AWS_PROFILE"
   ```
   Use `--group-name superadmin` for full control, `admin` to allow
   uploading, or skip the group entirely for a plain viewer. The Cognito
   console works the same way if you'd rather click through it than run
   commands. Cognito emails a temporary password; the person sets a real
   one on first login via the Hosted UI. Group membership takes effect on
   the next login (it's baked into the ID token).

6. Visit `https://<DOMAIN_NAME>` -- you should land on the login page, and
   in the gallery (empty, until art is added) after logging in.

## Removing a person's access

```
set -a; source .env; set +a

aws cognito-idp admin-delete-user \
  --user-pool-id "$(python scripts/tf.py output -raw cognito_user_pool_id)" \
  --username someone@example.com --profile "$AWS_PROFILE"
```

No code or Terraform changes needed.

## Outputs reference

`python scripts/tf.py output` lists all of these:

- `site_domain`, `cloudfront_distribution_id`, `cloudfront_domain_name`
- `acm_validation_records`
- `cognito_hosted_ui_domain`, `cognito_client_id`, `cognito_user_pool_id`
- `bucket_name`

## Troubleshooting

- **Stuck on an S3 error page instead of the gallery/login page**: the
  `/photos/*` 403 -> `/login.html` custom error response only fires for
  403s. If S3 returns something else (404, etc.), check the object
  actually exists at that key.
- **Logged in but bounced back to login.html**: check the `auth-callback`
  Lambda's CloudWatch logs (`/aws/lambda/art-gallery-site-auth-callback`)
  -- it logs why (token exchange failure, ID token verification failure,
  etc.).
- **Upload/edit fails with a login or permission message**: check the
  `pieces-api` Lambda's CloudWatch logs
  (`/aws/lambda/art-gallery-site-pieces-api`) for the reason (expired
  token, wrong group, etc.).
- **Upload fails with a CORS error in the browser console**: the photo
  PUTs go straight from the browser to S3 using presigned URLs, so the
  bucket's CORS configuration (`aws_s3_bucket_cors_configuration.gallery`
  in `s3.tf`) has to allow the site's own origin -- check it matches
  `domain_name`.
- **`terraform apply` complains about a managed cache/origin-request
  policy ID**: those UUIDs (CachingOptimized, CachingDisabled, AllViewerExceptHostHeader)
  are AWS-managed policies -- `aws cloudfront list-cache-policies --type
  managed` shows the current ones if AWS ever changes them, and they can
  be updated in `cloudfront.tf`.
