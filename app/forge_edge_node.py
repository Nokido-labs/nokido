# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = edge/edge-node-receiver
NOEUD EDGE — receveur de world-vector COTE NOEUD (ferme la boucle broadcast->receive).

GAP (roadmap edge P1 / debat 4096D) : forge_edge_fleet.broadcast_world_vector POSTe
l'etat-monde COMPRESSE (int8) aux noeuds edge (POST <url>/world_vector), mais AUCUN
noeud ne l'implementait -> broadcast = 404. Ce module = le programme qu'un noeud edge
(Linux/Android/Xbox, cf roadmap_edge_inference_fleet) lance pour RECEVOIR : decode le
codec, stocke le dernier etat-monde localement (inference locale du noeud), l'expose.
Symetrique du receveur HOST (app/web_hub/app.py POST /world_vector).

POURQUOI dedie (anti-dup, §3) : forge_edge_fleet = COORDINATEUR (broadcast/registry/
dispatch) ; app.py = receveur HOST (FastAPI, 1 endpoint parmi 50). Ici = un PROGRAMME
NOEUD autonome, STDLIB PURE (zero FastAPI/deps -> portable sur un edge maigre), qui ne
fait QUE recevoir + servir le world-vector. Reutilise forge_world_vector_codec (decode).

  LAFORGE_PYTHON app/forge_edge_node.py --serve --port 7460 --name edge-xbox
  LAFORGE_PYTHON app/forge_edge_node.py --selftest    # boucle broadcast->receive locale
"""
from __future__ import annotations
import os, sys, json, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer

APP = os.path.dirname(os.path.abspath(__file__))
if APP not in sys.path:
    sys.path.insert(0, APP)

NODE_NAME = os.environ.get("LAFORGE_EDGE_NODE_NAME", "edge-node")
_LAST = {"ts": None, "dim": None, "norm": None, "bytes": None, "_vec": None}

# Plafonds de corps. Un world-vector 4096D int8 pese ~4 Ko ; l'OTA est bornee pour qu'un
# envoi ne puisse remplir ni la RAM d'un edge maigre (VM DNS : 906 Mo) ni son disque.
_CORPS_MAX = {"/world_vector": 64 * 1024, "/ota": 16 * 1024 * 1024}


def _jeton_ota() -> tuple[str, str]:
    """Jeton OTA lu dans un FICHIER, jamais dans l'environnement : credential systemd
    (`LoadCredential=edge_ota_token:<chemin>` -> $CREDENTIALS_DIRECTORY/edge_ota_token) ou
    LAFORGE_EDGE_OTA_TOKEN_FILE. Rend (jeton, raison) : jeton vide = OTA fermee, et la raison
    distingue l'ABSENCE de configuration d'un fichier ILLISIBLE."""
    base = os.environ.get("CREDENTIALS_DIRECTORY") or ""
    chemin = os.environ.get("LAFORGE_EDGE_OTA_TOKEN_FILE") or (
        os.path.join(base, "edge_ota_token") if base else "")
    if not chemin:
        return "", "ota fermee : aucun jeton configure"
    try:
        with open(chemin, encoding="utf-8") as f:
            jeton = f.read().strip()
    except OSError as e:
        return "", f"ota fermee : jeton illisible ({type(e).__name__})"
    return (jeton, "") if jeton else ("", "ota fermee : jeton vide")


def _store(blob: bytes) -> dict:
    """Decode le world-vector compresse recu (int8 -> float32) et le stocke localement."""
    import numpy as np
    try:
        from nokido_agent.app import forge_world_vector_codec as wv
    except ImportError:
        # noeud deploye SEUL (VM, Pi) : le codec est pose a cote de ce fichier, et APP est
        # deja dans sys.path. Sans ce repli, /world_vector rendait 400 hors du depot.
        import forge_world_vector_codec as wv
    v = wv.dequantize(wv.unpack(blob))
    _LAST.update({"ts": time.time(), "dim": int(len(v)),
                  "norm": round(float(np.linalg.norm(v)), 4), "bytes": len(blob), "_vec": v})
    return {k: _LAST[k] for k in ("dim", "norm", "bytes")}


def _node_metrics() -> dict:
    """Metriques noeud best-effort, STDLIB pure (portable edge maigre : Android/Pi/Xbox)."""
    import platform
    m = {"ok": True, "node": NODE_NAME, "device_type": "edge-node",
         "os_version": None, "uptime_s": None, "mem_total_mb": None, "mem_used_mb": None}
    try:
        m["os_version"] = f"{platform.system()} {platform.release()}"
    except Exception:
        pass
    try:
        with open("/proc/uptime") as f:
            m["uptime_s"] = int(float(f.read().split()[0]))
    except Exception:
        pass
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                info[k.strip()] = int(v.strip().split()[0])  # kB
        total = info.get("MemTotal", 0) // 1024
        avail = info.get("MemAvailable", info.get("MemFree", 0)) // 1024
        if total:
            m["mem_total_mb"] = total
            m["mem_used_mb"] = total - avail
    except Exception:
        pass
    return m


class _Handler(BaseHTTPRequestHandler):
    timeout = 10  # serveur mono-fil : un client lent ne bloque pas le noeud indefiniment

    def _lire_corps(self, plafond: int):
        """Lit le corps SEULEMENT s'il est borne. Rend (octets, None) ou (None, (code, motif)) :
        le refus tombe AVANT la lecture, sur le Content-Length annonce."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None, (400, "Content-Length illisible")
        if n < 0:
            return None, (400, "Content-Length negatif")
        if n > plafond:
            return None, (413, f"corps de {n} o au-dela du plafond de {plafond} o")
        return self.rfile.read(n), None

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        p = self.path.rstrip("/")
        if p == "/world_vector":
            blob, refus = self._lire_corps(_CORPS_MAX[p])
            if refus:
                return self._json({"error": refus[1]}, refus[0])
            try:
                return self._json({"ok": True, "node": NODE_NAME, "received": _store(blob)})
            except Exception as e:  # noqa: BLE001
                return self._json({"error": str(e)[:120]}, 400)
        if p == "/ota":
            return self._recv_ota()
        return self._json({"error": "not found"}, 404)

    def _recv_ota(self):
        """Recoit un fichier OTA (headers X-OTA-Path, X-OTA-SHA256), verifie le sha256.

        FERMEE par defaut : un noeud edge ecoute sur le LAN, et une ecriture de fichier sans
        authentification y serait ouverte a tout poste du reseau. Elle ne s'ouvre qu'avec un
        jeton (fichier, cf `_jeton_ota`) et un en-tete X-Edge-Token egal, compare en temps
        constant ; le refus est rendu AVANT de lire le corps."""
        import hashlib
        import hmac
        jeton, raison = _jeton_ota()
        if not jeton:
            return self._json({"ok": False, "error": raison}, 403)
        recu = (self.headers.get("X-Edge-Token") or "").strip()
        if not hmac.compare_digest(recu.encode(), jeton.encode()):
            return self._json({"ok": False, "error": "jeton OTA refuse"}, 403)
        data, refus = self._lire_corps(_CORPS_MAX["/ota"])
        if refus:
            return self._json({"ok": False, "error": refus[1]}, refus[0])
        try:
            name = os.path.basename((self.headers.get("X-OTA-Path") or "").strip()) or "ota.bin"
            want = (self.headers.get("X-OTA-SHA256") or "").strip().lower()
            got = hashlib.sha256(data).hexdigest()
            if want and want != got:
                return self._json({"ok": False, "error": "sha256 mismatch", "sha256": got}, 400)
            dest_dir = os.environ.get(
                "LAFORGE_EDGE_OTA_DIR",
                os.path.join(os.path.expanduser("~"), ".nokido_edge", "ota"))
            os.makedirs(dest_dir, exist_ok=True)
            path = os.path.join(dest_dir, name)
            with open(path, "wb") as f:
                f.write(data)
            self._json({"ok": True, "node": NODE_NAME, "path": path,
                        "bytes": len(data), "sha256": got})
        except Exception as e:  # noqa: BLE001
            self._json({"error": str(e)[:120]}, 400)

    def do_GET(self):
        p = self.path.rstrip("/")
        if p in ("/world_vector/last", "/api/world_vector/last"):
            return self._json({k: _LAST[k] for k in ("ts", "dim", "norm", "bytes")})
        if p in ("/health", "/metrics", ""):
            return self._json(_node_metrics())
        self._json({"error": "not found"}, 404)

    def log_message(self, *a):  # silence access log
        pass


def serve(host: str = "127.0.0.1", port: int = 7460, name: str | None = None) -> None:
    """Boucle bloquante = le noeud edge tourne ce receveur en permanence (daemon/service)."""
    global NODE_NAME
    if name:
        NODE_NAME = name
    srv = HTTPServer((host, port), _Handler)
    print(f"[edge-node {NODE_NAME}] receveur world-vector -> http://{host}:{port}/world_vector")
    srv.serve_forever()


def selftest() -> dict:
    """Boucle LOCALE broadcast->receive : la flotte host diffuse, CE noeud recoit + decode."""
    import numpy as np
    from nokido_agent.app import forge_edge_fleet as ef
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        ef.register_edge("selftest-node", f"http://127.0.0.1:{port}",
                         capabilities={"world_vector": True})
        rng = np.random.default_rng(0)
        vec = rng.normal(size=4096).astype("float32")
        bc = ef.broadcast_world_vector(vec, timeout=3)
        time.sleep(0.3)
        recv = _LAST.get("_vec")
        cos = (float(np.dot(vec, recv) / (np.linalg.norm(vec) * np.linalg.norm(recv) + 1e-9))
               if recv is not None else 0.0)
        node_res = (bc.get("edges", {}) or {}).get("selftest-node")
        return {"ok": recv is not None and cos > 0.99, "port": port,
                "node_broadcast_result": node_res, "received_dim": _LAST.get("dim"),
                "received_bytes": _LAST.get("bytes"), "cos": round(cos, 4)}
    finally:
        srv.shutdown()


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7460)
    ap.add_argument("--name", default=None)
    args = ap.parse_args(argv)
    if args.serve and not args.selftest:
        serve(args.host, args.port, args.name)
        return 0
    r = selftest()
    print("=== EDGE-NODE selftest (broadcast->receive) ===")
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
