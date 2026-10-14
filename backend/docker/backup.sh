#!/bin/sh
# Daily compressed pg_dump into /backups, keeping BACKUP_KEEP_DAYS days.
set -eu
while true; do
  stamp=$(date +%Y%m%d-%H%M%S)
  if pg_dump --format=custom --file="/backups/calmap-$stamp.dump"; then
    echo "backup written: calmap-$stamp.dump"
  else
    echo "backup FAILED at $stamp" >&2
    rm -f "/backups/calmap-$stamp.dump"
  fi
  find /backups -name 'calmap-*.dump' -mtime +"${BACKUP_KEEP_DAYS:-14}" -delete
  sleep 86400
done
