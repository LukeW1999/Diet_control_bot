#!/usr/bin/env bash
# Deploy /opt/health-bot from GitHub.
#
# Restarts BOTH services on purpose. They share this one checkout, so updating the
# code without restarting each of them leaves a process serving stale logic against
# live data — which is how a gunicorn from 17 days earlier kept overwriting the
# daily summary with Apple's resting energy while every visible number stayed
# plausible. Restarting only the one you were thinking about is the failure mode.
set -euo pipefail

REPO=/opt/health-bot
SERVICES=(health-bot health-bot-wecom)

cd "$REPO"

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "refusing to deploy: working tree has uncommitted changes" >&2
    git status --short >&2
    echo "commit them, or 'git reset --hard origin/main' to discard" >&2
    exit 1
fi

before=$(git rev-parse --short HEAD)
git fetch --quiet origin
# ff-only: a deploy should never invent a merge commit on the server.
git merge --ff-only --quiet origin/main
after=$(git rev-parse --short HEAD)

# Idempotent: each migration checks for its column before adding it.
venv/bin/python scripts/migrate_refeed.py

systemctl restart "${SERVICES[@]}"
sleep 3

for svc in "${SERVICES[@]}"; do
    if ! systemctl is-active --quiet "$svc"; then
        echo "FAILED: $svc did not come back up" >&2
        journalctl -u "$svc" -n 25 --no-pager >&2
        exit 1
    fi
done

if [ "$before" = "$after" ]; then
    echo "already at $after, services restarted"
else
    echo "deployed $before -> $after"
fi
echo "  $(git log -1 --format='%s')"
for svc in "${SERVICES[@]}"; do
    printf '  %-18s up since %s\n' "$svc" \
        "$(systemctl show -p ActiveEnterTimestamp --value "$svc")"
done
