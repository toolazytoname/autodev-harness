#!/bin/bash
# init-project.sh - Project Initialization
set -euo pipefail
log() { echo "[INIT] $*"; }
TYPE="${1:-fullstack}"
NAME="${2:-my-project}"
log "Initializing $TYPE project: $NAME"
mkdir -p "$NAME" && cd "$NAME"
case "$TYPE" in
  fullstack) npx create-next-app@latest . --typescript --tailwind --app --no-src-dir --import-alias "@/*" --yes 2>/dev/null || npm init -y ;;
  frontend) npx create-next-app@latest . --typescript --tailwind --app --no-src-dir --yes 2>/dev/null || npm init -y ;;
  api) npm init -y && npm install express cors && mkdir -p src/routes src/middleware ;;
  library) npm init -y && npm install -D typescript @types/node ;;
esac
npm pkg set scripts.dev="npm run dev" scripts.build="npm run build" scripts.lint="npm run lint" scripts.test="npm test"
git init
log "Done: cd $NAME && npm run dev"
