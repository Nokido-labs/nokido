"""NR — le drain d'embedding s'abstient quand la machine est chargee (hysteresis).

Mesure 2026-09-06 : `forge_embed_auto_trigger` n'avait AUCUNE garde RAM - il vectorisait
a plein regime quelle que soit la charge. C'est ce qui avait mene a ecarter le pilier
local le 2026-09-01 (« machine a 98 % »). Le meme jour, l'embedder borne mesure
15,6 chunks/s pour un RSS qui plafonne a ~2,5 Go : le drain PEUT tourner, a condition
de se taire sous charge.

Quatre garanties :
  1. deux seuils, pas un (sinon le drain repart au dixieme de point et pompe) ;
  2. RAM illisible (-1) = abstention, JAMAIS feu vert (un capteur muet n'est pas
     « machine au repos ») ;
  3. les seuils viennent de `forge_physiology` (HIGH/RELEASE), pas de valeurs inventees ;
  4. sous le seuil de reprise, le drain travaille.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _d in ("app", "tools"):
    _p = str(ROOT / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

SRC = (ROOT / "tools" / "forge_embed_auto_trigger.py").read_text(encoding="utf-8", errors="replace")


def test_deux_seuils_avec_hysteresis_pas_un_seul():
    assert "RAM_PAUSE" in SRC and "RAM_REPRISE" in SRC
    # la reprise doit etre CONDITIONNELLE a l'etat de pause (hysteresis), pas au seul seuil
    assert re.search(r"_en_pause and _ram > RAM_REPRISE", SRC), "hysteresis absente"


def test_les_seuils_viennent_de_la_physiologie_du_corps():
    assert "from nokido_agent.tools.forge_physiology import HIGH as RAM_PAUSE, RELEASE as RAM_REPRISE" in SRC
    import forge_physiology as ph  # type: ignore
    assert ph.HIGH > ph.RELEASE, (ph.HIGH, ph.RELEASE)


def test_ram_illisible_rend_moins_un_et_provoque_abstention():
    # le capteur rend -1.0 (illisible), et le garde traite `< 0` comme une abstention
    assert re.search(r"return -1\.0", SRC), "le capteur RAM doit rendre -1.0 si illisible"
    assert re.search(r"if _ram < 0 or \(_ram >= RAM_PAUSE\)", SRC), "illisible non traite en abstention"
    assert "abstention" in SRC and "ram_pct" in SRC, "l'abstention doit etre DITE au heartbeat"


def test_le_capteur_ram_ne_rend_jamais_zero_sur_echec(monkeypatch):
    import importlib

    mod = importlib.import_module("forge_embed_auto_trigger")
    import psutil  # type: ignore

    def _boom():
        raise RuntimeError("capteur indisponible")

    monkeypatch.setattr(psutil, "virtual_memory", _boom)
    assert mod._ram_pct() == -1.0
