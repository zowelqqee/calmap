#!/bin/sh
# SSH access to this server for an administrator abroad.
#
# Inbound SSH from abroad is cut on the way into Russia, outbound SSH passes. This
# keeps a reverse tunnel: port RELAY_PORT on the server abroad's loopback leads to
# the SSH server of this host (the compose network's gateway). Log in with
#   ssh -J root@<server abroad> -p 2222 root@127.0.0.1
# If the tunnel drops, ssh exits and docker restarts the container.
set -eu
: "${EGRESS_HOST:?set EGRESS_HOST in .env}"
exec ssh -N \
  -R "127.0.0.1:${RELAY_PORT:-2222}:${HOST_GATEWAY:-172.28.0.1}:22" \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  -o UserKnownHostsFile=/state/known_hosts \
  -i /egress_key \
  "${EGRESS_USER:-tunnel}@${EGRESS_HOST}"
