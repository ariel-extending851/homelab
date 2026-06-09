# Tests for BRT→UTC schedule conversion in EventBridge cron expressions.
# BRT = America/Sao_Paulo = UTC-3 (fixed offset — Brazil abolished DST in 2019).
# Formula: utc_hour = (brt_hour + 3) % 24

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
}

# ── standard workday window: 10 AM–9 PM BRT ──────────────────────────────────

run "default_window_10am_9pm_brt" {
  variables {
    schedule_start_hour = 10 # BRT 10:00 → UTC 13:00
    schedule_stop_hour  = 21 # BRT 21:00 → UTC 24 mod 24 = 00:00
  }
  assert {
    condition     = aws_cloudwatch_event_rule.start_instances.schedule_expression == "cron(0 13 * * ? *)"
    error_message = "10 AM BRT must produce cron(0 13 * * ? *)"
  }
  assert {
    condition     = aws_cloudwatch_event_rule.stop_instances.schedule_expression == "cron(0 0 * * ? *)"
    error_message = "9 PM BRT (21) must produce cron(0 0 * * ? *) — midnight UTC"
  }
}

# ── midnight wrap-around: start at midnight BRT ───────────────────────────────

run "midnight_start_0am_brt" {
  variables {
    schedule_start_hour = 0  # BRT 00:00 → UTC 03:00
    schedule_stop_hour  = 23 # BRT 23:00 → UTC 26 mod 24 = 02:00
  }
  assert {
    condition     = aws_cloudwatch_event_rule.start_instances.schedule_expression == "cron(0 3 * * ? *)"
    error_message = "Midnight BRT (0) must produce cron(0 3 * * ? *)"
  }
  assert {
    condition     = aws_cloudwatch_event_rule.stop_instances.schedule_expression == "cron(0 2 * * ? *)"
    error_message = "11 PM BRT (23) must produce cron(0 2 * * ? *) — 26 mod 24 = 2"
  }
}

# ── late evening stop: 10 PM BRT → 1 AM UTC ──────────────────────────────────

run "late_stop_22_brt" {
  variables {
    schedule_start_hour = 8  # BRT 08:00 → UTC 11:00
    schedule_stop_hour  = 22 # BRT 22:00 → UTC 25 mod 24 = 01:00
  }
  assert {
    condition     = aws_cloudwatch_event_rule.start_instances.schedule_expression == "cron(0 11 * * ? *)"
    error_message = "8 AM BRT must produce cron(0 11 * * ? *)"
  }
  assert {
    condition     = aws_cloudwatch_event_rule.stop_instances.schedule_expression == "cron(0 1 * * ? *)"
    error_message = "10 PM BRT (22) must produce cron(0 1 * * ? *) — 25 mod 24 = 1"
  }
}

# ── lambda naming convention ──────────────────────────────────────────────────

run "lambda_naming" {
  variables {
    schedule_start_hour = 10
    schedule_stop_hour  = 21
  }
  assert {
    condition     = aws_lambda_function.scheduler.function_name == "hl-ec2-scheduler"
    error_message = "Lambda must be named 'hl-ec2-scheduler'"
  }
  assert {
    condition     = aws_lambda_function.scheduler.runtime == "python3.12"
    error_message = "Lambda runtime must be python3.12"
  }
}

# ── eventbridge rule naming ───────────────────────────────────────────────────

run "eventbridge_naming" {
  variables {
    schedule_start_hour = 10
    schedule_stop_hour  = 21
  }
  assert {
    condition     = aws_cloudwatch_event_rule.start_instances.name == "hl-k3s-start-daily"
    error_message = "Start rule must be named 'hl-k3s-start-daily'"
  }
  assert {
    condition     = aws_cloudwatch_event_rule.stop_instances.name == "hl-k3s-stop-daily"
    error_message = "Stop rule must be named 'hl-k3s-stop-daily'"
  }
}
