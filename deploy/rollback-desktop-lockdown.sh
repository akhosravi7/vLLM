#!/usr/bin/bash
set -Eeuo pipefail
umask 077

[[ $(id -u) -eq 0 ]] || { printf 'Run as root.\n' >&2; exit 1; }
[[ $# -eq 1 && -f "$1/manifest" ]] || {
    printf 'Usage: %s /var/backups/vllm-desktop-lockdown/TIMESTAMP\n' "$0" >&2
    exit 1
}
readonly BACKUP_DIR="$(cd -- "$1" && pwd -P)"
while read -r state path; do
    [[ "$path" == /etc/* || "$path" == /var/home/ali/.local/share/flatpak ]] || {
        printf 'Unexpected manifest path: %s\n' "$path" >&2; exit 1;
    }
    if [[ "$state" == present ]]; then
        if [[ -e "$path" || -L "$path" ]]; then
            moved="$BACKUP_DIR/rollback-removed/${path#/}"
            install -d -m 0700 "$(dirname "$moved")"
            mv -- "$path" "$moved"
        fi
        install -d -m 0755 "$(dirname "$path")"
        cp -a -- "$BACKUP_DIR/${path#/}" "$path"
    elif [[ "$state" == absent ]]; then
        if [[ -e "$path" || -L "$path" ]]; then
            moved="$BACKUP_DIR/rollback-removed/${path#/}"
            install -d -m 0700 "$(dirname "$moved")"
            mv -- "$path" "$moved"
        fi
    else
        printf 'Invalid manifest entry.\n' >&2; exit 1
    fi
done <"$BACKUP_DIR/manifest"
systemctl try-reload-or-restart polkit.service || true
printf 'Files restored. Review %s/tailscale-prefs.txt and restore the former Operator with:\n' "$BACKUP_DIR"
printf '  tailscale set --operator=FORMER_OPERATOR\n'
