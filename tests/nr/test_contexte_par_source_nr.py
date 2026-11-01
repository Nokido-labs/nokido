"""NR -- P0 economie de contexte (decision owner 20/10) : ventiler une transcription Claude Code par source.

Le cout d'une session longue = taille du contexte x nombre de tours. L'instrument dit QUI occupe le contexte
(hook par balise, outil par nom, texte), ce qui s'y REPETE mot pour mot, et combien de tours chaque bloc est relu.
Il mesure seulement : il ne retire rien.
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


def _hook(evenement, texte):
    return {"type": "attachment", "attachment": {"type": "hook_additional_context", "content": [texte],
                                                 "hookName": evenement, "hookEvent": evenement},
            "rendered": [{"content": "<system-reminder>\n%s hook additional context: %s\n</system-reminder>"
                          % (evenement, texte)}]}


def _user(texte):
    return {"type": "user", "message": {"role": "user", "content": texte}}


def _appel(rid, blocs, total_entree):
    return {"type": "assistant", "requestId": rid,
            "message": {"id": rid, "role": "assistant", "content": blocs,
                        "usage": {"input_tokens": total_entree, "cache_read_input_tokens": 0,
                                  "cache_creation_input_tokens": 0}}}


def _resultat(tid, texte):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "content": texte}]}}


SENSE = "[sense] alerte cli_present\n[langue] Reponds en francais"


def _transcription():
    return [
        _hook("UserPromptSubmit", SENSE),
        _user("question une"),
        _appel("r1", [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "x.py"}}], 1000),
        _resultat("t1", "A" * 400 + "\n[HOOK:INBOX]\n  * msg 1\n[/HOOK:INBOX]"),
        _appel("r2", [{"type": "text", "text": "fini"}], 1300),
        _hook("UserPromptSubmit", SENSE),
        _user("question deux"),
        _appel("r3", [{"type": "text", "text": "ok"}], 1400),
    ]


def _par_source(rapport):
    return {s["source"]: s for s in rapport["sources"]}


def test_les_hooks_sont_ventiles_par_balise_et_la_repetition_est_comptee():
    s = _par_source(C.analyser(_transcription()))
    sense = s["hook:UserPromptSubmit:sense"]
    assert sense["occurrences"] == 2
    assert sense["car_repetes"] == sense["car"] // 2 > 0   # la 2e injection est identique mot pour mot
    assert "hook:UserPromptSubmit:langue" in s and "hook:UserPromptSubmit:enveloppe" in s


def test_le_resultat_d_outil_va_a_son_outil_et_la_boite_du_hub_a_part():
    s = _par_source(C.analyser(_transcription()))
    assert s["outil:Read"]["car"] >= 400
    assert "hub:inbox" in s and "[HOOK:INBOX]" not in json.dumps(s["outil:Read"])
    assert s["appel_outil:Read"]["occurrences"] == 1


def test_le_poids_compte_les_tours_ou_le_bloc_est_relu():
    s = _par_source(C.analyser(_transcription()))
    # le resultat de Read arrive apres l'appel r1 : relu par r2 et r3 = 2 tours
    assert s["outil:Read"]["tours_relus"] == 2
    # le texte de la question deux n'est relu que par r3
    assert s["user:texte"]["tours_relus"] == 1 + 3   # question une (3 tours) + question deux (1 tour)


def test_une_compaction_coupe_le_contexte_et_le_poids():
    lignes = _transcription() + [
        {"type": "system", "subtype": "compact_boundary"},
        {"type": "user", "isCompactSummary": True, "message": {"role": "user", "content": "resume " * 10}},
        _appel("r4", [{"type": "text", "text": "suite"}], 300),
    ]
    r = C.analyser(lignes)
    assert r["segments"] == 2
    final = {s["source"]: s for s in r["contexte_final"]}
    assert set(final) >= {"resume_compaction"} and "outil:Read" not in final
    assert _par_source(r)["outil:Read"]["tours_relus"] == 2   # la compaction arrete le compte


def test_l_ajustement_retrouve_le_prefixe_invisible():
    # entree reelle = 5000 + 0.25 x caracteres visibles : l'ajustement doit le retrouver
    lignes, car = [], 0
    for i in range(6):
        t = "x" * (400 * (i + 1))
        lignes.append(_user(t))
        car += len(t)
        lignes.append(_appel("r%d" % i, [], int(5000 + 0.25 * car)))
    cal = C.analyser(lignes)["calibration"]
    assert cal["source"] == "ajustement" and abs(cal["prefixe_tokens"] - 5000) < 50
    assert abs(cal["tokens_par_car"] - 0.25) < 0.01


def test_trop_peu_d_appels_la_calibration_le_dit_au_lieu_d_inventer():
    cal = C.analyser([_user("a"), _appel("r1", [], 100)])["calibration"]
    assert cal["source"] == "defaut" and cal["prefixe_tokens"] is None


def test_un_hook_dont_le_contenu_est_une_chaine_n_est_pas_lu_caractere_par_caractere():
    # mesure 22/10 : 84 523 « occurrences » sans_balise -- le contenu chaine etait itere caractere par caractere
    e = _hook("UserPromptSubmit", SENSE)
    e["attachment"]["content"] = SENSE
    s = _par_source(C.analyser([e, _appel("r1", [], 10)]))
    assert s["hook:UserPromptSubmit:sense"]["occurrences"] == 1
    assert "hook:UserPromptSubmit:sans_balise" not in s


def test_les_familles_resument_la_part_de_chaque_origine():
    r = C.analyser(_transcription())
    fam = {f["famille"]: f for f in r["familles"]}
    assert {"hook", "outil", "appel_outil", "user", "assistant", "hub"} <= set(fam)
    assert abs(sum(f["part"] for f in r["familles"]) - 1.0) < 1e-6


import pytest  # noqa: E402 -- borne pytest du test au chemin reel (cliquet test_sous_processus_borne_sous_la_suite_nr)


@pytest.mark.timeout(60)
def test_le_code_mode_compte_les_chaines_d_outils_sans_texte():
    # johnlindquist/claude (code-mode-principles) : des appels d'outils enchaines sans un mot entre eux pourraient
    # tenir dans UN script ; leurs resultats INTERMEDIAIRES resteraient hors du contexte
    lignes = [
        _user("go"),
        _appel("r1", [{"type": "tool_use", "id": "t1", "name": "Grep", "input": {}}], 100),
        _resultat("t1", "B" * 300),
        _appel("r2", [{"type": "tool_use", "id": "t2", "name": "Read", "input": {}}], 200),
        _resultat("t2", "C" * 50),
        _appel("r3", [{"type": "text", "text": "fini"}], 300),
    ]
    cm = C.analyser(lignes)["code_mode"]
    assert cm["chaines"] == 1 and cm["appels_en_chaine"] == 2
    assert cm["car_intermediaires"] == 300          # le resultat de r1, pas celui du dernier maillon
    assert cm["car_tours_intermediaires"] == 300 * 2  # relu par r2 et r3


def test_pas_de_chaine_quand_le_modele_parle_entre_deux_outils():
    cm = C.analyser(_transcription())["code_mode"]
    assert cm["chaines"] == 0 and cm["car_intermediaires"] == 0


def test_le_point_d_entree_cli_ecrit_le_rapport(tmp_path):
    src = tmp_path / "t.jsonl"
    src.write_text("\n".join(json.dumps(x) for x in _transcription()) + "\nligne illisible\n", encoding="utf-8")
    sortie = tmp_path / "r.json"
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "forge_contexte_par_source.py"), str(src),
                        "--sortie", str(sortie)], capture_output=True, text=True, errors="replace", timeout=25)
    assert p.returncode == 0, p.stderr
    r = json.loads(sortie.read_text(encoding="utf-8"))
    assert r["lignes_illisibles"] == 1 and r["sources"]


def test_poids_schemas_outils():
    outils = [{"name": "a", "description": "desc", "inputSchema": {"type": "object"}},
              {"name": "b", "description": "", "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}}}]
    r = C.poids_schemas_outils(outils, compter=lambda t: len(t) // 4)
    assert r["outils"] == 2 and r["par_outil"][0]["outil"] == "b"
    assert r["car_total"] == sum(x["car"] for x in r["par_outil"])
    assert r["par_outil"][1]["car_description"] == 4 and 0 < r["par_outil"][1]["part_description_car"] < 1


def test_poids_schemas_compteur_illisible_est_unknown(monkeypatch):
    monkeypatch.setattr(C, "_compteur_tokens", lambda: None)
    r = C.poids_schemas_outils([{"name": "a", "description": "d", "inputSchema": {}}])
    assert r["tokens_total"] is None and r["compteur"] == "UNKNOWN" and r["par_outil"][0]["tokens"] is None
