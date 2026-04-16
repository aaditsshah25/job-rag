#!/bin/bash
# Vercel build script — injects environment variables into config.js
set -e

API_URL="$(echo "${JOBMATCH_API_URL:-http://localhost:8000}" | tr -d '[:space:]')"
API_KEY="$(echo "${JOBMATCH_API_KEY:-}" | tr -d '[:space:]')"
GOOGLE_ID="$(echo "${GOOGLE_CLIENT_ID:-}" | tr -d '[:space:]')"

cat > config.js <<EOF
// JobMatch AI — Runtime Configuration (generated at build time)
const CONFIG = {
  API_BASE_URL: '${API_URL}',
  API_KEY: '${API_KEY}',
  GOOGLE_CLIENT_ID: '${GOOGLE_ID}',
};
EOF

echo "config.js generated:"
cat config.js
