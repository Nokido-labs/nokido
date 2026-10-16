"""NR - Vérification statique du client navigateur Gemini Web (Tampermonkey) pour le connecteur des pairs.

Contrat (mission owner 15/10) :
- Seuls les outils autorisés de la surface figée du connecteur pair sont nommés.
- Transport HTTPS strict (aucun 'http://' dans le script).
- Aucune chaîne ressemblant à un jeton en dur ou secret.
- Aucun eval( ni Function(.
- Stockage du jeton isolé dans le gestionnaire de scripts (GM_setValue/GM_getValue), jamais dans localStorage.
- Aucun ciblage du /mcp du hub (port 8766), aucune exécution de code, aucune lecture locale.
- Provenance 'gemini_web' et quarantaine (OWNER_APPROBATION / EXTERNE_NON_VERIFIEE) bien intégrées.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "clients" / "gemini_web" / "nokido_pair.user.js"
README_PATH = ROOT / "clients" / "gemini_web" / "README.md"


@pytest.fixture(scope="session")
def _bac_des_organes():
    """Bac temporaire local au test statique, évitant un échec si D:\\Temp\\pytest-of-user est verrouillé."""
    import tempfile
    for candidat in (
        Path(tempfile.gettempdir()) / "gemini_nr_tmp",
        Path.home() / "AppData" / "Local" / "Temp" / "gemini_nr_tmp",
        ROOT / "sandbox" / "tmp_nr",
    ):
        try:
            candidat.mkdir(parents=True, exist_ok=True)
            probe = candidat / "probe.txt"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return candidat
        except Exception:
            continue
    return ROOT / "sandbox"


@pytest.fixture(scope="module")
def script_content() -> str:
    assert SCRIPT_PATH.exists(), f"Le fichier userscript n'existe pas : {SCRIPT_PATH}"
    return SCRIPT_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def outils_pair_mcp() -> set[str]:
    spec = importlib.util.spec_from_file_location("forge_pair_mcp", ROOT / "tools" / "forge_pair_mcp.py")
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return set(m.OUTILS)


def test_fichier_userscript_existe_et_lisible(script_content: str):
    assert len(script_content) > 1000
    assert len(script_content.splitlines()) > 50


def test_en_tete_userscript_tampermonkey_conforme(script_content: str):
    assert "// ==UserScript==" in script_content
    assert "// ==/UserScript==" in script_content
    assert "@match        https://gemini.google.com/*" in script_content
    assert "@grant        GM_xmlhttpRequest" in script_content
    assert "@grant        GM_setValue" in script_content
    assert "@grant        GM_getValue" in script_content
    assert "@grant        GM_deleteValue" in script_content


def test_seuls_les_outils_autorises_du_connecteur_pair_sont_nommes(script_content: str, outils_pair_mcp: set[str]):
    # Extrait la liste déclarée dans OUTILS_AUTORISES ou les tableaux du script
    match_lecture = re.search(r"OUTILS_LECTURE\s*=\s*\[(.*?)\];", script_content, re.DOTALL)
    match_pair = re.search(r"OUTILS_PAIR\s*=\s*\[(.*?)\];", script_content, re.DOTALL)
    assert match_lecture and match_pair

    declares = set(re.findall(r'"([a-z_]+)"', match_lecture.group(1) + " " + match_pair.group(1)))
    # Tous les outils déclarés doivent appartenir à la surface figée de forge_pair_mcp
    assert declares == outils_pair_mcp
    assert declares == {
        "etat_corps",
        "point_ssot",
        "recherche_rag",
        "journal_commits",
        "derniere_capsule",
        "proposer_fait",
        "envoyer_message",
        "soumettre_tache",
        "lire_reponses",
        "suivre",
    }


def test_aucun_outil_d_action_ni_hub_local_vise(script_content: str):
    # Outils d'action du hub ou d'autres surfaces interdits aux pairs
    interdits = [
        "governed_edit",
        "run_job",
        "nokido_hub",
        "trusted_script",
        "forge_machine_vault",
        "get_secret",
        "forge_mcp_registry",
    ]
    for outil in interdits:
        assert outil not in script_content, f"Outil d'action interdit détecté : {outil}"

    # Pas de ciblage du port 8766 du hub souverain
    assert "8766" not in script_content
    assert "127.0.0.1:8766" not in script_content
    assert "localhost:8766" not in script_content


def test_transport_https_strict_sans_aucun_http(script_content: str):
    # Aucun 'http://' n'est toléré dans le code ni les métadonnées (https strict)
    assert "http://" not in script_content

    # Vérification que la fonction de validation vérifie le préfixe https://
    assert 'startsWith("https://")' in script_content or "startsWith('https://')" in script_content


def test_aucun_jeton_en_dur_ni_secret_dans_le_script(script_content: str):
    # Motifs d'API keys et de secrets
    assert not re.search(r"sk-ant-[A-Za-z0-9_\-]{16,}", script_content)
    assert not re.search(r"ghp_[A-Za-z0-9]{20,}", script_content)
    assert not re.search(r"\b[0-9a-fA-F]{40,}\b", script_content)
    assert not re.search(r"Bearer\s+[A-Za-z0-9_\-\.]{25,}", script_content)


def test_aucun_eval_ni_constructeur_function(script_content: str):
    # Interdiction stricte de l'évaluation dynamique de code
    assert "eval(" not in script_content
    assert "new Function(" not in script_content
    assert "Function(" not in script_content


def test_stockage_securise_sans_localstorage(script_content: str):
    # Les jetons doivent être manipulés via GM_setValue / GM_getValue
    assert "GM_setValue" in script_content
    assert "GM_getValue" in script_content
    assert "GM_deleteValue" in script_content

    # Aucun usage de localStorage ou sessionStorage pour les jetons
    assert "localStorage" not in script_content
    assert "sessionStorage" not in script_content


def test_provenance_gemini_web_et_quarantaine_clairement_identifiees(script_content: str):
    # Client ID identifié comme gemini_web
    assert 'CLIENT_ID = "gemini_web"' in script_content
    assert "gemini_web" in script_content

    # Quarantaine et boîte d'approbation mentionnées
    assert "OWNER_APPROBATION" in script_content
    assert "EXTERNE_NON_VERIFIEE" in script_content


def test_documentation_readme_presente():
    assert README_PATH.exists()
    contenu = README_PATH.read_text(encoding="utf-8")
    assert "nokido_pair.user.js" in contenu
    assert "gemini_web" in contenu
    assert "https://" in contenu
    assert "@connect" in contenu


def test_controle_origine_avant_chaque_requete_http(script_content: str):
    """Contrôle d'origine à l'exécution : toute requête GM_xmlhttpRequest doit viser
    l'origine exacte (même schéma https, même hôte, même port) de l'URL publique sauvegardée.
    """
    # Présence de la fonction de validation d'origine stricte
    assert "function verifierOrigineCible" in script_content

    # Vérification que le schéma https:, l'hôte et le port sont vérifiés via .origin
    assert ".origin !== " in script_content or ".origin ===" in script_content
    assert 'urlCibleObj.protocol !== "https:"' in script_content or "urlCibleObj.protocol" in script_content
    assert 'urlPubliqueObj.protocol !== "https:"' in script_content or "urlPubliqueObj.protocol" in script_content

    # Refus journalisé en cas d'incohérence
    assert "Refus de requête" in script_content

    # Vérification que l'exécution de GM_xmlhttpRequest est protégée par le contrôle d'origine
    assert "function executerRequeteHttpSecurisee" in script_content
    assert "verifierOrigineCible(options.url)" in script_content

    # Vérification que chaque point d'appel réseau (/token échange, /token refresh, /mcp)
    # effectue le contrôle d'origine
    assert 'verifierOrigineCible(urlToken)' in script_content
    assert 'verifierOrigineCible(urlMcp)' in script_content


def test_suppression_verificateur_apres_echange(script_content: str):
    """Le vérificateur PKCE (nokido_oauth_verifier) doit être supprimé du stockage
    après usage lors de l'échange OAuth, qu'il y ait succès OU échec.
    """
    # La fonction traiterRetourOAuthSiPresent doit exister
    assert "function traiterRetourOAuthSiPresent" in script_content

    # Découpage du corps de traiterRetourOAuthSiPresent
    corps_fonction = script_content.split("function traiterRetourOAuthSiPresent")[1].split("function assurerJetonValide")[0]

    # Vérification de la suppression de nokido_oauth_verifier
    assert 'GM_deleteValue("nokido_oauth_verifier")' in corps_fonction

    # Vérification que la suppression est exécutée en cas d'échec/erreur (nettoyerSecretsEchange, finally, onerror)
    assert "finally" in corps_fonction or corps_fonction.count('GM_deleteValue("nokido_oauth_verifier")') >= 2
    assert "onerror" in corps_fonction

