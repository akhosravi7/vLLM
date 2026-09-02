# Flatpak, Bazaar, NetworkManager, and Tailscale lockdown

This extension is deliberately connection-safe: it does not activate, modify,
or disconnect a NetworkManager connection. It inventories the live machine,
checks the installed polkit action IDs, and then installs policy under `/etc`.

## Observed before staging

- Flatpak 1.18.1 has one system remote, `flathub`.
- All listed apps and runtimes are system installations. The user installation
  has no listed remote or installed ref, but its directory contains an empty
  OSTree repository, portal databases, and browser overrides. Nothing is
  deleted or migrated.
- Bazaar 0.9.3 is a host RPM at `/usr/bin/bazaar`. Its binary links libflatpak
  and contains both `flatpak_installation_new_system` and
  `flatpak_installation_new_user`, so Bazaar is not assumed to be system-only.
- The installed NetworkManager policy supplies the exact action IDs referenced
  by `50-ali-desktop-lockdown.rules`.
- This restricted inspection environment could not reach the system D-Bus.
  The root installer therefore records live NetworkManager profiles,
  permissions, tailscaled state, preferences, and Serve configuration before
  mutation and fails before mutation if required action IDs are absent.

## Installation

From an authenticated guardian shell, create and inspect a root-owned snapshot:

```bash
sudo install -d -o root -g root -m 0700 /root/vllm-install-staging
sudo cp -a /var/home/ali/vLLM/deploy/. /root/vllm-install-staging/
sudo chown -R root:root /root/vllm-install-staging
sudo find /root/vllm-install-staging -type d -exec chmod go-w {} +
sudo find /root/vllm-install-staging -type f -exec chmod go-w {} +
sudo less /root/vllm-install-staging/README-desktop-lockdown.md
sudo /root/vllm-install-staging/install.sh
```

The main installer invokes `install-desktop-lockdown.sh` from that same
root-owned snapshot. To install only this extension, guardian may instead run:

```bash
sudo /root/vllm-install-staging/install-desktop-lockdown.sh
```

Every existing destination is copied under a timestamped mode-0700 directory
in `/var/backups/vllm-desktop-lockdown/`. Reinstallation is idempotent and
creates a new rollback point. The installer never sources shell configuration
and refuses group/world-writable staging files.

## Installed files and modes

| Path | Owner | Mode |
| --- | --- | --- |
| `/etc/polkit-1/rules.d/50-ali-desktop-lockdown.rules` | `root:root` | `0644` |
| `/etc/NetworkManager/dispatcher.d/pre-up.d/10-block-unapproved-tunnels` | `root:root` | `0755` |
| `/etc/NetworkManager/dispatcher.d/vpn-pre-up.d/10-block-unapproved-tunnels` | `root:root` | `0755` |
| `/etc/vllm/approved-network-tunnel-uuids` | `root:root` | `0644` |
| `/var/home/ali/.local/share/flatpak` | `root:root` | `0755` |
| `/var/home/ali/.local/share/flatpak/repo` (if present) | `root:root` | no group/world write |

The existing `db/` and `overrides/` children remain owned by `ali`, preserving
portal state and per-app overrides. Existing system Flatpaks remain untouched.
All staged sources remain user-owned review copies and are never executed by a
root service.

Tailscale's socket normally remains world-connectable; tailscaled enforces its
Operator internally. The installer sets Operator to `guardian` without running
`tailscale down`, changing routes, or changing Serve configuration.

## Tests as ali (after logout/login)

Use nonexistent examples so tests do not install or disconnect anything:

```bash
flatpak run org.mozilla.firefox
flatpak remote-ls --system --updates
flatpak install --user --noninteractive flathub.invalid invalid.App
flatpak remote-add --user --if-not-exists invalid https://127.0.0.1/invalid.flatpakrepo
touch /tmp/invalid.flatpak /tmp/invalid.flatpakref
flatpak install --user --noninteractive /tmp/invalid.flatpak
flatpak install --user --noninteractive /tmp/invalid.flatpakref
nmcli general permissions
nmcli connection import type openvpn file /tmp/nonexistent.ovpn
nmcli connection add type wireguard ifname wg-lockdown-test con-name wg-lockdown-test
nmcli connection add type vpn con-name vpn-lockdown-test vpn-type openvpn
nmcli connection modify "YOUR_EXISTING_CONNECTION" ipv4.ignore-auto-dns yes ipv4.dns 1.1.1.1
tailscale set --exit-node=100.64.0.1
sudo -n id
/usr/local/bin/vllm-docker/docker ps
vllmctl status
vllmctl logs -n 5
hf --version
git --version
```

The Flatpak user operations must fail at the canonical user repository; system
installs/imports and NetworkManager changes must request guardian credentials
or fail. The Tailscale change, arbitrary sudo, and Docker access must fail.
Do not submit a guardian password while testing as `ali`. Bazaar should display
an administrator authentication prompt for a new system app. Cancel it; a live
install test is intentionally not automated.

## Tests as guardian

```bash
sudo pkaction | grep -E 'org.freedesktop.(Flatpak|NetworkManager)'
sudo nmcli -f NAME,UUID,TYPE,DEVICE connection show
sudo nmcli general permissions
sudo systemctl is-active NetworkManager tailscaled vllm.service vllm-docker.service
sudo tailscale status
sudo tailscale serve status
curl --fail http://127.0.0.1:8000/health
curl --fail https://alibazz.tailf4ff3b.ts.net/health
sudo stat -c '%A %U:%G %n' /etc/polkit-1/rules.d/50-ali-desktop-lockdown.rules \
  /etc/NetworkManager/dispatcher.d/pre-up.d/10-block-unapproved-tunnels \
  /etc/NetworkManager/dispatcher.d/vpn-pre-up.d/10-block-unapproved-tunnels \
  /etc/vllm/approved-network-tunnel-uuids /var/home/ali/.local/share/flatpak \
  /var/home/ali/.local/share/flatpak/repo
sudo visudo -cf /etc/sudoers.d/vllm
```

Compare the current Tailscale Serve output with the pre-change copy in the
latest backup. Do not test the dispatcher by activating a tunnel remotely.

## Rollback

Choose the exact backup produced by the installer, review its `manifest`, then:

```bash
sudo /root/vllm-install-staging/rollback-desktop-lockdown.sh \
  /var/backups/vllm-desktop-lockdown/YYYYMMDD-HHMMSS
```

The rollback moves replaced files into that backup's `rollback-removed/` and
restores originals. It prints the command needed to restore the former
Tailscale Operator; determine the former value from `tailscale-prefs.txt`.
Rollback does not stop NetworkManager, tailscaled, Docker, or vLLM.

## Security boundary and remaining bypasses

Flatpak has no polkit authorization for a per-user repository. Moreover,
Flatpak 1.18 honors the caller-controlled `FLATPAK_USER_DIR` and
`XDG_DATA_HOME`. Root-locking the canonical repository blocks the requested
ordinary `--user`, remote-add, `.flatpak`, `.flatpakref`, and Bazaar paths, but
`ali` can point Flatpak/libflatpak at another writable directory. Preventing
that absolutely requires denying Flatpak/libflatpak execution to `ali` through
a custom SELinux domain or replacing it with a privileged allowlist broker;
either is substantially broader and risks breaking existing GUI app launch.

Likewise, polkit cannot distinguish VPN from Wi-Fi profile contents. Denying
both NetworkManager modify actions means existing Ethernet/Wi-Fi and automatic
DHCP continue, but `ali` needs guardian authentication to join a new Wi-Fi or
change its password. The pre-up dispatcher blocks NetworkManager VPN,
WireGuard, TUN, and IP-tunnel activation unless guardian allowlists a UUID.

This does not stop user-space proxies, browser extensions, SSH SOCKS tunnels,
downloaded binaries/AppImages, containers without Docker, Tor, custom DNS over
HTTPS inside a browser, or a self-contained userspace tunnel. Blocking those
requires egress allowlisting, application control, browser enterprise policy,
and usually a confined user domain—materially reducing normal desktop and
development usability.
