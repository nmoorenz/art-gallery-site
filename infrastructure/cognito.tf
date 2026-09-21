resource "aws_cognito_user_pool" "gallery" {
  name = "${var.project_tag}-users"

  # The gallery owner creates every account by hand (Cognito console or `aws cognito-idp
  # admin-create-user`) -- there is no public sign-up page.
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  username_attributes     = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length    = 8
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = false
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true
  }

  tags = { Project = var.project_tag }
}

resource "aws_cognito_user_pool_client" "gallery" {
  name         = "${var.project_tag}-client"
  user_pool_id = aws_cognito_user_pool.gallery.id

  generate_secret = true

  allowed_oauth_flows                 = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["openid", "email"]
  supported_identity_providers         = ["COGNITO"]

  callback_urls = ["https://${var.domain_name}/auth/callback"]
  logout_urls   = ["https://${var.domain_name}/login.html"]

  explicit_auth_flows = ["ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_SRP_AUTH"]

  # ID token lifetime -- how long a login lasts before Cognito's own session
  # expires and the family member has to log in again via the hosted UI.
  id_token_validity      = 12
  access_token_validity  = 12
  refresh_token_validity = 30
  token_validity_units {
    id_token      = "hours"
    access_token  = "hours"
    refresh_token = "days"
  }
}

resource "aws_cognito_user_pool_domain" "gallery" {
  domain       = var.cognito_domain_prefix
  user_pool_id = aws_cognito_user_pool.gallery.id
}

# Permission model: superadmin (the gallery owner) controls everything;
# admin (the artist and a couple of other family members) can upload/edit
# their own pieces; anyone logged in but in neither group is a plain viewer.
# Membership is managed by hand in the Cognito console (the gallery owner's
# choice) -- these resources just declare the two groups
# so they exist to add people to, and so pieces-api can check
# `cognito:groups` on the ID token.
resource "aws_cognito_user_group" "superadmin" {
  name         = "superadmin"
  user_pool_id = aws_cognito_user_pool.gallery.id
  description  = "Full control -- can edit category/era on any existing piece."
  precedence   = 1
}

resource "aws_cognito_user_group" "admin" {
  name         = "admin"
  user_pool_id = aws_cognito_user_pool.gallery.id
  description  = "Can upload new pieces via the web form."
  precedence   = 2
}
