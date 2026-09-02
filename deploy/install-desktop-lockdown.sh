#!/usr/bin/bash
set -Eeuo pipefail
umask 077

[[ $(id -u) -eq 0 ]] || { printf 'Run from reviewed root-owned staging as root.\n' >&2; exit 1; }
readonly SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly TARGET_USER=ali
readonly GUARDIAN_USER=guardian
readonly STAMP="$(date +%Y%m%d-%H%M%S)"
readonly BACKUP_DIR="/var/backups/vllm-desktop-lockdown/$STAMP"
readonly MANIFEST="$BACKUP_DIR/manifest"

[[ $(stat -c %U "$SOURCE_DIR") == root ]] || { printf 'Staging directory is not root-owned: %s\n' "$SOURCE_DIR" >&2; exit 1; }
find "$SOURCE_DIR" -xdev -type f -perm /022 -print -quit | grep -q . && {
    printf 'A staging file is group/world writable; refusing.\n' >&2; exit 1;
}
id "$TARGET_USER" >/dev/null
id "$GUARDIAN_USER" >/dev/null

required_actions=(
 org.freedesktop.NetworkManager.network-control
 org.freedesktop.NetworkManager.settings.modify.own
 org.freedesktop.NetworkManager.settings.modify.system
 org.freedesktop.NetworkManager.settings.modify.global-dns
 org.freedesktop.Flatpak.app-install org.freedesktop.Flatpak.app-update
 org.freedesktop.Flatpak.install-bundle org.freedesktop.Flatpak.configure-remote
)
available="$(pkaction)"
for action in "${required_actions[@]}"; do
    grep -Fxq "$action" <<<"$available" || { printf 'Missing polkit action: %s\n' "$action" >&2; exit 1; }
done
command -v flatpak nmcli tailscale >/dev/null

install -d -o root -g root -m 0700 "$BACKUP_DIR"
: >"$MANIFEST"
backup() {
    local path=$1 rel=${1#/}
    if [[ -e "$path" || -L "$path" ]]; then
        install -d -m 0700 "$BACKUP_DIR/$(dirname "$rel")"
        cp -a -- "$path" "$BACKUP_DIR/$rel"
        printf 'present %s\n' "$path" >>"$MANIFEST"
    else
        printf 'absent %s\n' "$path" >>"$MANIFEST"
    fi
}
put() { local mode=$1 src=$2 dst=$3; backup "$dst"; install -o root -g root -m "$mode" "$src" "$dst"; }

# Evidence is captured before mutation. No app, remote, or profile is deleted.
flatpak remotes --system --show-details >"$BACKUP_DIR/flatpak-remotes-system.txt"
runuser -u "$TARGET_USER" -- flatpak remotes --user --show-details >"$BACKUP_DIR/flatpak-remotes-user.txt"
flatpak list --system --columns=application,ref,origin,installation >"$BACKUP_DIR/flatpak-list-system.txt"
runuser -u "$TARGET_USER" -- flatpak list --user --columns=application,ref,origin,installation >"$BACKUP_DIR/flatpak-list-user.txt"
nmcli -f NAME,UUID,TYPE,DEVICE connection show >"$BACKUP_DIR/nm-connections.txt"
nmcli general permissions >"$BACKUP_DIR/nm-permissions-before.txt"
systemctl status tailscaled --no-pager >"$BACKUP_DIR/tailscaled-status.txt" || true
tailscale status >"$BACKUP_DIR/tailscale-status.txt" || true
tailscale serve status >"$BACKUP_DIR/tailscale-serve-status.txt" || true
tailscale debug prefs >"$BACKUP_DIR/tailscale-prefs.txt" || true

install -d -o root -g root -m 0755 /etc/vllm /etc/polkit-1/rules.d \
    /etc/NetworkManager/dispatcher.d/pre-up.d /etc/NetworkManager/dispatcher.d/vpn-pre-up.d
put 0644 "$SOURCE_DIR/50-ali-desktop-lockdown.rules" /etc/polkit-1/rules.d/50-ali-desktop-lockdown.rules
put 0755 "$SOURCE_DIR/10-block-unapproved-tunnels" /etc/NetworkManager/dispatcher.d/pre-up.d/10-block-unapproved-tunnels
put 0755 "$SOURCE_DIR/10-block-unapproved-tunnels" /etc/NetworkManager/dispatcher.d/vpn-pre-up.d/10-block-unapproved-tunnels
put 0644 "$SOURCE_DIR/approved-network-tunnel-uuids" /etc/vllm/approved-network-tunnel-uuids

# There are currently no user apps/remotes. Preserve the tree as evidence and
# make the canonical user installation non-writable. See documentation for the
# unavoidable FLATPAK_USER_DIR limitation.
user_flatpak="$(getent passwd "$TARGET_USER" | cut -d: -f6)/.local/share/flatpak"
backup "$user_flatpak"
install -d -o root -g root -m 0755 "$user_flatpak"
if [[ -e "$user_flatpak/repo" ]]; then
    chown -R root:root "$user_flatpak/repo"
    find "$user_flatpak/repo" -xdev -type d -exec chmod go-w {} +
    find "$user_flatpak/repo" -xdev -type f -exec chmod go-w {} +
fi

# Tailscaled's local API socket is intentionally world-accessible; Operator is
# its authorization boundary. This preserves routes, login, and Serve config.
tailscale set --operator="$GUARDIAN_USER"

systemctl try-reload-or-restart polkit.service || true
printf 'Installed desktop lockdown. Backup and pre-change evidence: %s\n' "$BACKUP_DIR"
printf 'Log out/in ali before interactive authorization tests. No network profile was activated or disconnected.\n'
