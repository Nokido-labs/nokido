"""NR -- la page postal DIT quand le registre live des agents est indisponible.

Dette `ui_audit_webhub_demo_residuelle` point (3), audit du 01/08 : `postal.html` porte une liste
d'agents codee en dur (seed) que `/api/agents` surcharge en live ; sur echec ou timeout, le
`.catch(()=>{})` retombait EN SILENCE sur le seed -- l'owner lisait des rings/canaux figes comme
s'ils venaient du registre (UNKNOWN != NO : une source muette ne prouve rien).
"""
import re
from pathlib import Path

PAGE = Path(__file__).resolve().parents[2] / "app" / "web_hub" / "postal.html"


def _appel_registre(src: str) -> str:
    debut = src.index("fetch('/api/agents')")
    return src[debut:src.index("connect();", debut)]


def test_l_echec_du_registre_live_n_est_pas_avale_en_silence():
    appel = _appel_registre(PAGE.read_text(encoding="utf-8"))
    assert not re.search(r"\.catch\(\s*\(\s*\)\s*=>\s*\{\s*\}\s*\)", appel)


def test_la_page_affiche_la_provenance_du_registre():
    assert 'id="registre"' in PAGE.read_text(encoding="utf-8")
