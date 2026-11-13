#!/bin/sh
# Let's Encrypt certificate through the DNS-01 challenge at REG.RU (lego).
#
# For servers that Let's Encrypt cannot reach over HTTP from abroad: the domain is
# proved by a TXT record that lego writes through the REG.RU API, so no inbound
# connection is needed. Renewal is checked twice a day; a certificate with fewer
# than 30 days left is renewed and Caddy picks it up (docker/caddy-run.sh).
set -eu
: "${DOMAIN:?set DOMAIN in .env}"
: "${LEGO_EMAIL:?set LEGAL_CONTACT_EMAIL in .env}"

# The release image keeps the binary at /lego; source builds put it in PATH.
LEGO=$(command -v lego || echo /lego)

set -- --accept-tos --email "$LEGO_EMAIL" --dns regru --domains "$DOMAIN" --path /certs
if [ -n "${ACME_SERVER:-}" ]; then
  set -- "$@" --server "$ACME_SERVER"
fi

if [ -z "${REGRU_USERNAME:-}" ] || [ -z "${REGRU_PASSWORD:-}" ]; then
  # Manual mode: the server cannot reach the REG.RU API, so the TXT record is
  # added by hand (RELEASE.md, "Сертификат через DNS вручную"). This service only
  # waits for the certificate file and reminds about renewal.
  until [ -s "/certs/certificates/$DOMAIN.crt" ]; do
    echo "no certificate yet: obtain it by hand (RELEASE.md, «Сертификат через DNS вручную»)"
    sleep 300
  done
  while true; do
    echo "manual certificates: renew by hand within 60 days of $(date -r "/certs/certificates/$DOMAIN.crt" +%Y-%m-%d)"
    sleep 86400
  done
fi

if [ ! -s "/certs/certificates/$DOMAIN.crt" ]; then
  echo "obtaining a certificate for $DOMAIN through REG.RU DNS..."
  until "$LEGO" "$@" run; do
    echo "certificate request failed; retrying in 15 minutes" >&2
    sleep 900
  done
fi
echo "certificate for $DOMAIN is in place"
while true; do
  sleep 43200
  "$LEGO" "$@" renew --days 30 || echo "renewal failed; next attempt in 12 hours" >&2
done
