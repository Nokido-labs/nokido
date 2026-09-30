#!/usr/bin/env python3
"""
forge_tls_proxy.py — Reverse-proxy TLS-terminant devant le hub HTTP:8766.

Pourquoi (finding 2026-06-01) : le hub force SelectorEventLoop (fix service NSSM
Windows). Or asyncio SSL sur SelectorEventLoop Windows ne complete pas le
handshake TLS (ProactorEventLoop requis). Terminer le TLS DANS le hub = hang.

Solution : proxy en PROCESSUS SÉPARÉ. Termine le TLS sur :8443, forwarde en clair
vers 127.0.0.1:8766. Transparent (byte-pump TCP bidirectionnel) → HTTP, SSE, WS,
MCP sans parsing. Stdlib pure (aucune dep).

⚠️ LIMITATION WINDOWS (test 2026-06-01) : asyncio SSL côté SERVEUR est défaillant
sur Windows dans les DEUX boucles — SelectorEventLoop = handshake hang ;
ProactorEventLoop = EOF spurious sur le read serveur qui détruit le transport
client → la réponse backend (lue OK, ex 205o) ne peut être réécrite
(ConnectionReset). CE PROXY est donc FIABLE sur POSIX (Linux/macOS, loop défaut)
mais PAS sur Windows. Sur Windows, utiliser un terminateur TLS NON-asyncio
(stunnel/caddy) devant :8766. NB : sur POSIX le TLS in-hub (dual-listen) marche
déjà directement → ce proxy n'y est utile qu'en déport dédié.

PRÉ-REQUIS : retirer LAFORGE_HUB_TLS_CERT/KEY de Nokido.env + restart hub, pour
que le hub LIBÈRE :8443 (sinon conflit de bind avec ce proxy).

Usage
-----
  python tools/forge_tls_proxy.py
  python tools/forge_tls_proxy.py --listen-port 8443 --target-port 8766
Cert/key : --cert/--key ou env LAFORGE_HUB_TLS_CERT/KEY (def sandbox/tls).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import ssl
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEF_CERT = os.environ.get("LAFORGE_HUB_TLS_CERT", str(ROOT / "sandbox" / "tls" / "cert.pem"))
DEF_KEY = os.environ.get("LAFORGE_HUB_TLS_KEY", str(ROOT / "sandbox" / "tls" / "key.pem"))


async def _pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, tag: str) -> None:
    # Half-close : quand le reader EOF, on signale EOF au writer (write_eof) SANS
    # le fermer, pour que l'autre sens puisse encore transmettre la réponse.
    # (SSL ne supporte pas write_eof -> can_write_eof() False -> on laisse ouvert.)
    n = 0
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            n += len(data)
            writer.write(data)
            await writer.drain()
        # NE PAS write_eof/close ici : la requête HTTP est complète, le backend
        # répond sans avoir besoin d'un FIN ; un FIN/close prématuré le fait
        # abandonner (0 octet). On laisse l'autre sens vivre (fermeture en _handle).
    except Exception as e:
        print(f"[tls-proxy] pump {tag} err: {e!r}", flush=True)
    finally:
        print(f"[tls-proxy] pump {tag} fini ({n} octets)", flush=True)


async def _handle(cli_r, cli_w, host: str, port: int) -> None:
    try:
        srv_r, srv_w = await asyncio.open_connection(host, port)
    except Exception as e:
        print(f"[tls-proxy] backend {host}:{port} injoignable: {e!r}", flush=True)
        try:
            cli_w.close()
        except Exception:
            pass
        return
    try:
        await asyncio.gather(_pump(cli_r, srv_w, "cli->srv"), _pump(srv_r, cli_w, "srv->cli"))
    finally:
        for w in (srv_w, cli_w):
            try:
                w.close()
            except Exception:
                pass


async def _serve(args, ctx: ssl.SSLContext) -> None:
    async def _cb(reader, writer):
        # callback DOIT être une coroutine function : un lambda renvoyant une
        # coroutine n'est PAS awaité par asyncio.start_server (handler jamais exécuté).
        await _handle(reader, writer, args.target_host, args.target_port)

    server = await asyncio.start_server(
        _cb, args.listen_host, args.listen_port, ssl=ctx,
    )
    print(f"[tls-proxy] HTTPS :{args.listen_port} -> {args.target_host}:{args.target_port}", flush=True)
    async with server:
        await server.serve_forever()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Reverse-proxy TLS-terminant devant le hub.")
    p.add_argument("--listen-host", default="127.0.0.1")
    p.add_argument("--listen-port", type=int, default=8443)
    p.add_argument("--target-host", default="127.0.0.1")
    p.add_argument("--target-port", type=int, default=8766)
    p.add_argument("--cert", default=DEF_CERT)
    p.add_argument("--key", default=DEF_KEY)
    a = p.parse_args(argv)

    if not (os.path.isfile(a.cert) and os.path.isfile(a.key)):
        print(f"[tls-proxy] ERREUR: cert/key introuvable: {a.cert} / {a.key}", flush=True)
        return 1
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(a.cert, a.key)

    # ProactorEventLoop = SSL fonctionnel sur Windows (≠ SelectorEventLoop du hub).
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    try:
        asyncio.run(_serve(a, ctx))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
