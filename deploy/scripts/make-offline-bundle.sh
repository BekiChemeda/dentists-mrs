#!/usr/bin/env bash
# Builds an offline installation bundle: everything a clinic server needs, so the installer works with no
# internet at the clinic. Run it on a machine WITH internet and Docker (Ubuntu 24.04, x86-64), from the
# application folder:
#
#     deploy/scripts/make-offline-bundle.sh 1.4.0
#
# Output: dist/mrs-offline-1.4.0.tar (about 1 GB) and its .sha256. Copy both to a USB stick. At the clinic:
#
#     sha256sum -c mrs-offline-1.4.0.tar.sha256
#     sudo tar -xf mrs-offline-1.4.0.tar -C /opt && sudo mv /opt/mrs-1.4.0 /opt/mrs
#     cd /opt/mrs && sudo deploy/install.sh
#
# The bundle holds: the application files of the current git commit; the three container images (API,
# web, PostgreSQL 16) already built; Docker Engine and Compose packages for Ubuntu 24.04 with their
# dependencies; a manifest and SHA-256 checksums the installer verifies before using anything.
set -euo pipefail

VERSION="${1:-}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Usage: $0 VERSION   (for example 1.4.0)" >&2; exit 2; }
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
for tool in docker git sha256sum tar gzip; do
    command -v "$tool" >/dev/null || { echo "$tool is required" >&2; exit 1; }
done
[[ "$(uname -m)" == x86_64 ]] || { echo "Build the bundle on an x86-64 machine (clinic servers are x86-64)." >&2; exit 1; }
if [[ -n "$(git status --porcelain)" ]]; then
    echo "The working tree has uncommitted changes. Commit them first: the bundle is built from a commit." >&2
    exit 1
fi

NAME="mrs-$VERSION"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
OUT="$WORK/$NAME"
mkdir -p "$OUT" dist

echo "== Application files ($(git rev-parse --short HEAD))"
git archive --format=tar HEAD | tar -xf - -C "$OUT"
mkdir -p "$OUT/offline/debs"

echo "== Container images"
MRS_VERSION="$VERSION" docker compose build --pull
docker pull postgres:16
docker save "mrs-api:$VERSION" "mrs-web:$VERSION" postgres:16 | gzip -1 > "$OUT/offline/images.tar.gz"

echo "== Docker Engine packages for Ubuntu 24.04 (with dependencies)"
# A clean Ubuntu 24.04 container downloads exactly what a fresh Ubuntu Server 24.04 would need.
docker run --rm -v "$OUT/offline/debs:/out" ubuntu:24.04 bash -euc '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl >/dev/null
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    rm -f /var/cache/apt/archives/*.deb
    apt-get install -y -qq --download-only docker-ce docker-ce-cli containerd.io docker-buildx-plugin \
        docker-compose-plugin >/dev/null
    cp /var/cache/apt/archives/*.deb /out/
    chown -R '"$(id -u):$(id -g)"' /out'

echo "== Manifest and checksums"
{
    echo "version=$VERSION"
    echo "commit=$(git rev-parse HEAD)"
    echo "built=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "ubuntu=24.04"
    echo "arch=amd64"
} > "$OUT/offline/MANIFEST"
(cd "$OUT/offline" && find . -type f ! -name SHA256SUMS -printf '%P\n' | sort | xargs sha256sum > SHA256SUMS)

tar -cf "dist/$NAME.tar" -C "$WORK" "$NAME"
(cd dist && sha256sum "$NAME.tar" > "$NAME.tar.sha256")
echo
echo "Bundle: dist/$NAME.tar ($(du -h "dist/$NAME.tar" | cut -f1))"
echo "Check:  dist/$NAME.tar.sha256"
