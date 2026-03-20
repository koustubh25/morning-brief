#!/bin/sh
# Copy SSH key to /tmp (container writable layer, not a k8s volume).
# fsGroup only applies to k8s-managed volumes, so chmod 400 here is permanent.
mkdir -p /tmp/.ssh
cp /ssh-secret/id_ed25519 /tmp/.ssh/id_ed25519
chmod 400 /tmp/.ssh/id_ed25519
export GIT_SSH_COMMAND="ssh -i /tmp/.ssh/id_ed25519 -o StrictHostKeyChecking=no"

# The ConfigMap mount replaces config/ with symlinks, and output/archive are
# tracked but absent from the image.  Reset tracked files and index so
# pull --rebase works.  Do NOT git clean (would delete gmail.py if untracked).
git reset --hard HEAD 2>/dev/null || true

# Mark ConfigMap symlinks as assume-unchanged so they don't block pull/rebase.
git update-index --assume-unchanged config/sources.yaml config/topics.yaml 2>/dev/null || true

# The ConfigMap mount may leave config/ dirty in the index.  Explicitly
# reset the index for those paths after assume-unchanged.
git checkout -- output/ archive/ 2>/dev/null || true

exec python main.py "$@"
