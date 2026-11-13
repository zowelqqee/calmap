#!/bin/sh
# Caddy with certificates from files (docker-compose.dns-certs.yml): reload the
# configuration when the certs service renews the certificate, since Caddy does
# not watch certificate files itself.
set -u
CERT="/certs/certificates/$DOMAIN.crt"
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile &
pid=$!
seen=$(stat -c %Y "$CERT" 2>/dev/null || echo 0)
while kill -0 "$pid" 2>/dev/null; do
  sleep 300
  now=$(stat -c %Y "$CERT" 2>/dev/null || echo 0)
  if [ "$now" != "$seen" ]; then
    echo "certificate changed; reloading Caddy"
    caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile && seen=$now
  fi
done
wait "$pid"
