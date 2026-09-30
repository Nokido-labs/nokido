#!/usr/bin/env python
"""forge_symptom_index.py — « SUIS-JE DEJA PASSE PAR LA ? ». Lecture seule.

LE DEFAUT QU'IL CORRIGE (mesure 2026-07-30, sur 65 transcripts)
    Les 485 memoires stockent des CONCLUSIONS (« la cause etait X, le fix est Y »).
    Aucune ne stocke un SYMPTOME EXPLORE. Consequence mesuree : le 26-07 (session
    d314fd41) une enquete sur des heartbeats `never_read` s'est conclue par
    « j'avais tort : le superviseur lit bien ses heartbeats, mon never_read partout
    venait de quatre echantillons dont aucun ne POUVAIT etre lu ». Le 29-07, meme
    symptome : enquete refaite de zero, trois hypotheses fausses, quatre
    redemarrages, une journee. Rien ne s'etait allume, parce qu'un index de
    reponses ne repond pas a une question posee par SYMPTOME.

    Un systeme qui indexe ses reponses mais pas ses questions REFAIT ses enquetes.

ANTI-DUP (3 etapes faites, le hook recon_first ayant bloque la premiere tentative)
    `rag_fts` sur index/symptome/enquete/transcript : rien qui couvre ce besoin.
    Le module le PLUS PROCHE est `forge_self_correction` (`anchor_solution` /
    `read_lessons`) : il stocke des conclusions, clefees par enonce de probleme,
    dans le RAG. C'est exactement le defaut ci-dessus — pas un doublon a reutiliser
    mais le manque a combler. Ici la clef est un JETON de symptome et la source
    est le transcript, pas une note redigee apres coup.

CE QU'IL FAIT
    `--build`  : parcourt les transcripts et construit, par session, (a) les JETONS
                 techniques qui l'identifient et (b) les PIEGES, c'est-a-dire mes
                 propres aveux d'erreur avec leur contexte. Les jetons sont
                 extraits MECANIQUEMENT (snake_case, NokidoXxx, :port, forge_*.py,
                 WinError, XxxError) : aucun vocabulaire choisi par l'agent, donc
                 aucun biais de lexique — le defaut paye par les deux versions
                 precedentes de `forge_recurrence_audit`.
    `--ask X`  : rend les sessions qui ont touche X, du plus recent au plus ancien,
                 AVEC les pieges de chacune. Reponse a « qu'est-ce qui m'avait
                 pris la derniere fois ? ».

    Deux comptes, deux visibilites : `--build` exige le profil owner (le bac a
    sable ne voit pas `~/.claude`). L'index atterrit dans `sandbox/`, que le bac a
    sable LIT — donc `--ask` est utilisable comme reflexe depuis n'importe ou.
    Donnee derivee, jamais versionnee : elle contient des extraits de transcript.

TEST DE VALIDITE
    `--ask never_read` doit rendre la session d314fd41 du 26-07 ET la phrase ou
    l'agent s'y est trompe. S'il ne le fait pas, l'index ne sert a rien.

USAGE
    LAFORGE_PYTHON tools/forge_symptom_index.py --build      # owner, ~1 min
    LAFORGE_PYTHON tools/forge_symptom_index.py --ask never_read
    LAFORGE_PYTHON tools/forge_symptom_index.py --ask heartbeat --json
"""

from __future__ import annotations

__FORGE_COLOR__ = "cognition/memoire-d-enquete"

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "sandbox" / "enquetes_index.json"
# RACINE des projets, pas UN projet. Defaut corrige le 2026-07-30 : l'outil ne
# lisait que `C--Users-user-Script-python-IA` et concluait « mars a mai absent
# du disque ». Faux : `C--Users-user-Script-python-IA-LaForge` (ancien cwd)
# contient des sessions d'AVRIL. Conclure a l'absence depuis un seul repertoire
# scanne est le motif `invisible_lu_comme_absent` — celui-la meme que cet outil
# est cense aider a ne plus commettre.
SESSIONS_DEFAUT = Path.home() / ".claude" / "projects"

# Aveux d'erreur : la seule trace d'un piege qui ne depende ni de l'humeur de
# l'owner ni d'un lexique que l'agent s'est choisi — c'est l'agent qui se dedit.
PIEGE_RE = re.compile(
    r"(je me suis tromp\w+|j'avais tort|mon erreur|ma faute|erreur de ma part"
    r"|hypoth[eè]se (?:\w+ )?fausse|j'ai eu tort|je retire|c'[eé]tait faux"
    r"|je me corrige|artefact)",
    re.I,
)

# Jetons techniques AUTO-EXTRAITS. Rien de choisi a la main : ce sont les formes
# qui identifient un symptome dans ce depot.
JETON_RES = (
    re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+){1,4}\b"),      # snake_case
    re.compile(r"\bNokido[A-Z][A-Za-z]+\b"),                    # NokidoQdrantSync
    re.compile(r"(?<!\d):(\d{4,5})\b"),                         # :8766
    re.compile(r"\bforge_[a-z0-9_]+\.(?:py|ts)\b"),
    re.compile(r"\bWinError\s+\d+\b"),
    re.compile(r"\b[A-Z][a-zA-Z]{3,}(?:Error|Exception)\b"),
)
# Jetons trop generiques pour designer un symptome. DEUX familles, pas une.
BRUIT = frozenset({
    # (1) vocabulaire du FORMAT de transcription -- present depuis l'origine.
    "tool_use", "tool_result", "system_reminder", "text_delta", "input_json",
    "content_block", "message_start", "message_delta", "stop_reason", "cache_read",
    "output_tokens", "input_tokens", "session_id", "parent_uuid", "is_meta",
    "tool_name", "tool_input", "user_message", "assistant_message",
    # (2) VOCABULAIRE DE L'INSTRUMENT LUI-MEME (2026-09-20). « Un instrument ne
    # lit jamais son propre vocabulaire » -- regle deja appliquee ailleurs dans
    # ce depot, qui manquait ICI. Mesure sur enquetes_index.json (188 sessions,
    # 4 499 jetons distincts) : les QUATRE jetons les PLUS FREQUENTS de l'index
    # etaient l'index et son garde, 826 occurrences cumulees --
    #     226 forge_symptom_index · 203 forge_symptom_index.py
    #     200 hook_recon_first    · 197 recon_first
    # Consequence mesuree le jour meme : ces outils etant tres edites, toute
    # session qui travaille SUR le garde devenait un faux voisin de toute autre.
    # `hook_recon_first` a refuse QUATRE appels en citant des pieges sans
    # rapport -- deux fois le meme, sur le meme appel -- et n'a rien dit au
    # moment ou une duplication reelle allait etre creee. Un garde qui crie a
    # faux se fait desarmer : c'est son DIAGNOSTIC qu'on corrige ici, pas lui.
    "forge_symptom_index", "forge_symptom_index.py",
    "hook_recon_first", "recon_first",
})
MIN_OCCURRENCES = 2       # un jeton vu une seule fois n'identifie pas la session
MAX_JETONS = 400          # borne l'index, pas la mesure
CONTEXTE = 200            # caracteres d'aveu affiches
# Fenetre ELARGIE, uniquement pour rattacher un piege a ses propres jetons. Sans
# elle, `--ask never_read` rendait des pieges de la bonne session mais du mauvais
# sujet (mesure 2026-07-30 : 2 des 3 affiches parlaient d'un `git -am` et du
# postal). Un rappel imprecis est un rappel qu'on apprend a survoler.
FENETRE_JETONS = (300, 500)
MAX_JETONS_PIEGE = 60


def _jetons(txt: str, minimum: int = 4) -> list[str]:
    """Jetons techniques d'un texte. Extraction MECANIQUE, aucun mot choisi."""
    vus: list[str] = []
    for rx in JETON_RES:
        for brut in rx.findall(txt):
            j = (brut if isinstance(brut, str) else brut[0]).lower()
            if j in BRUIT or len(j) < minimum or j in vus:
                continue
            vus.append(j)
    return vus


def _texte_assistant(ev: dict) -> str:
    if ev.get("type") != "assistant":
        return ""
    contenu = (ev.get("message") or {}).get("content")
    if isinstance(contenu, list):
        return " ".join(
            str(b.get("text", "")) for b in contenu
            if isinstance(b, dict) and b.get("type") in (None, "text")
        )
    return str(contenu or "")


def construire(dossier: Path) -> dict:
    if not dossier.exists():
        return {"etat": "ILLISIBLE", "raison": f"dossier absent/interdit: {dossier}"}
    # Accepte la racine des projets OU un projet unique. `*/*.jsonl` couvre tous
    # les projets sans ramasser les `*/subagents/*.jsonl` (deux niveaux plus bas),
    # qui ne sont pas des conversations owner.
    fichiers = sorted(set(dossier.glob("*.jsonl")) | set(dossier.glob("*/*.jsonl")))
    if not fichiers:
        return {"etat": "ILLISIBLE", "raison": f"aucun .jsonl sous {dossier}"}

    sessions: list[dict] = []
    illisibles: list[dict] = []
    ignorees: list[dict] = []
    for f in fichiers:
        compte: dict[str, int] = {}
        pieges: list[dict] = []
        date = None
        try:
            with f.open(encoding="utf-8", errors="replace") as fh:
                for n, ligne in enumerate(fh, 1):
                    if date is None:
                        m = re.search(r'"timestamp":"(\d{4}-\d{2}-\d{2})', ligne)
                        if m:
                            date = m.group(1)
                    if '"assistant"' not in ligne:
                        continue
                    try:
                        ev = json.loads(ligne)
                    except Exception as e:
                        print(f"[index] {f.stem[:8]}:{n} ligne non parsable:"
                              f" {type(e).__name__}", file=sys.stderr)
                        continue
                    txt = _texte_assistant(ev)
                    if not txt:
                        continue
                    for j in _jetons(txt):
                        compte[j] = compte.get(j, 0) + 1
                    for m in PIEGE_RE.finditer(txt):
                        deb = max(0, m.start() - 40)
                        avant, apres = FENETRE_JETONS
                        voisinage = txt[max(0, m.start() - avant):m.start() + apres]
                        pieges.append({
                            "ligne": n,
                            "extrait": " ".join(txt[deb:m.start() + CONTEXTE].split()),
                            "jetons": _jetons(voisinage, minimum=6)[:MAX_JETONS_PIEGE],
                        })
        except OSError as e:
            illisibles.append({"session": f.stem[:8], "raison": str(e)[:70]})
            continue
        jetons = sorted(
            (j for j, c in compte.items() if c >= MIN_OCCURRENCES),
            key=lambda j: -compte[j],
        )[:MAX_JETONS]
        vus: set[str] = set()
        uniques: list[dict] = []
        for p in pieges:  # le meme paragraphe reapparait dans les reprises
            cle = p["extrait"][:70]
            if cle not in vus:
                vus.add(cle)
                uniques.append(p)
        # Repli de DATE : sans horodatage exploitable, le mtime reste une date.
        # Trois sessions ressortaient a `None` et se rangeaient en queue de tri,
        # donc invisibles au rappel « suis-je deja passe par la ».
        if not date:
            try:
                date = time.strftime("%Y-%m-%d", time.localtime(f.stat().st_mtime))
            except OSError as e:
                print(f"[index] {f.stem[:8]} sans date ni mtime: "
                      f"{type(e).__name__}", file=sys.stderr)
        # Retenue si JETONS *ou* PIEGES : les aveux sont la charge utile de cet
        # index ; les jeter avec une session courte supprimait exactement ce qu'on
        # vient y chercher. Et jamais en silence : une session ecartee sans trace
        # est une couverture surestimee (la session du 27-04 disparaissait ici).
        if not jetons and not uniques:
            ignorees.append({"session": f.stem[:8], "projet": f.parent.name,
                             "date": date, "raison": "ni jeton recurrent ni aveu"})
            continue
        sessions.append({
            "session": f.stem[:8], "fichier": f.name, "projet": f.parent.name,
            "date": date, "jetons": jetons, "pieges": uniques[:40],
            "n_pieges": len(uniques),
        })
    # Les transcripts locaux ne couvrent pas tout : la periode anterieure vit en RAG.
    depuis_rag = construire_rag(ROOT / "RAG" / "embeddings.db")
    sessions.extend(depuis_rag)
    sessions.sort(key=lambda s: s["date"] or "0000-00-00", reverse=True)
    return {"etat": "ok", "n_sessions": len(sessions), "sessions": sessions,
            "illisibles": illisibles, "ignorees": ignorees,
            "n_fichiers_vus": len(fichiers), "n_depuis_rag": len(depuis_rag)}


def construire_rag(db: Path, max_sessions: int = 400) -> list[dict]:
    """Sessions issues du RAG : Claude Desktop, Gemini CLI, Gemini Web.

    POURQUOI. L'export Desktop (`conversations.json`) etait un telechargement
    manuel depuis claude.ai, ingere une fois puis supprime : `CLAUDE_DESKTOP_DEFAULT`
    pointe vers un dossier absent. Mais les CHUNKS sont restes en base
    (`conv_claude_desktop/*`), donc la periode mars-mai est deja la — conclure a son
    absence parce que le fichier source a disparu serait exactement la faute que cet
    outil traque. On indexe donc la source qui EXISTE.

    Les dates sont VOLONTAIREMENT nulles : `created_at` des chunks `conv_*` est la
    date d'INGESTION, pas celle des echanges (artefact paye le 29-07). Mieux vaut pas
    de date qu'une fausse ; ces sessions restent interrogeables par symptome.
    Filtre sur `source` = prefixe, pas une recherche de contenu : `rag_fts` ne sert
    pas a balayer un corpus entier par famille.
    """
    import sqlite3

    if not db.exists():
        return []
    par_session: dict[str, list[str]] = {}
    try:
        conn = sqlite3.connect(f"file:{str(db).replace(chr(92), '/')}?mode=ro", uri=True)
        for source, texte in conn.execute(
            # Union de deux GLOB : '_' etant un joker en LIKE, `LIKE 'conv_%'` couvrait
            # aussi les 9 sources `conv://...` (mesure 2026-09-04). Les perdre aurait
            # retire des conversations de l'index d'enquetes -- c'est-a-dire de la
            # memoire qui evite de refaire deux fois la meme investigation.
            "SELECT source, text FROM rag_chunks "
            "WHERE (source GLOB 'conv_*' OR source GLOB 'conv:*') "
            "AND text IS NOT NULL ORDER BY source"
        ):
            morceaux = str(source).split("/")
            if len(morceaux) < 2:
                continue
            cle = f"{morceaux[0]}/{morceaux[1]}"
            lot = par_session.setdefault(cle, [])
            if len(lot) < 400:  # borne par session, pas de dump illimite
                lot.append(str(texte))
        conn.close()
    except Exception as e:  # noqa: BLE001
        print(f"[index] RAG ignore: {type(e).__name__}: {str(e)[:90]}", file=sys.stderr)
        return []

    sorties: list[dict] = []
    for cle, morceaux in list(par_session.items())[:max_sessions]:
        txt = "\n".join(morceaux)
        compte: dict[str, int] = {}
        for j in _jetons(txt):
            compte[j] = compte.get(j, 0) + 1
        jetons = sorted((j for j, c in compte.items() if c >= MIN_OCCURRENCES),
                        key=lambda j: -compte[j])[:MAX_JETONS]
        pieges, vus = [], set()
        for m in PIEGE_RE.finditer(txt):
            deb = max(0, m.start() - 40)
            avant, apres = FENETRE_JETONS
            extrait = " ".join(txt[deb:m.start() + CONTEXTE].split())
            if extrait[:70] in vus:
                continue
            vus.add(extrait[:70])
            pieges.append({
                "ligne": 0, "extrait": extrait,
                "jetons": _jetons(txt[max(0, m.start() - avant):m.start() + apres],
                                  minimum=6)[:MAX_JETONS_PIEGE],
            })
        if not jetons and not pieges:
            continue
        famille, sid = cle.split("/", 1)
        sorties.append({
            "session": sid[:8], "fichier": cle, "projet": famille,
            "date": None, "origine": "rag", "jetons": jetons,
            "pieges": pieges[:40], "n_pieges": len(pieges),
        })
    return sorties


# Memoire d'enquete PARTAGEE : generisee, versionnee, fusionnable (JSONL).
# Produite par `tools/forge_enquetes_publier.py`, publiee dans le dist — alors
# que l'index local, lui, ne l'est pas.
PARTAGE = ROOT / "docs" / "enquetes_partagees.jsonl"


def charger_index() -> dict:
    """Index LOCAL union memoire PARTAGEE — la SOURCE UNIQUE des trois lecteurs.

    Pourquoi une fonction et pas trois lectures. Mesure du 2026-09-19 : ce
    fichier, `hook_recon_first` et `claude_session_start` lisaient chacun
    `sandbox/enquetes_index.json` par un chemin en dur. Brancher la memoire
    partagee sur un seul aurait reproduit le motif deja paye dans ce depot —
    deux chemins pour une meme capacite, un seul qui lit la politique.

    Ce que l'union apporte, et pour qui :
      - chez l'owner : le local (complet) PLUS le partage, sans doublon ;
      - chez un CONTRIBUTEUR du dist : le local est absent, et le partage est
        alors la SEULE memoire. Sans lui, `--ask` repond « terrain neuf » a
        tout, ce qui est un faux negatif et non une absence.

    DEDUPLICATION par identifiant d'enquete : l'owner publie depuis son propre
    local, donc les deux sources se recouvrent largement. Le LOCAL gagne — il
    est plus riche (non generise).

    Fail-safe : une source illisible n'empeche jamais l'autre, et le nombre de
    sources effectivement lues est rendu dans `sources`. Un appelant qui veut
    distinguer « rien trouve » de « je n'ai pas pu lire » a de quoi le faire.
    """
    idx: dict = {"sessions": [], "sources": [], "illisibles": []}
    vus: set = set()

    if INDEX.is_file():
        try:
            local = json.loads(INDEX.read_text(encoding="utf-8"))
            for s in local.get("sessions") or []:
                cle = str(s.get("session") or "")[:12]
                if cle and cle not in vus:
                    vus.add(cle)
                    idx["sessions"].append(s)
            idx["sources"].append(f"local:{len(idx['sessions'])}")
        except Exception as e:  # noqa: BLE001
            idx["illisibles"].append(f"local ({type(e).__name__})")

    if PARTAGE.is_file():
        n = 0
        try:
            for ligne in PARTAGE.read_text(encoding="utf-8").splitlines():
                if not ligne.strip():
                    continue
                r = json.loads(ligne)
                cle = str(r.get("enquete") or "")[:12]
                if not cle or cle in vus:
                    continue
                vus.add(cle)
                pieges = r.get("pieges") or []
                idx["sessions"].append({
                    "session": cle, "date": r.get("date", ""),
                    "jetons": r.get("jetons") or [],
                    "pieges": pieges, "n_pieges": len(pieges),
                    "origine": r.get("origine", "partage"),
                })
                n += 1
            idx["sources"].append(f"partage:{n}")
        except Exception as e:  # noqa: BLE001
            idx["illisibles"].append(f"partage ({type(e).__name__})")

    idx["n_sessions"] = len(idx["sessions"])
    return idx


def demander(terme: str, index: dict, limite: int = 5) -> list[dict]:
    """Sessions ayant touche ce symptome, du plus RECENT au plus ancien."""
    t = terme.lower().strip()
    sortie: list[dict] = []
    for s in index.get("sessions", []):
        exact = t in s["jetons"]
        partiel = [j for j in s["jetons"] if t in j] if not exact else []
        if exact or partiel:
            # Ne garder que les pieges dont le PARAGRAPHE parle du symptome.
            cibles = [
                p for p in s["pieges"]
                if any(t == j or t in j for j in p.get("jetons", []))
            ]
            sur_sujet = bool(cibles)
            sortie.append({
                "session": s["session"], "date": s["date"],
                "correspondance": "exacte" if exact else f"partielle: {partiel[:3]}",
                "n_pieges": s["n_pieges"],
                "pieges": (cibles or s["pieges"])[:3],
                "pieges_sur_le_sujet": sur_sujet,
            })
        if len(sortie) >= limite:
            break
    return sortie


def main() -> int:
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"[index] reconfigure ignore: {type(e).__name__}", file=sys.stderr)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", action="store_true", help="reconstruit l'index (owner)")
    ap.add_argument("--ask", metavar="SYMPTOME")
    ap.add_argument("--sessions", default=str(SESSIONS_DEFAUT))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.build:
        idx = construire(Path(args.sessions))
        if idx.get("etat") != "ok":
            print(f"[index] ILLISIBLE : {idx.get('raison')}")
            print("  (ce n'est PAS « rien trouve » : --build exige le profil owner)")
            return 1
        INDEX.parent.mkdir(parents=True, exist_ok=True)
        INDEX.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
        n_p = sum(s["n_pieges"] for s in idx["sessions"])
        print(f"[index] {idx['n_sessions']} sessions retenues "
              f"({idx['n_fichiers_vus']} transcripts vus + {idx['n_depuis_rag']} "
              f"depuis le RAG), {n_p} pieges -> {INDEX.relative_to(ROOT)}")
        if idx["ignorees"]:
            print(f"  ECARTEES ({len(idx['ignorees'])}) — la couverture n'est pas "
                  f"celle des fichiers vus :")
            for g in idx["ignorees"][:10]:
                print(f"    {g['date']} {g['session']} ({g['projet']}) : {g['raison']}")
        if idx["illisibles"]:
            print(f"  ILLISIBLES : {idx['illisibles']}")
        return 0

    if not args.ask:
        ap.print_help()
        return 0

    idx = charger_index()
    if not idx["sessions"]:
        # DISTINGUER les deux causes : « rien a lire » n'est pas « lecture
        # refusee ». Sans ca, un contributeur du dist croirait que la memoire
        # est vide alors qu'elle n'a peut-etre pas pu s'ouvrir.
        if idx["illisibles"]:
            print(f"[index] ILLISIBLE : {', '.join(idx['illisibles'])} — ce n'est "
                  f"PAS une absence d'enquete, c'est une lecture qui a echoue.")
        else:
            print("[index] aucune memoire d'enquete : ni index local "
                  "(`--build`, cote owner) ni `docs/enquetes_partagees.jsonl`.")
        return 1
    res = demander(args.ask, idx)
    if args.json:
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return 0
    if not res:
        print(f"[index] « {args.ask} » : aucune session anterieure. "
              f"Terrain neuf — mais l'index ne couvre que {idx.get('n_sessions')} "
              f"sessions, ce n'est pas une preuve d'absence.")
        return 0
    print(f"=== « {args.ask} » : DEJA EXPLORE dans {len(res)} session(s) ===")
    for r in res:
        marque = "" if r.get("pieges_sur_le_sujet") else "  [pieges HORS SUJET, " \
                                                         "montres a defaut]"
        quand = r["date"] or "date inconnue (RAG)"
        print(f"\n  {quand}  {r['session']}  ({r['correspondance']}, "
              f"{r['n_pieges']} piege(s) dans la session){marque}")
        for p in r["pieges"]:
            print(f"     — {p['extrait'][:180]}")
    print("\n  Lis ces pieges AVANT de rouvrir l'enquete : c'est exactement ce que")
    print("  l'absence de cet index a coute le 29-07 (symptome deja explore le 26).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
