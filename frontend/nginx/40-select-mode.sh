#!/bin/sh
# Chooses HTTPS (default) or plain HTTP at container start.
set -eu
if [ "${MRS_HTTPS:-true}" = "true" ]; then
    if [ ! -s /etc/nginx/certs/server.crt ] || [ ! -s /etc/nginx/certs/server.key ]; then
        echo "ERROR: MRS_HTTPS=true but /etc/nginx/certs/server.crt or server.key is missing." >&2
        echo "Run deploy/scripts/make-certs.sh on the server, or set MRS_HTTPS=false for a trial." >&2
        exit 1
    fi
    cp /etc/nginx/mrs/https.conf /etc/nginx/conf.d/default.conf
    echo "MRS: HTTPS mode"
else
    cp /etc/nginx/mrs/http.conf /etc/nginx/conf.d/default.conf
    echo "WARNING: MRS is running over plain HTTP. Passwords and patient data are not encrypted on the network." >&2
fi
