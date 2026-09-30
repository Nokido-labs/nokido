#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_vm_dns.py — accès TRUSTED à la VM StackDNS (AdGuardHome) pour debug/unblock.

SSH freebox@localhost ; creds lus depuis Nokido.env LOCALEMENT (jamais
exposés à l'agent — ce script tourne en trusted_script sous LaForgeTrusted).
Cf [[roadmap_vm_dns_hardening]] (AdGuard + Unbound, Debian ARM64 Freebox VM).

Actions :
  discover            : liste les CLÉS env candidates (NOMS masqués) + dispo paramiko.
  blocked [N]         : N dernières requêtes BLOQUÉES par AdGuard (voir le domaine du jeu).
  inspect             : statut DNS64 (AdGuard yaml + Unbound) — lecture seule.
  allow <domaine>     : ajoute @@||domaine^ aux user_rules AdGuard + restart (écrit).
  run "<cmd>"         : exécute une commande shell brute (debug).
"""

__FORGE_COLOR__ = "reseau/node : acces trusted a la VM StackDNS (AdGuardHome)"  # organe declare le 2026-09-06 (audit de raccordement)
import os
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = os.path.join(ROOT, "Nokido.env")
HOST = "localhost"
USER = "freebox"
QLOG = "/opt/AdGuardHome/data/querylog.json"
AG_YAML = "/opt/AdGuardHome/AdGuardHome.yaml"


def _load_env() -> dict:
    d = {}
    if os.path.exists(ENV):
        for line in open(ENV, encoding="utf-8", errors="replace"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip().strip('"').strip("'")
    return d


_HINTS = ("FREEBOX", "STACKDNS", "VM_SSH", "SSH_VM", "VM_DNS", "DNS_VM", "ADGUARD", "166")


def _find_creds(env: dict):
    host = env.get("SSH_HOST") or HOST
    user = env.get("SSH_USER") or USER
    try:
        port = int(env.get("SSH_PORT") or 22)
    except Exception:  # noqa: BLE001
        port = 22
    pw = (env.get("SSH_PASS") or env.get("SSH_PASSWORD") or env.get("SSH_PWD")
          or env.get("FREEBOX_PASS") or env.get("VM_SSH_PASS"))
    keyfile = (env.get("PRIVATE_KEY_PATH") or env.get("SSH_KEY") or env.get("SSH_KEYFILE")
               or env.get("SSH_KEY_PATH") or env.get("SSH_IDENTITY") or env.get("SSH_PRIVATE_KEY"))
    if not pw and not keyfile:  # fallback : scan par indices
        for k, v in env.items():
            ku = k.upper()
            if any(h in ku for h in _HINTS) and v:
                if "PASS" in ku or "PWD" in ku:
                    pw = v
                elif "KEY" in ku:
                    keyfile = v
    return host, port, user, pw, keyfile


def _ssh_run(cmd: str, timeout: int = 25):
    """Via le client OpenSSH natif Windows (ssh.exe) — pas de crypto Python
    (asyncssh/paramiko cassés ici : _cffi_backend ACL refusé en contexte trusted).
    Auth par clé (PRIVATE_KEY_PATH), BatchMode (jamais de prompt password)."""
    import subprocess
    env = _load_env()
    host, port, user, pw, keyfile = _find_creds(env)
    ssh = "ssh"
    args = [ssh, "-p", str(port),
            "-o", "StrictHostKeyChecking=no",
            "-o", f"UserKnownHostsFile={os.devnull}",
            "-o", f"GlobalKnownHostsFile={os.devnull}",
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={min(timeout, 20)}"]
    if keyfile and os.path.exists(keyfile):
        args += ["-i", keyfile]
    args += [f"{user}@{host}", cmd]
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout + 15)
    except FileNotFoundError:
        return None, "ssh.exe introuvable (OpenSSH client absent du PATH)"
    except subprocess.TimeoutExpired:
        return None, f"timeout ssh {user}@{host}:{port}"
    err = r.stderr or ""
    if r.returncode != 0 and not r.stdout:
        return None, f"ssh rc={r.returncode}: {err.strip()[:300]}"
    return r.stdout or "", err


def _discover():
    env = _load_env()
    scan = ("SSH", "VM", "DNS", "FREEBOX", "STACKDNS", "166", "PASS", "PWD",
            "KEY", "SECRET", "CRED", "PEM", "PRIV", "IDENT")
    cand = []
    for k, v in env.items():
        if any(t in k.upper() for t in scan):
            masked = (v[:2] + "***" + str(len(v))) if v else "(vide)"
            cand.append(f"  {k} = {masked}")
    host, port, user, pw, keyfile = _find_creds(env)
    try:
        import asyncssh  # noqa: F401
        lib = "asyncssh OK"
    except Exception as e:  # noqa: BLE001
        lib = f"asyncssh ABSENT ({e})"
    print("Nokido.env présent:", os.path.exists(ENV))
    print("clés candidates (valeurs masquées):")
    print("\n".join(cand) or "  (aucune)")
    print(f"\nrésolu -> {user}@{host}:{port} pw={'oui' if pw else 'non'} key={keyfile or 'non'}")
    print("transport:", lib)


def _blocked(n: int, ip: str = None):
    # querylog root-only -> sudo -n. Dédup par domaine (coupe le spam télémétrie),
    # filtre client optionnel -> le vrai bloqueur du jeu ressort.
    cmd = f"sudo -n tail -n 5000 {QLOG} 2>/dev/null || tail -n 5000 {QLOG} 2>&1"
    out, err = _ssh_run(cmd)
    if out is None:
        print("ERR:", err)
        return
    agg = {}  # domaine -> [count, last_t, set(ips), rule]
    for line in out.splitlines():
        line = line.strip().rstrip(",")
        if not line.startswith("{"):
            continue
        try:
            j = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        res = j.get("Result") or {}
        if not res.get("IsFiltered"):
            continue
        cip = j.get("IP", "")
        if ip and cip != ip:
            continue
        qh = j.get("QH") or ""
        t = (j.get("T") or "")[11:19]
        rule = (res.get("Rule") or (res.get("Rules") or [{}])[0].get("Text", "")) if res.get("Rules") or res.get("Rule") else ""
        e = agg.setdefault(qh, [0, t, set(), rule])
        e[0] += 1
        e[1] = t
        e[2].add(cip)
    items = sorted(((qh, *v) for qh, v in agg.items()), key=lambda x: x[2])
    items = items[-n:] if n else items
    flt = f" (client {ip})" if ip else ""
    if not items:
        print(f"(aucun domaine bloqué{flt} dans les 5000 dernières lignes — relance PENDANT le chargement du jeu)")
        if not out.strip() and err.strip():
            print("[stderr]", err.strip()[:300])
        return
    print(f"=== domaines BLOQUÉS uniques{flt} — {len(items)} (récents EN BAS) ===")
    for qh, cnt, last, ips, rule in items:
        ipss = ",".join(sorted(ips))[:28]
        print(f"  {last}  x{cnt:<4} {qh:<46} <- {ipss:<18} {rule}")


def _recent(ip: str, n: int = 50):
    """TOUTES les requêtes récentes d'un client (allowed + bloquées), dédup,
    ⛔=bloqué. Pour voir le pattern DNS complet du jeu pendant le chargement."""
    cmd = f"sudo -n tail -n 5000 {QLOG} 2>/dev/null || tail -n 5000 {QLOG} 2>&1"
    out, err = _ssh_run(cmd)
    if out is None:
        print("ERR:", err)
        return
    agg = {}
    for line in out.splitlines():
        line = line.strip().rstrip(",")
        if not line.startswith("{"):
            continue
        try:
            j = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if ip and j.get("IP", "") != ip:
            continue
        qh = j.get("QH", "")
        t = (j.get("T") or "")[11:19]
        blk = bool((j.get("Result") or {}).get("IsFiltered"))
        e = agg.setdefault(qh, [0, t, False])
        e[0] += 1
        e[1] = t
        e[2] = e[2] or blk
    items = sorted(((qh, *v) for qh, v in agg.items()), key=lambda x: x[2])[-n:]
    print(f"=== requêtes {ip or 'tous'} — {len(items)} domaines (récents EN BAS, ⛔=bloqué) ===")
    for qh, cnt, last, blk in items:
        print(f"  {last}  {'BLOCK' if blk else '  ok '} x{cnt:<4} {qh}")


def _aaaa(mode: str):
    """off = AdGuard ne renvoie plus d'AAAA (aaaa_disabled: true) -> clients en
    IPv4-only (fix IPv6-externe-cassé). on = réactive. status = état."""
    if mode == "status":
        out, err = _ssh_run(f"sudo -n grep -niE 'aaaa_disabled' {AG_YAML} 2>/dev/null || echo '(clé absente -> AAAA actives par défaut)'")
        print(out if out is not None else f"ERR: {err}")
        return
    if mode not in ("off", "on"):
        print("usage: aaaa off | on | status")
        return
    val = "true" if mode == "off" else "false"
    script = r'''
Y=/opt/AdGuardHome/AdGuardHome.yaml; VAL=__VAL__
TS=$(date +%s); sudo -n cp "$Y" "${Y}.bak.${TS}"
sudo -n systemctl stop AdGuardHome
sudo -n python3 - "$Y" "$VAL" <<'PY'
import re, sys
p, val = sys.argv[1], sys.argv[2]
s = open(p).read()
if re.search(r'(?m)^(\s*)aaaa_disabled:\s*\w+', s):
    s = re.sub(r'(?m)^(\s*)aaaa_disabled:\s*\w+', lambda m: m.group(1) + 'aaaa_disabled: ' + val, s, count=1)
elif re.search(r'(?m)^dns:\s*$', s):
    s = re.sub(r'(?m)^(dns:\s*)$', lambda m: m.group(1) + '\n  aaaa_disabled: ' + val, s, count=1)
else:
    sys.stderr.write('section dns: introuvable\n'); sys.exit(2)
open(p, 'w').write(s); sys.stderr.write('SET aaaa_disabled=' + val + '\n')
PY
sudo -n systemctl start AdGuardHome; sleep 2
if systemctl is-active --quiet AdGuardHome; then echo "OK aaaa_disabled=$VAL :"; sudo -n grep -niE 'aaaa_disabled' "$Y"; else echo "ECHEC start -> ROLLBACK"; sudo -n cp "${Y}.bak.${TS}" "$Y"; sudo -n systemctl start AdGuardHome; sleep 1; systemctl is-active AdGuardHome; fi
'''.replace("__VAL__", val)
    out, err = _ssh_run(script, timeout=45)
    print(out if out is not None else f"ERR: {err}")
    if err and err.strip():
        print("[stderr]", err.strip()[:300])


def _dns64(mode: str):
    if mode == "status":
        out, err = _ssh_run(
            f"echo '=== AdGuard ==='; sudo -n grep -niE 'dns64|use_dns64' {AG_YAML} 2>/dev/null; "
            "echo '=== Unbound ==='; sudo -n grep -riE 'dns64|module-config' /etc/unbound/ 2>/dev/null | head")
        print(out if out is not None else f"ERR: {err}")
        return
    if mode != "off":
        print("usage: dns64 off | status")
        return
    # Coupe DNS64 dans AdGuard (use_dns64/dns64 true->false). SÛR : backup, stop,
    # sed, start, ROLLBACK si AdGuard refuse de redémarrer.
    script = r'''
Y=/opt/AdGuardHome/AdGuardHome.yaml
if ! sudo -n grep -qiE '(use_dns64:[[:space:]]*true|^[[:space:]]*dns64:[[:space:]]*true)' "$Y"; then
  echo "DNS64 déjà off (ou clé absente) côté AdGuard. État actuel :"; sudo -n grep -niE 'dns64' "$Y" || echo "(aucune clé dns64)"; exit 0
fi
TS=$(date +%s); sudo -n cp "$Y" "${Y}.bak.${TS}"
sudo -n systemctl stop AdGuardHome
sudo -n sed -i -E 's/(use_dns64:[[:space:]]*)true/\1false/; s/^([[:space:]]*dns64:[[:space:]]*)true/\1false/' "$Y"
sudo -n systemctl start AdGuardHome; sleep 2
if systemctl is-active --quiet AdGuardHome; then
  echo "OK DNS64 coupé côté AdGuard :"; sudo -n grep -niE 'dns64' "$Y"
else
  echo "ECHEC start -> ROLLBACK"; sudo -n cp "${Y}.bak.${TS}" "$Y"; sudo -n systemctl start AdGuardHome; sleep 1; systemctl is-active AdGuardHome
fi
'''
    out, err = _ssh_run(script, timeout=45)
    print(out if out is not None else f"ERR: {err}")
    if err and err.strip():
        print("[stderr]", err.strip()[:300])


def _inspect():
    cmd = (f"echo '--- AdGuard dns64 ---'; grep -iEn 'dns64|use_dns64|dns64_prefix' {AG_YAML} 2>/dev/null; "
           "echo '--- Unbound dns64 ---'; grep -riEn 'dns64|module-config' /etc/unbound/ 2>/dev/null | head -20; "
           "echo '--- AdGuard service ---'; systemctl is-active AdGuardHome 2>/dev/null")
    out, err = _ssh_run(cmd)
    print(out if out is not None else f"ERR: {err}")


def _allow(domain: str):
    if not domain or not all(c.isalnum() or c in ".-_" for c in domain):
        print("domaine invalide:", domain)
        return
    # SÛR : backup, stop, edit texte (pas de dép PyYAML), start, ROLLBACK si
    # AdGuard refuse de redémarrer (jamais de DNS down pour la maison).
    script = r'''
D="__DOMAIN__"; R="@@||${D}^"; Y=/opt/AdGuardHome/AdGuardHome.yaml
sudo -n grep -qF "$R" "$Y" && { echo "DEJA présent: $R"; exit 0; }
TS=$(date +%s); sudo -n cp "$Y" "${Y}.bak.${TS}"
sudo -n systemctl stop AdGuardHome
sudo -n python3 - "$Y" "$R" <<'PY'
import re, sys
p, rule = sys.argv[1], sys.argv[2]
s = open(p).read()
if rule in s:
    sys.exit(0)
if re.search(r'(?m)^user_rules:\s*\[\s*\]\s*$', s):
    s = re.sub(r'(?m)^user_rules:\s*\[\s*\]\s*$', "user_rules:\n  - '" + rule + "'", s)
elif re.search(r'(?m)^user_rules:\s*$', s):
    s = re.sub(r'(?m)^(user_rules:)\s*$', lambda m: m.group(1) + "\n  - '" + rule + "'", s, count=1)
else:
    sys.stderr.write("user_rules introuvable\n"); sys.exit(2)
open(p, 'w').write(s)
sys.stderr.write("EDIT OK\n")
PY
sudo -n systemctl start AdGuardHome; sleep 2
if systemctl is-active --quiet AdGuardHome; then
  echo "OK AdGuard actif — $R whitelisté"
else
  echo "ECHEC start -> ROLLBACK"; sudo -n cp "${Y}.bak.${TS}" "$Y"; sudo -n systemctl start AdGuardHome; sleep 1; systemctl is-active AdGuardHome
fi
'''.replace("__DOMAIN__", domain)
    out, err = _ssh_run(script, timeout=45)
    print(out if out is not None else f"ERR: {err}")
    if err and err.strip():
        print("[stderr]", err.strip()[:400])


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = sys.argv[1:]
    action = args[0] if args else "discover"
    if action == "discover":
        _discover()
    elif action == "blocked":
        _blocked(int(args[1]) if len(args) > 1 else 60,
                 args[2] if len(args) > 2 else None)
    elif action == "recent" and len(args) > 1:
        _recent(args[1], int(args[2]) if len(args) > 2 else 50)
    elif action == "dns64" and len(args) > 1:
        _dns64(args[1])
    elif action == "aaaa" and len(args) > 1:
        _aaaa(args[1])
    elif action == "inspect":
        _inspect()
    elif action == "allow" and len(args) > 1:
        _allow(args[1])
    elif action == "run" and len(args) > 1:
        out, err = _ssh_run(args[1])
        print(out if out is not None else f"ERR: {err}")
        if err and err.strip():
            print("[stderr]", err.strip()[:400])
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
