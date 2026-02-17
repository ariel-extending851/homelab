#!/bin/bash
git pull origin main
mise install
terraform init -upgrade
# Lista os PRs abertos pelo Jules
gh pr list --author "google-jules"
