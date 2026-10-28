#!/usr/bin/env bash
# Deploy Trợ lý Tin học AI lên Railway. Chạy: bash deploy.sh [GEMINI_API_KEY]
set -e
cd "$(dirname "$0")"
KEY="${1:-${GEMINI_API_KEY:-$(head -n1 _workspace/.gemini_keys 2>/dev/null)}}"
KEYS="$(grep -v "^$" _workspace/.gemini_keys 2>/dev/null | paste -sd, -)"
[ -n "$KEYS" ] || KEYS="$KEY"
SECRET="$(cat _workspace/.secret_key 2>/dev/null)"; [ ${#SECRET} -ge 32 ] || { SECRET=$(python3 -c "import secrets;print(secrets.token_hex(32))"); printf "%s" "$SECRET" > _workspace/.secret_key; }
SVC=tro-ly-tin-hoc-ai
PIN="$(cat _workspace/.teacher_pin 2>/dev/null)"; [ ${#PIN} -ge 4 ] || { PIN=$(python3 -c "import secrets;print(secrets.randbelow(900000)+100000)"); printf "%s" "$PIN" > _workspace/.teacher_pin; }
railway add --service "$SVC" 2>/dev/null || true
railway service link "$SVC" 2>/dev/null || railway service "$SVC" 2>/dev/null || true
railway variables --set "TRUST_PROXY=1" --set "TEACHER_PIN=$PIN" --set "SECRET_KEY=$SECRET" --set "APP_DATA_DIR=/data" ${KEY:+--set "GEMINI_API_KEY=$KEY"} ${KEYS:+--set "GEMINI_API_KEYS=$KEYS"} --skip-deploys
railway volume add --mount-path /data 2>/dev/null || true
railway up --detach --service "$SVC" --ci || railway up --detach --ci
railway domain
railway status
