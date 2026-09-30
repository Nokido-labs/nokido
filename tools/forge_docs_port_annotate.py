# -*- coding: utf-8 -*-
"""forge_docs_port_annotate.py — annote les docs qui citent un port ARRETE.

Complement d'ecriture de `forge_capability_audit.c_ports_docs`, qui, lui, ne fait
que MESURER. Origine : audit AGY du 2026-08-30 — son extraction LLM avait expire
(timeout silencieux de `qwen2.5-coder:1.5b`) et son unique exemple etait faux, mais
le fond tenait : des documents citent des ports arretes sans le dire, et un lecteur
qui suit `:5557` tombe sur un service mort depuis le 2026-06-03.

Principe : ne RIEN reecrire du corps. On insere, juste apres le titre H1, un
encadre qui nomme les ports arretes que ce fichier mentionne, avec leur date et
leur remplacant. Le corps historique reste lisible tel qu'il a ete ecrit — c'est
une note de peremption, pas une reecriture du passe.

Idempotent : un fichier deja annote (marqueur `<!-- ports-arretes -->`) est saute.
Dry-run par defaut ; `--apply` pour ecrire.

    LAFORGE_PYTHON tools/forge_docs_port_annotate.py
    LAFORGE_PYTHON tools/forge_docs_port_annotate.py --apply
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARQUEUR = "<!-- ports-arretes -->"

# Source : CLAUDE.md §8/§13. Uniquement des arrets DATES et documentes — jamais un
# service simplement eteint a la demande, sinon l'annotation crierait a faux.
PORTS_ARRETES = {
    "5557": "`brain_worker :5557` est **arrete depuis le 2026-06-03** (OOM ONNX BGE-M3) — l'embedder vivant est `:8099` (BGE-M3 GGUF llama.cpp).",
    "8100": "`NokidoLlamaReranker :8100` est **arrete depuis le 2026-08-10** (boot-trim RAM) — le rerank passe alors par son repli (Cohere `/v2/rerank`, puis lexical).",
    "7474": "`NokidoGraphExplorer :7474` est **arrete depuis le 2026-08-10** (boot-trim RAM) — reveil a la demande.",
}

SIGNAL_ARRET = re.compile(
    r"disabled|désactiv|desactiv|arrêté|arrete|OOM|deprecated|obsol|historique|"
    r"remplac|au profit|n'est plus|boot-trim|on-demand|à la demande|a la demande|"
    r"coupé|coupe\b|éteint|eteint", re.I)


def ports_muets(lignes: list[str]) -> list[str]:
    """Ports arretes que ce fichier cite SANS signaler leur etat."""
    muets = []
    for port in sorted(PORTS_ARRETES):
        hits = [i for i, l in enumerate(lignes) if (":" + port) in l]
        if not hits:
            continue
        if not any(SIGNAL_ARRET.search("\n".join(lignes[max(0, i - 4):i + 5])) for i in hits):
            muets.append(port)
    return muets


def encadre(ports: list[str]) -> list[str]:
    """L'encadre a inserer. Une ligne par port, pour rester lisible en diff."""
    out = [MARQUEUR, "> ⚠️ **Ports arrêtés cités dans cette page** (note ajoutée le 2026-08-30 ;"
           " le corps ci-dessous n'a pas été réécrit) :", ">"]
    for p in ports:
        out.append("> - " + PORTS_ARRETES[p])
    out.append("")
    return out


def _point_d_insertion(lignes: list[str]) -> int:
    """Juste apres le titre H1 s'il existe, sinon en tete -- JAMAIS au-dessus d'un frontmatter.

    Mesure 2026-09-28 : un frontmatter OKF de 14 lignes (liste `sources`) repoussait le H1
    hors des 12 premieres lignes ; la note se posait en ligne 0, AU-DESSUS du `---`, et la
    page perdait son frontmatter (`missing_frontmatter`, gate L1 rouge). Et un commentaire
    YAML `# ...` dans le frontmatter aurait ete pris pour le titre. On saute donc le bloc
    `---` ... `---` d'abord ; un frontmatter non ferme laisse le comportement d'origine.
    """
    debut = 0
    if lignes and lignes[0].strip() == "---":
        for j in range(1, len(lignes)):
            if lignes[j].strip() == "---":
                debut = j + 1
                break
    for i in range(debut, min(len(lignes), debut + 12)):
        if lignes[i].startswith("# "):
            return i + 1
    return debut


def traiter(chemin: Path, apply: bool) -> tuple[str, list[str]]:
    texte = chemin.read_text(encoding="utf-8", errors="replace")
    if MARQUEUR in texte:
        return "deja", []
    lignes = texte.splitlines()
    muets = ports_muets(lignes)
    if not muets:
        return "rien", []
    i = _point_d_insertion(lignes)
    neuf = lignes[:i] + [""] + encadre(muets) + lignes[i:]
    if apply:
        chemin.write_text("\n".join(neuf) + "\n", encoding="utf-8")
    return "annote", muets


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="ecrit (defaut : dry-run)")
    ap.add_argument("--dossier", default="docs")
    a = ap.parse_args(argv)

    base = ROOT / a.dossier
    if not base.is_dir():
        print("ABSENT : %s" % base)
        return 2
    vus = illisibles = annotes = deja = 0
    for rep, dn, fn in os.walk(base):
        dn[:] = [d for d in dn if d not in ("archive", "i18n")]
        for f in sorted(fn):
            if not f.endswith(".md"):
                continue
            p = Path(rep) / f
            try:
                etat, muets = traiter(p, a.apply)
            except OSError as exc:
                illisibles += 1
                print("  ILLISIBLE %s (%s)" % (p.name, type(exc).__name__))
                continue
            vus += 1
            if etat == "annote":
                annotes += 1
                print("  %-9s %-52s %s" % ("ANNOTE" if a.apply else "A ANNOTER",
                                           str(p.relative_to(ROOT)).replace("\\", "/"),
                                           ",".join(muets)))
            elif etat == "deja":
                deja += 1
    print("\n%d fichier(s) scanne(s), %d illisible(s), %d a annoter, %d deja annote(s)%s"
          % (vus, illisibles, annotes, deja, "" if a.apply else "  [DRY-RUN]"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
