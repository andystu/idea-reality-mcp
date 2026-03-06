"""Stripe payment utilities for Idea Reality paid reports."""

from __future__ import annotations

import os

import stripe


def _get_stripe_key() -> str | None:
    """Return STRIPE_SECRET_KEY or None if not configured."""
    return (os.environ.get("STRIPE_SECRET_KEY") or "").strip() or None


def _get_webhook_secret() -> str | None:
    """Return STRIPE_WEBHOOK_SECRET or None if not configured."""
    return (os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip() or None


def create_checkout_session(
    idea_text: str,
    idea_hash: str,
    language: str,
    success_url: str,
    cancel_url: str,
) -> str:
    """Create a Stripe Checkout session for a paid report.

    Returns the checkout session URL.
    Raises ValueError if Stripe is not configured.
    Raises stripe.StripeError on API failures.
    """
    secret_key = _get_stripe_key()
    if not secret_key:
        raise ValueError("Stripe is not configured")

    stripe.api_key = secret_key

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "unit_amount": 999,
                    "product_data": {
                        "name": "Idea Reality Full Report",
                    },
                },
                "quantity": 1,
            }
        ],
        metadata={
            "idea_text": idea_text[:500],  # Stripe metadata value max 500 chars
            "idea_hash": idea_hash,
            "language": language,
        },
        customer_email_collection="required",
        success_url=success_url,
        cancel_url=cancel_url,
    )

    return session.url


def verify_webhook(payload: bytes, sig_header: str) -> stripe.Event:
    """Verify and parse a Stripe webhook event.

    Raises ValueError if webhook secret is not configured.
    Raises stripe.SignatureVerificationError on invalid signature.
    """
    webhook_secret = _get_webhook_secret()
    if not webhook_secret:
        raise ValueError("Stripe webhook secret is not configured")

    return stripe.Webhook.construct_event(payload, sig_header, webhook_secret)


def get_session_status(session_id: str) -> dict:
    """Retrieve Stripe checkout session status.

    Returns dict with payment_status and status.
    """
    secret_key = _get_stripe_key()
    if not secret_key:
        raise ValueError("Stripe is not configured")
    stripe.api_key = secret_key
    session = stripe.checkout.Session.retrieve(session_id)
    return {
        "payment_status": session.payment_status,
        "status": session.status,
    }
