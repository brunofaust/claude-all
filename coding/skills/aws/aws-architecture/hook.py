#!/usr/bin/env python3
"""Reminder hook for aws-architecture skill — fires on Terraform / CloudFormation / Lambda handler files."""

from __future__ import annotations

import json
import sys

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

    file_path = data.get("tool_input", {}).get("file_path", "")
    new_string = data.get("tool_input", {}).get("new_string", "") or ""

    fires = False
    if file_path.endswith(IAC_EXTS):
        # Terraform .tf or CloudFormation YAML — fire only if it touches AWS resources
        if any(h in new_string for h in TF_HINTS) or any(
            h in new_string for h in CFN_HINTS
        ):
            fires = True
        elif any(m in new_string for m in AWS_MARKERS):
            fires = True
    elif any(m in new_string for m in AWS_MARKERS):
        # Python / TS handlers using AWS service strings
        fires = True

    if not fires:
        return 0

    import os
    import tempfile

    session_id = data.get("session_id") or "no-session"
    flag = os.path.join(tempfile.gettempdir(), f"claude-all-aws-arch-{session_id}.flag")
    if os.path.exists(flag):
        return 0
    try:
        open(flag, "w").write(file_path)
    except OSError:
        pass

    print(
        "Reminder (aws-architecture, first AWS-touching edit this session): "
        "Lambda idempotency on async invokes; SQS visibility ≥ 6× processing time + DLQ; "
        "SNS→SQS fanout, EventBridge for filter/replay/cross-account; "
        "DynamoDB high-cardinality partition keys, never Scan in hot paths; "
        "HTTP API > REST API (70% cheaper); "
        "watch cost: NAT Gateway $/GB → VPC endpoints; CW Logs ingest $0.50/GB.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
