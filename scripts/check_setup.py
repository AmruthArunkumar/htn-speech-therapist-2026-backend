#!/usr/bin/env python3
"""Preflight: check every dependency the pipeline needs before you record.

    python scripts/check_setup.py

Checks Mongo, S3 credentials and bucket access, and that the API keys are set.
Nothing here costs an ElevenLabs or Gemini call.
"""

import asyncio
import sys
import uuid

OK, BAD, WARN = "  ok  ", " FAIL ", " warn "


def line(status: str, label: str, detail: str = "") -> None:
    print(f"[{status}] {label}" + (f" - {detail}" if detail else ""))


async def check_mongo(settings) -> bool:
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(settings.mongodb_url, serverSelectionTimeoutMS=2500)
    try:
        await client.admin.command("ping")
    except Exception as exc:  # noqa: BLE001
        line(BAD, "MongoDB", f"{settings.mongodb_url} unreachable ({type(exc).__name__})")
        print("         start one with:")
        print("         docker run -d -p 27017:27017 --name htn-mongo mongo:7")
        return False
    else:
        line(OK, "MongoDB", settings.mongodb_url)
        return True
    finally:
        client.close()


def check_s3(settings) -> bool:
    if not settings.s3_bucket:
        line(WARN, "S3", "S3_BUCKET empty - uploads will be skipped, audio=null")
        return True

    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError

    client = boto3.client(
        "s3",
        region_name=settings.s3_region,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
    )

    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except NoCredentialsError:
        line(BAD, "S3 credentials", "none found - set AWS_ACCESS_KEY_ID/SECRET in .env")
        return False
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        hint = {
            "404": "bucket does not exist in this account",
            "403": "credentials are valid but lack access to this bucket",
            "301": f"bucket is in a different region than S3_REGION={settings.s3_region}",
        }.get(code, code)
        line(BAD, "S3 bucket", f"{settings.s3_bucket}: {hint}")
        return False
    line(OK, "S3 bucket", f"{settings.s3_bucket} ({settings.s3_region})")

    # Write permission is the one that actually matters at request time.
    key = f"{settings.s3_key_prefix.strip('/')}/_preflight/{uuid.uuid4().hex}.txt"
    try:
        client.put_object(Bucket=settings.s3_bucket, Key=key, Body=b"preflight")
    except ClientError as exc:
        line(BAD, "S3 write", f"s3:PutObject denied ({exc.response['Error']['Code']})")
        return False
    line(OK, "S3 write", key)

    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=settings.s3_url_expiry_s,
    )
    line(OK, "S3 presign", url[:72] + "...")

    try:
        client.delete_object(Bucket=settings.s3_bucket, Key=key)
        line(OK, "S3 cleanup", "preflight object removed")
    except ClientError:
        line(WARN, "S3 cleanup", f"could not delete {key} - harmless, delete by hand")
    return True


def check_keys(settings) -> bool:
    ok = True
    for label, value in (
        ("ElevenLabs key", settings.elevenlabs_api_key),
        ("Gemini key", settings.gemini_api_key),
    ):
        if value:
            line(OK, label, f"set ({len(value)} chars)")
        else:
            line(BAD, label, "missing")
            ok = False
    if settings.jwt_secret_key.startswith("local-development"):
        line(WARN, "JWT secret", "still the placeholder - fine locally, not in deploy")
    return ok


def main() -> int:
    from database.config import get_settings

    settings = get_settings()
    results = [
        asyncio.run(check_mongo(settings)),
        check_s3(settings),
        check_keys(settings),
    ]
    print()
    if all(results):
        print("All checks passed. Start the server:")
        print("  uvicorn main:app --reload")
        return 0
    print("Fix the FAIL lines above, then re-run.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
