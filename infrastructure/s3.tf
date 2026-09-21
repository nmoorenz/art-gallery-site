resource "aws_s3_bucket" "gallery" {
  bucket = var.bucket_name
  tags   = { Project = var.project_tag }
}

resource "aws_s3_bucket_public_access_block" "gallery" {
  bucket                  = aws_s3_bucket.gallery.id
  block_public_acls       = true
  block_public_policy     = false # bucket policy below grants CloudFront (not the public) access
  ignore_public_acls      = true
  restrict_public_buckets = false
}

resource "aws_s3_bucket_versioning" "gallery" {
  bucket = aws_s3_bucket.gallery.id
  versioning_configuration {
    status = "Enabled" # cheap insurance against an accidental sync overwrite
  }
}

# The upload form PUTs photo files straight to S3 using presigned URLs from
# pieces-api, from the browser -- that's a cross-origin request as far as
# S3 is concerned (the site is served via CloudFront, not straight from the
# bucket), and a JPEG body triggers a CORS preflight. This is what lets that
# preflight succeed.
resource "aws_s3_bucket_cors_configuration" "gallery" {
  bucket = aws_s3_bucket.gallery.id
  cors_rule {
    allowed_methods = ["PUT"]
    allowed_origins = ["https://${var.domain_name}"]
    allowed_headers = ["*"]
    max_age_seconds = 3000
  }
}

resource "aws_cloudfront_origin_access_control" "gallery" {
  name                              = "${var.project_tag}-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Everything in the bucket -- both the "site/" and "photos/" prefixes -- is
# only readable through CloudFront (via OAC). "photos/*" is further
# restricted at the CloudFront behaviour level (signed cookies); this policy
# just keeps S3 itself from ever being reachable directly.
resource "aws_s3_bucket_policy" "gallery" {
  bucket = aws_s3_bucket.gallery.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFrontServicePrincipal"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.gallery.arn}/*"
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.gallery.arn
        }
      }
    }]
  })
}

# The gallery's actual datastore: a single JSON file, read-modify-written by
# pieces-api (see lambda.tf) every time a piece is added or edited, and read
# directly by the frontend (same as it always has been) via the /photos/*
# CloudFront behaviour. This resource only creates the file if it doesn't
# exist yet -- lifecycle.ignore_changes keeps `terraform apply` from ever
# stomping on real data with this empty starting point once pieces-api has
# started writing to it.
resource "aws_s3_object" "manifest_bootstrap" {
  bucket       = aws_s3_bucket.gallery.id
  key          = "photos/manifest.json"
  content      = jsonencode({
    generated = "1970-01-01T00:00:00Z"
    hallway   = { width = 6, wallHeight = 3.2, spacing = 2.4, margin = 2.2 }
    pieces    = []
  })
  content_type  = "application/json"
  cache_control = "no-cache"

  lifecycle {
    ignore_changes = [content, content_type, cache_control, etag]
  }
}
