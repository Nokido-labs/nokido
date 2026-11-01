# -*- coding: utf-8 -*-
"""NR -- chantiers symbiose (owner 31/10) : carte d'attention derivee, economie etag, rayon d'impact en observation.

Trois vues LUES dans des journaux existants (zero ecriture nouvelle), qui disent ILLISIBLE plutot que 0 :
- forge_network_logger.carte_attention : journal d'actes (ts chaine, extrait caviarde portant chemin/symbole) ;
- forge_token_cache.bilan_economie : token_savings.jsonl (cle `tokens_evites`) ;
- forge_callgraph_jit.signatures_publiques_changees / observer_rayon_impact : blocs SEARCH/REPLACE de governed_edit.
"""
import json
import time
from datetime import datetime

import forge_callgraph_jit as CG
import forge_network_logger as NL
import forge_token_cache as TC


def _acte(ts, outil, extrait, agent="CLAUDE"):
    return json.dumps({"ts": datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S"), "outil": outil,
                       "agent": agent, "extrait": extrait})


def test_carte_attention_fenetre_ordre_et_compte_des_actes_sans_chemin(tmp_path, monkeypatch):
    now = time.time()
    j = tmp_path / "actes.jsonl"
    j.write_text("\n".join([
        _acte(now - 4000, "read", '{"action": "file", "path": "app/vieux.py"}'),          # hors fenetre
        _acte(now - 300, "read_function_body", '{"file_path": "app/a.py", "function_name": "f"}'),
        _acte(now - 200, "governed_edit", "path=app/b.py (120 car. blocs)", agent="AGY"),
        _acte(now - 100, "read", '{"action": "file", "path": "app/a.py"}'),
        _acte(now - 50, "read", '{"action": "tail_logs"}'),                               # sans chemin
        _acte(now - 10, "web_search", '{"query": "x"}'),                                   # hors outils
    ]) + "\n", encoding="utf-8")
    monkeypatch.setattr(NL, "_JOURNAL_ACTES", j)
    c = NL.carte_attention(fenetre_s=1800, n=7, maintenant=now)
    chemins = [f["chemin"] for f in c["fichiers"]]
    assert chemins == ["app/a.py", "app/b.py"], chemins          # plus recent d'abord, le vieux exclu
    a = c["fichiers"][0]
    assert a["lectures"] == 2 and a["ecritures"] == 0 and a["symboles"] == ["f"]
    assert c["fichiers"][1]["ecritures"] == 1 and c["fichiers"][1]["agents"] == ["AGY"]
    assert c["actes_sans_chemin"] == 1 and "lignes" in c["borne"]
    assert all("etag" in f for f in c["fichiers"])


def test_carte_attention_borne_au_nombre_de_fichiers(tmp_path, monkeypatch):
    now = time.time()
    j = tmp_path / "actes.jsonl"
    j.write_text("\n".join(_acte(now - i, "read", '{"path": "app/m%d.py"}' % i) for i in range(10)) + "\n",
                 encoding="utf-8")
    monkeypatch.setattr(NL, "_JOURNAL_ACTES", j)
    assert len(NL.carte_attention(n=7, maintenant=now)["fichiers"]) == 7


def test_bilan_economie_lit_tokens_evites_et_dit_illisible_sans_journal(tmp_path):
    assert TC.bilan_economie(base_dir=tmp_path)["etat"] == "ILLISIBLE"     # absent n'est pas 0
    now = time.time()
    (tmp_path / "token_savings.jsonl").write_text("\n".join(json.dumps(e) for e in [
        {"horodatage": now - 10, "chemin": "app/a.py", "mode": "INCHANGE", "tokens_evites": 900},
        {"horodatage": now - 20, "chemin": "app/a.py", "mode": "DIFF", "tokens_evites": 300},
        {"horodatage": now - 999999, "chemin": "app/z.py", "mode": "INCHANGE", "tokens_evites": 5},
    ]) + "\n", encoding="utf-8")
    b = TC.bilan_economie(fenetre_s=3600, maintenant=now, base_dir=tmp_path)
    assert b["etat"] == "MESURE" and b["tokens_evites"] == 1200
    assert b["par_mode"]["INCHANGE"] == {"appels": 1, "tokens_evites": 900}
    assert b["fichiers_les_plus_economes"][0] == {"chemin": "app/a.py", "tokens_evites": 1200}


BLOCS = """<<<<<<< SEARCH
def publique(a, b):
    return a
def _privee(x):
    return x
def stable(x: int):
    return x
=======
def publique(a, b, c):
    return a
def _privee(x, y):
    return x
def stable(x: int):
    return x * 2
>>>>>>> REPLACE"""


def test_signatures_publiques_changees_dans_les_blocs():
    assert CG.signatures_publiques_changees(BLOCS) == ["publique"]      # privee ignoree, corps seul = stable
    assert CG.signatures_publiques_changees("") == []


def test_signatures_normalisees_par_ast_sans_faux_positif():
    blocs = ("<<<<<<< SEARCH\ndef f(x=(1, 2), cb: 'Callable[[int], str]' = None):\n    pass\n"
             "def g(a,\n      b):\n    pass\n=======\n"
             "def f(x=(1,2),   cb: 'Callable[[int], str]'=None):  # reformate seulement\n    return 1\n"
             "def g(a, b, c):\n    pass\n>>>>>>> REPLACE")
    assert CG.signatures_publiques_changees(blocs) == ["g"]       # f reformate : pas un changement
    coupe = "<<<<<<< SEARCH\ndef h(a,\n=======\ndef h(a, b):\n    pass\n>>>>>>> REPLACE"
    assert CG.signatures_publiques_changees(coupe) == ["h"]       # en-tete coupe = TRONQUEE, dit comme change


def test_observation_antirebond_par_chemin_et_fonction(tmp_path, monkeypatch):
    appels = []
    monkeypatch.setattr(CG, "get_function_dependencies", lambda f, p: appels.append(f) or {"callers": []})
    monkeypatch.setattr(CG, "_DERNIERE_OBSERVATION", {})
    journal = tmp_path / "obs.jsonl"
    for _ in range(3):
        assert CG.observer_rayon_impact("app/rafale.py", BLOCS, journal=journal) == ["publique"]
    for _ in range(50):
        if journal.exists() and journal.read_text(encoding="utf-8").strip():
            break
        time.sleep(0.05)
    time.sleep(0.1)
    assert len(journal.read_text(encoding="utf-8").splitlines()) == 1     # 3 editions, 1 mesure


def test_carte_attention_dit_le_risque_de_collision_et_les_lectures_totales(tmp_path, monkeypatch):
    now = time.time()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "chaud.py").write_text("x = 1\n", encoding="utf-8")
    chaud = "app/chaud.py"            # les actes portent des chemins RELATIFS au depot
    j = tmp_path / "actes.jsonl"
    j.write_text("\n".join([
        _acte(now - 30, "governed_edit", "path=%s (10 car. blocs)" % chaud, agent="AGY"),
        _acte(now - 600, "governed_edit", "path=app/tiede.py (10 car. blocs)"),
        _acte(now - 20, "read", '{"path": "app/tiede.py"}'),
    ]) + "\n", encoding="utf-8")
    monkeypatch.setattr(NL, "_JOURNAL_ACTES", j)
    c = NL.carte_attention(maintenant=now, racine=tmp_path)
    par = {f["chemin"]: f for f in c["fichiers"]}
    assert par[chaud]["risque_collision"] is True and par[chaud]["ecrivain"] == "AGY"
    assert par["app/tiede.py"]["risque_collision"] is False          # ecrit il y a 10 min : plus en chirurgie
    assert c["lectures_totales"] == 1
    premier = par[chaud]["etag"]
    assert not premier.startswith("ILLISIBLE")
    second = {f["chemin"]: f for f in NL.carte_attention(maintenant=now, racine=tmp_path)["fichiers"]}
    assert second[chaud]["etag"] == premier                          # memoise sur (mtime, taille)


def test_consigne_attention_lignes_imperatives_collision_en_tete(tmp_path, monkeypatch):
    now = time.time()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "lu.py").write_text("a = 1\n", encoding="utf-8")
    j = tmp_path / "actes.jsonl"
    j.write_text("\n".join([
        _acte(now - 10, "read", '{"path": "app/lu.py"}'),
        _acte(now - 60, "governed_edit", "path=app/chirurgie.py (10 car. blocs)", agent="AGY"),
    ]) + "\n", encoding="utf-8")
    monkeypatch.setattr(NL, "_JOURNAL_ACTES", j)
    texte = NL.consigne_attention(maintenant=now, racine=tmp_path)
    lignes = texte.strip().splitlines()
    assert lignes[0].startswith("[CARTE D'ATTENTION")
    assert "app/chirurgie.py" in lignes[1] and "RISQUE DE COLLISION" in lignes[1] and "AGY" in lignes[1]
    assert 'si_etag="' in lignes[2] and "app/lu.py" in lignes[2]
    vide = tmp_path / "vide.jsonl"
    vide.write_text("", encoding="utf-8")
    monkeypatch.setattr(NL, "_JOURNAL_ACTES", vide)
    assert NL.consigne_attention(maintenant=now) == ""             # carte vide : consigne inchangee


def test_executeur_prefixe_la_consigne_et_respecte_l_interrupteur(monkeypatch):
    import importlib
    from tools import forge_task_executor as TE
    # le module que l'executeur importe REELLEMENT (espace de noms du hub), pas l'alias du test
    reel = importlib.import_module("nokido_agent.app.forge_network_logger")
    monkeypatch.setattr(reel, "consigne_attention", lambda *a, **k: "[CARTE]\n\n")
    monkeypatch.delenv("LAFORGE_CARTE_DELEGATION", raising=False)
    assert TE._avec_carte_attention("travail") == "[CARTE]\n\ntravail"
    monkeypatch.setenv("LAFORGE_CARTE_DELEGATION", "0")
    assert TE._avec_carte_attention("travail") == "travail"           # interrupteur : cout zero
    monkeypatch.delenv("LAFORGE_CARTE_DELEGATION")
    assert TE._avec_carte_attention("") == ""


def test_observer_rayon_impact_journalise_sans_bloquer(tmp_path, monkeypatch):
    monkeypatch.setattr(CG, "get_function_dependencies", lambda f, p: {"callers": ["a", "b", "c"]})
    journal = tmp_path / "obs.jsonl"
    assert CG.observer_rayon_impact("app/x.txt", BLOCS, journal=journal) == []     # pas du python
    assert CG.observer_rayon_impact("app/x.py", BLOCS, agent="T", journal=journal) == ["publique"]
    for _ in range(50):                                                     # tache de fond
        if journal.exists() and journal.read_text(encoding="utf-8").strip():
            break
        time.sleep(0.05)
    e = json.loads(journal.read_text(encoding="utf-8").splitlines()[0])
    assert e["fonction"] == "publique" and e["appelants"] == 3 and e["agent"] == "T"
