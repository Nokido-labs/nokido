"""Non-regression P0 SECURITE : un type de bac inconnu ECHOUE FERME.

DEFAUT MESURE le 2026-09-01, en lecture seule, sur le hub reel :

    sandbox="local"                  -> desktop-xxxx\\laforgesbxoffline
    sandbox="online"                 -> NT AUTHORITY\\SYSTEM
    sandbox="trusted"                -> NT AUTHORITY\\SYSTEM   (SeTcb + SeDebug ACTIVES)
    sandbox="zzz_valeur_inexistante" -> NT AUTHORITY\\SYSTEM

Une entree INVALIDE obtenait PLUS de privileges qu'une entree valide. Cause : la
condition d'aiguillage testait `sandbox not in ("local", "")`, si bien qu'une valeur
inconnue passait pour un "type explicite", contournait le confinement par compte, puis
ne matchait aucune branche de `_exec_sandboxed` et tombait sur la branche finale, qui
execute `pwsh` in-process du hub. La valeur INVENTEE est la preuve decisive : le defaut
n'etait pas propre a `online`/`trusted`, il etait dans la SELECTION du confinement.

Ces tests portent sur l'EFFET de la garde, pas sur sa presence :
  1. les types RECONNUS restent acceptes -- on ne ferme pas un chemin voulu ;
  2. l'ABSENCE de valeur reste acceptee (comportement historique, SANDBOX_EXEC off) ;
  3. `online`, `trusted` et toute valeur inventee sont REFUSES ;
  4. le refus NOMME la forme correcte, sinon l'appelant repete la meme erreur ;
  5. les DEUX points de controle existent (entree + profondeur) : une frontiere de
     privilege ne tient pas sur un seul point.

Zero service externe : on importe le registre (0,14 s mesure) et on instancie SANS
`__init__` (`__new__`), car la garde ne depend que d'un attribut de CLASSE. On teste
ainsi le code REELLEMENT livre, et non une reecriture de la regle dans le test -- qui
serait une seconde verite et validerait n'importe quoi.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent.parent
SOURCE = RACINE / "app" / "forge_mcp_registry.py"
for _d in (RACINE / "app",):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

TYPES_RECONNUS = ("", "local", "console", "ps_clm", "docker", "windows", "wasm", "gvisor")
DOIVENT_ETRE_REFUSES = ("online", "trusted", "zzz_valeur_inexistante", "LOCAL ",
                        "sandbox", "None", "0", "system", "local ", "Local")


@pytest.fixture(scope="module")
def garde():
    import forge_mcp_registry as reg

    obj = reg.ToolRegistry.__new__(reg.ToolRegistry)
    if not hasattr(obj, "_sandbox_valide"):
        pytest.fail("la garde fail-closed est ABSENTE du registre : appliquer "
                    "tools/forge_patch_sandbox_failopen.py")
    return obj


def test_les_types_reconnus_restent_acceptes(garde):
    """On ferme le chemin que personne n'a choisi, jamais un chemin voulu."""
    for t in TYPES_RECONNUS:
        assert garde._sandbox_valide(t) == "", f"type legitime refuse : {t!r}"


def test_absence_de_valeur_reste_acceptee(garde):
    """SANDBOX_EXEC off => comportement historique ; il ne doit pas casser."""
    assert garde._sandbox_valide("") == ""
    assert garde._sandbox_valide(None) == ""


def test_online_et_trusted_sont_refuses(garde):
    """Les deux valeurs que la doctrine recommandait, et qui rendaient SYSTEM."""
    for t in ("online", "trusted"):
        refus = garde._sandbox_valide(t)
        assert refus, f"{t!r} accepte : le fail-open est de retour"
        assert "REFUSE" in refus


def test_toute_valeur_inconnue_est_refusee(garde):
    """LE test central du mandat : une valeur inventee ne s'execute JAMAIS."""
    for t in DOIVENT_ETRE_REFUSES:
        assert garde._sandbox_valide(t), f"valeur inconnue ACCEPTEE : {t!r}"


def test_le_refus_nomme_la_forme_correcte(garde):
    """Un refus muet fait repeter la meme erreur au tour suivant."""
    refus = garde._sandbox_valide("online")
    assert "network=true" in refus, "le refus n'indique pas comment obtenir l'egress"
    assert "trusted_script" in refus, "le refus n'indique pas la voie privilegiee legitime"
    assert "docker" in refus, "le refus n'enumere pas les types valides"


def test_les_deux_points_de_controle_existent():
    """Entree ET profondeur : une frontiere de privilege ne tient pas sur un seul."""
    src = SOURCE.read_text(encoding="utf-8")
    appels = src.count("self._sandbox_valide(sandbox)")
    assert appels >= 2, (
        f"un seul point de controle trouve ({appels}) : la validation d'entree et la "
        "garde en profondeur doivent coexister")
    assert src.index("self._sandbox_valide(sandbox)") < src.index('if sandbox == "console"'), \
        "la garde en profondeur doit PRECEDER le premier aiguillage de type"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
