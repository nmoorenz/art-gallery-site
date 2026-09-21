variable "aws_profile" {
  description = "AWS CLI profile to use. Required -- set via TF_VAR_aws_profile (scripts/tf.py does this from .env), no default so an incomplete config fails before anything is created."
  type        = string
}

variable "aws_region" {
  description = "Region for S3, Cognito and the Lambdas. Must support Lambda function URLs -- ap-southeast-6 does not."
  type        = string
  default     = "ap-southeast-2"
}

variable "bucket_name" {
  description = "S3 bucket holding both the static site and the private photos. Must be globally unique. Required -- set via TF_VAR_bucket_name (scripts/tf.py does this from .env), no default."
  type        = string
}

variable "domain_name" {
  description = "Custom domain the gallery is served on. Required -- set via TF_VAR_domain_name (scripts/tf.py does this from .env), no default."
  type        = string
}

variable "project_tag" {
  type    = string
  default = "art-gallery-site"
}

variable "cognito_domain_prefix" {
  description = "Prefix for the Cognito Hosted UI domain (<prefix>.auth.<region>.amazoncognito.com). Must be globally unique. Required -- set via TF_VAR_cognito_domain_prefix (scripts/tf.py does this from .env), no default."
  type        = string
}
