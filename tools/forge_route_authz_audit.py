#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_route_authz_audit.py — matrice d'autorisation des routes HTTP du hub.

__FORGE_COLOR__ = "immunitaire/matrice-autorisation-routes"

PHASE A : RECENSER, ne rien modifier.

CONSTAT QUI MOTIVE CET OUTIL (mesure 2026-09-02)
    `forge_videur` se declare « couche identite x access-control » et expose
    `authorize(agent, token, local, tool=...)`. Or le hub HTTP ne l'appelle
    JAMAIS : il ne demande que `resolve_identity` (« qui es-tu ») et `capture`
    (journal), pas « as-tu le droit ». Mesure : 81 routes, `_resolve_ring`
    appele 7 fois, `authorize` 0 fois depuis nokido_hub.
    Verifie en reel : `GET /api/services/list` rend HTTP 200 SANS jeton, et
    `GET /admin/run_job` rend 405 (methode) et non 401 (auth) -- la requete est
    donc ROUTEE avant tout controle.

TROIS ETATS, JAMAIS DEUX
    Une route sans garde detectee n'est PAS « publique » : elle est INCONNUE.
    Ne pas trouver d'appelant ne prouve pas qu'il n'y en a pas -- le journal du
    videur ne voit que les routes deja gardees, donc il est AVEUGLE aux autres.
    Chaque verdict porte donc sa PROVENANCE et son degre de certitude.

CE QUE L'OUTIL NE FAIT PAS
    Aucune requete reseau, aucune mutation, aucune modification du hub. Il lit
    le code. Le branchement de `authorize()` est une phase ULTERIEURE, et il
    devra passer par un mode SHADOW avant tout refus effectif -- armer un mur
    sans mesurer le trafic legitime, c'est l'erreur deja payee avec le mode M2M.

Usage : forge_route_authz_audit.py [--json <fichier>]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

__FORGE_COLOR__ = "immunitaire/matrice-autorisation-routes"

ROOT = Path(__file__).resolve().parent.parent
HUB = ROOT / "tools" / "nokido_hub.py"

# Marqueurs d'un controle d'acces DANS le corps du handler.
#
# ERREUR PAYEE LE 2026-09-02 : cette liste OMETTAIT `_admin_tok_ok`, la garde la
# plus utilisee du hub (15 routes, JWT HS256 + `required_scope`). L'audit a donc
# declare « aucune garde » sur `/api/services/shutdown_all` et `/api/sandbox/spawn`,
# qui refusent pourtant en 401 -- verifie en reel. Une sonde qui ne connait pas le
# vocabulaire du garde declare son absence : c'est le meme defaut que
# `_organ_by_text` refusant `SNC`, ou `findstr` ne voyant pas `tpm_sign`.
# LECON : l'analyse statique NE SUFFIT PAS. `--probe` mesure le comportement REEL.
# `peut_consommer_boite` AJOUTEE le 2026-09-22, le jour de l'armement de
# `/inbox/{agent_id}`. Sans elle, l'inventaire declarait `inbox_stream` « SANS
# garde » alors qu'une garde venait d'y etre posee -- un vocabulaire fige
# d'avance ne voit pas une garde qui arrive.
#
#     CALL_SITE != DECISION_SITE : la decision est passee par un nom que le
#     detecteur ignorait. On corrige le DETECTEUR, jamais l'inventaire.
#
# Troisieme fois ce jour-la que ce motif se paie. Toute nouvelle primitive de
# decision d'autorisation doit etre ajoutee ICI, source unique du vocabulaire :
# ce fichier existe precisement parce que des listes locales ont produit QUATRE
# faux verdicts.
GARDES = ("peut_consommer_boite",
          "_resolve_ring", "_admin_tok_ok", "_serve_guarded", "HUB_TOKEN",
          "_AGENT_TOKENS", "compare_digest", "Authorization", "CapabilityToken",
          "corrigibility_gate", "authorize(",
          # 2026-09-24 : garde posee A L'ENREGISTREMENT de la route (session UI du
          # portail + origine locale, ou jeton admin) -- voir `_GARDE_ENREGISTREMENT`.
          "_garde_ui", "autoriser_mutation_ui",
          # 2026-09-24 : route d'ORGANE, identite prouvee exigee (decision = _resolve_ring).
          "_exiger_identite")

# Une garde peut envelopper le handler DANS la declaration de route :
#     Route("/api/watch/create", _garde_ui(watch_create_api, "veille:creer"), ...)
# Le corps du handler n'en porte alors aucune trace. Sans cette lecture, l'audit
# prenait l'ENVELOPPE pour le handler et ratait la methode (GET par defaut) --
# CALL_SITE != DECISION_SITE, meme correction : le DETECTEUR, jamais l'inventaire.
_GARDE_ENREGISTREMENT = ("_garde_ui",)
_ROUTE = re.compile(
    r'Route\(\s*"([^"]+)"\s*,\s*(?:(%s)\(\s*)?(\w+)(?:\s*,\s*"[^"]*"\s*\))?'
    r'(?:\s*,\s*methods\s*=\s*(\[[^\]]*\]))?' % "|".join(_GARDE_ENREGISTREMENT))

# ── P1-E / P1-F (2026-09-21) : ROUTE GUARD != FUNCTION GUARD ──────────────
#
# CE QUI A ETE PAYE. Un inventaire ecrit le meme jour cherchait des NOMS de
# fonction (`_admin_tok_ok`, `authorize`, ...) et a declare « GARDE : AUCUNE »
# sur quatre handlers qui en portent une, ecrite INLINE sans fonction :
#
#     swarm_run · recon_run · ctf_run · auth_login
#
# `GARDES` ci-dessus les voyait DEJA. Le defaut n'etait pas dans le corps : un
# vocabulaire avait ete RECOPIE et perdu en route. La regle est ecrite mot pour
# mot dans `ci_local.py` a propos d'un autre vocabulaire -- « liste BLANCHE
# prise chez le producteur, jamais recopiee ». Ce module EST le producteur.
#
# TROIS ETATS, JAMAIS DEUX. `NOT_DETECTED` ne vaut pas `NO_GUARD` : l'analyse
# statique ne voit ni le middleware, ni le decorateur, ni le dispatch dynamique.
ETATS_GARDE = ("DETECTED", "NOT_DETECTED", "UNKNOWN")

# Marqueurs d'un REFUS effectif dans le corps. Sans refus visible, un handler
# qui manipule un jeton ne prouve pas qu'il ferme quoi que ce soit.
_REFUS = ("401", "403", "status_code=401", "status_code=403", "abort(",
          "raise HTTPException", "unauthorized", "forbidden", "PermissionError")

# Hotes que le corps traite comme « local ». `LOCAL_ONLY != TRUSTED` : le
# compte sandbox du hub atteint le loopback, et cela n'authentifie personne
# (directive owner 2026-09-18). Une garde qui les exempte reste DETECTED --
# elle existe -- mais elle est ouverte a tout appelant local SANS porteur, et
# ce fait doit VOYAGER avec le verdict au lieu d'etre perdu.
_HOTES_LOCAUX = ("127.0.0.1", "::1", "localhost", "0.0.0.0", "[::1]")


def classer_garde(corps: str) -> tuple:
    """Classe la garde d'un handler par son COMPORTEMENT, pas par un nom.

    Rend `(etat, notes)` ou `etat` est l'un de `ETATS_GARDE` et `notes` un
    tuple de marqueurs qualifiant la garde trouvee.

    DETECTED      un motif d'authentification ET un refus visible ;
    UNKNOWN       un motif d'authentification SANS refus visible -- le handler
                  touche a l'identite mais on ne voit pas ce qu'il en fait ;
    NOT_DETECTED  ni l'un ni l'autre. **Ce n'est PAS `NO_GUARD`** : middleware,
                  decorateur et dispatch dynamique sont hors de portee d'une
                  lecture de source.

    NOTES possibles :
      EXEMPTION_LOCALE   la condition de refus epargne un hote local
      CLIENT_VIDE        la chaine vide est rangee avec les hotes locaux ;
                         elle survient quand `request.client` est absent
      MOTIFS:<...>       les marqueurs de `GARDES` reellement trouves
    """
    texte = corps or ""
    motifs = [g for g in GARDES if g in texte]
    refus = any(r in texte for r in _REFUS)

    notes = []
    if motifs:
        notes.append("MOTIFS:" + "|".join(motifs))

    # L'exemption ne se cherche que dans les LIGNES DE CONDITION : un hote local
    # cite dans un commentaire ou une docstring n'exempte rien. Mesure du
    # 2026-09-21 : sans cette borne, toute route mentionnant `127.0.0.1` dans
    # son aide sortait « exemptee ».
    lignes_cond = [l for l in texte.splitlines()
                   if re.search(r"^\s*(?:el)?if\b|\bnot in\b|\bin\s*\(", l)]
    cond = "\n".join(lignes_cond)
    if any(h in cond for h in _HOTES_LOCAUX):
        notes.append("EXEMPTION_LOCALE")
        if re.search(r"""(?:,\s*|\(\s*)(''|"")\s*[,)]""", cond):
            notes.append("CLIENT_VIDE")

    if motifs and refus:
        return "DETECTED", tuple(notes)
    if motifs:
        return "UNKNOWN", tuple(notes)
    return "NOT_DETECTED", tuple(notes)


# Classement par EFFET, pas par nom : c'est l'effet qui decide du risque.
MUTANT = ("run_job", "spawn", "restart", "stop", "start", "shutdown", "boot",
          "toggle", "release", "emit", "ingest", "push", "gc", "set", "create",
          "kill", "delete", "write", "reload")
ADMIN = ("/admin/", "/api/services/", "/api/rings/", "/api/sandbox/",
         "/api/maintenance/")
PUBLIC_PLAUSIBLE = ("/health", "/static/", "/.well-known/")


def _handlers(src: str) -> dict:
    lignes = src.splitlines()
    idx = {}
    for i, l in enumerate(lignes):
        m = re.match(r"^\s*(?:async )?def (\w+)\(", l)
        if m:
            idx.setdefault(m.group(1), i)
    return idx, lignes


def _corps(nom: str, idx: dict, lignes: list) -> str | None:
    if nom not in idx:
        return None
    i = idx[nom]
    base = len(lignes[i]) - len(lignes[i].lstrip())
    out = [lignes[i]]
    for j in range(i + 1, len(lignes)):
        l = lignes[j]
        if l.strip() and (len(l) - len(l.lstrip())) <= base:
            break
        out.append(l)
    return "\n".join(out)


# Fichiers qui NOMMENT des routes sans jamais les appeler : le hub qui les
# declare, et les instruments qui les auditent. Mesure du 2026-09-02 : sans
# cette exclusion, `/api/push` sortait avec `forge_authz_matrice.py` pour
# appelant, et `/api/sandbox/spawn` avec `forge_route_authz_audit.py` -- les
# outils se citaient eux-memes, ce qui faisait passer des routes de UNKNOWN a
# AUTH. Un instrument qui se compte parmi ses propres mesures se trompe TOUJOURS
# du cote rassurant : il fabrique des appelants la ou il n'y en a pas.
# Verbes d'APPEL. Le producteur du vocabulaire est la seule source : le NR les
# consomme, il ne les redefinit pas.
_VERBES_APPEL = re.compile(
    r"\bfetch\(|\bEventSource\(|\baxios\.\w+\(|\brequests\.\w+\(|"
    r"\bhttpx\.\w+\(|\burlopen\(|\.open\(\s*['\"][A-Z]+['\"]")


# Une borne d'ORIGINE : comparaison de l'adresse de l'appelant a une liste
# d'hotes locaux, SUIVIE d'un refus. Exige les trois : lire `client.host` pour
# le journaliser n'est pas une garde.
_BORNE_HOTE = re.compile(r"client\.host|request\.client")
_BORNE_LOCAUX = re.compile(r"127\.0\.0\.1|::1|localhost")
_BORNE_REFUS = re.compile(r"status_code\s*=\s*(?:401|403)")


# Motifs de GARDES qui nomment un CREDENTIAL, et non une fonction de controle.
# Leur simple presence ne prouve rien : un handler peut les COMPARER ou les
# EMETTRE, et ce sont des contraires.
_GARDES_CREDENTIAL = ("HUB_TOKEN", "_AGENT_TOKENS", "CapabilityToken")
_COMPARAISON = re.compile(r"==|!=|\bin\b|\bis\b|compare_digest")

# Une verification DELEGUEE reste une verification. `/api/login` passe
# `agent_tokens=_AGENT_TOKENS` a `login_agent`, qui compare role_id/secret_id
# et leve `ValueError` -> 401. Exiger une comparaison SUR PLACE en faisait une
# route « sans garde » : faux negatif introduit par le correctif d'a cote,
# attrape par un NR existant le jour meme.
#
#     CALL_SITE != DECISION_SITE -- le credential voyage vers son juge.
_VERIF_DELEGUEE = re.compile(r"\blogin_agent\s*\(|agent_tokens\s*=")


def _credential_compare(corps: str, motif: str) -> bool:
    """Ce credential est-il COMPARE, ou seulement mentionne ?

    MESURE DU 2026-09-22. `GARDES` cherche des motifs TEXTUELS. Trois routes
    mentionnaient `HUB_TOKEN` pour l'INJECTER dans la page servie :

        tok = _AGENT_TOKENS.get("CLAUDE", "") or HUB_TOKEN or ""
        html = html.replace("__LAFORGE_BEARER__", tok)
        return HTMLResponse(html)

    L'audit les comptait GARDEES. Elles sont l'inverse : elles DISTRIBUENT le
    porteur a qui demande la page -- et les trois rendent 200 sans jeton.

        TEXT_OCCURRENCE != COMPARAISON
        un credential MENTIONNE peut etre un credential EMIS

    On exige donc un operateur de comparaison ou d'appartenance sur la ligne.
    Une affectation seule ne suffit plus.
    """
    for ligne in corps.splitlines():
        if motif not in ligne or ligne.strip().startswith("#"):
            continue
        if _COMPARAISON.search(ligne) or _VERIF_DELEGUEE.search(ligne):
            return True
    return False


_EMISSION = re.compile(r"\.replace\s*\(|f\"|\.format\s*\(|%\s*\(|\+\s*tok\b|\btok\s*\+")

# ── CLASSER CE QU'UNE REPONSE EXPOSE ──────────────────────────────────────
# Vocabulaire repris TEL QUEL de `config/share_policy.json`. Inventer un
# second jeu de classes creerait une verite a maintenir deux fois.
#
#     PUBLIC        deja publique ou publiable en l'etat
#     INTERNAL      interne non secret : code, mesures, journaux non sensibles
#     CONFIDENTIAL  configuration, TOPOLOGIE, enquete, memoire owner
#     SECRET        secrets, cles, JETONS, certificats, journal DPAPI
#
# Et son invariant s'applique ici sans changement :
#     UNKNOWN = REFUSE -- ne pas savoir n'est pas une autorisation.
_MARQ = {
    "pid": re.compile(r'"pid"\s*:\s*\d+'),
    "port": re.compile(r'"port"\s*:\s*\d+'),
    "chemin": re.compile(r"[A-Za-z]:\\\\|/home/|/Users/"),
    "agent": re.compile(r'"agent(_id|_name)?"\s*:\s*"'),
    "commande": re.compile(r'"(cmd|command|exe|argv)"\s*:'),
}
# Un porteur dans la reponse prime sur tout le reste.
# `re.I` passe en ARGUMENT : un `(?i)` en milieu d'expression est une erreur de
# compilation depuis Python 3.11, et elle tombe a la COLLECTE -- donc visible,
# jamais silencieuse.
_MARQ_SECRET = re.compile(
    r"Bearer\s+[A-Za-z0-9._\-]{16,}"
    r"|\"[^\"]*(token|secret|api[_-]?key|password)[^\"]*\"\s*:\s*\"[^\"]{16,}\""
    r"|[A-Za-z0-9]{56,}", re.I)


def classer_exposition(corps) -> dict:
    """Que REVELE cette reponse ? Rend des COMPTEURS et une classe.

    NE RECOPIE AUCUNE VALEUR -- ni en retour, ni en journal. C'est la regle
    owner (« tu ne lis, n'affiches et ne journalises JAMAIS la valeur d'un
    secret ») et c'est aussi ce qui empeche l'audit de devenir lui-meme un
    canal de divulgation : faute payee le 2026-09-21, une valeur de cle partie
    dans une sortie de mesure.

    `UNKNOWN` pour une reponse vide ou illisible : la ranger en PUBLIC la
    classerait du cote rassurant par defaut, ce que la constitution interdit
    (on classe par liste BLANCHE, jamais par liste noire).
    """
    if not corps or not str(corps).strip():
        return {"classe": "UNKNOWN", "marqueurs": {k: 0 for k in _MARQ},
                "raison": "reponse vide ou illisible -- non jugeable"}
    t = str(corps)
    marq = {k: len(rx.findall(t)) for k, rx in _MARQ.items()}
    if _MARQ_SECRET.search(t):
        return {"classe": "SECRET", "marqueurs": marq,
                "raison": "motif de credential dans la reponse"}
    chauds = [k for k in ("pid", "port", "commande", "chemin") if marq[k]]
    if chauds:
        return {"classe": "CONFIDENTIAL", "marqueurs": marq,
                "raison": "topologie exposee : " + ", ".join(chauds)}
    if marq["agent"]:
        return {"classe": "INTERNAL", "marqueurs": marq,
                "raison": "identites d'agents, sans topologie"}
    return {"classe": "INTERNAL", "marqueurs": marq,
            "raison": "aucun marqueur sensible detecte -- INTERNAL par defaut, "
                      "jamais PUBLIC : le caractere publiable est une DECISION"}


def _credential_emis(corps: str) -> bool:
    """Ce handler INJECTE-t-il un credential dans ce qu'il renvoie ?

    `config/share_policy.json` classe les jetons en `SECRET` et ecrit qu'ils
    « ne sortent JAMAIS ». Cette politique gouverne l'egress vers les
    providers ; AUCUN garde ne l'appliquait a une reponse HTTP.

    Mesure du 2026-09-22 : trois routes du hub servent un porteur a un
    appelant anonyme --

        tok = _AGENT_TOKENS.get("CLAUDE", "") or HUB_TOKEN or ""
        html = html.replace("__LAFORGE_BEARER__", tok)
        return HTMLResponse(html)

    On cherche donc : un motif de credential, PAS compare, et une construction
    de sortie (substitution, format, concatenation). La fonction ne lit ni
    n'expose aucune valeur -- elle juge la FORME du code.
    """
    for motif in _GARDES_CREDENTIAL:
        if motif not in corps or _credential_compare(corps, motif):
            continue
        for ligne in corps.splitlines():
            if motif in ligne and not ligne.strip().startswith("#"):
                # le credential est affecte : la sortie est-elle construite avec ?
                if _EMISSION.search(corps):
                    return True
    return False


def _borne_loopback(corps: str) -> bool:
    """La route refuse-t-elle un appelant non local ?

    MESURE DU 2026-09-22. `/debug/stacks` rend 403 hors loopback, et l'audit la
    classait NUE : `GARDES` ne contient que des NOMS DE FONCTIONS, aucun motif
    de borne d'origine. Une route qui a une politique etait donc rangee avec
    celles qui n'en ont aucune.

        NU != VOLONTAIREMENT EXEMPTE

    Ampleur mesuree : UNE route sur 47. Ce qui compte n'est pas le nombre mais
    la categorie -- on travaille sinon sur la mauvaise.

    ET CE N'EST PAS UNE AUTHENTIFICATION : `LOCAL_ONLY != TRUSTED` (directive
    owner du 2026-09-18). La garde est donc NOMMEE `borne_loopback`, jamais
    fondue dans les gardes de porteur -- sans quoi l'inventaire compterait une
    route authentifiee de plus qu'il n'y en a.
    """
    return bool(_BORNE_HOTE.search(corps) and _BORNE_LOCAUX.search(corps)
                and _BORNE_REFUS.search(corps))


def sonder_exposition(routes: list, base: str = "http://127.0.0.1:8766",
                      octets_max: int = 200_000, timeout: float = 6.0) -> dict:
    """Classe ce que chaque route REVELE. GET seulement, corps BORNE.

    Le corps n'est jamais ecrit sur disque ni rendu : il est classe en memoire
    par `classer_exposition`, qui ne produit que des compteurs. L'audit ne doit
    pas devenir le canal de divulgation qu'il cherche.

    BORNE DITE : 200 000 octets et 6 s par route. Une reponse plus longue est
    classee sur ce qu'on a LU, et le dit (`tronquee: True`) -- une borne
    annonce combien, jamais seulement « trop ». Un flux SSE qui n'emet rien
    sort en `UNKNOWN`, pas en « sain ».
    """
    import socket
    from urllib.parse import urlsplit

    u = urlsplit(base)
    hote, port = u.hostname or "127.0.0.1", u.port or 80
    out = {}
    for r in routes:
        if "GET" not in r["methodes"] or "{" in r["route"]:
            continue          # parametre : on n'invente pas de valeur
        s = None
        try:
            s = socket.create_connection((hote, port), timeout=timeout)
            s.sendall((f"GET {r['route']} HTTP/1.1\r\nHost: {hote}:{port}\r\n"
                       "LaForge-Agent-Name: AUDIT_PROBE\r\n"
                       "Connection: close\r\n\r\n").encode())
            s.settimeout(timeout)
            buf = b""
            while len(buf) < octets_max:
                try:
                    c = s.recv(16384)
                except socket.timeout:
                    break
                if not c:
                    break
                buf += c
            brut = buf.decode("latin-1", "replace")
            corps = brut.split("\r\n\r\n", 1)[1] if "\r\n\r\n" in brut else ""
            # LE STATUT AVANT LE CORPS. Une route qui REFUSE n'a rien montre :
            # classer le corps de son 401 la rangeait en INTERNAL, c'est-a-dire
            # du cote rassurant. Mesure du 2026-09-22 : `/admin/heap`,
            # `/api/audit/recent` et `/api/ring_buffer/stats` -- trois routes
            # GARDEES -- ressortaient « aucun marqueur sensible detecte ».
            #
            #     UN REFUS N'EST PAS UNE ABSENCE D'EXPOSITION
            statut = 0
            ligne1 = brut.split("\r\n", 1)[0]
            parts = ligne1.split(" ")
            if len(parts) >= 2 and parts[1].isdigit():
                statut = int(parts[1])
            if statut != 200:
                v = {"classe": "NON_MESUREE", "marqueurs": {},
                     "raison": "la route n'a pas rendu 200 (HTTP %s) : elle n'a "
                               "rien expose, ce qu'elle exposerait reste inconnu"
                               % (statut or "sans statut")}
            else:
                v = classer_exposition(corps)
            v["http"] = statut
            v["octets_lus"] = len(buf)
            v["tronquee"] = len(buf) >= octets_max
            out[r["route"]] = v
        except Exception as e:  # noqa: BLE001
            out[r["route"]] = {"classe": "UNKNOWN", "marqueurs": {},
                               "raison": "injoignable/illisible: %s" % type(e).__name__}
        finally:
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass      # muet-ok : mesure deja prise
    return out


def _appel_dans_observateur(texte: str, motif: str) -> bool:
    """Un fichier qui DECLARE une route peut aussi l'APPELER.

    MESURE DU 2026-09-22. `nokido_hub.py` portait le commentaire « declare les
    routes, ne les appelle pas ». C'est FAUX : `/api/mcp/flags` y a quatre
    occurrences, et elles ne se valent pas --

        L2141  fetch('/api/mcp/flags',{method:'POST'})   APPEL (JS inline)
        L3209  commentaire
        L3281  commentaire citant le JS
        L6060  Route("/api/mcp/flags", ...)              DECLARATION

    Ecarter le FICHIER pour eviter l'auto-reference ecartait donc aussi
    l'appelant, et l'audit rendait « AUCUN appelant trouve » sur une route qui
    en a un. Ce n'est pas anodin : la garde posee le 2026-09-21 sur cette route
    exacte, au motif qu'elle n'avait aucun appelant, a CASSE un bouton de
    l'interface.

        DECLARER UNE ROUTE != NE PAS L'APPELER

    On ne retire pas le fichier des observateurs -- on recolterait la ligne
    `Route(...)` et les commentaires, soit un appelant fantome sur les 83
    routes. On ecarte le VOCABULAIRE et on lit les APPELS.
    """
    for ligne in texte.splitlines():
        if motif not in ligne:
            continue
        nu = ligne.lstrip()
        if nu.startswith("#") or "Route(" in ligne:
            continue          # declaration ou commentaire : pas un appel
        if _VERBES_APPEL.search(ligne):
            return True
    return False


_OBSERVATEURS = frozenset({
    # ATTENTION : ces fichiers sont ecartes pour leur VOCABULAIRE (declarations
    # de routes, commentaires, tables d'audit), PAS parce qu'ils n'appellent
    # rien. `_appel_dans_observateur` y cherche les appels reels.
    "nokido_hub.py",                 # declare les routes ET en appelle en JS inline
    "forge_route_authz_audit.py",    # cet inventaire
    "forge_authz_matrice.py",        # la matrice candidate
    "forge_authz_shadow.py",         # l'observation SHADOW
})


def _appelants(chemin: str) -> list:
    """Qui NOMME cette route dans le depot ? Borne HAUTE, jamais une preuve d'appel."""
    motif = chemin.split("{")[0].rstrip("/") or chemin
    if len(motif) < 4:
        return []
    trouves = []
    for zone, exts in (("app", ("*.py",)), ("tools", ("*.py",)),
                       ("app/web_hub", ("*.py", "*.html", "*.js")),
                       ("proxy_deno", ("*.ts",)), ("static", ("*.js", "*.html"))):
        d = ROOT / zone
        if not d.is_dir():
            continue
        for ext in exts:
            for p in d.rglob(ext):
                try:
                    texte = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue      # muet-ok : illisible, compte comme non vu
                if p.name in _OBSERVATEURS:
                    # vocabulaire ecarte, APPELS conserves
                    if _appel_dans_observateur(texte, motif):
                        trouves.append(str(p.relative_to(ROOT)).replace("\\", "/"))
                    continue
                if motif in texte:
                    trouves.append(str(p.relative_to(ROOT)).replace("\\", "/"))
    return sorted(set(trouves))[:6]


def auditer(avec_appelants: bool = True) -> dict:
    """Inventaire des routes et de leurs gardes.

    `avec_appelants=False` saute la recherche d'appelants (un balayage du depot par
    route, ~29 s pour 81 routes). La CI n'en a pas besoin et un test lent finit
    desactive ; le rapport en ligne de commande, lui, la garde.
    """
    src = HUB.read_text(encoding="utf-8", errors="replace")
    idx, lignes = _handlers(src)
    routes = _ROUTE.findall(src)
    # DECISION EXPLICITE par route (exposition + authentification), prise chez son
    # producteur `forge_authz_shadow.DECLARE` -- jamais recopiee ici. Illisible = None
    # pour toutes, et le rapport le DIT : une declaration absente n'est pas « aucune ».
    try:
        from nokido_agent.app.forge_authz_shadow import DECLARE as _declare
        declarations_lisibles = True
    except Exception:  # noqa: BLE001
        _declare, declarations_lisibles = {}, False
    out = []
    for chemin, enveloppe, handler, methodes in routes:
        c = _corps(handler, idx, lignes)
        if enveloppe:
            garde, certitude = enveloppe, "garde posee a l'enregistrement de la route"
        elif c is None:
            garde, certitude = "ILLISIBLE", "handler introuvable — sonde aveugle"
        else:
            trouvees = [g for g in GARDES
                        if g in c
                        and (g not in _GARDES_CREDENTIAL or _credential_compare(c, g))]
            garde = trouvees[0] if trouvees else None
            if garde is None and _borne_loopback(c):
                # Une politique d'ORIGINE, nommee pour ce qu'elle est.
                garde = "borne_loopback"
            certitude = "corps lu"
        meth = json.loads(methodes.replace("'", '"')) if methodes else ["GET"]
        mutante = any(m in chemin.lower() or m in handler.lower() for m in MUTANT) \
            or any(x in meth for x in ("POST", "PUT", "DELETE", "PATCH"))
        admin = any(chemin.startswith(a) for a in ADMIN)
        out.append({
            "route": chemin, "methodes": meth, "handler": handler,
            "garde_detectee": garde, "certitude": certitude,
            "classe": "ADMIN" if admin else ("MUTANTE" if mutante else "LECTURE"),
            "public_plausible": any(chemin.startswith(p) for p in PUBLIC_PLAUSIBLE),
            "declaration": (dict(_declare[chemin]) if chemin in _declare else None)
            if declarations_lisibles else "ILLISIBLE",
            "appelants_dans_le_depot": _appelants(chemin) if avec_appelants else None,
            # Volontairement NON renseignes : ils exigent une decision owner.
            "tool_propose": None, "ring_min": None, "scopes": None,
            "verdict": "UNKNOWN — a decider, DENY par defaut",
        })
    return {"source": str(HUB.relative_to(ROOT)), "routes": out}


# --------------------------------------------------------------------------- #
# Surface MCP -- l'autre moitie du probleme
# --------------------------------------------------------------------------- #

# `app/forge_cai_bridge.py` DEPORTE hors du coeur (2026-09-27, depot prive
# laforge-redteam) : ne plus l'attendre ici. ABSENT != cassee -- une source deportee
# n'est pas illisible ; en lab actif elle vit dans redteam/, hors scan du coeur.
MCP_SOURCES = ("app/mcp_server_tools.py", "app/patch.py",
               "tools/forge_gemini_mcp_connector.py")

# Motifs de garde propres a la surface MCP.
#
# LES GARDES NE SONT PAS TOUS DU MEME TYPE, et l'oublier fabrique de fausses
# alertes. Mesure 2026-09-02 : `file_read` / `file_write` n'ont aucune capability
# mais sont proteges par `.mcpignore` (liste de chemins interdits) et par la
# resolution `_res()`. Les compter comme « sans garde » aurait produit l'annonce
# « les tools d'ecriture de fichiers sont ouverts » -- fausse, et c'est exactement
# le faux negatif deja paye le 2026-09-01 en omettant `_admin_tok_ok`.
GARDES_MCP = (
    # capability / identite
    "_require_capability", "require_capability", "capability",
    "authorize(", "_admin_tok_ok", "ring",
    # protection par CHEMIN (autre famille, tout aussi reelle)
    "_is_prot", "mcpignore", "_res(",
)


def auditer_tools_mcp() -> dict:
    """Recense les tools MCP et leur garde. AST, pas regex.

    POURQUOI CE PENDANT EXISTE : l'audit des routes HTTP ne couvrait que
    `tools/nokido_hub.py`, soit 81 points d'entree sur environ 570 declares dans le
    depot. La surface MCP -- celle que tout agent connecte peut appeler -- n'y etait
    PAS. Annoncer « toutes les routes sont identifiees » sur cette base aurait ete
    faux.

    L'AST evite le faux positif paye en regex : un decoupage sur `@mcp.tool()`
    ramassait `_authority_log`, qui n'est pas un tool mais une fonction voisine.
    """
    import ast as _ast

    out = []
    for rel in MCP_SOURCES:
        p = ROOT / rel
        if not p.exists():
            out.append({"source": rel, "etat": "ABSENT"})
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        try:
            arbre = _ast.parse(src)
        except SyntaxError as e:
            # ILLISIBLE n'est pas VIDE : un fichier non analyse doit se voir.
            out.append({"source": rel, "etat": "ILLISIBLE", "detail": str(e)[:120]})
            continue
        lignes = src.splitlines()
        for n in _ast.walk(arbre):
            if not isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                continue
            est_tool = False
            for d in n.decorator_list:
                cible = d.func if isinstance(d, _ast.Call) else d
                nom = getattr(cible, "attr", getattr(cible, "id", ""))
                if nom == "tool":
                    est_tool = True
            if not est_tool:
                continue
            fin = getattr(n, "end_lineno", n.lineno)
            corps = "\n".join(lignes[n.lineno - 1:fin])
            trouvees = [g for g in GARDES_MCP if g in corps]
            out.append({
                "source": rel, "tool": n.name, "ligne": n.lineno,
                "garde_detectee": trouvees[0] if trouvees else None,
                # Une lecture d'etat n'est pas une mutation : la classe oriente la
                # DECISION, elle ne la prend pas.
                "classe": "LECTURE" if any(
                    n.name.endswith(s) or n.name.startswith(s)
                    for s in ("_status", "_list", "status", "list_", "search", "recent")
                ) else "ACTION",
            })
    tools = [t for t in out if "tool" in t]
    return {
        "tools": len(tools),
        "gardes": sum(1 for t in tools if t["garde_detectee"]),
        "sans_garde": [t["tool"] for t in tools if not t["garde_detectee"]],
        "actions_sans_garde": [t["tool"] for t in tools
                               if not t["garde_detectee"] and t["classe"] == "ACTION"],
        "illisibles": [t for t in out if t.get("etat") in ("ILLISIBLE", "ABSENT")],
        "detail": out,
    }


def prober(routes: list, base: str = "http://127.0.0.1:8766") -> dict:
    """Mesure le comportement REEL, sans jeton. GET SEULEMENT.

    Aucune route POST/PUT/DELETE n'est appelee : prouver qu'une mutation
    s'execute exigerait de la declencher. Un `405` ne prouve d'ailleurs RIEN
    sur la securite -- il dit seulement que la methode ne correspond pas.
    """
    import socket
    from urllib.parse import urlsplit

    u = urlsplit(base)
    hote, port = u.hostname or "127.0.0.1", u.port or 80

    def _ligne_de_statut(chemin: str, timeout: float = 12.0):
        """Code HTTP lu sur la PREMIERE LIGNE, sans consommer le corps.

        Pourquoi pas `urlopen` : il attend les en-tetes, et un flux SSE dont le
        serveur n'emet ses en-tetes qu'au premier evenement le fait EXPIRER.
        Mesure 2026-09-02 : dix routes sortaient ainsi en `INJOIGNABLE`, lu
        comme « pas 200 donc protege » -- alors que neuf rendaient `200 OK`
        sans le moindre jeton. L'instrument sous-estimait l'ouverture, et il le
        faisait du cote rassurant.
        """
        s = None
        try:
            s = socket.create_connection((hote, port), timeout=timeout)
            # S'ANNONCER. Mesure du 2026-09-02 : les sondes de cet audit
            # apparaissaient dans le journal d'observation comme des appelants
            # ANONYMES -- trois d'entre elles ont ete relevees comme « appels
            # non authentifies sur /mcp » avant qu'on ne reconnaisse leur
            # signature (une rafale de routes dans la meme seconde). Un
            # instrument qui se mesure lui-meme fabrique les anomalies qu'il
            # rapporte ; c'est la meme faute que les appelants du depot ou ces
            # fichiers se citaient eux-memes.
            # Cet en-tete n'AUTHENTIFIE rien -- un nom sans jeton degrade
            # l'identite au plancher anti-spoof, et c'est voulu : la sonde doit
            # rester non authentifiee pour mesurer ce qu'un anonyme obtient.
            # Il sert a ETIQUETER la ligne de journal, pas a obtenir un droit.
            s.sendall((f"GET {chemin} HTTP/1.1\r\nHost: {hote}:{port}\r\n"
                       "Accept: text/event-stream\r\n"
                       "LaForge-Agent-Name: AUDIT_PROBE\r\n"
                       "Connection: close\r\n\r\n").encode())
            s.settimeout(timeout)
            buf = b""
            while b"\r\n" not in buf and len(buf) < 200:
                c = s.recv(1)
                if not c:
                    break
                buf += c
            ligne = buf.decode("latin-1").strip()
            parts = ligne.split(" ")
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
            return f"SANS_LIGNE_DE_STATUT:{ligne[:40]!r}" if ligne else "AUCUNE_REPONSE"
        except socket.timeout:
            return f"PAS_DE_STATUT_EN_{timeout:.0f}S"
        except Exception as e:  # noqa: BLE001
            return f"INJOIGNABLE:{type(e).__name__}"
        finally:
            if s is not None:
                try:
                    s.close()
                except OSError:  # muet-ok : fermeture best-effort, mesure deja prise
                    pass

    out = {}
    for r in routes:
        if "GET" not in r["methodes"] or "{" in r["route"]:
            continue          # parametre : on n'invente pas de valeur
        out[r["route"]] = _ligne_de_statut(r["route"])
    return out


def classer_sonde(code) -> str:
    """Code HTTP obtenu SANS jeton -> verdict d'authentification.

    CINQ etats, et chacun a ete paye :

    - `OUVERTE` (200) : servie sans identite.
    - `REFUSEE_AUTH` (401/403) : la seule preuve positive de protection.
    - `REDIRECTION` (3xx) : le verdict est AU BOUT, pas ici. Mesure du
      2026-09-02 : /forge/postal, /forge/rag et /forge/swarm rendent 302 puis
      401. Un client qui SUIT les redirections voit 401, un client qui ne les
      suit pas voit 302 -- les ranger avec les 200 aurait annonce trois routes
      ouvertes qui ne le sont pas. Deux instruments, deux verdicts : c'est la
      redirection qu'il fallait NOMMER, pas l'un des deux qu'il fallait croire.
    - `ABSENTE` (404).
    - `INDETERMINEE` : 405, 4xx divers, 5xx, timeout. Ne dit RIEN de l'auth.

    La version binaire d'origine (200 vs « refusees ») rangeait 404, 405, 5xx
    et les timeouts du cote rassurant : elle SURESTIMAIT la protection, du cote
    qui arrange. Un instrument qui se trompe doit se tromper en accusant, pas
    en absolvant.
    """
    if code == 200:
        return "OUVERTE"
    if code in (401, 403):
        return "REFUSEE_AUTH"
    if isinstance(code, int) and 300 <= code < 400:
        return "REDIRECTION"
    if code == 404:
        return "ABSENTE"
    return "INDETERMINEE"

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--json", type=Path, help="ecrit la matrice complete")
    p.add_argument("--probe", action="store_true",
                   help="mesure le code HTTP REEL sans jeton (GET seulement)")
    p.add_argument("--exposition", action="store_true",
                   help="classe ce que chaque reponse REVELE (compteurs, aucune valeur)")
    a = p.parse_args(argv)
    r = auditer()
    if a.probe:
        mesures = prober(r["routes"])
        # QUATRE etats, jamais deux. La version binaire (200 vs « refusees »)
        # rangeait 404, 405, 5xx et INJOIGNABLE du cote rassurant : elle
        # SURESTIMAIT la protection, alors que la docstring de `prober` dit
        # elle-meme qu'un 405 ne prouve rien sur la securite. Un code qui
        # contredit sa propre documentation se lit dans le sens qui arrange.
        seaux = {"OUVERTE": [], "REFUSEE_AUTH": [], "REDIRECTION": [],
                 "ABSENTE": [], "INDETERMINEE": []}
        for x in r["routes"]:
            c = mesures.get(x["route"])
            if c is None:
                continue
            x["http_sans_jeton"] = c
            seau = classer_sonde(c)
            x["sonde_verdict"] = seau
            seaux[seau].append((x["route"], x["classe"], c))
        ouvertes = seaux["OUVERTE"]
        total = sum(len(v) for v in seaux.values())
        print(f"\n=== SONDE REELLE (GET sans jeton) : {total} routes sondees "
              f"sur {len(r['routes'])} declarees ===")
        print(f"  NON SONDEES (POST/PUT/DELETE ou chemin parametre) : "
              f"{len(r['routes']) - total}")
        print("    -> etat INCONNU, et assume : declencher une mutation pour la")
        print("       mesurer couterait plus cher que l'ignorance.")
        for seau in ("OUVERTE", "REFUSEE_AUTH", "REDIRECTION", "ABSENTE", "INDETERMINEE"):
            items = seaux[seau]
            print(f"\n  {seau} ({len(items)}) :")
            for route, classe, c in sorted(items, key=lambda z: (z[1], z[0])):
                print(f"    [{classe:8}] {route}  <- {c}")
        sensibles = [t for t in ouvertes if t[1] in ("ADMIN", "MUTANTE")]
        print(f"\n  >>> OUVERTES ET SENSIBLES : {len(sensibles)}")
        for route, classe, _ in sorted(sensibles):
            print(f"      [{classe}] {route}")
        print("  NB : un 200 en LECTURE n'est pas forcement une faille — il l'est")
        print("  s'il expose de l'information operationnelle. C'est une DECISION.")
    if a.exposition:
        vues = sonder_exposition(r["routes"])
        par = {}
        for x in r["routes"]:
            v = vues.get(x["route"])
            if v is None:
                continue
            x["exposition"] = v
            par.setdefault(v["classe"], []).append((x["route"], v))
        total = sum(len(z) for z in par.values())
        print(f"\n=== EXPOSITION MESUREE : {total} routes sur {len(r['routes'])} ===")
        print(f"  NON MESUREES (POST ou chemin parametre) : {len(r['routes']) - total}")
        print("  Vocabulaire de config/share_policy.json. AUCUNE valeur n'est lue,")
        print("  rendue ni ecrite : seulement des compteurs et une raison.")
        # ordre DECROISSANT de sensibilite : ce qui compte se lit en premier
        for classe in ("SECRET", "CONFIDENTIAL", "INTERNAL", "PUBLIC",
                       "UNKNOWN", "NON_MESUREE"):
            items = par.get(classe) or []
            print(f"\n  {classe} ({len(items)}) :")
            for route, v in sorted(items):
                tr = " [TRONQUEE]" if v.get("tronquee") else ""
                print(f"    {route:34} {v['raison'][:52]}{tr}")
        sec = par.get("SECRET") or []
        if sec:
            print(f"\n  >>> {len(sec)} route(s) revelent un motif de CREDENTIAL.")
            print("      `config/share_policy.json` : SECRET « ne sort JAMAIS ».")
    rs = r["routes"]
    par_classe = Counter(x["classe"] for x in rs)
    sans = [x for x in rs if not x["garde_detectee"]]
    orphelines = [x for x in sans if not x["appelants_dans_le_depot"]]
    print(f"routes                     : {len(rs)}")
    print(f"  avec garde detectee      : {sum(1 for x in rs if x['garde_detectee'])}")
    print(f"  SANS garde detectee      : {len(sans)}")
    print(f"  classes                  : {dict(par_classe)}")
    print(f"\nSANS garde ET sensibles (ADMIN/MUTANTE) :")
    for x in sorted(sans, key=lambda z: (z["classe"], z["route"])):
        if x["classe"] in ("ADMIN", "MUTANTE"):
            app = ", ".join(x["appelants_dans_le_depot"]) or "AUCUN appelant trouve"
            print(f"  [{x['classe']:8}] {x['route']:32} {','.join(x['methodes']):18} <- {app[:70]}")
    print(f"\nSANS garde et SANS appelant trouve : {len(orphelines)}")
    print("  ATTENTION : « aucun appelant trouve » ne veut PAS dire « personne ne")
    print("  l'appelle » — un client externe, un navigateur ou un script hors depot")
    print("  n'apparait pas ici. Ces routes sont UNKNOWN, pas mortes.")
    if a.json:
        a.json.write_text(json.dumps(r, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\nmatrice ecrite -> {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
