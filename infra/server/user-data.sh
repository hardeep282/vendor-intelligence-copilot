#!/bin/bash
# Purpose : one-time bootstrap of the EC2 host (Ubuntu Server 24.04 LTS).
# Use     : paste into "Advanced details > User data" when launching the instance.
#           Logs go to /var/log/cloud-init-output.log on the server.
# Result  : Docker + Compose, nginx reverse proxy on port 80 -> 127.0.0.1:8000, Certbot,
#           AWS CLI, and /opt/copilot ready for the first deploy.
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y docker.io docker-compose-v2 nginx certbot python3-certbot-nginx curl
snap install aws-cli --classic
systemctl enable --now docker
mkdir -p /opt/copilot

# Reverse proxy. server_name "_" answers any host until the domain exists;
# Day 2's HTTPS step replaces it with api.vendor.<domain> and runs Certbot.
cat >/etc/nginx/sites-available/copilot <<'NGINX'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    client_max_body_size 1m;
    server_tokens off;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Request-ID $request_id;
        proxy_read_timeout 120s;
    }
}
NGINX
ln -sf /etc/nginx/sites-available/copilot /etc/nginx/sites-enabled/copilot
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
