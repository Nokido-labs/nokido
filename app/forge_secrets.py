"""
app/forge_secrets.py - Nokido v18.5
======================================
Source de vérité unique pour tous les secrets.
Priorité : coffre machine (DPAPI) > WCM (keyring) > Nokido.env > os.environ

RÈGLE SECURE BY DESIGN :
  Ne jamais lire os.environ directement pour un secret.
  Toujours utiliser get_secret("NOM_CLE").
  Jamais de fallback silencieux vers une clé expirée.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `CleIntegriteIndisponible` — Ni cle d'integrite dediee, ni maitre de transition : aucune signature HMAC possible.
- `cle_integrite_hmac` — Cle HMAC d'INTEGRITE partagee (ledger vectoriel, sanitizer, bus d'etat).
- `etat_journal_reserves` — Ou ecrit le recensement, et s'il a echoue dans CE process.
- `journaliser_lecture_directe` — Lecture du coffre machine SANS `get_secret` (appel direct de `vault_get`).
"""
from __future__ import annotations
import os
import sys
from pathlib import Path
from typing import Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT     = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / "Nokido.env"
SERVICE  = "Nokido"

# Cache en mémoire (évite de lire WCM à chaque appel)
_cache: dict[str, str] = {}
_cache_miss: set[str]  = set()

# --- REGISTRE D'OBSERVATION (Phase 1 -- mandat « organe de secretion ») -------
#
# Le guichet est traverse par ~100 modules (159 appelants mesures le 2026-09-20)
# pendant que `diagnostic()` n'est appele par PERSONNE. La seule facon honnete de
# savoir ce que le corps consomme, c'est de l'observer ICI, au passage.
#
# CE REGISTRE NE PORTE JAMAIS UNE VALEUR : noms, etats, compteurs, horodatages.
_OBSERVE: dict = {}
_SOURCE_DU_CACHE: dict = {}

# Une absence CONSTATEE n'est pas une absence ETERNELLE. `_cache_miss` figeait
# le premier « introuvable » pour toute la vie du process : un secret
# provisionne apres coup, une rotation, un coffre demarre en retard restaient
# invisibles. Mesure du 2026-09-20 sur le breakglass :
#     1er appel (variable absente) -> None, mise en _cache_miss
#     variable POSEE, 2e appel     -> None   <- la bascule ne commandait plus rien
_MISS_TS: dict = {}
_MISS_TTL_S = 300.0

# --- FENETRE DE CONTOURNEMENT D'UNE REVOCATION -------------------------------
#
# Le cache des valeurs TROUVEES n'avait AUCUNE expiration : un secret retire du
# coffre continuait d'etre servi jusqu'a l'arret du process. La fenetre de
# contournement d'une revocation n'etait donc pas longue -- elle etait INFINIE.
#
# Cartographie du 2026-09-21 qui rend ce point central : la racine reelle n'est
# pas le TPM mais DPAPI `CRYPTPROTECT_LOCAL_MACHINE` (tout compte de la machine
# sait dechiffrer, aucune entropie optionnelle ne lie un blob a un appelant), et
# le TPM ne chiffre rien -- ECDSA_P256, `sign`/`verify` seulement. Une KEK posee
# au-dessus d'un cache eternel ne protegerait pas davantage.
#
# La fenetre reste NON NULLE a dessein : sans cache, chaque appel re-sonde
# quatre sources (le rotateur mesure ~300 acces DPAPI pour resoudre un pool).
# Elle est desormais BORNEE et OBSERVABLE (`observees()[k]["age_cache_s"]`).
_CACHE_TS: dict = {}
_CACHE_TTL_S = 300.0


def _horodatage_perime(horodatages: dict, key: str, ttl_s: float) -> bool:
    """True si l'horodatage de `key` est trop vieux pour valoir verdict.

    UNE SEULE implementation pour les deux caches (valeurs et constats
    d'absence). Le cliquet de duplication a attrape le clone le 2026-09-21 :
    `_cache_perime` et `_miss_perime` etaient identiques a l'AST pres, et la
    nuance ci-dessous n'etait ecrite que dans l'une des deux -- c'est
    exactement ce que coute un doublon, pas la place qu'il prend.

    `monotonic` et non `time` : un TTL ne doit pas dependre d'un changement
    d'heure systeme. Et la comparaison est `>=` parce que `time.time()` a une
    resolution de ~15 ms sous Windows : avec `>`, un TTL de 0 ne perimait RIEN
    et le garde devenait ineprouvable en test -- or un garde qu'on ne peut pas
    faire virer au rouge n'est pas une securite, c'est une dette de cablage.
    """
    import time as _t
    ts = horodatages.get(key)
    return ts is None or (_t.monotonic() - ts) >= ttl_s


def _cache_perime(key: str) -> bool:
    """Le cache de VALEURS est-il perime pour cette cle ?"""
    return _horodatage_perime(_CACHE_TS, key, _CACHE_TTL_S)


def _sante_de_la_valeur(val: str):
    """Etat de sante EFFECTIF de cette valeur, lu dans LE ledger du rotateur.

    Rend None (inconnue du ledger), "ok", "quota" ou "bad".

    `forge_key_rotation` tient deja ce registre : `mark(env, cle, status)`
    persiste dans `sandbox/key_health.json`, indexe par EMPREINTE sha256 de la
    valeur -- jamais la cle en clair. Le guichet le CONSULTE ; il ne s'en
    fabrique pas un second, qui divergerait du premier.

    Le rearmement temporel est delegue a `_usable` : un `bad` se re-arme apres
    _BAD_TTL (6 h), parce qu'une cle re-fournie ou transitoirement 401 doit
    pouvoir reessayer. On ne redefinit pas cette politique ici.
    """
    from nokido_agent.app.forge_key_rotation import _fp, _load_health, _usable
    entree = _load_health().get(_fp(val))
    if not entree:
        return None
    return "ok" if _usable(entree) else entree.get("status")


def _memoriser(key: str, val: str, source: str):
    """Met en cache AVEC son horodatage, note l'observation, rend la valeur.

    REFUSE de servir une valeur REVOQUEE. Mesure du 2026-09-21 : le rotateur
    savait `TOGETHER_API_KEY` morte (http401) pendant que le guichet la
    distribuait a ses 159 appelants -- deux organes, deux verites, et c'est
    celui que tout le corps traverse qui portait la fausse.

    DEUX ASYMETRIES ASSUMEES :
      * `bad` revoque, `quota` NON. Un 401 dit que le credential ne vaut plus
        rien ; un 429 dit que le fournisseur limite le debit. Refuser sur quota
        empecherait meme les appels qui reussiraient apres attente.
      * Une sante ILLISIBLE ne revoque PAS. Ici le fail-closed serait
        catastrophique : un `key_health.json` corrompu eteindrait le corps
        entier. ILLISIBLE n'est pas NON. Le fail-closed reste la regle pour
        l'AUTORISATION (breakglass), pas pour un signal de SANTE.
    """
    import time as _t
    try:
        sante = _sante_de_la_valeur(val)
    except Exception:          # noqa: BLE001 -- sante illisible != revoquee
        sante = "ILLISIBLE"
    if sante in ("bad", "revoked"):
        # La valeur EXISTE et est lisible : ce n'est ni ABSENT ni ILLISIBLE.
        # On ne cherche pas ailleurs -- chercher une autre source apres un
        # retrait reviendrait a le contourner.
        #
        # TROISIEME ASYMETRIE (2026-09-21) : la DUREE du retrait se dit.
        # `bad` est une QUARANTAINE -- `forge_key_rotation._usable` la leve
        # seule apres `_BAD_TTL` (6 h), a dessein, pour qu'un 401/403
        # transitoire puisse reessayer. `revoked` est une DECISION et ne se
        # re-arme jamais. Les deux refusent ici, mais les nommer pareil ferait
        # lire « morte » a un operateur devant une cle qui revient toute seule
        # -- et lire « revient seule » devant une cle compromise.
        _noter(key, "REVOQUE" if sante == "revoked" else "QUARANTAINE",
               source, sante=sante)
        return None
    _cache[key] = val
    _CACHE_TS[key] = _t.monotonic()
    _SOURCE_DU_CACHE[key] = source
    _noter(key, "TROUVE", source, sante=sante)
    return val

# --- BASCULES DE POLITIQUE : jamais mises en cache ---------------------------
# Ces cles ne sont pas des secrets, ce sont des INTERRUPTEURS qui commandent des
# gardes. Un interrupteur se relit a chaque appel, sinon il ne se releve jamais.
#
# Mesure du 2026-09-20 : mis en cache, LAFORGE_ALLOW_SECRETS_READ survivait au
# retrait de la variable -- 15 NR du garde SQL sont passes au rouge en disant
# « [BREAKGLASS] SQL table sensible autorise » alors que plus personne
# n'autorisait rien. En exploitation : l'operateur ouvre le breakglass, fait son
# geste, retire la variable, et le garde reste OUVERT jusqu'a l'arret du process.
_BASCULES_DE_POLITIQUE = frozenset({
    "LAFORGE_ALLOW_SECRETS_READ",
})


def _compter(cles: dict, champ: str) -> dict:
    """Repartition par valeur d'un champ. `None` est nomme, jamais efface :
    une cle sans nature n'est pas une cle de nature nulle."""
    out: dict = {}
    for fiche in cles.values():
        k = fiche.get(champ) or "NON_CLASSE"
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _miss_perime(key: str) -> bool:
    """Le constat d'ABSENCE est-il trop vieux pour valoir verdict ?

    Deux caches distincts et deux TTL distincts, mais UNE seule regle de
    peremption : voir `_horodatage_perime`.
    """
    return _horodatage_perime(_MISS_TS, key, _MISS_TTL_S)


# --- ATTRIBUTION DE LA DEMANDE (phase 6) -------------------------------------
#
# SEARCH BEFORE BUILD : la politique d'autorisation EXISTE deja -- forge_mcp_rbac
# (outil -> ring), forge_authz_shadow (jeton a bail vs jeton inconnu),
# forge_separation (transporte le ring), forge_integrity (CapabilityToken,
# scopes, revoke), forge_agent_credential (jeton court). Il ne manque pas un
# moteur de politique : il manque son RACCORD a la delivrance d'un secret.
#
# Ce bloc ne pose AUCUNE politique. Il rend la DEMANDE attribuable, ce qui en
# est le prealable strict : une politique branchee sur un demandeur inconnu ne
# deciderait rien. Aujourd'hui `get_secret` rend la valeur a quiconque appelle,
# donc DEMANDE et DELIVRANCE sont confondues.
#
# L'attribution est DEDUITE de la pile, pas demandee : `get_secret` a 159
# appelants -- un parametre obligatoire les casserait tous, un parametre
# optionnel serait omis partout et ne mesurerait donc jamais rien.
_CARTE_ORGANES_DEMANDEURS: dict | None = None


def _charger_carte_organes() -> dict:
    """Carte module -> organe que le corps tient deja (1755 modules, phase 3).

    Illisible => {} : tout vaudra INCONNU. Une panne d'instrument ne cree pas
    de fait, et surtout ne cree pas de permission.
    """
    import json as _j
    import pathlib as _p
    racine = _p.Path(__file__).resolve().parent.parent
    try:
        brut = _j.loads(
            (racine / "sandbox" / "workspace" / "organ_map_full.json")
            .read_text(encoding="utf-8", errors="replace"))
        return brut.get("module_organ") or {}
    except Exception:          # noqa: BLE001
        return {}


def _vider_carte_organes() -> None:
    """Remise a zero du cache de carte. Reserve aux tests."""
    global _CARTE_ORGANES_DEMANDEURS
    _CARTE_ORGANES_DEMANDEURS = None


def _demandeur() -> tuple:
    """(module, organe) du premier frame HORS de ce module.

    Remonter jusqu'au premier frame etranger evite que le guichet s'attribue
    tous les appels a lui-meme -- un instrument qui se lit lui-meme. La remontee
    est BORNEE a 12 frames : au-dela on rend INCONNU plutot que de payer un
    parcours de pile sur un chemin chaud.
    """
    global _CARTE_ORGANES_DEMANDEURS
    import os as _o
    import sys as _s
    mod = "INCONNU"
    try:
        f = _s._getframe(1)
        for _ in range(12):
            if f is None:
                break
            if f.f_code.co_filename != __file__:
                mod = _o.path.basename(f.f_code.co_filename)
                break
            f = f.f_back
    except Exception:          # noqa: BLE001
        return ("INCONNU", "INCONNU")
    if _CARTE_ORGANES_DEMANDEURS is None:
        _CARTE_ORGANES_DEMANDEURS = _charger_carte_organes()
    return (mod, _CARTE_ORGANES_DEMANDEURS.get(mod) or "INCONNU")


# --- ETAPE 0 DU CORRECTIF DU COFFRE (owner 2026-09-28) ------------------------
#
# Mesure du 2026-09-28 : un compte bac a sable lit au coffre machine des porteurs
# de ring <= 1 et le secret de signature JWT. Ces noms sortiront du coffre
# machine ; AVANT, on mesure qui les lit -- compte, processus, module, source --
# sans rien refuser (un garde neuf observe avant d'enforcer). La liste est FERMEE
# et unique : la resolution fail-closed de l'etape 2 la reutilisera.
NOMS_RESERVES = frozenset({
    "FORGE_MCP_TOKEN",
    "LAFORGE_SUPERVISOR_TOKEN",
    "LAFORGE_JWT_SECRET",
    "LAFORGE_ADMIN_TOKEN",
    # Etape 1 (2026-09-28) : les cles DEDIEES qui remplacent le maitre dans ses roles de
    # cle. Absentes aujourd'hui ; reservees des leur naissance, pour etre recensees des
    # leur provisionnement et scellees avec les autres a l'etape 2.
    # NOKIDO_HMAC_KEY en est SORTIE (decision owner 2026-09-28) : cle d'INTEGRITE
    # partagee par des signataires qui tournent aussi sous les comptes bac a sable --
    # voir `cle_integrite_hmac`.
    "FORGE_ENCRYPT_KEY",
    "LAFORGE_DB_KEY",
    # Etape 2b-1 (2026-09-28) : la cle HMAC persona. Elle vivait dans un fichier lisible
    # par les comptes bac a sable ; reservee, elle se lit au coffre reserve d'abord et
    # entre au recensement. Sa NOUVELLE valeur s'ecrit sous SYSTEM (rotation, go owner).
    "FORGE_PERSONA_HMAC_KEY",
    # Etape 2b-2 (2026-09-28) : deux cles de signature (CapabilityToken, jetons de trame),
    # la cle du pont privilegie (signe les demandes d'execution owner) et la cle du
    # journal du pare-feu -- toutes hors du recensement jusqu'ici (inventaire 2b-0).
    "MCP_DEV_SECRET",
    "HUB_JWT_SECRET",
    "LAFORGE_PRIV_BRIDGE_HMAC",
    "firewall_log_hmac",
    # Etape 2b-3 (2026-09-28) : cle PRIVEE Ed25519 des JWT du hub (EdDSA, RFC 8037).
    "LAFORGE_JWT_ED25519_PRIVE",
    # 2026-09-28 : fichier-cle VeraCrypt du conteneur monte en V: -- il vivait au coffre
    # machine, hors recensement, LISIBLE par les comptes bac a sable (mesure).
    "LAFORGE_VC_KEYFILE_B64",
})


class CleIntegriteIndisponible(RuntimeError):
    """Ni cle d'integrite dediee, ni maitre de transition : aucune signature HMAC possible."""


_TRANSITION_INTEGRITE_DITE = {"maitre": False}


def cle_integrite_hmac(lire=None) -> bytes:
    """Cle HMAC d'INTEGRITE partagee (ledger vectoriel, sanitizer, bus d'etat) -- source
    unique, decision owner du 2026-09-28.

    NOKIDO_HMAC_KEY n'est PAS un nom reserve : ses signataires tournent aussi sous les
    comptes bac a sable, qui n'ont pas de magasin personnel. Elle est DECOUPLEE du maitre ;
    sa compromission permet de forger une signature d'integrite, jamais un jeton.

    Ordre : NOKIDO_HMAC_KEY ; sinon le maitre en TRANSITION (dit une fois par process,
    fermeture = etape 2b-6) ; sinon LEVE `CleIntegriteIndisponible`. Plus jamais de valeur
    devinable (hash du chemin du projet, "default_secret"). `lire` = le `get_secret` de
    l'appelant (les tests le remplacent la ou il est importe).
    """
    lire = lire or get_secret
    dediee = lire("NOKIDO_HMAC_KEY") or ""
    if len(dediee) >= 16:
        return dediee.encode()[:64]
    maitre = lire("FORGE_MCP_TOKEN") or ""
    if len(maitre) >= 16:
        if not _TRANSITION_INTEGRITE_DITE["maitre"]:
            _TRANSITION_INTEGRITE_DITE["maitre"] = True
            import logging as _logging

            _logging.getLogger(__name__).warning(
                "[secrets] NOKIDO_HMAC_KEY absente : signature d'integrite avec le MAITRE en "
                "TRANSITION (fermeture = etape 2b-6)")
        return maitre.encode()[:64]
    raise CleIntegriteIndisponible("ni NOKIDO_HMAC_KEY ni maitre lisibles depuis ce compte")
_JOURNAL_RESERVES = ROOT / "sandbox" / "secrets_reserves_lectures.jsonl"
# Dernier etat du coffre RESERVE vu par CE process, par cle -- jamais une valeur (etape
# 2a, 2026-09-28). Le journal le porte : il dira, avant l'etape 2b, QUI se voit refuser
# le coffre reserve et vit encore du repli sur le coffre machine.
_ETAT_COFFRE_RESERVE: dict = {}
# Premiere occurrence par process de (cle, module, source, issue) : le recensement
# veut QUI lit, pas combien de fois -- un chemin chaud ne doit pas remplir le disque.
_DEJA_JOURNALISE: set = set()
_JOURNAL_ECHECS: dict = {"n": 0, "derniere": None}


def _compte_du_jeton() -> str:
    """Compte porte par le JETON du process, jamais `USERNAME`.

    Un enfant lance par `CreateProcessAsUser` peut heriter du bloc
    d'environnement de son parent : `USERNAME` y dirait SYSTEM pour un process
    qui tourne sous un compte bac a sable. Illisible -> ILLISIBLE, jamais un
    compte devine.
    """
    try:
        if sys.platform == "win32":
            import ctypes
            n = ctypes.c_ulong(257)
            buf = ctypes.create_unicode_buffer(257)
            if ctypes.windll.advapi32.GetUserNameW(buf, ctypes.byref(n)):
                return buf.value or "ILLISIBLE"
            return "ILLISIBLE"
        import getpass
        return getpass.getuser() or "ILLISIBLE"
    except Exception:          # noqa: BLE001
        return "ILLISIBLE"


def _journaliser_reserve(key: str, issue: str, source, module: str, organe: str) -> None:
    """Consigne la premiere lecture d'un nom reserve dans CE process. Ne leve jamais.

    Aucune valeur n'entre ici, par construction : nom, issue, source, lecteur.
    """
    if key not in NOMS_RESERVES:
        return
    marque = (key, module, source, issue)
    if marque in _DEJA_JOURNALISE:
        return
    _DEJA_JOURNALISE.add(marque)
    try:
        import json as _json
        import time as _t
        rec = {
            "ts": round(_t.time(), 3), "cle": key, "issue": issue, "source": source,
            "module": module, "organe": organe, "compte": _compte_du_jeton(),
            "pid": os.getpid(), "exe": os.path.basename(sys.executable or ""),
            "script": os.path.basename(sys.argv[0]) if sys.argv and sys.argv[0] else "",
            # Un porteur recu par l'ENVIRONNEMENT survivrait a sa sortie du coffre :
            # c'est ce champ qui dira si le scellement suffit.
            "aussi_dans_environ": key in os.environ,
            # Etape 2a : l'etat du coffre reserve pour CE lecteur. Une lecture servie par
            # le coffre machine avec `ACCES_REFUSE` ici est exactement celle que l'etape
            # 2b casserait : c'est la liste a traiter avant de fermer.
            "coffre_reserve": _ETAT_COFFRE_RESERVE.get(key),
        }
        _JOURNAL_RESERVES.parent.mkdir(parents=True, exist_ok=True)
        with open(_JOURNAL_RESERVES, "a", encoding="utf-8") as f:
            f.write(_json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as exc:   # noqa: BLE001 -- un journal ne casse jamais la lecture
        # Panne d'audit INVISIBLE = organe muet qui ignore qu'il est muet.
        _JOURNAL_ECHECS["n"] += 1
        _JOURNAL_ECHECS["derniere"] = type(exc).__name__


def journaliser_lecture_directe(key: str, issue: str) -> None:
    """Lecture du coffre machine SANS `get_secret` (appel direct de `vault_get`).

    Appelee par `forge_machine_vault.vault_get`. Une lecture qui vient de CE
    module a deja ete consignee par `_noter` : elle n'est pas comptee deux fois.
    """
    global _CARTE_ORGANES_DEMANDEURS
    if key not in NOMS_RESERVES:
        return
    mod = "INCONNU"
    try:
        ici = os.path.basename(__file__)
        f = sys._getframe(1)
        for _ in range(12):
            if f is None:
                break
            nom = os.path.basename(f.f_code.co_filename)
            if nom == "forge_machine_vault.py":
                f = f.f_back
                continue
            if nom == ici:
                return
            mod = nom
            break
        if _CARTE_ORGANES_DEMANDEURS is None:
            _CARTE_ORGANES_DEMANDEURS = _charger_carte_organes()
        organe = _CARTE_ORGANES_DEMANDEURS.get(mod) or "INCONNU"
    except Exception:          # noqa: BLE001
        organe = "INCONNU"
    _journaliser_reserve(key, issue, "coffre_direct", mod, organe)


def etat_journal_reserves() -> dict:
    """Ou ecrit le recensement, et s'il a echoue dans CE process."""
    return {
        "chemin": str(_JOURNAL_RESERVES), "noms": sorted(NOMS_RESERVES),
        "echecs": _JOURNAL_ECHECS["n"], "derniere_erreur": _JOURNAL_ECHECS["derniere"],
    }


def _noter(key: str, issue: str, source=None, illisibles=None, sante=None) -> dict:
    """Consigne QUE la cle a ete demandee et COMMENT ca s'est passe.

    `issue` vaut TROUVE, ABSENT ou ILLISIBLE -- trois etats et jamais deux -- ou FERME :
    nom reserve refuse hors SYSTEM par politique (etape 2b-6), qui n'est pas une absence.
    Aucune valeur n'entre ici, par construction.
    """
    import time as _t
    now = _t.time()
    e = _OBSERVE.get(key)
    if e is None:
        e = _OBSERVE[key] = {
            "appels": 0, "issue": issue, "source": source,
            "premier_ts": now, "dernier_ts": now,
            "sources_illisibles": [], "illisible_total": 0,
            "demandeurs": {}, "organes_demandeurs": {},
        }
    _mod, _organe = _demandeur()
    _journaliser_reserve(key, issue, source, _mod, _organe)
    e.setdefault("demandeurs", {})
    e.setdefault("organes_demandeurs", {})
    e["demandeurs"][_mod] = e["demandeurs"].get(_mod, 0) + 1
    e["organes_demandeurs"][_organe] = e["organes_demandeurs"].get(_organe, 0) + 1
    e["appels"] += 1
    e["dernier_ts"] = now
    e["issue"] = issue
    e["source"] = source
    # `sources_illisibles` decrit le DERNIER appel ; `illisible_total` cumule,
    # parce qu'une panne transitoire doit rester lisible apres guerison.
    e["sources_illisibles"] = sorted(illisibles or [])
    if illisibles:
        e["illisible_total"] += 1
    # L'etat du fournisseur reste VISIBLE meme quand il n'empeche pas la
    # delivrance : un quota actif ou une sante illisible doivent se voir.
    e["sante_cle"] = sante
    return e


def _sonder(nom: str, key: str):
    """(valeur, illisible) pour une source. Ne leve jamais.

    Les fonctions sont resolues A CHAQUE APPEL : les capturer au chargement du
    module rendrait tout monkeypatch -- et tout NR -- silencieusement inoperant
    (lecon du 2026-09-18 : verifier qu'une substitution MORD).
    """
    fn = {"coffre_reserve": _coffre_reserve, "coffre": _machine_vault, "wcm": _wcm,
          "dotenv": _dotenv}[nom]
    try:
        return fn(key), False
    except Exception:          # noqa: BLE001 -- l'echec est une DONNEE, pas un plantage
        return None, True


def observees() -> dict:
    """Ce que le guichet s'est vu demander dans CE process.

    Sert a batir un audit sur les consommateurs REELS au lieu d'une liste codee
    en dur. Ne contient aucune valeur de secret.
    """
    import time as _t
    out: dict = {}
    for k, v in _OBSERVE.items():
        d = dict(v)
        # Phase 10 : un etat sans temporalite ne suffit pas. On dit de QUAND
        # date ce qu'on sert -- jamais ce qu'on sert.
        ts = _CACHE_TS.get(k) if k in _cache else None
        d["age_cache_s"] = round(_t.monotonic() - ts, 3) if ts is not None else None
        d["ttl_cache_s"] = _CACHE_TTL_S
        out[k] = d
    return out


def _vider_observations() -> None:
    """Remise a zero du registre. Reserve aux tests."""
    _OBSERVE.clear()
    _SOURCE_DU_CACHE.clear()
    _DEJA_JOURNALISE.clear()
    _ETAT_COFFRE_RESERVE.clear()


def _wcm(key: str) -> Optional[str]:
    """Lire depuis Windows Credential Manager."""
    try:
        import keyring as _kr
        return _kr.get_password(SERVICE, key) or None
    except Exception:
        return None


def _machine_vault(key: str) -> Optional[str]:
    """Lire depuis le coffre machine-wide (DPAPI LocalMachine).
    Lisible par TOUS les comptes service, contrairement au WCM per-user."""
    try:
        from nokido_agent.app.forge_machine_vault import vault_get
        return vault_get(key)
    except Exception:
        return None


def _coffre_reserve(key: str) -> Optional[str]:
    """Coffre RESERVE (etape 2a, go owner 2026-09-28) : DPAPI portee utilisateur sous
    SYSTEM, dossier a ACL SYSTEM + Administrateurs. Consulte pour les seuls noms
    reserves.

    LEVE quand il est illisible (acces refuse, blob scelle pour un autre compte,
    fichier corrompu) : `_sonder` en fait une source ILLISIBLE, jamais une absence.
    L'etat est garde pour le journal des noms reserves.
    """
    try:
        from nokido_agent.app.forge_machine_vault import RESERVE_ETATS_ILLISIBLES, reserve_lire
    except Exception:
        _ETAT_COFFRE_RESERVE[key] = "INIMPORTABLE"
        raise
    val, etat = reserve_lire(key)
    _ETAT_COFFRE_RESERVE[key] = etat
    if etat in RESERVE_ETATS_ILLISIBLES:
        raise PermissionError(f"coffre reserve {etat}")
    return val


def _dotenv(key: str) -> Optional[str]:
    """Lire depuis Nokido.env (fallback WCM)."""
    if not ENV_PATH.exists():
        return None
    for line in ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == key:
            v = v.strip()
            return v if v else None
    return None


# --- ETAPE 2b-6 DU CORRECTIF DU COFFRE, LOT 1 (go owner 2026-09-28) -----------------
#
# Noms reserves encore servis par le coffre machine et Nokido.env -- deux sources que tout
# compte bac a sable lit. Chacun a un lecteur REEL hors SYSTEM, mesure au journal des
# lectures reservees le 2026-09-28, qui n'a pas encore sa voie propre :
#   FORGE_MCP_TOKEN          pont stdio (compte owner), portail (cle d'integrite en transition)
#   LAFORGE_ADMIN_TOKEN      portail (compte owner), campagne UI (bac a sable)
#   LAFORGE_JWT_SECRET       portail : sessions HS256 de transition
#   MCP_DEV_SECRET           mode dev et secours (compte owner), veille RSS
#   LAFORGE_PRIV_BRIDGE_HMAC le demon du pont privilegie VERIFIE sous le compte owner et ne
#                            lit pas le coffre reserve (cle partagee par conception, P0)
#   LAFORGE_SUPERVISOR_TOKEN le lanceur du BUREAU de l'owner (`nokido_launcher.py`, relance du
#                            hub) le lit sous le compte owner. Ferme au lot 1 sur une fenetre
#                            de journal de 7 h ou ce lanceur, rare, ne figurait pas : la relance
#                            owner a pris 401 (mesure 2026-09-28). Une source qui se tait ne
#                            prouvait pas l'absence de lecteur -- REMIS en transition.
#   (FORGE_ENCRYPT_KEY et LAFORGE_DB_KEY, remis en transition le 2026-09-28 parce que
#   `forge_encrypt`/`forge_db_conn` retombaient sur une cle DERIVEE DU MAITRE, sont
#   REFERMES le meme jour : ce repli est retire -- echec franc, jamais de derive.)
# Lot 2 (meme jour) : HUB_JWT_SECRET et firewall_log_hmac FERMES apres `--appliquer` sous
# SYSTEM -- leur lecteur SYSTEM (le hub) passait par le repli tant qu'ils manquaient au
# coffre reserve ; relus depuis au coffre reserve dans un process SYSTEM neuf.
# Les autres noms reserves sont FERMES : hors SYSTEM, seul le magasin PERSONNEL (WCM) les
# sert encore. Cliquet : cet ensemble ne fait que DECROITRE
# (tests/nr/test_fermeture_replis_reserves_2b6_nr.py).
RESERVES_EN_TRANSITION = frozenset({
    "FORGE_MCP_TOKEN",
    "LAFORGE_ADMIN_TOKEN",
    "LAFORGE_JWT_SECRET",
    "MCP_DEV_SECRET",
    "LAFORGE_PRIV_BRIDGE_HMAC",
    "LAFORGE_SUPERVISOR_TOKEN",
    # (LAFORGE_VC_KEYFILE_B64, ne en transition le 2026-09-28, est FERME le meme jour : copie
    # au coffre reserve sous SYSTEM pour la tache de demarrage `LaForge-VC-Boot`, et copie
    # dans le magasin PERSONNEL de l'owner pour son montage manuel -- relues identiques.)
})


def get_secret(key: str, required: bool = False) -> Optional[str]:
    """
    Récupère un secret dans l'ordre de priorité :
      1. Cache mémoire (session)
      1b. Coffre RESERVE (DPAPI portée utilisateur sous SYSTEM) — noms réservés
          seulement (étape 2a, 2026-09-28)
      2. Coffre machine-wide (DPAPI LocalMachine) — FERMÉ aux noms réservés hors
         transition (étape 2b-6)
      3. Windows Credential Manager (WCM, per-user)
      4. Nokido.env — FERMÉ comme le coffre machine
      5. os.environ (dernier recours, avec warning)

    Args:
        key: Nom de la variable (ex: "GROQ_API_KEY")
        required: Si True, lève ValueError si introuvable

    Returns:
        Valeur du secret ou None
    """
    if key in _BASCULES_DE_POLITIQUE:
        # Relue a CHAQUE appel, jamais memorisee : c'est ce qui permet au garde
        # de se refermer quand l'operateur retire l'autorisation.
        for _nom in ("environ", "coffre", "wcm", "dotenv"):
            if _nom == "environ":
                _v = os.environ.get(key)
            else:
                _v, _i = _sonder(_nom, key)
                if _i:
                    continue
            if _v:
                _noter(key, "TROUVE", _nom)
                return _v
        _noter(key, "ABSENT", None)
        if required:
            raise ValueError(f"Secret requis introuvable: {key}")
        return None

    if key in _cache:
        if _cache_perime(key):
            # Peremption : on ne SERT plus sans re-demander. C'est ce qui donne
            # un EFFET a une revocation faite pendant que le process tournait.
            _cache.pop(key, None)
            _CACHE_TS.pop(key, None)
            _SOURCE_DU_CACHE.pop(key, None)
        else:
            _noter(key, "TROUVE", _SOURCE_DU_CACHE.get(key, "cache"))
            return _cache[key]
    if key in _cache_miss:
        # L'environnement est la seule source qui peut changer SANS que
        # personne ne previenne : un operateur qui pose une bascule apres le
        # demarrage, un service lance avec un env enrichi. Le relire coute un
        # acces dict -- on ne fige jamais une absence contre lui.
        _tardif = os.environ.get(key)
        if _tardif:
            _cache_miss.discard(key)
            _MISS_TS.pop(key, None)
            return _memoriser(key, _tardif, "environ")
        if _miss_perime(key):
            # STALE != DEAD : on re-sonde au lieu de rendre un verdict perime.
            _cache_miss.discard(key)
            _MISS_TS.pop(key, None)
        else:
            _noter(key, "ABSENT", None)
            if required:
                raise ValueError(f"Secret requis introuvable: {key}")
            return None

    _illisibles: list = []

    # 0. Coffre RESERVE -- noms reserves SEULEMENT (etape 2a, go owner 2026-09-28). Lu
    # D'ABORD. Illisible (ACL, blob scelle pour un autre compte) ne vaut pas absent.
    # Etape 2b-6 : pour un nom reserve FERME, le coffre machine et Nokido.env ne sont
    # meme plus sondes -- lisibles par tout compte bac a sable, ils rendaient le
    # scellement decoratif. Le magasin personnel (WCM) reste : illisible par un autre
    # compte, il porte les copies de l'owner (modes dev).
    _ferme = key in NOMS_RESERVES and key not in RESERVES_EN_TRANSITION
    if key in NOMS_RESERVES:
        val, _ill = _sonder("coffre_reserve", key)
        if _ill:
            _illisibles.append("coffre_reserve")
        elif val:
            return _memoriser(key, val, "coffre_reserve")

    # 1. Coffre machine (DPAPI) — lisible par tous les comptes service
    if not _ferme:
        val, _ill = _sonder("coffre", key)
        if _ill:
            _illisibles.append("coffre")
        elif val:
            return _memoriser(key, val, "coffre")

    # 2. WCM (keyring, per-user)
    val, _ill = _sonder("wcm", key)
    if _ill:
        _illisibles.append("wcm")
    elif val:
        return _memoriser(key, val, "wcm")

    # 3. .env
    if not _ferme:
        val, _ill = _sonder("dotenv", key)
        if _ill:
            _illisibles.append("dotenv")
        elif val:
            return _memoriser(key, val, "dotenv")

    # 4. os.environ — dernier recours avec warning
    val = os.environ.get(key)
    if val:
        import logging
        logging.getLogger("forge.secrets").warning(
            f"Secret {key!r} lu depuis os.environ (non sécurisé) — migrer vers WCM"
        )
        return _memoriser(key, val, "environ")

    # FERME n'est ni ABSENT ni ILLISIBLE : une POLITIQUE refuse ce nom hors SYSTEM
    # (DISABLED_BY_POLICY != RESOURCE_UNAVAILABLE). Jamais mis en `_cache_miss` : le
    # meme process peut le lire des que le coffre reserve lui devient lisible.
    if _ferme:
        _noter(key, "FERME", None, _illisibles)
        if required:
            raise ValueError(
                f"Secret reserve FERME hors SYSTEM (etape 2b-6) : {key!r}\n"
                f"  -> il se lit au coffre reserve (SYSTEM) ou au magasin personnel"
                f" de l'owner ; le coffre machine et Nokido.env ne le servent plus"
            )
        return None

    # Introuvable -- mais POURQUOI ? ABSENT et ILLISIBLE ne se soldent pas pareil.
    if _illisibles:
        # Une source qui a LEVE ne prouve rien sur l'existence de la cle. La
        # mettre en `_cache_miss` transformerait une panne de trois secondes en
        # absence definitive pour toute la vie du process.
        _noter(key, "ILLISIBLE", None, _illisibles)
        if required:
            raise ValueError(
                f"Secret requis ILLISIBLE (et non absent): {key!r}\n"
                f"  sources en echec : {', '.join(_illisibles)}\n"
                f"  -> verifier l'acces avant de conclure a une absence"
            )
        return None
    import time as _t_miss
    _cache_miss.add(key)
    _MISS_TS[key] = _t_miss.monotonic()
    _noter(key, "ABSENT", None)
    if required:
        raise ValueError(
            f"Secret requis introuvable: {key!r}\n"
            f"  → Ajouter dans WCM: python app/forge_secrets.py --set {key}\n"
            f"  → Ou dans Nokido.env: {key}=votre_valeur"
        )
    return None


def invalidate_cache(key: Optional[str] = None) -> None:
    """Invalide le cache (après rotation de clé)."""
    if key:
        _cache.pop(key, None)
        _cache_miss.discard(key)
    else:
        _cache.clear()
        _cache_miss.clear()


def set_secret(key: str, value: str) -> bool:
    """Stocke un secret dans le coffre machine (DPAPI) + invalide le cache.
    Backend canonique : lisible par tous les comptes service, contrairement
    au WCM per-user."""
    try:
        from nokido_agent.app.forge_machine_vault import vault_set
        if not vault_set(key, value):
            return False
        invalidate_cache(key)
        return True
    except Exception as e:
        print(f"[forge_secrets] Erreur stockage {key}: {e}")
        return False


def require(*keys: str) -> dict[str, str]:
    """
    Récupère plusieurs secrets requis d'un coup.
    Lève ValueError si l'un manque.
    Usage: creds = require("GROQ_API_KEY", "GEMINI_API_KEY")
    """
    return {k: get_secret(k, required=True) for k in keys}


def diagnostic(scan: bool = False) -> dict:
    """État complet des secrets connus."""
    try:
        import keyring as _kr
        keyring_ok = True
    except ImportError:
        keyring_ok = False

    known = [
        "GEMINI_API_KEY","GROQ_API_KEY","XAI_API_KEY","DEEPSEEK_API_KEY",
        "MISTRAL_API_KEY","HF_TOKEN","GITHUB_TOKEN","CODEBERG_TOKEN",
        "FORGE_MCP_TOKEN","MCP_DEV_SECRET","ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY","LAFORGE_ADMIN_TOKEN","GITHUB_MODELS_TOKEN",
        "SMITHERY_API","COHERE_API_KEY","KAGGLE_API_TOKEN",
        "FORGE_TOKEN_CLAUDE","FORGE_TOKEN_GEMINI","FORGE_TOKEN_CLINE",
        "FORGE_TOKEN_ZCODE",
        "FORGE_TOKEN_BRIDGE","FORGE_TOKEN_GEMINI_HEADLESS",
        "FORGE_TOKEN_NETCFG","FORGE_TOKEN_TRAY","FORGE_TOKEN_SERVICES",
    ]
    in_vault, in_wcm, in_env, missing = [], [], [], []
    for k in known:
        if _machine_vault(k):
            in_vault.append(k)
        elif keyring_ok and _wcm(k):
            in_wcm.append(k)
        elif _dotenv(k):
            in_env.append(k)
        else:
            missing.append(k)

    # --- PHASE 1 : l'audit ne se limite plus a sa propre liste ---------------
    # Mesure du 2026-09-20 : 26 cles connues ici, 74 demandees par le code sur
    # 219 sites. Un audit qui rend « tout va bien » sur 26 cles pendant que 74
    # circulent ne mesure pas le coffre -- il mesure sa propre liste.
    cles: dict = {}
    for nom in known:
        if nom in in_vault:
            etat, src = "TROUVE", "coffre"
        elif nom in in_wcm:
            etat, src = "TROUVE", "wcm"
        elif nom in in_env:
            etat, src = "TROUVE", "dotenv"
        else:
            etat, src = "ABSENT", None
        o = _OBSERVE.get(nom)
        if o and o["issue"] == "ILLISIBLE":
            # L'observation vivante prime sur la sonde a froid : si le guichet a
            # vu une source echouer, « ABSENT » serait un faux negatif.
            etat, src = "ILLISIBLE", None
        cles[nom] = {
            "origine": "declaree", "etat": etat, "source": src,
            "observee": bool(o), "appels": (o or {}).get("appels", 0),
        }

    for nom, o in _OBSERVE.items():
        if nom in cles:
            continue
        cles[nom] = {
            "origine": "observee", "etat": o["issue"], "source": o.get("source"),
            "observee": True, "appels": o["appels"],
        }

    # --- SCAN STATIQUE, a la demande -----------------------------------------
    # Le registre d'observation ne voit que CE process : le hub, les daemons et
    # les jobs sont ailleurs. Seul le scan du depot rend l'inventaire GLOBAL.
    # Il coute ~2400 lectures : son cout est EXPLICITE, jamais paye a l'insu de
    # l'appelant.
    scan_info = {
        "etat": "NON_DEMANDE", "cles_vues": 0, "stats": None,
        "pourquoi": "diagnostic(scan=True) parcourt le depot ; le cout se demande.",
    }
    if scan:
        try:
            # `proprietaires()` appelle `cles_demandees()` en interne et y joint
            # la carte d'organes : un SEUL parcours du depot, une seule verite.
            from nokido_agent.tools.forge_secret_source_audit import (
                proprietaires, nature as _nature_de,
            )
            vues, st = proprietaires()
            scan_info = {"etat": "FAIT", "cles_vues": len(vues), "stats": st,
                         "pourquoi": ""}
            for nom, fiche in vues.items():
                # La NATURE voyage avec l'inventaire : la recalculer ici
                # produirait un second classement, et deux classements
                # divergent toujours en silence.
                enrichi = {
                    "sites": fiche["sites"][:8],
                    "occurrences": fiche.get("occurrences", 0),
                    "nature": fiche.get("nature"),
                    "nature_pourquoi": fiche.get("nature_pourquoi"),
                    "nature_trancher": fiche.get("nature_trancher"),
                    # PHASE 3 : le proprietaire voyage avec la cle. « 82 cles OK »
                    # n'est pas un resultat -- la question est qui possede quoi,
                    # et ce qu'on IGNORE.
                    "proprietaire": fiche.get("verdict"),
                    "organes": fiche.get("organes", []),
                    "instruire": fiche.get("instruire", ""),
                }
                if nom in cles:
                    cles[nom].update(enrichi)
                    continue
                cles[nom] = {
                    "origine": "scan", "etat": "NON_OBSERVEE", "source": None,
                    "observee": False, "appels": 0, **enrichi,
                }
            # Une cle DECLAREE que le scan n'a pas croisee restait sans nature :
            # « NON_CLASSE » n'est pas une nature, c'est un trou. On la classe
            # par son nom comme les autres -- meme fonction, jamais une seconde.
            for nom, fiche in cles.items():
                if not fiche.get("nature"):
                    _n = _nature_de(nom)
                    fiche["nature"] = _n["nature"]
                    fiche["nature_pourquoi"] = _n["pourquoi"]
                    fiche["nature_trancher"] = _n["trancher"]
                if not fiche.get("proprietaire"):
                    # Declaree dans la liste du guichet et croisee par AUCUN
                    # site de consommation : c'est la definition d'ORPHAN, pas
                    # un trou de classement. « NON_CLASSE » serait ici un aveu
                    # d'instrument la ou le contrat a deja un mot.
                    fiche["proprietaire"] = "ORPHAN"
                    fiche["organes"] = []
                    fiche["instruire"] = (
                        "declaree au diagnostic mais aucun site de consommation "
                        "mesure : retirer la declaration, ou brancher le "
                        "consommateur qui devait l'utiliser"
                    )
        except Exception as _e:        # noqa: BLE001
            # Un scan qui echoue rend ILLISIBLE et le DIT. Rendre « rien vu »
            # ferait passer un instrument casse pour un depot sans secrets.
            scan_info = {
                "etat": "ILLISIBLE", "cles_vues": 0, "stats": None,
                "pourquoi": "%s: %s" % (_e.__class__.__name__, _e),
            }

    return {
        "service":           SERVICE,
        "keyring_available": keyring_ok,
        "in_vault":          in_vault,
        "in_wcm":            in_wcm,
        "in_env_only":       in_env,
        "missing":           missing,
        "total_known":       len(known),
        "cles":              cles,
        "total":             len(cles),
        "non_observe":       sorted(n for n, f in cles.items() if not f["observee"]),
        "illisibles":        sorted(n for n, f in cles.items() if f["etat"] == "ILLISIBLE"),
        "scan":              scan_info,
        # SECRET != CONFIG != CREDENTIAL : on ne peut pas segmenter par organe
        # (DEK-LLM / DEK-GIT / DEK-MCP) ce qui n'est pas distingue du
        # parametrage. La separation est un PREALABLE a la segmentation
        # cryptographique, pas un raffinement ulterieur.
        "par_nature":        _compter(cles, "nature"),
        "par_proprietaire":  _compter(cles, "proprietaire"),
        "par_origine":       _compter(cles, "origine"),
        "par_etat":          _compter(cles, "etat"),
        "portee":            (
            "DECLAREE = sondee a l'instant. OBSERVEE = telle que CE process l'a "
            "vue passer. Une cle declaree mais jamais demandee ici est "
            "NON_OBSERVEE, ce qui n'est pas un certificat de sante. Les cles "
            "demandees par d'autres process ne sont pas visibles d'ici."
        ),
    }

_HF_POOL_INDEX = 0

def get_hf_token(current_failing_token: str | None = None) -> Optional[str]:
    """
    Récupère un token HF depuis un pool de clés configuré (HF_TOKEN, HF_TOKEN_1, HF_TOKEN_2, etc.)
    et gère la rotation automatique en cas d'erreur (429/limites) détectée.
    """
    global _HF_POOL_INDEX
    tokens = []
    t0 = get_secret("HF_TOKEN")
    if t0:
        tokens.append(t0)
    for i in range(1, 10):
        t = get_secret(f"HF_TOKEN_{i}")
        if t:
            tokens.append(t)
            
    if not tokens:
        return None
        
    if current_failing_token and current_failing_token in tokens:
        idx = tokens.index(current_failing_token)
        _HF_POOL_INDEX = (idx + 1) % len(tokens)
        import logging
        logging.getLogger("forge.secrets").warning(
            f"Rotation du token HF : clé #{idx} en échec, bascule sur la clé #{_HF_POOL_INDEX}"
        )
        
    _HF_POOL_INDEX = _HF_POOL_INDEX % len(tokens)
    return tokens[_HF_POOL_INDEX]


def main() -> int:
    """CLI du gestionnaire de secrets.

    Entrypoint console `nokido-secrets` (pyproject [project.scripts]). Le corps
    vivait dans le garde `__main__` : la cible declaree n'existait donc pas, et
    la commande installee par pip mourait en AttributeError (mesure 2026-08-27).
    """
    import argparse
    p = argparse.ArgumentParser(description="Nokido secrets manager")
    p.add_argument("command", nargs="?", default="status",
                   choices=["status","selftest","set","get"])
    p.add_argument("--key", "-k", help="Nom de la clé")
    args = p.parse_args()

    if args.command in ("status", "selftest"):
        d = diagnostic()
        print(f"Keyring: {'OK' if d['keyring_available'] else 'ABSENT'}")
        print(f"Coffre machine ({len(d['in_vault'])}): {d['in_vault']}")
        print(f"Dans WCM ({len(d['in_wcm'])}): {d['in_wcm']}")
        print(f"Dans .env seulement ({len(d['in_env_only'])}): {d['in_env_only']}")
        print(f"Manquants ({len(d['missing'])}): {d['missing']}")
        # --- PORTEE, dite plutot que masquee -----------------------------
        obs = d["total"] - d["total_known"]
        print(f"\nPortee de cet audit : {d['total']} cle(s) "
              f"({d['total_known']} declarees + {obs} observee(s) dans CE process)")
        if d["illisibles"]:
            print(f"ILLISIBLES ({len(d['illisibles'])}) : {d['illisibles']}")
            print("  ILLISIBLE n'est pas ABSENT -- ne pas re-provisionner sur cette base.")
        print(f"NON OBSERVEES ici : {len(d['non_observe'])} cle(s) -- "
              f"ce n'est pas un certificat de sante, seulement l'absence de demande.")
        print(f"  {d['portee']}")
    elif args.command == "set" and args.key:
        val = input(f"Valeur pour {args.key}: ").strip()
        ok = set_secret(args.key, val)
        print("OK" if ok else "ERREUR")
    elif args.command == "get" and args.key:
        # Une VALEUR ne sort jamais d'ici, meme tronquee : `val[-4:]` rendait
        # quatre caracteres reels du secret sur la sortie standard, donc dans
        # tout journal qui la capture. On rend une EMPREINTE PUBLIQUE, qui
        # permet de comparer deux instances sans rien reveler.
        val = get_secret(args.key)
        o = _OBSERVE.get(args.key, {})
        etat = o.get("issue") or ("TROUVE" if val else "ABSENT")
        empreinte = "-"
        if val:
            import hashlib
            empreinte = hashlib.sha256(val.encode("utf-8", "replace")).hexdigest()[:12]
        print(f"{args.key} : {etat}  source={o.get('source') or '-'}  "
              f"empreinte(sha256/12)={empreinte}")
        if etat == "ILLISIBLE":
            print("  sources en echec :", ", ".join(o.get("sources_illisibles") or []))
            print("  -> verifier l'acces AVANT de conclure a une absence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
