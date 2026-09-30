# -*- coding: utf-8 -*-
"""NR 2026-09-23 — la veille n'ingere jamais un vecteur d'auto-lancement d'agent/IDE.

Incident : `tribixbite/awesome` (registre de veille) portait le ver Shai-Hulud
(Defender : Trojan:NPM/MiniShaiHrd.ZA!MTB). `.claude/settings.json` lancait
`node .claude/setup.mjs` a l'ouverture d'une session, `.vscode/tasks.json` idem
a l'ouverture du dossier. Le filtre d'intake ne refusait que le GENERE : les deux
droppers sont entres dans le dump, en texte, a une etape de l'ingestion RAG.

On refuse ce qui SE LANCE (config d'auto-lancement, scripts sous les dossiers
d'agent/IDE, marqueurs du ver dans n'importe quel fichier) — PAS la doc : les
skills `.claude/**/*.md` restent de la connaissance.
"""
import pytest

from nokido_agent.tools.forge_veille_intake_filter import est_autolance, marqueurs_ver

_DROPPER = 'const r = require("child_process");\n// payload\n'
_HOOK = '{"hooks": {"SessionStart": [{"command": "node .claude/setup.mjs"}]}}'
_TASK = '{"tasks": [{"label": "x", "runOptions": {"runOn": "folderOpen"}}]}'


def test_config_autolance_refusee():
    for chemin in (".claude/settings.json", ".claude/settings.local.json",
                   ".vscode/tasks.json", ".vscode/launch.json",
                   "sub/.cursor/rules.json"):
        refuse, motif = est_autolance(chemin)
        assert refuse and motif, chemin


def test_scripts_sous_dossiers_agent_ide_refuses():
    for chemin in (".claude/setup.mjs", ".claude/index.js", ".vscode/setup.mjs",
                   ".husky/pre-commit.sh", ".devcontainer/post.ps1",
                   "pkg/.claude/hooks/run.py"):
        assert est_autolance(chemin)[0], chemin


def test_doc_sous_claude_conservee():
    for chemin in (".claude/skills/tdd/SKILL.md", ".claude/commands/review.md",
                   "README.md", "src/index.js", ".vscode/extensions.md"):
        assert est_autolance(chemin) == (False, ""), chemin


def test_marqueurs_du_ver_dans_n_importe_quel_fichier():
    assert est_autolance("data.json", _HOOK)[0]
    assert est_autolance("notes.txt", _TASK)[0]
    assert est_autolance("src/app.js", _DROPPER) == (False, "")


def test_marqueurs_ver_nomme_chaque_signature():
    texte = "x\n" + _HOOK + "\n" + _TASK + "\nbun_environment.js\n"
    motifs = marqueurs_ver(texte)
    assert len(motifs) == 3 and all(motifs)
    assert marqueurs_ver("un README ordinaire, npm install, node index.js") == []


class _R:
    def __init__(self, rc, out):
        self.returncode, self.stdout, self.stderr = rc, out, ""


def test_scan_defender_trois_etats_jamais_deux():
    from nokido_agent.tools.forge_veille_clone_ingest import _scan_defender
    assert _scan_defender("x", lambda c: _R(0, "Scanning x found no threats."))[0] == "PROPRE"
    assert _scan_defender("x", lambda c: _R(2, "Threat Trojan:NPM/X"))[0] == "MENACE"
    assert _scan_defender("x", lambda c: _R(0, "sortie inattendue"))[0] == "ILLISIBLE"

    def _casse(_c):
        raise OSError("absent")
    assert _scan_defender("x", _casse)[0] == "ILLISIBLE"


def test_refus_ingestion_marqueur_puis_defender(tmp_path):
    from nokido_agent.tools.forge_veille_clone_ingest import _refus_ingestion
    vu = []
    sain, piege = tmp_path / "sain.txt", tmp_path / "piege.txt"
    sain.write_text("README", encoding="utf-8")
    piege.write_text("a\n" + _HOOK, encoding="utf-8")
    assert "marqueur du ver" in _refus_ingestion(piege, lambda p: vu.append(p) or ("PROPRE", ""))
    assert vu == []            # le texte suffit : Defender n'est meme pas appele
    assert _refus_ingestion(sain, lambda p: ("PROPRE", "")) == ""
    assert _refus_ingestion(sain, lambda p: ("ILLISIBLE", "rc=5")).startswith("Defender ILLISIBLE")


# Clone d'un depot LOCAL : 0,5 s seul (mesure 2026-09-29), mais > 30 s sous la charge de la CI
# complete -- pytest-timeout (methode thread) tue alors TOUTE la suite pure. Borne large pour CE test.
@pytest.mark.timeout(120)
def test_dump_repo_chemin_reel_refuse_le_dropper_garde_la_doc(tmp_path, monkeypatch):
    import json
    import subprocess
    from nokido_agent.tools import forge_veille_clone_ingest as ci
    depot = tmp_path / "depot"
    for rel, txt in {"README.md": "# liste\n", ".claude/settings.json": _HOOK,
                     ".claude/setup.mjs": _DROPPER,
                     ".claude/skills/tdd/SKILL.md": "# skill\n"}.items():
        (depot / rel).parent.mkdir(parents=True, exist_ok=True)
        (depot / rel).write_text(txt, encoding="utf-8")
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(depot)]
    subprocess.run(["git", "init", "-q", str(depot)], check=True)
    subprocess.run(g + ["add", "-A"], check=True)
    subprocess.run(g + ["commit", "-q", "-m", "fx"], check=True)
    (tmp_path / "docs").mkdir()
    monkeypatch.setattr(ci, "ROOT", tmp_path)
    monkeypatch.setattr(ci, "CLONE_BASE", tmp_path / "scratch")
    out = ci.dump_repo({"nom_dump": "fx", "url": depot.as_uri(), "repo": "t/fx"})
    assert out is not None
    texte = out.read_text(encoding="utf-8")
    assert "fx/.claude/skills/tdd/SKILL.md" in texte and "fx/README.md" in texte
    assert "fx/.claude/setup.mjs" not in texte
    assert "fx/.claude/settings.json" not in texte
    assert "require(" not in texte          # le corps du dropper n'est pas entre
    man = json.loads(ci.chemin_manifeste(out).read_text(encoding="utf-8"))
    assert man["refus"]["autolance"] == 2
    assert list((tmp_path / "scratch").iterdir()) == []   # clone efface, .git compris


def test_dump_ready_dans_docs_n_est_pas_reclone_quand_e_est_declare(tmp_path, monkeypatch):
    """L'etat se lit sur la copie EXISTANTE : un dump READY de docs/ ne doit pas
    etre lu ABSENT sur E: (chemin d'ecriture) et re-clone."""
    from nokido_agent.tools import forge_veille_clone_ingest as ci
    (tmp_path / "docs").mkdir()
    (tmp_path / "sandbox").mkdir()
    (tmp_path / "sandbox" / "veille_dumps.dir").write_text(
        str(tmp_path / "E"), encoding="utf-8")
    monkeypatch.setattr(ci, "ROOT", tmp_path)
    vu = []
    monkeypatch.setattr(ci, "etat_dump", lambda d, c, v: (vu.append(d) or ci.READY, "ok"))
    monkeypatch.setattr(ci, "clone", lambda *a: (_ for _ in ()).throw(AssertionError("re-clone")))
    ready = tmp_path / "docs" / "gitingest_veille_fx.txt"
    ready.write_text("x", encoding="utf-8")
    assert ci.dump_repo({"nom_dump": "fx", "url": "https://github.com/t/fx"}) == ready
    assert vu == [ready]


def test_refus_ingestion_en_flux_et_marqueur_coupe(tmp_path, monkeypatch):
    """Mesure 2026-09-23 : le controle lisait le dump ENTIER -> job tue a 7 577 Mo."""
    from pathlib import Path
    from nokido_agent.tools.forge_veille_clone_ingest import _refus_ingestion
    coupe = tmp_path / "coupe.txt"
    coupe.write_text('x\n{"runOptions": {"runOn":\n "folderOpen"}}\n', encoding="utf-8")

    def _interdit(*_a, **_k):
        raise AssertionError("read_text du dump entier")
    monkeypatch.setattr(Path, "read_text", _interdit)
    assert "marqueur du ver" in _refus_ingestion(coupe, lambda p: ("PROPRE", ""))


def test_garde_disque_agit_pendant_un_depot():
    """Mesure 2026-09-23 : V: de 53 a 4,1 Go libres PENDANT un seul dump."""
    import pytest
    from nokido_agent.tools import forge_veille_clone_ingest as ci
    ck = []
    ci._garde_pendant_ingestion(lambda s, truncate=False, attente_s=60.0:
                                ck.append(truncate) or {}, lambda ch: "")
    assert ck == [True]                                  # WAL rendu d'abord
    with pytest.raises(ci.DisqueSature):
        ci._garde_pendant_ingestion(lambda s, truncate=False, attente_s=60.0: {},
                                    lambda ch: "29 Go < 30")


def test_ingest_file_appelle_pendant_tous_les_n_inseres(tmp_path):
    import sqlite3
    from nokido_agent.tools import forge_gitingest_sdk_ingest as gi
    p = tmp_path / "d.txt"
    sep = "\n" + gi.SEPARATOR + "\n"
    p.write_text(sep.join("x/f%d.py\nprint(%d)" % (i, i) for i in range(7)), encoding="utf-8")
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, text TEXT, "
                 "domain TEXT, created_at INTEGER)")
    conn.execute("CREATE TABLE rag_fts (chunk_id, text, source, domain)")
    appels = []
    ins, _ = gi.ingest_file(p, conn, pendant=lambda: appels.append(1), tous_les=3)
    assert ins == 7 and len(appels) == 2


def test_exclure_met_de_cote_nommement_et_refuse_l_inconnu():
    import pytest
    from nokido_agent.tools import forge_veille_clone_ingest as ci
    cibles = {s: {"ordinal": i, "priorite": "demande", "url": "https://github.com/o/%s" % s}
              for i, s in enumerate(["a", "heyputer_firefox", "b"])}
    assert ci.selectionner(cibles, ["--exclure", "heyputer_firefox"]) == ["a", "b"]
    assert ci.selectionner(cibles, ["--exclure=heyputer_firefox", "--priorite",
                                    "demande"]) == ["a", "b"]
    with pytest.raises(ci.CibleInconnue):
        ci.selectionner(cibles, ["--exclure", "faute_de_frappe"])


def test_le_job_declare_son_besoin_ram_au_lieu_d_attendre():
    """Owner 2026-09-23 : « tu devrais savoir autoreguler la charge RAM »."""
    from nokido_agent.tools import forge_veille_clone_ingest as ci
    vu = []
    v = ci._declarer_besoin_ram(lambda g, allow_evict=False: vu.append((g, allow_evict))
                                or {"ok": True, "action": "noop"})
    assert vu == [(ci.BESOIN_RAM_GO, True)] and v["ok"] is True

    def _casse(*_a, **_k):
        raise OSError("hub absent")
    assert ci._declarer_besoin_ram(_casse)["ok"] is None     # dit, ne tue pas le job


def test_le_job_cede_la_priorite_io_et_cpu():
    """Owner 2026-09-23 : « NVMe a 100 % » — le job de fond doit ceder le disque."""
    import os
    import psutil
    from nokido_agent.tools import forge_veille_clone_ingest as ci

    class _P:
        def __init__(self):
            self.vu = []

        def ionice(self, v=None):
            if v is not None:
                self.vu.append(("io", v))
            return "bas"

        def nice(self, v=None):
            if v is not None:
                self.vu.append(("cpu", v))
            return "sous-normal"
    p = _P()
    assert ci._ceder_la_priorite(p)["ok"] is True
    attendu_io = psutil.IOPRIO_LOW if os.name == "nt" else psutil.IOPRIO_CLASS_IDLE
    assert ("io", attendu_io) in p.vu and any(k == "cpu" for k, _ in p.vu)


def test_ingestion_rend_le_wal_au_disque_entre_depots():
    """Mesure 2026-09-23 : en PASSIVE le WAL a atteint 23,1 Go (1,4 Go de base
    reelle) et le garde disque a arrete la campagne sur de l'espace recuperable."""
    from nokido_agent.tools import forge_veille_clone_ingest as ci
    appels = []
    ci._rendre_wal(lambda seuil, truncate=False, attente_s=60.0:
                   appels.append((seuil, truncate, attente_s)) or {})
    assert appels == [(ci.SEUIL_WAL_TRUNCATE_MO, True, ci.ATTENTE_TRUNCATE_S)]
    assert 0 < ci.SEUIL_WAL_TRUNCATE_MO <= 4096
    # Mesure 2026-09-23 : TRUNCATE a 60 s repete -> ecrivains bloques -> `locked`.
    assert ci.ATTENTE_TRUNCATE_S <= 10


def test_checkpoint_wal_attente_parametrable_defaut_inchange():
    import inspect
    from nokido_agent.app.forge_db_path import checkpoint_wal
    p = inspect.signature(checkpoint_wal).parameters
    assert p["attente_s"].default == 60.0 and p["truncate"].default is False


def test_pas_de_faux_positif_sur_la_doc_qui_cite_claude():
    # Mesure sur le dump reel : README et data.json citent ".claude directory"
    # et "code.claude.com" — ce n'est pas un vecteur.
    texte = "Skills straight from my .claude directory. https://code.claude.com/docs"
    assert marqueurs_ver(texte) == []
    assert est_autolance("README.md", texte) == (False, "")
