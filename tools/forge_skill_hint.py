"""forge_skill_hint.py -- le rappel d'une skill arrive au MOMENT ou elle s'applique.

__FORGE_COLOR__ = "skill-management"

POURQUOI (owner 2026-10-14). /doctor : 4 skills sur 26 utilisees sur la fenetre observee. Une
skill n'est choisie que si sa description est relue au bon moment ; la liste chargee en debut de
session ne l'est pas. La doctrine le dit deja des gardes -- « le rappel arrive au moment de
l'erreur, pas dans une liste » : ce module l'applique aux skills.

Anti-dup (verifie 2026-10-14) : `introspect` sur « hook qui suggere une skill » ne rend rien ;
forge_skill_capability_graph et forge_skill_realisations decrivent ce qu'une skill FAIT, pas
QUAND la proposer ; hook_capability_gate rappelle des FORMES d'outil avant l'appel, pas des skills.

Donnee, pas code : config/skill_triggers.json. Appele par deux hooks DEJA cables, donc aucun
reglage a toucher : hook_context_firewall (PostToolUse sur run/Bash/PowerShell : la sortie d'un
outil) et claude_inbox_tick (UserPromptSubmit : la demande de l'owner).

Discipline :
  - un rappel par skill et par session au plus toutes les RAPPEL_S secondes : un rappel qui
    crie a chaque appel se fait ignorer, puis desarmer ;
  - chaque rappel emis est journalise (sandbox/skill_hints.jsonl) : la conversion rappel ->
    invocation se MESURE contre `skillUsage` de ~/.claude.json, elle ne se suppose pas ;
  - table illisible ou declencheur invalide : on le DIT sur stderr. Jamais un faux calme muet.

  verifier la table : LAFORGE_PYTHON tools/forge_skill_hint.py --verifier   (rc 1 si un defaut)
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "config" / "skill_triggers.json"
SKILLS = ROOT / "docs" / "skills"
RETIRES = ROOT / "docs" / "skills_attic" / "retires.json"
JOURNAL = ROOT / "sandbox" / "skill_hints.jsonl"
ETAT = ROOT / "sandbox" / "skill_hints_etat"
RAPPEL_S = 1800
# Une sortie d'outil peut peser des Mo : on lit la tete et la queue, la ou pytest et les traces
# posent leur verdict. Le milieu n'est PAS lu -- un motif qui n'apparaitrait que la est rate.
TETE, QUEUE = 20_000, 60_000
# Un texte qui CITE une skill n'est pas un symptome : mesure 2026-10-14, une sortie de
# `forge_skill_sync --preview` collee par l'owner a declenche forge-m2m-debat-mesure, forge-tdd et
# forge-android sur leurs seuls noms (« m2m », « debat », « tdd », « android »). Les noms de skills
# sont retires du texte avant la recherche des motifs.
_NOMS_DE_SKILLS = re.compile(r"(?i)\b(?:forge|nokido|laforge)-[a-z0-9][a-z0-9-]*")


def charger(chemin=None) -> list:
    """Declencheurs valides de la table. Ce qui est ecarte est dit sur stderr."""
    chemin = Path(chemin or TABLE)
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print("[skill-hint] table illisible (%s : %s) : aucun rappel" % (chemin.name, type(e).__name__),
              file=sys.stderr)
        return []
    valides = []
    for i, d in enumerate(brut.get("declencheurs", [])):
        try:
            v = {"skill": str(d["skill"]), "evenement": str(d["evenement"]),
                 "outils": tuple(d.get("outils") or ()),
                 "tous": [re.compile(m) for m in d.get("tous", [])],
                 "un_de": [re.compile(m) for m in d.get("un_de", [])],
                 "pourquoi": str(d["pourquoi"])}
        except (KeyError, TypeError, re.error) as e:
            print("[skill-hint] declencheur %d ecarte (%s : %s)" % (i, type(e).__name__, e), file=sys.stderr)
            continue
        if not v["tous"] and not v["un_de"]:
            print("[skill-hint] declencheur %d ecarte (aucun motif)" % i, file=sys.stderr)
            continue
        valides.append(v)
    return valides


def _texte(valeur) -> str:
    if valeur is None:
        return ""
    t = valeur if isinstance(valeur, str) else json.dumps(valeur, ensure_ascii=False)
    t = t if len(t) <= TETE + QUEUE else t[:TETE] + "\n" + t[-QUEUE:]
    return _NOMS_DE_SKILLS.sub(" ", t)


def _correspond(d: dict, texte: str) -> bool:
    return (all(m.search(texte) for m in d["tous"])
            and (not d["un_de"] or any(m.search(texte) for m in d["un_de"])))


def suggerer(evenement: str, texte, outil: str = "", session: str = "", maintenant=None,
             declencheurs=None, etat_dir=None, journal=None) -> list:
    """Lignes de rappel a injecter ; vide si rien ne s'applique ou si deja rappele recemment."""
    maintenant = time.time() if maintenant is None else maintenant
    texte = _texte(texte)
    if not texte:
        return []
    candidats = []
    for d in (charger() if declencheurs is None else declencheurs):
        if d["evenement"] != evenement or (d["outils"] and outil not in d["outils"]):
            continue
        if d["skill"] not in {c["skill"] for c in candidats} and _correspond(d, texte):
            candidats.append(d)
    if not candidats:
        return []
    nom = "".join(c for c in session if c.isalnum() or c in "-_")[:80] or "sans_session"
    etat_f = Path(etat_dir or ETAT) / ("%s.json" % nom)
    try:
        vu = json.loads(etat_f.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # muet-ok : premier rappel de la session, ou etat illisible -> on rappelle
        vu = {}
    emis = [d for d in candidats if maintenant - float(vu.get(d["skill"], 0)) >= RAPPEL_S]
    if not emis:
        return []
    for d in emis:
        vu[d["skill"]] = maintenant
    try:
        etat_f.parent.mkdir(parents=True, exist_ok=True)
        etat_f.write_text(json.dumps(vu), encoding="utf-8")
    except OSError as e:
        print("[skill-hint] etat non ecrit (%s) : rappel repete possible" % type(e).__name__, file=sys.stderr)
    try:
        j = Path(journal or JOURNAL)
        j.parent.mkdir(parents=True, exist_ok=True)
        with j.open("a", encoding="utf-8") as fh:
            for d in emis:
                fh.write(json.dumps({"ts": maintenant, "skill": d["skill"], "evenement": evenement,
                                     "outil": outil, "session": session}, ensure_ascii=False) + "\n")
    except OSError as e:
        print("[skill-hint] journal non ecrit (%s) : rappel non mesurable" % type(e).__name__, file=sys.stderr)
    return ["[skill] %s s'applique : %s. Charger avec l'outil Skill." % (d["skill"], d["pourquoi"])
            for d in emis]


def verifier(chemin=None, skills=None, retires=None) -> list:
    """Defauts de la table : skill absente du canonical, skill retiree, declencheur ecarte."""
    chemin = Path(chemin or TABLE)
    skills, retires = Path(skills or SKILLS), Path(retires or RETIRES)
    try:
        bruts = json.loads(chemin.read_text(encoding="utf-8")).get("declencheurs", [])
    except (OSError, ValueError) as e:
        return ["table illisible : %s" % type(e).__name__]
    try:
        hors_service = {k for k in json.loads(retires.read_text(encoding="utf-8")) if not k.startswith("_")}
    except FileNotFoundError:  # muet-ok : registre absent = aucun retrait declare
        hors_service = set()
    except (OSError, ValueError) as e:
        return ["registre des skills retirees illisible : %s" % type(e).__name__]
    defauts = []
    if len(charger(chemin)) != len(bruts):
        defauts.append("%d declencheur(s) ecarte(s) au chargement (detail sur stderr)"
                       % (len(bruts) - len(charger(chemin))))
    for d in bruts:
        nom = str(d.get("skill"))
        if not (skills / nom / "SKILL.md").exists():
            defauts.append("%s : absente de %s" % (nom, skills.name))
        if nom in hors_service:
            defauts.append("%s : skill RETIREE, son declencheur doit partir avec elle" % nom)
    return defauts


if __name__ == "__main__":
    if "--verifier" in sys.argv:
        problemes = verifier()
        for p in problemes:
            print("DEFAUT", p)
        print("skill_triggers : %s" % ("CONFORME" if not problemes else "%d defaut(s)" % len(problemes)))
        sys.exit(1 if problemes else 0)
    print(__doc__)
