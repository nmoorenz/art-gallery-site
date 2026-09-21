# DNS is managed by hand at the registrar, not by Terraform/Route53 -- so
# this only creates + validates the cert; you add the validation CNAME (and
# later the domain's own CNAME/ALIAS) yourself. See infrastructure/README.md
# for the two-step apply this requires.
resource "aws_acm_certificate" "gallery" {
  provider          = aws.us_east_1
  domain_name       = var.domain_name
  validation_method = "DNS"
  tags              = { Project = var.project_tag }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate_validation" "gallery" {
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.gallery.arn
  validation_record_fqdns = [for r in aws_acm_certificate.gallery.domain_validation_options : r.resource_record_name]
}
