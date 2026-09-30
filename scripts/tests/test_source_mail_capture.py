"""Exact, side-effect-free SES store-only rule checks."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _source_mail_capture import active_store_only_match, validate_store_only_rule

BUCKET = "source-quarantine"
TOPIC = "arn:aws:sns:us-east-1:188757775631:source-mail"
ROLE = "arn:aws:iam::188757775631:role/source-ses-delivery"
PARAMS = {"bucket": BUCKET, "topic_arn": TOPIC, "role_arn": ROLE}


def store_only_rule() -> dict:
    return {
        "Name": "HeyTimBotInbox",
        "Enabled": True,
        "ScanEnabled": True,
        "Recipients": ["bots.heytim.ai"],
        "Actions": [
            {
                "S3Action": {
                    "BucketName": BUCKET,
                    "ObjectKeyPrefix": "received/",
                    "TopicArn": TOPIC,
                    "IamRoleArn": ROLE,
                }
            }
        ],
    }


def active_set(*others: dict) -> dict:
    return {
        "Metadata": {"Name": "source-set"},
        "Rules": [store_only_rule(), *others],
    }


def active_matches(value: dict) -> bool:
    return active_store_only_match(
        value, rule_set="source-set", rule_name="HeyTimBotInbox", **PARAMS
    )


def test_exact_store_only_rule_is_accepted() -> None:
    assert validate_store_only_rule(store_only_rule(), **PARAMS)
    assert active_matches(active_set())


@pytest.mark.parametrize(
    "field,value",
    [
        ("Enabled", False),
        ("ScanEnabled", False),
        ("Recipients", []),
        ("Recipients", ["heytim.ai"]),
        ("Recipients", ["bots.heytim.ai", "other.example"]),
        ("Actions", []),
        ("Actions", [{"BounceAction": {}}]),
        ("Actions", [{"StopAction": {}}]),
        ("Actions", [{"S3Action": {}, "StopAction": {}}]),
    ],
)
def test_rule_rejects_incorrect_shape(field: str, value: object) -> None:
    rule = store_only_rule()
    rule[field] = value
    assert not validate_store_only_rule(rule, **PARAMS)


@pytest.mark.parametrize(
    "field,value",
    [
        ("BucketName", "old-raw-mail"),
        ("ObjectKeyPrefix", ""),
        ("TopicArn", "arn:aws:sns:us-east-1:820323452649:other"),
        ("IamRoleArn", "arn:aws:iam::820323452649:role/other"),
        ("KmsKeyArn", "arn:aws:kms:us-east-1:188757775631:key/other"),
    ],
)
def test_rule_rejects_unreviewed_s3_destination_or_option(
    field: str, value: str
) -> None:
    rule = store_only_rule()
    rule["Actions"][0]["S3Action"][field] = value
    assert not validate_store_only_rule(rule, **PARAMS)


@pytest.mark.parametrize(
    "recipients",
    [
        [],
        ["bots.heytim.ai"],
        ["user@bots.heytim.ai"],
        [".heytim.ai"],
        [None],
    ],
)
def test_overlapping_bounce_or_stop_rule_blocks_capture(recipients: list) -> None:
    other = {
        "Name": "OtherRule",
        "Enabled": True,
        "Recipients": recipients,
        "Actions": [{"StopAction": {"Scope": "RuleSet"}}],
    }
    assert not active_matches(active_set(other))
    other["Actions"] = [{"BounceAction": {"SmtpReplyCode": "550"}}]
    assert not active_matches(active_set(other))


def test_unrelated_or_disabled_rule_does_not_block_capture() -> None:
    unrelated = {
        "Name": "OtherRule",
        "Enabled": True,
        "Recipients": ["heytim.ai"],
        "Actions": [{"BounceAction": {}}],
    }
    assert active_matches(active_set(unrelated))
    unrelated["Recipients"] = [".bots.heytim.ai"]
    assert active_matches(active_set(unrelated))
    unrelated["Recipients"] = []
    unrelated["Enabled"] = False
    assert active_matches(active_set(unrelated))


def test_active_rule_must_have_exact_set_name_and_one_matching_rule() -> None:
    value = active_set()
    value["Metadata"]["Name"] = "wrong-set"
    assert not active_matches(value)
    value = active_set(store_only_rule())
    assert not active_matches(value)
    value = active_set()
    value["Rules"][0]["Name"] = "wrong-rule"
    assert not active_matches(value)


def test_malformed_overlapping_rule_fails_closed() -> None:
    value = active_set(
        {"Name": "OtherRule", "Enabled": True, "Actions": [{"UnknownAction": {}}]}
    )
    assert not active_matches(value)
    value = copy.deepcopy(value)
    value["Rules"][1]["Recipients"] = []
    value["Rules"][1]["Actions"] = [{}]
    assert not active_matches(value)
    value["Rules"][1]["Enabled"] = "unknown"
    assert not active_matches(value)
