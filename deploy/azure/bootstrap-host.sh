#!/usr/bin/env bash
set -euo pipefail

: "${GTZ_DOMAIN:?GTZ_DOMAIN is required}"
: "${GTZ_KEY_VAULT:?GTZ_KEY_VAULT is required}"

REPOSITORY_URL="${GTZ_REPOSITORY_URL:-https://github.com/braindead-dev/groktimizer.git}"
REPOSITORY_REF="${GTZ_REPOSITORY_REF:-main}"
SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_SOURCE="${GTZ_CONFIG_SOURCE:-$SOURCE_ROOT/groktimizer.toml.example}"
DATA_DEVICE="${GTZ_DATA_DEVICE:-/dev/disk/azure/scsi1/lun0}"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl debian-keyring \
  debian-archive-keyring git gnupg jq sqlite3 unattended-upgrades

if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
  chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  chmod o+r /etc/apt/sources.list.d/caddy-stable.list
  apt-get update
  apt-get install -y caddy
fi

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
fi

if ! id groktimizer >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/groktimizer --shell /usr/sbin/nologin groktimizer
fi
if [[ ! -b "$DATA_DEVICE" ]]; then
  echo "Managed data disk not found at $DATA_DEVICE" >&2
  exit 1
fi
if ! blkid "$DATA_DEVICE" >/dev/null 2>&1; then
  mkfs.ext4 -L groktimizer-data "$DATA_DEVICE"
fi
install -d -m 0750 /var/lib/groktimizer
DATA_UUID="$(blkid -s UUID -o value "$DATA_DEVICE")"
if ! grep -q "UUID=$DATA_UUID" /etc/fstab; then
  echo "UUID=$DATA_UUID /var/lib/groktimizer ext4 defaults,nofail,x-systemd.device-timeout=30 0 2" \
    >> /etc/fstab
fi
mountpoint -q /var/lib/groktimizer || mount /var/lib/groktimizer
install -d -o groktimizer -g groktimizer -m 0750 /var/lib/groktimizer
install -d -o root -g groktimizer -m 0750 /etc/groktimizer

if [[ ! -d /opt/groktimizer/.git ]]; then
  git clone --branch "$REPOSITORY_REF" --single-branch "$REPOSITORY_URL" /opt/groktimizer
else
  git -C /opt/groktimizer fetch origin "$REPOSITORY_REF"
  git -C /opt/groktimizer checkout -B "$REPOSITORY_REF" "origin/$REPOSITORY_REF"
fi
git -C /opt/groktimizer reset --hard "origin/$REPOSITORY_REF"
chown -R groktimizer:groktimizer /opt/groktimizer
runuser -u groktimizer -- uv sync --directory /opt/groktimizer --frozen --no-dev

install -m 0755 "$SOURCE_ROOT/deploy/azure/fetch-key-vault-secrets.py" \
  /usr/local/libexec/groktimizer-fetch-secrets
sed "s/__GTZ_KEY_VAULT__/${GTZ_KEY_VAULT}/g" \
  "$SOURCE_ROOT/deploy/azure/groktimizer-secrets.service" \
  > /etc/systemd/system/groktimizer-secrets.service
sed "s/__GTZ_DOMAIN__/${GTZ_DOMAIN}/g" \
  "$SOURCE_ROOT/deploy/azure/groktimizer-api.service" \
  > /etc/systemd/system/groktimizer-api.service
sed "s/__GTZ_DOMAIN__/${GTZ_DOMAIN}/g" \
  "$SOURCE_ROOT/deploy/azure/Caddyfile" \
  > /etc/caddy/Caddyfile

install -o root -g groktimizer -m 0640 "$CONFIG_SOURCE" \
  /etc/groktimizer/groktimizer.toml

systemctl daemon-reload
systemctl enable groktimizer-secrets.service groktimizer-api.service caddy
systemctl restart groktimizer-secrets.service
systemctl restart groktimizer-api.service
caddy validate --config /etc/caddy/Caddyfile
systemctl restart caddy
systemctl enable --now unattended-upgrades
