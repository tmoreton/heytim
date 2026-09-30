"""Provider cutover ledger safety and reconciliation tests."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from provider_delivery_ledger import (
    DESTINATION_ACCOUNT, SOURCE_ACCOUNT, append, load, report,
)

START = "2026-09-29T21:00:00Z"
STOP = "2026-09-29T21:30:00Z"
DEST = "2026-09-29T21:35:00Z"
END = "2026-09-29T22:35:00Z"


def _window(path: Path) -> None:
    append(path, {
        "kind": "window", "startedAt": START,
        "sourceAccount": SOURCE_ACCOUNT, "destinationAccount": DESTINATION_ACCOUNT,
        "stripeEndpointId": "we_1UHW7fA7YzCs1pRZGFtVDD4J", "githubAppId": "4931494",
    }, create=True)


def _boundary(path: Path, name: str, at: str) -> None:
    append(path, {"kind": "boundary", "name": name, "at": at, "reference": "EV-BOUNDARY"})


def _delivery(path: Path, provider: str, event_id: str) -> None:
    append(path, {
        "kind": "delivery", "provider": provider, "id": event_id,
        "identityKind": "body-digest" if provider == "plaid" else "provider-id",
        "firstObservedAt": "2026-09-29T21:45:00Z", "eventType": "sample.event",
        "expectedOwner": "destination", "effectExpected": True, "reference": "EV-DELIVERY",
    })


def test_private_chain_is_append_only_and_detects_tampering() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "ledger.jsonl"
        _window(path)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        _boundary(path, "source-stopped", STOP)
        assert len(load(path)) == 2
        with pytest.raises(ValueError, match="immutable"):
            _boundary(path, "source-stopped", STOP)
        data = path.read_text().replace("EV-BOUNDARY", "EV-MODIFIED")
        path.write_text(data)
        with pytest.raises(ValueError, match="changed"):
            load(path)


def test_symlink_and_broad_permissions_are_rejected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "ledger.jsonl"
        link = Path(directory) / "link.jsonl"
        _window(path)
        link.symlink_to(path)
        with pytest.raises(OSError):
            load(link)
        os.chmod(path, 0o644)
        with pytest.raises(ValueError, match="0600"):
            load(path)


def test_http_200_alone_never_reconciles_and_missing_coverage_blocks() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "ledger.jsonl"
        _window(path)
        _boundary(path, "source-stopped", STOP)
        _boundary(path, "destination-started", DEST)
        _boundary(path, "ended", END)
        _delivery(path, "stripe", "evt_123456789")
        append(path, {
            "kind": "attempt", "provider": "stripe", "id": "evt_123456789",
            "attemptId": "req_1", "receivedAt": "2026-09-29T21:46:00Z",
            "account": DESTINATION_ACCOUNT, "httpStatus": 200, "reference": "EV-ATTEMPT",
        })
        result = report(load(path))
        assert result["status"] == "NO_GO"
        assert "stripe_provider_coverage_incomplete" in result["blockers"]
        assert "stripe-marker_unproved" in result["deliveries"][0]["missing"]
        assert "billing-row_unproved" in result["deliveries"][0]["missing"]


def test_complete_synthetic_evidence_still_requires_independent_review() -> None:
    identities = {
        "stripe": "evt_123456789",
        "github": "123e4567-e89b-12d3-a456-426614174000",
        "plaid": "sha256:" + "a" * 64,
    }
    effects = {
        "stripe": ("owner-mapping", "stripe-marker", "billing-row"),
        "github": ("owner-mapping", "subscription-index", "queue-job", "group-message"),
        "plaid": ("owner-mapping", "item-mapping", "sync-row"),
    }
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "ledger.jsonl"
        _window(path)
        _boundary(path, "source-stopped", STOP)
        _boundary(path, "destination-started", DEST)
        _boundary(path, "ended", END)
        for provider, event_id in identities.items():
            for scope in ("provider", "source-ingress", "destination-ingress"):
                append(path, {
                    "kind": "coverage", "provider": provider, "scope": scope,
                    "from": START, "through": END, "completeness": "complete",
                    "method": "operator-reconciliation" if provider == "plaid" and scope == "provider" else ("provider-api" if scope == "provider" else "aws-ingress"),
                    "reference": "EV-COVERAGE",
                })
            _delivery(path, provider, event_id)
            append(path, {
                "kind": "attempt", "provider": provider, "id": event_id,
                "attemptId": "attempt-1", "receivedAt": "2026-09-29T21:46:00Z",
                "account": DESTINATION_ACCOUNT, "httpStatus": 200,
                "reference": "EV-ATTEMPT",
            })
            for effect in effects[provider]:
                append(path, {
                    "kind": "evidence", "provider": provider, "id": event_id,
                    "effect": effect, "account": DESTINATION_ACCOUNT,
                    "state": "present", "reference": "EV-EFFECT",
                })
            append(path, {
                "kind": "resolution", "provider": provider, "id": event_id,
                "outcome": "reconciled", "reference": "EV-RECONCILED",
            })
        result = report(load(path))
        assert result["blockers"] == []
        assert result["status"] == "EVIDENCE_REVIEW_REQUIRED"


def test_plaid_cannot_claim_complete_api_listing_or_accept_payload_fields() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "ledger.jsonl"
        _window(path)
        with pytest.raises(ValueError, match="no complete"):
            append(path, {
                "kind": "coverage", "provider": "plaid", "scope": "provider",
                "from": START, "through": END, "completeness": "complete",
                "method": "provider-api", "reference": "EV-COVERAGE",
            })
        with pytest.raises(ValueError, match="unapproved fields"):
            append(path, {
                "kind": "delivery", "provider": "stripe", "id": "evt_123456789",
                "identityKind": "provider-id", "firstObservedAt": START,
                "eventType": "invoice.paid", "expectedOwner": "destination",
                "effectExpected": True, "reference": "EV-DELIVERY", "rawBody": "private webhook payload",
            })
