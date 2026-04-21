# [ROLE_NAME] Role

Brief description of what this role does.

## Requirements

- Ansible >= 2.12
- (List any external requirements: specific packages, services, etc.)

## Role Variables

- `example_variable` (default: "default_value") — Description of what this does

## Example Playbook

```yaml
- hosts: servers
  roles:
    - role: [ROLE_NAME]
      vars:
        example_variable: "custom_value"
```

## Testing

Run Molecule tests locally:
```bash
cd ansible/roles/[ROLE_NAME]
molecule test
```

See `ansible/TESTING.md` for detailed testing guide.
