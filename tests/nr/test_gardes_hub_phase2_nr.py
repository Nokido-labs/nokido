"""NR -- phase 2 des gardes COTE HUB, par identite d'agent (decision owner 17/10 : « les garde fous doivent emaner du hub...
et pareil pour les autres cli »).

Mesure 17/10 : CLAUDE a relu le depot par `read_text` dans `run action=python` APRES le disjoncteur de lecture (le hub
executait le code sans le compter : `forge_recon_breaker` ne voyait que l'outil `read`), et a ajoute trois fonctions dans
des modules existants sans consulter LEUR domaine (`hook_recon_first` ne mord que sur une CREATION de fichier et juge une
fraicheur GLOBALE, hook Claude seul). Brique etendue ici, pas de systeme parallele :
  * `lit_le_depot(code)` : un run qui ouvre un fichier de CODE du depot est une lecture (un journal ou un etat n'en est pas une).
Le registre des consultations par agent existe DEJA cote hub (app/forge_introspect.consultation_recente, lu par le
handler governed_edit depuis le 31/08) : c'est lui qui s'etend au domaine. Un second registre ecrit ici le 17/10 a ete
retire (anti-dup).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_recon_breaker as B  # noqa: E402


def test_un_run_qui_lit_un_module_du_depot_est_une_lecture():
    assert B.lit_le_depot('from pathlib import Path\n'
                          'Path(r"%NOKIDO_ROOT%/tools/forge_x.py").read_text()')
    assert B.lit_le_depot('print(open("app/forge_llm_router.py", encoding="utf-8").read())')
    assert B.lit_le_depot('type tools\\forge_task_executor.py')
    assert B.lit_le_depot('Get-Content proxy_deno/core/supervisor.ts -TotalCount 40')


def test_un_journal_un_etat_ou_un_calcul_ne_sont_pas_une_lecture_de_code():
    assert not B.lit_le_depot('Path("sandbox/jobs/job_x.log").read_text()')
    assert not B.lit_le_depot('json.loads(Path("sandbox/task_executor_mistral.heartbeat").read_text())')
    assert not B.lit_le_depot('import datetime; print(datetime.datetime.now())')
    assert not B.lit_le_depot("")


def test_le_disjoncteur_ne_porte_pas_de_second_registre_de_consultation():
    """Le registre vit dans forge_introspect (cote hub) ; un doublon ici divergerait en silence."""
    assert not hasattr(B, "consulter") and not hasattr(B, "LEDGER")


# --- Brique C : le gate COGNITIF de governed_edit (decision pure ; le handler du hub la branche) -----------------------
# Elle vit dans l'organe cognitif (forge_introspect, a cote de consultation_du_domaine) : forge_governed_edit est
# CRITICAL et la derogation owner du 17/10 ne couvre que le branchement dans forge_mcp_registry.
sys.path.insert(0, str(ROOT))
from nokido_agent.app import forge_introspect as G  # noqa: E402


def test_les_symboles_neufs_et_la_creation_se_mesurent_a_l_ast(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "ROOT", tmp_path)
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "forge_x.py").write_text("def a():\n    pass\n", encoding="utf-8")
    assert G.symboles_neufs("tools/forge_x.py", "def a():\n    pass\n\n\ndef b():\n    pass\n") == (False, {"b"})
    assert G.symboles_neufs("tools/forge_x.py", "def a():\n    return 1\n") == (False, set()), "editer n'est pas creer"
    assert G.symboles_neufs("tools/forge_neuf.py", "class C:\n    pass\n") == (True, {"C"})
    assert G.symboles_neufs("docs/note.md", "# texte") == (False, set())


def test_un_symbole_neuf_sans_consultation_du_domaine_est_signale(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "ROOT", tmp_path)
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "forge_x.py").write_text("def a():\n    pass\n", encoding="utf-8")
    neuf = "def a():\n    pass\n\n\ndef _reaffecter():\n    pass\n"
    monkeypatch.setattr(G, "_consultation_du_domaine", lambda agent, chemin: {"vu": False, "etat": "JAMAIS"})
    msg = G.verdict_cognitif("CLAUDE", "tools/forge_x.py", neuf)
    assert msg and "forge_x" in msg and "_reaffecter" in msg and "introspect" in msg, msg
    monkeypatch.setattr(G, "_consultation_du_domaine", lambda agent, chemin: {"vu": True, "etat": "RECENTE"})
    assert G.verdict_cognitif("CLAUDE", "tools/forge_x.py", neuf) is None
    assert G.verdict_cognitif("CLAUDE", "tools/forge_x.py", "def a():\n    return 2\n") is None, "pas un peage"


# --- Brique B : branchements dans le dispatch du hub (verrou de source, ecrit APRES le code -- pas un RED) -------------
_REG = (ROOT / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8")


def test_le_dispatch_compte_la_lecture_de_code_par_run():
    i = _REG.index('if name == "run" and str(args.get("action") or "") in ("python", "shell"):')
    bloc = _REG[i:i + 1800]
    # 17/10 : le compteur se cle par identite PROUVEE (cle_de_garde), plus par le nom brut -- test_cle_de_garde_*.
    assert "_brk2.lit_le_depot(" in bloc and '_brk2.verdict(_brk2.cle_de_garde(str(agent or "HUB")), "read", True)' in bloc
    assert '_m2 == "refus"' in bloc, "le refus n'existe que sur l'interrupteur owner"


def test_governed_edit_juge_le_domaine_avant_d_ecrire():
    i = _REG.index("_cog = _vcog(agent, str(path), content)")
    assert i < _REG.index("verdict = governed_write(str(path), content", i), "juge AVANT l'ecriture"


def test_la_recon_deleguee_est_une_consultation_du_domaine():
    i = _REG.index("async def _handle_deep_explore(")
    assert "_noter(agent," in _REG[i:i + 4000]


# --- Brique E : l'IMPULSION comptee par le hub, par identite (meme logique que le hook de Claude, pas une copie) --------
import hook_capability_gate as H  # noqa: E402


def test_le_comptage_des_tours_est_une_fonction_pure_partagee():
    tours, dernier, n = H.compter_tour([], None, 100.0)
    assert (tours, dernier, n) == ([100.0], 100.0, 1)
    assert H.compter_tour(tours, dernier, 101.0)[2] == 1, "a moins de 2 s : meme tour"
    tours, dernier, n = H.compter_tour([100.0, 130.0], 130.0, 160.0)
    assert n == 3, "3e tour dans la fenetre de 90 s"
    assert H.compter_tour([10.0], 10.0, 200.0)[2] == 1, "hors fenetre : le compte repart"


def test_le_hub_compte_l_impulsion_par_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "IMPULSION", tmp_path / "impulsion_agents.json")
    assert B.impulsion("CLAUDE", maintenant=100.0)[0] is None
    assert B.impulsion("CLAUDE", maintenant=120.0)[0] == "avertissement"
    assert B.impulsion("ANTIGRAVITY", maintenant=121.0)[0] is None, "chaque identite a sa propre fenetre"
    assert B.impulsion("CLAUDE", maintenant=140.0)[0] == "refus"
    B.impulsion_remise("CLAUDE")
    assert B.impulsion("CLAUDE", maintenant=141.0)[0] is None, "une ecriture remet le compte a zero"


def test_le_dispatch_compte_l_impulsion_et_la_remet_a_zero_sur_ecriture():
    # 19/10 : la liste python/shell/job_status est remplacee par est_sonde (le meme classifieur que le hook) ;
    # job_status reste une sonde, verifie par test_hub_impulsion_par_est_sonde_nr.
    i = _REG.index("_brk3.impulsion(")
    assert "est_sonde" in _REG[i - 600:i] and '_m3 == "refus"' in _REG[i:i + 900]


def test_seule_une_edition_reussie_remet_l_impulsion_a_zero():
    """Revue adverse de Codex (17/10, CONFIRME) : la remise etait faite AVANT le handler, donc par un governed_edit
    trivial ou rate -- une rafale se vidait d'un appel. Elle vit desormais APRES l'ecriture reussie."""
    assert "_brk3.impulsion_remise(" not in _REG, "plus de remise dans le dispatch, avant validation"
    i = _REG.index("verdict = governed_write(str(path), content")
    j = _REG.index('if not verdict.get("ok"):', i)
    assert "impulsion_remise(" in _REG[j:j + 700], "remise APRES l'ecriture reussie"


def test_un_symbole_imbrique_ou_une_lambda_affectee_sont_des_symboles_neufs(tmp_path, monkeypatch):
    """Revue adverse de Codex (17/10, CONFIRME) : seuls les def/class de premier niveau etaient vus."""
    monkeypatch.setattr(G, "ROOT", tmp_path)
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "forge_x.py").write_text("def a():\n    pass\n", encoding="utf-8")
    neuf = "def a():\n    def cache():\n        pass\n    return cache\n\n\nraccourci = lambda x: x\n"
    assert G.symboles_neufs("tools/forge_x.py", neuf) == (False, {"cache", "raccourci"})


def test_le_mode_vient_de_l_interrupteur_owner_et_vaut_observer_par_defaut(monkeypatch):
    monkeypatch.delenv("LAFORGE_GARDES_HUB", raising=False)
    assert G.mode_gardes_hub() == "observer"
    monkeypatch.setenv("LAFORGE_GARDES_HUB", "refus")
    assert G.mode_gardes_hub() == "refus"
    monkeypatch.setenv("LAFORGE_GARDES_HUB", "n'importe quoi")
    assert G.mode_gardes_hub() == "observer", "valeur inconnue = observer, jamais un refus fabrique"
