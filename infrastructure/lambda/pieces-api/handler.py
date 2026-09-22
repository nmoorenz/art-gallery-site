"""Upload + edit API for the art gallery.

Reached via the CloudFront behaviour for /api/* whose origin is this
function's Lambda Function URL -- see infrastructure/cloudfront.tf.
CloudFront is the only permitted caller (X-Origin-Verify shared secret).
On top of that, every route verifies the `id_token` cookie that auth-callback
sets at login: the signature is always re-checked here, the cookie's contents
are never trusted as they arrive. `cognito:groups` on the verified token
decides admin vs superadmin vs viewer.

The gallery's datastore is one JSON file, photos/manifest.json -- the same
file the frontend fetches. Writes are a read-modify-write guarded by S3
conditional PutObject (If-Match on the current ETag), with retries if two
edits race.

Routes:
    POST  /api/upload-url          {"filename": "..."}  -> presigned PUTs
    POST  /api/pieces              {"id": ..., "name": ..., ...}
    PATCH /api/pieces/{id}         {"category": ..., "era": ...}

Keep this file ASCII-only.
"""

import json
import logging
import os
import re
import urllib.parse
import uuid
from datetime import datetime, timezone

import boto3
import jwt
from botocore.exceptions import ClientError

log = logging.getLogger()
log.setLevel(logging.INFO)

s3 = boto3.client("s3")

BUCKET = os.environ["BUCKET_NAME"]
CLIENT_ID = os.environ["COGNITO_CLIENT_ID"]
USER_POOL_ID = os.environ["COGNITO_USER_POOL_ID"]
REGION = USER_POOL_ID.split("_")[0]
ISSUER = "https://cognito-idp.%s.amazonaws.com/%s" % (REGION, USER_POOL_ID)
JWKS_URL = ISSUER + "/.well-known/jwks.json"

MANIFEST_KEY = "photos/manifest.json"
UPLOAD_URL_EXPIRY_SECONDS = 300
ID_PATTERN = re.compile(r"^[a-z0-9-]{8,64}$", re.I)
FILENAME_UNSAFE = re.compile(r"[^a-zA-Z0-9._-]")
DEFAULT_ASPECT = 1.3

_jwk_client = None


def get_jwk_client():
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = jwt.PyJWKClient(JWKS_URL, cache_keys=True)
    return _jwk_client


def json_response(status, payload):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(payload),
    }


def read_cookie(event, name):
    for cookie in event.get("cookies") or []:
        key, _, value = cookie.partition("=")
        if key.strip() == name:
            return value.strip()
    return None


def get_claims(event):
    token = read_cookie(event, "id_token")
    if not token:
        return None
    try:
        key = get_jwk_client().get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=CLIENT_ID,
            issuer=ISSUER,
            options={"require": ["exp", "iss", "aud"]},
        )
    except Exception as err:
        log.warning("id_token verification failed: %s", err)
        return None


def groups_of(claims):
    groups = claims.get("cognito:groups") or []
    return groups if isinstance(groups, list) else []


def is_admin_or_above(claims):
    return bool({"admin", "superadmin"} & set(groups_of(claims)))


def is_superadmin(claims):
    return "superadmin" in groups_of(claims)


def display_name(claims):
    return claims.get("email") or claims.get("cognito:username") or "unknown"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_body(event):
    """Returns (body, error_response)."""
    try:
        return json.loads(event.get("body") or "{}"), None
    except ValueError:
        return None, json_response(400, {"error": "Invalid JSON body."})


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------


def read_manifest():
    got = s3.get_object(Bucket=BUCKET, Key=MANIFEST_KEY)
    return json.loads(got["Body"].read()), got["ETag"]


def update_manifest(mutate):
    """Read, mutate, write back only if nobody else wrote in between.

    `mutate` may return a value, which is passed back to the caller.
    """
    for attempt in range(5):
        manifest, etag = read_manifest()
        result = mutate(manifest)
        manifest["generated"] = now_iso()

        try:
            s3.put_object(
                Bucket=BUCKET,
                Key=MANIFEST_KEY,
                Body=json.dumps(manifest).encode("utf-8"),
                ContentType="application/json",
                CacheControl="no-cache",
                IfMatch=etag,
            )
            return result
        except ClientError as err:
            code = err.response["Error"]["Code"]
            status = err.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if (code == "PreconditionFailed" or status == 412) and attempt < 4:
                continue
            raise
    raise RuntimeError("manifest update: too many conflicting writes, gave up")


def sort_pieces(pieces):
    pieces.sort(key=lambda piece: (piece.get("category") or "", piece.get("date") or ""))


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


def handle_upload_url(event, claims):
    if not is_admin_or_above(claims):
        return json_response(403, {"error": "Not allowed to upload."})

    body, error = parse_body(event)
    if error:
        return error

    filename = FILENAME_UNSAFE.sub("_", str(body.get("filename") or "photo.jpg"))
    piece_id = str(uuid.uuid4())

    def presign(key, content_type=None):
        params = {"Bucket": BUCKET, "Key": key}
        if content_type:
            params["ContentType"] = content_type
        return s3.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=UPLOAD_URL_EXPIRY_SECONDS
        )

    return json_response(
        200,
        {
            "id": piece_id,
            "uploadUrls": {
                "orig": presign("photos/%s/orig/%s" % (piece_id, filename)),
                "full": presign("photos/%s/full.jpg" % piece_id, "image/jpeg"),
                "thumb": presign("photos/%s/thumb.jpg" % piece_id, "image/jpeg"),
            },
        },
    )


def handle_create_piece(event, claims):
    if not is_admin_or_above(claims):
        return json_response(403, {"error": "Not allowed to upload."})

    body, error = parse_body(event)
    if error:
        return error

    piece_id = str(body.get("id") or "")
    name = str(body.get("name") or "").strip()
    if not ID_PATTERN.match(piece_id):
        return json_response(400, {"error": "Missing or invalid id -- call /api/upload-url first."})
    if not name:
        return json_response(400, {"error": "Missing name."})

    try:
        aspect = float(body.get("aspect"))
    except (TypeError, ValueError):
        aspect = DEFAULT_ASPECT
    if aspect <= 0:
        aspect = DEFAULT_ASPECT

    piece = {
        "id": piece_id,
        "name": name,
        "description": str(body.get("description") or "").strip(),
        "date": str(body.get("date") or "").strip(),
        "category": str(body.get("category") or "").strip() or "Uncategorised",
        "era": str(body.get("era") or "").strip(),
        "medium": str(body.get("medium") or "").strip(),
        # A piece uploaded through the web form is always a single image --
        # grouping multiple images into one piece is CSV/admin only for now
        # (see scripts/sync_gallery.py) -- but it still gets the same
        # images[] shape every other piece uses, so the frontend never has
        # to special-case where a piece came from.
        "images": [{
            "id": piece_id,
            "label": "",
            "thumb": "/photos/%s/thumb.jpg" % piece_id,
            "full": "/photos/%s/full.jpg" % piece_id,
            "aspect": aspect,
        }],
        "uploadedBy": display_name(claims),
        "uploadedAt": now_iso(),
    }

    def mutate(manifest):
        manifest.setdefault("pieces", []).append(piece)
        sort_pieces(manifest["pieces"])

    update_manifest(mutate)
    return json_response(201, {"piece": piece})


def handle_patch_piece(event, claims, piece_id):
    if not is_superadmin(claims):
        return json_response(403, {"error": "Only a superadmin can edit an existing piece."})

    body, error = parse_body(event)
    if error:
        return error

    patch = {}
    if isinstance(body.get("category"), str):
        patch["category"] = body["category"].strip() or "Uncategorised"
    if isinstance(body.get("era"), str):
        patch["era"] = body["era"].strip()
    if not patch:
        return json_response(400, {"error": "Nothing to update -- expected category and/or era."})

    state = {"piece": None}

    def mutate(manifest):
        piece = next((p for p in manifest.get("pieces", []) if p.get("id") == piece_id), None)
        if piece is None:
            return
        piece.update(patch)
        sort_pieces(manifest["pieces"])
        state["piece"] = piece

    update_manifest(mutate)

    if state["piece"] is None:
        return json_response(404, {"error": "No piece with that id."})
    return json_response(200, {"piece": state["piece"]})


def handler(event, _context):
    if (event.get("headers") or {}).get("x-origin-verify") != os.environ["ORIGIN_VERIFY_SECRET"]:
        return {"statusCode": 403, "body": "Forbidden"}

    method = ((event.get("requestContext") or {}).get("http") or {}).get("method", "GET")
    path = event.get("rawPath") or "/"
    claims = get_claims(event)

    if claims is None:
        return json_response(401, {"error": "Please log in again."})

    try:
        if method == "POST" and path == "/api/upload-url":
            return handle_upload_url(event, claims)

        if method == "POST" and path == "/api/pieces":
            return handle_create_piece(event, claims)

        match = re.match(r"^/api/pieces/([^/]+)$", path)
        if method == "PATCH" and match:
            return handle_patch_piece(event, claims, urllib.parse.unquote(match.group(1)))

        return json_response(404, {"error": "Not found."})
    except Exception:
        log.exception("pieces-api error")
        return json_response(500, {"error": "Something went wrong -- try again."})
