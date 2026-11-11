"""NR -- un sujet PRIVE ne part dans aucune sortie publique (owner 4/11).

La liste des chemins et des mots vit dans `config/sujets_prives.txt`, suivi dans la source et bloque au profil public,
comme la liste d'identites : le manifeste `.git-publish-rules.json` part au public et ne doit pas nommer ce qu'il cache.
`load_manifest` fusionne la liste dans le seul profil public : gate de push, dist et miroir lisent ainsi un seul juge.
Le promoteur refuse de publier si un mot subsiste, ou si la liste est vide ou illisible (fail-closed).

Hermetique : motifs factices, arbre en tmp, aucun reseau, aucun push.
"""

from __future__ import annotations

import json
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_dist_publish as D  # noqa: E402
import forge_git_egress as EG  # noqa: E402
import forge_public_mirror as M  # noqa: E402

LISTE = ("# commentaire\n\nchemin outils/*factice*\nchemin secret_dossier/**\nmot sujet[ _-]?factice\n"
         "caviarder gen.md\ncaviarder gen.json\ncaviarder listes.py\nretirer test_retire_\n")


@pytest.fixture
def liste(tmp_path, monkeypatch):
    f = tmp_path / "sujets.txt"
    f.write_text(LISTE, encoding="utf-8")
    monkeypatch.setattr(EG, "SUJETS_PRIVES", f)
    return f


def _ecrire(racine: Path, rel: str, texte: str = "x") -> Path:
    f = racine / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(texte, encoding="utf-8")
    return f


def test_lecture_de_la_liste(liste):
    s = EG.sujets_prives()
    assert s["chemins"] == ["outils/*factice*", "secret_dossier/**"]
    assert s["mots"] == ["sujet[ _-]?factice"]
    assert s["caviarder"] == ["gen.md", "gen.json", "listes.py"]
    assert s["retirer"] == ["test_retire_"]
    assert s["erreurs"] == []


def test_liste_absente_est_vide_sans_erreur(tmp_path):
    s = EG.sujets_prives(tmp_path / "absent.txt")
    assert s == {"chemins": [], "mots": [], "caviarder": [], "retirer": [], "erreurs": []}


@pytest.mark.parametrize("ligne", ["inconnu valeur", "mot [", "chemin", "mot", "retirer [", "caviarder"])
def test_ligne_invalide_signalee(tmp_path, ligne):
    f = tmp_path / "l.txt"
    f.write_text(ligne + "\n", encoding="utf-8")
    assert EG.sujets_prives(f)["erreurs"]


def test_fusion_dans_le_seul_profil_public(liste):
    m = EG.load_manifest()
    pub, prive = m["profiles"]["public"], m["profiles"]["private"]
    assert "secret_dossier/**" in pub["blocked_paths"]
    assert pub["mots_prives"] == ["sujet[ _-]?factice"]
    assert "secret_dossier/**" not in prive["blocked_paths"]
    assert not prive.get("mots_prives")


def test_fusion_ne_modifie_pas_le_defaut(liste, tmp_path, monkeypatch):
    monkeypatch.setattr(EG, "MANIFEST_PATH", tmp_path / "absent.json")
    assert "secret_dossier/**" in EG.load_manifest()["profiles"]["public"]["blocked_paths"]
    assert "secret_dossier/**" not in EG._DEFAULT_MANIFEST["profiles"]["public"]["blocked_paths"]
    assert "mots_prives" not in EG._DEFAULT_MANIFEST["profiles"]["public"]


def test_gate_de_push_refuse_mot_et_chemin_au_public(liste):
    profils = EG.load_manifest()["profiles"]
    pire, trouves = EG.scan_files({"doc.md": "ici le Sujet-Factice"}, profils["public"])
    assert pire == EG.pg.Severity.RED, trouves
    pire, trouves = EG.scan_files({"secret_dossier/a.md": "neutre"}, profils["public"])
    assert pire == EG.pg.Severity.RED, trouves
    pire, trouves = EG.scan_files({"sujet_factice.md": "neutre"}, profils["public"])
    assert pire == EG.pg.Severity.RED, trouves


def test_gate_de_push_laisse_passer_au_prive(liste):
    pire, trouves = EG.scan_files({"doc.md": "ici le sujet factice"}, EG.load_manifest()["profiles"]["private"])
    assert pire != EG.pg.Severity.RED, trouves


def test_assemblage_retire_les_chemins_prives(liste, tmp_path):
    arbre = tmp_path / "dist"
    _ecrire(arbre, "secret_dossier/plan.md")
    _ecrire(arbre, "outils/mon_factice.py")
    garde = _ecrire(arbre, "app/garde.py")
    D._appliquer_politique_publique(arbre)
    assert not (arbre / "secret_dossier/plan.md").exists()
    assert not (arbre / "outils/mon_factice.py").exists()
    assert garde.exists()


def test_controle_refuse_mot_dans_contenu_nom_et_binaire(liste, tmp_path):
    arbre = tmp_path / "dist"
    _ecrire(arbre, "ok.md", "neutre")
    D._verifier_sujets_prives(arbre)
    contenu = _ecrire(arbre, "a.md", "le sujet_factice")
    with pytest.raises(RuntimeError, match="a.md"):
        D._verifier_sujets_prives(arbre)
    contenu.unlink()
    nom = _ecrire(arbre, "sujet_factice.md", "neutre")
    with pytest.raises(RuntimeError, match="nom de fichier"):
        D._verifier_sujets_prives(arbre)
    nom.unlink()
    (arbre / "b.png").write_bytes(b"\x89PNG\xff sujet factice \xff")
    with pytest.raises(RuntimeError, match="b.png"):
        D._verifier_sujets_prives(arbre)
    (arbre / "b.png").unlink()
    (arbre / "c.txt").write_bytes("latin-1 \xe9 sujet factice".encode("latin-1"))
    with pytest.raises(RuntimeError, match="c.txt"):
        D._verifier_sujets_prives(arbre)


@pytest.mark.parametrize("texte", ["", "# rien\n", "chemin seulement/**\n", "mot seulement\n", "mot [\nchemin a/**\nmot b\n"])
def test_controle_fail_closed_si_liste_incomplete(tmp_path, monkeypatch, texte):
    f = tmp_path / "l.txt"
    f.write_text(texte, encoding="utf-8")
    monkeypatch.setattr(EG, "SUJETS_PRIVES", f)
    arbre = tmp_path / "dist"
    _ecrire(arbre, "ok.md", "neutre")
    with pytest.raises(RuntimeError, match="sujets"):
        D._verifier_sujets_prives(arbre)


def test_controle_fail_closed_si_liste_absente(tmp_path, monkeypatch):
    monkeypatch.setattr(EG, "SUJETS_PRIVES", tmp_path / "absent.txt")
    arbre = tmp_path / "dist"
    _ecrire(arbre, "ok.md", "neutre")
    with pytest.raises(RuntimeError, match="sujets"):
        D._verifier_sujets_prives(arbre)


def test_sync_snapshot_appelle_le_controle(liste, tmp_path, monkeypatch):
    """Par le chemin reel : l'arbre extrait porte le mot, l'assemblage doit s'arreter."""
    source = tmp_path / "src"
    _ecrire(source, "doc.md", "le sujet factice")
    dist = tmp_path / "dist"
    dist.mkdir()

    def faux_git_archive(cmd, *a, **k):
        with tarfile.open(cmd[cmd.index("-o") + 1], "w") as t:
            t.add(source / "doc.md", arcname="doc.md")

    monkeypatch.setattr(D, "TMP", tmp_path)
    monkeypatch.setattr(D, "run", faux_git_archive)
    monkeypatch.setattr(D, "_embarquer_workflows_dist", lambda *a, **k: None)
    monkeypatch.setattr(D, "_generiser_chemins_owner", lambda *a, **k: None)
    monkeypatch.setattr(D, "_verifier_identite_civile", lambda *a, **k: None)
    monkeypatch.setattr(D, "_scanner_secrets", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="doc.md"):
        D.sync_snapshot("HEAD", dist)


def test_caviardage_retire_les_lignes_du_texte(liste, tmp_path):
    arbre = tmp_path / "dist"
    gen = _ecrire(arbre, "gen.md", "garde 1\nle sujet factice\ngarde 2\nvoir test_retire_x\n")
    D._caviarder_sujets(arbre)
    assert gen.read_text(encoding="utf-8") == "garde 1\ngarde 2\n"
    D._verifier_sujets_prives(arbre)


def test_caviardage_nettoie_le_json_sans_le_casser(liste, tmp_path):
    arbre = tmp_path / "dist"
    gen = _ecrire(arbre, "gen.json", json.dumps({
        "garde": 1,
        "sujet_factice.py": "cle retiree",
        "noeuds": [{"cle": "sujet_factice_1", "reste": "plateau chiffre"}, {"cle": "neutre", "deps": ["sujet factice", "ok"]}],
    }))
    D._caviarder_sujets(arbre)
    assert json.loads(gen.read_text(encoding="utf-8")) == {"garde": 1, "noeuds": [{"cle": "neutre", "deps": ["ok"]}]}


def test_caviardage_laisse_intact_un_json_sans_motif(liste, tmp_path):
    arbre = tmp_path / "dist"
    brut = '{"a":   1}\n'
    gen = _ecrire(arbre, "gen.json", brut)
    D._caviarder_sujets(arbre)
    assert gen.read_text(encoding="utf-8") == brut


def test_caviardage_refuse_un_json_entierement_retire(liste, tmp_path):
    arbre = tmp_path / "dist"
    _ecrire(arbre, "gen.json", json.dumps({"cle": "sujet factice"}))
    with pytest.raises(RuntimeError, match="gen.json"):
        D._caviarder_sujets(arbre)


def test_caviardage_python_reste_valide(liste, tmp_path):
    arbre = tmp_path / "dist"
    py = _ecrire(arbre, "listes.py", 'L = [\n    "a.py",\n    "test_retire_b.py",  # sujet factice\n    "c.py",\n]\n')
    D._caviarder_sujets(arbre)
    assert py.read_text(encoding="utf-8") == 'L = [\n    "a.py",\n    "c.py",\n]\n'


def test_caviardage_python_casse_est_refuse(liste, tmp_path):
    arbre = tmp_path / "dist"
    _ecrire(arbre, "listes.py", 'L = [\n    "sujet factice",\n    "b.py",\n]; M = ("a", # ok\n"sujet factice"\n)\nif L: # sujet factice\n    pass\n')
    with pytest.raises(RuntimeError, match="listes.py"):
        D._caviarder_sujets(arbre)


def test_caviardage_ne_touche_que_les_fichiers_nommes(liste, tmp_path):
    arbre = tmp_path / "dist"
    autre = _ecrire(arbre, "autre.md", "le sujet factice\n")
    D._caviarder_sujets(arbre)
    assert autre.read_text(encoding="utf-8") == "le sujet factice\n"
    with pytest.raises(RuntimeError, match="autre.md"):
        D._verifier_sujets_prives(arbre)


def test_retirer_ne_refuse_pas_hors_caviardage(liste, tmp_path):
    arbre = tmp_path / "dist"
    _ecrire(arbre, "autre.md", "voir test_retire_x\n")
    D._verifier_sujets_prives(arbre)


def test_sync_snapshot_caviarde_avant_le_controle(liste, tmp_path, monkeypatch):
    source = tmp_path / "src"
    _ecrire(source, "gen.md", "garde\nle sujet factice\n")
    dist = tmp_path / "dist"
    dist.mkdir()

    def faux_git_archive(cmd, *a, **k):
        with tarfile.open(cmd[cmd.index("-o") + 1], "w") as t:
            t.add(source / "gen.md", arcname="gen.md")

    monkeypatch.setattr(D, "TMP", tmp_path)
    monkeypatch.setattr(D, "run", faux_git_archive)
    monkeypatch.setattr(D, "_embarquer_workflows_dist", lambda *a, **k: None)
    monkeypatch.setattr(D, "_generiser_chemins_owner", lambda *a, **k: None)
    monkeypatch.setattr(D, "_verifier_identite_civile", lambda *a, **k: None)
    monkeypatch.setattr(D, "_scanner_secrets", lambda *a, **k: None)
    D.sync_snapshot("HEAD", dist)
    assert (dist / "gen.md").read_text(encoding="utf-8") == "garde\n"


def test_demon_sans_module_des_bancs(monkeypatch):
    """Les bancs sont prives : le demon de la distribution publique tourne sans eux."""
    import forge_epistemic_daemon as DM

    monkeypatch.setitem(sys.modules, "forge_banc_amelioration", None)
    assert DM._bancs_declares() == {}


def test_miroir_refuse_le_mot(liste, monkeypatch):
    import nokido_agent.tools.forge_history_secret_audit as A

    monkeypatch.setattr(M, "_git", lambda *a, **k: (0, "100644 blob aaa 20\tdoc.md".replace("\t", " "), ""))
    monkeypatch.setattr(A, "lire_blobs", lambda shas: [("aaa", b"le sujet factice", 20)])
    profil = EG.load_manifest()["profiles"]["public"]
    r = M._audit_du_tree("arbre", profil, EG)
    assert r["etat"] == "rouge"
    assert r["findings"] == [{"fichier": "doc.md", "type": "sujet_prive"}]


def test_manifeste_public_cache_la_liste():
    """Le manifeste part au public : il bloque la liste et n'en reprend aucun motif."""
    brut = (ROOT / ".git-publish-rules.json").read_text(encoding="utf-8")
    assert "config/sujets_prives.txt" in brut
    assert "exclude config/sujets_prives.txt" in (ROOT / "MANIFEST.in").read_text(encoding="utf-8")


def test_liste_reelle_valide_et_absente_du_manifeste():
    if not EG.SUJETS_PRIVES.exists():
        pytest.skip("liste absente hors du depot source (dist, wheel)")
    s = EG.sujets_prives()
    assert s["chemins"] and s["mots"] and not s["erreurs"]
    import re

    brut = (ROOT / ".git-publish-rules.json").read_text(encoding="utf-8")
    for mot in s["mots"]:
        assert not re.search(mot, brut, re.IGNORECASE), mot
