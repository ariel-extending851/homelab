"""
K3s Homelab EC2 Instance Scheduler

Automatically starts and stops EC2 instances based on schedule to reduce costs.
Triggered by EventBridge (scheduled) or manual invocation via Lambda Function URL.

Environment Variables:
    SERVER_INSTANCE_ID: EC2 instance ID for k3s server
    AGENT_INSTANCE_ID: EC2 instance ID for k3s agent

Event Input:
    {
        "action": "start" | "stop" | "status"
    }
"""

import json
import logging
import os
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from datetime import datetime, timezone
from typing import Dict, Any, List

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# EC2 error codes worth letting EventBridge retry on.
# Anything else (InvalidInstanceID.NotFound, UnauthorizedOperation, ...) is
# permanent and retrying only generates noise.
_RETRYABLE_EC2_ERROR_CODES = frozenset(
    {
        "Throttling",
        "ThrottlingException",
        "RequestLimitExceeded",
        "TooManyRequestsException",
        "InternalError",
        "InternalFailure",
        "ServiceUnavailable",
    }
)

# Initialize AWS clients
# Region is inferred from Lambda's AWS_REGION environment variable
ec2 = boto3.client("ec2", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def _is_retryable(err: Exception) -> bool:
    """True if the caller should re-raise so EventBridge retries the invocation.

    BotoCoreError subclasses (connection/DNS/SSL failures) are always treated
    as transient. ClientError is retryable only for whitelisted EC2 codes.
    """
    if isinstance(err, BotoCoreError):
        return True
    if isinstance(err, ClientError):
        code = err.response.get("Error", {}).get("Code", "")
        return code in _RETRYABLE_EC2_ERROR_CODES
    return False


def _ec2_error_response(operation: str, err: Exception) -> Dict[str, Any]:
    """Build a structured 502 response for a *permanent* boto3 error.

    The returned ``statusCode`` is useful for synchronous/manual callers such as
    a Lambda Function URL. For EventBridge-triggered Lambda invocations the
    return payload is ignored for retry purposes: retries only happen when the
    invocation fails with a Lambda error (exception or timeout). Transient
    errors are therefore re-raised by the caller (see ``_is_retryable``) so
    EventBridge's built-in async retry applies; this helper is called only for
    permanent errors where retrying would not help.
    """
    if isinstance(err, ClientError):
        code = err.response.get("Error", {}).get("Code", "ClientError")
        message = err.response.get("Error", {}).get("Message", str(err))
    else:
        code = type(err).__name__
        message = str(err)
    body = {"error": code, "message": message, "operation": operation}
    # logger.exception preserves the traceback in CloudWatch for post-mortem.
    logger.exception("EC2 %s failed (permanent): %s", operation, code)
    return {
        "statusCode": 502,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler function

    Args:
        event: Lambda event containing action parameter
        context: Lambda context object

    Returns:
        Response with status code and execution results
    """

    # Get action from event (default to 'status')
    action = event.get("action", "status")

    # Get instance IDs from environment variables
    instance_ids = [
        os.environ.get("SERVER_INSTANCE_ID"),
        os.environ.get("AGENT_INSTANCE_ID"),
    ]

    # Filter out None values (in case env vars not set)
    instance_ids = [iid for iid in instance_ids if iid]

    if not instance_ids:
        return {
            "statusCode": 400,
            "body": json.dumps(
                {"error": "No instance IDs configured in environment variables"}
            ),
        }

    # Get current instance states.
    # Transient errors (throttling, connection failures) are re-raised so
    # EventBridge retries the invocation; permanent errors return a structured
    # 502 for Function URL callers.
    try:
        instances = get_instance_details(instance_ids)
    except (ClientError, BotoCoreError) as err:
        if _is_retryable(err):
            raise
        return _ec2_error_response("describe_instances", err)

    result = {
        "action": action,
        "instances": instances,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": context.aws_request_id,
    }

    # Execute requested action
    if action == "start":
        stopped = [i["InstanceId"] for i in instances if i["State"] == "stopped"]
        if stopped:
            try:
                ec2.start_instances(InstanceIds=stopped)
            except (ClientError, BotoCoreError) as err:
                if _is_retryable(err):
                    raise
                return _ec2_error_response("start_instances", err)
            result["started"] = stopped
            result["message"] = f"Started {len(stopped)} instance(s)"
        else:
            result["message"] = "No stopped instances to start"

    elif action == "stop":
        running = [i["InstanceId"] for i in instances if i["State"] == "running"]
        if running:
            try:
                ec2.stop_instances(InstanceIds=running)
            except (ClientError, BotoCoreError) as err:
                if _is_retryable(err):
                    raise
                return _ec2_error_response("stop_instances", err)
            result["stopped"] = running
            result["message"] = f"Stopped {len(running)} instance(s)"
        else:
            result["message"] = "No running instances to stop"

    elif action == "status":
        result["message"] = f"Status check: {len(instances)} instance(s) found"

    else:
        result["message"] = f"Unknown action: {action}"
        result["error"] = "Valid actions: start, stop, status"

    print(json.dumps(result))

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(result, indent=2),
    }


def get_instance_details(instance_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Retrieve instance details from EC2

    Args:
        instance_ids: List of EC2 instance IDs

    Returns:
        List of instance details dictionaries
    """
    response = ec2.describe_instances(InstanceIds=instance_ids)

    instances = []
    for reservation in response["Reservations"]:
        for instance in reservation["Instances"]:
            # Extract tags into dict
            tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}

            instances.append(
                {
                    "InstanceId": instance["InstanceId"],
                    "InstanceType": instance["InstanceType"],
                    "State": instance["State"]["Name"],
                    "Name": tags.get("Name", "N/A"),
                    "PrivateIpAddress": instance.get("PrivateIpAddress", "N/A"),
                    "PublicIpAddress": instance.get("PublicIpAddress", "N/A"),
                }
            )

    return instances
