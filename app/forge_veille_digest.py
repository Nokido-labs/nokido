# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ : cognition / metacognition (organe)

ORGANE : DIGEST -> SUGGEST — « tirer les leçons de ce qu'on vient d'apprendre ».

Le pipeline veille s'arretait a `store` : les documents entraient en biblio/RAG et
AUCUN organe ne les croisait avec l'anatomie et la roadmap pour en tirer des
ameliorations (demande owner 2026-07-22 : « ca devrait etre automatique »).
Jumeau inverse de forge_epistemic_veille (lui : gap de savoir -> declenche une
veille ; ici : savoir fraichement digere -> suggestions d'evolution).

Anti-dup verifie 2026-07-22 : forge_ssot_maintainer mine le blackboard (pas
biblio), forge_skill_curator digere les traces (pas biblio), le hook topics de
forge_biblio_worker etiquette sans suggerer. Personne ne fait ce pont.

Sorties (sobres, hors write-funnel blackboard — la promotion en FACT_PROPOSED
reste un geste d'agent apres lecture) :
  - table `veille_digest_suggestions` (dedup par hash suggestion+organe)
  - rapport humain `sandbox/veille_digest_report.md` (append, horodate)

LLM 100 % LOCAL (Ollama, pattern _extract_topics de forge_biblio_worker).

CLI :
    LAFORGE_PYTHON app/forge_veille_digest.py --backfill [--limit 400] [--since 2026-01-01]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("Nokido.VeilleDigest")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.environ.get("LAFORGE_DB_PATH", str(ROOT / "RAG" / "embeddings.db"))
REPORT = ROOT / "sandbox" / "veille_digest_report.md"
ORGAN_MAP = ROOT / "sandbox" / "workspace" / "organ_map_full.json"

DIGEST_HOST = os.environ.get("LAFORGE_DIGEST_HOST",
                             os.environ.get("LAFORGE_TOPIC_HOST", "http://127.0.0.1:11434"))
# Decision owner 2026-08-31 : la matiere biblio est jugee SENSIBLE par le DLP du
# pare-feu (mesure : « DLP: 2 donnees sensibles detectees » sur les lots cloud),
# et le pare-feu a raison — on ne l'affaiblit pas. Le chemin biblio est donc
# LOCAL, et le modele par defaut doit EXISTER : `laforge-qwen` etait une
# reference fantome, absente des 16 modeles servis, qui rendait le secondaire
# structurellement MODEL_UNAVAILABLE.
DIGEST_MODEL = (os.environ.get("LAFORGE_DIGEST_MODEL")
                or os.environ.get("LAFORGE_TOPIC_MODEL")
                or "qwen2.5:latest")
BATCH = int(os.environ.get("LAFORGE_DIGEST_BATCH", "10"))

# CONTRAT PROVIDER (decision owner 2026-08-31) : Groq PRIMAIRE, Ollama SECONDAIRE.
# L'ordre est explicite et le repli est TRACE : `choisir_provider` rend le verdict
# de chaque fournisseur consulte, si bien qu'un digest servi par le secondaire ne
# peut pas passer pour un digest servi par le primaire.
# groq (free, primaire) -> openrouter_free (routeur :free d'OpenRouter, cloud de
# repli GRATUIT quand groq est 429/quota) -> ollama (local, dernier recours lent).
# openrouter_free est le remplacant VIVANT du pool :free (slugs individuels
# retires) : il choisit un modele gratuit cote serveur, rien n'est code en dur.
# Plan Free = 50 req/jour : c'est un REPLI, pas un primaire.
ORDRE_PROVIDERS = ("groq", "openrouter_free", "ollama")
MODELE_GROQ = "openai/gpt-oss-120b"   # palier gratuit ; mesure 2026-08-31 : llm_fails=0
_SANTE_ENDPOINTS = ROOT / "sandbox" / "endpoint_health_last.json"
_SANTE_TTL_S = 900.0
_SONDE_LOCALE_TIMEOUT_S = 6.0

# Invariant anti-echec-muet (paye le jour meme de la creation : backfill
# job_79f34be7a9a5 = 40 lots, 0 suggestion, rc=0 — TOUS les appels LLM
# timeoutaient et l'echec etait avale lot par lot).
_LLM_FAILS = 0
# La DERNIERE cause d'echec, en clair. Un compteur dit COMBIEN, jamais POURQUOI :
# mesure 2026-08-31, les 51 appels biblio de l'historique n'echouaient pas sur le
# modele mais sur le pare-feu de Nokido (« DLP: 2 donnees sensibles detectees »),
# dont le refus etait recu comme une reponse ordinaire sans JSON. Quarante jours
# de « la veille ne produit rien » pour une chaine de refus jamais affichee.
_LLM_DERNIERE_ERREUR = ""
# Suggestions ECARTEES parce que leur organe sortait de la nomenclature. Compte,
# et non silence : une contrainte qu'on n'observe pas reste une suggestion.
_ORGANES_REJETES = 0
_ORGANES_NULS = 0

# Fallback si le census n'est pas lisible : domaines stables de l'anatomie.
_FALLBACK_ORGANS = [
    "rag/memoire", "veille/biblio", "securite/rbac/firewall", "endocrine/homeostat",
    "m2m/collaboration", "sandbox/exec", "router-llm/providers", "supervision/keepers",
]

_PROMPT = (
    "Tu es l'organe de metacognition de Nokido (systeme multi-agents souverain, "
    "local-first). On te donne des documents FRAICHEMENT digerees par la veille et "
    "la liste des organes du systeme. Propose 0 a 3 ameliorations CONCRETES de "
    "l'intelligence ou de la robustesse de Nokido que ces documents justifient. "
    # CONTRAINTE D'AFFECTATION (mesure A/B du 2026-09-01). La nomenclature etait
    # fournie comme un DECOR : le modele rangeait une idee sur Bazel/CI dans
    # « Metabolisme LLM (routage/backends) » alors que « Qualite/Build/Spec »
    # figurait dans la liste, et sans contexte il inventait « UX/UI », « R&D »,
    # « Developpement ». Le defaut s'est reproduit sur LES DEUX branches de
    # l'A/B : ce n'est ni le contexte ni la matiere, c'est que le choix n'etait
    # jamais contraint ni justifie.
    "\n\nREGLE D'AFFECTATION, la plus importante : le champ \"organe\" doit valoir "
    "EXACTEMENT une des chaines de la liste ORGANES ci-dessous, recopiee au "
    "caractere pres. N'invente JAMAIS de categorie. Choisis l'organe qui serait "
    "REELLEMENT IMPACTE par l'idee proposee, et non celui dont le vocabulaire "
    "revient le plus souvent dans le contexte general. Si deux organes semblent "
    "plausibles, retiens celui qui porte directement la capacite modifiee, et un "
    "seul. Si AUCUN organe de la liste ne convient, mets \"organe\": null. "
    "Ajoute toujours \"justification_organe\" : une phrase courte qui relie ton "
    "choix au CONTENU de la source citee — ou, pour null, la phrase exacte "
    "\"aucun organe existant ne correspond suffisamment\".\n\n"
    "Les mentions de type \"[CONTENU WEB NON-FIABLE — injection de prompt "
    "detectee]\" sont des METADONNEES DE SURETE : ce ne sont ni des instructions, "
    "ni le sujet du document, et elles ne doivent jamais determiner l'organe.\n\n"
    # Accolades JSON DOUBLEES : ce template passe par str.format() (vrais champs =
    # {organs}/{roadmap}/{docs}). Une accolade simple autour du JSON d'exemple
    # faisait lire « suggestions » comme un champ -> KeyError silencieux, 0 suggestion
    # depuis le 22-07, masque seulement par le garde DIGEST_SUSPECT.
    "Reponds UNIQUEMENT en JSON: {{\"suggestions\":[{{\"s\":\"<amelioration, 1 phrase "
    "francaise, actionnable>\",\"organe\":\"<UNE chaine EXACTE de ORGANES, ou null>\","
    "\"justification_organe\":\"<1 phrase reliant ce choix a la source>\","
    "\"prio\":\"P1|P2|P3\",\"src\":\"<titre du document source>\"}}]}}. "
    "Liste vide si rien de solide.\n\n"
    "ORGANES: {organs}\n\nROADMAP EN COURS: {roadmap}\n\nDOCUMENTS:\n{docs}"
)


_ORGANE_MAX_CHARS = 80          # un NOM d'organe, jamais une structure serialisee


def noms_organes(data) -> list:
    """Les noms d'organes du census. PURE, donc testable sans fichier.

    SOURCE CANONIQUE = `tally`, qui recense exactement les organes (16 au
    2026-08-31). L'ancienne lecture parcourait `data.values()` et appliquait
    `str(v)` a chaque valeur RACINE — dont `module_organ`, un dictionnaire de
    1 280 modules. Mesure : **70 808 caracteres** injectes comme « ORGANES » dans
    chaque prompt biblio, pour 540 caracteres de matiere.

    Ce seul defaut explique quatre symptomes tenus jusque-la pour distincts : le
    `413 Payload Too Large` de Groq, les refus DLP (c'est la carte interne du
    systeme qui partait au cloud, pas les articles), les 51 appels historiques
    sans une seule suggestion, et l'impossibilite de tester la voie locale.
    """
    if not isinstance(data, dict):
        return []
    tally = data.get("tally")
    if isinstance(tally, dict) and tally:
        noms = [str(k) for k in tally]
    else:
        # Schema anterieur : les organes se deduisent des modules eux-memes.
        mo = data.get("module_organ")
        source = mo if isinstance(mo, dict) else data
        noms = [str(v.get("organ")) for v in source.values()
                if isinstance(v, dict) and v.get("organ")]
    # GARDE DE FORME. Un nom d'organe est court et ne contient pas de structure.
    # Sans elle, le PROCHAIN changement de schema reinjecte silencieusement un
    # dictionnaire serialise dans le prompt — la panne exacte qu'on repare ici.
    return sorted({n for n in noms
                   if n and len(n) <= _ORGANE_MAX_CHARS and "{" not in n})


def organes_valides(organs: str) -> list:
    """La nomenclature, telle qu'elle a ete ENVOYEE au modele. PURE.

    On re-derive la liste de la chaine du prompt plutot que de relire le census :
    valider contre une autre source que celle affichee au modele, c'est lui
    reprocher un choix qu'on ne lui a pas propose.
    """
    return [o.strip() for o in (organs or "").split(",") if o.strip()]


def valider_organe(propose, valides: list) -> tuple:
    """(organe, etat) — etat vaut RETENU, NUL ou HORS_LISTE. PURE.

    Mesure A/B du 2026-09-01, reproduite sur les DEUX branches : le modele
    rangeait Bazel/CI dans « Metabolisme LLM (routage/backends) » quand
    « Qualite/Build/Spec » lui etait fourni, et sans contexte il inventait
    « UX/UI », « R&D », « Developpement ». La nomenclature etait un decor.

    On tolere la casse et les espaces — un ecart de frappe n'est pas une
    invention — mais AUCUN rapprochement approximatif : deviner l'organe voulu
    reviendrait a ajouter le classifieur que ce chantier refuse d'ecrire.
    """
    if propose is None or (isinstance(propose, str) and not propose.strip()):
        return (None, "NUL")
    txt = str(propose).strip()
    if txt.lower() in ("null", "none", "aucun", "?"):
        return (None, "NUL")
    for v in valides:
        if txt.casefold() == v.casefold():
            return (v, "RETENU")          # on rend la forme CANONIQUE
    return (txt, "HORS_LISTE")


def _organs() -> str:
    try:
        data = json.loads(ORGAN_MAP.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - census absent/illisible = repli
        # Le DIRE : un repli muet se lit comme un census a jour.
        logger.warning("census d'organes ILLISIBLE (%s) — repli sur la liste stable",
                       type(exc).__name__)
        return ", ".join(_FALLBACK_ORGANS)
    noms = noms_organes(data)
    return ", ".join(noms[:24]) if noms else ", ".join(_FALLBACK_ORGANS)


def _roadmap() -> str:
    try:
        doc = json.loads((ROOT / "docs" / "roadmap_state.json").read_text(encoding="utf-8"))
        return json.dumps(doc, ensure_ascii=False)[:600]
    except Exception:  # noqa: BLE001
        return "(roadmap indisponible)"


def tag_complet(nom: str) -> str:
    """`qwen2.5` et `qwen2.5:latest` designent le MEME modele chez ollama.

    Mesure 2026-08-31, et c'est une erreur que j'ai commise moi-meme : le
    catalogue rend `laforge-qwen:latest`, la config demandait `laforge-qwen`, et
    la comparaison de chaines exactes a conclu « modele ABSENT » sur un modele
    parfaitement present. Un comparateur qui ignore la convention de tag fabrique
    des MODEL_UNAVAILABLE faux — et un garde qui crie a faux se fait desarmer.
    """
    nom = (nom or "").strip()
    return (nom + ":latest") if (nom and ":" not in nom) else nom


def etat_provider(nom: str, sante: dict | None, sonde_locale: dict | None = None,
                  modele_local: str = "") -> tuple:
    """(etat, modele, raison) pour UN fournisseur. PURE : ni reseau, ni fichier.

    CINQ etats, et la distinction qui compte est INCONNU vs INDISPONIBLE. Le
    releve de sante partage range dans `"-"` ce que sa sonde n'a PAS PU mesurer
    (timeout, refus reseau) -- `forge_endpoint_monitor.probe` ne produit cette
    valeur que depuis son `except` generique. Lire `"-"` comme une panne est ce
    qui a fait abstenir la boucle SEPT fois de suite le 2026-08-31 sur un Ollama
    parfaitement vivant : « je n'ai pas pu regarder » etait devenu « c'est mort ».

    SERVICE_UP / API_READY / MODEL_READY restent SEPARES pour le local, parce
    qu'ils mentent l'un pour l'autre : mesure du meme jour, le service tournait,
    le port ecoutait, `/api/tags` rendait 200 -- et `laforge-qwen`, le modele que
    la config reclame, etait absent des douze modeles servis.
    """
    nom = str(nom or "").strip()
    if nom == "ollama":
        s = sonde_locale or {}
        if s.get("api") is None:
            return ("UNKNOWN", modele_local,
                    "ollama NON SONDE — absence de mesure, pas un verdict de panne")
        if not s.get("api"):
            return ("API_UNAVAILABLE", modele_local,
                    "ollama injoignable (%s)" % str(s.get("raison") or "?")[:70])
        catalogue = s.get("catalogue")
        if catalogue is None:
            return ("UNKNOWN", modele_local, "catalogue ollama ILLISIBLE")
        _voulu = tag_complet(modele_local)
        if _voulu not in {tag_complet(x) for x in catalogue}:
            return ("MODEL_UNAVAILABLE", modele_local,
                    "modele %s absent du catalogue (%d servis)"
                    % (modele_local, len(catalogue)))
        residents = s.get("residents")
        if residents is None:
            return ("UNKNOWN", modele_local, "modeles residents ILLISIBLES")
        if _voulu not in {tag_complet(x) for x in residents}:
            # PRESENT n'est pas PRET. Un modele au catalogue mais non charge coute
            # son chargement au premier appel : mesure 2026-08-31, >55 s pour un 7B,
            # quand le tick de la boucle autonome vaut 60 s. Le declarer pret, c'est
            # rendre la sonde responsable de la panne qu'elle est censee eviter.
            return ("MODEL_COLD", modele_local,
                    "modele %s present mais NON CHARGE (chargement mesure >55 s, "
                    "au-dela d'un tick de 60 s)" % modele_local)
        return ("READY", modele_local, "%s charge et resident" % modele_local)
    if not isinstance(sante, dict):
        return ("UNKNOWN", "", "releve de sante indisponible")
    par_statut = sante.get("par_statut") or {}
    # openrouter_free est servi par l'endpoint 'openrouter' du releve partage
    # (le routeur choisit le modele par requete -> on ne sonde pas un modele).
    nom_sante = "openrouter" if nom == "openrouter_free" else nom
    if nom == "groq":
        modele_ready = MODELE_GROQ
    elif nom == "openrouter_free":
        modele_ready = "openrouter/free"
    else:
        modele_ready = ""
    for statut, noms in par_statut.items():
        if nom_sante in (noms or []):
            st = str(statut).strip()
            if st in ("200", "201", "ok"):
                return ("READY", modele_ready,
                        "%s joignable (statut %s)" % (nom, st))
            if st == "-":
                return ("UNKNOWN", "",
                        "%s NON SONDE (la sonde elle-meme a echoue)" % nom)
            return ("API_UNAVAILABLE", "", "%s statut %s" % (nom, st))
    return ("UNKNOWN", "", "%s absent du releve de sante" % nom)


def choisir_provider(sante: dict | None, sonde_locale: dict | None = None,
                     ordre: tuple = ORDRE_PROVIDERS, modele_local: str = "") -> tuple:
    """(provider, modele, etat, essais). PURE.

    AUCUN repli silencieux : `essais` porte le verdict de chaque fournisseur
    consulte, dans l'ordre. Un digest servi par le secondaire le DIT, et un
    digest qui n'a pas eu lieu dit lequel a refuse et pourquoi.
    """
    essais = []
    _cache: dict = {}

    def _locale():
        """La sonde locale n'est evaluee que si un fournisseur LOCAL est consulte.

        `sonde_locale` accepte une valeur ou un CALLABLE. Le callable est ce qui
        evite de payer deux GET (jusqu'a 12 s bornees) a chaque tick quand le
        primaire distant repond : une sonde qu'on paie sans s'en servir est du
        temps pris au tick, exactement ce que ce chantier cherche a rendre.
        """
        if "v" not in _cache:
            _cache["v"] = sonde_locale() if callable(sonde_locale) else sonde_locale
        return _cache["v"]

    for nom in ordre:
        etat, modele, raison = etat_provider(
            nom, sante, sonde_locale=(_locale() if nom == "ollama" else None),
            modele_local=modele_local)
        essais.append({"provider": nom, "etat": etat, "modele": modele,
                       "raison": raison})
        if etat == "READY":
            return (nom, modele, etat, essais)
    # Aucun pret. On ne resume PAS les refus en un mot : deux fournisseurs peuvent
    # refuser pour des raisons de natures differentes (API muette d'un cote,
    # modele absent de l'autre), et c'est la raison qui dicte le remede.
    return ("", "", (essais[-1]["etat"] if essais else "UNKNOWN"), essais)


def statut_abstention(essais: list) -> str:
    """SKIPPED_MODEL_UNAVAILABLE ou SKIPPED_PROVIDER_UNAVAILABLE. PURE.

    Le refus qui porte sur le MODELE est le plus SPECIFIQUE : il se corrige dans
    la config, quand un refus d'API se corrige sur le service. Les confondre
    enverrait chercher la panne du cote d'un service qui va bien.
    """
    etats = {str(e.get("etat")) for e in (essais or [])}
    if etats & {"MODEL_UNAVAILABLE", "MODEL_COLD"}:
        return "SKIPPED_MODEL_UNAVAILABLE"
    return "SKIPPED_PROVIDER_UNAVAILABLE"


def statut_digest(lots_ok: int, lots_ko: int) -> str:
    """DIGEST_OK / DIGEST_PARTIAL / DIGEST_FAILED. PURE.

    Le verdict porte sur les LOTS, pas sur les suggestions : un lot qui aboutit
    sans rien proposer est un succes (« rien a dire »), un lot qui echoue est un
    echec meme si un autre lot a produit dix suggestions.
    """
    if lots_ko and lots_ok:
        return "DIGEST_PARTIAL"
    if lots_ko:
        return "DIGEST_FAILED"
    return "DIGEST_OK"


def sante_endpoints(chemin=None, ttl: float = _SANTE_TTL_S, maintenant=None,
                    avec_motif: bool = False):
    """Le releve de sante partage, ou None. None = INCONNU, jamais « en panne ».

    `avec_motif=True` rend `(releve, motif)`. Le motif existe parce que trois
    causes tres differentes produisent le meme None -- fichier ABSENT, fichier
    ILLISIBLE, releve PERIME -- et qu'elles n'appellent pas le meme remede :
    la premiere dit que la sonde n'a jamais tourne, la troisieme qu'elle ne
    tourne plus. Les confondre, c'est refaire l'erreur que ce chantier corrige.
    """
    import time as _t
    p = chemin or _SANTE_ENDPOINTS
    try:
        brut = Path(p).read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return (None, "releve de sante ABSENT (%s)" % Path(p).name) if avec_motif else None
    try:
        d = json.loads(brut)
    except Exception as exc:  # noqa: BLE001
        motif = "releve de sante ILLISIBLE (%s)" % type(exc).__name__
        return (None, motif) if avec_motif else None
    age = (maintenant if maintenant is not None else _t.time()) - float(d.get("ts") or 0)
    if age > ttl:
        motif = "releve de sante PERIME (%.0f min)" % (age / 60)
        return (None, motif) if avec_motif else None
    return (d, "") if avec_motif else d


def sonde_ollama(hote: str = "", timeout: float = _SONDE_LOCALE_TIMEOUT_S) -> dict:
    """{'api', 'catalogue', 'residents', 'raison'} — None partout ou l'on n'a pas vu.

    BORNEE et sans effet de bord : deux GET qui ne chargent AUCUN modele. Mesure
    2026-08-31 apres remise en route : `/api/tags` 2,9 ms, `/api/ps` 269 ms.

    On ne lance deliberement PAS de generation d'essai. Sur un modele froid elle
    coute plus de 55 s, soit davantage qu'un tick de la boucle : la sonde
    deviendrait la panne qu'elle cherche a detecter. `/api/ps` repond a la meme
    question — « une requete minimale passerait-elle MAINTENANT » — pour 269 ms.
    """
    base = (hote or DIGEST_HOST).rstrip("/")
    out = {"api": None, "catalogue": None, "residents": None, "raison": ""}

    def _get(chemin: str):
        req = urllib.request.Request(base + chemin,
                                     headers={"User-Agent": "nokido-digest-sonde"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    try:
        d = _get("/api/tags")
        out["api"] = True
        out["catalogue"] = [str(m.get("name") or "") for m in (d.get("models") or [])]
    except Exception as exc:  # noqa: BLE001
        out["api"] = False
        out["raison"] = "%s: %s" % (type(exc).__name__, str(exc)[:60])
        return out
    try:
        d = _get("/api/ps")
        out["residents"] = [str(m.get("name") or "") for m in (d.get("models") or [])]
    except Exception as exc:  # noqa: BLE001
        # `residents` reste None : on n'a pas vu, on ne dira pas « aucun charge ».
        out["raison"] = "residents: %s" % type(exc).__name__
    return out


# BUDGET DE MATIERE. Mesures 2026-09-01 qui le contraignent, dans cet ordre :
#   - chunk median = 2 071 chars (p25 2 045, p75 2 101) : l'unite naturelle ;
#   - LLAMACPP_N_CTX = 4096 tokens ~ 16 000 chars pour prompt ET reponse ;
#   - contexte fixe du prompt = 1 582 chars.
# D'ou un plafond par LOT, reparti entre ses documents : a 10 documents (BATCH)
# chacun recoit 1 200 chars, a 3 documents il recoit les 2 000 pleins. Ce n'est
# pas une valeur choisie au hasard, et elle reste a re-mesurer si le contexte du
# fournisseur change — un lot de 10 ne peut PAS porter davantage sous 4096.
_MATIERE_BUDGET_DOC = 2000
_MATIERE_BUDGET_LOT = 12000
_MATIERE_MIN_CHARS = 400          # sous ce seuil, la matiere ne vaut pas le resume

# Marqueurs de FORME, tous releves sur les chunks reels du 2026-09-01. On ne
# devine pas la structure : on ecarte ce qu'on a MESURE comme non substantiel.
_CHROME_WEB = ("Bibliographic", "Recommenders and Search", "Influence Flower",
               "ScienceCast", "Connected Papers", "alphaXiv", "Litmaps", "DagsHub",
               "Current browse context", "References & Citations", "arXivLabs",
               "What is the Explorer?", "Which authors of this paper")
_FRONT_MATTER = ("Noname manuscript No.", "will be inserted by the editor",
                 "CONTENU WEB NON-FIABLE", "E-mail:", "@queensu.ca")


def rang_chunk(texte: str) -> int:
    """0 = resume, 1 = corps, 2 = ecarte. PURE, donc testable sans base.

    Trois rangs et pas deux : le resume est ce qu'un digest veut LIRE EN PREMIER,
    le corps vient ensuite, et le reste n'est pas de la connaissance. Mesure du
    2026-09-01 sur les trois documents de l'experience : sur la page `abs`
    d'arXiv, **la moitie des caracteres** est de la navigation (« Bibliographic
    Explorer », « What is GotitPub? ») ; sur le PDF, les deux premiers chunks
    sont la page de garde et les adresses des auteurs. Envoyer cela au modele,
    c'est exactement ce qui lui a fait rendre `[]`.
    """
    t = texte or ""
    if not t.strip():
        return 2
    bas = t.lower()
    if sum(1 for m in _CHROME_WEB if m in t) >= 2:
        return 2
    # LE RESUME PASSE AVANT LE REJET DE FRONT-MATTER, et l'ordre a ete corrige
    # apres mesure : le chunk 0 d'un PDF porte la page de garde ET le resume dans
    # le meme bloc. Tester le front-matter d'abord jetait le resume de Bazel avec
    # « Noname manuscript No. » -- on perdait la seule phrase qui dit de quoi
    # parle l'article. Un chunk mixte vaut mieux qu'un document sans resume.
    if "abstract" in bas:
        return 0
    if any(m in t for m in _FRONT_MATTER):
        return 2
    # Bibliographie : une densite de « et al. » / de DOI que le corps n'atteint pas.
    if t.count("et al.") >= 6 or bas.count("doi.org") >= 4:
        return 2
    return 1


def selectionner_matiere(chunks: list, budget_chars: int) -> str:
    """`chunks` = [(sequence_id, texte)] -> texte borne. PURE et DETERMINISTE.

    Le determinisme n'est pas cosmetique : sans lui, deux digests de la meme
    matiere ne seraient pas comparables, et la faiblesse de la dedup de sortie
    (mesuree : neuf fichiers rejoues rendent neuf autres formulations) deviendrait
    impossible a distinguer d'une variation d'entree.

    Le resume passe devant, le corps suit dans l'ordre du document, et le rendu
    final est re-trie par `sequence_id` pour que le modele lise un texte suivi.
    """
    if budget_chars <= 0:
        return ""
    classes = [(rang_chunk(t), int(s if s is not None else i), t)
               for i, (s, t) in enumerate(chunks or [])]
    retenus, total = [], 0
    for rang in (0, 1):
        for _r, seq, t in sorted((x for x in classes if x[0] == rang),
                                 key=lambda x: x[1]):
            # Le separateur de jointure COMPTE dans le budget. Sans lui, la sortie
            # depassait d'exactement le nombre de morceaux -- un debordement d'un
            # caractere qui, sur un contexte de 4096 tokens deja serre, n'est pas
            # une coquette : c'est le test qui l'a trouve, pas une relecture.
            sep = 1 if retenus else 0
            reste = budget_chars - total - sep
            if reste <= 0:
                break
            morceau = t[:reste]
            if not morceau:
                continue
            retenus.append((seq, morceau))
            total += len(morceau) + sep
    retenus.sort(key=lambda x: x[0])
    return "\n".join(m for _, m in retenus)


def matiere_document(conn, url: str, budget_chars: int = _MATIERE_BUDGET_DOC) -> str:
    """Le CORPS du document tel que Nokido le possede DEJA. '' si rien.

    LIAISON MESUREE, pas supposee : `rag_chunks.source == biblio_raw.url`, egalite
    exacte sur l'index `idx_rag_source` (lookup a 0,00 s). Les trois autres formes
    candidates testees le 2026-09-01 — identifiant `arxiv.org_pdf_...`, URL
    `/pdf/`, prefixe de la description — rendent ZERO ligne.

    POURQUOI CETTE FONCTION EXISTE : le digest lisait `description[:180]`, qui
    contient du front-matter (titre, identifiant arXiv, noms d'auteurs). Les
    memes documents portaient 142 077 / 5 163 / 4 635 caracteres de vraie matiere,
    deja collectee, deja vectorisee, deja active. Aucun crawl n'est ajoute ici :
    on branche le digest sur ce qui est deja en base.
    """
    url = (url or "").strip()
    if not url:
        return ""
    try:
        rows = conn.execute(
            "SELECT sequence_id, text FROM rag_chunks "
            "WHERE source = ? AND COALESCE(active, 1) = 1 "
            "ORDER BY COALESCE(sequence_id, 0), id", (url,)).fetchall()
    except Exception as exc:  # noqa: BLE001
        # ILLISIBLE n'est pas VIDE : on le DIT, et l'appelant retombera sur le
        # resume en le sachant, au lieu de croire le document sans matiere.
        logger.warning("matiere RAG ILLISIBLE pour %s (%s)", url[:60], type(exc).__name__)
        return ""
    return selectionner_matiere([(r[0], r[1] or "") for r in rows], budget_chars)


def budget_par_document(n_documents: int) -> int:
    """Le budget d'UN document dans un lot de `n`. PURE."""
    if n_documents <= 0:
        return _MATIERE_BUDGET_DOC
    return max(_MATIERE_MIN_CHARS,
               min(_MATIERE_BUDGET_DOC, _MATIERE_BUDGET_LOT // n_documents))


def _ensure_curseur(conn) -> bool:
    """Pose `biblio_raw.digested_at` si absente. Idempotent.

    POURQUOI UNE COLONNE PLUTOT QUE `status` : `status` appartient a
    `forge_biblio_core.promote_entry`, qui maintient l'invariant « status=promoted
    <=> ligne dans bibliography ». Y ecrire 'digested' romprait cet invariant et
    effacerait l'information de promotion. Le curseur est une donnee du DIGEST :
    il vit dans sa propre colonne, additive et NULL par defaut, donc invisible
    aux quinze modules qui lisent deja cette table.
    """
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(biblio_raw)")}
    except Exception:  # noqa: BLE001
        return False
    if "digested_at" in cols:
        return True
    try:
        conn.execute("ALTER TABLE biblio_raw ADD COLUMN digested_at TEXT")
        conn.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        # Le dire : sans curseur la selection reste une FENETRE sur le haut de la
        # pile, et le backlog ne se videra a aucune cadence.
        logger.warning("curseur digested_at NON pose (%s) — le backlog ne se videra pas",
                       type(exc).__name__)
        return False


def extraire_json(txt: str):
    """Le PREMIER JSON top-level valide du texte, ou None. PURE.

    L'ancienne lecture prenait du PREMIER `{` au DERNIER `}`. Mesure 2026-09-01 :
    le modele local rend un objet parfaitement forme, parfois suivi d'un second,
    et l'intervalle le plus large en contenait alors DEUX -> `JSONDecodeError:
    Extra data` -> DIGEST_FAILED sur une reponse pourtant valide. Un faux echec
    qui bloquait le curseur.

    `raw_decode` s'arrete a la fin de la premiere valeur : on essaie chaque
    position d'ouverture et on rend la premiere qui decode. Cela couvre l'objet
    nu, la liste nue, la cloture markdown, et le texte avant ou apres — sans
    aucune heuristique sur la forme du texte.
    """
    t = txt or ""
    dec = json.JSONDecoder()
    for i, ch in enumerate(t):
        if ch not in "{[":
            continue
        try:
            val, _fin = dec.raw_decode(t, i)
        except ValueError:
            continue          # muet-ok : cette ouverture n'amorce pas un JSON
        return val
    return None


def normaliser_reponse(val) -> dict:
    """Un modele rend tantot `{"suggestions": [...]}`, tantot la liste nue. PURE.

    La liste nue est le cas MESURE le 2026-09-01 : sur une matiere pauvre, le
    modele rendait `[]`, ce que l'ancien chemin comptait comme un echec de lot.
    « Rien a dire » est un digest REUSSI sans suggestion, pas une panne — les
    confondre faisait rejouer indefiniment une matiere deja lue.
    """
    if isinstance(val, dict):
        return val
    if isinstance(val, list):
        return {"suggestions": [x for x in val if isinstance(x, dict)]}
    return {}


def _hub_json(provider: str, prompt: str) -> dict:
    """Chemin QUALITE (directive owner 2026-07-22) : router gouverne du hub
    (forge_agent_proxy.ask = firewall + tracking + CCR) au lieu d'Ollama brut.
    Le jugement/synthese exige un modele de qualite — mesure : 40 lots au 7B
    local = 0 suggestion (TimeoutError avale)."""
    import asyncio
    import sys as _s

    app = str(ROOT / "app")
    if app not in _s.path:
        _s.path.insert(0, app)
    from nokido_agent.app.forge_agent_proxy import ask

    res = asyncio.run(ask(provider, prompt, rag_context=False, raw=True,
                          max_tokens=700, timeout=90))
    if not res.get("ok"):
        raise RuntimeError("hub ask KO (%s): %s" % (provider, str(res.get("error"))[:120]))
    txt = res.get("text") or ""
    val = extraire_json(txt)
    if val is None:
        # MONTRER CE QU'ON A RECU. « pas de JSON » sans la reponse a laisse le
        # digest biblio echouer en silence depuis le 2026-07-22 : 51 appels, 0
        # suggestion, lus a tort comme « le modele n'avait rien a dire » alors que
        # chaque appel echouait -- c'etait le pare-feu qui refusait le payload.
        raise ValueError("pas de JSON dans la reponse %s (%d chars) : %r"
                         % (provider, len(txt), txt[:220]))
    return normaliser_reponse(val)


def _llm_json(prompt: str, provider: str = "", modele: str = "") -> dict:
    provider = (provider or os.environ.get("LAFORGE_DIGEST_PROVIDER", "")).strip()
    if provider and provider != "ollama":
        return _hub_json(provider, prompt)
    body = json.dumps({
        "model": (modele or DIGEST_MODEL), "prompt": prompt, "format": "json",
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 512},
    }).encode()
    req = urllib.request.Request(f"{DIGEST_HOST}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        brut = json.loads(r.read()).get("response", "") or ""
    val = extraire_json(brut)
    if val is None:
        raise ValueError("pas de JSON dans la reponse ollama (%d chars) : %r"
                         % (len(brut), brut[:220]))
    return normaliser_reponse(val)


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS veille_digest_suggestions (
            id TEXT PRIMARY KEY, suggestion TEXT NOT NULL, organe TEXT, prio TEXT,
            sources TEXT, created_at TEXT NOT NULL)"""
    )


def digest_batch(entries: list[dict], organs: str, roadmap: str,
                 extrait_max: int = 180, provider: str = "",
                 modele: str = "") -> list[dict]:
    """Un lot de documents -> suggestions filtrees (peut etre vide).

    `extrait_max` : 180 convient a la voie BIBLIO, ou la description EST deja un
    resume d'article. Il ruine la voie DEPOTS -- mesure du 2026-08-30 : juge sur
    180 caracteres d'un fichier de code, le modele ne peut que paraphraser son
    NOM, et rend des suggestions qui visent le depot observe (« uniformiser le
    prefixe codex- sur les crates ») au lieu de ce que Nokido doit en tirer.
    """
    docs = "\n".join(
        "- %s — %s" % ((e.get("title") or "")[:110],
                       (e.get("description") or "")[:extrait_max])
        for e in entries
    )
    titres = ", ".join((e.get("title") or "")[:70] for e in entries)
    try:
        parsed = _llm_json(_PROMPT.format(organs=organs, roadmap=roadmap, docs=docs),
                           provider=provider, modele=modele)
    except Exception as exc:  # noqa: BLE001 - un lot KO ne tue pas le backfill
        global _LLM_FAILS, _LLM_DERNIERE_ERREUR
        _LLM_FAILS += 1
        _LLM_DERNIERE_ERREUR = "%s: %s" % (type(exc).__name__, str(exc)[:300])
        logger.warning("digest lot KO: %s", _LLM_DERNIERE_ERREUR)
        return []
    global _ORGANES_REJETES, _ORGANES_NULS
    valides = organes_valides(organs)
    out = []
    for s in parsed.get("suggestions", []):
        txt = str(s.get("s") or "").strip()
        if not (15 <= len(txt) <= 300):
            continue
        organe, etat = valider_organe(s.get("organe"), valides)
        if etat == "HORS_LISTE":
            # ECARTEE, et COMPTEE. Accepter en repliant sur `null` masquerait la
            # violation et rendrait la mesure de l'affectation impossible.
            _ORGANES_REJETES += 1
            logger.warning("organe hors nomenclature ecarte : %r", organe[:60])
            continue
        if etat == "NUL":
            _ORGANES_NULS += 1
        # La provenance est DETERMINISTE : les titres du lot sont connus du code.
        # La demander au modele donnait `src: None` sur 6 suggestions sur 6 --
        # une connaissance sans lien vers sa source n'est pas verifiable.
        out.append({
            "suggestion": txt,
            "organe": organe if organe else "?",
            # PREUVE MINIMALE D'AFFECTATION. Non persistee (aucune colonne ajoutee) :
            # elle vit dans le resultat et dans le rapport, ou elle sert a juger le
            # choix au lieu de le croire.
            "justification_organe": str(s.get("justification_organe") or "").strip()[:300],
            "prio": s.get("prio") if s.get("prio") in ("P1", "P2", "P3") else "P3",
            "src": (str(s.get("src") or "").strip() or titres)[:120],
        })
    return out[:3]


def backfill(limit: int = 400, since: str = "", ids: list | None = None,
             provider: str = "", modele: str = "", marquer: bool = True) -> dict:
    if provider:
        etat, essais = "FORCE", [{"provider": provider, "etat": "FORCE",
                                  "modele": modele, "raison": "impose par l'appelant"}]
    else:
        provider, modele, etat, essais = choisir_provider(
            sante_endpoints(), sonde_ollama, modele_local=DIGEST_MODEL)
        if not provider:
            # ABSTENTION AVANT toute lecture de base et tout appel LLM. Rien n'est
            # marque, la matiere reste entiere, le tour suivant la reprend. C'est
            # l'inverse exact du chemin « provider KO -> appel aveugle -> 120 s ».
            return {"statut": statut_abstention(essais), "provider": "", "model": "",
                    "provider_state": etat, "essais": essais,
                    "documents": 0, "batches": 0, "success": 0, "failure": 0,
                    "suggestions_generated": 0, "new_suggestions": 0,
                    "docs": 0, "filtered_docs": 0, "docs_marques": 0,
                    "llm_fails": 0, "suspect": False, "report": str(REPORT)}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _ensure_table(conn)
    curseur = _ensure_curseur(conn)
    q = ("SELECT id, title, description, url, created_at FROM biblio_raw "
         "WHERE status IN ('reviewed','promoted','unverified')")
    args: list = []
    if curseur:
        # LE CURSEUR. Sans lui la requete rend TOUJOURS le haut de la pile
        # (`ORDER BY created_at DESC LIMIT`) : ce n'etait pas une file, c'etait une
        # fenetre fixe, et le backlog ne pouvait se vider a aucune cadence.
        q += " AND digested_at IS NULL"
    if since:
        q += " AND created_at >= ?"
        args.append(since)
    if ids:
        # PROVENANCE. `since` est une FENETRE DE TEMPS, pas un lien : il ramene
        # tout ce qui a ete ingere dans la meme periode, y compris par d'autres
        # chaines. `ids` restreint a la matiere d'UNE veille identifiee, ce qui
        # est la seule facon d'attribuer un digest -- et de savoir quoi reprendre
        # quand il echoue.
        q += " AND id IN (%s)" % ",".join("?" * len(ids))
        args.extend(str(i) for i in ids)
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    rows = [dict(r) for r in conn.execute(q, args).fetchall()]

    # Filter out product documentation from the digest
    def _is_product_doc(r: dict) -> bool:
        t = (r.get("title") or "").lower()
        d = (r.get("description") or "").lower()
        product_keywords = {
            "huggingface.co", "github.com", "lerobot", "documentation", "install",
            "installation", "quickstart", "tutorial", "dataset", "how-to",
            "api reference", "cli reference", "readme", "model hub", "hf-mirror",
            "pip install",
        }
        return any(kw in t or kw in d for kw in product_keywords)

    filtered_rows = [r for r in rows if not _is_product_doc(r)]

    organs, roadmap = _organs(), _roadmap()
    kept, seen_batches, lots_ok, lots_ko, a_marquer = [], 0, 0, 0, []
    depuis_rag = depuis_resume = 0
    for i in range(0, len(filtered_rows), BATCH):
        lot = filtered_rows[i:i + BATCH]
        seen_batches += 1
        # LE POINT DE LECTURE. Avant : `description[:180]`, c'est-a-dire la page
        # de garde du PDF. Apres : le corps du document, que Nokido possede deja.
        # Le repli sur le resume est EXPLICITE et compte : un document sans
        # matiere exploitable ne doit pas se confondre avec un document riche.
        _budget = budget_par_document(len(lot))
        for _e in lot:
            _m = matiere_document(conn, _e.get("url") or "", _budget)
            if len(_m) >= _MATIERE_MIN_CHARS:
                _e["description"] = _m
                depuis_rag += 1
            else:
                depuis_resume += 1
        _avant = _LLM_FAILS
        suggestions = digest_batch(lot, organs, roadmap, extrait_max=_budget,
                                   provider=provider, modele=modele)
        # `digest_batch` rend [] pour DEUX raisons opposees : le lot a echoue, ou
        # le modele n'avait rien a dire. Seul le compteur d'echecs les separe, et
        # c'est cette distinction qui autorise -- ou non -- a marquer le lot digere.
        if _LLM_FAILS == _avant:
            lots_ok += 1
            a_marquer.extend(str(r["id"]) for r in lot)
        else:
            lots_ko += 1
        for s in suggestions:
            h = hashlib.md5((s["suggestion"][:80] + s["organe"]).lower()
                            .encode("utf-8")).hexdigest()[:16]
            dup = conn.execute(
                "SELECT 1 FROM veille_digest_suggestions WHERE id=?", (h,)).fetchone()
            if dup:
                continue
            conn.execute(
                "INSERT INTO veille_digest_suggestions VALUES (?,?,?,?,?,?)",
                (h, s["suggestion"], s["organe"], s["prio"], s["src"],
                 datetime.now(tz=timezone.utc).isoformat(timespec="seconds")),
            )
            kept.append(s)
        conn.commit()

    # LE CURSEUR AVANCE ICI, et UNIQUEMENT sur les lots qui ont abouti. Un document
    # d'un lot en echec reste `digested_at IS NULL` et sera repris au tour suivant.
    marques = 0
    if marquer and curseur and a_marquer:
        _stamp = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        for k in range(0, len(a_marquer), 400):
            bloc = a_marquer[k:k + 400]
            conn.execute("UPDATE biblio_raw SET digested_at=? WHERE id IN (%s)"
                         % ",".join("?" * len(bloc)), [_stamp] + bloc)
            marques += len(bloc)
        conn.commit()

    stamp = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    lines = ["\n## Digest %s [%s %s] — %d docs (filtrés: %d), %d lots "
             "(ok %d / ko %d), %d suggestions générées, %d marqués digérés\n"
             % (stamp, provider, modele or "?", len(rows), len(filtered_rows),
                seen_batches, lots_ok, lots_ko, len(kept), marques)]
    for s in sorted(kept, key=lambda x: x["prio"]):
        lines.append("- **%s** [%s] %s _(src: %s)_\n"
                     % (s["prio"], s["organe"], s["suggestion"], s["src"]))
        if s.get("justification_organe"):
            lines.append("    - _organe justifié :_ %s\n" % s["justification_organe"])
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("a", encoding="utf-8") as f:
        f.writelines(lines)
    conn.close()
    # `suggestions_generated` N'EST PAS une mesure de connaissance : mesure du
    # 2026-08-31, deux passes sur les MEMES 9 fichiers ont rendu 9 + 9 lignes,
    # dont au moins cinq paires portant la meme idee sur la meme source, avec une
    # formulation differente. La dedup md5 ne voit pas une reformulation. Tant
    # qu'aucune dedup semantique n'est fiable, ce compteur compte des LIGNES.
    return {"statut": statut_digest(lots_ok, lots_ko),
            "provider": provider, "model": modele, "provider_state": etat,
            "essais": essais,
            "documents": len(filtered_rows), "batches": seen_batches,
            "success": lots_ok, "failure": lots_ko,
            "suggestions_generated": len(kept),
            "organes_rejetes": _ORGANES_REJETES, "organes_nuls": _ORGANES_NULS,
            "matiere_rag": depuis_rag, "matiere_resume": depuis_resume,
            "budget_par_doc": budget_par_document(min(len(filtered_rows), BATCH))
            if filtered_rows else 0,
            "docs_marques": marques, "curseur": bool(curseur),
            "docs": len(rows), "filtered_docs": len(filtered_rows),
            "new_suggestions": len(kept),   # compat lecteurs existants
            "llm_fails": _LLM_FAILS, "raison_echec": _LLM_DERNIERE_ERREUR,
            "suspect": bool(seen_batches and not kept),
            "report": str(REPORT)}


# Budget de payload pour la voie DEPOTS. Les fournisseurs gratuits plafonnent bas
# (Groq : 8 000 tokens/minute), et le contexte fixe pesait a lui seul ~59 000
# chars. Ces bornes sont ce qui rend le digest EXECUTABLE, pas un reglage de
# confort.
EXTRAIT_DEPOT = 700
ORGANS_MAX = 3500
ROADMAP_MAX = 1500
BATCH_DEPOT = 3


def entrees_depots(conn, limit: int = 60, depot: str = "") -> list[dict]:
    """Transforme les chunks de depots ingeres en entrees digestibles.

    REGRESSION CORRIGEE (mesure 2026-08-30) : `backfill` lit `biblio_raw`, donc
    la veille par CLONE n'atteignait jamais cet organe -- 116 620 chunks en
    `domain='sdk_gitingest'`, dont openai/codex et ShinkaEvolve, stockes et
    JAMAIS digeres. Doublement exclus, d'ailleurs : `_is_product_doc` ecarte
    « github.com » et « readme », si bien qu'un depot passe par biblio aurait
    ete filtre comme documentation produit.

    Le groupement se fait par SOURCE (un fichier = une entree) et non par chunk :
    mesure du jour, `config_tests.rs` pese 410 chunks a lui seul. Digerer chunk
    par chunk couterait 32 072 appels pour le seul codex, contre ~1 138 par
    fichier -- meme matiere, cout divise par 28.

    L'ordre de selection privilegie ce qui PORTE des lecons : contrats d'agent,
    prompts, politiques, doc. Mesure du jour : la doc ne represente que 1,1 % du
    corpus codex, et c'est d'elle qu'est sortie la seule lecon actionnable de la
    journee. Le volume est un mauvais guide de valeur.
    """
    q = ("SELECT source, COUNT(*) AS n, SUBSTR(GROUP_CONCAT(text, ' '), 1, 1800) AS extrait "
         "FROM rag_chunks WHERE domain='sdk_gitingest' ")
    args: list = []
    if depot:
        q += "AND source LIKE ? "
        args.append(f"{depot}/%")
    q += "GROUP BY source"
    rows = [dict(r) for r in conn.execute(q, args).fetchall()]

    def rang(src: str) -> tuple:
        """Ordre de lecture. MESURE 2026-08-30, et elle a corrige mon premier tri.

        J'avais mis README en rang 0. Resultat : le digest a lu du PACKAGING et
        rendu « automatiser le staging npm », « adopter une procedure de
        contribution » -- generique, et parfois destine au depot observe plutot
        qu'a Nokido. Un README dit comment INSTALLER ; il ne dit pas ce que le
        systeme decide.

        La seule lecon reellement actionnable tiree de codex ce jour-la venait de
        `codex-rs/prompts/templates/permissions/on_request.md` -- une politique
        d'approbation, qui a produit un correctif de securite reel sur
        `bash_guard`. Pour un depot d'AGENT, la substance est dans les prompts,
        les permissions et les politiques ; le README est du packaging.
        """
        s = (src or "").lower()
        nom = s.rsplit("/", 1)[-1]
        if ("/prompt" in s or "/permission" in s or "/polic" in s
                or "/instructions" in s or "system_prompt" in nom):
            return (0, s.count("/"))
        if nom in ("agents.md", "architecture.md", "design.md"):
            return (1, s.count("/"))
        if s.endswith((".md", ".rst", ".adoc")) and nom != "readme.md":
            return (2, s.count("/"))
        if nom == "readme.md":
            return (3, s.count("/"))
        return (4, s.count("/"))

    rows.sort(key=lambda r: rang(r["source"]))
    return [
        {"id": r["source"], "title": r["source"],
         "description": (r["extrait"] or "")[:EXTRAIT_DEPOT], "created_at": ""}
        for r in rows[:limit]
    ]


def backfill_depots(limit: int = 60, depot: str = "", provider: str = "",
                    modele: str = "") -> dict:
    """Digest de la voie CLONE, avec la meme table et la meme dedup que biblio.

    Meme contrat provider que `backfill` : la voie depots ne doit pas rester sur
    l'ancien chemin « env sinon Ollama brut », sinon un digest sur deux s'abstient
    pour des raisons que l'autre ne sait pas nommer.

    PAS DE CURSEUR ICI : le chantier du curseur porte sur `biblio_raw` (decision
    owner). `entrees_depots` reste donc une FENETRE sur les fichiers les mieux
    classes, et il faut le savoir avant de lire ses compteurs.
    """
    if provider:
        etat, essais = "FORCE", [{"provider": provider, "etat": "FORCE",
                                  "modele": modele, "raison": "impose par l'appelant"}]
    else:
        provider, modele, etat, essais = choisir_provider(
            sante_endpoints(), sonde_ollama, modele_local=DIGEST_MODEL)
        if not provider:
            return {"statut": statut_abstention(essais), "provider": "", "model": "",
                    "provider_state": etat, "essais": essais,
                    "documents": 0, "fichiers": 0, "batches": 0,
                    "success": 0, "failure": 0,
                    "suggestions_generated": 0, "new_suggestions": 0,
                    "llm_fails": 0, "suspect": False, "report": str(REPORT)}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _ensure_table(conn)
    rows = entrees_depots(conn, limit=limit, depot=depot)
    # Le contexte fixe DOMINE le payload : mesure du 2026-08-30, un lot de 8
    # fichiers a 1800 chars a produit 73 575 chars envoyes, soit ~59 000 chars
    # d'anatomie et de roadmap pour 14 400 chars de matiere -- et un refus 413
    # (24 177 tokens demandes pour une limite de 8 000). Ce n'est pas la matiere
    # qui sature, c'est le decor. On le borne, et on reduit la taille des lots.
    organs, roadmap = _organs()[:ORGANS_MAX], _roadmap()[:ROADMAP_MAX]
    kept, seen_batches, lots_ok, lots_ko = [], 0, 0, 0
    for i in range(0, len(rows), BATCH_DEPOT):
        seen_batches += 1
        _avant = _LLM_FAILS
        _sugg = digest_batch(rows[i:i + BATCH_DEPOT], organs, roadmap,
                             extrait_max=EXTRAIT_DEPOT, provider=provider,
                             modele=modele)
        if _LLM_FAILS == _avant:
            lots_ok += 1
        else:
            lots_ko += 1
        for s in _sugg:
            h = hashlib.md5((s["suggestion"][:80] + s["organe"]).lower()
                            .encode("utf-8")).hexdigest()[:16]
            if conn.execute("SELECT 1 FROM veille_digest_suggestions WHERE id=?",
                            (h,)).fetchone():
                continue
            conn.execute(
                "INSERT INTO veille_digest_suggestions VALUES (?,?,?,?,?,?)",
                (h, s["suggestion"], s["organe"], s["prio"], s["src"],
                 datetime.now(tz=timezone.utc).isoformat(timespec="seconds")),
            )
            kept.append(s)
        conn.commit()

    stamp = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    lines = ["\n## Digest DEPOTS %s [%s %s] — %d fichiers, %d lots "
             "(ok %d / ko %d), %d suggestions générées\n"
             % (stamp, provider, modele or "?", len(rows), seen_batches,
                lots_ok, lots_ko, len(kept))]
    for s in sorted(kept, key=lambda x: x["prio"]):
        lines.append("- **%s** [%s] %s _(src: %s)_\n"
                     % (s["prio"], s["organe"], s["suggestion"], s["src"]))
        if s.get("justification_organe"):
            lines.append("    - _organe justifié :_ %s\n" % s["justification_organe"])
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("a", encoding="utf-8") as f:
        f.writelines(lines)
    conn.close()
    # `suspect` : des lots traites sans AUCUNE suggestion retenue signale un LLM
    # muet ou une dedup qui avale tout -- a distinguer d'un « rien a dire ».
    return {"statut": statut_digest(lots_ok, lots_ko),
            "provider": provider, "model": modele, "provider_state": etat,
            "essais": essais,
            "documents": len(rows), "fichiers": len(rows), "batches": seen_batches,
            "success": lots_ok, "failure": lots_ko,
            "suggestions_generated": len(kept),
            "organes_rejetes": _ORGANES_REJETES, "organes_nuls": _ORGANES_NULS,
            "new_suggestions": len(kept),   # compat lecteurs existants
            "llm_fails": _LLM_FAILS, "raison_echec": _LLM_DERNIERE_ERREUR,
            "suspect": bool(seen_batches and not kept), "report": str(REPORT)}


def _main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--since", default="")
    # --backfill est l'unique action ; sans lui, on le fait quand meme. Un digest
    # lance en run_job/schtask ne passe pas d'arg, et print_help + rc=1 rendait ce
    # cablage muet (mesure 24-07 : le job sortait l'aide sans rien digerer).
    ap.add_argument("--depots", action="store_true",
                    help="digerer la voie CLONE (domain=sdk_gitingest) au lieu de biblio_raw")
    ap.add_argument("--depot", default="", help="restreindre a un depot, ex: codex")
    # `--provider` COURT-CIRCUITE le contrat : reserve a une preuve ou a une
    # reprise manuelle, et le resultat le declare (`provider_state: FORCE`), pour
    # qu'un digest force ne se lise jamais comme un digest arbitre.
    ap.add_argument("--provider", default="", help="forcer un fournisseur (ex: groq)")
    ap.add_argument("--modele", default="", help="forcer un modele")
    ap.add_argument("--sans-marquer", action="store_true",
                    help="mesurer sans faire avancer le curseur digested_at")
    a = ap.parse_args()
    if a.depots or a.depot:
        res = backfill_depots(limit=a.limit if a.limit != 400 else 60, depot=a.depot,
                              provider=a.provider, modele=a.modele)
    else:
        res = backfill(a.limit, a.since, provider=a.provider, modele=a.modele,
                       marquer=not a.sans_marquer)
    print(json.dumps(res, ensure_ascii=False))
    if str(res.get("statut") or "").startswith("SKIPPED_"):
        # Une abstention n'est PAS un succes, et elle n'est pas non plus un echec
        # de digest : code de retour distinct, pour qu'un lanceur puisse reprendre
        # la matiere au lieu de la croire traitee.
        print("DIGEST_SKIPPED: %s — %s"
              % (res.get("statut"),
                 json.dumps(res.get("essais") or [], ensure_ascii=False)[:400]))
        return 3
    if res.get("suspect"):
        print("DIGEST_SUSPECT: 0 suggestion sur %s lots (llm_fails=%s) — "
              "canal LLM ou prompt a inspecter, ne PAS lire comme un succes\n"
              "  cause: %s"
              % (res.get("batches"), res.get("llm_fails"),
                 res.get("raison_echec") or "(non renseignee)"))
        return 2
    return 0


if __name__ == "__main__":
    import sys as _sys

    logging.basicConfig(level=logging.INFO)
    _sys.exit(_main())
