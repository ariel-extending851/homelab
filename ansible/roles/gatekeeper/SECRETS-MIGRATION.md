# Gatekeeper Wi-Fi Password Secret Migration (SOPS)

Use this after initial gatekeeper validation is complete.

## Goal
Move `wifi_password` out of role defaults and into an encrypted Ansible group variable file for the `router` group.

## Prerequisites
- SOPS installed on your workstation.
- Age key available at `~/.config/sops/age/keys.txt`.
- Run commands from repository root (`/workspaces/homelab`).

## Steps
1. Create the router secret file from the example:

   ```bash
   cp ansible/group_vars/router.sops.yaml.example ansible/group_vars/router.sops.yml
   ```

2. Encrypt the file in place:

   ```bash
   sops --encrypt --in-place ansible/group_vars/router.sops.yml
   ```

3. Edit safely in SOPS (keeps encrypted-at-rest on disk):

   ```bash
   sops ansible/group_vars/router.sops.yml
   ```

4. Confirm Ansible can read inventory (without printing secrets):

   ```bash
   cd ansible
   ansible-inventory -i inventory/production.yml --graph
   ```

5. Run the gatekeeper playbook against the router group.

## Notes
- `wifi_password` in `roles/gatekeeper/defaults/main.yml` is a test fallback only.
- Variable precedence ensures `group_vars/router.sops.yml` overrides role defaults for hosts in `router`.
- `.sops.yaml` now includes an Ansible rule for `ansible/group_vars/*.sops.yaml` and encrypts the `wifi_password` key.
