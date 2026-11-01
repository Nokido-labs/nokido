"""NR -- l'importeur de Knowledge Pack accepte une cible `--db` explicite (recette du livrable 0.20.14, 21/10).

La recette des packs par source sur le livrable publie (OPENCODE_GPTOSS, job_529a26d1, VERTE 4025/4025 et
72227/72227) a du DETOURNER le module : aucune option ne designe la base cible, `DB = ROOT/"RAG"/"embeddings.db"` est
fige (tools/forge_knowledge_pack_import.py:73). Recetter un livrable sur une base vierge -- ou importer ailleurs que
dans la base de production -- exigeait de charger le module et d'ecraser sa globale a la main.

Contrats (chemin reel : main() et son analyse d'arguments) :
  1. `--db <chemin>` : import_pack ecrit dans CETTE base ;
  2. une base `--db` absente est REFUSEE (rc 1, message qui la nomme) -- jamais creee en silence, jamais de repli sur
     la base de production ;
  3. sans `--db`, la cible reste la base par defaut (comportement inchange).
"""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_knowledge_pack_import as K  # noqa: E402


def _espion(monkeypatch):
    monkeypatch.setattr(K, "DB", K.DB)  # restauree a la fin du test, meme sur echec
    vus = []
    monkeypatch.setattr(K, "import_pack", lambda *a, **kw: vus.append(Path(K.DB)) or {"inserted": 0})
    return vus


def test_db_explicite_est_la_cible(tmp_path, monkeypatch):
    base = tmp_path / "vierge.db"
    base.write_bytes(b"")
    vus = _espion(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["x", "--from", str(tmp_path / "p.tar"), "--db", str(base)])
    assert K.main() == 0
    assert vus == [base]


def test_db_absente_refusee_sans_repli(tmp_path, monkeypatch, capsys):
    vus = _espion(monkeypatch)
    absente = tmp_path / "nulle_part" / "x.db"
    monkeypatch.setattr(sys, "argv", ["x", "--from", str(tmp_path / "p.tar"), "--db", str(absente)])
    assert K.main() == 1
    assert vus == []
    assert not absente.exists()
    assert str(absente) in capsys.readouterr().err


def test_sans_db_la_cible_par_defaut_est_inchangee(tmp_path, monkeypatch):
    vus = _espion(monkeypatch)
    defaut = Path(K.DB)
    monkeypatch.setattr(sys, "argv", ["x", "--from", str(tmp_path / "p.tar")])
    assert K.main() == 0
    assert vus == [defaut]
