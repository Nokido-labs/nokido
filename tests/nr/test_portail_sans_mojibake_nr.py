"""NR -- aucune page du portail :7400 ne porte de mojibake ; l'Event Feed affiche l'heure du PC.

MESURE du 2026-09-25 (owner, /forge/feed) : le titre affichait `ðŸ§ ` a la place de 🧠 et
« Aucun Ã©vÃ©nement ». Ce n'etait PAS un defaut de transport : les octets UTF-8, relus en
Windows-1252 puis re-enregistres, etaient FIGES dans la source (forge_feed.html:74, 107, 161).
Meme page : l'heure etait la portion brute de `ts`, UTC NAIF (forge_state_manager :
`datetime.utcnow().isoformat()`), donc l'heure universelle et non celle du PC.

Le scan couvre toute la classe (pages, gabarits, scripts du portail), pas le seul fichier vu.
LIMITE DECLAREE pour l'heure : controle STRUCTUREL (pas de navigateur dans la suite pure).
"""
from __future__ import annotations

import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
PORTAIL = RACINE / "app" / "web_hub"
# Sequences produites par de l'UTF-8 relu en Windows-1252 (é -> Ã©, emoji -> ðŸ, ' -> â€™).
MOJIBAKE = re.compile("Ã[ -¿]|ðŸ|â€[™œ\u009d¦”“]|Â[ «»°·]")


def test_aucune_page_du_portail_ne_porte_de_mojibake():
    fautifs = []
    for p in sorted(PORTAIL.rglob("*")):
        if p.suffix not in (".html", ".py", ".js", ".css") or "node_modules" in p.parts:
            continue
        for n, ligne in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if MOJIBAKE.search(ligne):
                fautifs.append("%s:%d" % (p.relative_to(RACINE).as_posix(), n))
    assert not fautifs, "texte double-encode dans le portail : %s" % fautifs[:20]


def test_event_feed_convertit_l_utc_en_heure_locale():
    page = (PORTAIL / "forge_feed.html").read_text(encoding="utf-8")
    assert "function heureLocale(ts)" in page
    assert "heureLocale(e.ts)" in page, "l'horodatage n'est pas converti avant affichage"
    assert "toLocaleTimeString" in page
    assert "e.ts.split('T')[1]" not in page, "retour de l'affichage brut (UTC)"
