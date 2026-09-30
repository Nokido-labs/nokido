#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/forge_tui_textual.py — la TUI Textual de Nokido, branchee sur le REEL.

POURQUOI CE FICHIER EXISTE (2026-08-29)
=======================================
Deux moities de TUI trainaient sans jamais se rejoindre :

* `tools/archive_tui/swarm_dashboard_v2.py` (30 avril) — le LAYOUT est bon et
  l'archive dit vrai quand elle se declare « fonctionnelle et esthetique », mais
  tout ce qu'elle AFFICHE est faux : arbres d'agents en dur (« Cortex (7B) -
  Idle »), heartbeat fige a « 60 BPM | Sync OK » avec un emoji qui clignote, et
  un `simulate_event_bus` qui tire au hasard dans une liste d'evenements
  inventes. C'est une maquette de demonstration — exactement ce que la regle
  « GUI live-only, aucune tuile demo » interdit de servir.

* `tools/forge_tui.py` — les COLLECTEURS, eux, lisent du reel : HTTP sur les
  services, fichiers heartbeat sur disque, SQLite du RAG, git. Mais ses widgets
  Textual etaient colles APRES son `if __name__ == "__main__"`, donc
  inatteignables, dans un module dont la docstring dit « no textual ». Et ils
  etaient casses : `HeartbeatTail.on_mount` appelait un `scan_heartbeats` qui
  n'existe pas, `ServiceMonitor` posait ses `reactive` dans `__init__` (ou ils
  ne reagissent pas). Des widgets que personne ne monte ne se voient jamais
  echouer.

Ici on garde le layout de l'un et les donnees de l'autre. Aucune valeur n'est
inventee : ce qui ne se lit pas s'affiche ILLISIBLE, avec le type d'erreur — un
panneau vide et un panneau muet ne doivent pas se ressembler.

USAGE
=====
    LAFORGE_PYTHON tools/forge_tui_textual.py            # plein ecran (TTY requis)
    LAFORGE_PYTHON tools/forge_tui_textual.py --once     # un instantane texte

`--once` n'exige pas de terminal : il sert aux comptes de service et au controle
depuis un agent, la ou une TUI ne peut pas s'afficher.
"""

from __future__ import annotations

__FORGE_COLOR__ = "interface/proprioception-terminal"

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.tools import forge_tui  # noqa: E402 — les collecteurs REELS, jamais reecrits ici

INTERVALLE_S = 3.0

# (identifiant, titre, NOM du collecteur). Chaque collecteur vit dans forge_tui :
# cette TUI n'a pas le droit d'avoir sa propre idee de l'etat du systeme, sinon
# deux surfaces divergeraient sur ce qu'est « le RAG ».
# On garde le NOM et non la fonction : resolu a l'appel, le collecteur reste
# substituable — sans quoi un test devrait joindre le reseau, SQLite et git pour
# verifier un affichage, donc ne serait plus hermetique.
SOURCES = (
    ("services", "SERVICES", "check_services"),
    ("heartbeats", "HEARTBEATS", "get_heartbeats"),
    ("rag", "RAG", "get_rag_status"),
    ("git", "GIT", "get_git_info"),
)


def collecter() -> dict:
    """Rend {identifiant: (titre, lignes, erreur|None)}.

    TROIS etats par source : des lignes / une liste vide / illisible. Un
    collecteur qui leve ne doit pas vider le panneau en silence — un ecran calme
    se lit comme un systeme calme."""
    out = {}
    for ident, titre, nom_fn in SOURCES:
        try:
            lignes = list(getattr(forge_tui, nom_fn)() or [])
            out[ident] = (titre, lignes, None)
        except Exception as ex:  # noqa: BLE001 — illisible EST un resultat, on le nomme
            out[ident] = (titre, [], "%s: %s" % (type(ex).__name__, str(ex)[:120]))
    return out


def instantane() -> str:
    """Le meme etat, en texte, sans terminal ni Textual."""
    lignes = ["Nokido — instantane %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ""]
    for _ident, (titre, corps, erreur) in collecter().items():
        lignes.append("── %s ──" % titre)
        if erreur:
            lignes.append("   ILLISIBLE — %s" % erreur)
        elif not corps:
            lignes.append("   (aucune ligne — lu, et vide)")
        else:
            lignes += ["   " + l for l in corps]
        lignes.append("")
    return "\n".join(lignes)


def _construire_app():
    """Importe Textual seulement ici : `--once` doit marcher sans lui."""
    from textual.app import App, ComposeResult
    from textual.containers import Grid
    from textual.widgets import Footer, Header, Static

    class Panneau(Static):
        """Un cadre, un titre, et ce que la source a REELLEMENT rendu."""

        def __init__(self, titre: str, **kw) -> None:
            super().__init__(**kw)
            self.titre = titre
            self.border_title = titre
            # Ce qui a ete AFFICHE, tel quel. Textual ne rend pas le contenu d'un
            # Static de facon stable d'une version a l'autre (`renderable` a
            # disparu) : sans ce miroir, aucun test ne peut verifier qu'un panneau
            # montre bien ce que le collecteur a rendu — et un panneau qu'on ne
            # verifie pas est un panneau qui peut se vider en silence.
            self.dernier_texte = ""

        def poser(self, lignes: list, erreur: str | None) -> None:
            if erreur:
                texte = "[b red]ILLISIBLE[/b red]\n%s" % erreur
            elif not lignes:
                texte = "[dim](aucune ligne — lu, et vide)[/dim]"
            else:
                texte = "\n".join(lignes)
            self.dernier_texte = texte
            self.update(texte)

    class NokidoTUI(App):
        TITLE = "Nokido — etat vivant"
        BINDINGS = [("q", "quit", "Quitter"), ("r", "rafraichir", "Rafraichir")]
        CSS = """
        Grid#grille { grid-size: 2 2; grid-gutter: 1; padding: 1; }
        Panneau {
            border: round $accent; padding: 0 1; height: 100%;
            overflow-y: auto;
        }
        """

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Grid(id="grille"):
                for ident, titre, _nom in SOURCES:
                    yield Panneau(titre, id="p_" + ident)
            yield Footer()

        def on_mount(self) -> None:
            self.rafraichir()
            self.set_interval(INTERVALLE_S, self.rafraichir)

        def action_rafraichir(self) -> None:
            self.rafraichir()

        def rafraichir(self) -> None:
            # Les collecteurs font des I/O bloquantes (HTTP, SQLite, git) : dans la
            # boucle d'evenements ils gelent l'affichage. Un fil dedie, et le
            # resultat repasse par call_from_thread.
            self.run_worker(self._collecte, thread=True, exclusive=True)

        def _collecte(self) -> None:
            for ident, (_titre, lignes, erreur) in collecter().items():
                self.call_from_thread(self._poser, ident, lignes, erreur)

        def _poser(self, ident: str, lignes: list, erreur: str | None) -> None:
            try:
                self.query_one("#p_" + ident, Panneau).poser(lignes, erreur)
            except Exception as ex:  # noqa: BLE001 — panneau demonte pendant l'arret
                self.log("panneau %s injoignable : %s" % (ident, type(ex).__name__))

    return NokidoTUI


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--once" in argv:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass  # muet-ok : la sortie reste lisible en ascii degrade
        print(instantane())
        return 0
    try:
        app = _construire_app()()
    except ImportError as ex:
        print("textual absent (%s) — `--once` reste disponible." % ex, file=sys.stderr)
        return 2
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
