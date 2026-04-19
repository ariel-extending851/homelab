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
import os
import boto3
from datetime import datetime, timezone
from typing import Dict, Any, List

# Initialize AWS clients
# Region is inferred from Lambda's AWS_REGION environment variable
ec2 = boto3.client("ec2", region_name=os.environ.get("AWS_REGION", "us-east-1"))


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

    # Get current instance states
    instances = get_instance_details(instance_ids)

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
            ec2.start_instances(InstanceIds=stopped)
            result["started"] = stopped
            result["message"] = f"Started {len(stopped)} instance(s)"
        else:
            result["message"] = "No stopped instances to start"

    elif action == "stop":
        running = [i["InstanceId"] for i in instances if i["State"] == "running"]
        if running:
            ec2.stop_instances(InstanceIds=running)
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
