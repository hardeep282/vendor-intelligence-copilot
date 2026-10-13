#!/usr/bin/env bash
# Purpose : switch the API to a new image; roll back to the previous one if /health fails.
# Inputs  : $1 = full image URI (registry/repository:tag), $2 = AWS region.
# Runs    : as root on the EC2 host, sent by the CI deploy job through SSM Run Command.
set -euo pipefail
# SSM Run Command does not always include /snap/bin, where Ubuntu's aws CLI lives.
export PATH="$PATH:/snap/bin:/usr/local/bin"

IMAGE="$1"
REGION="$2"
DIR=/opt/copilot
REGISTRY="${IMAGE%%/*}"

cd "$DIR"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
PREVIOUS="$(cat "$DIR/current_image" 2>/dev/null || true)"
docker pull "$IMAGE"

switch_to() {
  API_IMAGE="$1" AWS_REGION="$REGION" docker compose -f "$DIR/compose.yaml" up -d --remove-orphans
}

healthy() {
  for _ in $(seq 1 20); do
    if curl -fsS http://127.0.0.1:8000/health >/dev/null; then
      return 0
    fi
    sleep 3
  done
  return 1
}

switch_to "$IMAGE"
if healthy; then
  echo "$IMAGE" >"$DIR/current_image"
  docker image prune -f >/dev/null
  echo "deployed $IMAGE"
else
  echo "health check failed for $IMAGE" >&2
  docker compose -f "$DIR/compose.yaml" logs --tail 50 api >&2 || true
  if [ -n "$PREVIOUS" ]; then
    switch_to "$PREVIOUS"
    if healthy; then echo "rolled back to $PREVIOUS" >&2; fi
  fi
  exit 1
fi
