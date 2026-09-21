# A secret only known to CloudFront and this Lambda, so the function URL
# can't usefully be invoked by anyone who finds it directly.
resource "random_password" "origin_verify" {
  length  = 32
  special = false
}

# Zips what scripts/build_lambdas.py assembled -- handler plus its installed
# dependencies. Run that script before apply.
data "archive_file" "auth_callback" {
  type        = "zip"
  source_dir  = "${path.module}/build/auth-callback"
  output_path = "${path.module}/dist/auth-callback.zip"
}

resource "aws_iam_role" "auth_callback" {
  name = "${var.project_tag}-auth-callback"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "auth_callback_logs" {
  role       = aws_iam_role.auth_callback.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "auth_callback_ssm" {
  name = "${var.project_tag}-auth-callback-ssm"
  role = aws_iam_role.auth_callback.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "ssm:GetParameter"
      Resource = [
        aws_ssm_parameter.cookie_signing_private_key.arn,
        aws_ssm_parameter.cognito_client_secret.arn,
      ]
    }]
  })
}

resource "aws_lambda_function" "auth_callback" {
  function_name    = "${var.project_tag}-auth-callback"
  role             = aws_iam_role.auth_callback.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  timeout          = 10
  filename         = data.archive_file.auth_callback.output_path
  source_code_hash = data.archive_file.auth_callback.output_base64sha256

  environment {
    variables = {
      COGNITO_DOMAIN          = "https://${aws_cognito_user_pool_domain.gallery.domain}.auth.${var.aws_region}.amazoncognito.com"
      COGNITO_CLIENT_ID       = aws_cognito_user_pool_client.gallery.id
      COGNITO_USER_POOL_ID    = aws_cognito_user_pool.gallery.id
      REDIRECT_URI            = "https://${var.domain_name}/auth/callback"
      LOGOUT_REDIRECT_URI     = "https://${var.domain_name}/login.html"
      COOKIE_DOMAIN           = var.domain_name
      COOKIE_RESOURCE         = "https://${var.domain_name}/photos/*"
      CLOUDFRONT_KEY_PAIR_ID  = aws_cloudfront_public_key.cookie_signing.id
      SSM_PRIVATE_KEY_PARAM   = aws_ssm_parameter.cookie_signing_private_key.name
      SSM_CLIENT_SECRET_PARAM = aws_ssm_parameter.cognito_client_secret.name
      ORIGIN_VERIFY_SECRET    = random_password.origin_verify.result
    }
  }

  tags = { Project = var.project_tag }
}

resource "aws_lambda_function_url" "auth_callback" {
  function_name      = aws_lambda_function.auth_callback.function_name
  authorization_type = "NONE" # gated instead by the X-Origin-Verify header check inside the function
}

# ---------------------------------------------------------------------------
# pieces-api -- upload + edit endpoints behind /api/*. Same
# CloudFront-only-caller pattern as auth-callback (X-Origin-Verify), but
# each route additionally checks the caller's Cognito group from the
# id_token cookie auth-callback sets on login.
# ---------------------------------------------------------------------------

data "archive_file" "pieces_api" {
  type        = "zip"
  source_dir  = "${path.module}/build/pieces-api"
  output_path = "${path.module}/dist/pieces-api.zip"
}

resource "aws_iam_role" "pieces_api" {
  name = "${var.project_tag}-pieces-api"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "pieces_api_logs" {
  role       = aws_iam_role.pieces_api.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Everything this function needs to touch -- the manifest and the
# thumb/full/orig objects it presigns uploads for -- lives under photos/.
resource "aws_iam_role_policy" "pieces_api_s3" {
  name = "${var.project_tag}-pieces-api-s3"
  role = aws_iam_role.pieces_api.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject"]
      Resource = "${aws_s3_bucket.gallery.arn}/photos/*"
    }]
  })
}

resource "aws_lambda_function" "pieces_api" {
  function_name    = "${var.project_tag}-pieces-api"
  role             = aws_iam_role.pieces_api.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  timeout          = 10
  filename         = data.archive_file.pieces_api.output_path
  source_code_hash = data.archive_file.pieces_api.output_base64sha256

  environment {
    variables = {
      BUCKET_NAME          = aws_s3_bucket.gallery.bucket
      COGNITO_USER_POOL_ID = aws_cognito_user_pool.gallery.id
      COGNITO_CLIENT_ID    = aws_cognito_user_pool_client.gallery.id
      ORIGIN_VERIFY_SECRET = random_password.origin_verify.result
    }
  }

  tags = { Project = var.project_tag }
}

resource "aws_lambda_function_url" "pieces_api" {
  function_name      = aws_lambda_function.pieces_api.function_name
  authorization_type = "NONE" # gated instead by the X-Origin-Verify header check inside the function
}
