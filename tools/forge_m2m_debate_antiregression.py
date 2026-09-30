#!/usr/bin/env python3
"""forge_m2m_debate_antiregression.py — DEBAT M2M (Claude <-> Antigravity <-> panel local)
dont l'objet est UNE SEULE chose : une methode de detection de regression qui NE RATE RIEN.

Reutilise (aucune reimplementation) :
  - tools/forge_debate_job.run_debate  : arene multi-tours, turn-taking, RAG + firewall
  - tools/forge_regression_sweep       : les axes deja en production (source des axes)
  - app/forge_postal                   : canal M2M vers ANTIGRAVITY (async, facteur)
  - app/forge_swarm_blackboard         : depot du fait consolide

MECANIQUE ANTI-"ON CROIT AVOIR TOUT VU" (le coeur du sujet) :
  un debat produit des OPINIONS. Ici la methode proposee est MESUREE sur un CORPUS DE
  REGRESSIONS DEJA CONNUES (memoires d'incidents + lecons + ancres RAG). Pour chaque cas
  historique, un scoreur dit QUEL axe l'aurait attrape -- ou MISSED. Le rappel (recall)
  est le verdict ; chaque MISSED devient un axe manquant, nomme, a ajouter. Une methode
  sans mesure de rappel n'est pas une methode, c'est une intention.

Usage (deporte) :
  run_job script=tools/forge_m2m_debate_antiregression.py online=true
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_semantic_firewall import redact_text


DB = ROOT / "RAG" / "embeddings.db"
from nokido_agent.app.forge_db_path import m2m_path  # noqa: E402
M2M = Path(m2m_path())   # scission M2M : agent_messages suit l'interrupteur ; DB reste pour rag_chunks
MEM = Path(r"%USERPROFILE%\.claude\projects\C--Users-user-Script-python-IA\memory")
# ── ROLES DIALECTIQUES (app/forge_debate_roles.py) ──────────────────────────
# La chaine de pensee imposee est un SCRATCHPAD : seule la balise `publie` entre
# au SSoT. Les etapes de reconstruction/extraction stabilisent le raisonnement
# sans que l'adversaire puisse repondre a un brouillon.
try:
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_debate_roles import DEBATE_ROLES, TourInvalide, anonymise, extract_cot

    _ROLES_OK = True
except Exception as _e_roles:  # noqa: BLE001
    _ROLES_OK = False
    print(f"[arene] roles dialectiques INDISPONIBLES ({type(_e_roles).__name__}: "
          f"{str(_e_roles)[:80]}) | consequence: pas de protocole de balises, "
          f"pas d'anonymisation -- le debat retombe en texte libre", flush=True)


def _tokens(nom_role: str, defaut: int = 520) -> int:
    """Budget de sortie DECLARE par le role.

    Defaut de `_turn` = 520 tokens : insuffisant pour trois balises (mesure
    2026-08-14, premier lancement du panel elargi — DEBATTEUR_POUR a produit
    1 392 caracteres et s'est fait couper AVANT `</refutation>`, donc rejete par
    le fail-closed). Un protocole de balises impose de financer la derniere.
    """
    if _ROLES_OK and nom_role in DEBATE_ROLES:
        return int(DEBATE_ROLES[nom_role].max_tokens or defaut)
    return defaut


def _rappel_format(nom_role: str) -> str:
    """Rappel COURT du protocole, a re-envoyer a CHAQUE tour.

    Mesure 2026-08-14 : le dossier (role + objectif) ne part qu'une fois pour
    economiser le contexte — mais le PROTOCOLE vivait dedans. Aux tours suivants
    l'agent recevait « meme role qu'au tour precedent » et rendait 371 caracteres
    SANS AUCUNE balise : il avait perdu le contrat de format. Le dossier peut ne
    partir qu'une fois ; le format, jamais. C'est le contrat minimal.
    """
    if not _ROLES_OK or nom_role not in DEBATE_ROLES:
        return ""
    tags = DEBATE_ROLES[nom_role].cot_tags
    if not tags:
        return ""
    ouv = " ".join(tags)
    fer = " ".join(t.replace("<", "</") for t in tags)
    return ("\n\n## FORMAT OBLIGATOIRE (rappel — un tour hors format est REJETE)\n"
            f"Balises attendues, dans cet ordre : {ouv}\n"
            f"Chacune doit etre FERMEE : {fer}\n"
            "Sois tres bref dans les balises intermediaires (2 phrases) ; ton DELTA "
            f"va dans {tags[-1]} en lignes AXE:/TENSION:/ACQUIS:.")


def _publie(nom_role: str, texte: str) -> tuple:
    """(delta_publie, ok, motif). FAIL-CLOSED : un tour hors protocole est REJETE.

    Jamais de repli sur « prendre tout le texte » : c'est ce repli qui a produit
    trois « recall 100 % » mensongers le 2026-08-13 (un `**MISSED**` en gras
    suffisait). Un role sans balise obligatoire passe tel quel.
    """
    if not _ROLES_OK or nom_role not in DEBATE_ROLES or not DEBATE_ROLES[nom_role].cot_tags:
        return texte, True, ""
    try:
        return extract_cot(texte, nom_role)["publie"], True, ""
    except TourInvalide as e:
        return "", False, str(e)[:160]


OUT_DOC = ROOT / "sandbox" / "DEBAT_M2M_ANTIREGRESSION_2026-08-13.md"
OUT_JSON = ROOT / "sandbox" / "debat_m2m_antiregression.json"


def _blind(d: dict, k: str, why: str) -> None:
    """Un rapport qui ne nomme pas ses angles morts se donne raison tout seul."""
    d.setdefault("angles_morts", []).append(f"{k}: {why}")


def axes_en_production(bl: dict) -> list:
    """Les axes REELS du sweep (pas ceux dont je me souviens)."""
    try:
        src = (ROOT / "tools" / "forge_regression_sweep.py").read_text(encoding="utf-8", errors="replace")
        return sorted(set(re.findall(r"^def (axe_[a-z_]+)\(", src, re.M)))
    except Exception as e:  # noqa: BLE001
        _blind(bl, "axes_sweep", f"lecture KO {e!r}")
        return []


def proposition_agy(bl: dict) -> str:
    """Le texte REEL d'Antigravity, pas ma paraphrase : il est partie au debat."""
    try:
        c = sqlite3.connect(f"file:{M2M}?mode=ro", uri=True)
        r = c.execute(
            "SELECT payload FROM agent_messages WHERE upper(from_agent) LIKE '%ANTIGRAV%' "
            "AND payload LIKE '%PROPOSITION DEBAT%' ORDER BY created_at DESC LIMIT 1").fetchone()
        c.close()
        if not r:
            _blind(bl, "agy_proposal", "aucune PROPOSITION DEBAT en base")
            return ""
        try:
            return str(json.loads(r[0]).get("text") or r[0])
        except Exception:  # noqa: BLE001
            return str(r[0])
    except Exception as e:  # noqa: BLE001
        _blind(bl, "agy_proposal", f"SQL KO {e!r}")
        return ""


def corpus_regressions_connues(bl: dict, limite: int = 40) -> list:
    """VERITE TERRAIN : un cas = une regression REELLEMENT survenue et documentee.
    3 sources independantes ; celles qui rendent zero sont NOMMEES (pas silencieuses)."""
    cas: list = []
    try:
        fics = sorted(MEM.glob("*.md"))
        n = 0
        for f in fics:
            if f.name == "MEMORY.md":
                continue
            nom = f.stem
            if not re.search(r"incident|gotcha|blocker|regress|garde|trou|veille_vide|"
                             r"sources_qui|couper|nudge|crash", nom):
                continue
            txt = f.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"^description:\s*(.+)$", txt, re.M)
            cas.append({"id": nom, "source": "memoire",
                        "desc": (m.group(1) if m else txt[:300]).strip()[:400]})
            n += 1
        if n == 0:
            _blind(bl, "corpus_memoire", f"0 cas retenu sur {len(fics)} fichiers ({MEM})")
    except Exception as e:  # noqa: BLE001
        _blind(bl, "corpus_memoire", f"acces KO {e!r} (compte du job ?)")

    # 2) COMMITS DE CORRECTION : un fix = une regression qui a REELLEMENT eu lieu, datee,
    #    ecrite par l'owner. safe.directory=* car le depot est a l'owner et le job tourne
    #    en compte sandbox (le refus 'dubious ownership' est un probleme de COMPTE).
    try:
        import subprocess

        g = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", str(ROOT), "log", "--since=2026-05-01",
             "-i", "--grep=fix", "--grep=incident", "--grep=regress", "--pretty=%h|%s"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        lignes = [l for l in g.stdout.splitlines() if "|" in l and len(l) > 25]
        if not lignes:
            _blind(bl, "corpus_git", f"0 commit (rc={g.returncode}) {g.stderr.strip()[:140]}")
        pas = max(1, len(lignes) // 25)   # echantillon ETALE : les 25 derniers = un prefixe biaise
        for l in lignes[::pas][:25]:
            h, s = l.split("|", 1)
            cas.append({"id": f"git_{h}", "source": "git_fix", "desc": s.strip()[:400]})
    except Exception as e:  # noqa: BLE001
        _blind(bl, "corpus_git", f"git KO {e!r}")

    # 3) chunks RAG d'incident. La colonne s'appelle 'text' : 'content' n'existe pas ici.
    try:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        rows = c.execute(
            "SELECT id, substr(text,1,400) FROM rag_chunks WHERE (text LIKE '%INCIDENT%' "
            "OR text LIKE '%REGRESSION%') AND active=1 ORDER BY ingested_at DESC LIMIT 400"
        ).fetchall()
        c.close()
        if not rows:
            _blind(bl, "corpus_rag", "0 chunk incident/regression (filtre actif=1)")
        pas = max(1, len(rows) // 15)
        for rid, t in rows[::pas][:15]:
            cas.append({"id": f"rag_{str(rid)[:12]}", "source": "rag",
                        "desc": " ".join(str(t).split())[:400]})
    except Exception as e:  # noqa: BLE001
        _blind(bl, "corpus_db", f"{DB} KO {e!r}")

    vus, out = set(), []
    for k in cas:
        sig = re.sub(r"\W+", "", k["desc"].lower())[:80]
        if sig in vus:
            continue
        vus.add(sig)
        out.append(k)
    if len(out) > limite:
        _blind(bl, "corpus_plafond", f"{len(out)} cas -> tronque a {limite} (plafond NOMME)")
        out = out[:limite]
    return out


def _participants(agy_txt: str, axes: list):
    """Panel ELARGI (2026-08-14) : roles dialectiques + providers MESURES joignables.

    Les providers sont ceux que `whoami` rend `providers_available` — mesure, pas
    supposition : `hub list_providers` (registre) et les noms acceptes par `ask`
    sont DEUX espaces de noms distincts, et `gemini_flash` (present au registre,
    inconnu de `ask`) avait rendu 9 tours sur 9 en reponse vide le 2026-08-13.
    `gemini_cli` EST AGY (agy.exe, abonnement owner) : ne pas le substituer.
    """
    axes_s = ", ".join(a.replace("axe_", "") for a in axes) or "(axes illisibles)"
    _dp = DEBATE_ROLES["DEBATTEUR_POUR"].system_prompt if _ROLES_OK else ""
    _dc = DEBATE_ROLES["DEBATTEUR_CONTRE"].system_prompt if _ROLES_OK else ""
    _ar = DEBATE_ROLES["ARBITRE_EPISTEMIQUE"].system_prompt if _ROLES_OK else ""
    _fmt = ("\nCONTRAINTE DE FORMAT, non negociable : les TROIS balises doivent "
            "etre presentes ET FERMEES (</ironman_reconstruction>, "
            "</flaw_extraction>, </refutation>). Sois TRES BREF dans les deux "
            "premieres (2 phrases max chacune) : leur seul role est de stabiliser "
            "ton raisonnement, elles ne sont PAS transmises. Un tour dont une "
            "balise manque est REJETE et ne compte pas."
            "\nDans <refutation>, ecris UNIQUEMENT ton DELTA en lignes prefixees "
            "AXE:/TENSION:/ACQUIS: (120 mots max).")
    # PROVIDERS VERIFIES VIVANTS le 2026-08-14 11:30 par un PONG direct. La cle
    # GROQ_API_KEY a ete ECARTEE par la rotation (http403, re-test dans ~6 h) : les
    # deux debatteurs etaient dessus -> 18 tours, 3 reussis, tout le reste en
    # « reponse vide ». Ne jamais mettre deux roles sur le MEME provider, et ne
    # jamais supposer qu'un provider qui repondait il y a une heure repond encore.
    parts = [
        ("DEBATTEUR_POUR", "cohere",
         _dp + "\n\n## TA THESE\nLe backtest git est la SEULE verite terrain datee "
         "et gratuite : un axe ne vaut que s'il a fait taire une alerte sur un "
         "commit de correction reel.\n\n## FAIT NEUF A DEFENDRE (mesure 2026-08-14)\n"
         "Un axe EXECUTABLE vient d'etre livre : `forge_fix_sentinel` detecte un "
         "correctif commite puis ANNULE par un revert qui emporte plus que son "
         "objet. Cas reel : 43dbf555 et fe9f323d (gardes anti-sawtooth Docker) "
         "emportes par 3aec1500 ; symptome revenu des SEMAINES plus tard. Ni les "
         "tests ni le lint ne le voient : le defaut n'est pas dans le code "
         "present, il est dans CE QUI A DISPARU. Mesure honnete : v1 = 5 alertes "
         "dont 3 faux positifs (60%), v3 = 0 perdu sur 713 ancres, 29 "
         "remplacements ecartes." + _fmt),
        # Provider DISTINCT de POUR : une cle ecartee ne doit pas emporter les deux
        # cotes du debat d'un coup (c'est ce qui vient d'arriver avec groq, puis
        # avec cerebras — les deux detectes morts par la supervision d'endpoints).
        ("DEBATTEUR_CONTRE", "mistral",
         _dc + "\n\n## TA THESE\nLe backtest git mesure la capacite a retrouver le "
         "DEJA-TROUVE : biais de survie. Les regressions jamais detectees — les "
         "seules qui comptent — sont structurellement absentes du corpus.\n\n"
         "## CE QUE TU DOIS ATTAQUER EN PRIORITE (fait neuf du 2026-08-14)\n"
         "Un axe `fix_reverte` vient d'etre livre (detecte un correctif annule par "
         "un revert). Son auteur admet : v1 = 60% de faux positifs, v2 = AVEUGLE "
         "au cas de reference, v3 = 0 alerte sur 713 ancres. Un capteur qui "
         "n'alerte JAMAIS sur l'etat courant a-t-il seulement ete valide ? Exige "
         "une preuve qu'il tire sur un cas REEL, pas sur un cas reconstruit." + _fmt),
        # ARBITRE hors du local — COMPROMIS ASSUME, mesure 2026-08-14.
        # Aucun backend local ne GENERE : `ollama` et `llamacpp` rendent « backend
        # non pret » (service NokidoOllama pourtant `already_running` HTTP 200 — le
        # modele n'est pas charge : politique RAM boot-trim, KEEP_ALIVE=30s,
        # MAX_LOADED_MODELS=1) ; `router_local` et `lmstudio` TIMEOUT a 120 s.
        # Insister a fait TOMBER LE HUB (trois reveils enchaines sur une machine a
        # 80 % de RAM) : gotcha connu d'interblocage RAM keeper/lmstudio.
        # Ce que le role NE perd PAS : son independance vient de ce qu'il n'a
        # AUCUNE these et doit SOURCER, pas de sa localisation. Ce qu'il perd
        # vraiment : l'acces direct aux preuves locales — d'ou le TESTEUR (local,
        # executable) qui reste la seule autorite FACTUELLE ; l'arbitre annote.
        # Provider distinct de tous les debatteurs : il ne juge pas sa propre voix.
        ("ARBITRE_EPISTEMIQUE", "openrouter_free",
         _ar + "\n\nDans <annotation>, signale les affirmations non sourcees du "
         "debat et ecris INDETERMINE quand tu ne peux pas verifier."),
        ("AGY-porte-parole", "gemini_cli",
         "Tu portes la position D'ANTIGRAVITY, mot pour mot ci-dessous. Tu la defends et tu la "
         "PRECISES en mecanique executable (quel AST, quel seuil, quel fichier), tu ne la dilues "
         f"pas.\n### POSITION ANTIGRAVITY (texte reel)\n{agy_txt or '(non recue)'}"),
        ("Archeologue", "mistral",
         "Tu es l'ARCHEOLOGUE DES RATES. Ta seule question : parmi les regressions DEJA SURVENUES "
         "du corpus fourni, lesquelles la methode discutee n'aurait PAS vues, et POURQUOI "
         "(capteur absent, signal present mais non lu, garde qui repond ok sans regarder). Tu "
         "raisonnes par contre-exemple historique, jamais par principe general."),
        ("Sentinelle", "deepseek",
         "Tu es ADVERSARIAL. Tu attaques la methode par ses FAUX-VERTS : sonde qui rend OK sans "
         "avoir regarde, LIMIT sans ORDER BY pris pour un echantillon, outil qui indexe le depot "
         "qu'il alimente et se donne raison, plafond silencieux, except nu qui avale le signal. "
         "Chaque attaque nomme le mecanisme exact, pas un risque vague."),
    ]
    return parts, axes_s


def _objectif(axes_s: str, corpus: list, n_cas: int = 6) -> str:
    ex = "\n".join(f"- [{c['source']}] {c['id']} :: {c['desc'][:180]}" for c in corpus[:n_cas])
    if len(corpus) > n_cas:
        ex += f"\n- (+{len(corpus) - n_cas} autres cas au corpus, non montres ici)"
    return (
        "Definir LA methode de detection de regression de Nokido qui NE RATE RIEN, et la rendre "
        "MESURABLE.\n"
        f"DEJA EN PRODUCTION (ne pas reinventer) : forge_regression_sweep, axes = {axes_s}. "
        "forge_intent_verifier fait du LEXICAL (grep d'enonces) : c'est lui la limite discutee.\n"
        "La methode retenue sera notee sur son RAPPEL contre des regressions DEJA SURVENUES. "
        "Echantillon du corpus de verite terrain :\n" + ex + "\n"
        "Livrable : la liste des AXES (existants gardes + nouveaux) ; pour chacun le SIGNAL "
        "observe, la SOURCE, les VERDICTS possibles, et le test qui prouve que l'axe voit "
        "vraiment (anti faux-vert)."
    )


CONTRAINTE = (
    "Local-first, zero nouveau service. Tout axe s'appuie sur une source deja presente (AST du "
    "depot, sqlite embeddings.db, hooks, superviseur, git, network_log). Un axe incapable de "
    "rendre INDETERMINE est refuse : le silence doit se distinguer du sain."
)

async def _scorer_rappel(methode: str, corpus: list) -> dict:
    """Chaque cas historique -> quel axe l'aurait attrape, ou MISSED. C'est LA mesure :
    sans elle, 'ne rate rien' reste une affirmation invérifiable."""
    from nokido_agent.tools.forge_debate_job import _turn

    lignes = "\n".join(f"{i+1}. [{c['id']}] {c['desc'][:220]}" for i, c in enumerate(corpus))
    prompt = (
        "Tu es un SCOREUR. Voici une methode de detection de regression (liste d'axes) :\n\n"
        f"{methode[:6000]}\n\n"
        "Voici des regressions REELLEMENT SURVENUES. Pour CHACUNE, une ligne :\n"
        "  <numero>|<nom_axe_qui_l_attrape ou MISSED>|<justification 12 mots max>\n"
        "Sois severe : si aucun axe ne lit le signal necessaire, c'est MISSED. Pas de preambule.\n\n"
        f"{lignes}"
    )
    # Le scoreur NE DOIT PAS etre le modele des debatteurs : un panel qui se note
    # lui-meme se donne raison. Juge distinct et plus fort que les plaidoiries.
    txt, ok = await _turn("groq:llama-3.3-70b-versatile", prompt, max_tokens=1400)
    couvert, manque = [], []
    for l in [x.strip() for x in (txt or "").splitlines() if "|" in x]:
        # FAUX-VERT VECU (2026-08-13) : le modele prefixe sa PROPRE numerotation
        # ("1. 2|axe|MISSED"). Lue naivement, elle decale tout d'un cran — le
        # verdict MISSED tombe dans la justification, chaque ligne passe pour
        # COUVERTE, et le rappel affiche 100% alors que le modele a repondu
        # MISSED partout. Pire, "1. 2" donnait l'index 12. On retire donc
        # l'enumeration AVANT de decouper.
        l = re.sub(r"^\s*\d+\s*[.)]\s+(?=\d)", "", l)
        parts = [p.strip() for p in l.split("|")]
        if len(parts) < 2:
            continue
        try:
            idx = int(re.sub(r"\D", "", parts[0])) - 1
        except Exception:  # noqa: BLE001
            continue
        if not (0 <= idx < len(corpus)):
            continue
        # Le verdict peut se loger dans n'importe quel champ selon la mise en
        # forme : on cherche MISSED PARTOUT plutot que de parier sur sa place.
        # 3e FAUX-VERT DU MEME INSTRUMENT (2026-08-13) : run 1, le modele
        # prefixait sa numerotation ; run 2, il a ecrit **MISSED** en gras
        # markdown -- et startswith("MISS") echoue sur une chaine qui commence
        # par '*'. Chaque run invente une mise en forme, et chaque fois le
        # verdict MISSED se transforme en couverture. On normalise donc avant
        # de comparer, et on cherche la sous-chaine, pas le prefixe.
        norm = [re.sub(r"[^A-Z0-9_]", "", p.upper()) for p in parts[1:]]
        rate = any("MISSED" in p or p == "MISS" for p in norm)
        item = {"cas": corpus[idx]["id"], "axe": parts[1],
                "why": parts[2] if len(parts) > 2 else ""}
        (manque if rate else couvert).append(item)
    n = len(couvert) + len(manque)
    # FAIL-CLOSED : un juge dont la sortie ne se lit pas ne rend AUCUN score.
    # Coercer une ligne mal formee en "couverte" est precisement ce qui a
    # produit trois 100% mensongers. Sans lecture fiable : recall = None.
    lisibles = n / len(corpus) if corpus else 0
    fiable = bool(ok) and lisibles >= 0.8
    return {
        "ok": ok, "n_juges": n, "n_corpus": len(corpus),
        "recall_pct": (round(100.0 * len(couvert) / n, 1) if n else None) if fiable else None,
        "verdict_lisible": fiable,
        "raison_non_fiable": None if fiable else (
            f"seulement {n}/{len(corpus)} lignes lues (seuil 80%)" if ok
            else "le juge n'a pas repondu"),
        "non_juges": len(corpus) - n, "couvert": couvert, "MISSED": manque,
        "brut": (txt or "")[:2000],
    }


def _diffuser(res: dict) -> None:
    r = res.get("rappel", {})
    corps = (
        "[DEBAT-M2M ANTIREGRESSION — retour de CLAUDE sur ta PROPOSITION DEBAT]\n\n"
        "Contre-proposition : tes 4 points sont RETENUS mais subordonnes a une mesure. Un axe "
        "n'entre dans la methode que s'il augmente le RAPPEL mesure sur des regressions DEJA "
        "survenues, et qu'il sait rendre INDETERMINE.\n\n"
        f"RAPPEL MESURE : {r.get('recall_pct')}% ({r.get('n_juges')} cas juges / "
        f"{r.get('n_corpus')} corpus)\n"
        f"MISSED (= axes manquants) : {[m['cas'] for m in r.get('MISSED', [])][:12]}\n\n"
        f"SYNTHESE :\n{(res.get('synthesis') or '')[:2200]}\n\n"
        f"ANGLES MORTS DECLARES : {res.get('angles_morts')}\n\n"
        "Ton tour : conteste la mesure, ou propose les axes qui couvrent les MISSED. Reponds a "
        "CLAUDE via forge_postal."
    )
    try:
        from nokido_agent.app.forge_postal import post
        post("CLAUDE", "ANTIGRAVITY", corps)
        res["postal"] = "ANTIGRAVITY"
    except Exception as e:  # noqa: BLE001
        res["postal_err"] = repr(e)
    try:
        from nokido_agent.app.forge_swarm_blackboard import get_blackboard
        get_blackboard().propose_fact(
            "discovered_facts",
            json.dumps({
                "sujet": "methode_antiregression_recall_mesure",
                "recall_pct": r.get("recall_pct"),
                "missed": [m["cas"] for m in r.get("MISSED", [])][:20],
                "angles_morts": res.get("angles_morts"), "doc": str(OUT_DOC),
            }, ensure_ascii=False),
            category="methode", trust=0.7, key="methode_antiregression_2026_08_13")
        res["blackboard"] = "ok"
    except Exception as e:  # noqa: BLE001
        res["blackboard_err"] = repr(e)
    try:
        OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
        doc = [
            "# Debat M2M — methode anti-regression qui ne rate rien (2026-08-13)",
            "",
            f"**Rappel mesure** : {r.get('recall_pct')}% sur {r.get('n_juges')} cas juges "
            f"({r.get('n_corpus')} au corpus, {r.get('non_juges')} non juges).",
            "",
            "## Angles morts declares",
            *[f"- {a}" for a in (res.get("angles_morts") or ["(aucun)"])],
            "",
            "## Cas historiques NON couverts (MISSED) = axes a creer",
            *([f"- **{m['cas']}** — {m['why']}" for m in r.get("MISSED", [])] or ["- (aucun)"]),
            "",
            "## Synthese du debat",
            "",
            res.get("synthesis", ""),
            "",
            "## Tours de parole",
            "",
        ]
        for t in res.get("transcript", []):
            doc += [f"### {t['name']} ({t['provider']}) — {'OK' if t['ok'] else 'FAIL'}",
                    t["text"], ""]
        OUT_DOC.write_text("\n".join(doc), encoding="utf-8")
        res["doc"] = str(OUT_DOC)
    except Exception as e:  # noqa: BLE001
        res["doc_err"] = repr(e)


# ── SSoT DU DEBAT (memoire partagee) ─────────────────────────────────
# Mesure du 2026-08-13 sur un debat de 9 tours : 9 796 caracteres PRODUITS,
# 44 978 RE-ENVOYES, soit 4,6x de redondance -- parce que chaque prise de
# parole re-injecte tout le transcript. Le cout croit en O(N^2) alors que la
# connaissance, elle, croit en O(N). On remplace donc le transcript par un ETAT
# PARTAGE borne : chaque agent lit l'etat (axes + tensions + acquis mesures) et
# n'ecrit que son DELTA. Le verbatim va au journal, qui n'est jamais re-envoye.
SSOT_FICHIER = ROOT / "sandbox" / "debat_ssot_antiregression.json"
JOURNAL = ROOT / "sandbox" / "debat_journal_antiregression.md"
SSOT_CAP = 1800          # plafond du contexte partage, NOMME (jamais silencieux)


def ssot_lire() -> dict:
    try:
        return json.loads(SSOT_FICHIER.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"tour": 0, "axes": {}, "tensions": [], "acquis": []}


def ssot_ecrire(etat: dict) -> None:
    """Ecrit l'etat, le miroite au tableau noir (cle deterministe = idempotent)
    et publie l'evenement : les autres organes reagissent au lieu de sonder."""
    try:
        SSOT_FICHIER.parent.mkdir(parents=True, exist_ok=True)
        SSOT_FICHIER.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    try:
        from nokido_agent.app.forge_swarm_blackboard import get_blackboard

        get_blackboard().propose_fact(
            "discovered_facts", json.dumps(etat, ensure_ascii=False)[:4000],
            category="debat", trust=0.6, key="debat_antiregression_ssot")
    except Exception:  # noqa: BLE001
        pass
    # Un except nu ici avalerait la panne du bus : le debat se croirait
    # evenementiel en ne publiant rien. L'echec est donc INSCRIT dans l'etat.
    try:
        from nokido_agent.app.forge_events import publish

        publish("debat.tour", {"tour": etat.get("tour"), "axes": len(etat.get("axes", {}))})
        etat.pop("_bus_err", None)
    except Exception as e:  # noqa: BLE001
        etat["_bus_err"] = f"{type(e).__name__}: {str(e)[:110]}"


def _ssot_compact(etat: dict) -> str:
    """L'etat tel qu'un agent le recoit : borne, et le plafond est declare."""
    vue = {
        "tour": etat.get("tour"),
        "axes": {k: f"{v.get('statut')} ({v.get('mesure', 'non mesure')})"
                 for k, v in (etat.get("axes") or {}).items()},
        "tensions_ouvertes": (etat.get("tensions") or [])[-6:],
        "acquis_mesures": (etat.get("acquis") or [])[-6:],
    }
    s = json.dumps(vue, ensure_ascii=False)
    return s if len(s) <= SSOT_CAP else s[:SSOT_CAP] + f"... [ETAT TRONQUE a {SSOT_CAP} car.]"


# Vocabulaire FERME des statuts d'axe. Ce qui n'en fait pas partie retombe au
# plus bas ("candidat") : un modele ne doit pas pouvoir inventer un statut.
_STATUTS = ("candidat", "admis", "rejete")


def _norme(txt: str) -> str:
    """Retire la mise en forme markdown AVANT d'en faire une cle ou un statut.

    MESURE 2026-08-14, TROISIEME passage du MEME mecanisme : le SSoT contenait
    CINQ variantes d'un seul axe — `AST_Runtime_Mismatch`,
    `**AST_Runtime_Mismatch**`, `AST_Runtime_Mismatch**`,
    `** **AST_Runtime_Mismatch**` — simultanement `admis`, `candidat` ET
    `**rejete**`, parce que `strip(" -*")` ne nettoyait que les BORDS de la ligne.
    Pire : `**AXE**:` ne passait meme pas le `startswith("AXE:")`, donc des tours
    entiers n'entraient pas. Avant cela, un `**MISSED**` en gras avait transforme
    un rappel reel de 12,5 % en 100 % annonce. Le markdown d'un modele ne doit
    JAMAIS devenir une cle. Les `_` sont PRESERVES : les axes sont en snake_case.
    """
    import re as _re

    t = _re.sub(r"[*`#~]+", "", txt or "")
    return _re.sub(r"\s+", " ", t).strip(" :|-•\t")


def rejouer(journal: list) -> dict:
    """Reconstruit l'etat A PARTIR DU JOURNAL, depuis zero.

    ETAPE 2 de la couche causale (2026-09-04). `positions[]` est une PROJECTION,
    pas un journal : sans les deltas bruts, on peut relire l'etat mais pas le
    REJOUER. Un test qui rejoue un flux ecrit a la main simule le systeme, il ne
    le rejoue pas — la nuance decide si NR-7a mesure quelque chose.

    Contrat : `rejouer(etat["journal"]) == etat` (aux clefs derivees pres). C'est
    ce qui rend possibles l'event log, la baseline sur rejeu, puis le banc SNN.
    """
    etat: dict = {"tour": 0, "axes": {}, "tensions": [], "acquis": [],
                  "positions": [], "journal": []}
    for ev in journal or []:
        _applique_delta(etat, ev.get("qui", ""), ev.get("texte", ""),
                        _journaliser=True)
    return etat


def _applique_delta(etat: dict, qui: str, texte: str, _journaliser: bool = True) -> int:
    """Un tour n'ajoute que son delta. Sans lignes reconnues : rien n'entre.

    Le delta BRUT est journalise avant d'etre applique : c'est lui, et non
    l'etat derive, qui permet le rejeu. Un delta sans ligne reconnue n'entre pas
    dans l'etat mais RESTE au journal — sinon le rejeu ne reproduirait pas le
    meme decompte de tours, et un silence d'agent deviendrait invisible.
    """
    n = 0
    if _journaliser:
        etat.setdefault("journal", []).append(
            {"seq": len(etat.get("journal") or []) + 1,
             "tour": etat.get("tour", 0), "qui": qui, "texte": texte})
    for l in (texte or "").splitlines():
        s = _norme(l)          # normaliser AVANT de reconnaitre le prefixe
        h = s.upper()
        if h.startswith("AXE:"):
            p = [x.strip() for x in s[4:].split("|")]
            nom = _norme(p[0] if p else "")
            if nom:
                st = _norme(p[1] if len(p) > 1 else "").lower()
                if st not in _STATUTS:
                    # FAIL-CLOSED : statut illisible ou invente -> le plus bas.
                    st = "candidat"
                # NON DESTRUCTIF (2026-09-04). Avant : `axes[nom] = {...}` ECRASAIT
                # la position precedente. L'antecedent disparaissait, donc aucune
                # filiation n'etait reconstructible et le REJEU etait impossible —
                # pas faute de journal, mais parce que l'information n'existait
                # plus. C'est le verrou de fondation : sans lui, ni `supersedes`,
                # ni projection des tensions, ni event log, ni banc SNN.
                cle = nom[:60]
                axes = etat.setdefault("axes", {})
                hist = etat.setdefault("positions", [])
                ancien = axes.get(cle)
                # IDENTITE DETERMINISTE : rang de la position DANS SON AXE. Jamais
                # d'horodatage ni d'uuid — rejouer le meme flux doit rendre les
                # MEMES identifiants, sinon l'invariant de rejeu est infalsifiable.
                seq = 1 + sum(1 for q in hist if q.get("axe") == cle)
                position = {
                    "id": "P_%s_%d" % (cle, seq),
                    "axe": cle,
                    "statut": st,
                    "par": qui,
                    "why": _norme(p[2] if len(p) > 2 else "")[:140],
                    "mesure": "non mesure",
                    "supersedes": (ancien or {}).get("id"),
                }
                hist.append(position)
                # `axes[cle]` reste la vue COURANTE, meme forme qu'avant plus
                # `id`/`supersedes` : les lecteurs existants (_ssot_compact,
                # agent_testeur) ne changent pas de semantique.
                axes[cle] = dict(position)
                n += 1
        elif h.startswith("TENSION:"):
            etat.setdefault("tensions", []).append(f"[{qui}] {s[8:].strip()[:160]}")
            n += 1
        elif h.startswith("ACQUIS:"):
            etat.setdefault("acquis", []).append(f"[{qui}] {s[7:].strip()[:160]}")
            n += 1
    return n


def agent_testeur(etat: dict, n_commits: int = 12) -> dict:
    """L'AGENT TESTEUR : il ne discute pas, il EXECUTE et inscrit le resultat.

    Chaque axe propose par la parole reste 'non mesure' jusqu'a ce qu'un
    detecteur executable le confronte a des regressions DEJA survenues. Regle
    non negociable du debat : AUCUN axe ne peut passer 'admis' sans mesure --
    sinon la conviction d'un modele suffirait a faire entrer un capteur aveugle
    dans la methode. Un axe sans detecteur est donc retrograde, pas rejete :
    il attend son implementation.
    """
    bilan = {"mesures": 0, "sans_detecteur": 0, "retrogrades": 0}
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools import forge_axis_backtest as B

        commits = B.commits_de_correction("2026-05-01", n_commits)
    except Exception as e:  # noqa: BLE001
        etat["_testeur_err"] = f"{type(e).__name__}: {str(e)[:110]}"
        return bilan
    if not commits:
        etat["_testeur_err"] = "0 commit de correction : verite terrain muette"
        return bilan
    for nom, ax in (etat.get("axes") or {}).items():
        if ax.get("mesure") not in (None, "", "non mesure"):
            continue
        cle = next((k for k in B.AXES if k in nom or nom in k), None)
        if not cle:
            ax["mesure"] = "non executable — aucun detecteur ecrit"
            bilan["sans_detecteur"] += 1
        else:
            try:
                r = B.backtest(cle, commits)
                ax["mesure"] = (f"rappel {r['rappel_pct']}% / hors cible "
                                f"{r['bruit_hors_cible_pct']}% sur {r['commits_juges']} commits")
                ax["rappel_pct"] = r["rappel_pct"]
                bilan["mesures"] += 1
            except Exception as e:  # noqa: BLE001
                ax["mesure"] = f"mesure KO: {str(e)[:80]}"
        if str(ax.get("statut", "")).lower().startswith("admis"):
            ax["statut"] = "candidat"
            ax["why"] = (ax.get("why", "") + " [retrograde par le testeur : admis sans mesure]")[:220]
            bilan["retrogrades"] += 1
    return bilan


async def arene_ssot(objectif: str, parts: list, rounds: int) -> dict:
    """Debat a memoire partagee : contexte = ETAT + dernier delta, pas l'historique."""
    from nokido_agent.tools.forge_debate_job import _turn

    etat = ssot_lire()
    transcript, envoyes, dernier = [], 0, "(ouverture du debat)"
    # LE DOSSIER (objectif + corpus + role complet) NE PART QU'UNE FOIS PAR
    # PARTICIPANT. Mesure du 2026-08-13 : le SSoT seul n'avait rien economise
    # (46 237 car. contre 44 978) parce que ce dossier constant repartait a
    # CHAQUE tour -- a 9 tours, c'est lui le volume, pas le transcript. Ensuite
    # l'agent ne recoit que l'etat + le dernier delta : ce qu'il a besoin de
    # savoir a deja ete verse dans les axes, tensions et acquis.
    dossier_vu: set = set()
    for rnd in range(1, rounds + 1):
        for nom, provider, role in parts:
            if rnd == 1:
                # TOUR AVEUGLE (idee du Model Council de Perplexity, 02/2026) : au
                # premier tour personne ne voit les autres. Passer le delta precedent
                # CONTAMINE — le second argumente deja dans le cadre du premier, les
                # erreurs se correlent et le panel converge sur une position commune
                # qui peut etre commune ET fausse. On decorrele d'abord, on confronte
                # ensuite. (Leur limite, qu'on ne reprend pas : leur synthetiseur
                # agrege des OPINIONS ; ici le Testeur execute.)
                prompt = (
                    f"{role}\n\n## OBJECTIF\n{objectif}\n\n## CONTRAINTE\n{CONTRAINTE}\n\n"
                    f"## TOUR AVEUGLE — {nom}\nTu ne vois AUCUNE autre position : c'est "
                    "voulu. Ecris ton DELTA seul, 120 mots max, en lignes prefixees :\n"
                    "  AXE: <nom> | <candidat|admis|rejete> | <pourquoi, mecanique concrete>\n"
                    "  TENSION: <ce qui te parait fragile dans l'objectif lui-meme>\n"
                    "  ACQUIS: <fait etabli, avec sa source ou sa mesure>"
                )
                dossier_vu.add(nom)
                envoyes += len(prompt)
                texte, ok = await _turn(provider, prompt, _tokens(nom))
                etat["tour"] = etat.get("tour", 0) + 1
                _pub, _fmt_ok, _motif = _publie(nom, texte)
                ok = ok and _fmt_ok
                deltas = _applique_delta(etat, nom, _pub) if ok else 0
                if not _fmt_ok:
                    print(f"[arene] tour REJETE — {nom}: {_motif}", flush=True)
                ssot_ecrire(etat)
                transcript.append({"name": nom, "provider": provider, "ok": ok,
                                   "text": texte, "deltas": deltas, "aveugle": True})
                try:
                    with JOURNAL.open("a", encoding="utf-8") as f:
                        f.write(f"\n### tour {etat['tour']} — {nom} ({provider}) AVEUGLE "
                                f"{'OK' if ok else 'FAIL'} — {deltas} delta(s)\n{texte}\n")
                except Exception:  # noqa: BLE001
                    pass
                continue
            if nom in dossier_vu:                     # tours suivants : contexte MINIMAL
                entete = (f"Tu es {nom}, meme role qu'au tour precedent (dossier deja transmis).\n\n"
                          f"## ETAT PARTAGE DU DEBAT (SSoT — seule memoire commune)\n"
                          f"{_ssot_compact(etat)}\n\n")
            else:                                     # premiere prise de parole : dossier complet
                dossier_vu.add(nom)
                entete = (f"{role}\n\n## OBJECTIF\n{objectif}\n\n## CONTRAINTE\n{CONTRAINTE}\n\n"
                          f"## ETAT PARTAGE DU DEBAT (SSoT — seule memoire commune)\n"
                          f"{_ssot_compact(etat)}\n\n")
            prompt = (
                entete
                + f"## DERNIERE PRISE DE PAROLE\n{dernier[:700]}\n\n"
                f"## TON TOUR — {nom} (round {rnd}/{rounds})\n"
                "N'ecris QUE ton DELTA, 120 mots max, en lignes prefixees :\n"
                "  AXE: <nom> | <candidat|admis|rejete> | <pourquoi, mecanique concrete>\n"
                "  TENSION: <desaccord precis qui reste ouvert>\n"
                "  ACQUIS: <fait etabli, avec sa source ou sa mesure>\n"
                "Ne repete RIEN de l'etat : il est deja lu par tous."
                + _rappel_format(nom)
            )
            envoyes += len(prompt)
            texte, ok = await _turn(provider, prompt, _tokens(nom))
            etat["tour"] = etat.get("tour", 0) + 1
            _pub, _fmt_ok, _motif = _publie(nom, texte)
            ok = ok and _fmt_ok
            deltas = _applique_delta(etat, nom, _pub) if ok else 0
            if not _fmt_ok:
                print(f"[arene] tour REJETE — {nom}: {_motif}", flush=True)
            ssot_ecrire(etat)
            transcript.append({"name": nom, "provider": provider, "ok": ok,
                               "text": texte, "deltas": deltas,
                               "format_ok": _fmt_ok, "publie": _pub[:400]})
            if ok:
                # ANONYMISATION : la complaisance est pilotee par l'IDENTITE du
                # pair (ACL 2026). On masque QUI a parle, jamais ce qui a ete dit.
                _vu = (anonymise([{"agent": nom, "txt": _pub}], "")[0]["agent"]
                       if _ROLES_OK else nom)
                dernier = f"[{_vu}] {_pub}"
            try:
                with JOURNAL.open("a", encoding="utf-8") as f:
                    f.write(f"\n### tour {etat['tour']} — {nom} ({provider}) "
                            f"{'OK' if ok else 'FAIL'} — {deltas} delta(s)\n{texte}\n")
            except Exception:  # noqa: BLE001
                pass
        # Fin de round : le TESTEUR passe. Les axes proposes au round N sont
        # mesures AVANT que quiconque parle au round N+1 -- les debatteurs
        # argumentent donc contre des chiffres, plus contre des opinions.
        etat["_testeur"] = agent_testeur(etat)
        ssot_ecrire(etat)
    produits = sum(len(t["text"]) for t in transcript)
    return {"transcript": transcript, "ssot": etat, "rounds": rounds,
            "economie": {"chars_contexte_envoyes": envoyes, "chars_produits": produits,
                         "dossiers_envoyes": len(dossier_vu), "tours": len(transcript),
                         "reference_ssot_seul": 46237, "reference_transcript": 44978,
                         "note": "meme unite que reference_ssot_seul (prompt ENTIER) : "
                                 "seule cette paire est comparable"}}


async def _run(rounds: int) -> dict:
    bl: dict = {}
    axes = axes_en_production(bl)
    agy = proposition_agy(bl)
    corpus = corpus_regressions_connues(bl)

    # Pre-redaction to bypass cloud firewall DLP block on legitimate paths/IPs
    agy, _ = redact_text(agy)
    for c in corpus:
        c["desc"], _ = redact_text(c["desc"])

    parts, axes_s = _participants(agy, axes)

    res = await arene_ssot(_objectif(axes_s, corpus), parts, rounds)
    res["synthesis"] = json.dumps(res.get("ssot", {}), ensure_ascii=False)
    res["axes_production"] = axes
    res["corpus_n"] = len(corpus)
    res["agy_position_recue"] = bool(agy)
    res["angles_morts"] = bl.get("angles_morts", [])
    res["rappel"] = (await _scorer_rappel(res.get("synthesis") or "", corpus)) if corpus else {
        "recall_pct": None, "n_juges": 0, "n_corpus": 0, "MISSED": [],
        "note": "corpus VIDE -> aucune mesure possible (voir angles_morts)"}
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    a = ap.parse_args()
    t0 = time.time()
    res = asyncio.run(_run(max(1, min(4, a.rounds))))
    _diffuser(res)
    res["elapsed_s"] = round(time.time() - t0, 1)
    try:
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str),
                            encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    r = res.get("rappel", {})
    print(json.dumps({
        "ok": True, "elapsed_s": res["elapsed_s"],
        "turns": len(res.get("transcript", [])),
        "ok_turns": sum(1 for t in res.get("transcript", []) if t["ok"]),
        "corpus": res.get("corpus_n"), "recall_pct": r.get("recall_pct"),
        "missed": len(r.get("MISSED", [])), "angles_morts": res.get("angles_morts"),
        "postal": res.get("postal") or res.get("postal_err"), "doc": res.get("doc"),
    }, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
