"""NR — le cliquet des lectures de secrets DETECTE, et ne crie pas a faux.

Un garde qu'on ne peut pas faire virer au ROUGE dans un test n'est pas une securite :
c'est une dette de cablage. Mesure du 2026-09-03, deux fois dans la meme journee : un
frein d'admission branche sur une hormone que personne n'emettait, et un module de
progression importe par deux consommateurs alors qu'il n'avait jamais ete ecrit. Dans
les deux cas le code se relisait comme protege.

On eprouve donc les trois verdicts sur un depot jetable :
  - une lecture directe dans l'environnement  -> HORS COFFRE
  - la meme precedee de `get_secret()`        -> REPLI (contrat respecte)
  - un REGLAGE qui porte le mot-cle           -> ignore (un nom n'est pas une preuve)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

audit = pytest.importorskip("forge_secret_source_audit")


def _depot(tmp_path: Path, nom: str, code: str) -> Path:
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / nom).write_text(code, encoding="utf-8")
    return tmp_path


def test_une_lecture_directe_est_vue_comme_hors_coffre(tmp_path: Path) -> None:
    r = _depot(tmp_path, "faux_module.py",
               "import os\nJ = os.environ.get('ACME_API_KEY', '')\n")
    trouves, stats = audit.scanner(racine=r, bases=("app",))
    assert stats["fichiers_lus"] == 1, stats
    assert [(t[2], t[3]) for t in trouves] == [("ACME_API_KEY", "HORS COFFRE")], trouves


def test_un_repli_apres_get_secret_est_conforme(tmp_path: Path) -> None:
    """L'environnement en DERNIER recours est le contrat, pas une infraction."""
    r = _depot(tmp_path, "faux_repli.py",
               "import os\n"
               "from forge_secrets import get_secret\n"
               "j = get_secret('ACME_API_KEY')\n"
               "if not j:\n"
               "    j = os.environ.get('ACME_API_KEY', '')\n")
    trouves, _ = audit.scanner(tout=True, racine=r, bases=("app",))
    assert [t[3] for t in trouves] == ["REPLI"], trouves


def test_un_reglage_qui_porte_le_mot_cle_n_est_pas_signale(tmp_path: Path) -> None:
    """TOKENIZERS_PARALLELISM ou MAX_TOKENS ne sont pas des secrets. Les signaler
    ferait crier le garde a faux — et un garde qui crie a faux se fait desarmer."""
    r = _depot(tmp_path, "faux_reglage.py",
               "import os\n"
               "a = os.environ.get('TOKENIZERS_PARALLELISM', 'false')\n"
               "b = os.environ.get('ONNXGENAI_MAX_TOKENS', '512')\n"
               "c = os.environ.get('LAFORGE_ALLOW_SECRETS_READ', '0')\n")
    trouves, _ = audit.scanner(tout=True, racine=r, bases=("app",))
    assert trouves == [], trouves


def test_un_chemin_vers_un_secret_n_est_pas_un_secret(tmp_path: Path) -> None:
    """`X_TOKEN_FILE` et `CREDENTIALS_DIRECTORY` (systemd `LoadCredential`, convention
    Docker `*_FILE`) portent un CHEMIN : le secret vit dans le fichier, que la rotation
    met a jour. Mesure du 2026-09-28 : le cliquet rougissait sur le noeud edge alors
    que `_PATH` et `_DIR` passaient deja. Le jeton lui-meme, lu dans l'environnement,
    reste signale."""
    r = _depot(tmp_path, "faux_edge.py",
               "import os\n"
               "d = os.environ.get('CREDENTIALS_DIRECTORY')\n"
               "f = os.environ.get('ACME_OTA_TOKEN_FILE')\n"
               "t = os.environ.get('ACME_OTA_TOKEN')\n")
    trouves, _ = audit.scanner(tout=True, racine=r, bases=("app",))
    assert [(t[2], t[3]) for t in trouves] == [("ACME_OTA_TOKEN", "HORS COFFRE")], trouves


def test_un_fichier_exempt_n_est_pas_juge(tmp_path: Path) -> None:
    """`forge_secrets` EST la couche environnement : l'y interdire serait absurde."""
    r = _depot(tmp_path, "forge_secrets.py",
               "import os\nj = os.environ.get('ACME_API_KEY', '')\n")
    trouves, stats = audit.scanner(tout=True, racine=r, bases=("app",))
    assert trouves == [], trouves
    assert stats["exempts"] >= 1, stats


def test_le_socle_du_depot_existe_et_est_non_vide() -> None:
    """Sans socle lisible, le cliquet ne rend AUCUN verdict — il serait present
    sans garder. On verifie donc l'armement, pas seulement le fichier de code."""
    import json

    socle = audit.SOCLE
    assert socle.is_file(), "socle absent : cliquet non arme (%s)" % socle
    entrees = json.loads(socle.read_text(encoding="utf-8"))
    assert entrees, "socle vide : le cliquet laisserait tout passer"
    assert all("::" in e for e in entrees), "format attendu fichier::CLE"
