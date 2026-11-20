#!/bin/sh
# Lecture Grafana via op run (secrets jamais affichés). Usage: gq.sh METHOD PATH [DATA]
# Env injectés par op run : GF_TOKEN, CF_ID, CF_SECRET
M="$1"; P="$2"; D="$3"
set -- -s --max-time 20 -X "$M" "${GRAFANA_URL:?GRAFANA_URL non défini (ex. https://grafana.example.com)}$P" \
  -H "Authorization: Bearer $GF_TOKEN" -H "CF-Access-Client-Id: $CF_ID" -H "CF-Access-Client-Secret: $CF_SECRET" \
  -w '\nHTTP %{http_code}\n'
if [ -n "$D" ]; then curl "$@" -H "Content-Type: application/json" --data "$D"; else curl "$@"; fi
