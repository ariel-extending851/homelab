# Tests for the finops module. Mocked AWS provider — no real API calls.

mock_provider "aws" {}

run "topic_and_budget_named_correctly" {
  variables {
    alert_email        = "ops@example.com"
    monthly_budget_usd = 30
    billing_alarm_usd  = 35
  }
  command = plan

  assert {
    condition     = aws_sns_topic.cost_alerts.name == "hl-cost-alerts"
    error_message = "SNS topic must be named hl-cost-alerts (shared alert sink)."
  }

  assert {
    condition     = aws_budgets_budget.monthly.limit_amount == "30"
    error_message = "Budget limit must reflect monthly_budget_usd."
  }

  assert {
    condition     = aws_accessanalyzer_analyzer.account.type == "ACCOUNT"
    error_message = "Access Analyzer must be the free ACCOUNT (external-access) type, not the paid unused-access tier."
  }

  assert {
    condition     = length(aws_sns_topic_subscription.cost_email) == 1
    error_message = "A non-empty alert_email must create exactly one email subscription."
  }
}

run "empty_email_skips_subscription" {
  variables {
    alert_email = ""
  }
  command = plan

  assert {
    condition     = length(aws_sns_topic_subscription.cost_email) == 0
    error_message = "Empty alert_email must not create an email subscription."
  }
}

run "zero_budget_rejected" {
  variables {
    monthly_budget_usd = 0
  }
  command         = plan
  expect_failures = [var.monthly_budget_usd]
}
