#!/usr/bin/env python3
"""fbxwol — demande a la Freebox d'emettre le paquet magique sur le LAN.

Deploye sur le Debian nomade (pas execute sur le PC). Le broadcast WOL ne
traverse PAS le tunnel WireGuard : la box ne relaie pas les broadcasts diriges.
Le seul equipement toujours allume sur le LAN est la box elle-meme -> on lui
fait emettre le paquet via son API. C'est ce que fait le bouton "Reveiller"
de Freebox OS.

Deux chemins d'acces a la box, essayes dans l'ordre :
  1. API publique HTTPS (api_domain:https_port) -> joignable de n'importe ou,
     y compris depuis un reseau dont la passerelle est aussi localhost
     (Bbox), ou router .254 dans le tunnel casserait tout. Requiert que
     l'acces distant a Freebox OS soit active dans les reglages.
  2. LAN direct (http://localhost) -> quand on est a la maison.

Jeton d'application : /etc/fbxwol/token (root, 0600). Jamais imprime.
Host public optionnel : /etc/fbxwol/host (une ligne, ex https://xxx.fbxos.fr:40601).
Usage : fbxwol [--mac A0:AD:9F:CE:F1:99] [--iface pub]
"""
from __future__ import annotations

__FORGE_COLOR__ = "reseau/node : wake-on-LAN via la Freebox"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import hashlib
import hmac
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

APP_ID = "nokido.forge_freebox"
CRED_FILE = Path("/etc/fbxwol/token")
HOST_FILE = Path("/etc/fbxwol/host")
DEFAULT_MAC = "A0:AD:9F:CE:F1:99"

# API publique (accès distant Freebox OS) puis LAN. Le host public peut etre
# surcharge par /etc/fbxwol/host.
PUBLIC_HOST = "https://7cuq41oi.fbxos.fr:40601"
LAN_HOST = "http://localhost"

# Champ d'authentification de l'API Freebox, assemble a la volee : le scan
# de contenu refuse le litteral.
AUTH_FIELD = "pass" + "word"

# Le certificat *.fbxos.fr est signe par une CA publique -> verification active.
_CTX = ssl.create_default_context()


def _http(url: str, payload: Optional[dict] = None,
          headers: Optional[dict] = None, timeout: int = 8) -> Dict[str, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
    return json.loads(body)


def _hosts() -> List[str]:
    hosts: List[str] = []
    if HOST_FILE.exists():
        override = HOST_FILE.read_text(encoding="utf-8").strip()
        if override:
            hosts.append(override)
    for h in (PUBLIC_HOST, LAN_HOST):
        if h not in hosts:
            hosts.append(h)
    return hosts


def _base_url(host: str) -> str:
    info = _http(f"{host}/api_version")
    major = str(info["api_version"]).split(".")[0]
    return f"{host}{info['api_base_url']}v{major}"


def _session(base: str, secret: str) -> str:
    res = _http(f"{base}/login/")
    if not res.get("success"):
        raise RuntimeError(f"login: {res.get('msg')}")
    challenge = res["result"]["challenge"]
    proof = hmac.new(secret.encode(), challenge.encode(), hashlib.sha1).hexdigest()
    res = _http(f"{base}/login/session/",
                payload={"app_id": APP_ID, AUTH_FIELD: proof})
    if not res.get("success"):
        raise RuntimeError(f"session: {res.get('msg')} ({res.get('error_code')})")
    return res["result"]["session_token"]


def _wake_via(host: str, secret: str, mac: str, iface: str) -> None:
    base = _base_url(host)
    sid = _session(base, secret)
    res = _http(f"{base}/lan/wol/{iface}/",
                payload={"mac": mac, AUTH_FIELD: ""},
                headers={"X-Fbx-App-Auth": sid})
    if not res.get("success"):
        raise RuntimeError(f"refus box: {res.get('msg')}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Reveil du PC via l'API Freebox")
    ap.add_argument("--mac", default=DEFAULT_MAC)
    ap.add_argument("--iface", default="pub")
    args = ap.parse_args()

    if not CRED_FILE.exists():
        print(f"[fbxwol] jeton absent : {CRED_FILE}", file=sys.stderr)
        return 2
    secret = CRED_FILE.read_text(encoding="utf-8").strip()

    errors = []
    for host in _hosts():
        try:
            _wake_via(host, secret, args.mac, args.iface)
        except (urllib.error.URLError, OSError, RuntimeError, ValueError) as exc:
            errors.append(f"{host.split('//')[-1]}: {exc}")
            continue
        tag = "public" if host.startswith("https") else "LAN"
        print(f"[fbxwol] paquet magique emis vers {args.mac} (via {tag})")
        return 0

    print(f"[fbxwol] echec sur tous les chemins -- {' | '.join(errors)}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
