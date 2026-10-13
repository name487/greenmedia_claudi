#!/usr/bin/env bash
# End-to-end: real API + real Django site in a real browser; Google, Meta and OpenAI are fakes.
#   cd e2e && npm install && ./run.sh            (needs the backend + web Python deps installed)
set -euo pipefail
cd "$(dirname "$0")"
export E2E_API_PORT=${E2E_API_PORT:-8001} E2E_WEB_PORT=${E2E_WEB_PORT:-8000} E2E_FAKE_PORT=${E2E_FAKE_PORT:-8099}
export E2E_WEB_URL="http://127.0.0.1:${E2E_WEB_PORT}"
mkdir -p artifacts
python fake_api.py > artifacts/api.log 2>&1 &
API=$!
(cd ../web && API_URL="http://127.0.0.1:${E2E_API_PORT}" exec python manage.py runserver "${E2E_WEB_PORT}" --noreload > ../e2e/artifacts/web.log 2>&1) &
WEB=$!
trap 'kill $API $WEB 2>/dev/null || true' EXIT
for i in $(seq 1 60); do
  curl -sf "http://127.0.0.1:${E2E_API_PORT}/api/health" >/dev/null && curl -sf "${E2E_WEB_URL}/login/" >/dev/null && break
  sleep 1
done
node full-flow.mjs
