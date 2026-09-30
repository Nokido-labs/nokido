# -*- coding: utf-8 -*-
"""NR — la chaîne WASM : défaut `_start`, et jamais un échec SANS motif.

__FORGE_COLOR__ = "immunitaire/guard : non-regression de la chaine d execution wasm"

CE QUI A ÉTÉ PAYÉ (2026-09-06). Le bac `sandbox="wasm"` posait
`func_name = _rest[0] if _rest else "run"`. Or `"run"` n'est le nom d'aucune convention :
une COMMANDE WASI exporte `_start`. Conséquence : tout module passé sans nom de fonction
échouait sur les **trois** backends d'affilée (Deno, wasmtime natif, pont WasmEdge), et un
module `wasm32-wasip1` — le cas SWE-bench, qui n'expose QUE `_start` — était tout
simplement **inatteignable**.

Et l'échec était ILLISIBLE : chaque couche écrasait le motif de la précédente, jusqu'à un
`"wasm bridge failed"` nu quand `stderr` était vide. Trois backends refusaient, l'appelant
en voyait un seul, sans `rc` ni `stdout`. C'est ce qui a fait diagnostiquer « chaîne WASM
morte » alors que les trois backends étaient SAINS — mesuré le même jour : wasmtime natif
rend `add(3,4)=7` depuis le compte sandbox, et le pont WSL/WasmEdge rend `rc=0 stdout=7`.

Les deux gardes ci-dessous sont donc indissociables : le bon défaut rend la capacité
atteignable, le motif rend l'échec diagnosticable.
"""

from __future__ import annotations

import ast
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

REGISTRY = ROOT / "app" / "forge_mcp_registry.py"
CERVELET = ROOT / "app" / "forge_wasm_cervelet.py"


def _defauts_func_name() -> list:
    """Valeurs par défaut du `func_name` du bac wasm, lues par AST (pas par grep :
    un commentaire qui CITE l'ancienne valeur ne doit pas faire passer le test)."""
    arbre = ast.parse(REGISTRY.read_text(encoding="utf-8", errors="replace"))
    vus = []
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Assign):
            continue
        cibles = [t.id for t in n.targets if isinstance(t, ast.Name)]
        if "func_name" not in cibles:
            continue
        # func_name = _rest[0] if _rest else <defaut>
        if isinstance(n.value, ast.IfExp) and isinstance(n.value.orelse, ast.Constant):
            vus.append(n.value.orelse.value)
        elif isinstance(n.value, ast.Constant):
            vus.append(n.value.value)
    return vus


def test_le_defaut_du_bac_est_la_fonction_wasi():
    defauts = _defauts_func_name()
    assert defauts, "aucun `func_name` par defaut trouve dans le bac wasm"
    for d in defauts:
        assert d != "run", (
            "`run` n'est le nom d'aucune convention wasm : ce defaut rendait tout module "
            "WASI inatteignable et faisait echouer les trois backends a la suite")
        assert d == "_start", f"defaut inattendu {d!r} — une COMMANDE WASI exporte `_start`"


def test_le_motif_du_premier_essai_est_conserve():
    """Trois backends qui echouent sans dire lequel a refuse = diagnostic impossible."""
    src = REGISTRY.read_text(encoding="utf-8", errors="replace")
    assert "_deno_err" in src, (
        "le motif de l'essai Deno doit survivre au passage aux backends suivants")


def _cervelet_avec_pont(reponse_pont: dict, wasmtime_present: bool = False):
    """Charge le cervelet avec un pont FACTICE : le test doit rester hermetique
    (aucun wsl, aucun subprocess, aucun reseau)."""
    os.environ.setdefault("LAFORGE_CERVELET_WSL_IP", "127.0.0.1")  # evite `wsl` a l'import
    import forge_wasm_cervelet as C  # noqa: PLC0415

    faux = types.ModuleType("forge_wasm_bridge")
    faux.submit_wasm = lambda *a, **k: dict(reponse_pont)  # noqa: ARG005
    sys.modules["forge_wasm_bridge"] = faux
    sys.modules["nokido_agent.tools.forge_wasm_bridge"] = faux
    C._wasmtime_exe = lambda: (r"C:\faux\wasmtime.exe" if wasmtime_present else None)
    return C


def test_un_stderr_vide_ne_devient_pas_un_echec_nu(monkeypatch):
    """`stderr` vide n'est PAS un motif : rendre rc et stdout, sinon l'echec du pont est
    indiscernable d'un backend absent."""
    C = _cervelet_avec_pont({"ok": False, "rc": 3, "stdout": "sortie partielle", "stderr": ""})
    r = C.run_wasm("peu importe.wasm")
    err = str(r.get("error") or "")
    assert "wasm bridge failed" not in err, "l'echec nu est revenu"
    assert "rc=3" in err, f"le code de retour doit etre rendu : {err!r}"
    assert "sortie partielle" in err, "ce que le module a quand meme ecrit doit etre rendu"


def test_les_deux_backends_en_echec_sont_TOUS_DEUX_nommes(monkeypatch):
    """Natif KO + pont KO : l'appelant doit voir les DEUX, sinon il repare le mauvais."""
    C = _cervelet_avec_pont({"ok": False, "rc": 1, "stdout": "", "stderr": "pont: refus"},
                            wasmtime_present=True)
    C._run_wasm_native = lambda *a, **k: {"ok": False, "error": "natif: refus",  # noqa: ARG005
                                          "backend": "wasmtime-native"}
    err = str(C.run_wasm("peu importe.wasm").get("error") or "")
    assert "pont: refus" in err and "natif: refus" in err, (
        f"un seul des deux backends est nomme : {err!r}")


def test_le_succes_du_pont_reste_un_succes():
    """Un garde qui casse le chemin nominal ne garde rien."""
    C = _cervelet_avec_pont({"ok": True, "rc": 0, "stdout": "7", "stderr": ""})
    r = C.run_wasm("peu importe.wasm")
    assert r.get("ok") is True and r.get("result") == "7", r


def test_spin_absent_ne_se_confond_pas_avec_spin_illisible():
    """ABSENT (pas installe) et ILLISIBLE (pas pu regarder) sont deux verdicts
    DIFFERENTS. Les confondre envoie reparer une installation qui existe -- ou fait
    conclure a une capacite presente alors qu'on n'a rien pu mesurer."""
    C = _cervelet_avec_pont({"ok": True, "rc": 0, "stdout": "", "stderr": ""})
    C.spin_exe = lambda: None
    assert C.health_spin()["etat"] == "ABSENT"

    C.spin_exe = lambda: r"C:\quelque\part\spin.exe"

    def _explose(*a, **k):  # noqa: ARG001
        raise OSError("subprocess interdit ici")

    import subprocess as _sp  # noqa: PLC0415

    vrai_run, _sp.run = _sp.run, _explose
    try:
        etat = C.health_spin()["etat"]
    finally:
        _sp.run = vrai_run
    assert etat == "ILLISIBLE", f"un refus d'executer n'est pas une absence : {etat}"


def test_le_path_prime_sur_le_chemin_de_depannage():
    """`C:\\tmp` est un emplacement de depannage : une installation propre doit
    l'emporter SANS qu'on edite le code (piege du lanceur fige dans C:\\tmp)."""
    src = CERVELET.read_text(encoding="utf-8", errors="replace")
    # Le localisateur est FACTORISE (cliquet clones) : on garde l'ORDRE, qui est la
    # propriete a proteger, sans dependre du nom du binaire cherche.
    i_which = src.find("_sh.which(nom)")
    assert i_which > 0, "le localisateur doit interroger le PATH"
    assert src.find("for c in candidats", i_which) > i_which, (
        "le PATH doit etre interroge AVANT les chemins codes en dur")
    assert "_localiser_exe(\"spin\"" in src, "spin doit passer par le localisateur commun"
    assert "_SPIN_CANDIDATES" in src


def test_le_gotcha_du_cache_reste_ecrit():
    """`-C cache=n` : sans lui, wasmtime ecrit dans HOME=C:\\Users\\Default et prend un
    Acces refuse. Le retirer casserait le backend natif sous TOUS les comptes du hub."""
    src = CERVELET.read_text(encoding="utf-8", errors="replace")
    assert '"cache=n"' in src or "'cache=n'" in src, (
        "le cache doit rester desactive : profil Default non inscriptible")
