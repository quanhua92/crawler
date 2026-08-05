"""S3 write-through archive.

Every live request persists {hash}/input.json + {hash}/output.json to S3
(fire-and-forget, never blocks the response). The /archive/* routes read from
S3 only — like Google Cache for when the source goes down.

The hash is deterministic per (platform, kind, identifier), so the live route
and the archive route derive the same key from the same params.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from app.config import settings
from app.models import CrawlResponse

logger = logging.getLogger("crawler.storage")

_s3_client = None


def get_s3():
    global _s3_client
    if _s3_client is None and settings.s3_endpoint:
        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=BotoConfig(signature_version="s3v4", retries={"max_attempts": 2}),
        )
    return _s3_client


def archive_enabled() -> bool:
    return bool(settings.s3_endpoint)


def request_hash(platform: str, kind: str, identifier: str) -> str:
    """Deterministic SHA-256 for any crawl request.

    Both the live route and the archive route call this with the same args.
    Examples:
      ("x", "feed", "QwenDevs")
      ("x", "post", "2084102417885585597")
      ("url", "fetch", "https://nitter.net/QwenDevs/rss")
      ("substack", "feed", "lennysnewsletter")
    """
    key = f"{platform}:{kind}:{identifier}"
    return hashlib.sha256(key.encode()).hexdigest()


def ensure_bucket() -> None:
    """Create the S3 bucket if it doesn't exist. Call once at startup."""
    s3 = get_s3()
    if s3 is None:
        return
    try:
        s3.head_bucket(Bucket=settings.s3_bucket)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchBucket"):
            s3.create_bucket(Bucket=settings.s3_bucket)
            logger.info("created S3 bucket: %s", settings.s3_bucket)
        else:
            logger.warning("S3 bucket check failed: %s", e)


async def persist(
    platform: str, kind: str, identifier: str, params: dict, response: CrawlResponse
) -> None:
    """Write-through to S3, fire-and-forget. Never blocks, never raises.

    Writes three objects:
      {hash}/input.json              — latest request params (always overwritten)
      {hash}/versions/{ts}.json      — every fetch preserved (success or failure)
      {hash}/output.json             — latest GOOD response (only when status ok/partial,
                                        so a transient failure never clobbers a good archive)
    """
    if not archive_enabled():
        return
    h = request_hash(platform, kind, identifier)
    ts = time.time()
    input_data = json.dumps(
        {"platform": platform, "kind": kind, "identifier": identifier, "params": params,
         "hash": h, "timestamp": ts},
        default=str,
    )
    output_data = response.model_dump_json()
    is_good = response.status in ("ok", "partial")

    async def _write():
        def _put():
            s3 = get_s3()
            if s3 is None:
                return
            # Always: latest input params
            s3.put_object(Bucket=settings.s3_bucket, Key=f"{h}/input.json",
                          Body=input_data, ContentType="application/json")
            # Always: timestamped version (every fetch, including failures)
            s3.put_object(Bucket=settings.s3_bucket, Key=f"{h}/versions/{ts:.0f}.json",
                          Body=output_data, ContentType="application/json")
            # Only on success: update latest-good snapshot
            if is_good:
                s3.put_object(Bucket=settings.s3_bucket, Key=f"{h}/output.json",
                              Body=output_data, ContentType="application/json")

        await asyncio.to_thread(_put)

    try:
        asyncio.create_task(_write())
    except RuntimeError:
        pass  # No event loop — skip


async def get_archived(platform: str, kind: str, identifier: str) -> CrawlResponse | None:
    """Read the latest GOOD archived response from S3. Returns None if never archived."""
    if not archive_enabled():
        return None
    h = request_hash(platform, kind, identifier)

    def _get():
        s3 = get_s3()
        if s3 is None:
            return None
        try:
            resp = s3.get_object(Bucket=settings.s3_bucket, Key=f"{h}/output.json")
            return json.loads(resp["Body"].read())
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            logger.warning("S3 archive read failed: %s", e)
            return None

    data = await asyncio.to_thread(_get)
    return CrawlResponse(**data) if data else None


async def get_archived_versions(
    platform: str, kind: str, identifier: str
) -> list[str]:
    """List all archived version timestamps for a request (newest last)."""
    if not archive_enabled():
        return []
    h = request_hash(platform, kind, identifier)

    def _list():
        s3 = get_s3()
        if s3 is None:
            return []
        prefix = f"{h}/versions/"
        versions: list[str] = []
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                ts_name = obj["Key"][len(prefix):].removesuffix(".json")
                versions.append(ts_name)
        return sorted(versions)

    return await asyncio.to_thread(_list)


async def get_archived_version(
    platform: str, kind: str, identifier: str, ts: str
) -> CrawlResponse | None:
    """Read a specific timestamped version (point-in-time lookup)."""
    if not archive_enabled():
        return None
    h = request_hash(platform, kind, identifier)

    def _get():
        s3 = get_s3()
        if s3 is None:
            return None
        try:
            resp = s3.get_object(Bucket=settings.s3_bucket, Key=f"{h}/versions/{ts}.json")
            return json.loads(resp["Body"].read())
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            return None

    data = await asyncio.to_thread(_get)
    return CrawlResponse(**data) if data else None
