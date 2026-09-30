"""forge_endpoint_monitor — santé LIVE des endpoints LLM (cloud + local).

« Mieux monitorer mes endpoints possibles ». Probe GET /models (cheap, ne brûle pas de quota
d'inférence) avec la clé résolue par le MÊME chemin que les providers (forge_agent_proxy.
_load_api_key : vault forge_secrets > env > Nokido.env), masquée. Classe chaque endpoint :
ok / bad_key (401/403) / quota (429) / no_key / down. Croise avec forge_provider_canonical
(vault_key_for) pour révéler la clé canonique attendue (le « bon chemin »).

Usage : LAFORGE_PYTHON tools/forge_endpoint_monitor.py [--json out.json]
Importable : from forge_endpoint_monitor import monitor
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# (name, models_url, key_env|None=local)
TARGETS = [
    ("groq", "https://api.groq.com/openai/v1/models", "GROQ_API_KEY"),
    ("cerebras", "https://api.cerebras.ai/v1/models", "CEREBRAS_API_KEY"),
    ("sambanova", "https://api.sambanova.ai/v1/models", "SAMBANOVA_API_KEY"),
    ("openrouter", "https://openrouter.ai/api/v1/models", "OPENROUTER_API_KEY"),
    # Together ajoute le 2026-08-05 (cle owner -> coffre machine). Enjeu precis :
    # savoir s'il sert `bge-m3`. Tout l'index RAG est en BGE-M3 1024D (HuggingFace,
    # Cloudflare @cf/baai/bge-m3, NVIDIA baai/bge-m3) et MEME DIMENSION N'EST PAS
    # MEME ESPACE : un vecteur bge-large-en insere dans rag_chunks serait compare
    # par cosinus a des vecteurs bge-m3 et rendrait des resultats plausibles et
    # FAUX, sans erreur. D'ou --grep : on regarde le catalogue avant de brancher.
    ("together", "https://api.together.xyz/v1/models", "TOGETHER_API_KEY"),
    ("ollama", "http://127.0.0.1:11434/v1/models", None),
    ("lmstudio", "http://127.0.0.1:1234/v1/models", None),
    ("proxy_7777", "http://127.0.0.1:7777/v1/models", None),
]

_HTTP = {401: "bad_key", 403: "bad_key/forbidden", 429: "quota", 404: "path?", 400: "bad_req"}


def _key(env):
    """Clé masquée via le chemin canonique des providers (jamais la valeur brute)."""
    if not env:
        return None, "local"
    try:
        from nokido_agent.app.forge_agent_proxy import _load_api_key

        k = _load_api_key(env)
    except Exception:  # noqa: BLE001
        k = None
    if not k:
        return None, "NO_KEY"
    return k, f"{k[:4]}...{k[-3:]} (len{len(k)})"


def _feed(env, key, status):
    """Alimente la santé des clés (forge_key_rotation) — clés réelles seulement, fail-safe.
    N'est appelé que sur une VRAIE réponse HTTP (200/401/403/429), jamais sur erreur réseau
    (offline) qui ne dit rien de la clé."""
    if not env or not key:
        return
    try:
        from nokido_agent.app.forge_key_rotation import mark_http

        mark_http(env, key, status)
    except Exception:  # noqa: BLE001
        pass


def _ids(body: bytes) -> list:
    """Identifiants de modeles, quelle que soit l'enveloppe. Together rend une
    LISTE nue la ou OpenAI rend {"data": [...]} -- supposer une seule forme ferait
    lire « 0 modele » sur un catalogue plein, ce qui se conclurait a tort en
    « ce fournisseur n'a rien »."""
    try:
        d = json.loads(body)
    except Exception:  # noqa: BLE001
        return []
    items = d.get("data") if isinstance(d, dict) else d
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if isinstance(it, dict):
            out.append(str(it.get("id") or it.get("name") or ""))
        elif isinstance(it, str):
            out.append(it)
    return [x for x in out if x]


def probe(name, url, env, motif: str = ""):
    key, kmask = _key(env)
    headers = {"Content-Type": "application/json", "User-Agent": "nokido-sonde"}
    if key:
        headers["Authorization"] = "Bearer " + key
    t = time.time()
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=12)
        body = r.read()
        ids = _ids(body)
        n = len(ids) if ids else -1
        _feed(env, key, getattr(r, "status", 200))
        res = {"provider": name, "key": kmask, "status": getattr(r, "status", 200),
               "health": "ok", "models": n, "ms": int((time.time() - t) * 1000)}
        if motif:
            trouves = [i for i in ids if motif.lower() in i.lower()]
            res["motif"] = motif
            res["correspondances"] = trouves[:20]
            # Trois etats : trouve / absent du catalogue / catalogue illisible.
            res["verdict_motif"] = ("trouve" if trouves else
                                    ("absent du catalogue" if ids else "catalogue illisible"))
        return res
    except urllib.error.HTTPError as e:
        # Un 401/403 ne dit quelque chose de la CLE que s'il vient de l'API. Un WAF
        # refuse AVANT elle : alimenter la rotation sur ce signal met une cle SAINE au
        # rebut pour des heures. Mesure 2026-08-28 (trouvee par ANTIGRAVITY) : faute de
        # User-Agent, Cloudflare rendait 403 et GROQ_API_KEY / CEREBRAS_API_KEY sont
        # parties en quarantaine — d'ou un « Tous providers echoue » sur une tache
        # deleguee. L'en-tete a ete ajoute, mais le meme piege reste ouvert pour tout
        # refus de bord (geo-blocage, rate-limit edge, challenge) : la cause se corrige
        # ICI, pas seulement son occurrence du jour.
        # Trois etats, jamais deux : cle jugee mauvaise / cle jugee bonne / PAS JUGEE.
        _hdrs = getattr(e, "headers", None)

        def _entete(nom: str) -> str:
            try:
                return (_hdrs.get(nom) or "") if _hdrs else ""
            except Exception:  # noqa: BLE001 - en-tetes illisibles: on ne conclut pas
                return ""

        _ctype = _entete("content-type").lower()
        _au_bord = bool(_entete("cf-ray")) or "cloudflare" in _entete("server").lower()
        # Une API d'authentification repond en JSON ; du HTML sur un 401/403 vient
        # d'un intermediaire. Content-type ABSENT => on ne tranche pas.
        if not _au_bord and e.code in (401, 403) and _ctype and "json" not in _ctype:
            _au_bord = True
        if _au_bord and e.code in (401, 403):
            return {"provider": name, "key": kmask, "status": e.code,
                    "health": "bloque_au_bord (WAF/edge — cle NON jugee)",
                    "ms": int((time.time() - t) * 1000)}
        _feed(env, key, e.code)
        return {"provider": name, "key": kmask, "status": e.code,
                "health": _HTTP.get(e.code, f"http{e.code}"), "ms": int((time.time() - t) * 1000)}
    except Exception as e:  # noqa: BLE001
        return {"provider": name, "key": kmask, "status": "-", "health": "down",
                "err": repr(e)[:90], "ms": int((time.time() - t) * 1000)}


def monitor(motif: str = ""):
    res = [probe(n, u, e, motif) for (n, u, e) in TARGETS]
    try:
        from nokido_agent.app.forge_provider_canonical import vault_key_for

        for r in res:
            try:
                r["vault_key"] = vault_key_for(r["provider"])
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    ap.add_argument("--grep", default="",
                    help="motif d'identifiant de modele a chercher dans chaque catalogue "
                         "(ex: bge-m3) — rend trouve / absent / illisible")
    args = ap.parse_args()
    res = monitor(args.grep)
    out_path = args.json or r"C:/tmp/endpoint_monitor.json"
    try:
        Path(out_path).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    for r in res:
        line = f"{r['provider']:12} {r['health']:18} status={r['status']} key={r.get('key')} {r['ms']}ms"
        if r.get("models", 0) and r["models"] > 0:
            line += f" models={r['models']}"
        if r.get("vault_key"):
            line += f" vault={r['vault_key']}"
        print(line)
        if r.get("verdict_motif"):
            print(f"             motif '{r['motif']}' -> {r['verdict_motif']}"
                  + (f" : {', '.join(r['correspondances'])}" if r.get("correspondances") else ""))


if __name__ == "__main__":
    main()
