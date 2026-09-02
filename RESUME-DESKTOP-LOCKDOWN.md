# Resume: Flatpak, NetworkManager, and Tailscale lockdown

Updated: 2026-09-02, America/Chicago

## Current state

The desktop/network lockdown was installed successfully by `guardian` from the
root-owned staging directory:

```text
/root/vllm-install-staging
```

The installation backup and pre-change evidence are here:

```text
/var/backups/vllm-desktop-lockdown/20260902-180519
```

Guardian verification already passed:

- `NetworkManager`, `tailscaled`, `vllm.service`, and
  `vllm-docker.service` were all active.
- Tailscale contained both expected devices.
- Tailscale Serve remained configured as:

  ```text
  https://alibazz.tailf4ff3b.ts.net (tailnet only)
  |-- / proxy http://127.0.0.1:8000
  ```

- Both local and Tailscale vLLM health requests succeeded.
- The installed policy, both dispatcher hooks, allowlist, and canonical user
  Flatpak repository were all `root:root` with the intended modes.
- No NetworkManager profile was activated, changed, or disconnected by the
  installer.

## Resume procedure

Completely log out, log back in as `ali`, open this file, and run the following
tests. Do not enter the guardian password while testing as `ali`; cancel any
administrator authentication prompt.

### Confirm permitted functions

```bash
id
flatpak run org.mozilla.firefox
hf --version
git --version
vllmctl status
vllmctl logs -n 5
curl --fail --show-error http://127.0.0.1:8000/health
curl --fail --show-error https://alibazz.tailf4ff3b.ts.net/health
```

Firefox should launch, CLI commands should work, and both health requests
should succeed. The health endpoints normally return an empty response body.

### Confirm Flatpak restrictions

```bash
flatpak remote-add --user --if-not-exists invalid \
  https://127.0.0.1/invalid.flatpakrepo

flatpak install --user --noninteractive flathub.invalid invalid.App
```

Both must fail. The first should fail because the canonical user repository is
not writable. No existing system Flatpak should be removed or changed.

Open Bazaar and select a new application only far enough to initiate an
installation. A system installation must request administrator authentication;
cancel the prompt. Do not complete an installation merely for testing.

### Confirm NetworkManager restrictions

These commands create only proposed test profiles and must fail or request
guardian authentication:

```bash
nmcli general permissions

nmcli connection add type wireguard \
  ifname wg-lockdown-test con-name wg-lockdown-test

nmcli connection add type vpn \
  con-name vpn-lockdown-test vpn-type openvpn
```

Cancel authentication prompts. Verify afterward that neither test profile was
created:

```bash
nmcli -t -f NAME,TYPE connection show | grep -E '^wg-lockdown-test:|^vpn-lockdown-test:'
```

No output is expected.

Do not modify or activate a real network profile during this test. The DNS
modification test is intentionally deferred because it is unnecessary while
validating remotely or without a second recovery connection.

### Confirm Tailscale, sudo, and Docker restrictions

```bash
tailscale set --exit-node=100.64.0.1
sudo -n id
/usr/local/bin/vllm-docker/docker ps
```

All three must fail. Then confirm Tailscale Serve and vLLM still work:

```bash
tailscale status
tailscale serve status
curl --fail --show-error http://127.0.0.1:8000/health
curl --fail --show-error https://alibazz.tailf4ff3b.ts.net/health
```

## Reporting results

In the next Codex session, say:

```text
Resume from RESUME-DESKTOP-LOCKDOWN.md. The lockdown is installed; help me
review the ali-account validation output without changing live networking.
```

Paste the outputs from the permitted and negative tests. Authentication
requests that are cancelled count as successful restrictions.

## Rollback reference

Rollback is not currently needed. If normal desktop, Flatpak launch, Tailscale
Serve, or vLLM functionality is broken, sign in as `guardian`, inspect the
manifest, and run:

```bash
sudo less /var/backups/vllm-desktop-lockdown/20260902-180519/manifest
sudo /root/vllm-install-staging/rollback-desktop-lockdown.sh \
  /var/backups/vllm-desktop-lockdown/20260902-180519
```

The rollback script restores files and prints instructions for restoring the
former Tailscale Operator from the saved preferences. It does not stop
NetworkManager, Tailscale, Docker, or vLLM.

## Known limitation

Flatpak has no polkit action for a per-user installation. The canonical user
repository is locked, but a technically capable user can select a different
writable repository using `FLATPAK_USER_DIR` or `XDG_DATA_HOME`. Fully blocking
that requires broader SELinux/application confinement or a privileged Flatpak
broker and was not enabled because of the desktop compatibility risk.
