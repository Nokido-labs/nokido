"""NR 28/10 : le diagnostic de demarrage du worker ACP ne journalise que des NOMS de variables, jamais de valeurs.

Contexte mesure : le CLI claude lance par le worker (lanceur runas) sort rc=1 sans stderr 4 s apres session/new,
alors qu'il marchait depuis la console owner. On compare les NOMS de l'environnement des deux contextes.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_acp_worker as W  # noqa: E402


def test_diag_rend_les_noms_jamais_les_valeurs(monkeypatch):
    monkeypatch.setenv("NOKIDO_TEST_DIAG_SECRET", "valeur-tres-secrete-123")
    d = W.diag_environnement()
    assert "NOKIDO_TEST_DIAG_SECRET" in d["noms"]
    assert "valeur-tres-secrete-123" not in repr(d)
    assert set(d) >= {"noms", "exe", "compte", "profil"}


def test_diag_dit_les_variables_de_profil_absentes(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    d = W.diag_environnement()
    assert "APPDATA" in d["profil"]["absentes"]
