"""NR — preuve != parole : un OK_DONE n'est acquis qu'apres verification de son artefact.

Manque paye 3x le 27/09 (session 58073b5a) : OK_DONE de GEMINI sur `gh_run:36257981298` -- run
CANCELLED, vieux SHA -- pris pour un succes ; « figé » du monitor ; faux trou d'AGY. Constitution
semantique : REQUESTED != ACHIEVED, SIGNAL != PREUVE DE VIE. Le corps doit REFUSER un livrable dont le
pointer_ref ne resout pas vers un artefact present ET verifie.

`verdict_livrable` federe forge_swarm_evidence (arbitrer) : il ne cree pas de vérificateur parallele.
Hermetique : resolveurs injectes, aucun reseau, aucun subprocess.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from forge_swarm_evidence import resoudre_pointer_ref, verdict_livrable  # noqa: E402

# résolveurs de test : commit toujours présent+vérifié ; gh_run vérifié seulement si "ok" ;
# fichier présent seulement si "existe".
_RES = {
    "commit": lambda s: {"present": True, "verifie": True},
    "gh_run": lambda s: {"present": True, "verifie": (s == "ok")},
    "fichier": lambda s: {"present": (s == "existe"), "verifie": (s == "existe")},
}


def test_ok_done_avec_artefact_verifie_est_accepte():
    v = verdict_livrable({"intent": "OK_DONE", "pointer_ref": "commit:abc123"}, resolveurs=_RES)
    assert v.action == "accept"


def test_ok_done_sur_run_non_reussi_refuse():
    # cas GEMINI 27/09 : gh_run resout mais conclusion != success
    v = verdict_livrable({"intent": "OK_DONE", "pointer_ref": "gh_run:cancelled"}, resolveurs=_RES)
    assert v.action != "accept"


def test_ok_done_sans_pointer_ref_ne_conclut_pas():
    v = verdict_livrable({"intent": "OK_DONE"}, resolveurs=_RES)
    assert v.action != "accept"
    assert v.etat == "UNKNOWN"


def test_pointer_ref_scheme_inconnu_sabstient():
    # aucun resolveur pour ce schema -> non verifiable -> on n'accepte pas (fail-safe)
    v = verdict_livrable({"intent": "OK_DONE", "pointer_ref": "mystere:x"}, resolveurs=_RES)
    assert v.action != "accept"


def test_resoudre_ne_fabrique_jamais_de_preuve():
    r = resoudre_pointer_ref("mystere:x", {})
    assert r["present"] is False
    assert r["verifie"] is None
    r2 = resoudre_pointer_ref("", _RES)
    assert r2["present"] is False


def test_fichier_absent_refuse():
    v = verdict_livrable({"intent": "OK_DONE", "pointer_ref": "fichier:manquant"}, resolveurs=_RES)
    assert v.action != "accept"
