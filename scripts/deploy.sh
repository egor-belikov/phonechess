#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REMOTE_HOST="${DEPLOY_HOST:-egorvps}"
REMOTE_DIR="${DEPLOY_DIR:-/root/my_projects/phonechess}"
BRANCH="${DEPLOY_BRANCH:-main}"
COMMIT_MSG="${1:-Deploy: update build and release latest changes}"

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
  if [ -f scripts/update_build_meta.py ]; then python3 scripts/update_build_meta.py; fi; \
  docker compose build app; \
  docker compose up -d app; \
  echo 'HEALTH:'; ok=0; \
  for i in 1 2 3 4 5 6 7 8 9 10; do if curl -fsS http://127.0.0.1:8000/health; then ok=1; break; fi; sleep 2; done; echo; \
  if [ \"\$ok\" != 1 ]; then echo 'HEALTH CHECK FAILED'; exit 1; fi; \
  echo 'BUILD_META:'; curl -sS http://127.0.0.1:8000/build-meta.json; echo"

echo "==> Done"
