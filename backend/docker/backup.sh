#!/bin/sh
# Daily compressed pg_dump into /backups, keeping BACKUP_KEEP_DAYS days.
# Dumps hold personal data: files are readable by their owner only, and with
# BACKUP_PASSPHRASE set they are encrypted (AES-256-CBC, PBKDF2) — restore with
#   openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in calmap-X.dump.enc -out calmap-X.dump
set -eu
umask 077
if [ -n "${BACKUP_PASSPHRASE:-}" ] && ! command -v openssl >/dev/null 2>&1; then
  apk add --no-cache openssl >/dev/null
fi
while true; do
  stamp=$(date +%Y%m%d-%H%M%S)
  file="/backups/calmap-$stamp.dump"
  if pg_dump --format=custom --file="$file"; then
    if [ -n "${BACKUP_PASSPHRASE:-}" ]; then
      if openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
          -pass env:BACKUP_PASSPHRASE -in "$file" -out "$file.enc"; then
        rm -f "$file"
        file="$file.enc"
      else
        echo "backup encryption FAILED at $stamp" >&2
        rm -f "$file" "$file.enc"
        sleep 3600
        continue
      fi
    fi
    echo "backup written: $(basename "$file")"
  else
    echo "backup FAILED at $stamp" >&2
    rm -f "$file"
  fi
  find /backups -name 'calmap-*.dump*' -mtime +"${BACKUP_KEEP_DAYS:-14}" -delete
  sleep 86400
done
