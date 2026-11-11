"""NR 9/11 (revue globale, choix owner « tagger + réparer le NR ») : le NR de stash@{3}
(archive/stash/3-skill-et-nr-masquage-secrets-ui) visait un VRAI trou -- `forge_mcp_registry.dispatch` publiait
`result_summary = str(result)[:200]` sur le bus (event_history, UI) SANS caviardage : un secret affiché par un outil
partait en clair. Son simulacre ne trouvait plus l'événement de fin ; réécrit ici contre le code actuel.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

import forge_mcp_registry as REG  # noqa: E402

# Faux jeton assemblé à l'exécution : jamais un littéral que le scan de secrets prendrait pour un vrai.
FAUX = "ghp_" + "a1B2c3D4e5" * 4


def test_secret_jamais_publie_en_clair():
    r = REG._resume_pour_bus("Secret found: %s fin" % FAUX, "run")
    assert FAUX not in r
    assert "Secret found:" in r          # la part non secrète reste informative
    assert len(r) <= 200


def test_texte_ordinaire_intact():
    assert REG._resume_pour_bus("No secret here, just regular output 12345", "run") == \
        "No secret here, just regular output 12345"


def test_caviardage_indisponible_retient_le_resume(monkeypatch):
    monkeypatch.setattr(REG, "_caviarder_essence", lambda t, o: (t, False, False))
    r = REG._resume_pour_bus("Secret found: %s" % FAUX, "run")
    assert FAUX not in r and "retenu" in r


def test_aucun_site_de_publication_ne_publie_le_brut():
    src = (ROOT / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8")
    assert "result_str[:200]" not in src
    blocs = re.findall(r'topic=f"tool\.\{name\}\.end".{0,400}', src, re.S)
    assert len(blocs) >= 3
    for b in blocs:
        assert "_resume_pour_bus" in b, b[:160]
