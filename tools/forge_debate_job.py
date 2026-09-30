"""forge_debate_job.py — ARÈNE DE DÉBAT multi-tour SOUVERAINE (déportable via run_job).

Orchestre les TOURS DE PAROLE en local : chaque participant parle EN ORDRE en voyant le
transcript courant (turn-taking structuré). La perception est nourrie par le RAG (domaine
nokido_code) puis filtrée par le SemanticFirewall (redact PII) AVANT tout envoi cloud. Après
N rounds : une synthèse (consensus / désaccords / actions) + CAPTURE D'INTENTIONS (lignes
'ACTION:' extraites = intents rapportés, JAMAIS auto-exécutés = ring-gated). Résultat posté à
l'émetteur (postal) + doc C:/tmp.

Participants = providers du registry (gemini_cli OAuth / sambanova Llama-3.3-70B / groq) =
cloud-léger : ZÉRO charge pool local/iGPU/embedder (compatible la garde homéostatique quand
ces sous-systèmes sont emboliés). Réutilise forge_cli_swarm._one (anti-dup, normalise ask()).

Conçu d'après l'ORDRE Gemini 2026-06-14 : « cristallisation du transient (RAM→Blackboard) vs
isolation Ring 4 + Qualified Perception ». Réutilisable : --rounds, défauts = l'ORDRE.
JAMAIS le Workflow cloud (subagents payants) — orchestration 100% souveraine.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `capsule_en_texte` — Rendu COURT pour une boite noire (Claude, agy) : sections fixes, borne.
- `cristalliser` — Capsule cognitive d'un resultat de `run_debate`.
- `ecrire_capsule` — Ecrit la capsule a cote du resultat (`x.json` -> `x.capsule.json`), qu'elle pointe.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# Racine DERIVEE du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

DEFAULT_OBJECTIVE = (
    "Définir la mécanique de CRISTALLISATION DU TRANSIENT (état RAM éphémère d'un agent → "
    "Blackboard persistant souverain) VS isolation RING 4 (Cloud/untrusted) : quand un état "
    "transient se cristallise (persiste), quand il reste éphémère (jeté), quand il DOIT être "
    "isolé en Ring 4. + QUALIFIED PERCEPTION : comment qualifier/gater la perception (trust)."
)
DEFAULT_CONSTRAINT = (
    "Perception nourrie par le RAG (domaine nokido_code) et filtrée par SemanticFirewall "
    "(redact PII) avant tout envoi cloud. Garde-fous ring/firewall = post-filtre non négociable."
)
# (nom affiché, provider registry, rôle/system injecté)
DEFAULT_PARTICIPANTS = [
    ("Gemini", "gemini_cli",
     "Tu es le PROPOSEUR. Défends une mécanique CONCRÈTE de cristallisation transient→blackboard : "
     "définis les SEUILS (quand persister un état RAM, quand le jeter)."),
    ("Llama-3.3-70B", "sambanova",
     "Tu es l'ANALYSTE. Rigueur + trade-offs mémoire/coût/latence. Propose les CRITÈRES précis "
     "d'isolation Ring 4. Challenge le proposeur sur les cas limites."),
    ("Sentinel", "router",
     "Tu es la SENTINELLE SÉCURITÉ (adversarial). Fuite PII, surface d'attaque, QUAND il FAUT "
     "forcer l'isolation Ring 4, enforcement firewall. Sois sceptique, cherche la faille."),
]
ROUNDS = 2


async def _turn(provider: str, prompt: str, max_tokens: int = 520):
    """Une prise de parole. Réutilise forge_cli_swarm._one (normalise ask -> {ok,text,...})."""
    try:
        from nokido_agent.tools.forge_cli_swarm import _one
        import re as _re

        # Nettoyage des chaînes de 64 caractères (comme les hashs RAG) pour éviter les faux-positifs DLP cloud
        prompt = _re.sub(r"\b[A-Za-z0-9]{64}\b", "[HASH_64]", prompt)
        
        from nokido_agent.app.forge_semantic_firewall import redact_text
        prompt, _ = redact_text(prompt)

        a = await _one(provider, prompt, max_tokens)
        txt = (a.get("text") or "").strip()
        # UN APPEL QUI REUSSIT ET REND DU VIDE N'EST PAS UN AVIS (mesure 2026-09-02).
        # `ok` venait du TRANSPORT : un tour vide sortait donc `ok=True` et se comptait
        # comme une participation. Consequence directe : le taux de disponibilite d'un
        # provider etait surestime, et une revue sans contenu pouvait se lire comme un
        # « rien a signaler ». Le silence d'un agent doit rester un silence.
        if not txt:
            return f"[{provider}: réponse vide]", False
        return txt, bool(a.get("ok"))
    except Exception as e:  # noqa: BLE001
        return f"[{provider}: ERREUR {e!r}]", False


def _rag_context(query: str) -> str:
    """Nourrit la perception via RAG (nokido_code) PUIS redact PII (SemanticFirewall)."""
    ctx = ""
    try:
        from nokido_agent.app.forge_self_correction import preflight_check_verbose

        v = preflight_check_verbose(query, "")
        ctx = "\n".join(
            f"- [{r.get('source')}] {str(r.get('preview', ''))[:180]}"
            for r in (v.get("results") or [])[:6]
        ) or "(aucun match RAG)"
    except Exception as e:  # noqa: BLE001
        ctx = f"(RAG indispo: {e!r})"
    try:
        from nokido_agent.app.forge_semantic_firewall import get_firewall

        pf = get_firewall().pre_flight(ctx, context="", ring=2, provider="auto")
        if getattr(pf, "ok", True):
            ctx = getattr(pf, "safe_task", None) or ctx
    except Exception:  # noqa: BLE001
        pass
    return ctx


def _capture_intents(text: str) -> list:
    """Capte les INTENTIONS d'action du LLM (lignes ACTION:/PROPOSE:/RECOMMAND:). Rapportées,
    JAMAIS auto-exécutées (irréversible = ring-gated + confirmation owner)."""
    intents = []
    for line in (text or "").splitlines():
        s = line.strip(" -*\t•")
        if s[:9].upper().startswith(("ACTION", "PROPOSE", "RECOMMAN", "TODO")):
            intents.append(s[:220])
    return intents[:15]


# --- CAPSULE COGNITIVE (RecursiveMAS, direction owner 2026-09-28) ---------------------------
#
# RecursiveMAS pense AUTOUR des boites noires (Claude Code, agy), jamais dedans : elles ne
# recoivent qu'une capsule courte et tracable, CRISTALLISEE par le corps. La capsule est une
# projection DETERMINISTE de l'etat deja produit par le debat (axes, positions, tensions,
# acquis, intentions, verdict sous quorum) -- aucun appel de modele de plus, rien d'invente.
# « Preuve != parole » : tout ce qu'un debat produit est DECLARED ; OBSERVED/PROVEN
# exigeraient une reference de preuve, qu'un debat n'apporte pas. Le RAG est un CONTEXTE.
# Envoyer une capsule a un modele cloud reste soumis au pare-feu (`redact_tool_output`) :
# ce module la cristallise, il ne l'envoie pas.
CAPSULE_SCHEMA = "nokido.capsule/1"
CAPSULE_ETAT_MAX = 1500
CAPSULE_TEXTE_MAX = 3000
_CAPSULE_LISTE_MAX = 12
_CAPSULE_ITEM_MAX = 200


def _auteur_ligne(ligne: str) -> tuple:
    """'[qui] texte' -> (qui, texte)."""
    s = (ligne or "").strip()
    if s.startswith("[") and "]" in s:
        qui, _, reste = s[1:].partition("]")
        return qui.strip(), reste.strip()
    return "", s


def cristalliser(result: dict, ref: str = "", cristallise_a: str = None) -> dict:
    """Capsule cognitive d'un resultat de `run_debate` (voir le bandeau ci-dessus)."""
    import datetime as _dt

    delib = result.get("deliberation") or {}
    axes = delib.get("axes") or {}
    positions = delib.get("positions") or []

    def _item(axe: str, p: dict) -> dict:
        return {"axe": axe, "texte": str(p.get("why") or "")[:_CAPSULE_ITEM_MAX],
                "par": p.get("par"), "position": p.get("id"), "preuve": "DECLARED"}

    faits = [_item(a, p) for a, p in sorted(axes.items()) if p.get("statut") == "admis"]
    for ligne in delib.get("acquis") or []:
        qui, texte = _auteur_ligne(ligne)
        faits.append({"axe": None, "texte": texte[:_CAPSULE_ITEM_MAX], "par": qui,
                      "position": None, "preuve": "DECLARED"})
    ecartes = [_item(a, p) for a, p in sorted(axes.items()) if p.get("statut") == "rejete"]
    incertitudes = [_item(a, p) for a, p in sorted(axes.items()) if p.get("statut") == "candidat"]

    # Contradictions : tensions declarees, et axes ADMIS par l'un et REJETES par l'autre
    # (derniere position de chaque participant sur l'axe).
    contradictions = [str(t)[:_CAPSULE_ITEM_MAX] for t in delib.get("tensions") or []]
    dernieres: dict = {}
    for p in positions:
        dernieres[(p.get("axe"), p.get("par"))] = p.get("statut")
    for axe in sorted({a for a, _q in dernieres}):
        par_statut: dict = {}
        for (a, qui), st in dernieres.items():
            if a == axe:
                par_statut.setdefault(st, []).append(str(qui))
        if "admis" in par_statut and "rejete" in par_statut:
            contradictions.append(
                f"axe {axe} : admis par {', '.join(sorted(par_statut['admis']))}, "
                f"rejete par {', '.join(sorted(par_statut['rejete']))}"[:_CAPSULE_ITEM_MAX])

    participants, vus = [], set()
    for t in result.get("transcript") or []:
        cle = (t.get("name"), t.get("provider"))
        if cle not in vus:
            vus.add(cle)
            participants.append({"nom": cle[0], "fournisseur": cle[1]})
    synthese = result.get("synthesis") if result.get("verdict") == "ADOPTE" else None
    return {
        "schema": CAPSULE_SCHEMA,
        "objectif": str(result.get("objective") or "")[:400],
        "verdict": result.get("verdict"),
        # Un resultat SANS verdict est anterieur au quorum (2026-09-05) : sa synthese n'est
        # pas reprise, et c'est dit -- « None » se lirait comme une absence de motif.
        "verdict_motif": result.get("verdict_motif") or (
            "resultat sans verdict (anterieur au quorum) : synthese non reprise"
            if result.get("verdict") is None else None),
        "confiance": "DECLARED",
        "etat": str(synthese)[:CAPSULE_ETAT_MAX] if synthese else None,
        "faits": faits[:_CAPSULE_LISTE_MAX],
        "ecartes": ecartes[:_CAPSULE_LISTE_MAX],
        "incertitudes": incertitudes[:_CAPSULE_LISTE_MAX],
        "contradictions": contradictions[:_CAPSULE_LISTE_MAX],
        "prochaines_actions": [str(a)[:_CAPSULE_ITEM_MAX]
                               for a in (result.get("captured_intents") or [])][:_CAPSULE_LISTE_MAX],
        "provenance": {
            "mode": result.get("mode"),
            "participants": participants,
            "tours": result.get("rounds"),
            "n_repondus": result.get("n_repondus"),
            "n_structures": result.get("n_structures"),
            "resultat_ref": ref,
            "rag": "contexte (CONTEXTE != CAUSE)" if result.get("rag_context") else None,
            "cristallise_a": cristallise_a or _dt.datetime.now(_dt.timezone.utc).isoformat(
                timespec="seconds"),
        },
    }


def capsule_en_texte(capsule: dict) -> str:
    """Rendu COURT pour une boite noire (Claude, agy) : sections fixes, borne."""
    def _l(items, fmt):
        return "\n".join(f"- {fmt(i)}" for i in items) or "- (aucun)"

    pv = capsule.get("provenance") or {}
    txt = "\n".join([
        f"CAPSULE NOKIDO ({capsule.get('schema')}) -- verdict {capsule.get('verdict')}, "
        f"confiance {capsule.get('confiance')}",
        f"OBJECTIF : {capsule.get('objectif')}",
        f"ETAT : {(capsule.get('etat') or '(pas de synthese : ' + str(capsule.get('verdict_motif')) + ')')[:600]}",
        "FAITS DECLARES :", _l(capsule.get("faits") or [],
                               lambda f: f"[{f.get('par')}] {f.get('axe') or 'acquis'} : {f.get('texte')}"),
        "CONTRADICTIONS :", _l(capsule.get("contradictions") or [], str),
        "INCERTITUDES :", _l(capsule.get("incertitudes") or [],
                             lambda f: f"[{f.get('par')}] {f.get('axe')} : {f.get('texte')}"),
        "ECARTES :", _l(capsule.get("ecartes") or [],
                        lambda f: f"[{f.get('par')}] {f.get('axe')} : {f.get('texte')}"),
        "PROCHAINES ACTIONS :", _l(capsule.get("prochaines_actions") or [], str),
        f"PROVENANCE : mode {pv.get('mode')}, {len(pv.get('participants') or [])} participant(s), "
        f"{pv.get('tours')} tour(s), resultat {pv.get('resultat_ref')}",
    ])
    return txt[:CAPSULE_TEXTE_MAX]


def ecrire_capsule(result: dict, chemin_resultat) -> str:
    """Ecrit la capsule a cote du resultat (`x.json` -> `x.capsule.json`), qu'elle pointe."""
    import json as _json

    chemin_resultat = Path(chemin_resultat)
    cible = chemin_resultat.with_name(chemin_resultat.stem + ".capsule.json")
    cible.write_text(_json.dumps(cristalliser(result, ref=str(chemin_resultat)),
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    return str(cible)


# ── PRELIGHT : le panel est un ETAT MESURE, pas une configuration figee ───────
# Mesure du 2026-09-05, trois defauts INDEPENDANTS sur un meme run :
#   1. DISPONIBILITE — 2 des 3 participants du panel fige rendaient une reponse VIDE ;
#   2. PERTINENCE    — les roles de `DEFAULT_PARTICIPANTS` portaient encore le cadrage
#                      d'un debat de juin (« cristallisation transient », « Ring 4 »),
#                      donc HORS SUJET quel que soit l'objectif passe ;
#   3. STRUCTURE     — le seul agent qui a repondu n'a produit aucune ligne `AXE:`,
#                      donc RESPONDED=1 et STRUCTURED=0.
# Chacun suffit a vider un debat, et aucun ne se voit dans le resultat final : la
# synthese sortait quand meme, batie sur un avis unique.
#
# ON NE CREE AUCUN REGISTRE. Quatre couches existent deja et ne doivent pas fusionner :
#   `forge_pool_registry`  ce qui est DECLARE  (valeurs uniformes, horodatees juin —
#                          il annonce `gemini_cli` disponible alors qu'il rend vide) ;
#   routeur / config       ce qui est CONFIGURE ;
#   `provider_scores`      ce qui est MESURE (statut, grade, ttft, fraicheur, et QUATRE
#                          producteurs vivants) — seule source du preflight ;
#   le debat lui-meme      ce qui a REPONDU puis STRUCTURE.
FRAICHEUR_MAX_S = 86400.0
QUORUM_MIN = 2

_ROLES = [
    ("Proposeur", "Tu es le PROPOSEUR. Defends une mecanique CONCRETE repondant a "
                  "l'objectif ci-dessus, avec des seuils et des points de mesure."),
    ("Analyste", "Tu es l'ANALYSTE. Rigueur et arbitrages cout/latence/complexite. "
                 "Challenge le proposeur sur les cas limites de CET objectif."),
    ("Sentinelle", "Tu es la SENTINELLE (adversarial). Cherche la faille, la surface "
                   "d'attaque et le faux positif dans ce qui est propose POUR CET "
                   "objectif. Sois sceptique."),
    ("Mesureur", "Tu es le MESUREUR. Tu ne discutes pas : pour chaque affirmation liee "
                 "a l'objectif tu exiges la preuve executable, et tu ecris UNKNOWN "
                 "quand elle manque."),
]


def _age_mesure(brut) -> float:
    """Age en secondes d'un horodatage de mesure. `None` si ILLISIBLE, jamais 0.

    `measured_at` melange `2026-09-05 04:03:40` et de l'ISO avec `T` dans cette base :
    on ESSAIE les formats au lieu d'en supposer un, comme pour les pouls.
    """
    from datetime import datetime

    s = str(brut or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return (datetime.now() - datetime.strptime(s.split(".")[0], fmt)).total_seconds()
        except ValueError:
            continue
    try:
        return (datetime.now() - datetime.fromtimestamp(float(s))).total_seconds()
    except Exception:  # noqa: BLE001
        return None


def preflight_providers(frais_s: float = FRAICHEUR_MAX_S) -> dict:
    """Etat MESURE des providers. Trois etats par provider, jamais deux.

    `ok` frais -> ELIGIBLE · `down`/`fail` -> INELIGIBLE · mesure absente ou perimee
    -> INCONNU, et INCONNU n'est PAS eligible : `gemini_cli` et `sambanova` ne figurent
    pas du tout dans la table, et c'est precisement pour cela qu'ils ont rendu vide sans
    que rien ne l'annonce. Les ecarter en silence serait la meme faute a l'envers : la
    raison est donc rendue.
    """
    import sqlite3

    try:
        from nokido_agent.app.forge_db_path import db_path

        cx = sqlite3.connect("file:%s?mode=ro" % str(db_path()).replace("\\", "/"),
                             uri=True, timeout=10)
    except Exception as exc:  # noqa: BLE001
        return {"lisible": False, "raison": "%s: %s" % (type(exc).__name__, exc),
                "eligibles": [], "detail": []}
    detail, eligibles = [], []
    try:
        rows = cx.execute(
            "SELECT provider, status, grade, ttft_ms, measured_at FROM provider_scores"
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        cx.close()
        return {"lisible": False, "raison": "provider_scores illisible: %s" % exc,
                "eligibles": [], "detail": []}
    cx.close()
    vus = {}
    for prov, statut, grade, ttft, mesure in rows:
        age = _age_mesure(mesure)
        if prov in vus and (vus[prov] or 1e18) <= (age if age is not None else 1e18):
            continue
        vus[prov] = age
        if age is None:
            etat, motif = "INCONNU", "horodatage de mesure illisible"
        elif age > frais_s:
            etat, motif = "INCONNU", "mesure perimee (%.0f h)" % (age / 3600.0)
        elif statut == "ok":
            etat, motif = "ELIGIBLE", None
        else:
            etat, motif = "INELIGIBLE", "statut mesure = %s" % statut
        detail.append({"provider": prov, "etat": etat, "statut": statut,
                       "grade": grade, "ttft_ms": ttft, "age_s": age, "motif": motif})
    for d in detail:
        if d["etat"] == "ELIGIBLE":
            eligibles.append(d)
    eligibles.sort(key=lambda d: (d["ttft_ms"] if d["ttft_ms"] is not None else 1e9))
    return {"lisible": True, "raison": None, "eligibles": eligibles, "detail": detail}


def panel_pour(objectif: str, frais_s: float = FRAICHEUR_MAX_S) -> tuple:
    """(participants, preflight) — roles construits SUR L'OBJECTIF COURANT.

    Le role ne vient plus d'une constante : un cadrage metier fige survit a l'objectif
    qu'il servait, et produit alors une sortie techniquement valide mais EPISTEMIQUEMENT
    hors sujet — defaut mesure le 2026-09-05.
    """
    pf = preflight_providers(frais_s)
    parts = []
    for i, d in enumerate(pf["eligibles"][:len(_ROLES)]):
        nom, role = _ROLES[i]
        parts.append((nom, d["provider"], role))
    return parts, pf


async def run_debate(objective: str, constraint: str, participants: list, rounds: int,
                     latent: bool = False) -> dict:
    # VERROU 1 — le panel vient de la MESURE, et le quorum se verifie AVANT de bruler
    # du quota : decouvrir en plein debat qu'il n'y a qu'un intervenant coute des
    # appels payants pour un resultat qu'on sait deja non concluant.
    preflight = None
    if not participants:
        participants, preflight = panel_pour(objective)
    if len(participants) < QUORUM_MIN:
        return {
            "objective": objective, "rounds": rounds, "mode": "aucun",
            "verdict": "NEEDS_MEASUREMENT",
            "verdict_motif": "quorum d'eligibles NON atteint : %d participant(s) "
                             "mesure(s) disponible(s) pour un minimum de %d — un avis "
                             "unique n'est pas une deliberation"
                             % (len(participants), QUORUM_MIN),
            "preflight": preflight, "transcript": [], "synthesis": None,
            "captured_intents": [], "deliberation": {"tour": 0, "axes": {},
                                                     "tensions": [], "acquis": []},
        }

    safe_ctx = _rag_context(
        "transient state blackboard ring isolation crystallization qualified perception "
        "RAG semantic firewall trust"
    )
    transcript = []  # (name, provider, text, ok)

    # --- Mode LATENT (RecursiveMAS Path 1) : le tour precedent est compresse en K=8
    # soft-vecteurs (link+LoRA entraine, recursive_link_v1.pt) que le self-model Qwen-0.5B
    # lit via inputs_embeds AU LIEU de re-tokeniser le texte -> input court. 100% LOCAL
    # (zero cloud, aucun provider). Fallback texte-cloud si le runtime est indisponible.
    lat, lat_econ, lat_note = None, [], None
    if latent:
        try:
            from nokido_agent.tools import forge_recursive_link as _rl
            lat = _rl
        except Exception as e:  # noqa: BLE001
            lat, lat_note = None, f"import forge_recursive_link KO: {e!r}"
        if lat is not None and not lat.is_available():
            lat_note = f"latent indisponible ({lat.why_unavailable()}) -> fallback texte-cloud"
            lat = None
        latent = lat is not None

    def _tr():
        return "\n\n".join(f"[{n}] {t}" for n, _p, t, _ok in transcript) if transcript else "(début du débat)"

    # ── JONCTION vers l'etat REJOUABLE (2026-09-05) ──────────────────────────
    # Mesure du jour : ce moteur produisait un transcript et une synthese, et
    # RIEN n'alimentait `forge_m2m_debate_antiregression`, seul substrat qui sache
    # rejouer. Consequence : la capacite `deliberation.replay` publiee dans la carte
    # A2A ne couvrait AUCUN debat reel — un mecanisme present mais non cable.
    #
    # Le raccord est UNE ligne par tour, vers la primitive existante. Elle journalise
    # le texte BRUT avant toute analyse : un tour sans ligne reconnue — donc un agent
    # MUET — reste au journal, et le rejeu reproduit le meme decompte de tours. Ne
    # pas alimenter le replay depuis les seules reponses non vides est exactement
    # l'invariant que son NR verrouille.
    etat_rejouable, _err_delta = {"tour": 0, "axes": {}, "tensions": [], "acquis": []}, None
    try:
        from nokido_agent.tools.forge_m2m_debate_antiregression import _applique_delta as _delta
    except Exception as exc:  # noqa: BLE001
        _delta, _err_delta = None, "%s: %s" % (type(exc).__name__, exc)

    def _tracer(qui: str, texte: str) -> None:
        """Ne doit JAMAIS faire echouer le debat : la trace est une sonde."""
        if _delta is None:
            return
        try:
            _delta(etat_rejouable, qui, texte or "")
        except Exception:  # noqa: BLE001 - muet-ok : sonde, jamais un porteur
            pass

    for rnd in range(1, rounds + 1):
        etat_rejouable["tour"] = rnd
        for name, provider, role in participants:
            if latent:                                   # relais latent self-model (local)
                role_aug = f"Tu es {name}. {role}"       # role-augmente : identite injectee dans le seed
                if not transcript:                       # bootstrap 1er tour depuis role+objectif
                    seed = (f"{objective}\n\nContrainte: {constraint}\n\n"
                            f"Prends la parole en 120 mots max, mecanique concrete, EN RESTANT dans ton role.")
                    text = await asyncio.to_thread(lat.gen_text, seed, role_aug, 150)
                else:                                    # hop latent depuis le tour precedent
                    prev = transcript[-1][2]
                    text, n_lat = await asyncio.to_thread(lat.latent_hop, prev, role_aug, 100)
                    n_txt = await asyncio.to_thread(lat.text_input_tokens, prev, role_aug)
                    lat_econ.append({"turn": name, "tok_latent": n_lat, "tok_texte": n_txt})
                transcript.append((name, "self-model-0.5B", text, True))
                _tracer(name, text)
                continue
            prompt = (
                f"{role}\n\n## OBJECTIF DU DÉBAT\n{objective}\n\n## CONTRAINTE\n{constraint}\n\n"
                f"## CONTEXTE RAG (nokido_code, PII-filtré)\n{safe_ctx}\n\n"
                f"## TRANSCRIPT (round {rnd}/{rounds})\n{_tr()}\n\n"
                f"## TON TOUR — {name}\nRéponds en 150 mots max, argumenté, mécanique concrète. "
                f"Si tu proposes une action Nokido, mets-la sur une ligne préfixée 'ACTION:'. "
                f"Si tu prends position sur un axe, ajoute une ligne "
                f"'AXE: <nom_axe> | candidat|admis|rejete | <pourquoi>' — c'est ce qui "
                f"donne à ta position une filiation rejouable."
            )
            text, ok = await _turn(provider, prompt)
            transcript.append((name, provider, text, ok))
            # Le tour est trace MEME en echec : un agent qui n'a pas repondu doit
            # rester visible au rejeu, sinon son silence devient invisible.
            _tracer(name, text)

    # VERROU 2 — RESPONDED n'est pas STRUCTURED. Un tour qui repond poliment sans
    # prendre position ne laisse ni filiation ni desaccord : il vaut un silence.
    def _structure(txt: str) -> bool:
        return any(l.strip().upper().startswith("AXE:") for l in (txt or "").splitlines())

    structures = sum(1 for _n, _p, t, ok in transcript if ok and _structure(t))
    repondus = sum(1 for _n, _p, _t, ok in transcript if ok)

    full = "\n\n".join(
        f"### {n} ({p}) — {'OK' if ok else 'FAIL'}\n{t}" for n, p, t, ok in transcript
    )
    synth_prompt = (
        f"Tu es le SECRÉTAIRE neutre du débat. Tours de parole :\n\n{full}\n\n"
        f"OBJECTIF : {objective}\n\nProduis en <=350 mots : 1) CONSENSUS (la mécanique retenue, "
        f"concrète, avec seuils), 2) DÉSACCORDS persistants, 3) ACTIONS PROPOSÉES (chaque action "
        f"sur une ligne préfixée 'ACTION:')."
    )
    # VERROU 3 — pas de synthese sous quorum. Le run du 2026-09-05 en produisait une
    # a partir d'UN SEUL avis, ce qui donne a un monologue l'apparence d'un consensus.
    verdict, motif = "ADOPTE", None
    if structures < QUORUM_MIN:
        verdict = "NEEDS_MEASUREMENT"
        motif = ("%d position(s) STRUCTUREE(s) pour un minimum de %d (%d tour(s) ont "
                 "repondu) — aucune synthese ne sera produite : elle reposerait sur un "
                 "avis unique" % (structures, QUORUM_MIN, repondus))
        synthesis = None
    elif latent and lat is not None:                     # synthese aussi 100% locale
        synthesis = await asyncio.to_thread(
            lat.gen_text, synth_prompt, "Tu es le secretaire neutre du debat.", 320)
    else:
        synthesis, _ok = await _turn("router", synth_prompt, max_tokens=950)
    result = {
        "objective": objective,
        "rounds": rounds,
        "verdict": verdict,
        "verdict_motif": motif,
        "preflight": preflight,
        "n_repondus": repondus,
        "n_structures": structures,
        "mode": "latent-relay" if (latent and lat is not None) else "text-cloud",
        "transcript": [{"name": n, "provider": p, "ok": ok, "text": t} for n, p, t, ok in transcript],
        # Etat REJOUABLE, a cote du transcript et non a sa place : le transcript
        # reste la trace lisible, l'etat porte la filiation (`positions` avec
        # `supersedes`) et le `journal` qui permet le rejeu deterministe.
        "deliberation": etat_rejouable,
        "deliberation_indisponible": _err_delta,
        "synthesis": synthesis,
        "captured_intents": _capture_intents(synthesis or ""),
        "rag_context": safe_ctx,
    }
    if lat_econ:
        tl = sum(e["tok_latent"] for e in lat_econ)
        tt = sum(e["tok_texte"] for e in lat_econ)
        result["latent_economy"] = {
            "hops": len(lat_econ), "tok_latent_total": tl, "tok_texte_total": tt,
            "ratio": round(tl / tt, 3) if tt else None,
            "economie_pct": round((1 - tl / tt) * 100, 1) if tt else None,
            "per_turn": lat_econ,
        }
    if lat_note:
        result["latent_note"] = lat_note
    return result


def _post_and_doc(result: dict, objective: str) -> None:
    try:
        from nokido_agent.app.forge_postal import post

        post(
            "CLAUDE", "GEMINI",
            "[DEBAT-RESULT] Débat orchestré (multi-tour LOCAL, turn-taking, RAG nokido_code + "
            f"firewall redact). SYNTHÈSE:\n{result.get('synthesis', '')[:1300]}\n\n"
            f"INTENTS CAPTÉS (rapportés, non exécutés): {result.get('captured_intents')}",
        )
        result["posted_to"] = "GEMINI"
    except Exception as e:  # noqa: BLE001
        result["post_err"] = repr(e)
    try:
        doc = Path(r"C:/tmp/DEBAT_TRANSIENT_QUALIFIED_PERCEPTION_2026-06-14.md")
        out = [
            "# Débat — Transient Management & Qualified Perception (2026-06-14)",
            "",
            f"**Objectif** : {objective}",
            "",
            "## Synthèse (consensus / désaccords / actions)",
            "",
            result.get("synthesis", ""),
            "",
            "## Tours de parole",
            "",
        ]
        for t in result.get("transcript", []):
            out.append(f"### {t['name']} ({t['provider']}) — {'OK' if t['ok'] else 'FAIL'}")
            out.append(t["text"])
            out.append("")
        out.append("## Intentions captées (RAPPORTÉES, non auto-exécutées — ring-gated)")
        out += [f"- {i}" for i in result.get("captured_intents", [])] or ["- (aucune)"]
        doc.write_text("\n".join(out), encoding="utf-8")
        result["doc"] = str(doc)
    except Exception as e:  # noqa: BLE001
        result["doc_err"] = repr(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=ROUNDS)
    ap.add_argument("--out", default=r"C:/tmp/debate_result.json")
    ap.add_argument("--latent", action="store_true",
                    help="Relais LATENT self-model local (RecursiveMAS) au lieu du texte-cloud")
    # SUJET PARAMETRABLE (2026-09-02). `run_debate` etait deja parametrable ; seul
    # `main()` figeait les constantes, ce qui obligeait a ecrire un wrapper jetable
    # pour chaque sujet. Les defauts sont INCHANGES : sans ces options, le
    # comportement est exactement celui d'avant.
    ap.add_argument("--objective", default=None,
                    help="Sujet du debat (defaut : DEFAULT_OBJECTIVE)")
    ap.add_argument("--constraint", default=None,
                    help="Contrainte injectee a chaque tour (defaut : DEFAULT_CONSTRAINT)")
    ap.add_argument("--roles", default=None,
                    help="Participants au format 'nom:provider:role|nom:provider:role'. "
                         "Un provider injoignable ne doit PAS etre lu comme un avis : "
                         "le transcript porte ok=False pour ce tour.")
    args = ap.parse_args()
    objectif = args.objective or DEFAULT_OBJECTIVE
    contrainte = args.constraint or DEFAULT_CONSTRAINT
    participants = DEFAULT_PARTICIPANTS
    if args.roles:
        participants = []
        for bloc in args.roles.split("|"):
            morceaux = bloc.split(":", 2)
            if len(morceaux) != 3:
                raise SystemExit("--roles : attendu 'nom:provider:role', recu %r" % bloc)
            participants.append((morceaux[0], morceaux[1], morceaux[2]))
    t0 = time.time()
    result = asyncio.run(run_debate(objectif, contrainte, participants,
                                    args.rounds, latent=args.latent))
    _post_and_doc(result, objectif)
    result["elapsed_s"] = round(time.time() - t0, 1)
    try:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        # Capsule cognitive a cote du resultat (2026-09-28) : ce que recoit une boite noire.
        try:
            print("capsule :", ecrire_capsule(result, args.out))
        except Exception as exc:  # noqa: BLE001 -- la capsule ne fait jamais echouer le debat
            print("capsule NON ecrite :", type(exc).__name__)
    except Exception:  # noqa: BLE001
        pass
    print(json.dumps({
        "ok": True,
        "elapsed_s": result["elapsed_s"],
        "turns": len(result["transcript"]),
        "ok_turns": sum(1 for t in result["transcript"] if t["ok"]),
        "intents": len(result["captured_intents"]),
        "posted_to": result.get("posted_to"),
        "doc": result.get("doc"),
    }, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
