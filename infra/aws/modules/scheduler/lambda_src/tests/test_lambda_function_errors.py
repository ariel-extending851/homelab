"""
Error-path unit tests for infra/aws/modules/scheduler/lambda_src/lambda_function.py

Covers boto3 ClientError / BotoCoreError handling and partial-response edge
cases that the happy-path suite in test_lambda_function.py does not exercise.

Run: python3 -m pytest infra/aws/modules/scheduler/lambda_src/tests/ -v
"""

import json
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

sys.path.insert(0, str(Path(__file__).parent.parent))

import lambda_function


def _make_context(request_id="test-request-id"):
    ctx = MagicMock()
    ctx.aws_request_id = request_id
    return ctx


def _client_error(code: str, message: str, operation: str) -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": code, "Message": message}},
        operation_name=operation,
    )


SERVER_ID = "i-server123"
AGENT_ID = "i-agent456"

ENV = {
    "SERVER_INSTANCE_ID": SERVER_ID,
    "AGENT_INSTANCE_ID": AGENT_ID,
}


# ---------------------------------------------------------------------------
# describe_instances failures
# ---------------------------------------------------------------------------


def test_describe_instances_not_found_returns_502():
    """If EC2 rejects the DescribeInstances call, return a structured 502.

    Previously this raised an unhandled exception; now consumers of the
    Function URL (awscurl / aws lambda invoke) get a parseable error body.
    """
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.side_effect = _client_error(
        "InvalidInstanceID.NotFound",
        "The instance ID 'i-server123' does not exist",
        "DescribeInstances",
    )
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            response = lambda_function.lambda_handler(
                {"action": "status"}, _make_context()
            )

    assert response["statusCode"] == 502
    body = json.loads(response["body"])
    assert body["error"] == "InvalidInstanceID.NotFound"
    assert body["operation"] == "describe_instances"
    assert "does not exist" in body["message"]


def test_describe_instances_throttling_raises_for_retry():
    """Transient errors re-raise so EventBridge retries the invocation.

    EventBridge ignores the return payload for async Lambda — it only retries
    when the invocation itself fails. Throttling is transient, so we must let
    the exception propagate rather than swallowing it into a 502.
    """
    mock_ec2 = MagicMock()
    err = _client_error(
        "RequestLimitExceeded",
        "Request limit exceeded.",
        "DescribeInstances",
    )
    mock_ec2.describe_instances.side_effect = err
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            with pytest.raises(ClientError) as exc_info:
                lambda_function.lambda_handler(
                    {"action": "start"}, _make_context()
                )

    assert exc_info.value.response["Error"]["Code"] == "RequestLimitExceeded"


def test_describe_instances_network_error_raises_for_retry():
    """BotoCoreError (connection/DNS/SSL) is always transient — re-raise."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.side_effect = EndpointConnectionError(
        endpoint_url="https://ec2.us-east-1.amazonaws.com"
    )
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            with pytest.raises(EndpointConnectionError):
                lambda_function.lambda_handler(
                    {"action": "stop"}, _make_context()
                )


# ---------------------------------------------------------------------------
# start_instances / stop_instances failures
# ---------------------------------------------------------------------------


def test_start_instances_unauthorized_returns_502():
    """Describe succeeds but StartInstances is denied — still a structured 502."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": SERVER_ID,
                        "InstanceType": "t3.micro",
                        "State": {"Name": "stopped"},
                        "Tags": [{"Key": "Name", "Value": "hl-k3s-server"}],
                    }
                ]
            }
        ]
    }
    mock_ec2.start_instances.side_effect = _client_error(
        "UnauthorizedOperation",
        "You are not authorized to perform this operation.",
        "StartInstances",
    )
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            response = lambda_function.lambda_handler(
                {"action": "start"}, _make_context()
            )

    assert response["statusCode"] == 502
    body = json.loads(response["body"])
    assert body["error"] == "UnauthorizedOperation"
    assert body["operation"] == "start_instances"


def test_stop_instances_incorrect_state_returns_502():
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": AGENT_ID,
                        "InstanceType": "t3.micro",
                        "State": {"Name": "running"},
                        "Tags": [{"Key": "Name", "Value": "hl-k3s-agent"}],
                    }
                ]
            }
        ]
    }
    mock_ec2.stop_instances.side_effect = _client_error(
        "IncorrectInstanceState",
        "The instance is not in a state from which it can be stopped.",
        "StopInstances",
    )
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            response = lambda_function.lambda_handler(
                {"action": "stop"}, _make_context()
            )

    assert response["statusCode"] == 502
    body = json.loads(response["body"])
    assert body["error"] == "IncorrectInstanceState"
    assert body["operation"] == "stop_instances"


def test_start_failure_does_not_call_stop():
    """Regression guard: a failed start must not cascade into a stop attempt."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": SERVER_ID,
                        "InstanceType": "t3.micro",
                        "State": {"Name": "stopped"},
                        "Tags": [],
                    }
                ]
            }
        ]
    }
    mock_ec2.start_instances.side_effect = _client_error(
        "UnauthorizedOperation", "denied", "StartInstances"
    )
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            lambda_function.lambda_handler({"action": "start"}, _make_context())

    mock_ec2.stop_instances.assert_not_called()


def test_start_instances_throttling_raises_for_retry():
    """StartInstances throttling re-raises so EventBridge retries."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": SERVER_ID,
                        "InstanceType": "t3.micro",
                        "State": {"Name": "stopped"},
                        "Tags": [],
                    }
                ]
            }
        ]
    }
    mock_ec2.start_instances.side_effect = _client_error(
        "Throttling", "Rate exceeded", "StartInstances"
    )
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            with pytest.raises(ClientError):
                lambda_function.lambda_handler(
                    {"action": "start"}, _make_context()
                )


def test_stop_instances_network_error_raises_for_retry():
    """StopInstances network error re-raises so EventBridge retries."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": AGENT_ID,
                        "InstanceType": "t3.micro",
                        "State": {"Name": "running"},
                        "Tags": [],
                    }
                ]
            }
        ]
    }
    mock_ec2.stop_instances.side_effect = EndpointConnectionError(
        endpoint_url="https://ec2.us-east-1.amazonaws.com"
    )
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            with pytest.raises(EndpointConnectionError):
                lambda_function.lambda_handler(
                    {"action": "stop"}, _make_context()
                )


# ---------------------------------------------------------------------------
# Empty / partial describe_instances responses
# ---------------------------------------------------------------------------


def test_empty_reservations_returns_200_with_zero_count():
    """If EC2 returns no reservations, status should report 0 instances — not crash."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {"Reservations": []}
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            response = lambda_function.lambda_handler(
                {"action": "status"}, _make_context()
            )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert "0 instance(s)" in body["message"]


def test_start_with_no_instances_found_reports_no_stopped():
    """Two instance IDs requested but describe returns nothing — start is a no-op."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {"Reservations": []}
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            response = lambda_function.lambda_handler(
                {"action": "start"}, _make_context()
            )

    assert response["statusCode"] == 200
    mock_ec2.start_instances.assert_not_called()
    body = json.loads(response["body"])
    assert "No stopped instances" in body["message"]


def test_partial_response_starts_only_returned_instance():
    """If describe returns only 1 of 2 requested IDs, act on what we got.

    Documents current behavior: a missing instance is silently skipped rather
    than failing the whole invocation. That's intentional — one healthy node
    should still be started even if the other ID is stale.
    """
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": SERVER_ID,
                        "InstanceType": "t3.micro",
                        "State": {"Name": "stopped"},
                        "Tags": [],
                    }
                ]
            }
        ]
    }
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            response = lambda_function.lambda_handler(
                {"action": "start"}, _make_context()
            )

    assert response["statusCode"] == 200
    mock_ec2.start_instances.assert_called_once()
    call_args = mock_ec2.start_instances.call_args[1]["InstanceIds"]
    assert call_args == [SERVER_ID]


def test_mixed_reservations_across_multiple_groups():
    """describe_instances can return multiple Reservations, each with multiple
    Instances. The handler must flatten them correctly."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": SERVER_ID,
                        "InstanceType": "t3.micro",
                        "State": {"Name": "stopped"},
                        "Tags": [],
                    }
                ]
            },
            {
                "Instances": [
                    {
                        "InstanceId": AGENT_ID,
                        "InstanceType": "t3.micro",
                        "State": {"Name": "stopped"},
                        "Tags": [],
                    }
                ]
            },
        ]
    }
    with patch.dict(os.environ, ENV):
        with patch.object(lambda_function, "ec2", mock_ec2):
            response = lambda_function.lambda_handler(
                {"action": "start"}, _make_context()
            )

    assert response["statusCode"] == 200
    call_args = mock_ec2.start_instances.call_args[1]["InstanceIds"]
    assert set(call_args) == {SERVER_ID, AGENT_ID}


# ---------------------------------------------------------------------------
# _ec2_error_response helper
# ---------------------------------------------------------------------------


def test_error_response_helper_formats_client_error():
    err = _client_error("Throttling", "Rate exceeded", "DescribeInstances")
    response = lambda_function._ec2_error_response("describe_instances", err)

    assert response["statusCode"] == 502
    assert response["headers"]["Content-Type"] == "application/json"
    body = json.loads(response["body"])
    assert body == {
        "error": "Throttling",
        "message": "Rate exceeded",
        "operation": "describe_instances",
    }


def test_error_response_helper_formats_non_client_error():
    """Non-ClientError exceptions (if ever reached) still get a structured body
    using the exception class name as the error code. Defensive — BotoCoreError
    is normally re-raised via _is_retryable before it reaches this helper."""
    err = EndpointConnectionError(endpoint_url="https://example.invalid")
    response = lambda_function._ec2_error_response("describe_instances", err)

    body = json.loads(response["body"])
    assert body["error"] == "EndpointConnectionError"
    assert body["operation"] == "describe_instances"
    assert "example.invalid" in body["message"]


# ---------------------------------------------------------------------------
# _is_retryable helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "Throttling",
        "ThrottlingException",
        "RequestLimitExceeded",
        "TooManyRequestsException",
        "InternalError",
        "InternalFailure",
        "ServiceUnavailable",
    ],
)
def test_is_retryable_transient_client_errors(code):
    assert lambda_function._is_retryable(
        _client_error(code, "transient", "DescribeInstances")
    )


@pytest.mark.parametrize(
    "code",
    [
        "InvalidInstanceID.NotFound",
        "InvalidInstanceID.Malformed",
        "UnauthorizedOperation",
        "AuthFailure",
        "IncorrectInstanceState",
        "InvalidParameterValue",
    ],
)
def test_is_retryable_permanent_client_errors(code):
    assert not lambda_function._is_retryable(
        _client_error(code, "permanent", "DescribeInstances")
    )


def test_is_retryable_botocore_errors_always_retryable():
    err = EndpointConnectionError(endpoint_url="https://example.invalid")
    assert lambda_function._is_retryable(err)


def test_is_retryable_unrelated_exceptions_not_retryable():
    assert not lambda_function._is_retryable(ValueError("not a boto error"))
