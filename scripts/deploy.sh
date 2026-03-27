#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REMOTE_HOST="${DEPLOY_HOST:-egorvps}"
REMOTE_DIR="${DEPLOY_DIR:-/root/my_projects/phonechess}"
BRANCH="${DEPLOY_BRANCH:-main}"
COMMIT_MSG="${1:-Deploy: update build and release latest changes}"

echo "==> Updating build metadata"
python3 scripts/update_build_meta.py

echo "==> Creating commit (if needed)"
git add -A
if git diff --cached --quiet; then
  echo "No changes to commit."
else
  git -c alias.commit= commit -m "$COMMIT_MSG"
fi

echo "==> Pushing branch $BRANCH"
git push origin "$BRANCH"

echo "==> Deploying on $REMOTE_HOST:$REMOTE_DIR"
ssh "$REMOTE_HOST" "set -euo pipefail; \
  cd '$REMOTE_DIR'; \
  git stash push -u -m 'auto-deploy-pre-sync' >/dev/null 2>&1 || true; \
  git pull --ff-only origin '$BRANCH'; \
  docker compose build app; \
  docker compose up -d app; \
  sleep 2; \
  echo 'HEALTH:'; curl -sS http://127.0.0.1:8000/health; echo; \
  echo 'BUILD_META:'; curl -sS http://127.0.0.1:8000/build-meta.json; echo"

echo "==> Done"
