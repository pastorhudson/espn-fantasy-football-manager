"""Bounded public GET requests with a shared database cache."""

import time
from datetime import timedelta

import httpx
from django.utils import timezone

from decisions.models import SourceCache


class SourceError(Exception):
    """Only fixed, safe messages; no response bodies or request secrets."""


def fetch_json(url):
    with httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False) as client:
        for attempt in range(3):
            try:
                response = client.get(url)
            except httpx.TransportError:
                if attempt == 2:
                    raise SourceError("Public source could not be reached.") from None
            else:
                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError:
                        raise SourceError("Public source returned invalid JSON.") from None
                if response.status_code != 429 and response.status_code < 500:
                    raise SourceError("Public source rejected the request.")
                if attempt == 2:
                    raise SourceError("Public source temporarily unavailable.")
            time.sleep(2**attempt)
    raise SourceError("Public source unavailable.")


def cached_feed(key, url, minutes, parse, fetch=None):
    now = timezone.now()
    fetch = fetch or fetch_json
    cached = SourceCache.objects.filter(key=key).first()
    if cached and now - timedelta(minutes=minutes) <= cached.fetched_at <= now:
        return cached.data, cached.fetched_at
    # Parse before replacing the cache. An expired cache is never used on failure.
    try:
        data = parse(fetch(url))
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise SourceError("Public source returned an unsupported payload.") from None
    fetched_at = timezone.now()
    SourceCache.objects.update_or_create(
        key=key, defaults={"data": data, "fetched_at": fetched_at}
    )
    return data, fetched_at


def fetch_csv(url):
    """Fetch a bounded UTF-8 CSV without retaining response metadata or bodies."""
    with httpx.Client(timeout=httpx.Timeout(30, connect=5), follow_redirects=False) as client:
        for attempt in range(3):
            try:
                response = client.get(url)
            except httpx.TransportError:
                if attempt == 2:
                    raise SourceError("Public source could not be reached.") from None
            else:
                if response.status_code == 200:
                    content = response.content
                    if len(content) > 5_000_000:
                        raise SourceError("Public source returned an unsupported payload.")
                    try:
                        return content.decode("utf-8")
                    except UnicodeDecodeError:
                        raise SourceError("Public source returned an unsupported payload.") from None
                if response.status_code != 429 and response.status_code < 500:
                    raise SourceError("Public source rejected the request.")
                if attempt == 2:
                    raise SourceError("Public source temporarily unavailable.")
            time.sleep(2**attempt)
    raise SourceError("Public source unavailable.")
