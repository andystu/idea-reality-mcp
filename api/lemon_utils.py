"""LemonSqueezy payment utilities for Idea Reality paid reports.

Replaces Stripe integration. LemonSqueezy acts as Merchant of Record,
handling global tax compliance. No SDK needed — pure REST via httpx.

Env vars required:
  LEMONSQUEEZY_API_KEY    — API key from LemonSqueezy dashboard
  LEMONSQUEEZY_WEBHOOK_SECRET — Webhook signing secret (HMAC-SHA256)
  LEMONSQUEEZY_VARIANT_ID — Variant ID for the report product (default: 1374049)
  LEMONSQUEEZY_STORE_ID   — Store ID (default: 308439)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

LEMON_API = "https://api.lemonsqueezy.com/v1"


def _get_api_key() -> str | None:
    """Return LEMONSQUEEZY_API_KEY or None if not configured."""
    return (os.environ.get("LEMONSQUEEZY_API_KEY") or "").strip() or None


def _get_webhook_secret() -> str | None:
    """Return LEMONSQUEEZY_WEBHOOK_SECRET or None if not configured."""
    return (os.environ.get("LEMONSQUEEZY_WEBHOOK_SECRET") or "").strip() or None


def _get_variant_id() -> str:
    """Return variant ID (default product variant)."""
    return (os.environ.get("LEMONSQUEEZY_VARIANT_ID") or "").strip() or "1374049"


def _get_store_id() -> str:
    """Return store ID."""
    return (os.environ.get("LEMONSQUEEZY_STORE_ID") or "").strip() or "308439"


def _headers() -> dict:
    """Standard headers for LemonSqueezy API."""
    return {
        "Authorization": f"Bearer {_get_api_key()}",
        "Accept": "application/vnd.api+json",
        "Content-Type": "application/vnd.api+json",
    }


async def create_checkout(
    idea_text: str,
    idea_hash: str,
    language: str,
    success_url: str,
    depth: str = "quick",
) -> str:
    """Create a LemonSqueezy checkout session.

    Returns the checkout URL.
    Raises ValueError if LemonSqueezy is not configured.
    Raises httpx.HTTPError on API failures.
    """
    api_key = _get_api_key()
    if not api_key:
        raise ValueError("LemonSqueezy is not configured")

    variant_id = _get_variant_id()
    store_id = _get_store_id()

    payload = {
        "data": {
            "type": "checkouts",
            "attributes": {
                "custom_price": None,  # Use product price ($9.99)
                "product_options": {
                    "enabled_variants": [int(variant_id)],
                    "redirect_url": success_url,
                    "receipt_button_text": "View Your Report",
                    "receipt_link_url": success_url,
                },
                "checkout_options": {
                    "embed": False,
                    "media": False,
                    "desc": False,
                },
                "checkout_data": {
                    "custom": {
                        "idea_text": idea_text[:500],
                        "idea_hash": idea_hash,
                        "language": language,
                        "depth": depth,
                    },
                },
            },
            "relationships": {
                "store": {
                    "data": {
                        "type": "stores",
                        "id": store_id,
                    }
                },
                "variant": {
                    "data": {
                        "type": "variants",
                        "id": variant_id,
                    }
                },
            },
        }
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{LEMON_API}/checkouts",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    checkout_url = data["data"]["attributes"]["url"]
    logger.info("[LEMON] Checkout created: %s", checkout_url)
    return checkout_url


def verify_webhook(payload: bytes, signature: str) -> dict:
    """Verify LemonSqueezy webhook signature and parse the event.

    LemonSqueezy signs webhooks with HMAC-SHA256 using the webhook secret.
    The signature is in the X-Signature header.

    Returns the parsed event dict.
    Raises ValueError if webhook secret is not configured or signature is invalid.
    """
    secret = _get_webhook_secret()
    if not secret:
        raise ValueError("LemonSqueezy webhook secret is not configured")

    expected = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise ValueError("Invalid webhook signature")

    return json.loads(payload)


async def get_order(order_id: str) -> dict:
    """Retrieve a LemonSqueezy order by ID.

    Returns the order attributes dict.
    """
    api_key = _get_api_key()
    if not api_key:
        raise ValueError("LemonSqueezy is not configured")

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{LEMON_API}/orders/{order_id}",
            headers=_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

    return data["data"]["attributes"]
