#!/usr/bin/env bash
# Prepare a fresh Ubuntu 24.04 VM (arm64 or amd64) as the ListenUp host (ADR 0073).
# Run once as root, or paste into the cloud-init "user data" field. Safe to run again.
#
#   LISTENUP_DEPLOY_PUBKEY='ssh-ed25519 AAAA... release-workflow' sudo -E bash provision-host.sh
#
# Takes only a PUBLIC key. No secret is read, written or logged. It does not create
# /opt/listenup/.env (docs/runbooks/deploy.md, first-time setup step 9).
set -euo pipefail

: "${LISTENUP_DEPLOY_PUBKEY:?set to the public key of the release workflow, one line}"
deploy_user="${LISTENUP_DEPLOY_USER:-deploy}"
deploy_dir="${LISTENUP_DEPLOY_DIR:-/opt/listenup}"
swap_gb="${LISTENUP_SWAP_GB:-4}"
export DEBIAN_FRONTEND=noninteractive

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
[[ "$LISTENUP_DEPLOY_PUBKEY" =~ ^(ssh-ed25519|ecdsa-sha2-nistp256|ssh-rsa)\  ]] \
  || { echo "LISTENUP_DEPLOY_PUBKEY must be a public key line" >&2; exit 1; }
[[ "$LISTENUP_DEPLOY_PUBKEY" != *PRIVATE* ]] || { echo "that is a private key" >&2; exit 1; }

# Docker Engine and the Compose plugin from Docker's own apt repository: deploy.md
# needs Engine 28+ and Compose 2.24+, newer than Ubuntu's docker.io package.
apt-get update -y
apt-get install -y ca-certificates curl gnupg fail2ban unattended-upgrades iptables-persistent
install -m 0755 -d /etc/apt/keyrings
if [[ ! -s /etc/apt/keyrings/docker.asc ]]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
fi
arch="$(dpkg --print-architecture)"
# shellcheck disable=SC1091
. /etc/os-release
echo "deb [arch=$arch signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

# Deploy user: docker group, key-only SSH.
id "$deploy_user" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$deploy_user"
usermod -aG docker "$deploy_user"
install -d -m 0700 -o "$deploy_user" -g "$deploy_user" "/home/$deploy_user/.ssh"
auth="/home/$deploy_user/.ssh/authorized_keys"
touch "$auth"
grep -qxF "$LISTENUP_DEPLOY_PUBKEY" "$auth" || printf '%s\n' "$LISTENUP_DEPLOY_PUBKEY" >> "$auth"
chown "$deploy_user:$deploy_user" "$auth"
chmod 0600 "$auth"
install -d -m 0750 -o "$deploy_user" -g "$deploy_user" "$deploy_dir"

cat > /etc/ssh/sshd_config.d/10-listenup.conf <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
CONF
sshd -t && systemctl reload ssh

# Swap as a safety net for the speech models on a 12 GB host.
if [[ "$swap_gb" -gt 0 && ! -e /swapfile ]]; then
  fallocate -l "${swap_gb}G" /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Oracle's Ubuntu images ship iptables rules that reject everything but SSH, on top of
# the cloud firewall. Open the web ports before the generic REJECT rule. Harmless on
# images without that rule (the inserted rules simply accept traffic).
for rule in "-p tcp --dport 80" "-p tcp --dport 443" "-p udp --dport 443"; do
  # shellcheck disable=SC2086
  iptables -C INPUT $rule -j ACCEPT 2>/dev/null || iptables -I INPUT 1 $rule -j ACCEPT
done
netfilter-persistent save

systemctl enable --now fail2ban unattended-upgrades

docker --version
docker compose version
echo "provisioned: next, reboot is not required. See docs/runbooks/stage-0-host.md."
