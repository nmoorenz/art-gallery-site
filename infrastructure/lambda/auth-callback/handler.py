"""Cognito OAuth2 callback.

Flow: CloudFront serves login.html (public) when a viewer has no valid signed
cookies for /photos/*. login.html sends the browser to Cognito's Hosted UI.
Cognito redirects back here with ?code=... . This function:

  1. exchanges the code for tokens at Cognito's /oauth2/token endpoint
  2. verifies the returned ID token really came from our user pool
  3. issues CloudFront signed cookies scoped to /photos/*
  4. sets an id_token cookie scoped to /api/*, which pieces-api verifies
  5. redirects the browser back into the gallery

Reached via the CloudFront behaviour for /auth/* whose origin is this
function's Lambda Function URL -- see infrastructure/cloudfront.tf.

Keep this file ASCII-only.
"""

import base64
import json
import logging
import os
import time
import urllib.parse
import urllib.request

import boto3
import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

log = logging.getLogger()
log.setLevel(logging.INFO)

ssm = boto3.client("ssm")

COGNITO_DOMAIN = os.environ["COGNITO_DOMAIN"].rstrip("/")
CLIENT_ID = os.environ["COGNITO_CLIENT_ID"]
USER_POOL_ID = os.environ["COGNITO_USER_POOL_ID"]
REGION = USER_POOL_ID.split("_")[0]
ISSUER = "https://cognito-idp.%s.amazonaws.com/%s" % (REGION, USER_POOL_ID)
JWKS_URL = ISSUER + "/.well-known/jwks.json"

SESSION_SECONDS = 12 * 60 * 60

_secrets = None
_jwk_client = None


def get_secrets():
    global _secrets
    if _secrets is None:
        _secrets = {
            "private_key": ssm.get_parameter(
                Name=os.environ["SSM_PRIVATE_KEY_PARAM"], WithDecryption=True
            )["Parameter"]["Value"],
            "client_secret": ssm.get_parameter(
                Name=os.environ["SSM_CLIENT_SECRET_PARAM"], WithDecryption=True
            )["Parameter"]["Value"],
        }
    return _secrets


def get_jwk_client():
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = jwt.PyJWKClient(JWKS_URL, cache_keys=True)
    return _jwk_client


def verify_id_token(token):
    """Raises if the signature, issuer, audience or expiry do not check out."""
    key = get_jwk_client().get_signing_key_from_jwt(token).key
    return jwt.decode(
        token,
        key,
        algorithms=["RS256"],
        audience=CLIENT_ID,
        issuer=ISSUER,
        options={"require": ["exp", "iss", "aud"]},
    )


# ---------------------------------------------------------------------------
# CloudFront signed cookies
# ---------------------------------------------------------------------------

CF_TRANSLATION = str.maketrans("+=/", "-_~")


def cf_b64(raw):
    """base64 in CloudFront's URL-safe alphabet."""
    return base64.b64encode(raw).decode("ascii").translate(CF_TRANSLATION)


def signed_cookies(private_key_pem, key_pair_id, resource, expires_at):
    policy = json.dumps(
        {
            "Statement": [
                {
                    "Resource": resource,
                    "Condition": {"DateLessThan": {"AWS:EpochTime": expires_at}},
                }
            ]
        },
        separators=(",", ":"),
    ).encode("utf-8")

    key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    signature = key.sign(policy, padding.PKCS1v15(), hashes.SHA1())

    return {
        "CloudFront-Policy": cf_b64(policy),
        "CloudFront-Signature": cf_b64(signature),
        "CloudFront-Key-Pair-Id": key_pair_id,
    }


# ---------------------------------------------------------------------------
# responses
# ---------------------------------------------------------------------------


def cookie_attrs(max_age=None, path="/"):
    base = "Domain=%s; Path=%s; Secure; HttpOnly; SameSite=Lax" % (
        os.environ["COOKIE_DOMAIN"],
        path,
    )
    return base if max_age is None else "%s; Max-Age=%d" % (base, max_age)


def redirect(location, cookies=None):
    response = {"statusCode": 302, "headers": {"Location": location}, "body": ""}
    if cookies:
        response["cookies"] = cookies
    return response


def exchange_code(code, client_secret):
    basic = base64.b64encode(("%s:%s" % (CLIENT_ID, client_secret)).encode("utf-8")).decode("ascii")
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "redirect_uri": os.environ["REDIRECT_URI"],
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        COGNITO_DOMAIN + "/oauth2/token",
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": "Basic " + basic,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.loads(response.read())


def handler(event, _context):
    # Only CloudFront should ever be able to invoke this function.
    if (event.get("headers") or {}).get("x-origin-verify") != os.environ["ORIGIN_VERIFY_SECRET"]:
        return {"statusCode": 403, "body": "Forbidden"}

    path = event.get("rawPath") or "/"
    query = urllib.parse.parse_qs(event.get("rawQueryString") or "")

    if path.endswith("/logout"):
        logout_url = COGNITO_DOMAIN + "/logout?" + urllib.parse.urlencode(
            {"client_id": CLIENT_ID, "logout_uri": os.environ["LOGOUT_REDIRECT_URI"]}
        )
        return redirect(
            logout_url,
            [
                "CloudFront-Policy=deleted; " + cookie_attrs(0),
                "CloudFront-Signature=deleted; " + cookie_attrs(0),
                "CloudFront-Key-Pair-Id=deleted; " + cookie_attrs(0),
                "id_token=deleted; " + cookie_attrs(0, "/api"),
            ],
        )

    code = (query.get("code") or [None])[0]
    if not code:
        return {
            "statusCode": 400,
            "body": "Missing ?code= -- this endpoint is only meant to be hit by Cognito's redirect.",
        }

    try:
        secrets = get_secrets()
        tokens = exchange_code(code, secrets["client_secret"])
        id_token = tokens["id_token"]
        verify_id_token(id_token)

        expires_at = int(time.time()) + SESSION_SECONDS
        cookies = [
            "%s=%s; %s" % (name, value, cookie_attrs())
            for name, value in signed_cookies(
                secrets["private_key"],
                os.environ["CLOUDFRONT_KEY_PAIR_ID"],
                os.environ["COOKIE_RESOURCE"],
                expires_at,
            ).items()
        ]
        cookies.append("id_token=%s; %s" % (id_token, cookie_attrs(SESSION_SECONDS, "/api")))
        return redirect("/", cookies)
    except Exception:
        log.exception("auth callback failed")
        return redirect("/login.html")
