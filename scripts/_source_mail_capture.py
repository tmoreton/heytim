"""Pure checks for an enabled, store-only SES bot-mail capture rule.

The caller must separately prove the bucket, topic, role, and queue identities
belong to the intended AWS account. These checks do not call AWS or change it.
"""

from __future__ import annotations

from typing import Any

_ACTION_TYPES = {
    "AddHeaderAction",
    "BounceAction",
    "ConnectAction",
    "LambdaAction",
    "S3Action",
    "SNSAction",
    "StopAction",
    "WorkmailAction",
}


def validate_store_only_rule(
    rule: Any,
    *,
    bucket: str,
    topic_arn: str,
    role_arn: str,
    domain: str = "bots.heytim.ai",
) -> bool:
    """Require the exact enabled SES S3+SNS action selected for quarantine."""
    if not all(
        isinstance(value, str) and value
        for value in (bucket, topic_arn, role_arn, domain)
    ) or not isinstance(rule, dict):
        return False
    if rule.get("Enabled") is not True or rule.get("ScanEnabled") is not True:
        return False
    if rule.get("Recipients") != [domain]:
        return False
    actions = rule.get("Actions")
    if not isinstance(actions, list) or len(actions) != 1:
        return False
    action = actions[0]
    if not isinstance(action, dict) or set(action) != {"S3Action"}:
        return False
    s3_action = action["S3Action"]
    if not isinstance(s3_action, dict):
        return False
    return s3_action == {
        "BucketName": bucket,
        "ObjectKeyPrefix": "received/",
        "TopicArn": topic_arn,
        "IamRoleArn": role_arn,
    }


def _overlaps_domain(recipients: Any, domain: str) -> bool:
    """Conservatively identify SES recipient conditions covering this domain.

    An empty condition is catch-all. A leading-dot condition covers subdomains,
    while a bare parent domain does not cover its subdomains in SES receipt rules.
    Unknown or malformed conditions are treated as overlapping.
    """
    if not isinstance(recipients, list) or not recipients:
        return True
    target = domain.casefold()
    for recipient in recipients:
        if not isinstance(recipient, str) or not recipient:
            return True
        condition = recipient.casefold()
        if condition == target:
            return True
        if condition.startswith(".") and target.endswith(condition):
            return True
        if "@" in condition:
            if condition.count("@") != 1:
                return True
            if condition.rsplit("@", 1)[1] == target:
                return True
        elif condition.startswith("*") or condition.endswith("."):
            return True
    return False


def active_store_only_match(
    active_set: Any,
    *,
    rule_set: str,
    rule_name: str,
    bucket: str,
    topic_arn: str,
    role_arn: str,
) -> bool:
    """Bind the expected active rule and reject overlapping bounce/stop rules."""
    if not isinstance(active_set, dict) or not all(
        isinstance(value, str) and value
        for value in (rule_set, rule_name, bucket, topic_arn, role_arn)
    ):
        return False
    metadata = active_set.get("Metadata")
    rules = active_set.get("Rules")
    if (
        not isinstance(metadata, dict)
        or metadata.get("Name") != rule_set
        or not isinstance(rules, list)
    ):
        return False
    matches = [
        rule
        for rule in rules
        if isinstance(rule, dict) and rule.get("Name") == rule_name
    ]
    if len(matches) != 1 or not validate_store_only_rule(
        matches[0], bucket=bucket, topic_arn=topic_arn, role_arn=role_arn
    ):
        return False
    for rule in rules:
        if not isinstance(rule, dict):
            return False
        if rule is matches[0]:
            continue
        enabled = rule.get("Enabled")
        if enabled is False:
            continue
        if enabled is not True:
            return False
        if not _overlaps_domain(rule.get("Recipients"), "bots.heytim.ai"):
            continue
        actions = rule.get("Actions")
        if not isinstance(actions, list):
            return False
        for action in actions:
            if (
                not isinstance(action, dict)
                or len(action) != 1
                or not set(action) <= _ACTION_TYPES
                or "BounceAction" in action
                or "StopAction" in action
            ):
                return False
    return True
