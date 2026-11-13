#!/bin/sh
# Fallback address of the API through the server abroad.
#
# Part of the networks abroad cannot open HTTPS connections to this server: they
# are cut on the way into Russia, like inbound SSH (relay.sh). Outbound SSH passes,
# so this keeps a reverse tunnel: ports on the server abroad's loopback lead to
# Caddy here, and HAProxy there (docker/egress/haproxy.cfg) exposes them as ports
# 443 and 80 of FALLBACK_DOMAIN. TLS is not terminated abroad. If the tunnel
# drops, ssh exits and docker restarts the container.
set -eu
: "${EGRESS_HOST:?set EGRESS_HOST in .env}"
exec ssh -N \
  -R "127.0.0.1:${EDGE_HTTPS_PORT:-8443}:caddy:8443" \
  -R "127.0.0.1:${EDGE_HTTP_PORT:-8080}:caddy:80" \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  -o UserKnownHostsFile=/state/known_hosts \
  -i /egress_key \
  "${EGRESS_USER:-tunnel}@${EGRESS_HOST}"
