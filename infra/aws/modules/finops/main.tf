# ==============================================================================
# FinOps + Security Alerting Module
# ==============================================================================
# Free / near-free guardrails the homelab lacked: real spend alerts on the
# account (not just the Infracost PR gate), plus a single notification sink for
# security findings. Everything here is free at homelab volume:
#   - SNS: first 1,000 email notifications/month free.
#   - AWS Budgets: first 2 budgets free (one used here).
#   - Cost Anomaly Detection: entirely free.
#   - CloudWatch billing alarm: first 10 alarms free; AWS/Billing metrics only
#     publish in us-east-1 — the root provider is already us-east-1.
#   - IAM Access Analyzer (ACCOUNT type / external-access): free. (The
#     unused-access tier is the paid one — deliberately NOT used.)
#
# One SNS topic (hl-cost-alerts) is the shared sink for Budgets, Cost Anomaly,
# the billing alarm AND security findings (GuardDuty + Access Analyzer) via an
# EventBridge rule. The audit module deliberately scopes EventBridge fan-out
# out (see modules/audit/main.tf), so the findings rule lives here next to the
# topic it publishes to.
# ==============================================================================

data "aws_caller_identity" "current" {}

# ── Shared notification topic ────────────────────────────────────────────────

resource "aws_sns_topic" "cost_alerts" {
  name = "hl-cost-alerts"

  tags = {
    Name = "hl-cost-alerts"
  }
}

# Topic policy — without this, Budgets / Cost Anomaly / CloudWatch / EventBridge
# cannot publish to the topic and the alerts silently never arrive.
data "aws_iam_policy_document" "cost_alerts" {
  statement {
    sid     = "AllowServicesToPublish"
    actions = ["SNS:Publish"]
    principals {
      type = "Service"
      identifiers = [
        "budgets.amazonaws.com",    # AWS Budgets notifications
        "costalerts.amazonaws.com", # Cost Anomaly Detection
        "cloudwatch.amazonaws.com", # billing alarm
        "events.amazonaws.com",     # EventBridge security-findings rule
      ]
    }
    resources = [aws_sns_topic.cost_alerts.arn]
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_sns_topic_policy" "cost_alerts" {
  arn    = aws_sns_topic.cost_alerts.arn
  policy = data.aws_iam_policy_document.cost_alerts.json
}

# Email delivery. Optional: empty alert_email skips it so the module (and the
# root variable_validation tests) plan cleanly without an address. Email
# subscriptions require a one-time manual confirmation click — see
# docs/operations/cost-controls.md.
resource "aws_sns_topic_subscription" "cost_email" {
  count = var.alert_email == "" ? 0 : 1

  topic_arn = aws_sns_topic.cost_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ── Monthly cost budget ──────────────────────────────────────────────────────
# Notifies at 80% actual, 100% actual, and 100% forecasted. All notifications
# fan out through the SNS topic (which carries the email subscription) so there
# is a single delivery path to confirm.

resource "aws_budgets_budget" "monthly" {
  name         = "hl-monthly-cost"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 80
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = [aws_sns_topic.cost_alerts.arn]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 100
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = [aws_sns_topic.cost_alerts.arn]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 100
    threshold_type            = "PERCENTAGE"
    notification_type         = "FORECASTED"
    subscriber_sns_topic_arns = [aws_sns_topic.cost_alerts.arn]
  }
}

# ── Cost Anomaly Detection (free) ────────────────────────────────────────────
# DIMENSIONAL/SERVICE monitor catches a single runaway service (e.g. a spot
# price spike or a forgotten resource) even if total spend stays under budget.

resource "aws_ce_anomaly_monitor" "services" {
  name              = "hl-cost-anomaly-monitor"
  monitor_type      = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
}

resource "aws_ce_anomaly_subscription" "alerts" {
  name = "hl-cost-anomaly-subscription"
  # SNS subscribers require IMMEDIATE frequency (DAILY/WEEKLY are EMAIL-only in
  # Cost Anomaly Detection). The SNS topic fans out to the email subscription,
  # so a single SNS subscriber keeps the one-topic delivery path intact.
  frequency        = "IMMEDIATE"
  monitor_arn_list = [aws_ce_anomaly_monitor.services.arn]

  subscriber {
    type    = "SNS"
    address = aws_sns_topic.cost_alerts.arn
  }

  # Only surface anomalies whose absolute impact clears the threshold — keeps
  # day-to-day spot price jitter from generating noise.
  threshold_expression {
    dimension {
      key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
      match_options = ["GREATER_THAN_OR_EQUAL"]
      values        = [tostring(var.anomaly_impact_threshold_usd)]
    }
  }

  depends_on = [aws_sns_topic_policy.cost_alerts]
}

# ── CloudWatch billing alarm (backstop) ──────────────────────────────────────
# A coarse real-time backstop above the budget. EstimatedCharges only exists in
# us-east-1; this stack is us-east-1. Changing aws_region breaks this alarm.

resource "aws_cloudwatch_metric_alarm" "billing" {
  alarm_name          = "hl-billing-estimated-charges"
  alarm_description   = "Account EstimatedCharges exceeded the ${var.billing_alarm_usd} USD backstop (above the ${var.monthly_budget_usd} USD budget)."
  namespace           = "AWS/Billing"
  metric_name         = "EstimatedCharges"
  dimensions          = { Currency = "USD" }
  statistic           = "Maximum"
  period              = 21600 # 6h — billing metrics update only a few times/day
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = var.billing_alarm_usd
  alarm_actions       = [aws_sns_topic.cost_alerts.arn]
  treat_missing_data  = "notBreaching"

  tags = {
    Name = "hl-billing-estimated-charges"
  }
}

# ── IAM Access Analyzer (free, external-access) ──────────────────────────────
# Surfaces any S3 bucket / IAM role reachable from outside the account. Free
# at the ACCOUNT type; the unused-access analyzer is the paid tier and is not
# created here.

resource "aws_accessanalyzer_analyzer" "account" {
  analyzer_name = "hl-access-analyzer"
  type          = "ACCOUNT"

  tags = {
    Name = "hl-access-analyzer"
  }
}

# ── Security findings → SNS ──────────────────────────────────────────────────
# Routes GuardDuty + Access Analyzer findings to the same email path as cost
# alerts, so a finding is not stranded in a console nobody checks.

resource "aws_cloudwatch_event_rule" "findings" {
  name        = "hl-security-findings"
  description = "Route GuardDuty and IAM Access Analyzer findings to the hl-cost-alerts SNS topic."

  event_pattern = jsonencode({
    source = ["aws.guardduty", "aws.access-analyzer"]
  })

  tags = {
    Name = "hl-security-findings"
  }
}

resource "aws_cloudwatch_event_target" "findings_sns" {
  rule      = aws_cloudwatch_event_rule.findings.name
  target_id = "HlSecurityFindingsToSns"
  arn       = aws_sns_topic.cost_alerts.arn
}
