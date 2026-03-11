#!/bin/sh
# Copy SSH key to /tmp (container writable layer, not a k8s volume).
# fsGroup only applies to k8s-managed volumes, so chmod 400 here is permanent.
mkdir -p /tmp/.ssh
cp /ssh-secret/id_ed25519 /tmp/.ssh/id_ed25519
chmod 400 /tmp/.ssh/id_ed25519
export GIT_SSH_COMMAND="ssh -i /tmp/.ssh/id_ed25519 -o StrictHostKeyChecking=no"

# The ConfigMap mount creates symlinks in config/ where git expects regular files.
# Mark them as assume-unchanged so git pull --rebase doesn't refuse to run.
git update-index --assume-unchanged config/sources.yaml config/topics.yaml 2>/dev/null || true

exec python main.py "$@"
