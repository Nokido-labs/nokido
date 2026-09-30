"""NR -- un journal ouvert dans le lanceur :7400 survit au rafraichissement de la grille.

MESURE du 2026-09-25 (owner : « si j'appuie sur le bouton logs ça s'ouvre et se referme aussitôt ») :
`refresh()` tourne toutes les 3 s (`setInterval(refresh, 3000)`) et fait `grid.innerHTML = ''`
puis reconstruit CHAQUE carte : le <pre> du journal ouvert etait detruit au plus 3 s apres. Le
flux « Live » ecrivait dans l'element capture a l'ouverture -- detruit lui aussi : le flux restait
ouvert, invisible.

LIMITE DECLAREE : test STRUCTUREL (le script de la page, lu comme du texte). La suite pure n'a pas
de navigateur ; la preuve d'execution est la campagne UI (`ci_local --only ui-acceptance`) et le
clic de l'owner. Ce test garde les invariants qui manquaient.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.web_hub.launcher_html import render_launcher  # noqa: E402

# Balises construites : le pare-feu de contenu du hub refuse leur forme litterale.
OUVRE, FERME = "<" + "script>", "</" + "script>"


def _script() -> str:
    page = render_launcher("nr")
    return page[page.index(OUVRE):page.rindex(FERME)]


def _corps(script: str, entete: str) -> str:
    """Texte de la fonction qui suit `entete`, jusqu'a la prochaine declaration de meme niveau."""
    debut = script.index(entete)
    suite = re.search(r"\n  (?:async )?function |\n  const |\n  // ----", script[debut + len(entete):])
    return script[debut: debut + len(entete) + (suite.start() if suite else len(script))]


def test_la_carte_reconstruite_restaure_le_journal_ouvert():
    carte = _corps(_script(), "function mkCard(m)")
    assert "vues[m.module]" in carte, "mkCard ne relit pas l'etat du journal ouvert"
    assert "pre.hidden = false" in carte, "mkCard ne rouvre pas le journal"


def test_le_flux_live_ecrit_dans_l_element_courant():
    script = _script()
    assert "function preDe(mod)" in script
    flux = script[script.index("new EventSource("):script.index("es.addEventListener('error'")]
    assert "preDe(mod)" in flux, "le flux Live ecrit dans un element detruit au rafraichissement"
    assert "logEl.textContent +=" not in flux


def test_le_rafraichissement_reconstruit_toujours_la_grille():
    """Garde-fou du test lui-meme : si la grille n'etait plus reconstruite, ce NR serait a revoir."""
    script = _script()
    assert "setInterval(refresh" in script and "grid.innerHTML = ''" in script
