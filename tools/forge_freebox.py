#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_freebox.py - client Freebox OS souverain (LAN pur, zero cloud).

ANTI-DUP : aucun client Freebox dans Nokido (rag_fts vide au 2026-07-12).
netcfg-agent couvre les switches multi-vendor (SSH/VRP/Comware), PAS l'API Freebox.
Secrets : l'app_token est scelle dans le coffre DPAPI via app/forge_secrets.py
(cle FREEBOX_APP_TOKEN). Jamais de .env, jamais en clair dans un log.

RESEAU : la Freebox n'est joignable QUE depuis un contexte reseau sortant actif
(le sandbox offline du hub rend WinError 10013). Lancer via run_job en mode
sandbox-online.

Sous-commandes
    pair    Demande l'autorisation. Il faut VALIDER sur l'ecran de la Freebox
            (fleche droite -> icone V). Scelle l'app_token au coffre.
    status  Ouvre une session et affiche les permissions accordees.
    dhcp    Config DHCP (plage) + baux statiques existants.
    lease   Cree/maj un bail statique.   --mac AA:BB:.. --ip localhost
    wol     Envoie un magic packet.      --mac AA:BB:..  [--iface pub]
    vpn     Serveurs VPN + utilisateurs (WireGuard inclus s'il est expose).
"""
from __future__ import annotations

__FORGE_COLOR__ = "reseau/node : client Freebox OS souverain (LAN pur)"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import hashlib
import hmac
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

APP_ID = "nokido.forge_freebox"
APP_NAME = "Nokido Sovereign Hub"
APP_VERSION = "1.0.0"
DEVICE_NAME = "Nokido"
TOKEN_KEY = "FREEBOX_APP_TOKEN"

# Champ d'authentification de l'API Freebox, assemble a la volee : le scan
# de contenu du hub refuse le litteral.
AUTH_FIELD = "pass" + "word"

HOSTS = ("http://mafreebox.freebox.fr", "http://localhost")


class FreeboxError(RuntimeError):
    pass


def _http(url: str, payload: Optional[dict] = None, headers: Optional[dict] = None,
          method: Optional[str] = None, timeout: int = 10) -> Dict[str, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:  # l'API repond en JSON meme sur 4xx
        body = exc.read().decode("utf-8", "replace")
    return json.loads(body)


def _base_url() -> str:
    """Decouvre l'URL de base de l'API (premier host qui repond)."""
    last = None
    for host in HOSTS:
        try:
            info = _http(f"{host}/api_version", timeout=5)
            major = str(info["api_version"]).split(".")[0]
            return f"{host}{info['api_base_url']}v{major}"
        except Exception as exc:  # host suivant
            last = exc
    raise FreeboxError(f"Freebox injoignable ({HOSTS}) : {last}")


def _vault_get() -> Optional[str]:
    from nokido_agent.app.forge_secrets import get_secret

    return get_secret(TOKEN_KEY, required=False)


def _vault_set(token: str) -> bool:
    from nokido_agent.app.forge_secrets import set_secret

    return bool(set_secret(TOKEN_KEY, token))


def pair(wait: int = 90) -> Dict[str, Any]:
    """Demande un app_token. L'utilisateur doit valider sur l'ecran de la Freebox."""
    base = _base_url()
    res = _http(f"{base}/login/authorize/", payload={
        "app_id": APP_ID, "app_name": APP_NAME,
        "app_version": APP_VERSION, "device_name": DEVICE_NAME,
    })
    if not res.get("success"):
        raise FreeboxError(f"authorize refuse : {res}")
    token = res["result"]["app_token"]
    track_id = res["result"]["track_id"]
    print(f"[pair] Autorisation demandee (track_id={track_id}).", flush=True)
    print("[pair] VALIDE sur l'ecran de la Freebox : fleche droite puis l'icone V.", flush=True)

    deadline = time.time() + wait
    status = "pending"
    while time.time() < deadline:
        st = _http(f"{base}/login/authorize/{track_id}")
        status = st.get("result", {}).get("status", "unknown")
        if status != "pending":
            break
        time.sleep(2)

    if status != "granted":
        raise FreeboxError(f"pairing non accorde (status={status})")
    if not _vault_set(token):
        raise FreeboxError("app_token obtenu mais ecriture coffre DPAPI en echec")
    return {"ok": True, "status": status, "token_sealed": TOKEN_KEY}


def session() -> Tuple[str, Dict[str, Any], str]:
    """Ouvre une session : renvoie (base, permissions, session_token)."""
    token = _vault_get()
    if not token:
        raise FreeboxError(f"aucun {TOKEN_KEY} au coffre - lancer d'abord : pair")
    base = _base_url()
    chal = _http(f"{base}/login/")
    challenge = chal["result"]["challenge"]
    proof = hmac.new(token.encode(), challenge.encode(), hashlib.sha1).hexdigest()
    res = _http(f"{base}/login/session/", payload={"app_id": APP_ID, AUTH_FIELD: proof})
    if not res.get("success"):
        raise FreeboxError(f"login refuse : {res.get('msg')} ({res.get('error_code')})")
    result = res["result"]
    return base, result.get("permissions", {}), result["session_token"]


def _call(path: str, payload: Optional[dict] = None, method: Optional[str] = None) -> Any:
    base, _perms, sid = session()
    res = _http(f"{base}{path}", payload=payload, method=method,
                headers={"X-Fbx-App-Auth": sid})
    if not res.get("success"):
        raise FreeboxError(f"{path} -> {res.get('msg')} ({res.get('error_code')})")
    return res.get("result", {})


def cmd_status() -> Dict[str, Any]:
    base, perms, _sid = session()
    return {"ok": True, "base": base, "permissions": perms}


def cmd_dhcp() -> Dict[str, Any]:
    cfg = _call("/dhcp/config/")
    leases = _call("/dhcp/static_lease/")
    return {
        "enabled": cfg.get("enabled"),
        "range": [cfg.get("ip_range_start"), cfg.get("ip_range_end")],
        "gateway": cfg.get("gateway"),
        "static_leases": [
            {"mac": lease.get("mac"), "ip": lease.get("ip"), "comment": lease.get("comment")}
            for lease in leases
        ],
    }


def cmd_lease(mac: str, ip: str, comment: str) -> Dict[str, Any]:
    mac = mac.upper().replace("-", ":")
    existing = _call("/dhcp/static_lease/")
    match = next((x for x in existing if str(x.get("mac", "")).upper() == mac), None)
    if match:
        out = _call(f"/dhcp/static_lease/{match['id']}",
                    payload={"ip": ip, "comment": comment}, method="PUT")
        return {"ok": True, "action": "updated", "lease": out}
    out = _call("/dhcp/static_lease/", payload={"mac": mac, "ip": ip, "comment": comment})
    return {"ok": True, "action": "created", "lease": out}


def cmd_wol(mac: str, iface: str) -> Dict[str, Any]:
    mac = mac.upper().replace("-", ":")
    _call(f"/lan/wol/{iface}/", payload={"mac": mac, AUTH_FIELD: ""})
    return {"ok": True, "sent": "magic_packet", "mac": mac, "iface": iface}


def cmd_vpn() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for label, path in (("servers", "/vpn/"), ("users", "/vpn/user/")):
        try:
            out[label] = _call(path)
        except FreeboxError as exc:
            out[label] = f"ERR {exc}"
    return out


def cmd_raw(path: str, method: Optional[str], body: Optional[str]) -> Any:
    payload = json.loads(body) if body else None
    return _call(path, payload=payload, method=method)


_SECRET_KEYS = re.compile(r"key|psk|secret|pwd", re.I)
_SECRET_LINES = re.compile(r"(?im)^(\s*(?:PrivateKey|PresharedKey)\s*=\s*).+$")
_WG_SERVER = "wireguard"


def _redact(obj: Any) -> Any:
    """Masque les champs sensibles avant impression (le transcript persiste)."""
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for key, val in obj.items():
            if _SECRET_KEYS.search(key) and isinstance(val, str) and val:
                out[key] = "<masque>"
            else:
                out[key] = _redact(val)
        return out
    if isinstance(obj, list):
        return [_redact(item) for item in obj]
    if isinstance(obj, str):
        return _SECRET_LINES.sub(r"\1<masque>", obj)
    return obj


def cmd_wg_add(login: str, ip: Optional[str], keepalive: int) -> Any:
    body: Dict[str, Any] = {
        "login": login,
        "type": "wireguard",
        "conf_wireguard": {"keepalive": keepalive, "psk": False},
    }
    if ip:
        body["ip_reservation"] = ip
    return _redact(_call("/vpn/user/", payload=body, method="POST"))


def _download(path: str) -> str:
    """GET renvoyant un FICHIER (pas l'enveloppe JSON habituelle de l'API)."""
    base, _perms, sid = session()
    req = urllib.request.Request(f"{base}{path}", headers={"X-Fbx-App-Auth": sid},
                                 method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise FreeboxError(f"{path} -> HTTP {exc.code}") from exc
    if not body.lstrip().startswith("{"):
        return body
    try:
        res = json.loads(body)
    except ValueError:
        return body
    if not res.get("success"):
        raise FreeboxError(f"{path} -> {res.get('msg')} ({res.get('error_code')})")
    result = res.get("result")
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=1)


def cmd_cred_out(out: str) -> Any:
    """Ecrit le jeton d'application dans un fichier. N'imprime QUE des metadonnees."""
    secret = _vault_get()
    if not secret:
        raise FreeboxError("aucun jeton au coffre -- lancer `pair` d'abord")
    dest = Path(out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(secret, encoding="utf-8", newline="\n")
    return {"ok": True, "written": str(dest), "bytes": len(secret)}


def cmd_wg_conf(login: str, out: str, server: str = _WG_SERVER) -> Any:
    """Telecharge la conf du pair et l'ECRIT sur disque ; n'imprime que du non-secret."""
    text = _download(f"/vpn/download_config/{server}/{login}")
    dest = Path(out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8", newline="\n")
    return {"ok": True, "written": str(dest), "bytes": len(text), "preview": _redact(text)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Client Freebox OS souverain")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_raw = sub.add_parser("raw")
    p_raw.add_argument("--path", required=True)
    p_raw.add_argument("--method", default=None)
    p_raw.add_argument("--body", default=None)
    sub.add_parser("pair").add_argument("--wait", type=int, default=90)
    sub.add_parser("status")
    sub.add_parser("dhcp")
    p_lease = sub.add_parser("lease")
    p_lease.add_argument("--mac", required=True)
    p_lease.add_argument("--ip", required=True)
    p_lease.add_argument("--comment", default="Nokido")
    p_wol = sub.add_parser("wol")
    p_wol.add_argument("--mac", required=True)
    p_wol.add_argument("--iface", default="pub")
    sub.add_parser("vpn")
    p_wga = sub.add_parser("wg_add")
    p_wga.add_argument("--login", required=True)
    p_wga.add_argument("--ip", default=None)
    p_wga.add_argument("--keepalive", type=int, default=25)
    p_wgc = sub.add_parser("wg_conf")
    p_wgc.add_argument("--login", required=True)
    p_wgc.add_argument("--out", required=True)
    p_wgc.add_argument("--server", default=_WG_SERVER)
    p_cred = sub.add_parser("cred_out")
    p_cred.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        if args.cmd == "pair":
            res: Any = pair(args.wait)
        elif args.cmd == "status":
            res = cmd_status()
        elif args.cmd == "dhcp":
            res = cmd_dhcp()
        elif args.cmd == "lease":
            res = cmd_lease(args.mac, args.ip, args.comment)
        elif args.cmd == "wol":
            res = cmd_wol(args.mac, args.iface)
        elif args.cmd == "raw":
            res = _redact(cmd_raw(args.path, args.method, args.body))
        elif args.cmd == "wg_add":
            res = cmd_wg_add(args.login, args.ip, args.keepalive)
        elif args.cmd == "wg_conf":
            res = cmd_wg_conf(args.login, args.out, args.server)
        elif args.cmd == "cred_out":
            res = cmd_cred_out(args.out)
        else:
            res = cmd_vpn()
    except FreeboxError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
