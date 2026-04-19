"""
Unit tests for infra/aws/modules/scheduler/lambda_src/lambda_function.py

Mocks boto3 EC2 client entirely — no AWS credentials or network required.
Run: python3 -m pytest infra/aws/modules/scheduler/lambda_src/tests/ -v
"""

import json
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

# Allow import from parent directory
sys.path.insert(0, str(Path(__file__).parent.parent))

import lambda_function


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(request_id="test-request-id"):
    ctx = MagicMock()
    ctx.aws_request_id = request_id
    return ctx


def _ec2_describe_response(*instances):
    """Build a fake describe_instances response."""
    return {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": inst["id"],
                        "InstanceType": inst.get("type", "t3.micro"),
                        "State": {"Name": inst["state"]},
                        "Tags": [{"Key": "Name", "Value": inst.get("name", "test")}],
                        "PrivateIpAddress": inst.get("private_ip", "10.0.0.1"),
                    }
                    for inst in instances
                ]
            }
        ]
    }


SERVER_ID = "i-server123"
AGENT_ID = "i-agent456"

ENV = {
    "SERVER_INSTANCE_ID": SERVER_ID,
    "AGENT_INSTANCE_ID": AGENT_ID,
}


# ---------------------------------------------------------------------------
# Tests: missing environment variables
# ---------------------------------------------------------------------------


def test_no_env_vars_returns_400():
    with patch.dict(os.environ, {}, clear=True):
        # Remove instance ID vars if present
        os.environ.pop("SERVER_INSTANCE_ID", None)
        os.environ.pop("AGENT_INSTANCE_ID", None)
        response = lambda_function.lambda_handler({}, _make_context())

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert "error" in body


def test_only_server_env_var_works():
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = _ec2_describe_response(
        {"id": SERVER_ID, "state": "running"}
    )
    with patch.dict(os.environ, {"SERVER_INSTANCE_ID": SERVER_ID}, clear=True):
        with patch.object(lambda_function, "ec2", mock_ec2):
            response = lambda_function.lambda_handler(
                {"action": "status"}, _make_context()
            )

    assert response["statusCode"] == 200


# ---------------------------------------------------------------------------
# Tests: action=status
# ---------------------------------------------------------------------------


def test_status_returns_200_with_instance_count():
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = _ec2_describe_response(
        {"id": SERVER_ID, "state": "running"},
        {"id": AGENT_ID, "state": "running"},
    )
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            response = lambda_function.lambda_handler(
                {"action": "status"}, _make_context()
            )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert "2 instance(s)" in body["message"]


def test_status_is_default_action():
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = _ec2_describe_response(
        {"id": SERVER_ID, "state": "running"},
    )
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            response = lambda_function.lambda_handler({}, _make_context())

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["action"] == "status"


# ---------------------------------------------------------------------------
# Tests: action=start
# ---------------------------------------------------------------------------


def test_start_calls_start_instances_for_stopped():
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = _ec2_describe_response(
        {"id": SERVER_ID, "state": "stopped"},
        {"id": AGENT_ID, "state": "stopped"},
    )
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            response = lambda_function.lambda_handler(
                {"action": "start"}, _make_context()
            )

    assert response["statusCode"] == 200
    mock_ec2.start_instances.assert_called_once()
    call_args = mock_ec2.start_instances.call_args[1]["InstanceIds"]
    assert SERVER_ID in call_args
    assert AGENT_ID in call_args


def test_start_skips_already_running_instances():
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = _ec2_describe_response(
        {"id": SERVER_ID, "state": "running"},
        {"id": AGENT_ID, "state": "running"},
    )
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            response = lambda_function.lambda_handler(
                {"action": "start"}, _make_context()
            )

    mock_ec2.start_instances.assert_not_called()
    body = json.loads(response["body"])
    assert "No stopped instances" in body["message"]


def test_start_only_starts_stopped_not_running():
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = _ec2_describe_response(
        {"id": SERVER_ID, "state": "running"},
        {"id": AGENT_ID, "state": "stopped"},
    )
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            lambda_function.lambda_handler({"action": "start"}, _make_context())

    call_args = mock_ec2.start_instances.call_args[1]["InstanceIds"]
    assert AGENT_ID in call_args
    assert SERVER_ID not in call_args


# ---------------------------------------------------------------------------
# Tests: action=stop
# ---------------------------------------------------------------------------


def test_stop_calls_stop_instances_for_running():
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = _ec2_describe_response(
        {"id": SERVER_ID, "state": "running"},
        {"id": AGENT_ID, "state": "running"},
    )
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            response = lambda_function.lambda_handler(
                {"action": "stop"}, _make_context()
            )

    assert response["statusCode"] == 200
    mock_ec2.stop_instances.assert_called_once()
    call_args = mock_ec2.stop_instances.call_args[1]["InstanceIds"]
    assert SERVER_ID in call_args
    assert AGENT_ID in call_args


def test_stop_skips_already_stopped_instances():
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = _ec2_describe_response(
        {"id": SERVER_ID, "state": "stopped"},
        {"id": AGENT_ID, "state": "stopped"},
    )
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            response = lambda_function.lambda_handler(
                {"action": "stop"}, _make_context()
            )

    mock_ec2.stop_instances.assert_not_called()
    body = json.loads(response["body"])
    assert "No running instances" in body["message"]


def test_stop_only_stops_running_not_stopped():
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = _ec2_describe_response(
        {"id": SERVER_ID, "state": "running"},
        {"id": AGENT_ID, "state": "stopped"},
    )
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            lambda_function.lambda_handler({"action": "stop"}, _make_context())

    call_args = mock_ec2.stop_instances.call_args[1]["InstanceIds"]
    assert SERVER_ID in call_args
    assert AGENT_ID not in call_args


# ---------------------------------------------------------------------------
# Tests: unknown action
# ---------------------------------------------------------------------------


def test_unknown_action_returns_200_with_error_field():
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = _ec2_describe_response(
        {"id": SERVER_ID, "state": "running"},
    )
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            response = lambda_function.lambda_handler(
                {"action": "reboot"}, _make_context()
            )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert "error" in body
    assert "reboot" in body["message"]


# ---------------------------------------------------------------------------
# Tests: get_instance_details
# ---------------------------------------------------------------------------


def test_get_instance_details_parses_tags():
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = _ec2_describe_response(
        {"id": SERVER_ID, "state": "running", "name": "hl-k3s-server"},
    )
    with patch.object(lambda_function, "ec2", mock_ec2):
        result = lambda_function.get_instance_details([SERVER_ID])

    assert result[0]["Name"] == "hl-k3s-server"
    assert result[0]["State"] == "running"
    assert result[0]["InstanceId"] == SERVER_ID


def test_get_instance_details_handles_missing_tags():
    response = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": SERVER_ID,
                        "InstanceType": "t3.micro",
                        "State": {"Name": "running"},
                        # No Tags key at all
                        "PrivateIpAddress": "10.0.0.1",
                    }
                ]
            }
        ]
    }
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = response
    with patch.object(lambda_function, "ec2", mock_ec2):
        result = lambda_function.get_instance_details([SERVER_ID])

    assert result[0]["Name"] == "N/A"


def test_response_includes_timestamp_and_request_id():
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = _ec2_describe_response(
        {"id": SERVER_ID, "state": "running"},
    )
    ctx = _make_context(request_id="req-abc-123")
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            response = lambda_function.lambda_handler({"action": "status"}, ctx)

    body = json.loads(response["body"])
    assert "timestamp" in body
    assert body["request_id"] == "req-abc-123"
