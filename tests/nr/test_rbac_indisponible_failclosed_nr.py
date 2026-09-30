"""NR — un garde d'autorisation INDISPONIBLE ne vaut jamais une autorisation.

Mesure du 2026-09-12, `forge_mcp_registry`, dispatch des tools :

    try:
        from ...forge_mcp_rbac import check_tool_capability
        _rbac_ok, _rbac_reason = check_tool_capability(name, agent, ring)
        if not _rbac_ok:
            return {"error": "forbidden", ...}
    except ImportError:
        pass          # <-- aucune verification, en silence

`forge_mcp_rbac` est la SECONDE table d'autorisation (la premiere etant
`_TOOL_MIN_RING`), et c'est elle qui protege les tools les plus puissants —
`ps_run` et `ps_agent` y sont declares a `TRUST ED=2`. Si ce module devient
inimportable — erreur de syntaxe introduite, dependance manquante, renommage de
namespace — l'autorisation disparait SANS TRACE et tous les tools passent.

C'est `garde indisponible -> ALLOW`, le motif central de ce chantier.

CE QUI REND LE DURCISSEMENT SANS RISQUE MESURE : le module s'importe
aujourd'hui (`_MODE = "enforce"`, `_ENFORCE = True`, mesures du meme jour), donc
cette branche n'est PAS empruntee en fonctionnement normal. La fermer ne change
rien au comportement actuel ; elle protege d'une regression future.

NUANCE CONSERVEE : seul `ImportError` est capture. Une exception LEVEE PAR
`check_tool_capability` se propage deja, donc ce cas est fail-closed par
construction. Le trou est etroit et precisement delimite — ne pas l'elargir en
capturant `Exception`, ce qui creerait le fail-open qu'on ferme ici.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
REGISTRE = RACINE / "app" / "forge_mcp_registry.py"
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _bloc_rbac() -> str:
    """Fenêtre autour du garde RBAC.

    CORRECTION du 2026-09-12 : la fenêtre valait 1 200 caractères et le regex
    n'acceptait que `except ImportError:`. Après le correctif — qui ajoute un
    commentaire de justification et la forme `except ImportError as e:` — les
    deux tests ne trouvaient plus la branche et échouaient pour un défaut
    D'INSTRUMENT, pas de fond. Un test qui ne lit plus ce qu'il croit lire
    rapporte une fausse régression.
    """
    if not REGISTRE.is_file():
        pytest.skip(f"registre absent: {REGISTRE}")
    src = REGISTRE.read_text(encoding="utf-8", errors="replace")
    i = src.find("check_tool_capability")
    assert i != -1, "le garde RBAC a disparu du dispatch"
    bloc = src[max(0, i - 400): i + 4000]
    assert "except ImportError" in bloc, (
        "la branche de repli est hors de la fenetre lue — agrandir la fenetre "
        "avant de conclure a sa disparition")
    return bloc


def test_le_garde_rbac_est_toujours_cable():
    """Contrôle positif : sans appel, les tests suivants seraient vides."""
    bloc = _bloc_rbac()
    assert "check_tool_capability(" in bloc, "le garde n'est plus APPELE"
    assert "forbidden" in bloc, "le refus RBAC a disparu"


def test_le_module_rbac_est_importable_aujourd_hui():
    """Prémisse du durcissement : si ce test devient rouge, la branche de repli
    redevient un chemin réel et le durcissement change alors le comportement."""
    import forge_mcp_rbac as RB

    assert hasattr(RB, "check_tool_capability")
    assert RB._ENFORCE is True, "le RBAC n'est plus en mode enforce"


def test_import_error_ne_laisse_pas_passer_en_silence():
    """ROUGE ATTENDU avant correction.

    `pass` nu sur `except ImportError` = autorisation par indisponibilité.
    """
    bloc = _bloc_rbac()
    m = re.search(r"except ImportError(?:\s+as\s+\w+)?:\s*\n\s*(.+)", bloc)
    assert m, "la branche except ImportError a disparu"
    suite = m.group(1).strip()
    assert not suite.startswith("pass"), (
        "fallback OPEN : `except ImportError: pass` — un garde indisponible "
        "autorise tout, sans trace (ligne: %r)" % (suite,))


def test_l_indisponibilite_est_tracee_et_refusee():
    """ROUGE ATTENDU. Le refus doit être explicite ET journalisé : un garde qui
    s'éteint en silence ne se diagnostique jamais."""
    bloc = _bloc_rbac()
    apres = re.split(r"except ImportError(?:\s+as\s+\w+)?:", bloc, maxsplit=1)
    assert len(apres) == 2, "branche introuvable"
    corps = apres[1][:2000]
    assert "forbidden" in corps or "SECURITY" in corps, (
        "l'indisponibilite du garde ne produit aucun refus")
    assert "critical" in corps.lower() or "error" in corps.lower(), (
        "l'indisponibilite du garde n'est pas journalisee en niveau eleve")


def test_la_capture_reste_etroite():
    """Contrôle négatif : ne pas « corriger » en capturant Exception, ce qui
    avalerait les vraies erreurs du garde et recréerait un fail-open plus large."""
    bloc = _bloc_rbac()
    assert "except Exception" not in bloc.split("check_tool_capability", 1)[1][:800], (
        "la capture a ete elargie a Exception : les erreurs du garde seraient "
        "avalees au lieu de se propager")
