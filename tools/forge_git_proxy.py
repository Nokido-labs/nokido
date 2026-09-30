"""
FORGE INTELLIGENCE — forge_git_proxy [GREEN]
=============================================
Proxy CONNECT local : TOUTES les requêtes git (push/fetch/clone/ls-remote)
transitent par lui dès que git est configuré `http(s).proxy`. Contrôle par
HOST (allowlist) + audit complet. Couvre l'INGRESS et l'EGRESS (pas seulement
le push comme le hook v1).

RÉALITÉ TLS : HTTPS = tunnelé via CONNECT -> le proxy voit le HOST (en clair
dans `CONNECT host:443`) mais PAS le contenu chiffré. Donc :
  - proxy = contrôle/audit par host de TOUTES les requêtes (ce module).
  - contenu du PUSH = scan d'objets git (forge_git_egress, couche v1).
  - incontournable = WinDivert force tout 443 via ce proxy (forge_git_egress_lock).
Voir le contenu chiffré = MITM + CA cert (lourd, packfile binaire = inutile,
écarté par le multiplan).

Anti-dup (CLAUDE.md §3) : forge_web_egress = gateway fetch HTTP applicatif (POST
/fetch), forge_openai_proxy = proxy API LLM. AUCUN n'est un proxy CONNECT
transparent pour le transport git. Domaine neuf.

ACTIVATION (opt-in — sinon git casse si proxy down) :
  # démarrer le proxy (observe = log tout, tunnel tout) :
  LAFORGE_PYTHON tools/forge_git_proxy.py
  # ou enforce (deny les hosts non-allowlistés) :
  LAFORGE_PYTHON tools/forge_git_proxy.py --enforce
  # router git dessus (LOCAL au repo recommandé, pas --global) :
  git config --local http.proxy  http://127.0.0.1:7780
  git config --local https.proxy http://127.0.0.1:7780
Audit : sandbox/git_proxy.log
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"

import argparse
import json
import logging
import select
import socket
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGF = ROOT / "sandbox" / "git_proxy.log"
MANIFEST = ROOT / ".git-publish-rules.json"
DEFAULT_ALLOW = {"github.com", "codeberg.org", "gitlab.com",
                 "ssh.github.com", "objects.githubusercontent.com"}

log = logging.getLogger("forge_git_proxy")


def load_allow() -> set[str]:
    hosts = set(DEFAULT_ALLOW)
    try:
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for h in (m.get("proxy_allow_hosts") or []):
            hosts.add(str(h).lower())
    except Exception:
        pass
    return hosts


def _audit(line: str) -> None:
    try:
        LOGF.parent.mkdir(parents=True, exist_ok=True)
        with open(LOGF, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _host_allowed(host: str, allow: set[str]) -> bool:
    host = host.lower()
    return any(host == a or host.endswith("." + a) for a in allow)


class GitProxy:
    def __init__(self, host: str = "127.0.0.1", port: int = 7780,
                 allow: set[str] | None = None, enforce: bool = False):
        self.host, self.port = host, port
        self.allow = allow if allow is not None else load_allow()
        self.enforce = enforce  # True=deny non-listés ; False=observe (tunnel+log)
        self.stats = {"allowed": 0, "denied": 0, "error": 0}

    def serve(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(128)
        log.warning("git_proxy %s on %s:%s — allow=%s",
                    "ENFORCE" if self.enforce else "OBSERVE",
                    self.host, self.port, sorted(self.allow))
        try:
            while True:
                cli, _ = srv.accept()
                threading.Thread(target=self._handle, args=(cli,), daemon=True).start()
        except KeyboardInterrupt:
            log.warning("git_proxy stop — stats=%s", self.stats)
        finally:
            srv.close()

    def _handle(self, client: socket.socket) -> None:
        try:
            client.settimeout(15)
            req = b""
            while b"\r\n\r\n" not in req and len(req) < 65536:
                d = client.recv(4096)
                if not d:
                    client.close()
                    return
                req += d
            line = req.split(b"\r\n", 1)[0].decode("latin1", "replace")
            parts = line.split()
            if len(parts) < 2 or parts[0].upper() != "CONNECT":
                client.sendall(b"HTTP/1.1 501 Not Implemented\r\n\r\n")
                client.close()
                return
            hostport = parts[1]
            host = hostport.rsplit(":", 1)[0].lower()
            port = int(hostport.rsplit(":", 1)[1]) if ":" in hostport else 443
            ok = _host_allowed(host, self.allow)
            _audit(f"CONNECT host={host} port={port} allow={ok} enforce={self.enforce}")
            if not ok and self.enforce:
                self.stats["denied"] += 1
                log.warning("git_proxy DENY %s:%s", host, port)
                client.sendall(b"HTTP/1.1 403 Forbidden (forge_git_proxy)\r\n\r\n")
                client.close()
                return
            up = socket.create_connection((host, port), timeout=15)
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self.stats["allowed"] += 1
            self._relay(client, up)
        except Exception as e:  # noqa: BLE001
            self.stats["error"] += 1
            _audit(f"ERROR {e}")
            try:
                client.close()
            except Exception:
                pass

    @staticmethod
    def _relay(a: socket.socket, b: socket.socket) -> None:
        try:
            socks = [a, b]
            while True:
                r, _, _ = select.select(socks, [], [], 120)
                if not r:
                    break
                for s in r:
                    data = s.recv(8192)
                    if not data:
                        return
                    (b if s is a else a).sendall(data)
        except Exception:
            pass
        finally:
            for s in (a, b):
                try:
                    s.close()
                except Exception:
                    pass


def _selftest() -> int:
    p = GitProxy(enforce=True)
    print(f"allow = {sorted(p.allow)}")
    expect = {"github.com": True, "api.github.com": True, "ssh.github.com": True,
              "codeberg.org": True, "evil.example.com": False, "githubXcom": False}
    ok = True
    for h, exp in expect.items():
        got = _host_allowed(h, p.allow)
        flag = "OK" if got == exp else "FAIL"
        ok = ok and flag == "OK"
        print(f"  [{flag}] {h}: {'ALLOW' if got else 'DENY'} (attendu {'ALLOW' if exp else 'DENY'})")
    return 0 if ok else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Proxy CONNECT git (host-allowlist + audit)")
    ap.add_argument("--port", type=int, default=7780)
    ap.add_argument("--enforce", action="store_true", help="deny hosts non-allowlistés (défaut=observe)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(_selftest())
    GitProxy(port=a.port, enforce=a.enforce).serve()
