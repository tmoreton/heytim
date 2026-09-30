"""The private preview rejects a wrong account and never invokes a deploy."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "preview_destination_mail_capture.sh"
ACCOUNT = "820323452649"


def _fixture(tmp_path: Path, account: str) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    aws = bin_dir / "aws"
    aws.write_text(
        "#!/usr/bin/env bash\n"
        "case \"$*\" in\n"
        f"  *get-caller-identity*) echo {account};;\n"
        "  *get-app*) echo d17sj7dvhx07c;;\n"
        "  *get-branch*) echo main;;\n"
        "  *describe-stacks*) echo destination-stack-id;;\n"
        "  *) exit 91;;\n"
        "esac\n"
    )
    aws.chmod(0o755)
    cdk = bin_dir / "cdk"
    cdk.write_text(
        "#!/usr/bin/env bash\n"
        "echo \"$*\" >> \"$PREVIEW_CDK_CALLS\"\n"
        "if [[ \"$1\" == synth ]]; then\n"
        "  while [[ $# -gt 0 ]]; do\n"
        "    if [[ \"$1\" == --output ]]; then\n"
        "      shift; mkdir -p \"$1\"; echo '{}' > \"$1/test.template.json\"; break\n"
        "    fi\n"
        "    shift\n"
        "  done\n"
        "else\n"
        "  echo 'Resources'\n"
        "  echo '[+] AWS::SQS::Queue FrogBotApp/BotEmailInboundCapture ABC123'\n"
        "fi\n"
    )
    cdk.chmod(0o755)
    python = bin_dir / "python3"
    python.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$1\" == */_destination_mail_hold.py ]]; then\n"
        "  echo \"$*\" >> \"$PREVIEW_HOLD_CALLS\"\n"
        "  exit \"${PREVIEW_HOLD_STATUS:-0}\"\n"
        "fi\n"
        f"exec {sys.executable} \"$@\"\n"
    )
    python.chmod(0o755)
    return {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PREVIEW_CDK_CALLS": str(tmp_path / "cdk-calls"),
        "PREVIEW_HOLD_CALLS": str(tmp_path / "hold-calls"),
        "HEYTIM_ENVIRONMENT": "production",
        "HEYTIM_AUTH_EMAIL_PROVIDER": "ses",
        "HEYTIM_BOT_EMAIL_STAGE": "receive",
        "HEYTIM_BOT_EMAIL_CAPTURE_ONLY": "true",
        "HEYTIM_BOT_EMAIL_KEEP_HELD_SUBSCRIBER": "true",
        "HEYTIM_BOT_EMAIL_AVAILABLE": "false",
        "HEYTIM_AGENT_RUNTIME_ARN": f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/example",
        "HEYTIM_MEMORY_ID": "example",
        "HEYTIM_AGENTCORE_MEMORY_KMS_KEY_ARN": f"arn:aws:kms:us-east-1:{ACCOUNT}:key/example",
        "HEYTIM_GOOGLE_OAUTH_SECRET_ARN": f"arn:aws:secretsmanager:us-east-1:{ACCOUNT}:secret:google",
        "HEYTIM_GITHUB_APP_SECRET_ARN": f"arn:aws:secretsmanager:us-east-1:{ACCOUNT}:secret:github",
        "HEYTIM_X_OAUTH_SECRET_ARN": f"arn:aws:secretsmanager:us-east-1:{ACCOUNT}:secret:x",
        "HEYTIM_SLACK_OAUTH_SECRET_ARN": f"arn:aws:secretsmanager:us-east-1:{ACCOUNT}:secret:slack",
        "HEYTIM_NOTION_OAUTH_SECRET_ARN": f"arn:aws:secretsmanager:us-east-1:{ACCOUNT}:secret:notion",
        "HEYTIM_APNS_APPLICATION_ARN": f"arn:aws:sns:us-east-1:{ACCOUNT}:app/APNS/heytim",
        "HEYTIM_MONTHLY_BUDGET_USD": "100",
        "HEYTIM_YOUTUBE_SEARCH_DAILY_LIMIT": "100",
    }


def test_wrong_account_stops_before_synthesis(tmp_path: Path) -> None:
    env = _fixture(tmp_path, "188757775631")
    result = subprocess.run(
        ["bash", str(SCRIPT), "destination-profile"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "not the exact destination account" in result.stderr
    assert not Path(env["PREVIEW_CDK_CALLS"]).exists()


def test_valid_preview_uses_only_synth_and_template_diff(tmp_path: Path) -> None:
    env = _fixture(tmp_path, ACCOUNT)
    result = subprocess.run(
        ["bash", str(SCRIPT), "destination-profile"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "_destination_mail_hold.py --profile destination-profile" in Path(
        env["PREVIEW_HOLD_CALLS"]
    ).read_text()
    calls = Path(env["PREVIEW_CDK_CALLS"]).read_text().splitlines()
    assert len(calls) == 2
    assert calls[0].startswith("synth ")
    assert calls[1].startswith("diff ")
    assert "--method template" in calls[1]
    assert "deploy" not in "\n".join(calls)


def test_unproven_hold_stops_before_synthesis(tmp_path: Path) -> None:
    env = _fixture(tmp_path, ACCOUNT)
    env["PREVIEW_HOLD_STATUS"] = "1"
    result = subprocess.run(
        ["bash", str(SCRIPT), "destination-profile"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert Path(env["PREVIEW_HOLD_CALLS"]).exists()
    assert not Path(env["PREVIEW_CDK_CALLS"]).exists()
