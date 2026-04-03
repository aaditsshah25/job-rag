#!/bin/bash
# Vercel build script — injects environment variables into config.js
set -e

API_URL="${JOBMATCH_API_URL:-http://localhost:8000}"
API_KEY="${JOBMATCH_API_KEY:-}"
GOOGLE_ID="${GOOGLE_CLIENT_ID:-}"

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
