#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_veille_registre.py — le CONTRAT du registre de cibles de veille.

Producteur (`forge_veille_backlog_github`) et consommateur
(`forge_veille_clone_ingest`) partagent CE module. Dupliquer la validation des
deux cotes la ferait diverger : le producteur ecrirait un registre que le
consommateur croit valide, ou l'inverse.

TROIS PROPRIETES, chacune reponse a un mode de panne mesure :

1. **FAIL-CLOSED.** Un registre absent, illisible, corrompu ou invalide leve
   `RegistreInvalide`. Il n'existe AUCUN repli implicite : le repli sur les 12
   depots historiques est une decision de l'appelant, prise explicitement, et
   annoncee. Un registre a 342 cibles qui redevient 12 en silence, c'est une
   campagne qui se croit complete a 3,5 %.

2. **AUTO-VERIFIANT.** `generation_id` est l'empreinte du CONTENU (ordinal,
   target_id, url de chaque cible), pas un horodatage ni un aleatoire. Un
   registre tronque ou retouche ne peut donc pas se faire passer pour entier :
   son empreinte ne colle plus. Combine a l'ecriture atomique, cela ferme le cas
   « registre partiellement ecrit consommable ».

3. **IDENTITE STABLE.** `target_id = sha256(url canonique)[:16]` ne depend NI du
   nom de fichier, NI du slug, NI de l'ordre de generation. Le slug, lui, est
   une commodite d'affichage : il PEUT entrer en collision (deux organisations,
   un meme nom de depot), et ces collisions sont detectees et NOMMEES, jamais
   supposees absentes.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `EcrivainAtomique` — `ecrire_atomique` EN FLUX : meme contrat (temporaire voisin, fsync, replace ; tout ou rien), sans tenir le texte entier en memoire.
- `chemin_dump` — Copie existante la PLUS RECENTE du dump, ou None.
- `dossier_ecriture_dumps` — Premier dossier INSCRIPTIBLE, hors depot d'abord (dernier declare en tete), docs/ en dernier recours.
- `dossiers_dumps` — `[docs/, <dossiers de l'interrupteur>...]` — docs/ toujours en tete.
- `nom_fichier_dump` — Nom de fichier du dump d'une veille : `gitingest_veille_<nom>.txt`.
- `noms_dumps` — Noms de tous les dumps presents, tous dossiers confondus, sans doublon.
"""
from __future__ import annotations

__FORGE_COLOR__ = "digestif/registre-veille"

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

SCHEMA_VERSION = 1

_CHAMPS_META = ("schema_version", "generation_id", "generated_at", "source",
                "count", "cibles")
_CHAMPS_CIBLE = ("repo", "url", "target_id", "priorite", "ordinal",
                 "mentions_owner", "mentions_agent")
_RE_REPO = re.compile(r"^[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*$")
_RE_URL = re.compile(r"^https://github\.com/[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*$")
PRIORITES = ("demande", "contexte")

# Etats d'un dump. Trois, jamais deux : « pas de dump » et « dump dont on ignore
# la provenance » demandent des actions differentes, et les confondre fabrique
# soit un faux succes, soit un re-clone inutile.
ABSENT, STALE, READY = "ABSENT", "STALE", "READY"


class RegistreInvalide(ValueError):
    """Le registre ne peut pas etre consomme. Jamais rattrapee en silence."""


class CibleInconnue(ValueError):
    """Un nom donne en ligne de commande n'existe pas au registre."""


# ── identite ────────────────────────────────────────────────────────────────
def url_canonique(repo: str) -> str:
    """`org/nom` -> URL GitHub canonique. Forme UNIQUE, base de l'identite."""
    return "https://github.com/%s" % str(repo).strip().strip("/")


def target_id(url: str) -> str:
    """Identifiant stable, derive de l'URL canonique en minuscules.

    Insensible a la casse a dessein : `GreyDGL/PentestGPT` et
    `greydgl/pentestgpt` sont le MEME depot, et les compter deux fois gonflait
    le retard de veille (mesure du 31/08 : 342 cites -> 339 cibles reelles).
    """
    return hashlib.sha256(str(url).strip().lower().encode("utf-8")).hexdigest()[:16]


def slug_affichage(repo: str) -> str:
    """Nom lisible. PEUT entrer en collision — ce n'est pas une identite.

    `construire_registre` desambigue en suffixant le `target_id`, et consigne la
    collision au lieu de la taire.
    """
    return re.sub(r"[^a-z0-9]+", "_", str(repo).lower()).strip("_")


def calcul_generation_id(cibles: dict) -> str:
    """Empreinte du CONTENU du registre — pas de l'heure, pas d'un aleatoire.

    Deux generations sur des donnees identiques rendent le MEME id : c'est ce
    qui permet a une campagne en cours de constater qu'elle travaille toujours
    sur le meme instantane.
    """
    grain = "\n".join(sorted(
        "%s|%s|%s" % (c.get("ordinal"), c.get("target_id"), c.get("url"))
        for c in cibles.values()))
    return hashlib.sha256(grain.encode("utf-8")).hexdigest()[:16]


# ── validation ──────────────────────────────────────────────────────────────
def _exige(cond, msg: str) -> None:
    if not cond:
        raise RegistreInvalide(msg)


def _entier(valeur, champ: str) -> int:
    # `True` est un `int` en Python : sans ce garde, `mentions_owner: true`
    # passerait pour l'entier 1.
    if isinstance(valeur, bool) or not isinstance(valeur, int):
        raise RegistreInvalide(
            "%s: entier attendu, recu %s" % (champ, type(valeur).__name__))
    if valeur < 0:
        raise RegistreInvalide("%s: valeur negative (%d)" % (champ, valeur))
    return valeur


def valider_registre(doc) -> dict:
    """Rend le document si tout est conforme, leve `RegistreInvalide` sinon.

    Le message porte TOUJOURS le champ fautif : un refus qu'on ne peut pas
    diagnostiquer se contourne au lieu d'etre corrige.
    """
    _exige(isinstance(doc, dict),
           "racine: objet JSON attendu, recu %s" % type(doc).__name__)
    for champ in _CHAMPS_META:
        _exige(champ in doc, "champ obligatoire absent: %s" % champ)
    _exige(doc["schema_version"] == SCHEMA_VERSION,
           "schema_version %r, attendu %d" % (doc["schema_version"], SCHEMA_VERSION))
    for champ in ("generation_id", "generated_at", "source"):
        _exige(isinstance(doc[champ], str) and doc[champ].strip(),
               "%s: chaine non vide attendue" % champ)
    _entier(doc["count"], "count")

    cibles = doc["cibles"]
    _exige(isinstance(cibles, dict),
           "cibles: objet attendu, recu %s" % type(cibles).__name__)
    _exige(doc["count"] == len(cibles),
           "count=%d mais %d cible(s) — registre partiellement ecrit ?"
           % (doc["count"], len(cibles)))

    par_id: dict = {}
    par_ordinal: dict = {}
    for slug, c in cibles.items():
        _exige(isinstance(slug, str) and slug.strip(), "cle de cible vide")
        _exige(isinstance(c, dict), "%s: objet attendu, recu %s"
               % (slug, type(c).__name__))
        for champ in _CHAMPS_CIBLE:
            _exige(champ in c, "%s: champ absent %s" % (slug, champ))
        _exige(isinstance(c["repo"], str) and _RE_REPO.match(c["repo"]),
               "%s: repo non canonique %r" % (slug, c["repo"]))
        _exige(isinstance(c["url"], str) and _RE_URL.match(c["url"]),
               "%s: url GitHub non canonique %r" % (slug, c["url"]))
        _exige(c["url"] == url_canonique(c["repo"]),
               "%s: url %s incoherente avec repo %s" % (slug, c["url"], c["repo"]))
        attendu = target_id(c["url"])
        _exige(c["target_id"] == attendu,
               "%s: target_id %r, attendu %s" % (slug, c["target_id"], attendu))
        _exige(c["priorite"] in PRIORITES,
               "%s: priorite %r hors %s" % (slug, c["priorite"], list(PRIORITES)))
        _entier(c["ordinal"], "%s.ordinal" % slug)
        _entier(c["mentions_owner"], "%s.mentions_owner" % slug)
        _entier(c["mentions_agent"], "%s.mentions_agent" % slug)

        if attendu in par_id:
            raise RegistreInvalide(
                "collision d'identite: '%s' et '%s' partagent target_id %s"
                % (par_id[attendu], slug, attendu))
        par_id[attendu] = slug
        if c["ordinal"] in par_ordinal:
            raise RegistreInvalide(
                "ordinal %d partage par '%s' et '%s' — la selection par lot ne "
                "serait pas deterministe"
                % (c["ordinal"], par_ordinal[c["ordinal"]], slug))
        par_ordinal[c["ordinal"]] = slug

    empreinte = calcul_generation_id(cibles)
    _exige(doc["generation_id"] == empreinte,
           "generation_id %s ne correspond pas au contenu (%s) — document "
           "tronque ou retouche" % (doc["generation_id"], empreinte))
    return doc


def charger_registre(chemin) -> dict:
    """Lit et VALIDE. Distingue ABSENT / ILLISIBLE / CORROMPU / INVALIDE."""
    p = Path(chemin)
    try:
        brut = p.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RegistreInvalide("registre ABSENT: %s" % p) from exc
    except OSError as exc:
        # Un acces refuse n'est PAS un fichier vide : le dire, sinon on conclut
        # « aucune cible » sur un droit manquant.
        raise RegistreInvalide(
            "registre ILLISIBLE (%s): %s" % (type(exc).__name__, p)) from exc
    try:
        doc = json.loads(brut)
    except ValueError as exc:
        raise RegistreInvalide(
            "registre JSON corrompu (%s): %s" % (str(exc)[:90], p)) from exc
    return valider_registre(doc)


# ── ecriture ────────────────────────────────────────────────────────────────
def ecrire_atomique(chemin, texte: str) -> Path:
    """Ecrit tout ou rien : temporaire dans le MEME repertoire, fsync, replace.

    `write_text()` sur le fichier final le tronque AVANT d'ecrire : un plantage
    au milieu laisse un registre valide en JSON mais ampute, que le lecteur
    consommerait. `os.replace` est atomique sur le meme systeme de fichiers,
    d'ou le temporaire voisin et non dans le repertoire temporaire du systeme.
    """
    ecrivain = EcrivainAtomique(chemin)
    try:
        ecrivain.write(texte)
        return ecrivain.valider()
    except BaseException:
        ecrivain.abandonner()
        raise


class EcrivainAtomique:
    """`ecrire_atomique` EN FLUX : meme contrat (temporaire voisin, fsync,
    replace ; tout ou rien), sans tenir le texte entier en memoire.

    Mesure 2026-09-23 : un dump construit en memoire puis `join` a fait tuer un
    job de veille a 6 151 Mo de RSS. En flux, la memoire est bornee par le plus
    gros morceau ecrit. `abandonner()` apres `valider()` est sans effet : on peut
    l'appeler sans condition dans un `finally`.
    """

    def __init__(self, chemin):
        self.chemin = Path(chemin)
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        fd, self._tmp = tempfile.mkstemp(dir=str(self.chemin.parent),
                                         prefix=self.chemin.name + ".", suffix=".tmp")
        self._fh = os.fdopen(fd, "w", encoding="utf-8", newline="\n")
        self.fini = False

    def write(self, texte: str) -> None:
        self._fh.write(texte)

    def valider(self) -> Path:
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._fh.close()
        os.replace(self._tmp, self.chemin)
        self.fini = True
        return self.chemin

    def abandonner(self) -> None:
        if self.fini:
            return
        self.fini = True
        try:
            self._fh.close()
        except OSError:
            pass  # muet-ok : on jette le temporaire juste apres
        try:
            os.unlink(self._tmp)
        except OSError:
            pass  # muet-ok : le temporaire a deja disparu ou est inaccessible


def construire_registre(entrees, source: str, generated_at: str) -> dict:
    """Assemble un registre VALIDE depuis des entrees DEJA ORDONNEES.

    L'ordre d'entree devient l'`ordinal`, et l'ordinal est ce que les lots
    consomment : trier ici, une fois, evite que chaque campagne re-derive son
    propre ordre et voie les lots glisser sous ses pieds.
    """
    cibles: dict = {}
    par_id: dict = {}
    collisions: list = []
    ordinal = 0
    for e in entrees:
        repo = str(e["repo"]).strip().strip("/")
        url = url_canonique(repo)
        tid = target_id(url)
        if tid in par_id:
            # Meme depot ecrit differemment (casse). On garde le premier et on
            # DIT lequel est ecarte, au lieu de laisser deux entrees se disputer
            # le meme dump.
            collisions.append({"type": "identite", "garde": par_id[tid],
                               "ecarte": repo, "target_id": tid})
            continue
        slug = slug_affichage(repo)
        if slug in cibles:
            ancien = slug
            slug = "%s__%s" % (slug, tid[:6])
            collisions.append({"type": "slug", "slug": ancien, "repo": repo,
                               "renomme": slug})
        par_id[tid] = repo
        cibles[slug] = {
            "target_id": tid,
            "repo": repo,
            "url": url,
            "ordinal": ordinal,
            "priorite": e.get("priorite") if e.get("priorite") in PRIORITES else "contexte",
            "premiere_demande": str(e.get("premiere_demande") or "?"),
            "origine": str(e.get("origine") or "?"),
            "mentions_owner": int(e.get("mentions_owner") or 0),
            "mentions_agent": int(e.get("mentions_agent") or 0),
            "etat_ingestion": str(e.get("etat") or "?"),
            "detail": str(e.get("detail") or "-"),
        }
        ordinal += 1
    return {
        "schema_version": SCHEMA_VERSION,
        "generation_id": calcul_generation_id(cibles),
        "generated_at": generated_at,
        "source": source,
        "count": len(cibles),
        "collisions": collisions,
        "cibles": cibles,
    }


def ecrire_registre(chemin, doc: dict) -> Path:
    """Valide AVANT d'ecrire : on ne publie pas un registre qu'on refuserait."""
    valider_registre(doc)
    return ecrire_atomique(chemin, json.dumps(doc, ensure_ascii=False, indent=1))


# ── etat d'un dump ──────────────────────────────────────────────────────────
def chemin_manifeste(dump) -> Path:
    return Path(str(dump) + ".manifest.json")


# ── OU vivent les dumps ─────────────────────────────────────────────────────
# Mesure 2026-09-23 : sous `run_job online`, le clone passe enfin, mais le compte
# `LaForgeSbxOnline` n'a PAS le droit d'ecrire dans `docs/` ; il ecrit sur E:, et
# `LaForgeSbxOffline` (l'ingestion) y relit. Deplacer l'ecrivain seul aurait
# fabrique des faux ABSENT : trois lecteurs codaient `ROOT/docs` en dur.
#
# INTERRUPTEUR GLOBAL lu a chaque appel, jamais site par site : un fichier, une
# ligne par dossier supplementaire. Un fichier et non une variable
# d'environnement, parce que `run_job` ne transmet pas l'environnement.
INTERRUPTEUR_DUMPS = Path("sandbox") / "veille_dumps.dir"
_RACINE = Path(__file__).resolve().parents[1]


def nom_fichier_dump(nom: str) -> str:
    """Nom de fichier du dump d'une veille : `gitingest_veille_<nom>.txt`."""
    return "gitingest_veille_%s.txt" % nom


def dossiers_dumps(racine=None) -> list:
    """`[docs/, <dossiers de l'interrupteur>...]` — docs/ toujours en tete.

    Un interrupteur ILLISIBLE n'est pas un interrupteur absent : on le DIT, car
    les dumps qu'il designe deviennent invisibles et se liraient ABSENT.
    """
    racine = Path(racine) if racine else _RACINE
    dossiers = [racine / "docs"]
    try:
        lignes = (racine / INTERRUPTEUR_DUMPS).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return dossiers
    except OSError as exc:
        print("[registre] interrupteur %s ILLISIBLE (%s) : seuls les dumps de "
              "docs/ sont vus, ceux hors depot se liront ABSENT"
              % (INTERRUPTEUR_DUMPS, type(exc).__name__), flush=True)
        return dossiers
    for ligne in lignes:
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#") and Path(ligne) not in dossiers:
            dossiers.append(Path(ligne))
    return dossiers


def chemin_dump(nom: str, dossiers=None):
    """Copie existante la PLUS RECENTE du dump, ou None.

    Plusieurs copies peuvent coexister : un dump perime de docs/ re-dumpe sur E:
    (FILTRE_VERSION 2, 2026-09-23). L'ancienne est GELEE, jamais supprimee ; la
    plus recente la masque. A mtime egal, l'ordre des dossiers departage.
    """
    meilleur, meilleur_mtime = None, None
    for d in (dossiers if dossiers is not None else dossiers_dumps()):
        p = Path(d) / nom_fichier_dump(nom)
        try:
            mtime = p.stat().st_mtime
        except OSError:  # muet-ok : pas de copie ICI — cas normal ; aucune copie nulle part rend None, que l'appelant traite
            continue
        if meilleur is None or mtime > meilleur_mtime:
            meilleur, meilleur_mtime = p, mtime
    return meilleur


def _inscriptible(dossier: Path) -> bool:
    """Le compte COURANT peut-il creer un fichier ici ? Se MESURE, ne se deduit
    pas : le meme dossier est inscriptible pour un compte et refuse a l'autre."""
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(dossier), prefix=".sonde_", suffix=".tmp")
        os.close(fd)
        os.remove(tmp)
        return True
    except OSError:
        return False


def dossier_ecriture_dumps(nom: str, dossiers=None) -> Path:
    """Premier dossier INSCRIPTIBLE, hors depot d'abord (dernier declare en tete),
    docs/ en dernier recours — docs/ seul quand aucun interrupteur n'est pose.

    Mesure 2026-09-23 : ecrire « la ou le dump existe » envoyait le compte online
    re-ecrire un dump perime dans docs/, qu'il n'a pas le droit d'ecrire : le job
    mourait sur la premiere cible. `nom` reste dans la signature : l'appelant dit
    QUEL dump il ecrit, meme si le choix ne depend plus que des droits.
    """
    del nom
    dossiers = dossiers if dossiers is not None else dossiers_dumps()
    for d in reversed([Path(x) for x in dossiers]):
        if _inscriptible(d):
            return d
    return Path(dossiers[0])   # aucun : l'ecriture echouera et le DIRA


def noms_dumps(dossiers=None) -> list:
    """Noms de tous les dumps presents, tous dossiers confondus, sans doublon."""
    prefixe, suffixe = "gitingest_veille_", ".txt"
    vus = []
    for d in (dossiers if dossiers is not None else dossiers_dumps()):
        try:
            fichiers = sorted(Path(d).glob(prefixe + "*" + suffixe))
        except OSError as exc:
            print("[registre] dossier de dumps %s ILLISIBLE (%s)"
                  % (d, type(exc).__name__), flush=True)
            continue
        for p in fichiers:
            nom = p.name[len(prefixe):-len(suffixe)]
            if nom not in vus:
                vus.append(nom)
    return vus


# ── RATTACHER UN DUMP HISTORIQUE A SA CIBLE ───────────────────────────────────
# MESURE 2026-08-31 : 339 cibles au registre, 12 dumps dans `docs/`, et AUCUNE
# cible ne declarait `nom_dump` — le capteur ne surveillait donc rien.
#
# La PREUVE existe et n'est pas un nom approximatif : `forge_veille_clone_ingest`
# porte `REPOS`, qui associe chaque nom de dump historique a son URL. On resout
# donc nom -> URL -> URL canonique -> cible, jamais nom -> ressemblance.
MATCH, AMBIGU, ORPHELIN = "MATCH", "AMBIGU", "ORPHELIN"


def resoudre_dumps(noms_dumps, cibles: dict, noms_historiques: dict) -> dict:
    """{nom_dump: {etat, slug, target_id, url, preuve}} — TROIS etats.

    `noms_historiques` = {url canonique en minuscules: nom de dump}, la table de
    compatibilite existante. On l'inverse ici plutot que d'en ecrire une seconde.

    ORPHELIN n'est JAMAIS promu en MATCH par defaut. Rattacher un dump a la
    premiere cible venue ferait surveiller le mauvais depot pendant des mois, et
    l'erreur serait invisible : le capteur rendrait des verdicts parfaitement
    coherents sur une cible qui n'est pas la bonne.
    """
    par_nom: dict = {}
    for url, nom in (noms_historiques or {}).items():
        par_nom.setdefault(str(nom), []).append(str(url).lower())
    par_url: dict = {}
    for slug, c in (cibles or {}).items():
        par_url.setdefault(str((c or {}).get("url") or "").lower(), []).append(slug)

    out: dict = {}
    for nom in sorted(set(str(n) for n in (noms_dumps or []))):
        urls = par_nom.get(nom) or []
        if not urls:
            out[nom] = {"etat": ORPHELIN, "preuve": "aucune URL historique connue "
                                                    "pour ce nom de dump"}
            continue
        if len(set(urls)) > 1:
            out[nom] = {"etat": AMBIGU, "preuve": "%d URL historiques portent ce "
                                                  "nom: %s" % (len(set(urls)),
                                                               sorted(set(urls)))}
            continue
        url = urls[0]
        slugs = par_url.get(url) or []
        if not slugs:
            out[nom] = {"etat": ORPHELIN, "url": url,
                        "preuve": "URL absente du registre"}
        elif len(slugs) > 1:
            out[nom] = {"etat": AMBIGU, "url": url,
                        "preuve": "%d cibles portent cette URL: %s"
                                  % (len(slugs), sorted(slugs))}
        else:
            slug = slugs[0]
            out[nom] = {"etat": MATCH, "slug": slug, "url": url,
                        "target_id": (cibles[slug] or {}).get("target_id"),
                        "preuve": "URL historique -> cible unique"}
    # COLLISION : deux dumps qui pointeraient la meme cible. Aucun des deux ne
    # peut etre retenu — on ne devine pas lequel est le bon, on le SIGNALE.
    par_slug: dict = {}
    for nom, r in out.items():
        if r["etat"] == MATCH:
            par_slug.setdefault(r["slug"], []).append(nom)
    for slug, noms in par_slug.items():
        if len(noms) > 1:
            for nom in noms:
                out[nom] = {"etat": AMBIGU, "slug": slug,
                            "preuve": "collision: %s visent la meme cible"
                                      % sorted(noms)}
    return out


def rattacher_dumps(doc: dict, resolutions: dict) -> dict:
    """Nouveau registre avec `nom_dump` pose sur les seules cibles MATCH.

    DETERMINISTE et IDEMPOTENT : rejouer sur le registre produit rend un document
    identique, `generation_id` compris. Le schema n'est pas etendu — `nom_dump`
    est un champ que le registre acceptait deja ; seule sa PRESENCE change.

    Une cible SANS dump reste valide et simplement non suivie : une cible existe
    independamment d'un dump local, et confondre les deux ferait surveiller des
    depots dont rien n'a jamais ete rapatrie.
    """
    neuf = dict(doc)
    cibles = {slug: dict(c) for slug, c in (doc.get("cibles") or {}).items()}
    for nom, r in (resolutions or {}).items():
        if r.get("etat") != MATCH:
            continue
        slug = r.get("slug")
        if slug in cibles:
            cibles[slug]["nom_dump"] = nom
    neuf["cibles"] = cibles
    neuf["count"] = len(cibles)
    # L'empreinte suit le CONTENU : elle doit changer quand des rattachements
    # sont poses, et RESTER identique quand on rejoue sur un registre deja
    # rattache. C'est ce qui rend l'operation idempotente et verifiable.
    neuf["generation_id"] = calcul_generation_id(cibles)
    return neuf


# ── CHANGEMENT D'UN DEPOT, SANS CLONER ────────────────────────────────────────
# MESURE 2026-08-31 : `forge_veille_clone_ingest` et `forge_veille_github_direct`
# n'ont AUCUN importateur — la voie depot n'est pas une veille, c'est une commande
# qu'un humain lance. Pour qu'elle devienne recurrente sans re-cloner chaque
# heure, il faut savoir si le depot a bouge AVANT de le rapatrier.
#
# Le dernier HEAD ingere est deja persiste : le manifeste de dump porte `commit`
# depuis `b4310266f`. Aucun schema a creer, aucune base a ajouter.
NO_CHANGE, UPDATED, UNKNOWN = "NO_CHANGE", "UPDATED", "UNKNOWN"


def sha_ingere(dump):
    """Le commit du dernier dump, ou None si on ne peut pas le savoir.

    TROIS retours, jamais deux : un sha, `None` (manifeste absent ou illisible,
    ou commit note `inconnu`), et c'est l'appelant qui decide. Rendre `""` pour
    « pas pu lire » ferait passer un manifeste corrompu pour un depot jamais
    ingere, donc declencherait un clone complet a chaque tour.
    """
    try:
        m = json.loads(chemin_manifeste(Path(dump)).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return None
    if not isinstance(m, dict):
        return None
    sha = str(m.get("commit") or "").strip()
    return sha or None if sha != "inconnu" else None


def etat_cible(sha_distant, sha_local) -> tuple:
    """(etat, raison) parmi NO_CHANGE / UPDATED / UNKNOWN.

    UNKNOWN PRIME sur tout : un HEAD distant qu'on n'a pas pu lire ne prouve pas
    que le depot n'a pas bouge. Le confondre avec NO_CHANGE ferait un capteur qui
    se tait exactement quand le reseau tombe — la panne la plus banale — et la
    veille se croirait a jour indefiniment.

    `sha_local` absent et distant connu = UPDATED : jamais ingere, donc tout est
    neuf. C'est la seule asymetrie, et elle est volontaire.
    """
    d = str(sha_distant or "").strip()
    if not d:
        return UNKNOWN, "HEAD distant illisible : le depot n'est pas declare a jour"
    loc = str(sha_local or "").strip()
    if not loc:
        return UPDATED, "aucun dump ingere pour cette cible"
    if loc == d:
        return NO_CHANGE, "HEAD %s inchange" % d[:12]
    return UPDATED, "HEAD %s -> %s" % (loc[:12], d[:12])


def head_distant(url: str, lanceur=None) -> tuple:
    """(sha, raison) du HEAD distant, SANS cloner.

    `git ls-remote <url> HEAD` coute une requete la ou un clone coute le depot
    entier. C'est ce qui rend la recurrence tenable : mesure du 2026-08-31, le
    clone d'un seul depot prend 1,58 s sous `trusted` et ECHOUE sous `run_job`
    meme en `online` (0 fichier en 19 min) — le repeter chaque heure sur douze
    depots serait ingerable, et inutile puisque la plupart n'auront pas bouge.

    `lanceur` est injectable : les tests ne doivent joindre aucun reseau.
    GIT_TERMINAL_PROMPT=0 est OBLIGATOIRE — sans lui git attend une saisie qui
    ne viendra jamais et la commande PEND (piege deja paye sur le push).
    """
    if lanceur is None:
        def lanceur(cmd):  # noqa: PLW0127
            import os
            import subprocess  # noqa: PLC0415
            env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
            # `errors="replace"` : en mode texte SANS lui, un octet non decodable
            # dans la sortie fait planter le thread lecteur de subprocess, et la
            # detection de changement meurt sur un depot au nom exotique.
            return subprocess.run(cmd, capture_output=True, text=True,
                                  errors="replace", timeout=60, env=env)
    try:
        p = lanceur(["git", "ls-remote", str(url), "HEAD"])
    except Exception as exc:  # noqa: BLE001
        return None, "ls-remote impossible (%s)" % type(exc).__name__
    if getattr(p, "returncode", 1) != 0:
        return None, "ls-remote rc=%s: %s" % (getattr(p, "returncode", "?"),
                                              str(getattr(p, "stderr", ""))[:80])
    for ligne in str(getattr(p, "stdout", "") or "").splitlines():
        morceaux = ligne.split()
        if len(morceaux) >= 2 and morceaux[1].strip() == "HEAD":
            return morceaux[0].strip(), "HEAD lu"
    return None, "ls-remote sans ligne HEAD"


def etat_dump(dump, cible: dict, filtre_version: str,
              taille_min: int = 1000) -> tuple:
    """(etat, raison) parmi ABSENT / STALE / READY.

    Un dump sans manifeste est STALE et non READY : on ignore de quel commit il
    vient, donc toute connaissance qu'on en tirerait serait invérifiable. La
    consigne owner est explicite — une connaissance qu'on ne peut pas
    re-verifier contre sa source est une croyance.
    """
    p = Path(dump)
    try:
        if not p.exists():
            return ABSENT, "aucun dump"
        if p.stat().st_size <= taille_min:
            return ABSENT, "dump de %d o, sous le seuil" % p.stat().st_size
    except OSError as exc:
        return STALE, "dump illisible (%s)" % type(exc).__name__

    m = chemin_manifeste(p)
    try:
        manifeste = json.loads(m.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return STALE, "dump sans manifeste: provenance inconnue"
    except (OSError, ValueError) as exc:
        return STALE, "manifeste illisible (%s)" % type(exc).__name__
    if not isinstance(manifeste, dict):
        return STALE, "manifeste de type %s" % type(manifeste).__name__

    commit = str(manifeste.get("commit") or "").strip()
    if not commit or commit == "inconnu":
        return STALE, "commit source inconnu"
    if manifeste.get("target_id") != cible.get("target_id"):
        return STALE, ("manifeste target_id %s != cible %s"
                       % (manifeste.get("target_id"), cible.get("target_id")))
    if manifeste.get("url") != cible.get("url"):
        return STALE, "manifeste url %s != cible %s" % (manifeste.get("url"),
                                                        cible.get("url"))
    if str(manifeste.get("filtre_version")) != str(filtre_version):
        return STALE, ("filtre v%s, dump produit avec v%s"
                       % (filtre_version, manifeste.get("filtre_version")))
    return READY, "commit %s, filtre v%s" % (commit[:12], filtre_version)
