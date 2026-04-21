# Tests for scheduler module security and configuration correctness.
# Verifies Lambda URL auth, IAM ARN scoping, and EventBridge payload correctness.

mock_provider "aws" {
  mock_resource "aws_iam_role" {
    defaults = {
      arn  = "arn:aws:iam::123456789012:role/hl-ec2-scheduler-mock"
      id   = "hl-ec2-scheduler-mock"
      name = "hl-ec2-scheduler-mock"
    }
  }
  mock_resource "aws_lambda_function" {
    defaults = {
      arn = "arn:aws:lambda:us-east-1:123456789012:function:hl-ec2-scheduler"
    }
  }
  mock_resource "aws_cloudwatch_event_rule" {
    defaults = {
      arn = "arn:aws:events:us-east-1:123456789012:rule/hl-k3s-mock"
    }
  }
}
mock_provider "archive" {}

variables {
  server_instance_id = "i-0server123456789"
  agent_instance_id  = "i-0agent123456789a"
  schedule_start_hour = 10
  schedule_stop_hour  = 21
}

# ── Lambda URL requires IAM auth ──────────────────────────────────────────────

run "lambda_url_auth" {
  assert {
    condition     = aws_lambda_function_url.scheduler.authorization_type == "AWS_IAM"
    error_message = "Lambda URL must require AWS_IAM auth — NONE would allow unauthenticated invocation"
  }
}

# ── IAM policy scoped to specific instance ARNs ───────────────────────────────

run "iam_arn_scoped" {
  assert {
    condition = contains(
      jsondecode(aws_iam_role_policy.ec2_control.policy).Statement[1].Resource,
      "arn:aws:ec2:*:*:instance/i-0server123456789"
    )
    error_message = "EC2 control policy must scope StartInstances/StopInstances to the server instance ARN"
  }
  assert {
    condition = contains(
      jsondecode(aws_iam_role_policy.ec2_control.policy).Statement[1].Resource,
      "arn:aws:ec2:*:*:instance/i-0agent123456789a"
    )
    error_message = "EC2 control policy must scope StartInstances/StopInstances to the agent instance ARN"
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.ec2_control.policy).Statement[1].Sid == "StartStopSpecificInstances"
    error_message = "Scoped statement must be Sid=StartStopSpecificInstances"
  }
}

# ── EventBridge payloads are correct ─────────────────────────────────────────

run "eventbridge_start_payload" {
  assert {
    condition     = aws_cloudwatch_event_target.start_instances.input == "{\"action\":\"start\"}"
    error_message = "Start EventBridge target must send {\"action\":\"start\"} to Lambda"
  }
}

run "eventbridge_stop_payload" {
  assert {
    condition     = aws_cloudwatch_event_target.stop_instances.input == "{\"action\":\"stop\"}"
    error_message = "Stop EventBridge target must send {\"action\":\"stop\"} to Lambda"
  }
}

# ── Lambda invocation permissions ─────────────────────────────────────────────

run "lambda_permissions" {
  assert {
    condition     = aws_lambda_permission.allow_eventbridge_start.principal == "events.amazonaws.com"
    error_message = "Start Lambda permission must be granted to events.amazonaws.com"
  }
  assert {
    condition     = aws_lambda_permission.allow_eventbridge_stop.principal == "events.amazonaws.com"
    error_message = "Stop Lambda permission must be granted to events.amazonaws.com"
  }
}
