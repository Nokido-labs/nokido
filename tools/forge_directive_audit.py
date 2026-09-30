"""forge_directive_audit.py — consignes owner données en session mais JAMAIS consignées.

Bug récurrent, payé le 2026-08-02 : l'owner rappelle « on avait dit fini les temp », et la
vérification montre qu'aucune mémoire ne porte cette règle. Elle avait été donnée oralement
en session, jamais écrite — donc re-violée. **Une règle non consignée est une règle qui sera
re-violée**, et l'agent qui la re-viole ne peut même pas savoir qu'il récidive.

## Ce que fait cet outil, et ce qu'il ne fait pas

Il ne mesure pas des taux — `forge_recurrence_audit` le fait déjà (recadrages, redites,
tendance par session). Il répond à une autre question : **quelles DIRECTIVES DURABLES ai-je
reçues, et lesquelles n'ont aucune trace écrite ?** C'est un audit de COUVERTURE, pas de
fréquence.

Une demande ponctuelle (« lance le job ») n'est pas une directive durable. Seuls comptent
les énoncés portant une marque de GÉNÉRALITÉ (« toujours », « jamais », « plus jamais »,
« à chaque fois », « désormais », « on avait dit », « fini les »…) : ce sont ceux qui valent
au-delà du tour où ils sont dits, donc ceux qui doivent être écrits.

## Trois états, jamais deux

Le dossier des transcripts vit dans le profil owner et reste **illisible aux comptes de
service** : un scan qui rend « 0 directive » depuis le sandbox ne dit pas « tout est
consigné », il dit « je n'ai pas pu regarder ». L'outil distingue donc ILLISIBLE de VIDE,
et refuse de conclure dans le premier cas. Exécution attendue côté owner.

## Dette déclarée

La lecture des transcripts est aussi implémentée dans `forge_recurrence_audit.scan_sessions`
(mêmes filtres : `tool_result` écartés, `<system-reminder>` écartés, `isMeta` écarté). Les
deux doivent converger vers `messages_owner()` ci-dessous — non fait ici parce que ce
refactor ne peut pas être TESTÉ depuis un compte aveugle aux transcripts, et qu'on ne livre
pas un changement qu'on ne peut pas exécuter.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

__FORGE_COLOR__ = "memoire/audit-de-couverture"

# Marques de GÉNÉRALITÉ : ce qui vaut au-delà du tour où c'est dit.
GENERALITE = (
    "toujours", "jamais", "plus jamais", "a chaque fois", "à chaque fois",
    "systematiquement", "systématiquement", "desormais", "désormais", "dorenavant",
    "dorénavant", "on avait dit", "on a dit", "je t'ai dit", "je te l'ai dit",
    "fini les", "fini le", "arrete de", "arrête de", "ne fais plus", "ne refais plus",
    "interdit", "obligatoire", "tu dois", "il faut que tu", "je veux que tu",
    "je veux plus", "je ne veux plus", "en aucun cas", "chaque fois", "par principe",
    "regle", "règle",
)
# Reproches : une directive rappelée sous cette forme est une RÉCIDIVE avérée.
RECIDIVE = (
    "encore une fois", "tu n'as pas respecte", "tu n as pas respecte",
    "tu n'as pas respecté", "combien de fois", "je te repete", "je te répète",
    "comme d'habitude", "inadmissible", "recidive", "récidive",
)
# Mots vides : ils ne discriminent rien pour retrouver une mémoire couvrante.
VIDES = {
    "avec", "pour", "dans", "cette", "cela", "faire", "fait", "plus", "moins", "tout",
    "tous", "toute", "toutes", "veux", "peux", "dois", "faut", "alors", "aussi", "meme",
    "même", "quand", "comme", "sans", "sous", "chez", "elle", "nous", "vous", "leur",
    "mais", "donc", "parce", "puis", "encore", "toujours", "jamais", "avait", "avons",
    "etre", "être", "avoir", "juste", "vraiment", "bien", "trop", "tres", "très",
    "quoi", "dire", "dit", "regle", "règle", "chaque", "fois",
}
MOT = re.compile(r"[a-zA-Zà-ÿ_][\w\-à-ÿ]{3,}")
DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def messages_owner(fichier: Path,
                   compteurs: dict | None = None) -> tuple[list[str], str | None]:
    """Textes RÉELLEMENT tapés par l'owner, et l'horodatage du premier.

    `compteurs` (optionnel, rempli sur place) porte la VOLUMÉTRIE de la session :
    `lignes` (événements du transcript) et `messages_owner`. Il existe parce qu'un
    comptage d'erreurs sans dénominateur ne se juge pas — mesure du 2026-09-18 : les
    aveux par session passaient de 11,9 (août) à 28,7 (septembre) SANS qu'on puisse
    dire si les sessions avaient simplement grossi. Le paramètre est optionnel pour
    ne casser aucun appelant, et il est rempli dans la boucle EXISTANTE : relire les
    transcripts une seconde fois doublerait le coût d'un démarrage de session.

    On compte les ÉVÉNEMENTS, pas les messages owner : ces derniers sont un
    dénominateur biaisé, déjà payé le 2026-07-30 — un mois riche en « ok » / « go »
    fait baisser mécaniquement tout taux rapporté à eux.

    Quatre filtres, chacun pour une raison mesurée :
      · `type != "user"` — on ne veut pas l'assistant ;
      · blocs `tool_result` — ils arrivent AUSSI en type "user" ; les compter gonfle le
        dénominateur et fabrique un score flatteur (piège payé le 2026-07-30) ;
      · `<system-reminder>` en tête — injection du harnais, pas une parole d'owner ;
      · `isMeta` / texte commençant par « < » — événements de session.
    """
    textes: list[str] = []
    premier_ts: str | None = None
    with fichier.open(encoding="utf-8", errors="replace") as fh:
        for ligne in fh:
            if compteurs is not None:
                compteurs["lignes"] = compteurs.get("lignes", 0) + 1
            if '"user"' not in ligne:
                continue
            try:
                ev = json.loads(ligne)
            except (ValueError, TypeError):  # muet-ok : ligne tronquee, la suivante est lisible
                continue
            # `isCompactSummary` : quand le contexte est compacte, un message de
            # type "user" est injecte AVEC LE RESUME REDIGE PAR L'ASSISTANT. Il
            # porte donc la prose de l'agent sous l'etiquette de l'owner --
            # mesure du 2026-09-18 : huit entrees sur soixante commencaient par
            # « ⚠️ », « **Go.** » ou une puce de rapport, c'est-a-dire ma propre
            # ecriture presentee comme « ce que Nokido a compris de toi ».
            if ev.get("type") != "user" or ev.get("isMeta") or ev.get("isCompactSummary"):
                continue
            msg = ev.get("message") or {}
            contenu = msg.get("content")
            if isinstance(contenu, list):
                if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in contenu):
                    continue
                txt = " ".join(str(b.get("text", "")) for b in contenu
                               if isinstance(b, dict) and b.get("type") in (None, "text"))
            else:
                txt = str(contenu or "")
            txt = txt.strip()
            if not txt or txt.startswith("<") or "<system-reminder>" in txt[:200]:
                continue
            ts = str(ev.get("timestamp") or "")
            if ts and premier_ts is None:
                premier_ts = ts
            textes.append(txt)
    if compteurs is not None:
        compteurs["messages_owner"] = len(textes)
    return textes, premier_ts


def empreinte(texte: str, n: int = 6) -> list[str]:
    """Mots discriminants d'une directive, pour retrouver une mémoire qui la porterait."""
    vus: list[str] = []
    for m in MOT.finditer(texte.lower()):
        mot = m.group(0)
        if mot in VIDES or mot in vus:
            continue
        vus.append(mot)
    vus.sort(key=len, reverse=True)
    return vus[:n]


def directives(dossier: Path) -> dict:
    """Extrait les directives DURABLES de tous les transcripts. ILLISIBLE ≠ VIDE.

    Scanne le dossier ET ses sous-dossiers de 1er niveau (`*/*.jsonl`) — le corpus vit
    dans PLUSIEURS dossiers projet sous ~/.claude/projects/ (renommage LaForge->Nokido +
    cwd = superrepo ou submodule) : ne scanner qu'UN dossier ratait des conversations
    depuis mars (défaut mesuré 02/08). Exclut `subagents/` (pas des conversations owner)."""
    if not dossier.exists():
        return {"etat": "ILLISIBLE", "raison": f"dossier absent ou interdit : {dossier}"}
    fichiers = sorted(
        f for f in (set(dossier.glob("*.jsonl")) | set(dossier.glob("*/*.jsonl")))
        if f.is_file() and "subagents" not in f.parts)
    if not fichiers:
        return {"etat": "ILLISIBLE",
                "raison": f"aucun transcript sous {dossier} — profil owner illisible "
                          f"depuis un compte de service ? Ne PAS lire ceci comme « rien à signaler »."}
    trouvees, illisibles = [], []
    volumetrie: list[dict] = []
    for f in fichiers:
        compteurs: dict = {}
        try:
            textes, ts = messages_owner(f, compteurs)
        except OSError as exc:
            illisibles.append({"session": f.stem[:8], "raison": str(exc)[:70]})
            continue
        d = (DATE.search(ts or "") or [None])
        date = d.group(0) if hasattr(d, "group") else None
        # LE DÉNOMINATEUR, déposé avec le reste : sans lui, « N aveux dans cette
        # session » ne se compare à rien, et une hausse peut n'être qu'un
        # allongement des sessions.
        volumetrie.append({"session": f.stem[:8], "date": date,
                           "lignes": compteurs.get("lignes", 0),
                           "messages_owner": compteurs.get("messages_owner", 0)})
        for txt in textes:
            bas = txt.lower()
            if len(txt) < 15 or len(txt) > 1200:
                continue
            if not any(g in bas for g in GENERALITE):
                continue
            trouvees.append({
                "session": f.stem[:8],
                "date": date,
                "recidive": any(r in bas for r in RECIDIVE),
                "texte": txt.replace("\n", " ")[:220],
                "empreinte": empreinte(txt),
            })
    return {"etat": "ok", "n_transcripts": len(fichiers), "n_directives": len(trouvees),
            "directives": trouvees, "illisibles": illisibles,
            "volumetrie": volumetrie}


def couverture(directive: dict, memoires: dict[str, str], seuil: int = 2) -> list[str]:
    """Mémoires qui portent au moins `seuil` mots discriminants de la directive."""
    emp = directive["empreinte"]
    if len(emp) < seuil:
        return []
    couvrants = []
    for nom, contenu in memoires.items():
        if sum(1 for mot in emp if mot in contenu) >= seuil:
            couvrants.append(nom)
    return couvrants


def charger_memoires(dossier: Path, extras: list[Path]) -> dict[str, str]:
    """Corpus écrit : les mémoires, plus les fichiers de règles (CLAUDE.md, RULES_SHARED)."""
    corpus: dict[str, str] = {}
    if dossier.exists():
        # Mémoires du dossier ET de tous les sous-dossiers memory/ des projets frères
        # (le corpus écrit est réparti sur les 3 dossiers projet du renommage).
        for f in (set(dossier.glob("*.md")) | set(dossier.glob("*/memory/*.md"))
                  | set(dossier.glob("memory/*.md"))):
            try:
                corpus[f.name] = f.read_text(encoding="utf-8", errors="replace").lower()
            except OSError as exc:
                # Une memoire illisible RETRECIT le corpus de reference et fait donc
                # paraitre des directives orphelines a tort : le dire, jamais l'avaler.
                print(f"[directive_audit] memoire ILLISIBLE, couverture sous-estimee : "
                      f"{f.name} ({type(exc).__name__})", file=sys.stderr)
    # Les fichiers de regles vivent soit a la racine du superrepo, soit dans le submodule
    # selon d'ou l'outil est lance : on ESSAIE plusieurs dispositions et on ne crie que si
    # AUCUNE ne repond. Crier sur chaque candidat absent apprend a ignorer les alertes.
    lus = 0
    for f in extras:
        try:
            corpus[f.name] = f.read_text(encoding="utf-8", errors="replace").lower()
            lus += 1
        except OSError:  # muet-ok : candidat de disposition, l'absence globale est signalee
            continue
    if extras and not lus:
        print(f"[directive_audit] AUCUN fichier de regles lu parmi {[str(x) for x in extras]} — "
              f"la couverture est SOUS-estimee", file=sys.stderr)
    return corpus


def _forme_de_rapport(texte: str) -> bool:
    """Ce texte a-t-il la forme d'une sortie d'AGENT plutot que d'une parole ?

    Filtre assume, et son motif est mesure : meme apres avoir ecarte les resumes
    de compaction, des passages de rapport peuvent arriver sous l'etiquette
    « user » -- l'owner recolle parfois une reponse pour la commenter. Ils se
    reconnaissent a leur mise en forme : un pictogramme de tete, une puce, une
    numerotation, un tableau. Personne ne PARLE en tableau markdown.

    C'est une heuristique, donc elle se trompe parfois -- une directive courte
    qui commencerait par un tiret serait ecartee a tort. Le cout des deux erreurs
    n'est pas symetrique : laisser passer la prose de l'agent corrompt « ce que
    Nokido a compris de toi » a la racine, tandis qu'ecarter une directive la
    laisse dans l'audit complet, qui continue de tout compter. Et ce qui est
    ecarte est COMPTE, pas tu.
    """
    t = (texte or "").strip()
    if not t:
        return True
    if t[0] in "-*|#>" or t[:2] in ("1.", "2.", "3.", "4.", "5."):
        return True
    if t[0] in "⚠✅❌🪤📌🔒🎯🔎💡🧭" or t.startswith("**"):
        return True
    return False


def _sans_redites(brutes: list) -> list:
    """Ecarte les REDITES d'un meme message, pour l'affichage.

    Mesure du 2026-09-18 sur le premier export : deux entrees du 15/09 sont le
    MEME message reedite -- « ... les 4 missions ? » et « ... les 4- artefact dez
    missions ? ». L'owner s'est corrige en tapant ; l'extracteur a compte deux
    directives. Affichees cote a cote, elles donnent l'impression d'un systeme
    qui radote.

    PREMIERE TENTATIVE, ECARTEE PAR LA MESURE : comparer les quarante premiers
    caracteres. Elle ne captait RIEN sur le cas reel (trois entrees, trois
    sorties), parce que la correction est INSEREE AU MILIEU -- « les 4 missions »
    devient « les 4- artefact dez missions » et les tetes divergent des le
    vingtieme caractere. Supposer qu'une redite commence pareil etait faux.

    On mesure donc la similarite du texte ENTIER (`difflib`) et on garde la PLUS
    LONGUE : une correction de frappe allonge presque toujours la phrase, et la
    version la plus complete est la plus fidele. Le cout est quadratique, mais
    sur une centaine de directives cela reste quelques milliers de comparaisons.

    LE SEUIL N'EST PAS CHOISI AU JUGE. Distribution mesuree sur le corpus reel,
    mille sept cent soixante-dix paires :

        >= 0,93        5 paires   redites evidentes (2 doublons exacts)
        0,60 - 0,93    0 paire    <- un TROU
        <= 0,586    1765 paires   directives distinctes

    Le seuil vit dans ce trou : n'importe quelle valeur entre 0,60 et 0,93 donne
    le meme resultat ici. Armer un seuil sans regarder la distribution du signal
    est precisement ce qui a tue le hub huit fois par jour le 2026-09-05.

    CE QUE LA MESURE NE COUVRE PAS, et qui est dit : une directive suivie de sa
    version ETENDUE (« coupe docker... » puis « coupe docker..., sans qu'on le
    redemande ») tombe a 0,765 sur un essai fabrique -- sous le seuil, donc
    comptee deux fois. Aucune paire de cette forme n'existe dans le corpus reel,
    il n'y a donc rien a corriger aujourd'hui ; si le cas apparait, c'est la
    distribution qu'il faudra re-mesurer, pas le seuil qu'il faudra deviner.

    Ce filtre ne touche PAS la mesure de l'audit : `n_directives` continue de
    compter ce qui a ete dit. On ne nettoie que ce qu'on montre, et l'ecart
    entre les deux reste lisible dans le fichier.
    """
    import difflib as _dl
    import unicodedata as _ud

    def _norme(t: str) -> str:
        n = _ud.normalize("NFD", (t or "").lower())
        return " ".join("".join(c for c in n if c.isalnum() or c == " ").split())

    gardees: list = []
    for d in brutes:
        if _forme_de_rapport(d.get("texte", "")):
            continue
        txt = _norme(d.get("texte", ""))
        if not txt:
            continue
        jumeau = None
        for i, g in enumerate(gardees):
            if _dl.SequenceMatcher(None, txt, _norme(g.get("texte", ""))).ratio() >= 0.85:
                jumeau = i
                break
        if jumeau is None:
            gardees.append(d)
        elif len(d.get("texte", "")) > len(gardees[jumeau].get("texte", "")):
            gardees[jumeau] = d
    return [
        {"texte": d["texte"][:400], "date": d.get("date"),
         "recidive": bool(d.get("recidive")),
         "consignee": bool(d.get("couverte_par"))}
        for d in gardees
    ]


def main() -> int:
    racine = Path(__file__).resolve().parent.parent
    # RACINE des projets = tous les dossiers projet (renommage LaForge->Nokido) scannés
    # ensemble. Depuis mars, les conversations sont réparties sur plusieurs dossiers.
    defaut = Path.home() / ".claude" / "projects"
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--transcripts", default=str(defaut))
    ap.add_argument("--memoires", default=str(defaut))
    ap.add_argument("--seuil", type=int, default=2,
                    help="mots discriminants communs exigés pour dire qu'une mémoire couvre")
    ap.add_argument("--limite", type=int, default=25)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--hook", action="store_true",
                    help="mode SessionStart : terse, RECIDIVE-only, silencieux si rien")
    args = ap.parse_args()

    res = directives(Path(args.transcripts))
    if res["etat"] != "ok":
        # En mode hook, un dossier illisible ne doit PAS polluer chaque démarrage :
        # une ligne, jamais le JSON complet. Mais le dire (illisible != rien).
        if args.hook:
            print(f"[directive-audit] transcripts illisibles ({res.get('raison', '')[:60]}) "
                  f"— audit des consignes non écrites SAUTÉ")
            return 0
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 2

    memoires = charger_memoires(
        Path(args.memoires),
        [racine / "CLAUDE.md", racine.parent / "CLAUDE.md",
         racine / "RULES_SHARED.md", racine / "LaForge" / "RULES_SHARED.md",
         # Deportee de RULES_SHARED le 2026-09-19 (budget du noyau resident, -50,6 %).
         # Sans cette ligne, toutes les directives de cette section sortiraient de
         # l'audit comme ABSENTES du corpus ecrit : un deport non declare a son
         # lecteur vaut une perte, et l'audit crierait a faux sur 41 602 caracteres.
         racine / "docs" / "RULES_CAPACITES_EXECUTION.md"],
    )
    if not memoires:
        print(json.dumps({"etat": "ILLISIBLE", "raison": "aucune mémoire lisible — "
                          "sans corpus écrit, TOUTE directive paraîtrait non couverte"},
                         ensure_ascii=False, indent=2))
        return 3

    orphelines = []
    for d in res["directives"]:
        cov = couverture(d, memoires, seuil=args.seuil)
        if not cov:
            orphelines.append(d)
        d["couverte_par"] = cov
    orphelines.sort(key=lambda d: (not d["recidive"], d["date"] or ""), reverse=False)
    orphelines.sort(key=lambda d: (d["recidive"], d["date"] or ""), reverse=True)

    if args.hook:
        # PERSISTER CE QUI VIENT D'ÊTRE CALCULÉ (2026-09-18).
        #
        # La vue « Mémoire du persona » du portail promet « ce que Nokido a compris
        # de toi » et affichait des SOLUTION: extraites de lessons_learned —
        # c'est-à-dire des leçons de développement. Ce que Nokido a réellement
        # compris de l'owner, ce sont ces directives-ci.
        #
        # Le hub ne peut PAS les calculer lui-même : son compte ne lit pas
        # ~/.claude/projects (PermissionError WinError 5, mesuré). Ce hook, lui,
        # tourne du côté où les transcripts sont lisibles, et il vient de faire
        # tout le travail. Il le dépose donc dans le dépôt, où le portail sait lire.
        #
        # L'écriture ne doit JAMAIS casser un démarrage de session : elle échoue
        # en silence, mais le fichier porte sa date pour qu'un lecteur puisse voir
        # qu'il a vieilli plutôt que de le croire frais.
        try:
            import time as _t

            _art = racine / "sandbox" / "persona_directives.json"
            _art.parent.mkdir(parents=True, exist_ok=True)
            _art.write_text(json.dumps({
                "genere_ts": int(_t.time()),
                "n_transcripts": res["n_transcripts"],
                "n_directives": res["n_directives"],
                "n_illisibles": len(res["illisibles"]),
                # Ce qui est ECARTE est dit : sans ce chiffre, une liste propre
                # se lit comme une liste complete.
                "n_ecartes_forme": sum(1 for d in res["directives"]
                                       if _forme_de_rapport(d.get("texte", ""))),
                "directives": _sans_redites(res["directives"])[:60],
                # VOLUMÉTRIE PAR SESSION — le dénominateur qui manquait pour juger
                # le comptage d'aveux d'erreur. Déposé ici parce que ce module est
                # le seul à tourner du côté où les transcripts sont lisibles :
                # `forge_recurrence_audit` rend `ILLISIBLE` depuis le compte du hub,
                # et c'est un refus correct, pas une panne à contourner en forçant
                # des droits.
                "volumetrie": res.get("volumetrie", []),
            }, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:  # muet-ok : un export raté ne doit pas empêcher de démarrer
            pass

        # SessionStart : ne montrer que les RÉCIDIVES sans trace (le signal fort), cap 5.
        # Silencieux s'il n'y en a pas — un garde qui parle pour rien se fait ignorer.
        recid = [d for d in orphelines if d["recidive"]][:5]
        if recid:
            print(f"[directive-audit] {len(recid)} consigne(s) owner RÉPÉTÉE(S) et jamais "
                  f"consignée(s) — écris-les AVANT de dériver :")
            for d in recid:
                print(f"  ⟳ {d['date'] or '?'}  {d['texte'][:120]}")
        return 0

    if args.json:
        print(json.dumps({"etat": "ok", "n_transcripts": res["n_transcripts"],
                          "n_directives": res["n_directives"],
                          "n_orphelines": len(orphelines),
                          "orphelines": orphelines[:args.limite],
                          "illisibles": res["illisibles"]}, ensure_ascii=False, indent=2))
        return 0

    print(f"transcripts lus : {res['n_transcripts']} | directives durables : {res['n_directives']} "
          f"| SANS trace écrite : {len(orphelines)} | corpus écrit : {len(memoires)} fichiers")
    if res["illisibles"]:
        print(f"  ATTENTION — {len(res['illisibles'])} transcript(s) ILLISIBLES, "
              f"la couverture est donc SURESTIMÉE : {res['illisibles'][:3]}")
    print()
    for d in orphelines[:args.limite]:
        marque = "RECIDIVE " if d["recidive"] else "         "
        print(f"  {marque}{d['date'] or '?'}  [{d['session']}]  {d['texte'][:150]}")
        print(f"            empreinte: {', '.join(d['empreinte'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
