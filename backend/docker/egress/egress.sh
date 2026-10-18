#!/bin/sh
# SOCKS proxy for AI providers through an SSH tunnel to a server abroad.
#
# Plain SOCKS to a foreign server is cut on the way out of Russia; SSH passes and
# is encrypted. ssh -D opens a SOCKS5 proxy on port 1080 inside the compose
# network; the backend uses it as OPENAI_PROXY_URL=socks5://egress:1080. If the
# tunnel drops, ssh exits and docker restarts the container.
set -eu
: "${EGRESS_HOST:?set EGRESS_HOST in .env}"
exec ssh -N \
  -D 0.0.0.0:1080 \
  -o GatewayPorts=yes \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  -o UserKnownHostsFile=/state/known_hosts \
  -i /egress_key \
  "${EGRESS_USER:-tunnel}@${EGRESS_HOST}"
