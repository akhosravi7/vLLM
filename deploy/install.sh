#!/usr/bin/bash
set -Eeuo pipefail

if [[ $(id -u) -ne 0 ]]; then
  printf 'Run this reviewed installer as root.\n' >&2
  exit 1
fi

readonly SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly PROJECT_DIR=/var/home/ali/vLLM
readonly STAMP="$(date +%Y%m%d-%H%M%S)"
readonly BACKUP_DIR="/var/backups/vllm/$STAMP"

backup_if_present() {
  local destination=$1 relative
  if [[ -e "$destination" || -L "$destination" ]]; then
    relative=${destination#/}
    /usr/bin/install -d -m 0700 "$BACKUP_DIR/$(dirname "$relative")"
    /usr/bin/cp -a -- "$destination" "$BACKUP_DIR/$relative"
  fi
}

install_root_file() {
  local mode=$1 source=$2 destination=$3
  backup_if_present "$destination"
  /usr/bin/install -o root -g root -m "$mode" "$source" "$destination"
}

for required in \
  "$SOURCE_DIR/compose.yaml" \
  "$SOURCE_DIR/validate-config.py" \
  "$SOURCE_DIR/vllm.service" \
  "$SOURCE_DIR/vllm-docker.service" \
  "$SOURCE_DIR/vllm.sudoers" \
  "$SOURCE_DIR/vllmctl" \
  "$SOURCE_DIR/vllm.logrotate" \
  "$SOURCE_DIR/patch-runc-rpath.py" \
  /home/linuxbrew/.linuxbrew/bin/docker \
  /home/linuxbrew/.linuxbrew/bin/docker-compose \
  /home/linuxbrew/.linuxbrew/opt/docker-engine/bin/dockerd \
  /home/linuxbrew/.linuxbrew/opt/docker-engine/bin/docker-proxy \
  /home/linuxbrew/.linuxbrew/bin/containerd \
  /home/linuxbrew/.linuxbrew/bin/containerd-shim-runc-v2 \
  /home/linuxbrew/.linuxbrew/bin/ctr \
  /home/linuxbrew/.linuxbrew/bin/docker-init \
  /home/linuxbrew/.linuxbrew/sbin/runc \
  /home/linuxbrew/.linuxbrew/opt/libseccomp/lib/libseccomp.so.2 \
  /home/linuxbrew/.linuxbrew/opt/libpathrs/lib/libpathrs.so.0; do
  [[ -x "$required" || -r "$required" ]] || { printf 'Missing prerequisite: %s\n' "$required" >&2; exit 1; }
done

[[ $(stat -c %u "$PROJECT_DIR/vllm.env") -eq 1000 ]] || {
  printf '%s must be owned by uid 1000 (ali).\n' "$PROJECT_DIR/vllm.env" >&2
  exit 1
}
/usr/bin/chmod 0600 "$PROJECT_DIR/vllm.env"

/usr/bin/install -d -o root -g root -m 0755 /etc/vllm /usr/local/bin/vllm-docker /usr/local/lib/vllm-runc /usr/local/lib/vllm-runtime
/usr/bin/install -d -o root -g ali -m 0750 /var/log/vllm

install_root_file 0644 "$SOURCE_DIR/compose.yaml" /etc/vllm/compose.yaml
install_root_file 0755 "$SOURCE_DIR/validate-config.py" /usr/local/bin/vllm-validate-config
install_root_file 0755 "$SOURCE_DIR/patch-runc-rpath.py" /usr/local/bin/vllm-patch-runc-rpath
install_root_file 0644 "$SOURCE_DIR/vllm.service" /etc/systemd/system/vllm.service
install_root_file 0644 "$SOURCE_DIR/vllm-docker.service" /etc/systemd/system/vllm-docker.service
install_root_file 0440 "$SOURCE_DIR/vllm.sudoers" /etc/sudoers.d/vllm
install_root_file 0755 "$SOURCE_DIR/vllmctl" /usr/local/bin/vllmctl
install_root_file 0644 "$SOURCE_DIR/vllm.logrotate" /etc/logrotate.d/vllm

for name in docker docker-compose; do
  install_root_file 0755 "/home/linuxbrew/.linuxbrew/bin/$name" "/usr/local/bin/vllm-docker/$name"
done
for name in dockerd docker-proxy; do
  install_root_file 0755 "/home/linuxbrew/.linuxbrew/opt/docker-engine/bin/$name" "/usr/local/bin/vllm-docker/$name"
done
for name in containerd containerd-shim-runc-v2 ctr docker-init; do
  install_root_file 0755 "/home/linuxbrew/.linuxbrew/bin/$name" "/usr/local/bin/vllm-docker/$name"
done
# Make the known-working runc self-contained; its original RPATH is user-writable.
install_root_file 0644 /home/linuxbrew/.linuxbrew/opt/libseccomp/lib/libseccomp.so.2 /usr/local/lib/vllm-runc/libseccomp.so.2
install_root_file 0644 /home/linuxbrew/.linuxbrew/opt/libpathrs/lib/libpathrs.so.0 /usr/local/lib/vllm-runc/libpathrs.so.0
install_root_file 0755 /home/linuxbrew/.linuxbrew/sbin/runc /usr/local/bin/vllm-docker/runc
for installed_binary in /usr/local/bin/vllm-docker/*; do
  /usr/bin/python3 /usr/local/bin/vllm-patch-runc-rpath "$installed_binary"
  if { /usr/bin/readelf -l "$installed_binary"; /usr/bin/readelf -d "$installed_binary"; } 2>/dev/null | /usr/bin/grep -q /home/linuxbrew; then
    printf 'Unsafe Homebrew ELF path remains in %s.\n' "$installed_binary" >&2
    exit 1
  fi
done
/usr/local/bin/vllm-docker/runc --version >/dev/null

/usr/sbin/visudo -cf /etc/sudoers.d/vllm
/usr/bin/systemd-analyze verify /etc/systemd/system/vllm-docker.service /etc/systemd/system/vllm.service
/usr/local/bin/vllm-validate-config \
  --input "$PROJECT_DIR/vllm.env" --output /run/vllm-install.env --owner-uid 1000
/usr/local/bin/vllm-docker/docker-compose \
  --env-file /run/vllm-install.env -f /etc/vllm/compose.yaml config --quiet
/usr/bin/rm -f /run/vllm-install.env

/usr/bin/systemctl daemon-reload
/usr/bin/systemctl enable vllm-docker.service vllm.service

printf 'Installed hardened vLLM files. Backups (if any): %s\n' "$BACKUP_DIR"
printf 'Next: systemctl start vllm.service, then run the verification checklist.\n'
printf 'Do not remove ali from wheel until every verification passes.\n'
