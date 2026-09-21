output "site_domain" {
  value = var.domain_name
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.gallery.id
}

output "cloudfront_domain_name" {
  description = "Point domain_name's DNS (CNAME/ALIAS) at this."
  value       = aws_cloudfront_distribution.gallery.domain_name
}

output "acm_validation_records" {
  description = "Add these as CNAME records at your registrar before the first apply will finish -- see README."
  value = [for r in aws_acm_certificate.gallery.domain_validation_options : {
    name  = r.resource_record_name
    type  = r.resource_record_type
    value = r.resource_record_value
  }]
}

output "cognito_hosted_ui_domain" {
  value = "https://${aws_cognito_user_pool_domain.gallery.domain}.auth.${var.aws_region}.amazoncognito.com"
}

output "cognito_client_id" {
  value = aws_cognito_user_pool_client.gallery.id
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.gallery.id
}

output "bucket_name" {
  value = aws_s3_bucket.gallery.bucket
}
