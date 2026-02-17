# ==============================================================================
# Scheduler Module - Automated EC2 Instance Start/Stop
# ==============================================================================
# This module creates Lambda functions and EventBridge rules to automatically
# start and stop EC2 instances based on a schedule (e.g., 10 AM - 9 PM daily).
#
# Cost savings: Running instances 11 hours/day (45% uptime) vs 24/7
# ==============================================================================

# IAM Role for Lambda
resource "aws_iam_role" "scheduler_lambda" {
  name_prefix = "hl-ec2-scheduler-"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "hl-ec2-scheduler-lambda-role"
  }
}

# Attach basic Lambda execution policy
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.scheduler_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Custom policy for EC2 control
# Scoped to specific instances — DescribeInstances requires wildcard (no resource-level perms),
# but Start/Stop can be restricted to specific instance ARNs.
resource "aws_iam_role_policy" "ec2_control" {
  name_prefix = "ec2-scheduler-policy-"
  role        = aws_iam_role.scheduler_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DescribeInstances"
        Effect   = "Allow"
        Action   = ["ec2:DescribeInstances"]
        Resource = "*"
      },
      {
        Sid    = "StartStopSpecificInstances"
        Effect = "Allow"
        Action = [
          "ec2:StartInstances",
          "ec2:StopInstances"
        ]
        Resource = [
          "arn:aws:ec2:*:*:instance/${var.server_instance_id}",
          "arn:aws:ec2:*:*:instance/${var.agent_instance_id}"
        ]
      }
    ]
  })
}

# Package Lambda function code
# Output to .terraform/ directory to avoid polluting the repo with generated artifacts
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/lambda_src"
  output_path = "${path.root}/.terraform/lambda_builds/hl-ec2-scheduler.zip"
}

# Lambda Function
resource "aws_lambda_function" "scheduler" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = "hl-ec2-scheduler"
  role             = aws_iam_role.scheduler_lambda.arn
  handler          = "lambda_function.lambda_handler"
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  runtime          = "python3.12"
  timeout          = 60
  memory_size      = 128

  description = "K3s homelab EC2 instance scheduler (${var.schedule_start_hour}:00 - ${var.schedule_stop_hour}:00 ${var.schedule_timezone})"

  environment {
    variables = {
      SERVER_INSTANCE_ID = var.server_instance_id
      AGENT_INSTANCE_ID  = var.agent_instance_id
    }
  }

  tags = {
    Name = "hl-ec2-scheduler"
  }
}

# Lambda Function URL (for manual control)
# authorization_type = "AWS_IAM" requires callers to sign requests with
# AWS SigV4 (i.e. use 'aws lambda invoke' or awscurl, not plain curl).
# This prevents unauthenticated actors from starting/stopping instances.
resource "aws_lambda_function_url" "scheduler" {
  function_name      = aws_lambda_function.scheduler.function_name
  authorization_type = "AWS_IAM"
}

# Convert timezone-aware schedule to UTC for EventBridge
# BRT (America/Sao_Paulo) is UTC-3 (no DST currently)
# 10 AM BRT = 1 PM UTC (13:00)
# 9 PM BRT = 12 AM UTC next day (00:00)
locals {
  # UTC offset conversion for BRT (America/Sao_Paulo = UTC-3).
  # Brazil abolished Daylight Saving Time in 2019, so BRT is a fixed UTC-3 offset year-round.
  # This arithmetic is correct and requires no DST adjustment.
  # NOTE: If schedule_timezone is changed to a region that observes DST, this will
  # need to be replaced with a proper timezone-aware conversion.
  start_hour_utc = (var.schedule_start_hour + 3) % 24
  stop_hour_utc  = (var.schedule_stop_hour + 3) % 24
}

# EventBridge Rule - Start Instances
resource "aws_cloudwatch_event_rule" "start_instances" {
  name                = "hl-k3s-start-daily"
  description         = "Start k3s instances at ${var.schedule_start_hour}:00 ${var.schedule_timezone} daily"
  schedule_expression = "cron(0 ${local.start_hour_utc} * * ? *)"

  tags = {
    Name = "hl-k3s-start-daily"
  }
}

# EventBridge Rule - Stop Instances
resource "aws_cloudwatch_event_rule" "stop_instances" {
  name                = "hl-k3s-stop-daily"
  description         = "Stop k3s instances at ${var.schedule_stop_hour}:00 ${var.schedule_timezone} daily"
  schedule_expression = "cron(0 ${local.stop_hour_utc} * * ? *)"

  tags = {
    Name = "hl-k3s-stop-daily"
  }
}

# EventBridge Target - Start
resource "aws_cloudwatch_event_target" "start_instances" {
  rule      = aws_cloudwatch_event_rule.start_instances.name
  target_id = "StartK3sInstances"
  arn       = aws_lambda_function.scheduler.arn

  input = jsonencode({
    action = "start"
  })
}

# EventBridge Target - Stop
resource "aws_cloudwatch_event_target" "stop_instances" {
  rule      = aws_cloudwatch_event_rule.stop_instances.name
  target_id = "StopK3sInstances"
  arn       = aws_lambda_function.scheduler.arn

  input = jsonencode({
    action = "stop"
  })
}

# Grant EventBridge permission to invoke Lambda - Start
resource "aws_lambda_permission" "allow_eventbridge_start" {
  statement_id  = "AllowEventBridgeStart"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.start_instances.arn
}

# Grant EventBridge permission to invoke Lambda - Stop
resource "aws_lambda_permission" "allow_eventbridge_stop" {
  statement_id  = "AllowEventBridgeStop"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.stop_instances.arn
}
