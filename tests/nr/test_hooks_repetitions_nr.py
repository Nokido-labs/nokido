"""NR -- P1a MESURE SEULE : repetitions des injections de hooks (decision owner 20/10, volet P1a).

La mesure du 22/10 attribue ~8 % du contexte aux hooks, dont ~61 % d'injections identiques. Le rapport doit
dire, PAR HOOK, combien d'injections, combien de caracteres, et quelle part est identique a l'injection
PRECEDENTE du meme hook. La comparaison est stricte : une valeur qui revient apres une autre valeur n'est pas
une repetition consecutive (piege d'une vue "deja vu dans le segment").
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_contexte_par_source as C  # noqa: E402
import forge_hooks_repetitions as H  # noqa: E402


def _hook(nom, texte, evenement="UserPromptSubmit", typ="hook_additional_context"):
    return {"type": "attachment",
            "attachment": {"type": typ, "hookName": nom, "hookEvent": evenement, "content": [texte]}}


def _hook_stdout(nom, texte, evenement="SessionStart"):
    """hook success reel : `content` et `stdout` portent le meme texte, sans `hookEvent` parfois."""
    return {"type": "attachment",
            "attachment": {"type": "hook_success", "hookName": nom, "hookEvent": evenement,
                           "stdout": texte, "exitCode": 0}}


def _par_hook(rapport):
    return {s["hook"]: s for s in rapport["hooks"]}


def test_le_rapport_compte_par_hook_et_compare_a_l_injection_precedente():
    a, b = "[sense] alerte cli_present\n", "[sense] alerte autre\n"
    lignes = [_hook("UserPromptSubmit:sense", a), _hook("UserPromptSubmit:sense", a),
              _hook("UserPromptSubmit:sense", b)]
    r = H.analyser_hooks(lignes)
    s = _par_hook(r)["UserPromptSubmit:sense"]
    assert s["injections"] == 3
    assert s["caracteres"] == 2 * len(a) + len(b)
    assert s["avec_precedent"] == 2
    assert s["injections_identiques"] == 1          # seule la 2e repete la 1re
    assert s["caracteres_identiques"] == len(a)
    assert s["part_injections_identiques"] == 0.5
    assert s["part_caracteres_identiques"] == len(a) / (2 * len(a) + len(b))


def test_une_valeur_qui_revient_apres_une_autre_n_est_pas_une_repetition_consecutive():
    a, b = "[memoire] etat A\n", "[memoire] etat B\n"
    r = H.analyser_hooks([_hook("UserPromptSubmit:memoire", a), _hook("UserPromptSubmit:memoire", b),
                          _hook("UserPromptSubmit:memoire", a)])
    s = _par_hook(r)["UserPromptSubmit:memoire"]
    assert s["injections"] == 3 and s["avec_precedent"] == 2
    assert s["injections_identiques"] == 0          # A B A : aucune suite identique
    assert s["part_caracteres_identiques"] == 0.0


def test_hook_success_est_mesure_et_son_stdout_sert_quand_content_manque():
    a = "[hook-integrity] 44 cablages verifies\n"
    r = H.analyser_hooks([_hook_stdout("SessionStart:startup", a),
                          _hook_stdout("SessionStart:startup", a)])
    s = _par_hook(r)["SessionStart:startup"]
    assert s["injections"] == 2 and s["injections_identiques"] == 1
    assert s["caracteres"] == 2 * len(a)


def test_l_extraction_reutilisee_donne_l_ordre_et_ignore_les_evenements_sans_contenu():
    lignes = [
        _hook("UserPromptSubmit:sense", "[sense] un\n"),
        {"type": "attachment", "attachment": {"type": "hook_cancelled", "hookName": "SessionStart:audit",
                                              "hookEvent": "SessionStart", "timedOut": True}},
        {"type": "attachment", "isSidechain": True,
         "attachment": {"type": "hook_additional_context", "hookName": "UserPromptSubmit:autre",
                        "hookEvent": "UserPromptSubmit", "content": ["ignore"]}},
        _hook("PostToolUse:gate", "[gate] deux\n", evenement="PostToolUse"),
    ]
    inj = C.injections_hooks(lignes)
    assert [i["hook"] for i in inj] == ["UserPromptSubmit:sense", "PostToolUse:gate"]
    assert inj[0]["evenement"] == "UserPromptSubmit" and inj[0]["texte"] == "[sense] un\n"


def test_un_contenu_chaine_n_est_pas_itere_caractere_par_caractere():
    ligne = _hook("UserPromptSubmit:sense", "[sense] chaine entiere\n")
    ligne["attachment"]["content"] = "[sense] chaine entiere\n"
    inj = C.injections_hooks([ligne])
    assert len(inj) == 1 and inj[0]["texte"] == "[sense] chaine entiere\n"


def test_aucune_injection_ne_casse_pas_le_rapport():
    r = H.analyser_hooks([{"type": "user", "message": {"role": "user", "content": "salut"}}])
    assert r["hooks"] == [] and r["totaux"]["injections"] == 0
    assert r["totaux"]["part_caracteres_identiques"] == 0.0


def test_le_point_d_entree_cli_ecrit_le_rapport_sans_toucher_la_transcription(tmp_path):
    a = "[langue] Reponds en francais\n"
    lignes = [_hook("UserPromptSubmit:langue", a), _hook("UserPromptSubmit:langue", a)]
    src = tmp_path / "t.jsonl"
    contenu = "\n".join(json.dumps(x) for x in lignes) + "\nligne illisible\n"
    src.write_text(contenu, encoding="utf-8")
    sortie = tmp_path / "r.json"
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "forge_hooks_repetitions.py"), str(src),
                        "--sortie", str(sortie)], capture_output=True, text=True, errors="replace", timeout=25)
    assert p.returncode == 0, p.stderr
    r = json.loads(sortie.read_text(encoding="utf-8"))
    assert r["lignes_illisibles"] == 1
    assert _par_hook(r)["UserPromptSubmit:langue"]["injections_identiques"] == 1
    assert src.read_text(encoding="utf-8") == contenu       # lecture seule, aucune reecriture
