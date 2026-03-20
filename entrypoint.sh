#!/bin/sh
# Copy SSH key to /tmp (container writable layer, not a k8s volume).
# fsGroup only applies to k8s-managed volumes, so chmod 400 here is permanent.
mkdir -p /tmp/.ssh
cp /ssh-secret/id_ed25519 /tmp/.ssh/id_ed25519
chmod 400 /tmp/.ssh/id_ed25519
export GIT_SSH_COMMAND="ssh -i /tmp/.ssh/id_ed25519 -o StrictHostKeyChecking=no"

# Remove any LFS hooks left over from previous images.
rm -f .git/hooks/pre-push .git/hooks/post-checkout .git/hooks/post-commit .git/hooks/post-merge 2>/dev/null

# Fetch latest code from remote and hard-reset to it.
# This ensures the container always runs the latest committed code,
# even if the Docker image is stale.
git fetch origin main 2>/dev/null || true
git reset --hard origin/main 2>/dev/null || git reset --hard HEAD 2>/dev/null || true

# Mark ConfigMap symlinks as assume-unchanged so they don't block pull/rebase.
git update-index --assume-unchanged config/sources.yaml config/topics.yaml 2>/dev/null || true

exec python main.py "$@"
