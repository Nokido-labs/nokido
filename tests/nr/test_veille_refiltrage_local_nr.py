# -*- coding: utf-8 -*-
"""NR 2026-09-23 — re-filtrage LOCAL v3 des dumps existants (decision owner).

Re-cloner ~340 depots pour rejouer un filtre deterministe sur des donnees deja presentes
(chemin + texte integral dans les dumps v2) coutait plus d'une journee (Defender, clones).
Contrat owner : ne JAMAIS ecraser les dumps v2 ; artefact v3-local separe ; tracabilite
source -> resultat (chemin, sha256, version de filtre d'origine) ; compteurs ; v1 jamais
melange silencieusement ; idempotent.
"""
import hashlib
import json

from nokido_agent.tools import forge_veille_clone_ingest as ci

SEP = "=" * 80


def _v2(tmp_path, filtre="2"):
    src = tmp_path / "v2"
    src.mkdir()
    d = src / "gitingest_veille_fx.txt"
    sections = [
        "fx/_PROVENANCE\nrepo: https://github.com/t/fx\ncommit: abc\n",
        "fx/src/core.py\ndef moteur():\n    return 42\n",
        "fx/Makefile\nall:\n\techo ok\n",
        "fx/tests/test_core.py\ndef test_moteur_rend_42():\n    assert 1\n" + "# bruit\n" * 500,
        "fx/data/big.json\n" + json.dumps([{"cle_utile": i, "v": "x" * 40} for i in range(3000)]),
        'fx/.claude/settings.json\n{"hooks": {"SessionStart": [{"command": "node .claude/setup.mjs"}]}}',
    ]
    d.write_text(("\n" + SEP + "\n").join(sections), encoding="utf-8")
    (src / "gitingest_veille_fx.txt.manifest.json").write_text(json.dumps({
        "repo": "t/fx", "url": "https://github.com/t/fx", "target_id": "tid",
        "commit": "abc", "filtre_version": filtre}), encoding="utf-8")
    return src, d


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_refiltrage_v3_local_substance_resumes_tracabilite(tmp_path):
    src, d = _v2(tmp_path)
    avant = _sha(d)
    sortie = tmp_path / "v3"
    bilan = ci.refiltrer_dossier_local(src, sortie)
    assert _sha(d) == avant                                  # v2 JAMAIS modifie
    out = (sortie / d.name).read_text(encoding="utf-8")
    assert "def moteur" in out and "fx/Makefile" in out      # substance, meme sans extension
    assert "test_moteur_rend_42" in out and "# bruit" not in out   # moelle du test, pas le volume
    assert "cle_utile" in out and '"v": "xxxxx' not in out   # schema, pas les donnees
    assert ".claude/settings.json" not in out                # auto-lancement refuse
    man = json.loads((sortie / (d.name + ".manifest.json")).read_text(encoding="utf-8"))
    assert man["filtre_version"] == "3" and man["commit"] == "abc"
    rl = man["refiltre_local"]
    assert rl["source_sha256"] == avant and rl["source_filtre_version"] == "2"
    assert rl["source_dump"].endswith(d.name)
    assert man["refus"]["autolance"] == 1 and man["refus"]["hors_substance_resume"] == 2
    assert bilan["dumps_refiltres"] == 1 and bilan["fichiers_examines"] == 5


def test_idempotent_et_v1_explicite(tmp_path):
    src, d = _v2(tmp_path, filtre="1")
    sortie = tmp_path / "v3"
    ci.refiltrer_dossier_local(src, sortie)
    man = json.loads((sortie / (d.name + ".manifest.json")).read_text(encoding="utf-8"))
    assert man["refiltre_local"]["source_filtre_version"] == "1"   # v1 DIT, jamais melange
    b2 = ci.refiltrer_dossier_local(src, sortie)
    assert b2["deja_faits"] == 1 and b2["dumps_refiltres"] == 0     # meme source -> saute


def test_une_autre_source_n_ecrase_pas_la_sortie(tmp_path):
    src, d = _v2(tmp_path)                        # v2 recent (E:)
    sortie = tmp_path / "v3"
    ci.refiltrer_dossier_local(src, sortie)
    ancien = tmp_path / "docs"
    ancien.mkdir()
    (ancien / d.name).write_text("fx/_PROVENANCE\nrepo: vieux\n", encoding="utf-8")
    (ancien / (d.name + ".manifest.json")).write_text(json.dumps({"filtre_version": "1"}),
                                                      encoding="utf-8")
    b = ci.refiltrer_dossier_local(ancien, sortie)
    assert b.get("conflit_source") == 1 and b["dumps_refiltres"] == 0
    man = json.loads((sortie / (d.name + ".manifest.json")).read_text(encoding="utf-8"))
    assert man["refiltre_local"]["source_filtre_version"] == "2"   # la sortie v2 intacte


import sys  # noqa: E402

import pytest  # noqa: E402


def test_source_absente_leve_et_ne_cree_pas_la_sortie(tmp_path):
    sortie = tmp_path / "v3"
    with pytest.raises(FileNotFoundError):
        ci.refiltrer_dossier_local(tmp_path / "faute_de_frappe", sortie)
    assert not sortie.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="notion de chemin relatif au lecteur = Windows")
def test_chemin_relatif_au_lecteur_refuse(tmp_path):
    lecteur = str(tmp_path)[:2]            # ex. "C:"
    with pytest.raises(ValueError, match="relatif au lecteur"):
        ci.refiltrer_dossier_local(lecteur + "dossier_sans_barre", tmp_path / "v3")


def test_source_dump_enregistre_est_absolu(tmp_path, monkeypatch):
    src, d = _v2(tmp_path)
    detour = src / ".." / src.name                     # meme dossier, forme non normalisee
    ci.refiltrer_dossier_local(detour, tmp_path / "v3")
    man = json.loads((tmp_path / "v3" / (d.name + ".manifest.json")).read_text(encoding="utf-8"))
    enr = man["refiltre_local"]["source_dump"]
    assert ".." not in enr and __import__("os").path.isabs(enr)
    assert __import__("os").path.samefile(enr, d)


def test_cli_source_vide_rend_rc_3(tmp_path, capsys, monkeypatch):
    (tmp_path / "vide").mkdir()
    monkeypatch.setattr(sys, "argv", ["forge_veille_clone_ingest.py", "--refiltrer-local",
                                      str(tmp_path / "vide"), str(tmp_path / "v3")])
    monkeypatch.setattr(ci, "_ceder_la_priorite", lambda: None)
    monkeypatch.setattr(ci, "_declarer_besoin_ram", lambda *a, **k: None, raising=False)
    rc = ci.main()
    assert rc == 3
    assert '"dumps_vus": 0' in capsys.readouterr().out


def test_dump_sans_manifeste_n_est_pas_refiltre(tmp_path):
    src = tmp_path / "v2"
    src.mkdir()
    (src / "gitingest_veille_orphelin.txt").write_text("x/a.py\nprint(1)\n", encoding="utf-8")
    b = ci.refiltrer_dossier_local(src, tmp_path / "v3")
    assert b["sans_manifeste"] == 1 and b["dumps_refiltres"] == 0
