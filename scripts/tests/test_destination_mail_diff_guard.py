"""Full-backend private preview must surface risky changes before deployment."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _destination_mail_diff_guard import summarize


def test_resource_removal_and_replacement_block() -> None:
    diff = """Resources
[-] AWS::SNS::Subscription BotEmailReceiverSubscription ABC123 destroy
[~] AWS::Logs::LogGroup NativePushLogs DEF456 replace
 └─ [~] LogGroupName (requires replacement)
"""
    result = summarize(diff)
    assert result["status"] == "NO_GO"
    assert "cloudformation_resource_removal" in result["blockers"]
    assert "cloudformation_resource_replacement" in result["blockers"]


def test_iam_statement_changes_require_review_even_for_additions() -> None:
    diff = """IAM Statement Changes
Resources
[+] AWS::SQS::Queue FrogBotApp/BotEmailInboundCapture ABC123
"""
    result = summarize(diff)
    assert "iam_statement_change_requires_review" in result["blockers"]
    assert "duplicate_standalone_mail_capture" in result["blockers"]


def test_second_quarantine_bucket_blocks_even_without_iam_changes() -> None:
    diff = """Resources
[+] AWS::S3::Bucket FrogBotApp/BotEmailQuarantine Bucket123
"""
    result = summarize(diff)
    assert result["status"] == "NO_GO"
    assert "duplicate_standalone_mail_capture" in result["blockers"]


def test_template_url_value_change_is_not_resource_removal() -> None:
    diff = """Resources
[~] AWS::CloudFormation::Stack FrogBotApp.NestedStack/FrogBotApp.NestedStackResource ABC123
 └─ [~] TemplateURL
     └─ [-] old-template.json
     └─ [+] new-template.json
"""
    result = summarize(diff)
    assert result["status"] == "REVIEW_REQUIRED"
    assert not result["blockers"]


def test_unrelated_stateful_change_blocks() -> None:
    diff = """Resources
[~] AWS::S3::Bucket FrogBotApp/UserFiles UserFiles123
[+] AWS::ApiGatewayV2::Route FrogBotApp/HttpApi/PUT--account--ai-sharing Route123
"""
    result = summarize(diff)
    assert result["status"] == "NO_GO"
    assert "unreviewed_resource_change" in result["blockers"]


def test_empty_or_unrecognized_diff_blocks() -> None:
    result = summarize("There were no differences")
    assert result["blockers"] == ["no_cloudformation_resource_diff_parsed"]
