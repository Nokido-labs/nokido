"""NR -- Le superviseur journalise ses refus d'authentification (401).

Dette de regulation mesuree le 17/10/2026 :
logs/supervisor/laforge-master.log : 0 ligne 401/unauthorized le 16/10, alors que
manage_forge_lifecycle a recu « HTTP 401 » trois fois ce jour-la -- refus MUET,
cause trouvee seulement en lisant le client.

Au point ou une mutation /supervisor/* est refusee pour authentification dans
handleCtrl (supervisor.ts), le superviseur doit appeler log(...) avec :
- la route demandee (p),
- la methode HTTP (req.method),
- le nom d'appelant DECLARE (en-tete LaForge-Agent-Name, ou « inconnu » s'il manque).

REGLE DE SECURITE STRICTE (OpSec) :
JAMAIS le jeton presente, sa fin, ni son empreinte ne doivent entrer dans le log.

Ce test lit le source TypeScript de proxy_deno/core/supervisor.ts.
Test pur : zero service externe, aucune dependance reseau ni base de donnees.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SUP = ROOT / "proxy_deno" / "core" / "supervisor.ts"


@pytest.fixture(scope="module")
def src() -> str:
    assert SUP.exists(), f"superviseur introuvable : {SUP}"
    return SUP.read_text(encoding="utf-8", errors="replace")


def _branche_refus(src_code: str) -> str:
    """Isole le bloc de refus 401 sur echec d'authentification dans handleCtrl."""
    assert "handleCtrl" in src_code, "handleCtrl introuvable dans supervisor.ts"
    idx_ctrl = src_code.index("async function handleCtrl")
    idx_gate = src_code.find("!_supervisor_auth_ok(req)", idx_ctrl)
    assert idx_gate > 0, "gate !_supervisor_auth_ok(req) introuvable dans handleCtrl"
    debut = src_code.rfind("if (", idx_ctrl, idx_gate)
    assert debut > 0, "debut du bloc if introuvable"
    fin_401 = src_code.find("401);", idx_gate)
    assert fin_401 > 0, "retour 401 introuvable dans le bloc de refus"
    fin = src_code.find("}", fin_401)
    assert fin > 0, "accolade fermante du bloc if introuvable"
    return src_code[debut:fin + 1]


def test_le_fichier_supervisor_existe():
    """Garde-fou : supervisor.ts doit exister et etre non-vide."""
    assert SUP.exists(), "supervisor.ts n'existe pas"
    assert SUP.stat().st_size > 10_000, "supervisor.ts anormalement court"


def test_la_branche_de_refus_appelle_log(src: str):
    """Au point de refus d'authentification, le superviseur doit appeler log(...)."""
    bloc = _branche_refus(src)
    assert "log(" in bloc, (
        "le superviseur ne journalise aucun de ses refus d'authentification : "
        "refus muet dans handleCtrl (absence de log(...) dans le bloc 401)"
    )


def test_le_journal_contient_route_et_methode(src: str):
    """Le journal doit mentionner la route et la methode HTTP refusees."""
    bloc = _branche_refus(src)
    m_log = re.search(r"log\((.*?)\);", bloc, re.DOTALL)
    assert m_log, "appel log(...) introuvable dans la branche de refus"
    contenu_log = m_log.group(1)
    assert "req.method" in contenu_log, "la methode HTTP (req.method) n'est pas transmise a log(...)"
    # Resserre a l'integration (17/10) : `"p" in contenu_log` etait vrai pour presque toute chaine.
    assert "${p}" in contenu_log or "${url.pathname}" in contenu_log, (
        "la route refusee (p) n'est pas transmise a log(...)"
    )


def test_le_nom_declare_ne_peut_pas_forger_une_ligne_de_journal(src: str):
    """Revue d'integration (17/10) : l'en-tete LaForge-Agent-Name est fourni par l'APPELANT ; un retour a la ligne y
    forgerait une fausse ligne de journal. Seuls les caracteres imprimables passent, longueur bornee."""
    bloc = _branche_refus(src)
    assert "replace(/[^\\x20-\\x7E]/g" in bloc and ".slice(0, 64)" in bloc, bloc


def test_le_journal_declare_appelant_avec_repli_inconnu(src: str):
    """Le journal doit mentionner l'appelant declare (LaForge-Agent-Name) ou 'inconnu'."""
    bloc = _branche_refus(src)
    # Verification de la lecture de l'en-tete LaForge-Agent-Name
    assert "LaForge-Agent-Name" in bloc or "laforge-agent-name" in bloc, (
        "l'en-tete d'identite LaForge-Agent-Name n'est pas lu dans la branche de refus"
    )
    # Verification du repli 'inconnu'
    assert '"inconnu"' in bloc or "'inconnu'" in bloc, (
        "le repli 'inconnu' est absent lorsque l'en-tete d'agent manque"
    )
    # L'appel log doit inclure la variable ou l'expression de l'agent declare
    m_log = re.search(r"log\((.*?)\);", bloc, re.DOTALL)
    assert m_log, "appel log(...) introuvable dans la branche de refus"
    contenu_log = m_log.group(1)
    assert "agent" in contenu_log, "le nom d'appelant declare n'est pas inclus dans le log(...)"


def test_jamais_de_jeton_ni_empreinte_dans_le_journal(src: str):
    """OpSec : le journal ne doit JAMAIS contenir le jeton, sa fin ni son empreinte."""
    bloc = _branche_refus(src)
    m_log = re.search(r"log\((.*?)\);", bloc, re.DOTALL)
    assert m_log, "appel log(...) introuvable dans la branche de refus"
    contenu_log = m_log.group(1).lower()

    # Mots ou motifs representant un jeton, une tranche ou une empreinte
    interdits = [
        "tok",
        "token",
        "authorization",
        "bearer",
        "secret",
        "sha",
        "hash",
        "digest",
        "slice",
        "substring",
        "empreinte",
        "fingerprint",
    ]
    for mot in interdits:
        assert mot not in contenu_log, (
            f"terme sensible '{mot}' trouve dans log(...) du refus : "
            "interdiction stricte de journaliser le jeton, sa fin ou son empreinte"
        )


def test_la_decision_de_refus_reste_inchangee(src: str):
    """Le refus reste un refus : statut 401 et error unauthorized."""
    bloc = _branche_refus(src)
    assert "401" in bloc, "le code de statut 401 doit etre maintenu"
    assert '"unauthorized"' in bloc or "'unauthorized'" in bloc, (
        "le corps d'erreur unauthorized doit etre maintenu"
    )
    assert "return jsonResp(" in bloc, "la branche doit retourner immediatement la reponse 401"


def test_garde_du_garde():
    """Verifie que le test detecte fidelement l'absence de journal et les fuites."""
    # Cas 1 : code sans log (etat historique) -> l'assertion log( doit echouer
    bloc_sans_log = (
        '  if (p.startsWith("/supervisor/") && !_supervisor_auth_ok(req)) {\n'
        '    return jsonResp({ error: "unauthorized", path: p }, 401);\n'
        '  }\n'
    )
    assert "log(" not in bloc_sans_log

    # Cas 2 : code qui fuite le token dans le log -> l'interdiction doit mordre
    bloc_avec_fuite = (
        '  if (p.startsWith("/supervisor/") && !_supervisor_auth_ok(req)) {\n'
        '    const tok = req.headers.get("authorization");\n'
        '    log(`refus ${p} token=${tok}`);\n'
        '    return jsonResp({ error: "unauthorized", path: p }, 401);\n'
        '  }\n'
    )
    m_fuite = re.search(r"log\((.*?)\);", bloc_avec_fuite)
    assert m_fuite
    assert "token" in m_fuite.group(1).lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
