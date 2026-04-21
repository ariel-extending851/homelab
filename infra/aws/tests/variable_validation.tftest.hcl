# Tests for variable validation rules in the root AWS module.
# Runs with mocked providers — no real AWS calls.

mock_provider "aws" {}
mock_provider "sops" {}
mock_provider "tailscale" {}

# ── server_instance_type ──────────────────────────────────────────────────────

run "valid_server_instance_types" {
  variables {
    localstack_test      = "yes"
    server_instance_type = "t3.small"
    agent_instance_type  = "t3.micro"
  }
  command = plan
}

run "invalid_server_instance_type_rejected" {
  variables {
    localstack_test      = "yes"
    server_instance_type = "t3.large"
  }
  command         = plan
  expect_failures = [var.server_instance_type]
}

run "invalid_agent_instance_type_rejected" {
  variables {
    localstack_test     = "yes"
    agent_instance_type = "m5.xlarge"
  }
  command         = plan
  expect_failures = [var.agent_instance_type]
}

# ── ebs_volume_size ───────────────────────────────────────────────────────────

run "ebs_minimum_boundary_accepted" {
  variables {
    localstack_test = "yes"
    ebs_volume_size = 30
  }
  command = plan
}

run "ebs_below_minimum_rejected" {
  variables {
    localstack_test = "yes"
    ebs_volume_size = 10
  }
  command         = plan
  expect_failures = [var.ebs_volume_size]
}

run "ebs_above_maximum_rejected" {
  variables {
    localstack_test = "yes"
    ebs_volume_size = 200
  }
  command         = plan
  expect_failures = [var.ebs_volume_size]
}

# ── k3s_version ───────────────────────────────────────────────────────────────

run "valid_k3s_version_accepted" {
  variables {
    localstack_test = "yes"
    k3s_version     = "v1.28.5+k3s1"
  }
  command = plan
}

run "invalid_k3s_version_missing_prefix_rejected" {
  variables {
    localstack_test = "yes"
    k3s_version     = "1.28.5+k3s1"
  }
  command         = plan
  expect_failures = [var.k3s_version]
}

run "invalid_k3s_version_no_k3s_suffix_rejected" {
  variables {
    localstack_test = "yes"
    k3s_version     = "v1.28.5"
  }
  command         = plan
  expect_failures = [var.k3s_version]
}

# ── schedule_hours ────────────────────────────────────────────────────────────

run "schedule_hour_23_accepted" {
  variables {
    localstack_test     = "yes"
    schedule_start_hour = 0
    schedule_stop_hour  = 23
  }
  command = plan
}

run "schedule_start_hour_24_rejected" {
  variables {
    localstack_test     = "yes"
    schedule_start_hour = 24
  }
  command         = plan
  expect_failures = [var.schedule_start_hour]
}

run "schedule_stop_hour_negative_rejected" {
  variables {
    localstack_test    = "yes"
    schedule_stop_hour = -1
  }
  command         = plan
  expect_failures = [var.schedule_stop_hour]
}

# ── localstack_test ───────────────────────────────────────────────────────────

run "localstack_invalid_value_rejected" {
  variables {
    localstack_test = "maybe"
  }
  command         = plan
  expect_failures = [var.localstack_test]
}
