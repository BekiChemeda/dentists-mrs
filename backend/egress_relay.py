"""
Egress relay for payments: an HTTPS CONNECT proxy that reaches ONLY the hosts in EGRESS_ALLOWED_HOSTS
(port 443). The API container has no route to the internet; when payments by phone are used, it sends
requests to payment providers through this relay. TLS runs end to end between the API and the provider, so
the relay never sees payment data or keys, and it cannot be used to reach anything else.

Run: python egress_relay.py   (listens on 0.0.0.0:3128)
"""
from __future__ import annotations

import asyncio
import logging
import os

ALLOWED = {h.strip().lower() for h in os.environ.get("EGRESS_ALLOWED_HOSTS", "api.chapa.co").split(",") if h.strip()}
PORT = int(os.environ.get("EGRESS_PORT", "3128"))
log = logging.getLogger("egress")


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        writer.close()


async def handle(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
    try:
        head = await asyncio.wait_for(client_r.readuntil(b"\r\n\r\n"), timeout=10)
        first = head.split(b"\r\n", 1)[0].decode("latin-1")
        method, target, _ = first.split(" ", 2)
        host, _, port = target.rpartition(":")
        if method != "CONNECT" or port != "443" or host.lower() not in ALLOWED:
            log.warning("refused %s %s", method, target[:100])
            client_w.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            await client_w.drain()
            client_w.close()
            return
        up_r, up_w = await asyncio.wait_for(asyncio.open_connection(host, 443), timeout=15)
        client_w.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await client_w.drain()
        log.info("tunnel to %s", host)
        await asyncio.gather(_pipe(client_r, up_w), _pipe(up_r, client_w))
    except (ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, OSError):
        client_w.close()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s egress %(levelname)s %(message)s")
    # Listens inside the container network only; not published.
    server = await asyncio.start_server(handle, "0.0.0.0", PORT, limit=16384)  # nosec B104
    log.info("allowing %s", ", ".join(sorted(ALLOWED)))
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
