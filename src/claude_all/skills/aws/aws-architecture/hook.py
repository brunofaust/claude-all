#!/usr/bin/env python3
"""Reminder hook for aws-architecture skill.

Fires on Terraform / CloudFormation / Lambda handler files.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import time

IAC_EXTS = (".tf", ".tf.json", ".yaml", ".yml")
CFN_HINTS = ("AWSTemplateFormatVersion", "Resources:", "Type: AWS::")
TF_HINTS = ('resource "aws_', 'data "aws_', 'module "', 'provider "aws"')
# AWS service keywords worth flagging when seen in Python handlers / IaC.
AWS_MARKERS = (
    "aws_lambda_function",
    "aws_sqs_queue",
    "aws_sns_topic",
    "aws_dynamodb_table",
    "aws_ecs_service",
    "aws_apigatewayv2",
    "aws_api_gateway",
    "aws_sfn_state_machine",
    "aws_eventbridge",
    "aws_events_rule",
    "aws_cloudwatch_event_rule",
    "AWS::Lambda::",
    "AWS::SQS::",
    "AWS::SNS::",
    "AWS::DynamoDB::",
    "AWS::ECS::",
    "AWS::ApiGateway",
    "AWS::StepFunctions::",
    "AWS::Events::",
)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    # Edit sends `new_string`; Write sends `content` — cover both.
    new_string = tool_input.get("new_string") or tool_input.get("content") or ""

    fires = False
    if file_path.endswith(IAC_EXTS):
        # Terraform .tf or CloudFormation YAML — fire only if it touches AWS resources
        if (
            any(h in new_string for h in TF_HINTS)
            or any(h in new_string for h in CFN_HINTS)
            or any(m in new_string for m in AWS_MARKERS)
        ):
            fires = True
    elif any(m in new_string for m in AWS_MARKERS):
        # Python / TS handlers using AWS service strings
        fires = True

    if not fires:
        return 0

    session_id = data.get("session_id") or "no-session"
    flag = os.path.join(tempfile.gettempdir(), f"claude-all-aws-arch-{session_id}.flag")
    # re-fire at most once per hour (flag mtime = last-fired time), so a long
    # session keeps the conventions fresh instead of being reminded only once.
    with contextlib.suppress(OSError):
        if os.path.exists(flag) and (time.time() - os.path.getmtime(flag)) < 3600:
            return 0  # reminded within the last hour
    # best-effort flag write: if the FS is unwritable, skip the once-per-session dedup
    with contextlib.suppress(OSError), open(flag, "w", encoding="utf-8") as f:
        f.write(file_path)

    # exit 0 + JSON additionalContext: exit 1 stderr is shown to the USER as a hook
    # error, never to Claude — this reminder is addressed to Claude.
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": (
                    "Reminder (aws-architecture, first AWS-touching edit this session): "
                    "Lambda idempotency on async invokes; "
                    "SQS visibility >= 6x processing time + DLQ; "
                    "SNS→SQS fanout, EventBridge for filter/replay/cross-account; "
                    "DynamoDB high-cardinality partition keys, never Scan in hot paths; "
                    "HTTP API > REST API (70% cheaper); "
                    "watch cost: NAT Gateway $/GB → VPC endpoints; CW Logs ingest $0.50/GB."
                ),
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
