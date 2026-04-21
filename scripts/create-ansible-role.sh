#!/bin/bash
# Create new Ansible role from template scaffold
# Usage: ./scripts/create-ansible-role.sh my_new_role
# Or: make new-role ROLE=my_new_role

set -e

ROLE_NAME=$1

if [ -z "$ROLE_NAME" ]; then
  echo "Usage: $0 <role_name>" >&2
  exit 1
fi

# Validate role name (alphanumeric + underscore only)
if ! echo "$ROLE_NAME" | grep -qE '^[a-zA-Z0-9_]+$'; then
  echo "❌ Invalid role name: '$ROLE_NAME'" >&2
  echo "   Use only alphanumeric characters and underscores" >&2
  exit 1
fi

ROLE_PATH="ansible/roles/$ROLE_NAME"

if [ -d "$ROLE_PATH" ]; then
  echo "❌ Role '$ROLE_NAME' already exists at $ROLE_PATH" >&2
  exit 1
fi

# Copy template
template_path="ansible/roles/.template"
if [ ! -d "$template_path" ]; then
  echo "❌ Template not found at $template_path" >&2
  echo "   Make sure you're running from the repository root" >&2
  exit 1
fi

cp -r "$template_path" "$ROLE_PATH"
echo "✅ Role structure created at $ROLE_PATH"

# Replace [ROLE_NAME] placeholders
echo "🔄 Updating placeholders..."
for file in "$ROLE_PATH/meta/main.yml" "$ROLE_PATH/README.md" "$ROLE_PATH/molecule/default/molecule.yml" "$ROLE_PATH/molecule/default/converge.yml" "$ROLE_PATH/molecule/default/verify.yml"; do
  if [ -f "$file" ]; then
    sed -i "s/\[ROLE_NAME\]/$ROLE_NAME/g" "$file"
  fi
done

echo ""
echo "✅ Role created successfully!"
echo ""
echo "📋 Next steps:"
echo ""
echo "1. Edit your role's defaults:"
echo "   vim $ROLE_PATH/defaults/main.yml"
echo ""
echo "2. Implement the role logic:"
echo "   vim $ROLE_PATH/tasks/main.yml"
echo ""
echo "3. Update Molecule test setup (pre_tasks, stubs, etc):"
echo "   vim $ROLE_PATH/molecule/default/converge.yml"
echo ""
echo "4. Add test assertions:"
echo "   vim $ROLE_PATH/molecule/default/verify.yml"
echo ""
echo "5. Test locally:"
echo "   make test-molecule-$ROLE_NAME"
echo ""
echo "6. Validate structure:"
echo "   make validate-ansible-structure"
echo ""
echo "📚 For more details:"
echo "   - Read: CONTRIBUTING.md"
echo "   - Reference: ansible/roles/tailscale/ (simple) or k3s/ (complex)"
echo "   - Checklist: ansible/roles/.template/.template-checklist.md"
echo ""
