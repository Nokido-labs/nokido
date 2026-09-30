# -*- coding: utf-8 -*-
"""NR — S19 : le confinement de la forge dynamique est le RING, pas la denylist.

Registre de sécurité, ligne S19, état `À VÉRIFIER` depuis le 2026-09-19 (« rapporté
par la délégation agy, non re-mesuré par moi »). Re-mesuré le 2026-09-22 ; ce NR grave
la mesure pour que l'enquête ne soit pas refaite, et pour qu'une régression la casse.

CE QUI A ÉTÉ MESURÉ, et qui n'est pas une opinion
=================================================
`app/forge_tool_forger._validate_safe` est une **denylist AST**. Elle compare le nom
écrit AU SITE D'APPEL (`func.id` / `func.attr`) à une liste de noms interdits. Sur six
formes soumises au validateur réel, **quatre passent** :

    REFUSE   eval('...')                      -> le nom est littéralement `eval`
    REFUSE   __import__('os')                 -> idem
    ACCEPTE  g = eval ; g('...')              -> le site d'appel dit `g`
    ACCEPTE  importlib.import_module('os')    -> ni le module ni l'appel ne sont listés
    ACCEPTE  ().__class__.__base__.__subclasses__()
    ACCEPTE  getattr(builtins, 'ev'+'al')('...')

C'est le motif `CALL_SITE != DECISION_SITE` : **le nom sous lequel une fonction est
appelée n'est pas la fonction appelée.** Une denylist de noms ne peut pas être étanche,
et le code le DIT déjà — docstring de `forge_call_dynamic` : « PAS un sandbox airtight
(l'aliasing peut contourner la denylist) — le ring reste le confinement principal ».

Donc la question utile n'est pas « la denylist est-elle étanche ? » (non, par
construction) mais **« le confinement qu'elle désigne existe-t-il vraiment ? »**.

CE QUE CE NR GARDE — trois portes, pas une
==========================================
1. La FORGE (`forge_forge_tool`, seul écrivain d'un `.py` exécutable) n'est atteignable
   par AUCUNE surface MCP. C'est ce qui rend le défaut NON RÉALISÉ aujourd'hui :
   `mécanisme présent != défaut réalisé`. L'exposer refermerait la chaîne complète
   « payload MCP -> code LLM -> fichier -> exec » d'un seul geste, et ce test tomberait.
2. Le ring 2 est CONSOMMÉ par le handler, pas seulement déclaré dans une table.
   Un garde dont personne ne lit le verdict ne garde rien (motif payé 4 fois, registre).
3. Tout outil forgé présent sur le disque est SUIVI PAR GIT. Un `.py` exécutable non
   suivi échappe à la revue et à la CI tout en étant chargé par `_load_tool`.

Ce que ce NR ne prouve PAS, et le dit : il lit le TEXTE de `forge_mcp_registry` pour les
points 1 et 2, il n'exerce pas le hub vivant. Une ABSENCE textuelle est un signal fort
(on ne peut pas exposer un symbole sans l'écrire) ; une PRÉSENCE textuelle ne prouverait
pas l'effet. La limite est ici, nommée.
"""

import re
import subprocess
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git ls-files (l.157)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_tool_forger as F  # noqa: E402

REGISTRY_SRC = (ROOT / "app" / "forge_mcp_registry.py").read_text(
    encoding="utf-8", errors="replace"
)

# Formes mesurées le 2026-09-22 contre le validateur RÉEL.
_CONTOURNEMENTS = {
    "alias local d'appel": "def f():\n    g = eval\n    return g('1+1')\n",
    "importlib.import_module": (
        "def f():\n    import importlib as _i\n"
        "    return _i.import_module('os').getcwd()\n"
    ),
    "parcours de __subclasses__": "def f():\n    return ().__class__.__base__.__subclasses__()\n",
    "getattr sur builtins": (
        "def f():\n    import builtins as b\n"
        "    return getattr(b, 'ev' + 'al')('1+1')\n"
    ),
}
_REFUSES_ATTENDUS = {
    "eval littéral": "def f():\n    return eval('1+1')\n",
    "__import__ littéral": "def f():\n    return __import__('os').getcwd()\n",
}


def test_la_denylist_refuse_bien_les_formes_litterales():
    """CONTRE-ÉPREUVE : sans elle, les `ACCEPTE` ci-dessous seraient vrais par impuissance.

    Un validateur qui accepte TOUT accepterait aussi l'aliasing — et le test suivant
    passerait sans rien mesurer.
    """
    for nom, code in _REFUSES_ATTENDUS.items():
        assert F._validate_safe(code) is not None, (
            f"le validateur laisse passer la forme littérale « {nom} » : "
            "il n'est plus un filtre du tout, et le test d'aliasing ne mesure plus rien"
        )


def test_la_denylist_ast_n_est_pas_une_frontiere_de_securite():
    """La denylist laisse passer l'aliasing. Ce n'est pas un bug : c'est sa nature.

    Ce test EXISTE pour empêcher qu'on la prenne un jour pour la frontière. S'il devient
    rouge, c'est que `_validate_safe` a changé de nature (allowlist, analyse de flux) —
    bonne nouvelle, mais qui doit être CONSTATÉE et redocumentée, pas subie.
    """
    passants = [nom for nom, code in _CONTOURNEMENTS.items() if F._validate_safe(code) is None]
    assert passants, (
        "AUCUNE forme d'aliasing ne passe plus : `_validate_safe` a changé de nature. "
        "Relire S19 au registre et requalifier — le confinement principal peut avoir bougé."
    )
    # Une borne dit COMBIEN : le dénominateur est émis même en vert.
    print(
        f"[S19] {len(passants)}/{len(_CONTOURNEMENTS)} formes d'aliasing passent la denylist : "
        f"{passants}"
    )


def test_la_forge_n_est_atteignable_par_aucune_surface_mcp():
    """`forge_forge_tool` écrit un `.py` que `_load_tool` exécutera. Personne ne l'expose.

    C'est CE fait qui rend le défaut non réalisé. Il est fragile : une seule ligne
    ajoutée au catalogue suffirait à refermer la chaîne.
    """
    assert "forge_forge_tool" not in REGISTRY_SRC, (
        "`forge_forge_tool` apparaît désormais dans forge_mcp_registry : la FORGE devient "
        "atteignable depuis une surface. Or la denylist ne tient pas (test ci-dessus). "
        "Avant d'exposer : rendre `_validate_safe` étanche OU empêcher `_call_sandboxed` "
        "de retomber in-process en silence."
    )
    # Le catalogue dynamique n'expose que les deux génériques d'APPEL.
    i = REGISTRY_SRC.find("_forge_dynamic_catalog")
    assert i > 0, "`_forge_dynamic_catalog` introuvable — la structure a changé, relire S19"
    exposes = sorted(set(re.findall(r'"name":\s*"([a-z_]+)"', REGISTRY_SRC[i:i + 2600])))
    assert exposes == ["forge_call_dynamic", "forge_list_dynamic_tools"], (
        f"le catalogue dynamique expose autre chose que les deux génériques : {exposes}"
    )


def test_le_ring_2_est_consomme_par_le_handler_pas_seulement_declare():
    """Une entrée dans `_TOOL_MIN_RING` est une DÉCLARATION. Le refus est un EFFET."""
    assert re.search(r'"forge_call_dynamic"\s*:\s*2', REGISTRY_SRC), (
        "`forge_call_dynamic` n'est plus déclaré à ring 2 dans _TOOL_MIN_RING"
    )
    h = REGISTRY_SRC.find("async def _handle_forge_dynamic")
    assert h > 0, "`_handle_forge_dynamic` introuvable"
    corps = REGISTRY_SRC[h:h + 900]
    assert re.search(r"if ring > 2", corps), (
        "le handler des outils forgés ne refuse plus ring > 2 : la table déclare un "
        "plancher que le chemin réel n'applique pas"
    )


def test_tout_outil_forge_present_sur_le_disque_est_suivi_par_git():
    """Un `.py` exécutable non suivi échappe à la revue ET à la CI, et sera chargé."""
    dyn = ROOT / "app" / "forge_tools_dynamic"
    sur_disque = {p.name for p in dyn.glob("*.py")} if dyn.exists() else set()
    if not sur_disque:
        return  # rien à garder ; l'absence n'est pas un échec
    # `errors="replace"` : un subprocess en mode texte SANS lui fait crasher
    # `_readerthread` dès qu'un octet non décodable passe — anti-régression de
    # l'incident 47 Go, signalé par le gate firehose au commit de ce fichier.
    out = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(ROOT), "ls-files", "app/forge_tools_dynamic/"],
        capture_output=True, text=True, errors="replace", timeout=60,
    )
    if out.returncode != 0:
        # ILLISIBLE n'est pas CONFORME : on le dit plutôt que de conclure au vert.
        import pytest
        pytest.skip(f"git illisible depuis ce compte (rc={out.returncode}) — couverture NON établie")
    suivis = {Path(l).name for l in out.stdout.split() if l.endswith(".py")}
    non_suivis = sorted(sur_disque - suivis)
    print(f"[S19] {len(sur_disque)} outil(s) forgé(s) sur disque, {len(suivis)} suivi(s) par git")
    assert not non_suivis, (
        f"outil(s) forgé(s) NON suivi(s) par git, donc hors revue et hors CI, "
        f"et pourtant chargeables par _load_tool : {non_suivis}"
    )
