#!/usr/bin/env bash
# Creates a private clinic certificate authority and a server certificate for HTTPS on the LAN.
# A public CA cannot issue certificates for private IP addresses, so the clinic acts as its own CA.
# Install deploy/certs/clinic-ca.crt once on every client computer (see docs/operations/install.md).
#
# Usage: deploy/scripts/make-certs.sh 192.168.1.10 [mrs.clinic.local]
set -euo pipefail
ip="${1:?Usage: $0 <server-ip> [dns-name]}"
dns="${2:-mrs.clinic.local}"
dir="$(cd "$(dirname "$0")/../certs" && pwd)"
cd "$dir"
umask 077

if [[ ! -f clinic-ca.key ]]; then
    openssl req -x509 -new -nodes -newkey rsa:3072 -sha256 -days 3650 \
        -keyout clinic-ca.key -out clinic-ca.crt -subj "/CN=Clinic MRS Local CA"
    echo "Created clinic CA (valid 10 years). Keep clinic-ca.key secret and backed up offline."
fi

openssl req -new -nodes -newkey rsa:2048 -keyout server.key -out server.csr -subj "/CN=${dns}"
cat > server.ext <<EXT
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=IP:${ip},DNS:${dns},DNS:localhost
EXT
openssl x509 -req -in server.csr -CA clinic-ca.crt -CAkey clinic-ca.key -CAcreateserial \
    -out server.crt -days 825 -sha256 -extfile server.ext
rm -f server.csr server.ext
chmod 644 server.crt clinic-ca.crt
chmod 600 server.key clinic-ca.key
echo "Server certificate for IP ${ip} and ${dns} written to ${dir}/server.crt (valid 825 days)."
