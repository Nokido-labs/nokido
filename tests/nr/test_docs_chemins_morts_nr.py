# -*- coding: utf-8 -*-
"""NR — une page de doc ne renvoie pas vers du vide, et le gate CLASSE.

MESURE 2026-09-17 (owner : « le wiki porte des informations fausses ou des
chemins absents desormais ») : sur `docs/wiki/`, **2465 references de chemin
distinctes, 24 qui ne resolvent pas**, sur 14 pages.

⚠️ LE POINT CENTRAL : DETECTER NE SUFFIT PAS, IL FAUT CLASSER. Un detecteur
binaire crierait sur `tools/your_tool.py` -- placeholder pedagogique
parfaitement legitime de la doc des lanceurs -- et se ferait desarmer au
premier agacement. Le tri a paye immediatement sur le corpus reel :

    MORT     14   le fichier n'existe nulle part        -> a instruire
    COQUILLE  5   `sandbox/snn.wante` pour `snn.wanted` -> corriger la frappe
    DEPLACE   3   `app/forge_ami_strategist` vit en `tools/`, et la migration
                  de namespace `2fd348209` (2106 transformations) en explique
                  d'autres                              -> REPOINTER
    EXEMPLE   2   placeholder                           -> jamais signale

Sans ce tri on « corrige » une doc en supprimant une mention utile, et dans le
mauvais sens : un DEPLACE traite comme un MORT efface l'information qu'un
module existe encore.

CE QUE LE TRI A TROUVE EN PRIME : `tools/forge_test_resource_calibrator.py`
portait en tete de docstring le nom d'un AUTRE module, a un chemin inexistant.
`forge_wiki_modules` en faisait la « definition » publiee au wiki. Le gate a
donc remonte de l'artefact genere jusqu'a un defaut du CODE.

Hermetique : tous les cas sont montes en `tmp_path`, jamais sur `docs/`.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_docs_chemins_morts as C  # noqa: E402


def _faux_depot(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "sandbox").mkdir()
    (tmp_path / "app" / "forge_vivant.py").write_text("x", encoding="utf-8")
    (tmp_path / "tools" / "forge_ailleurs.py").write_text("x", encoding="utf-8")
    (tmp_path / "sandbox" / "snn.wanted").write_text("x", encoding="utf-8")
    return tmp_path


def test_un_chemin_qui_existe_est_VIVANT(tmp_path):
    r = _faux_depot(tmp_path)
    assert C.classer("app/forge_vivant.py", r)[0] == "VIVANT"


def test_un_module_ailleurs_est_DEPLACE_et_non_MORT(tmp_path):
    """Le confondre avec un MORT ferait supprimer une mention encore valable."""
    r = _faux_depot(tmp_path)
    etat, precision = C.classer("app/forge_ailleurs.py", r)
    assert etat == "DEPLACE"
    assert "tools/forge_ailleurs.py" in precision, (
        "le gate doit DIRE ou le fichier se trouve, sinon il laisse chercher")


def test_une_faute_de_frappe_est_une_COQUILLE(tmp_path):
    r = _faux_depot(tmp_path)
    etat, precision = C.classer("sandbox/snn.wante", r)
    assert etat == "COQUILLE"
    assert "snn.wanted" in precision


def test_un_placeholder_pedagogique_n_est_JAMAIS_signale(tmp_path):
    """`tools/your_tool.py` est un exemple, pas un lien casse. Un gate qui crie
    dessus se fait desarmer, et on perd le signal utile avec."""
    r = _faux_depot(tmp_path)
    assert C.classer("tools/your_tool.py", r)[0] == "EXEMPLE"


def test_un_vrai_disparu_est_MORT(tmp_path):
    r = _faux_depot(tmp_path)
    assert C.classer("app/forge_disparu_sans_trace.py", r)[0] == "MORT"


def test_un_glob_n_est_NI_vivant_NI_mort(tmp_path):
    """`tools/forge_*.py` est un motif : le resoudre n'a pas de sens. Le compter
    mort fabriquerait un defaut, le compter vivant masquerait un trou."""
    r = _faux_depot(tmp_path)
    assert C.classer("tools/forge_*.py", r)[0] == "GLOB"


def test_le_check_echoue_SEULEMENT_sur_un_MORT(tmp_path, monkeypatch):
    r = _faux_depot(tmp_path)
    monkeypatch.setattr(C, "ROOT", r)
    docs = r / "docs"
    docs.mkdir()

    (docs / "p.md").write_text(
        "voir `app/forge_ailleurs.py` et `tools/your_tool.py` et "
        "`sandbox/snn.wante`\n", encoding="utf-8")
    assert C.main(["--dossier", "docs", "--check"]) == 0, (
        "deplace, exemple et coquille ne doivent pas faire echouer le gate")

    (docs / "q.md").write_text("voir `app/forge_parti.py`\n", encoding="utf-8")
    assert C.main(["--dossier", "docs", "--check"]) == 1


def test_une_page_ILLISIBLE_est_comptee_et_non_lue_comme_propre(tmp_path, monkeypatch):
    """ILLISIBLE != PROPRE. Une page qu'on n'a pas pu ouvrir ne prouve pas
    qu'elle ne cite aucun chemin mort."""
    r = _faux_depot(tmp_path)
    monkeypatch.setattr(C, "ROOT", r)
    docs = r / "docs"
    docs.mkdir()
    (docs / "ok.md").write_text("rien\n", encoding="utf-8")

    vrai_read = Path.read_text

    def _read(self, *a, **k):
        if self.name == "casse.md":
            raise OSError("acces refuse")
        return vrai_read(self, *a, **k)

    (docs / "casse.md").write_text("rien\n", encoding="utf-8")
    monkeypatch.setattr(Path, "read_text", _read)
    res = C.scanner(docs, r)
    assert len(res["illisibles"]) == 1
    assert res["pages"] == 1, "la page illisible ne doit pas etre comptee comme lue"


def test_un_dossier_absent_est_DIT_et_ne_vaut_pas_succes(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ROOT", tmp_path)
    assert C.main(["--dossier", "nulle_part", "--check"]) == 0
