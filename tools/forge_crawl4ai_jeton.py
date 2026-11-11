"""Crawl4AI 0.9 : jeton au COFFRE et recreation du conteneur (owner 2026-11-10 : MAJ 0.8.6 -> 0.9.4, jeton
ALEATOIRE au coffre, jeton du hub retire du conteneur).

Pourquoi un outil neuf : l'installeur (forge_install_prerequis) DECLARE seulement les images, aucun outil ne lance
le compose crawl4ai (retrieval_sweep « docker-compose.crawl4ai » : aucun lanceur) ; le keeper ne fait que
`docker start` du conteneur existant. CHANGELOG crawl4ai 0.9.0 : « set CRAWL4AI_API_TOKEN and send Authorization:
Bearer <token> on every request except GET /health » ; les clients lisent le meme secret
(forge_crawl_tool.entetes_crawl4ai).

  --jeton    cree CRAWL4AI_API_TOKEN au coffre machine s'il manque (lisible des comptes de service) ; jamais affiche.
  --recreer  pull puis `up -d --force-recreate` du compose, jeton injecte dans l'ENV du seul processus docker
             compose ; sortie nettoyee du jeton. A lancer sous un compte qui joint Docker (commande au tray).
NR : tests/nr/test_crawl4ai_jeton_et_compose_nr.py
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

__FORGE_COLOR__ = "digestif/crawl4ai : jeton au coffre et recreation du conteneur de crawl"

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.crawl4ai.yml"
CLE = "CRAWL4AI_API_TOKEN"
# Conteneur existant = laforge-crawl4ai-1 (cree sous l'ancien nom du depot). Sans -p, compose creerait
# nokido-crawl4ai-1 A COTE, et le keeper (premier conteneur d'ancetre unclecode/crawl4ai) pourrait relancer l'ancien.
PROJET = os.environ.get("NOKIDO_CRAWL4AI_PROJET", "laforge")


def _lire_coffre(cle):
    for p in (ROOT.parent, ROOT / "app"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    try:
        from nokido_agent.app.forge_secrets import get_secret
    except ImportError:
        from forge_secrets import get_secret
    return get_secret(cle) or ""


def _ecrire_coffre(cle, valeur):
    _lire_coffre(cle)  # amorce sys.path
    try:
        from nokido_agent.app.forge_secrets import set_secret
    except ImportError:
        from forge_secrets import set_secret
    return set_secret(cle, valeur)


def creer_jeton(lire=_lire_coffre, ecrire=_ecrire_coffre) -> dict:
    """Cree le jeton s'il manque. Ne rend JAMAIS sa valeur ; un jeton present n'est jamais ecrase (pas de rotation
    implicite : elle invaliderait les clients en vol)."""
    if lire(CLE):
        return {"etat": "DEJA_PRESENT", "cle": CLE}
    jeton = secrets.token_urlsafe(32)
    if not ecrire(CLE, jeton):
        return {"etat": "ECHEC_ECRITURE", "cle": CLE}
    return {"etat": "CREE", "cle": CLE, "longueur": len(jeton)}


def _nettoyer(texte, jeton):
    return (texte or "").replace(jeton, "<jeton>") if jeton else (texte or "")


def recreer(lire=_lire_coffre, lanceur=subprocess.run, timeout: int = 900) -> dict:
    """pull puis up -d --force-recreate, jeton dans l'environnement du processus compose SEULEMENT."""
    jeton = lire(CLE)
    if not jeton:
        return {"verdict": "REFUS_SANS_JETON", "motif": "%s absent du coffre : lancer --jeton d'abord" % CLE}
    env = dict(os.environ, **{CLE: jeton})
    etapes = []
    for sous in (["pull"], ["up", "-d", "--force-recreate"]):
        cmd = ["docker", "compose", "-p", PROJET, "-f", str(COMPOSE)] + sous
        p = lanceur(cmd, env=env, capture_output=True, text=True, errors="replace", timeout=timeout)
        etapes.append({"etape": sous[0], "rc": p.returncode,
                       "sortie": _nettoyer((p.stdout or "") + (p.stderr or ""), jeton)[-600:]})
        if p.returncode != 0:
            return {"verdict": "ECHEC_%s" % sous[0].upper(), "etapes": etapes}
    return {"verdict": "RECREE", "etapes": etapes}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--jeton", action="store_true")
    ap.add_argument("--recreer", action="store_true")
    a = ap.parse_args()
    r = creer_jeton() if a.jeton else recreer() if a.recreer else {"verdict": "RIEN", "motif": "--jeton ou --recreer"}
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r.get("etat") in ("CREE", "DEJA_PRESENT") or r.get("verdict") == "RECREE" else 1


if __name__ == "__main__":
    sys.exit(main())
