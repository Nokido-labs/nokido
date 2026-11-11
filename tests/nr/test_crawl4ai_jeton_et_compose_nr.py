"""NR -- MAJ Crawl4AI 0.8.6 -> 0.9.4 (owner 10/11 : jeton ALEATOIRE au coffre ; jeton du hub RETIRE du conteneur).

Constats : le compose versionne (depot PUBLIC) portait `CRAWL4AI_API_TOKEN=demo-token-if-needed` en clair et passait
FORGE_MCP_TOKEN (jeton du hub) a une image tierce dont la 0.9.4 corrige une fuite des variables d'environnement.
Contrats :
  1. `creer_jeton` : absent -> jeton fort ecrit au coffre, JAMAIS rendu ; present -> rien n'est reecrit ;
  2. `recreer` : sans jeton au coffre, rien ne tourne ; avec, pull puis up --force-recreate, jeton dans l'ENV du
     processus seulement, et toute sortie nettoyee du jeton ;
  3. compose : image 0.9.4, jeton par variable, aucun FORGE_*, liaison 127.0.0.1, restart no, memoire bornee.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_crawl4ai_jeton as J  # noqa: E402


def test_creer_jeton_sans_jamais_le_rendre():
    ecrits = {}
    r = J.creer_jeton(lire=lambda k: "", ecrire=lambda k, v: ecrits.update({k: v}) or True)
    assert r["etat"] == "CREE" and len(ecrits["CRAWL4AI_API_TOKEN"]) >= 40
    assert ecrits["CRAWL4AI_API_TOKEN"] not in repr(r)
    ecrits.clear()
    r = J.creer_jeton(lire=lambda k: "deja-la", ecrire=lambda k, v: ecrits.update({k: v}) or True)
    assert r["etat"] == "DEJA_PRESENT" and not ecrits


def test_recreer_injecte_le_jeton_et_nettoie_la_sortie():
    appels = []

    def _lanceur(cmd, **k):
        appels.append((cmd, k["env"].get("CRAWL4AI_API_TOKEN")))
        return SimpleNamespace(returncode=0, stdout="ok secret-xyz fin", stderr="")

    assert J.recreer(lire=lambda k: "", lanceur=_lanceur)["verdict"] == "REFUS_SANS_JETON" and not appels
    r = J.recreer(lire=lambda k: "secret-xyz", lanceur=_lanceur)
    assert appels[0][0][-1] == "pull" and appels[1][0][-3:] == ["up", "-d", "--force-recreate"]
    # conteneur existant = laforge-crawl4ai-1 : sans -p, compose cree nokido-crawl4ai-1 a cote, et le keeper
    # (`ps -a --filter ancestor=unclecode/crawl4ai`, premier nom) pourrait relancer l'ancien 0.8.6
    assert all(c[0][c[0].index("-p") + 1] == "laforge" for c in appels)
    assert all(t == "secret-xyz" for _c, t in appels)
    assert r["verdict"] == "RECREE" and "secret-xyz" not in repr(r)


def test_compose_sans_valeur_en_clair_ni_jeton_du_hub():
    import pytest
    f = ROOT / "docker-compose.crawl4ai.yml"
    if not f.exists():  # ignore par git (.gitignore:164) : config LOCALE du poste, absente d'un checkout CI
        pytest.skip("docker-compose.crawl4ai.yml non versionne : controle actif sur le poste seulement")
    src = f.read_text(encoding="utf-8")
    assert "image: unclecode/crawl4ai:0.9.4" in src
    assert "CRAWL4AI_API_TOKEN=${CRAWL4AI_API_TOKEN}" in src and "demo-token" not in src
    assert "FORGE_" not in src
    assert '"127.0.0.1:11235:11235"' in src and 'restart: "no"' in src and "mem_limit: 3g" in src
