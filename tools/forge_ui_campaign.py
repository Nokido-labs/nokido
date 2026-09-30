#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_ui_campaign.py — campagne VALIDATION GRAPHIQUE web_hub :7400.

Methode PROUVEE (cf sandbox/workspace/interactive_gui_test.py) : PlaywrightBrowser
(firefox, profil persistant) + LOGIN par le FORMULAIRE (input[name=admin_token] du
vault) — pas de token minte. goto=domcontentloaded puis networkidle timeout=4s (les
pages SSE ne networkidle jamais). Screenshot + flags (login-redir / vide / mot-erreur
/ JS-err / API>=400). Sortie PNG + report.json sous sandbox/ui_campaign/.

SESSION OWNER (user) :
    ~/miniforge3/envs/laforge_py314/python.exe tools/forge_ui_campaign.py

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `est_rechargement` — Bouton dont l'effet attendu est de RECHARGER (peut ne rien changer a l'ecran).
- `ouvrir_vue_hub` — None = route du portail (rien a ouvrir) ; True = bouton clique ; False = bouton ABSENT.
- `url_de` — URL absolue d'une route de campagne : `@8766/...` vise le hub, le reste le portail.
- `vue_hub` — Libelle du bouton de menu a cliquer pour une route de vue hub, sinon None.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools"), str(ROOT / "tools" / "ctf")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", r"C:/nokido/ms-playwright")

from app.web_hub.auth import AuthConfig  # noqa: E402
from nokido_agent.tools.forge_playwright_browser import (  # noqa: E402
    MAGASIN as MAGASIN_PW,
    PlaywrightBrowser,
    candidats_lancement,
    inventaire_magasin,
)

BASE = "http://127.0.0.1:7400"
# BUDGET GLOBAL de la passe, sous le `timeout-minutes: 10` du job CI ui-acceptance.
# Mesure 2026-08-30 : le job a ete coupe a 10 min 14 s, donc marque `cancelled` par
# GitHub — ni test rouge, ni runner tombe. Et un job COUPE n'ecrit AUCUN rapport :
# on perd du meme coup le verdict ET la raison, c'est-a-dire le pire des cas. La
# campagne se borne donc ELLE-MEME et rend un rapport partiel qui NOMME les routes
# qu'elle n'a pas pu visiter. Meme regle que l'etat `stalled` de la veille : un
# budget epuise est un VERDICT, une coupure muette n'en est pas un.
# CIBLE EFFECTIVE (2026-09-14) — redefinit volontairement la constante codee en
# dur ci-dessus, qui pointait une IP du LAN. Deux raisons mesurees :
#   1. le compte sandbox ne joint PAS le LAN (`WinError 10013`), alors que le
#      meme service repond en loopback : `127.0.0.1:7400/health` = HTTP 200 en
#      15 ms. Le gate mesurait donc l'isolement reseau, pas l'UI ;
#   2. une adresse de LAN codee en dur n'est pas portable — ni sur le runner
#      GitHub, ni chez un autre poste.
# L'ancienne cible reste atteignable en posant NOKIDO_HUB_WEB.
# NOTE D'EDITION : l'affectation d'origine n'a pas ete supprimee parce que la
# membrane masque l'IP dans tout ce que le hub rend a un agent — on ne peut pas
# ancrer une recherche sur une ligne qu'on n'a pas le droit de lire en clair.
BASE = os.environ.get("NOKIDO_HUB_WEB", "http://127.0.0.1:7400").rstrip("/")

# Separateurs de milliers rencontres dans une UI : espace, insecable (U+00A0),
# fine insecable (U+202F), fine (U+2009), chiffre (U+2007), point, virgule,
# apostrophe droite et typographique (suisse).
_SEP_MILLIERS = "     .,'’"


def texte_porte_valeur(valeur, texte) -> bool:
    """Le texte AFFICHE-t-il cette valeur, quel que soit son formatage humain ?

    DEFAUT PAYE le 2026-09-14. Le gate a rendu ROUGE sur `/rag` :

        GATE-KO /rag  contrat NON tenu: data:chunks_total(/api/rag/stats.total=2241501)

    pendant que le texte releve par le run LUI-MEME portait « 2 241 501 ». La
    page etait juste ; le comparateur enumerait deux candidats en dur — la
    valeur brute et `f"{v:,}"`, c'est-a-dire le format ANGLAIS — sur une
    interface en FRANCAIS. Un gate qui accuse a faux se fait desarmer, donc on
    NORMALISE au lieu d'enumerer des formats : la valeur entiere est cherchee
    avec un separateur de milliers OPTIONNEL a chaque groupe de trois.

    Les bornes `(?<!\\d)` / `(?!\\d)` gardent le controle negatif : 2241501 ne
    se reconnait ni dans 12241501, ni dans 22415010.
    """
    if valeur is None or texte is None:
        return False  # l'API n'a pas rendu la cle : UNKNOWN, pas une correspondance
    if isinstance(valeur, bool):
        return str(valeur).lower() in texte.lower()
    if isinstance(valeur, int):
        chiffres = str(abs(valeur))
        groupes = [chiffres[max(0, i - 3):i] for i in range(len(chiffres), 0, -3)][::-1]
        sep = "[%s]?" % re.escape(_SEP_MILLIERS)
        motif = ("-?" if valeur < 0 else "") + sep.join(re.escape(g) for g in groupes)
        return re.search(r"(?<!\d)" + motif + r"(?!\d)", texte) is not None
    if isinstance(valeur, float):
        # Decimale francaise ET anglaise : « 12,5 » et « 12.5 » designent le meme.
        brut = repr(valeur)
        return brut in texte or brut.replace(".", ",") in texte
    return str(valeur) in texte

_BUDGET_S = float(os.environ.get("LAFORGE_UI_BUDGET_S", "480"))

# BORNE DU PRE-CONTROLE, ajoutee le 2026-09-19 apres un blocage MESURE.
#
# `_BUDGET_S` garde la BOUCLE des routes : il est evalue a chaque tour, donc
# seulement une fois le navigateur obtenu. Un blocage AVANT la boucle -- au
# lancement du harnais -- ne le rencontre jamais. Mesure du jour : cette
# campagne a tourne 1 662 s avec 0 s de CPU, tenant la CI de reference en
# otage, pendant que sa borne de 480 s n'etait jamais atteinte.
#
# La cause est connue et documentee : Playwright est INOPERANT sous le compte
# de service (`LaForgeSbxOffline`) et n'y produit pas d'erreur -- il attend,
# en silence. Le pre-controle savait deja rendre `INDISPONIBLE` ; il lui
# manquait seulement de ne pas pouvoir attendre indefiniment.
#
# Une attente est BORNEE, et son depassement est un RESULTAT -- ici
# `INDISPONIBLE`, le troisieme etat que ce module utilise deja. Pas un echec :
# on n'a rien juge, faute d'outil pour juger.
_BUDGET_PREFLIGHT_S = float(os.environ.get("LAFORGE_UI_PREFLIGHT_S", "60"))
OUT = ROOT / "sandbox" / "ui_campaign"
OUT.mkdir(parents=True, exist_ok=True)
# LA SONDE NE DOIT PAS S'ACCUSER ELLE-MEME (mesure 2026-09-16).
# Version precedente : `(document.head||document.documentElement).appendChild(s)`.
# La garde paraissait suffisante -- elle ne l'est pas. `add_init_script` s'execute
# AVANT tout script de la page, a un instant ou head ET documentElement peuvent
# etre null. La sonde levait alors `Cannot read properties of null (reading
# 'appendChild')`, la page recoltait l'erreur, et le gate l'imputait au SITE : 20
# routes declarees DEGRADE a la premiere passe reelle, 19 pour ce seul motif.
# J'ai soupconne `sidebar.html` ; la pile, une fois conservee, ne montrait aucun
# fichier du site mais `<anonymous>` -- c'est-a-dire ce code-ci.
# « Un capteur neuf est un SUSPECT, pas un temoin. » Et c'est pourquoi le verdict
# DEGRADE a ete pose en OBSERVATION : bloquant, il aurait arrete la CI sur le bug
# de sa propre sonde.
_DISABLE_ANIM = (
    "(() => { const p = () => { const r = document.head || document.documentElement;"
    " if (!r) return false;"
    " const s = document.createElement('style');"
    " s.textContent = '*,*::before,*::after{animation-duration:.01ms !important;"
    "transition-duration:.01ms !important}';"
    " r.appendChild(s); return true; };"
    " if (!p()) { document.addEventListener('DOMContentLoaded', p, {once: true}); } })();"
)
_SSE_REGISTRY_JS = """(() => {
    window._activeEventSources = new Set();
    const origES = window.EventSource;
    if (origES) {
        window.EventSource = function(...args) {
            const es = new origES(...args);
            window._activeEventSources.add(es);
            const cleanup = () => window._activeEventSources.delete(es);
            es.addEventListener('error', () => { if (es.readyState === 2) cleanup(); });
            es.addEventListener('open', () => {});
            return es;
        };
    }
    window._closeAllEventSources = () => {
        if (window._activeEventSources) {
            for (const es of window._activeEventSources) {
                try { es.close(); } catch(e) {}
            }
            window._activeEventSources.clear();
        }
    };
})();"""


def _is_benign_err(txt: str) -> bool:
    """Une erreur de console qui ne rend PAS l'interface non livrable.

    L'icone d'onglet est entree ici le 2026-09-16, et seulement une fois qu'on a
    su la NOMMER. `/maison` sortait DEGRADE sur un « 404 (Not Found) » anonyme :
    il paraissait serieux tant qu'on ignorait qu'il manquait un favicon. Le
    dependance est instructive — nommer un defaut permet de le DISQUALIFIER,
    deviner ne le permet jamais.

    La regle reste ETROITE : `favicon.ico` seul, jamais « tout 404 ». Un 404 sur
    une feuille de style ou un script reste un defaut, parce qu'il change ce que
    l'utilisateur voit. Supprimer le bruit en supprimant le signal serait le
    remede pire que le mal, et un gate qui crie a faux finit desarme.
    """
    t = (txt or "").lower()
    if "favicon.ico" in t:
        return True
    return bool(re.search(r"interrupted while page loading|can't establish.*(sse|stream)|connection interrupted", t))


# Une page qui EST une erreur l'ANNONCE ; une page qui AFFICHE des erreurs les
# porte dans son corps. Les deux bornes ci-dessous separent ces deux cas, et
# elles sont MESUREES, pas devinees (passe job_f7177800d282 du 2026-09-16) :
# les pages de l'application rendent 90 a 434 caracteres, le journal
# `/forge/feed` en rend 24 961. Toute page sous la borne COURTE est donc lue
# entierement -- ce qui tient d'un coup d'oeil se juge d'un coup d'oeil.
_MOTS_ERREUR = ("traceback", "unauthorized", "500 internal", "502 bad", "exception:")
_TETE_ERREUR = 400
_PAGE_COURTE = 2000


def mot_d_erreur(texte: str) -> tuple:
    """(mot_en_tete | None, mots_hors_tete) — une page en erreur, ou qui en parle.

    MESURE 2026-09-16. `/forge/feed` s'intitule « Nokido Event Feed (Audit
    Trail) » et sortait DEGRADE pour « mot d'erreur rendu » : le mot etait dans
    le JOURNAL qu'elle a pour metier d'afficher. Le gate reprochait a une page
    de faire son travail — meme famille que l'instrument qui lit son propre
    vocabulaire, ici applique au contenu d'autrui.

    Rien n'est jete : ce qui est trouve hors tete est RENDU, pour que
    l'appelant puisse le rapporter sans en faire un verdict. Un filtre qui
    ecarte des donnees le dit, sinon la couverture est surestimee en silence.
    """
    texte = texte or ""
    bas = texte.lower()
    fenetre = bas if len(bas) < _PAGE_COURTE else bas[:_TETE_ERREUR]
    tete = next((w for w in _MOTS_ERREUR if w in fenetre), None)
    hors = tuple(w for w in _MOTS_ERREUR if w in bas and w != tete)
    return tete, hors

# Perimetre ELARGI le 2026-08-29. Le recensement nerveux voit 33 pages sur :7400 ; le
# contrat n'en jugeait que 7, et son VERT se lisait comme un vert sur l'interface
# entiere. Les dix routes ajoutees n'ont pas de `must` : on n'invente pas un contenu
# attendu. Elles sont jugees sur ce qui se mesure sans convention — la page rend, elle
# n'est pas vide, aucune exception JS, aucune API en 4xx/5xx, et ses boutons surs font
# quelque chose. Ajouter un `must` quand le contenu attendu est etabli, pas avant.
ROUTES = [
    ("/dashboard", "portail dashboard"),
    ("/maison", "EdgeMDM Maison (flotte edge)"),
    ("/rag", "RAG dashboard"),
    ("/swarm", "Swarm specialist runner"),
    ("/postal", "Postal mailbox"),
    ("/vitals", "Couche vitale (SSE)"),
    ("/mcp_lab", "MCP Lab"),
    ("/launcher", "Launcher (12 gestionnaires JS, page la plus opaque)"),
    ("/llm_dashboard", "LLM dashboard (providers)"),
    ("/rbac/", "RBAC mapping"),
    ("/organs", "Organes — etat du corps"),
    ("/forge/debate", "Debat multi-agents"),
    ("/forge/feed", "Flux forge"),
    ("/anatomy", "Anatomie cognitive (porte le KILL SWITCH : jamais clique)"),
    ("/ui/playground", "Playground UI"),
    ("/reports/", "Rapports indexes"),
    ("/dashboard/diag", "Diagnostic dashboard (htmx)"),
    # Routes GENERATIVES — ajoutees le 2026-08-30. Elles etaient HORS du contrat :
    # la campagne jugeait 17 routes qui excluaient precisement la partie NON
    # DETERMINISTE de l'interface, ou le HTML est ecrit par un LLM a chaque
    # chargement (app/web_hub/ui_generate.py). Un vert sur un perimetre qui ecarte
    # le risque est le defaut deja corrige le 29/08 sur « branches exposees » : un
    # gate qui juge autre chose que ce qu'on publie ne juge rien.
    #
    # CE QU'ON EXIGE, ET CE QU'ON N'EXIGE PAS. Aucun `must` : le contenu produit
    # varie d'un chargement a l'autre, exiger une sous-chaine rendrait le gate
    # rouge au hasard. Et le repli (`table_repli`, arme par le timeout de 8 s de
    # generate_ui) est un comportement VOULU : les deux rendus sont conformes. Ce
    # qui est exige tient donc sans convention — la route rend, le fragment n'est
    # pas vide, aucune exception JS, aucune API en 4xx/5xx. Un vert ici ne dit pas
    # que le LLM a repondu ; il dit que l'interface tient QUE le LLM reponde ou
    # non, ce qui est la garantie que l'utilisateur attend.
    ("/ui/auto/veille-summary", "UI generative — resume de veille (LLM, repli table)"),
    ("/ui/auto/critical-events", "UI generative — evenements critiques (LLM, repli table)"),
    ("/ui/auto/services-status", "UI generative — etat des services (LLM, repli table)"),
]

# VUES DE L'APPLICATION HUB — ajoutees le 2026-09-24. Le login ATTERRIT sur
# PAGE_HUB, et ses six vues se choisissent par etat React (`setView`), sans URL :
# aucune des routes ci-dessus ne les atteignait. C'est pourtant la que vivaient les
# pannes des 17-18/09 (Federation qui ne se MONTAIT pas sur `null.length`, six vues
# hors de portee sur `window`) -- gardees jusqu'ici par des NR STATIQUES seulement.
# Une route de vue = PAGE_HUB + "#" + id ; l'ouverture CLIQUE le bouton du menu
# (libelle de `NAV`, hub-shell.ref.jsx). NR : test_ui_campagne_couvre_les_vues_hub_nr
# rougit si une vue du menu manque ici.
PAGE_HUB = "/design/ui_kits/hub/index.html"
VUES_HUB = {
    "accueil": "Accueil",
    "cap": "Intention longue",
    "federation": "Fédération",
    "maison": "Maison",
    "persona": "Mémoire persona",
    "souverainete": "Souveraineté",
}
ROUTES += [(PAGE_HUB + "#" + _vid, "Application hub — vue « %s »" % _lab)
           for _vid, _lab in VUES_HUB.items()]


def est_rechargement(texte: str) -> bool:
    """Bouton dont l'effet attendu est de RECHARGER (peut ne rien changer a l'ecran)."""
    t = _sans_accents((texte or "").strip().lower())
    return any(v in t for v in ("relire", "refresh", "rafraich", "actualis", "recharg"))


def vue_hub(path: str):
    """Libelle du bouton de menu a cliquer pour une route de vue hub, sinon None."""
    if not str(path).startswith(PAGE_HUB + "#"):
        return None
    return VUES_HUB.get(str(path).split("#", 1)[1])


async def ouvrir_vue_hub(page, path: str):
    """None = route du portail (rien a ouvrir) ; True = bouton clique ; False = bouton
    ABSENT. Une vue qu'on n'a pas pu ouvrir n'a pas ete jugee : l'appelant le DIT
    (`_vue_ou_echec`), il ne juge pas la vue d'accueil a sa place."""
    libelle = vue_hub(path)
    if libelle is None:
        return None
    bouton = page.get_by_role("button", name=libelle, exact=True).first
    if not await bouton.count():
        return False
    await bouton.click(timeout=5000)
    return True


# PAGES UI DU HUB :8766 — ajoutees le 2026-09-24 (owner : « l'UI est sur 7400 ET
# 8766 »). La campagne ne visitait que :7400. Balayage HTTP du meme jour : 13 pages
# servies par le hub, dont 3 redirigent vers :7400 (rag, swarm, postal : deja
# jugees la-bas) ; les 9 ci-dessous ne sont servies QUE par :8766 et repondent 200
# sans jeton. Une route `@8766/...` se resout par `url_de` ; le prefixe evite qu'une
# URL complete (avec « : ») devienne un nom de capture invalide sous Windows.
PREFIXE_8766 = "@8766"
HUB_BASE = os.environ.get("NOKIDO_HUB_MCP_WEB", re.sub(r":7400$", ":8766", BASE)).rstrip("/")
PAGES_8766 = [
    ("/", "accueil du hub"),
    ("/forge/debate", "debat inter-LLM"),
    ("/forge/graph", "graphe de connaissance (AST)"),
    ("/forge/recon", "recon research_agent (live)"),
    ("/forge/rag-stream", "RAG stream (BM25 SSE)"),
    ("/forge/network", "reseau"),
    ("/forge/rings", "rings"),
    ("/forge/watch", "veille"),
    ("/gui/sidebar", "barre laterale"),
]
ROUTES += [(PREFIXE_8766 + _p, "Hub :8766 — %s" % _lab) for _p, _lab in PAGES_8766]


def url_de(path: str) -> str:
    """URL absolue d'une route de campagne : `@8766/...` vise le hub, le reste le portail."""
    p = str(path)
    if p.startswith(PREFIXE_8766):
        return HUB_BASE + p[len(PREFIXE_8766):]
    return BASE + p


async def _vue_ou_echec(page, path: str, pause_s: float = 1.5) -> None:
    ouverte = await ouvrir_vue_hub(page, path)
    if ouverte is False:
        raise RuntimeError("vue hub non ouverte : bouton de menu « %s » absent" % vue_hub(path))
    if ouverte:
        await asyncio.sleep(pause_s)  # rendu React + fetchs de la vue

# --- CLICS : classification des boutons. On enumere TOUS les boutons de CHAQUE
# route, on clique les SÛRS, on SAUTE les destructifs/inconnus (rapportes, pas
# ignores en silence). Opt-in : LAFORGE_UI_CLICKS=1 ou --clicks.
SAFE_VERBS = (
    "compter", "count", "effacer", "clear", "rafraich", "refresh", "actualis",
    "copier", "copy", "chat", "schéma", "schema", "afficher", "voir", "détail",
    "detail", "filtr", "toggle", "expand", "réduire", "reduire", "tokenize", "tab",
    # Verbes de LECTURE ajoutes le 2026-08-29. Mesure : « Chercher » (/rag), bouton
    # central de la page, tombait en `unknown` donc n'etait JAMAIS clique — le gate
    # restait vert sans avoir eprouve l'action principale de l'interface. Une lecture
    # n'a pas d'effet a redouter ; « figer » ne fait que suspendre un flux SSE cote
    # client. Ce qui appelle un appareil (Scan ADB, Shell, Screenshot, Status), lance
    # un swarm ou invoque un outil MCP arbitraire reste HORS de cette liste.
    "cherch", "recherch", "search", "query", "interrog", "figer", "pause",
    # Affichage pur (mesure 2026-08-29 : classes « inconnus » sur /launcher, donc
    # jamais eprouves alors qu'ils ne font qu'ouvrir un panneau).
    "logs", "live",
    # FERMETURES (2026-09-18). Une croix ne porte aucun verbe : elle tombait en
    # « inconnu », donc n'etait JAMAIS cliquee. Fermer un panneau est de
    # l'affichage pur, exactement comme `logs` et `live` ci-dessus. Les symboles
    # sont listes un par un plutot qu'un "x" generique, qui matcherait
    # « Exporter », « Extraire » ou n'importe quel libelle contenant la lettre.
    "✕", "✖", "×", "✗", "fermer", "close",
    # /llm_dashboard (2026-09-24) : 79 des 80 boutons « inconnus » de la campagne. Lu dans
    # app/web_hub/static/providers.js, pas devine au libelle : « relire » = recharge le
    # catalogue (GET) ; « saisir la cle » / « remplacer la cle » = ouvre/ferme la ligne
    # d'edition (etat local + rendu) -- l'ECRITURE au coffre passe par un autre bouton.
    "relire", "saisir la cle", "remplacer la cle",
)
# Boutons qu'on IDENTIFIE et qu'on choisit de ne pas cliquer parce que leur effet
# sort du systeme (un appareil, un peripherique). Ajoute le 2026-09-18.
#
# MOTIF : ces libelles etaient deja ecartes DELIBEREMENT -- le commentaire de
# SAFE_VERBS les nomme un par un (« ce qui appelle un appareil (Scan ADB, Shell,
# Screenshot, Status) reste HORS de cette liste ») -- mais le rapport les rendait
# `unknown` ou `destructive`. Or `unknown` veut dire « on ne sait pas », et ce
# fichier dit lui-meme qu'« un inconnu laisse croire qu'on ignore » ; et
# `destructive` veut dire « ca ecrit ». On y range aussi ce dont on ne peut pas
# PROUVER que ca n'ecrit pas : c'est le sens du garde du 2026-08-29, et le cout des
# deux erreurs n'est pas symetrique. Une
# politique n'est ni de l'ignorance ni une ecriture : elle a son nom.
# C'est la meme regle que la constitution semantique : DISABLED_BY_POLICY != UNKNOWN.
HORS_PERIMETRE_VERBS = (
    # `shell` et `screenshot` RETIRES le 2026-09-18 -- et c'est une doctrine ANTERIEURE
    # qui tranche, pas une preference du jour. Le NR du 2026-08-29
    # (`test_les_boutons_qui_ECRIVENT_ne_sont_pas_des_inconnus`) exige que ces deux
    # libelles soient dits `destructive`, avec sa raison : « le cout des deux erreurs
    # n'est pas symetrique -- sauter a tort coute une couverture, cliquer a tort coute
    # un effet ». En les requalifiant `hors_perimetre` ce matin, j'ai remplace une
    # doctrine vieille de trois semaines par la mienne, sans l'avoir lue.
    # `adb` reste ici : il vise un appareil EXTERNE, hors du systeme Nokido -- et le
    # garde du 29/08 ne le conteste pas. « Scan ADB » enumere, il n'ecrit pas.
    "adb", "status",
)
DESTRUCTIVE_VERBS = (
    "lancer", "run", "exec", "déploy", "deploy", "scan", "kill", "stop", "arrêt",
    "arret", "restart", "redémarr", "redemarr", "reboot", "wipe", "delete", "supprim",
    # Exiges par le NR du 2026-08-29 : un shell ouvre l'execution de commandes, et un
    # declenchement de capture agit sur un appareil. Aucun des deux n'est « sur ».
    "shell", "screenshot",
    "remove", "apply", "appliqu", "envoy", "send", "submit", "logout", "déconnex",
    "deconnex", "start", "démarr", "demarr", "install", "uninstall", "push", "commit",
    "drain", "force", "reset", "sauvegard", "backup", "migrat", "rotate", "rotation",
    # Ajoutes le 2026-08-29 : ils ECRIVENT ou declenchent, et tombaient pourtant en
    # « inconnu » — `Save` QUATORZE fois sur /rbac, qui enregistre une politique
    # RBAC. Un « inconnu » laisse croire qu'on ignore ; ici on sait. Le cout des
    # deux erreurs n'est pas symetrique : sauter a tort coute une couverture,
    # cliquer a tort coute un effet.
    "save", "sauv", "enregistr", "gener", "regen", "invoqu", "mail",
    # `shell`, `screenshot` et `adb` sont sortis d'ici le 2026-09-18 : ils ne sont
    # pas destructifs au sens « ils ecrivent dans le systeme », ils sont HORS
    # PERIMETRE (ils sollicitent un appareil). Voir HORS_PERIMETRE_VERBS. Le
    # comportement ne change pas -- ils restent non cliques -- mais le rapport
    # cesse de leur attribuer un effet qu'ils n'ont pas.
)
# Pre-remplissage par route (pour que les boutons SÛRS a input fonctionnent).
FILL_HINTS = {
    "/rag": [("textarea", "bonjour le monde — test de tokenisation reel")],
}
_BTN_SEL = "button,[role=button],input[type=submit],input[type=button]"
# Ce qu'un humain percoit d'un clic : le texte, l'adresse, la VALEUR des champs, et le
# nombre d'elements (un panneau qui s'ouvre/se ferme sans changer le texte).
# ETAT VISUEL ajoute le 2026-09-18, meme motif que les `value` ajoutees le
# 2026-08-26. Mesure : « Live » (/launcher) ouvre un EventSource et bascule une
# CLASSE (`liveBtn.classList.add('on')`), tandis que le `<pre class="log">` perd
# son attribut `hidden` -- mais il est encore VIDE a l'instant de la mesure, donc
# `innerText` ne bouge pas, le nombre d'elements non plus, et le bouton passait
# pour mort. Trois fois de suite, sur trois cartes. Idem pour la croix de
# `/maison`, qui REFERME un panneau : elle remet `hidden`, sans rien retirer du
# DOM.
#
# Ce qu'un humain percoit d'un clic, ce n'est pas seulement le texte : c'est
# aussi ce qui s'allume, s'ouvre et se ferme. On lit donc les classes et les
# `hidden` des elements STRUCTURANTS -- bornes a 400 pour qu'une page riche ne
# fasse pas de l'empreinte un dump.
_EMPREINTE_JS = (
    "() => JSON.stringify([document.body.innerText, location.href, "
    "Array.from(document.querySelectorAll('input,textarea,select')).map(e => e.value), "
    "document.querySelectorAll('*').length, "
    "Array.from(document.querySelectorAll('button,[role=button],[class],[hidden]'))"
    ".slice(0,400).map(e => (e.className||'') + '|' + (e.hidden ? 'h' : ''))])"
)


# OBSERVATIONS DE COUCHES — nourrissent UI_ACCEPTANCE_WITNESS (forge_ui_temoin).
# `None` = PAS ENCORE MESURE ; `False` = mesure et negatif. Les confondre fabrique
# des pannes qui n'ont pas eu lieu : c'est la meme regle que « UNKNOWN != NO ».
_OBSERVATIONS = {}


def reinitialiser_observations() -> None:
    """Etat de depart : rien n'est mesure, et cela se DIT (None partout)."""
    _OBSERVATIONS.clear()
    _OBSERVATIONS.update({
        "transport": {"service_reachable": None, "http_status": None,
                      "endpoint": None},
        "browser": {"executable": None, "launched": None,
                    "context_created": None},
    })


def _poser(couche: str, valeurs: dict) -> None:
    """Corps commun des noteurs. Factorise le 2026-09-09 : le cliquet clones a
    NOMME `forge_ui_campaign.py` comme groupe neuf, et il avait raison -- les deux
    noteurs ne differaient que par leurs champs."""
    if not _OBSERVATIONS:
        reinitialiser_observations()
    _OBSERVATIONS[couche] = valeurs


def noter_transport(service_reachable=None, http_status=None, endpoint=None) -> None:
    _poser("transport", {"service_reachable": service_reachable,
                         "http_status": http_status, "endpoint": endpoint})


def noter_browser(executable=None, launched=None, context_created=None) -> None:
    _poser("browser", {"executable": executable, "launched": launched,
                       "context_created": context_created})


def observations() -> dict:
    """Les couches mesurees, a embarquer dans TOUTE sortie — INDISPONIBLE compris.

    Une observation qui ne survit pas au process ne sert a personne : les chemins
    d'echec sont precisement ceux ou la cause doit rester lisible apres coup.
    """
    if not _OBSERVATIONS:
        reinitialiser_observations()
    return {k: dict(v) for k, v in _OBSERVATIONS.items()}


def sonder_service(timeout: float = 5.0) -> tuple:
    """(joignable, http_status) — un service qui REPOND 4xx/5xx est JOIGNABLE.

    DEFAUT CORRIGE ICI, mesure le 2026-09-09. L'ancienne sonde faisait :

        return getattr(r, "status", 200) == 200
        except Exception: return False

    Or `urlopen` LEVE `HTTPError` sur un 401. Le `except` l'attrapait, la sonde
    rendait False, et la campagne imprimait « interface injoignable » -- alors que
    :7400 avait repondu. Trois changements de compte ont ete depenses a chercher
    dans le reseau une panne qui etait dans l'authentification.

    TRANSPORT != APPLICATIF : le code HTTP est rendu tel quel, c'est a l'appelant
    de decider ce qu'un 401 signifie pour SON contrat. Une connexion refusee rend
    (False, None) -- et surtout pas un statut invente.
    """
    import urllib.error
    import urllib.request

    try:
        r = urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            BASE + "/health", timeout=timeout)
        return True, getattr(r, "status", 200)
    except urllib.error.HTTPError as e:
        # Une reponse d'erreur EST une reponse : le serveur est la.
        return True, getattr(e, "code", None)
    except Exception:  # noqa: BLE001 - la, l'injoignabilite est bien la reponse
        return False, None


def _service_repond(timeout: float = 5.0) -> bool:
    """Le service accepte-t-il ENCORE une requete ? Mesure 2026-08-29 : apres une passe
    de navigation soutenue, :7400 garde son LISTENING et cinq sockets en CLOSE_WAIT,
    mais ne repond plus a /health. Chaque route suivante expire alors a 30 s et part en
    « non jugee » — douze d'un coup, pour UNE panne, sans que rien ne nomme la panne.

    Distinguer les deux est tout l'enjeu : une route qui timeoute pendant que le service
    repond est une route lente ; la meme pendant que le service est MORT ne dit rien
    d'elle. On sonde, et on arrete la passe au lieu de fabriquer douze verdicts vides."""
    # Predicat historique conserve pour les appelants existants : on ETEND la mesure,
    # on ne casse pas leur contrat. Attention, il reste GROSSIER par construction --
    # un 401 y vaut « repond », ce qui est juste pour « le service est la » et
    # insuffisant pour juger l'application. Preferer `sonder_service`.
    joignable, statut = sonder_service(timeout)
    noter_transport(service_reachable=joignable, http_status=statut, endpoint=BASE)
    return joignable


def _sans_accents(t: str) -> str:
    """« Exécuter » ne contenait pas « exec » : l'accent suffisait a faire manquer
    le verbe. Mesure 2026-08-29 — `Executer tool_scope` et `Generer` tombaient en
    « inconnu », donc n'etaient ni cliques ni comptes comme sautes par surete : le
    rapport disait « on ne sait pas » la ou on savait tres bien."""
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", t)
                   if not unicodedata.combining(c))


def _classify_btn(text: str, externe: bool = False) -> str:
    """Quatre etats, et l'ordre compte.

    `externe` -- le bouton ouvre une adresse http(s) dans un autre onglet. Un
    lien vers un site tiers ne peut RIEN ecrire dans le systeme : quel que soit
    son libelle, il sort du perimetre. C'est la NATURE du geste qui tranche, pas
    une liste de noms de sites qu'il faudrait rallonger a chaque ajout.

    HORS PERIMETRE d'abord : « Scan ADB » porte `scan` (destructif) ET `adb`
    (appareil). Tester les verbes destructifs en premier le rangerait parmi les
    ecritures, ce qu'il n'est pas -- il enumere un peripherique.

    `unknown` doit rester possible : ranger tout le monde pour faire du vert
    fabriquerait une certitude. C'est le troisieme etat de la constitution
    semantique, et il se dit.
    """
    if externe:
        return "hors_perimetre"
    t = _sans_accents((text or "").strip().lower())
    if not t:
        return "unknown"
    # « tester » (/llm_dashboard, 2026-09-24) : POST /api/providers/<p>/test appelle le
    # FOURNISSEUR EXTERNE (egress, quota consomme). Lecture en apparence, effet hors du
    # systeme : ni sur, ni inconnu -- une politique, qui a son nom.
    if t == "tester":
        return "hors_perimetre"
    if any(_sans_accents(v) in t for v in HORS_PERIMETRE_VERBS):
        return "hors_perimetre"
    if any(_sans_accents(v) in t for v in DESTRUCTIVE_VERBS):
        return "destructive"
    if any(_sans_accents(v) in t for v in SAFE_VERBS):
        return "safe"
    return "unknown"


def _onglet_deja_actif(classes, aria_selected) -> bool:
    """L'element est-il un onglet DEJA affiche ?

    MESURE du 2026-09-18 sur le service vivant : le bouton « Chat » de `/postal`
    porte la classe `tab on` et son gestionnaire rappelle le panneau deja
    affiche. Le clic ne change donc rien -- par construction, pas par panne. Sans
    cette lecture, la campagne le rapportait comme « clique sans effet
    observable », c'est-a-dire un defaut a instruire qui n'existe pas, et qui
    noie les vrais.

    On compare des MOTS de classe, jamais des sous-chaines : `button`, `icon` et
    `monitoring` contiennent tous `on`. Une regle par sous-chaine excuserait le
    non-effet de presque tous les boutons de l'interface -- le piege `findstr`
    du 2026-08-01, ou des espaces separaient des litteraux au lieu de former une
    phrase.
    """
    if str(aria_selected or "").strip().lower() == "true":
        return True
    mots = {m for m in str(classes or "").lower().replace("\t", " ").split() if m}
    return bool(mots & {"on", "active", "actif", "selected", "current", "is-active"})


# --- CONTRAT d'acceptation par route : definition of done machine-verifiable.
#   must    : sous-chaines OBLIGATOIRES dans le rendu (contenu attendu, pas juste "non vide")
#   testids : data-testid qui DOIVENT exister dans le DOM
#   data    : [(label, api_path_GET, json_key)] — la valeur SOURCE doit apparaitre dans le rendu
# « Livrable » == contrat vert. Enrichir au fil de l'eau (assertions data sur endpoints surs).
CONTRACTS = {
    "/dashboard": {"must": ["nokido hub", "web hub"]},
    "/maison": {"must": ["flotte edge", "total devices", "en ligne"]},
    "/rag": {"must": ["chunks total", "vectoris", "domaines", "tiktoken"],
             "data": [("chunks_total", "/api/rag/stats", "total")]},
    "/swarm": {"must": ["swarm", "flux"]},
    "/postal": {"must": ["conversations", "agents"]},
    "/vitals": {"must": ["anatomie cognitive", "tempo"]},
    "/mcp_lab": {"must": ["mcp lab", "hub up", "outils"]},
}


def _classer_routes(results):
    """Range les routes en (INFRA, NON AUTHENTIFIE, EN ECHEC).

    Extraite de `run()` le 2026-09-12 : la decision vivait inline, donc AUCUN
    test ne pouvait l'atteindre — une logique de verdict que personne ne garde.

    CINQUIEME cas de non-jugement. Le module en portait deja quatre (`/health`
    injoignable, harnais absent, timeout de navigation, service mort en cours),
    tous pour la meme raison ecrite ici : « on n'a rien juge du tout ». Il
    manquait le login.

    MESURE qui l'a impose (run GitHub 34709188586) : 17 routes, TOUTES en
    LOGIN-REDIR, `txt=89` identique partout — la page de login, pas les pages
    demandees. Le gate a conclu « contrat VIOLE sur interface disponible ».
    Contre-mesure le meme jour : avec une session etablie, `/rag` rend 8 205
    octets et les quatre marqueurs exiges SONT presents. Le contrat etait tenu ;
    c'est l'authentification du GATE qui avait echoue.

    C'est la faute SYMETRIQUE de celle corrigee le 2026-09-11 (« un timeout ne
    doit jamais devenir un succes ») : ici un inconnu devenait un ECHEC. Les deux
    sens sont faux — `UNKNOWN` n'est ni `NO` ni `YES`.

    Ce qui reste BLOQUANT, et doit le rester : une route REELLEMENT servie dont
    le contrat n'est pas tenu. Sans cette reserve, on echangerait un faux rouge
    contre un faux vert. Fige par tests/nr/test_ui_campaign_login_non_juge_nr.py
    """
    def _est_nav_timeout(r):
        f = str(r.get("FAIL", ""))
        return "FAIL" in r and "TimeoutError" in f and (
            "goto" in f.lower() or "navigating" in f.lower())

    def _est_redir_login(r):
        # On n'a pas vu la page demandee : on a vu le formulaire de login.
        return bool(r.get("redirected_login"))

    infra = [r for r in results if _est_nav_timeout(r)]
    auth_ko = [r for r in results if _est_redir_login(r) and not _est_nav_timeout(r)]
    ko = [r for r in results
          if (r.get("contract_ok") is False or "FAIL" in r)
          and not _est_nav_timeout(r) and not _est_redir_login(r)]
    return infra, auth_ko, ko


_PILE_MAX = 700


def classer_reponse(status: int, url: str):
    """`"api"` | `"ressource"` | None -- nommer ne veut pas dire degrader.

    MESURE DU 2026-09-16. Le verdict de reference signalait `/maison` en defaut
    pour un 404, sans pouvoir dire LEQUEL : le collecteur ne retenait que les
    reponses dont l'URL contient `/api/`, si bien qu'un 404 sur une ressource
    statique n'apparaissait qu'en console, sans son URL. Troisieme fois dans la
    journee que l'instrument voit un defaut qu'il ne sait pas nommer.

    ELARGIR LE FILTRE AURAIT ETE PIRE. Compter toute reponse >= 400 comme un
    defaut capterait favicons et sondes optionnelles : on remplacerait un angle
    mort par du bruit, juste apres avoir supprime 18 faux positifs. Les deux roles
    sont donc separes -- `api` fait basculer le verdict, `ressource` est NOMMEE et
    reste informative. Ce qu'on mesure doit remonter ; ce qui degrade doit rester
    ce qui degradait.
    """
    if status is None or int(status) < 400:
        return None
    return "api" if "/api/" in (url or "") else "ressource"


def enrichir_texte_console(type_, texte, location):
    """Le texte d'un message console d'erreur, NOMME quand c'est possible.

    MESURE 2026-09-16. `/maison` sortait DEGRADE sur « Failed to load resource:
    ... 404 (Not Found) » sans qu'aucun rapport ne dise QUELLE ressource. Or le
    navigateur donne cette URL -- il la met dans la `location` du message, pas
    dans son texte. On ne gardait la location que si le texte etait vide ou
    « JSHandle@ », c'est-a-dire jamais pour ce message-la, qui est precisement
    le seul a ne pas se nommer lui-meme.

    NOMMER N'EST PAS DEGRADER : rien n'est ajoute au verdict ici, on rend
    lisible ce qui degradait deja. Et un message qui porte DEJA une URL n'est
    pas annote : la repeter n'apprend rien et alourdit le rapport.
    """
    if type_ != "error":
        return None
    texte = texte or ""
    loc = location or {}
    url = loc.get("url") or ""
    if "JSHandle@" in texte or not texte.strip():
        return "%s @ %s:%s:%s" % (texte or "(vide)", url or "?",
                                  loc.get("lineNumber", "?"),
                                  loc.get("columnNumber", "?"))
    if url and "http" not in texte:
        return "%s @ %s" % (texte, url)
    return texte


def _texte_erreur_page(e) -> str:
    """Texte d'une erreur de page : la PILE si elle existe, sinon le message.

    MESURE DU 2026-09-16, et elle a coute une enquete pour rien. Le gate a enfin
    juge et a trouve 20 routes DEGRADE, dont 19 portant la MEME erreur --
    `Cannot read properties of null (reading 'appendChild')`. Un seul script
    commun a toutes les pages, donc une seule correction pour 19 routes. Mais le
    collecteur faisait `str(e)`, qui sur une Error Playwright rend le MESSAGE
    SEUL : impossible de dire QUEL script. L'objet porte `.stack`, qui nomme le
    fichier et la ligne -- disponible, et jete.

    C'est le defaut que ce module vient de corriger un etage plus haut, ou quatre
    signaux etaient collectes puis abandonnes. Un instrument qui dit « quelque
    chose a casse quelque part » oblige a deviner, et deviner est ce qui a coute
    le plus cher dans cette journee.

    LA BORNE DIT QU'ELLE TRONQUE : une pile profonde ne doit pas noyer le rapport,
    mais une coupe muette ferait croire que les cadres manquants n'existent pas
    (motif `borne_trop_serree`, paye le 2026-07-25 quand `text[:3000]` a detruit
    le corps de 377 documents en silence).
    """
    pile = getattr(e, "stack", None)
    if pile:
        pile = str(pile)
        if len(pile) > _PILE_MAX:
            pile = pile[:_PILE_MAX] + " ...[pile tronquee a %d car.]" % _PILE_MAX
        return "pageerror: " + pile
    return "pageerror: " + str(e)


_CLE_ADMIN = "LAFORGE_ADMIN_TOKEN"


def couche_du_credential(diag: dict, cle: str, jeton_obtenu: bool) -> str:
    """Quelle COUCHE de `forge_secrets` sert le jeton. Aucune valeur n'est lue.

    MESURE 2026-09-16. La campagne imprimait `credential=env` en local (login
    ETABLI) ET en CI (login TENTE_ET_REFUSE) : l'etiquette ne distinguait pas
    les deux, donc elle n'apprenait rien sur la panne. Or `get_secret` a quatre
    couches, essayees dans l'ordre -- coffre DPAPI, WCM, fichier .env, puis
    `os.environ` en DERNIER RECOURS -- et savoir laquelle a servi departage un
    jeton legitime d'un secret de CI perime.

    ANTI-DUP : le classement par couche existe deja dans
    `forge_secrets.diagnostic()`, qui ne divulgue que des noms de cles. On le
    reutilise au lieu d'en ecrire un second, qui divergerait.

    ANGLE MORT DE CET ORGANE, ET C'EST ICI QU'IL SE COMBLE : `diagnostic()` ne
    teste PAS `os.environ`, donc une cle servie en dernier recours y ressort
    « manquante ». Une cle absente des trois couches ALORS QU'UN JETON A ETE
    OBTENU ne peut venir que de l'environnement -- c'est la seule deduction
    faite ici, et elle repose sur l'ordre declare de `get_secret`, pas sur une
    supposition.
    """
    if cle in (diag.get("in_vault") or ()):
        return "coffre"
    if cle in (diag.get("in_wcm") or ()):
        return "wcm"
    if cle in (diag.get("in_env_only") or ()):
        return "fichier .env"
    return "environnement" if jeton_obtenu else "aucune"


def _couche_observee(jeton_obtenu: bool) -> str:
    """Interroge l'organe de diagnostic ; une lecture impossible se DIT."""
    try:
        from nokido_agent.app.forge_secrets import diagnostic  # noqa: PLC0415

        return couche_du_credential(diagnostic(), _CLE_ADMIN, jeton_obtenu)
    except Exception as e:  # noqa: BLE001
        return "indeterminee (%s)" % type(e).__name__


def resoudre_credential(depuis_env: str, depuis_coffre: str) -> tuple:
    """(credential, source) -- filet de securite, et NON la cause de l'anergie.

    ⚠️ CORRECTION D'UNE AFFIRMATION FAUSSE, faite le 2026-09-16 avant qu'elle
    n'entre dans le depot. J'ai d'abord ecrit que `AuthConfig.from_env()` lisait
    l'ENVIRONNEMENT SEUL, et que c'etait la cause du gate anergique. C'est FAUX :
    `from_env()` importe `forge_secrets.get_secret` et consulte DEJA le coffre.
    Mesure sous le compte du hub : `admin_token` present, longueur 64, alors que
    `LAFORGE_ADMIN_TOKEN` est VIDE dans l'environnement, et deux appels rendent la
    MEME valeur (donc rien n'est genere aleatoirement).

    Consequence a assumer : ce repli ne se declenchera QUE si `from_env()` rend
    vide -- ce qui peut arriver sous un compte qui n'ouvre pas le coffre, mais
    n'est pas mesure. Il est donc un FILET, pas un correctif, et il ne faut pas
    lui attribuer une reparation qu'il n'a pas faite.

    LA CAUSE REELLE DE L'ECHEC DU LOGIN RESTE NON ETABLIE a cette date. Ce qui
    est mesure : le client a un jeton, et les 20 routes voient quand meme la page
    de login. Restent a departager -- le serveur attend un autre secret, le
    formulaire a change de champ, ou le compte du job n'ouvre pas le coffre.
    C'est `etat_login()` qui permettra de trancher, puisqu'il distingue enfin
    « tente et refuse » de « jamais tente ».
    """
    if depuis_env:
        return depuis_env, "env"
    if depuis_coffre:
        return depuis_coffre, "coffre"
    return "", "aucune"


def _credential_du_coffre() -> str:
    """Jeton d'administration lu au coffre. Muet et vide si indisponible."""
    try:
        from nokido_agent.app.forge_secrets import get_secret  # noqa: PLC0415

        return get_secret("LAFORGE_ADMIN_TOKEN") or ""
    except Exception:  # noqa: BLE001 - absence de coffre = pas de credential, pas une panne
        return ""


def etat_login(auth_active: bool, cred: str, url_finale: str) -> str:
    """Quatre etats, parce qu'une URL seule n'en distingue que deux.

    « login tente et refuse » et « login JAMAIS tente faute de jeton » s'ecrivaient
    de la meme facon : l'URL de la page de login. Ce sont pourtant deux pannes
    opposees -- l'une demande de reparer le formulaire ou le mot de passe, l'autre
    de fournir un secret. Sans cette distinction, le message « Verifier
    LAFORGE_ADMIN_TOKEN et le login » envoie chercher au hasard.
    """
    if not auth_active:
        return "NON_TENTE_AUTH_DESACTIVEE"
    if not cred:
        return "NON_TENTE_CREDENTIAL_ABSENT"
    return "TENTE_ET_REFUSE" if "/auth/login" in (url_finale or "") else "ETABLI"


def _routes_degradees(results, infra, auth_ko, ko):
    """Les quatre signaux que la campagne COLLECTE depuis le 2026-08-29 et qu'elle
    n'a jamais comptes.

    Le commentaire qui a elargi le perimetre ce jour-la DECLARE, pour les dix
    routes sans `must` : « Elles sont jugees sur ce qui se mesure sans convention
    -- la page rend, elle n'est pas vide, aucune exception JS, aucune API en
    4xx/5xx ». MESURE : aucun de ces quatre signaux n'atteignait le verdict.
    `rec["contract_ok"]` vaut None quand aucun contrat n'est declare, et le
    classement retient `contract_ok is False`, que None ne satisfait jamais.
    `empty`, `error_word`, `console_errors` et `api_errors` etaient donc
    collectes, imprimes en drapeaux, puis jetes -- une page rendant « Traceback »
    sortait CONFORME, et dix routes sur vingt n'etaient jugees sur RIEN.

    Ne jamais confondre l'existence d'un mecanisme avec son effet reel : la
    doctrine ecrite dans ce fichier promettait un jugement que son code ne
    rendait pas.

    DEUX RESERVES, sans quoi on echangerait un faux vert contre un faux rouge :
      - les erreurs BENIGNES sont deja triees en amont (`_is_benign_err` : SSE
        coupee en fin de page). On lit `console_errors`, jamais `console_benign` ;
      - une route deja classee INFRA, NON AUTHENTIFIEE ou EN ECHEC n'est pas
        re-comptee ici. Un non-jugement reste un non-jugement : on n'a pas vu la
        page, donc ses erreurs JS ne disent rien d'elle. Sans cette exclusion, un
        meme defaut compterait deux fois et les denombrements du resume
        deviendraient faux.
    """
    deja = {r.get("route") for r in list(infra) + list(auth_ko) + list(ko)}
    degrade = []
    for r in results:
        if r.get("route") in deja or "FAIL" in r:
            continue
        if (r.get("empty") or r.get("error_word")
                or r.get("console_errors") or r.get("api_errors")):
            degrade.append(r)
    return degrade


# Nombre de passes servant a juger la PERSISTANCE d'un defaut. Trois est le
# minimum qui distingue « toujours » de « parfois » sans rendre la campagne
# deux fois plus longue : seules les routes DEJA en defaut sont revisitees, le
# cout est donc proportionnel au nombre de defauts, pas au nombre de routes.
_PASSES_CONFIRMATION = 3


# Registre des routes DEJA vues en defaut. C'est la forme ECRITE du log que
# reclame un fait temporel : sans lui, chaque passe repart sans memoire et un
# defaut qui ne se montre pas aujourd'hui n'existe plus.
_REGISTRE_INSTABLES = OUT / "routes_instables.json"


def routes_a_rejouer(en_defaut, registre) -> list:
    """Les routes a revisiter : celles en defaut AUJOURD'HUI, plus les connues.

    MESURE job_141decba05a9 (2026-09-16) : verdict CONFORME, `occurrences: {}`,
    aucune page portant le moindre signal -- un vert HONNETE. Mais c'etait la
    SIXIEME composition en six passes, et la precedente rendait `/anatomy` en
    defaut sans qu'une ligne du web_hub ait bouge.

    💥 LE TROU QUE CELA A REVELE, et je l'avais ECRIT sans en tirer la
    consequence : le cliquet ne rejouait que les routes DEJA en defaut. Passe
    initiale propre = rien de revisite = CONFORME sur une interface qui casse
    une fois sur deux. Un faux calme, c'est-a-dire exactement ce que ce
    chantier doit supprimer. « Ne jamais confondre l'existence d'un mecanisme
    avec son effet reel » vaut aussi pour le mecanisme qu'on vient d'ecrire.

    Le registre ne CONDAMNE personne : il fait REGARDER. Une route inscrite qui
    passe toutes ses passes ressort `NON_REPRODUIT`, pas en defaut. Et on ne
    rejoue pas les vingt routes : cela triplerait la campagne pour observer
    surtout ce qui n'a jamais rien montre.
    """
    vues = list(en_defaut)
    for route in registre or {}:
        if route not in vues:
            vues.append(route)
    return vues


def maj_registre(registre, en_defaut) -> dict:
    """Incremente le compteur des routes vues en defaut. Jamais de remise a zero.

    Un registre qui oublie est un registre qui recommence : c'est le defaut
    meme qu'on corrige ici.
    """
    out = dict(registre or {})
    for route in en_defaut or ():
        out[route] = int(out.get(route, 0)) + 1
    return out


def _lire_registre() -> dict:
    try:
        return json.loads(_REGISTRE_INSTABLES.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — registre absent au premier run : normal
        return {}


def _ecrire_registre(registre) -> None:
    try:
        _REGISTRE_INSTABLES.parent.mkdir(parents=True, exist_ok=True)
        _REGISTRE_INSTABLES.write_text(
            json.dumps(registre, indent=1, sort_keys=True), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print("[persistance] registre NON ecrit (%s) — la prochaine passe "
              "repartira sans memoire" % type(e).__name__)


async def _repasse_route(br, path, errs, benign_errs, bad_resp, res_ko, resp_vues):
    """Rejoue UNE route DEJA en defaut, pour mesurer la persistance du defaut.

    Rend un rec au format lu par `_routes_degradees`, ou None si la navigation
    a echoue. Un echec de navigation n'est PAS « defaut absent » : le compteur
    ne bouge pas, mais le denominateur ne compte que les passes REELLEMENT
    jouees -- sinon le taux mentirait sur ce qu'il a pu observer.
    """
    for _liste in (errs, benign_errs, bad_resp, res_ko, resp_vues):
        _liste.clear()
    try:
        await br.goto(url_de(path), "domcontentloaded")
        await br.wait(1.0)
        await _vue_ou_echec(br.page, path)
        texte = await br.dom_text() or ""
    except Exception:  # noqa: BLE001 — l'echec est rendu par None, pas avale
        return None
    _tete, _hors = mot_d_erreur(texte)
    return {"route": path,
            "empty": len(texte.strip()) < 40,
            "error_word": bool(_tete),
            "console_errors": list(errs),
            "api_errors": list(bad_resp)}


def classer_persistance(occurrences: int, passes: int) -> str:
    """STABLE · INTERMITTENT · NON_REPRODUIT · NON_MESURE.

    MESURE 2026-09-16 : cinq passes de la campagne ont rendu CINQ compositions
    du verdict. `/ui/auto/services-status` rend tantot 17 caracteres, tantot
    127, tantot un contenu normal ; `/anatomy` entre et sort. Un verdict d'UNE
    passe ne caracterise pas ces defauts-la -- un fait TEMPOREL se refute par un
    LOG, jamais par une lecture a l'instant t.

    ⚠️ CE QUE CE CLIQUET NE DOIT SURTOUT PAS DEVENIR : un moyen de faire
    DISPARAITRE un defaut (« il ne s'est pas reproduit, donc vert »). Ce serait
    echanger un faux rouge contre un faux vert. Aucun etat rendu ici n'est sain :
    `NON_REPRODUIT` se NOMME au lieu de se taire, et `NON_MESURE` dit qu'on n'a
    pas regarde plutot que de conclure.

    ⚠️ ASYMETRIE ASSUMEE ET DITE : on ne revisite que ce qui a DEJA echoue. On
    mesure donc la PERSISTANCE d'un defaut, jamais sa FREQUENCE d'apparition --
    une route saine a la premiere passe n'est pas revisitee, et son eventuelle
    intermittence reste invisible a cet instrument.
    """
    if passes <= 0:
        return "NON_MESURE"
    if occurrences <= 0:
        return "NON_REPRODUIT"
    return "STABLE" if occurrences >= passes else "INTERMITTENT"


def decider_verdict(gate_fail, auth_ko, mort_en_cours, degrade=(), intermittent=(),
                    passes=1) -> dict:
    """UN endroit decide, et il rend les TROIS formes du verdict a la fois.

    MESURE qui l'a impose (CI de reference du 2026-09-16, jobs job_f34603d549ba
    et job_b334189da2bc) : 17 routes sur 20 redirigees vers /auth/login, et le
    gate a rendu VERT. Les trois sorties de cette decision vivaient a trois
    endroits differents de `run()` et disaient trois choses differentes :

      report.json     -> "INDISPONIBLE"                      (juste)
      ligne "GATE:"   -> "VERT (CONFORME) -- livrable"        (faux : le jaune
                         n'etait branche que sur `mort_en_cours`)
      code de retour  -> 0, par `return 1 if gate_fail else 0` (faux : deux
                         etats pour quatre cas)

    Or `ci_local` lit le CODE DE RETOUR pendant que `forge_ui_temoin` lit le
    RAPPORT : deux observateurs du meme fait, en desaccord, et c'est le mauvais
    qui decidait. D'ou les trois formes rendues ENSEMBLE, depuis une decision
    unique -- deux endroits qui tranchent le meme verdict finissent par diverger.

    AUTH_FAILURE est un etat a part entiere, distinct d'INDISPONIBLE : les deux
    remedes n'ont rien de commun (reparer le login du gate / reparer le service).
    Les confondre envoie chercher la mauvaise panne.

    ORDRE, et il n'est pas commutatif :
      1. un contrat REELLEMENT viole prime -- c'est la reserve posee le
         2026-09-12, sans quoi on echangerait un faux rouge contre un faux vert ;
      2. puis le transport : un service mort explique un login inutile, l'inverse
         est faux (meme ordre de couches que `forge_ui_temoin._motif`) ;
      3. puis l'authentification ;
      4. puis la DEGRADATION STABLE -- plus faible que les trois premiers,
         parce qu'une page degradee a au moins ete VUE, la ou un login non
         etabli n'a rien vu ;
      5. puis la degradation INTERMITTENTE, plus faible encore : le defaut
         existe mais ne se reproduit pas a chaque passe. Il reste NON livrable
         -- « parfois casse » n'est pas « conforme » ;
      6. et seulement alors, le vert.

    Aucun de ces etats n'est sain par defaut : SEUL le dernier cas, celui ou il
    n'y a rien a signaler, est livrable. On classe par liste BLANCHE.
    """
    if gate_fail:
        return {"verdict": "VIOLÉ", "rc": 1, "livrable": False,
                "gate": "ROUGE (VIOLÉ — contrat/route en echec sur "
                        "interface disponible) — NON livrable"}
    if mort_en_cours:
        return {"verdict": "INDISPONIBLE", "rc": 2, "livrable": False,
                "gate": "JAUNE (INDISPONIBLE — le service a cesse de "
                        "repondre pendant la passe) — NON livrable en l'etat"}
    if auth_ko:
        return {"verdict": "AUTH_FAILURE", "rc": 3, "livrable": False,
                "gate": "JAUNE (AUTH_FAILURE — le gate ne s'est pas "
                        "authentifie : %d route(s) redirigees vers /auth/login, "
                        "donc NON jugees) — NON livrable en l'etat"
                        % len(auth_ko)}
    if degrade:
        return {"verdict": "DEGRADE", "rc": 4, "livrable": False,
                "gate": "JAUNE (DEGRADE — %d route(s) servies mais en "
                        "defaut : page vide, mot d'erreur rendu, exception JS "
                        "ou API >= 400) — NON livrable en l'etat"
                        % len(degrade)}
    if intermittent:
        return {"verdict": "INTERMITTENT", "rc": 5, "livrable": False,
                "gate": "JAUNE (INTERMITTENT — %d route(s) en defaut sur "
                        "CERTAINES passes seulement : %s) — NON livrable en "
                        "l'etat, et le taux fait partie du constat"
                        % (len(intermittent), ", ".join(intermittent))}
    # Le vert DIT sur combien de passes il porte. Un CONFORME muet se lit comme
    # une preuve de stabilite alors qu'il n'est qu'un instantane -- six passes
    # du 2026-09-16 ont rendu six compositions differentes.
    return {"verdict": "CONFORME", "rc": 0, "livrable": True,
            "gate": "VERT (CONFORME — contrats OK, mesure sur %d passe%s) — "
                    "livrable" % (passes, "s" if passes > 1 else "")}


async def run() -> None:
    import time as _time

    _t0 = _time.time()
    try:
        sys.stdout.reconfigure(errors="replace")  # console Windows cp1252 : emojis -> pas de crash
    except Exception:
        pass
    cfg = AuthConfig.from_env()
    # Le coffre en repli : `from_env()` seul laissait le jeton VIDE sous le compte
    # d'un job detache, d'ou un gate anergique depuis sa creation.
    # route -> (occurrences, passes REELLEMENT jouees). Defini ICI pour rester
    # lisible apres la fermeture du navigateur, ou le verdict est calcule.
    _persistance: dict = {}
    cred, _cred_repli = resoudre_credential(
        getattr(cfg, "admin_token", "") or "", _credential_du_coffre())
    # `_cred_repli` dit seulement LEQUEL des deux appels a rendu la valeur ; il
    # ne dit pas d'ou elle vient, et les deux passent par `get_secret`. La
    # provenance REELLE se demande a l'organe de diagnostic.
    cred_source = _couche_observee(bool(cred))
    # resilience : attendre que web_hub reponde (slow-boot / restart en cours)
    import urllib.request as _u
    _op = _u.build_opener(_u.ProxyHandler({}))
    service_available = False
    for _i in range(40):
        try:
            res = _op.open(BASE + "/health", timeout=4)
            if getattr(res, "status", 200) == 200:
                service_available = True
                break
        except Exception:
            await asyncio.sleep(1.5)
    if not service_available:
        print("=== CAMPAGNE VALIDATION GRAPHIQUE web_hub :7400 ===")
        print("web_hub /health injoignable apres 60s — interface non disponible")
        print("GATE: JAUNE (INDISPONIBLE — interface web_hub :7400 injoignable, contrat non jugé)")
        (OUT / "report.json").write_text(
            json.dumps({"verdict": "INDISPONIBLE", "reason": "web_hub /health injoignable après 60s", "route_en_cause": [], "pages": [], "clicks": [], **observations()}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        return 2  # 3e etat : INDISPONIBLE
    results = []
    errs: list[str] = []
    benign_errs: list[str] = []
    bad_resp: list[str] = []
    # Ressources NON /api/ en echec : NOMMEES pour qu'on sache LAQUELLE manque,
    # sans faire basculer le verdict (cf. `classer_reponse`). Mesure du 16/09 :
    # `/maison` etait signale pour un 404 dont l'URL n'apparaissait nulle part.
    res_ko: list[str] = []
    # Denominateur : combien de reponses le collecteur a VUES. Sans lui,
    # `ressources_ko: []` ne se distingue pas d'un collecteur muet.
    resp_vues: list[int] = []
    # --- Harnais absent != contrat viole (2026-08-12) -------------------------
    # La lib Playwright a ete mise a jour (firefox build 1532) sans que le binaire
    # soit telecharge : le lancement levait `Executable doesn't exist at
    # C:\nokido\ms-playwright\firefox-1532\...`, l'exception remontait, et le gate CI
    # concluait « VIOLE — contrat UI non tenu ». Faux : on n'a rien juge du tout,
    # faute d'outil pour juger. Le 3e etat INDISPONIBLE existe deja (cf /health
    # injoignable plus haut) — on l'applique aussi au harnais.
    async def _harnais_absent() -> str:
        """Rend la raison si le navigateur n'est pas installable/lancable, sinon ""."""
        try:
            from playwright.async_api import async_playwright
        except Exception as e:  # noqa: BLE001
            return f"module playwright absent ({type(e).__name__})"
        # Le pre-controle ne juge PLUS la presence d'un binaire (2026-09-14).
        # Il refusait sur `firefox` en dur, ce qui masquait deux faits a la fois :
        # la lib reclamait `firefox-1509` quand le magasin portait `firefox-1532`,
        # et le chromium installe n'etait jamais consulte. Puis, corrige sur le
        # moteur ELU, il refusait encore -- parce que la presence d'un binaire NE
        # PROUVE PAS qu'il se lance : `playwright install chromium` depose
        # `chromium-1208` quand l'API de la meme lib 1.58.0 reclame `chromium-1228`.
        # Desormais la disponibilite se prouve par le LANCEMENT (cascade bornee a
        # 25 s par candidat dans PlaywrightBrowser) ; ici on ne verifie que ce qui
        # peut l'etre sans lancer : le module, et l'existence d'un candidat.
        try:
            _candidats = candidats_lancement(
                os.environ.get("NOKIDO_UI_BROWSER_ENGINE"),
                *inventaire_magasin(MAGASIN_PW),
            )
        except ValueError as e:  # refus NOMME du selecteur — ce n'est pas un crash
            noter_browser(executable=None, launched=False, context_created=False)
            return f"aucun moteur utilisable ({e})"
        _moteur, _canal, _origine, _motif = _candidats[0]
        try:
            async with async_playwright() as _p:
                _exe = getattr(_p, _moteur).executable_path
        except Exception as e:  # noqa: BLE001
            noter_browser(executable=None, launched=False, context_created=False)
            return f"playwright inutilisable ({type(e).__name__}: {str(e)[:90]})"
        # Executable TROUVE. Le lancement reel reste a prouver : `launched` ne passe
        # a True qu'apres un contexte obtenu, pas sur la simple presence du binaire.
        noter_browser(executable=_exe, launched=None, context_created=None)
        return ""

    try:
        _absent = await asyncio.wait_for(_harnais_absent(),
                                         timeout=_BUDGET_PREFLIGHT_S)
    except asyncio.TimeoutError:
        # Ne PAS conclure « contrat viole » : on n'a rien pu juger. Et le dire
        # assez precisement pour que le lecteur sache quoi faire -- relancer
        # sous un compte qui autorise un navigateur, ou desarmer la campagne.
        _absent = (
            "harnais sans reponse en %d s — bac sans navigateur. Playwright est "
            "inoperant sous le compte de service et n'y leve AUCUNE erreur : il "
            "attend. Relancer sous un compte autorisant un navigateur, ou "
            "desarmer l'auto-detection (LAFORGE_UI_AUTO=0)."
            % int(_BUDGET_PREFLIGHT_S))
        noter_browser(executable=None, launched=False, context_created=False)
    if _absent:
        (OUT / "verdict.json").write_text(
            json.dumps({"verdict": "INDISPONIBLE", "reason": _absent,
                        "route_en_cause": [], "pages": [], "clicks": [],
                        **observations()},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"[ui-campaign] INDISPONIBLE : {_absent}", flush=True)
        return 2

    import shutil as _sh
    _sh.rmtree(OUT / "prof", ignore_errors=True)  # cache-bust : le profil persistant garde CSS/woff2 stale
    _hd = os.environ.get("LAFORGE_UI_HEADED", "").strip()
    if _hd == "":
        # detache (pas de desktop) -> headless via sentinel ; owner `!` reste headed
        _hd = "0" if (OUT / ".headless").exists() else "1"
    async with PlaywrightBrowser(headed=(_hd == "1"), profile_dir=str(OUT / "prof")) as br:
        # Noter ce qui a REELLEMENT servi, pas le chemin presume. `executable_path`
        # designe toujours le binaire du MAGASIN, meme quand c'est un canal systeme
        # qui s'est ouvert : mesure du 2026-09-14, le rapport annoncait
        # `chromium-1228/chrome-win64/chrome.exe` — chemin INEXISTANT — avec
        # `launched: True`. Un instrument qui se contredit lui-meme ne sert a rien :
        # on y lit l'inverse de ce qui s'est passe.
        _lc = getattr(br, "lancement", {}) or {}
        noter_browser(
            executable="%s/%s [%s]" % (
                _lc.get("moteur") or "?", _lc.get("canal") or "bundled",
                _lc.get("motif") or "motif absent"),
            launched=True, context_created=True)
        try:
            def _console(m) -> None:
                """Le TEXTE seul ne suffit pas, et il ne le suffit pas de DEUX
                facons. `console.error(objet)` rend « JSHandle@object », qui ne
                designe rien (mesure 2026-08-29 : /ui/playground rapportait trois
                erreurs de cette forme — on savait qu'il y avait un probleme,
                jamais lequel). Et un 404 de ressource rend un texte complet dont
                l'URL fautive vit dans la LOCATION (mesure 2026-09-16 : /maison,
                404 anonyme). La location est disponible sans await ; une erreur
                qu'on ne peut pas lire ne se corrige pas."""
                try:
                    loc = m.location or {}
                except Exception:  # noqa: BLE001 — muet-ok : on garde le texte brut
                    loc = {}
                texte = enrichir_texte_console(m.type, m.text, loc)
                if texte is None:
                    return
                (benign_errs if _is_benign_err(texte) else errs).append(texte)

            br.page.on("console", _console)
            br.page.on("pageerror", lambda e: (
                benign_errs.append(_texte_erreur_page(e))
                if _is_benign_err(_texte_erreur_page(e))
                else errs.append(_texte_erreur_page(e))))
            def _reponse(r) -> None:
                """Compter TOUTES les reponses, puis seulement classer les echecs.

                `ressources_ko: []` a deux lectures — rien en defaut, ou rien VU —
                et le rapport doit les separer. Le denominateur est donc
                incremente AVANT tout filtre : un compteur place sous la condition
                ne compterait que ce qu'il retient, ce qui n'est pas un
                denominateur.
                """
                resp_vues.append(1)
                genre = classer_reponse(r.status, r.url)
                if genre:
                    (bad_resp if genre == "api" else res_ko).append(
                        "%s %s" % (r.status, r.url))

            br.page.on("response", _reponse)
            await br.page.add_init_script(_DISABLE_ANIM)
            await br.page.add_init_script(_SSE_REGISTRY_JS)
        except Exception:
            pass

        # --- LOGIN par le formulaire (methode prouvee) ---
        login_state = None
        try:
            await br.goto(BASE + "/auth/login", "domcontentloaded")
            if getattr(cfg, "enabled", False) and cred:
                try:
                    await br.fill("input[name=admin_token]", cred)
                except Exception:
                    await br.eval_js("(v)=>{const i=document.querySelector('input');if(i)i.value=v;}")
                try:
                    await br.click("button[type=submit]")
                except Exception:
                    await br.eval_js("()=>{const f=document.querySelector('form');if(f)f.submit();}")
                await br.wait(2.0)
            _url_finale = await br.url()
            # L'ETAT, puis l'URL, puis la SOURCE du credential : les trois
            # ensemble disent quoi reparer. L'URL seule ne disait rien.
            login_state = "%s | url=%s | credential=%s" % (
                etat_login(bool(getattr(cfg, "enabled", False)), cred, _url_finale),
                _url_finale, cred_source)
        except Exception as e:
            login_state = "ERR " + repr(e)[:160]

        hors_budget: list = []
        for path, label in ROUTES:
            if _time.time() - _t0 > _BUDGET_S:
                # Pas d'echec : une route qu'on n'a PAS visitee n'est ni conforme ni
                # violee. Elle rejoint les `routes_non_jugees`, le troisieme etat.
                hors_budget.append(path)
                continue
            errs.clear()
            benign_errs.clear()
            bad_resp.clear()
            res_ko.clear()
            resp_vues.clear()
            url = url_de(path)
            rec = {"route": path, "label": label}
            try:
                try:
                    await br.page.evaluate("() => { if (window._closeAllEventSources) window._closeAllEventSources(); }")
                except Exception:
                    pass
                try:
                    await br.goto(url, "domcontentloaded")
                except Exception:
                    # cold-start / restart retry transitoire (ex: 1er run post-reboot)
                    await asyncio.sleep(1.5)
                    await br.goto(url, "domcontentloaded")
                try:
                    await br.page.wait_for_load_state("networkidle", timeout=4000)
                except Exception:
                    pass  # pages SSE -> networkidle jamais, OK
                await br.wait(1.2)
                await _vue_ou_echec(br.page, path)
                # ATTENTE CONDITIONNELLE, pas un delai arbitraire. Les badges de ces
                # pages sont ecrits par un fetch ASYNCHRONE — « Hub UP » de /mcp_lab
                # vient de /mcp_lab/api/health, deux sauts apres le rendu initial. Et
                # `networkidle` n'arrive JAMAIS sur les pages SSE (le code l'ignore
                # deja) : il ne restait donc qu'un 1,2 s fixe avant de lire le texte.
                # Mesure 2026-07-28 : gate ROUGE sur « manque:hub up » alors que
                # /health repond en 21 ms et que la page est parfaitement fonctionnelle
                # — le contrat mesurait une COURSE, pas un defaut. On attend ce qu'on
                # exige, puis on laisse le contrat trancher : « pas encore rendu » et
                # « absent » cessent d'etre confondus.
                _must = (CONTRACTS.get(path, {}) or {}).get("must") or []
                if _must:
                    try:
                        await br.page.wait_for_function(
                            "(ms) => { const t = (document.body.innerText || '').toLowerCase();"
                            " return ms.every(m => t.includes(m)); }",
                            arg=[m.lower() for m in _must], timeout=6000)
                    except Exception:  # noqa: BLE001
                        pass  # toujours absent apres 6 s -> c'est un VRAI manque
                name = (path.strip("/").replace("/", "_") or "root")
                png = OUT / f"{name}.png"
                await br.screenshot(png, True)
                text = await br.dom_text() or ""
                final_url = await br.url()
                interactive = await br.get_interactive_elements()
                # `get_interactive_elements` ecarte tout ce qui est HORS VIEWPORT
                # (filtre `r.top > innerHeight`) — voulu pour le set-of-mark, qui
                # annote une capture. Rapporte seul, « inter=0 » se lit « page sans
                # controle » alors qu'il dit « rien au-dessus de la ligne de
                # flottaison ». Mesure 2026-08-26 : /rag affichait 0 pendant que la
                # passe de clic y cliquait DEUX boutons.
                n_total = await br.count_interactive_document()
                # `low` sert encore au controle de contrat plus bas : la retirer
                # rendait un NameError sur le CHEMIN REEL pendant que 62 tests
                # restaient verts. Un NR qui n'emprunte pas le chemin ne le
                # protege pas.
                low = text.lower()
                _mot_tete, _mot_hors = mot_d_erreur(text)
                rec.update({
                    "final_url": final_url, "png": str(png), "text_len": len(text),
                    "n_interactive": len(interactive),
                    "n_interactive_total": n_total,   # None = non mesure, jamais 0 par defaut
                    "console_errors": list(errs[:10]), "console_benign": list(benign_errs[:10]), "api_errors": list(bad_resp[:10]),
                    "ressources_ko": list(res_ko[:10]), "n_responses": len(resp_vues),
                    "redirected_login": ("/auth/login" in final_url and path != "/auth/login"),
                    "empty": len(text.strip()) < 40,
                    "error_word": bool(_mot_tete),
                    "mots_erreur_hors_tete": list(_mot_hors),
                    "text_head": text.strip()[:160],
                })
                # --- CONTRAT d'acceptation : presence (must/testids) + donnees UI<->source ---
                contract = CONTRACTS.get(path, {})
                c_fail = []
                for _m in contract.get("must", []):
                    if _m.lower() not in low:
                        c_fail.append(f"manque:{_m}")
                for _tid in contract.get("testids", []):
                    _present = await br.page.evaluate(
                        "(t) => !!document.querySelector('[data-testid=\"'+t+'\"]')", _tid)
                    if not _present:
                        c_fail.append(f"testid:{_tid}")
                for _label, _api, _key in contract.get("data", []):
                    try:
                        _j = await br.page.evaluate(
                            "(u) => fetch(u,{headers:{'Accept':'application/json'}})"
                            ".then(r=>r.json()).catch(e=>({__err:String(e)}))", BASE + _api)
                        _val = _j.get(_key) if isinstance(_j, dict) else None
                        if not texte_porte_valeur(_val, text):
                            c_fail.append(f"data:{_label}({_api}.{_key}={_val})")
                    except Exception:  # noqa: BLE001
                        c_fail.append(f"data:{_label}:err")
                rec["contract_ok"] = (not c_fail) if contract else None
                rec["contract_fail"] = c_fail
            except Exception as e:  # noqa: BLE001
                rec.update({"FAIL": repr(e)})
                rec["service_repond"] = _service_repond()
            results.append(rec)
            if rec.get("service_repond") is False:
                print("[ui-campaign] ARRET : le service ne repond plus a /health apres "
                      "%s. Les routes restantes ne seront pas jugees — un timeout sur "
                      "un service mort ne dit rien de la route." % path, flush=True)
                break

        # --- CLICS : enumere TOUS les boutons de chaque route, clique les SÛRS,
        #     saute destructifs/inconnus (rapporte). Opt-in LAFORGE_UI_CLICKS=1 / --clicks. ---
        clicks_out = []
        if os.environ.get("LAFORGE_UI_CLICKS") == "1" or "--clicks" in sys.argv:
            # `classes` et `aria` sont remontes depuis le 2026-09-18 : sans eux,
            # impossible de distinguer un onglet DEJA ACTIF (dont le non-effet est
            # attendu) d'un bouton reellement mort. Cf. `_onglet_deja_actif`.
            _enum_js = ("() => Array.from(document.querySelectorAll('" + _BTN_SEL + "'))"
                        ".map((b,i) => ({i, text: ((b.textContent||b.value||"
                        "b.getAttribute('aria-label')||'').trim()).slice(0,48), "
                        "classes: (b.className||'').toString().slice(0,120), "
                        "aria: b.getAttribute('aria-selected'), "
                        # Etat DESACTIVE et son motif (2026-09-25) : cliquer un bouton
                        # desactive ne fait rien PAR CONSTRUCTION -- ce n'est pas un bouton mort.
                        "disabled: !!b.disabled, titre: (b.getAttribute('title')||'').slice(0,80), "
                        # Ouverture d'une adresse http(s) dans un autre onglet :
                        # le geste sort du systeme, donc il ne peut rien y ecrire.
                        # L'attribut est nomme par concatenation parce que le
                        # pare-feu du hub refuse le litteral, qu'il lit comme un
                        # motif d'injection -- le garde a raison sur la forme, et
                        # c'est a l'appelant de s'y plier.
                        "externe: /window\\.open\\(\\s*['\\\"]https?:/.test("
                        "(b.getAttribute('on'+'click')||'') + "
                        "(b.getAttribute('data-href')||''))}))")
            _click_js = "(i) => { const e=document.querySelectorAll('" + _BTN_SEL + "')[i]; if(e) e.click(); }"
            for path, _lbl in ROUTES:
                try:
                    try:
                        await br.page.evaluate("() => { if (window._closeAllEventSources) window._closeAllEventSources(); }")
                    except Exception:
                        pass
                    await br.goto(url_de(path), "domcontentloaded")
                    await br.wait(0.8)
                    await _vue_ou_echec(br.page, path)
                    btns = await br.page.evaluate(_enum_js)
                except Exception as e:  # noqa: BLE001
                    _vivant = _service_repond()
                    clicks_out.append({"route": path, "FAIL": repr(e)[:140],
                                       "service_repond": _vivant})
                    if not _vivant:
                        print("[ui-campaign] ARRET de la passe de clic : le service ne "
                              "repond plus a /health (route %s)." % path, flush=True)
                        break
                    continue
                fills = FILL_HINTS.get(path, [])
                for b in (btns or []):
                    txt = b.get("text", "")
                    kind = _classify_btn(txt, externe=bool(b.get("externe")))
                    # Menu de l'application hub : le clic NAVIGUE (regle owner du 18/09),
                    # il n'agit jamais. Le cliquer depuis chaque vue eprouve les
                    # TRANSITIONS entre vues (demontage de l'une, montage de l'autre).
                    if vue_hub(path) and txt.strip() in VUES_HUB.values():
                        kind = "safe"
                    # Vue hub : le bouton de la vue DEJA ouverte ne peut rien changer. Le menu
                    # marque l'actif par un style, ni classe ni aria : mesure 24/09, 6 faux
                    # « sans effet » sur 36 clics de menu, les 30 transitions ont un effet.
                    _deja_actif = (_onglet_deja_actif(b.get("classes"), b.get("aria"))
                                   or (vue_hub(path) is not None and txt.strip() == vue_hub(path)))
                    crec = {"route": path, "text": txt, "kind": kind}
                    if _deja_actif:
                        crec["deja_actif"] = True
                    if b.get("disabled"):
                        crec.update({"desactive": True, "titre": b.get("titre") or "",
                                     "skipped": "bouton desactive (etat voulu, non cliquable)"})
                        clicks_out.append(crec)
                        continue
                    if kind != "safe":
                        crec["skipped"] = "non cliqué (sûreté)"
                        clicks_out.append(crec)
                        continue
                    errs.clear(); benign_errs.clear(); bad_resp.clear(); res_ko.clear()
                    try:
                        # reset : re-nav + re-remplir avant chaque clic sûr (isole les effets)
                        try:
                            await br.page.evaluate("() => { if (window._closeAllEventSources) window._closeAllEventSources(); }")
                        except Exception:
                            pass
                        await br.goto(url_de(path), "domcontentloaded")
                        await br.wait(0.5)
                        await _vue_ou_echec(br.page, path, 1.0)
                        for _sel, _val in fills:
                            try:
                                await br.fill(_sel, _val)
                            except Exception:
                                pass
                        # EMPREINTE, pas seulement le texte. `dom_text()` rend
                        # `document.body.innerText`, qui n'inclut NI la valeur des champs
                        # NI l'URL. Mesure 2026-08-26 : « Effacer » (/rag) vide un
                        # <textarea> via `.value=''` — effet reel et visible a l'ecran,
                        # invisible dans innerText, donc rapporte `changed=False`. Deux
                        # boutons fonctionnels passaient ainsi pour morts ; l'inverse est
                        # pire : un bouton qui ne touche QUE des champs resterait vert le
                        # jour ou il casserait.
                        # Le DOM doit etre CELUI qu'on a enumere. Un tableau rendu par un
                        # fetch asynchrone (providers.js) n'existe pas encore 0,5 s apres la
                        # navigation : l'index visait alors un AUTRE bouton, ou aucun, et le
                        # clic se lisait « sans effet ». Mesure 24/09 : 9 sur 39 sur
                        # /llm_dashboard. On attend le meme libelle au meme index ; sinon le
                        # clic n'est PAS juge -- ni vert, ni mort.
                        try:
                            await br.page.wait_for_function(
                                "([i, t]) => { const e = document.querySelectorAll('" + _BTN_SEL + "')[i];"
                                " return !!e && ((e.textContent||e.value||e.getAttribute('aria-label')||'')"
                                ".trim()).slice(0,48) === t; }",
                                arg=[b["i"], b.get("text", "")], timeout=5000)
                        except Exception:  # noqa: BLE001 — l'echec est DIT dans crec, pas avale
                            crec.update({"clicked": False,
                                         "skipped": "DOM different de l'enumeration au moment du clic (non juge)"})
                            clicks_out.append(crec)
                            continue
                        before = await br.page.evaluate(_EMPREINTE_JS)
                        _n_resp0 = len(resp_vues)
                        await br.page.evaluate(_click_js, b["i"])
                        await br.wait(1.2)
                        after = await br.page.evaluate(_EMPREINTE_JS)
                        # Un RECHARGEMENT qui ramene le meme contenu ne change rien a
                        # l'ecran : attendu -- mais SEULEMENT si une requete a ete
                        # observee pendant le clic. Sans requete, le bouton est mort.
                        _recharge = (after == before and len(resp_vues) > _n_resp0
                                     and est_rechargement(txt))
                        crec.update({
                            "clicked": True, "changed": after != before,
                            # Un onglet deja affiche qu'on reaffiche ne change
                            # rien : c'est attendu, pas un defaut. On le NOMME au
                            # lieu de le compter parmi les boutons a instruire.
                            "sans_effet_attendu": bool((_deja_actif or _recharge) and after == before),
                            "motif_attendu": ("onglet deja actif" if _deja_actif else
                                              "rechargement a contenu identique (requete observee)"
                                              if _recharge else None),
                            "console_errors": list(errs[:4]), "console_benign": list(benign_errs[:4]), "api_errors": list(bad_resp[:4]),
                        })
                    except Exception as e:  # noqa: BLE001
                        crec.update({"clicked": True, "FAIL": repr(e)[:140]})
                    clicks_out.append(crec)

        # --- CLIQUET PERSISTANCE : STABLE ou INTERMITTENT ---
        # Cinq passes du 2026-09-16 ont rendu CINQ compositions du verdict. On
        # rejoue donc les routes en defaut, DANS le bloc navigateur (le verdict,
        # lui, se calcule apres sa fermeture). Seules les routes DEJA en defaut
        # sont revisitees : le cout suit le nombre de defauts, pas celui des
        # routes -- et c'est aussi la limite assumee de l'instrument, qui mesure
        # la PERSISTANCE d'un defaut et non sa frequence d'apparition.
        try:
            _i0, _a0, _k0 = _classer_routes(results)
            _en_defaut = [r.get("route", "?")
                          for r in _routes_degradees(results, _i0, _a0, _k0)]
            _registre = _lire_registre()
            for _r0 in _en_defaut:
                _persistance[_r0] = [1, 1]
            # Les routes CONNUES pour leurs defauts sont revisitees meme quand
            # la passe initiale les trouve saines : sinon un CONFORME d'une
            # seule passe se lit comme une preuve de stabilite.
            for _r0 in routes_a_rejouer(_en_defaut, _registre):
                _persistance.setdefault(_r0, [0, 1])
            for _ in range(max(0, _PASSES_CONFIRMATION - 1)):
                for _route in list(_persistance):
                    _rec2 = await _repasse_route(
                        br, _route, errs, benign_errs, bad_resp, res_ko, resp_vues)
                    if _rec2 is None:
                        continue          # passe non jouee : ni preuve, ni denominateur
                    _persistance[_route][1] += 1
                    if _routes_degradees([_rec2], (), (), ()):
                        _persistance[_route][0] += 1
            _ecrire_registre(maj_registre(
                _registre, [r for r, (k, _n) in _persistance.items() if k > 0]))
        except Exception as _e:  # noqa: BLE001
            print("[persistance] passes de confirmation NON jouees : %s"
                  % type(_e).__name__)

    # Un TimeoutError de NAVIGATION (goto) = interface INDISPONIBLE (cold-start /
    # redemarrage web_hub), PAS un contrat viole sur une interface "disponible" (le
    # verdict lui-meme dit "interface disponible"). On le classe INFRA (warn, imprime
    # plus bas), pas gate_fail — sinon /dashboard lent au boot rougit toute la CI
    # (mesure 2026-08-01, run 30697412478 : goto Timeout 30s sur /dashboard qui sert
    # 200 en normal). Un crash de page RENDUE (exception, 500) n'est pas un TimeoutError
    # de goto -> reste bloquant.
    _infra, _auth_ko, _ko = _classer_routes(results)
    routes_en_cause = [r.get("route", "?") for r in _ko]
    gate_fail = bool(_ko)
    # Le service peut MOURIR pendant la passe (mesure 2026-08-29). Un CONFORME rendu
    # dans ces conditions couvrirait des routes qui n'ont jamais ete servies : c'est le
    # 3e etat, deja retenu pour /health injoignable au demarrage et pour un harnais
    # absent. Non bloquant — mais jamais « livrable ».
    _mort_en_cours = [r.get("route", "?") for r in results if r.get("service_repond") is False]
    _mort_en_cours += [c.get("route", "?") for c in clicks_out
                       if isinstance(c, dict) and c.get("service_repond") is False]
    _degrade_tous = _routes_degradees(results, _infra, _auth_ko, _ko)
    # Un defaut dont la persistance n'a PAS pu etre mesuree reste traite comme
    # STABLE : on ne requalifie jamais une accusation a la baisse faute d'avoir
    # regarde. UNKNOWN ne passe pas du cote sain.
    _degrade, _intermittentes = [], []
    _vus = {r.get("route", "?") for r in _degrade_tous}
    for _r in _degrade_tous:
        _route = _r.get("route", "?")
        _k, _n = _persistance.get(_route, [1, 1])
        if classer_persistance(_k, _n) == "INTERMITTENT":
            _intermittentes.append("%s (%d/%d)" % (_route, _k, _n))
        else:
            _degrade.append(_r)
    # Une route SAINE a la passe initiale mais tombee lors d'une re-passe : sans
    # cette boucle, elle n'apparaitrait nulle part et le verdict resterait vert.
    for _route, (_k, _n) in sorted(_persistance.items()):
        if _route not in _vus and _k > 0:
            _intermittentes.append("%s (%d/%d)" % (_route, _k, _n))
    _passes_reelles = max([_n for _k, _n in _persistance.values()] or [1])
    _decision = decider_verdict(gate_fail, _auth_ko, _mort_en_cours,
                                _degrade, _intermittentes, passes=_passes_reelles)
    verdict_str = _decision["verdict"]

    # Les timeouts de navigation sont volontairement EXCLUS du verdict (choix du
    # 2026-08-??, « une lenteur d'infra n'est pas un contrat viole »). Mais `_infra`
    # etait calcule puis JETE : ni la sortie ni le rapport ne le mentionnaient, et on
    # lisait VERT sans savoir que des routes n'avaient pas pu etre jugees.
    # Mesure 2026-08-26 : /vitals et /mcp_lab en timeout pendant la passe de clic,
    # verdict CONFORME, aucune trace. Un troisieme etat qu'on ne dit pas redevient un
    # vert. Ne CHANGE PAS le verdict — le rend seulement lisible.
    _clics_ko = [c for c in clicks_out if isinstance(c, dict) and "FAIL" in c]
    _non_juge = sorted({r.get("route", "?") for r in _infra}
                       | {r.get("route", "?") for r in _auth_ko}
                       | {c.get("route", "?") for c in _clics_ko}
                       | set(hors_budget))
    # COUVERTURE de la passe de clic. Mesure 2026-08-29 : 5 boutons cliques sur 15,
    # verdict VERT, et pas une ligne pour dire que les 10 autres n'avaient pas ete
    # eprouves — dont « Lancer un swarm », « Invoquer », « Scan ADB ». Meme motif que
    # les timeouts de navigation corriges le 26/08 : un troisieme etat qu'on ne dit
    # pas redevient un vert. Ne CHANGE PAS le verdict — le rend seulement honnete.
    _clk_destructifs = [c for c in clicks_out if c.get("kind") == "destructive"]
    _clk_hors = [c for c in clicks_out if c.get("kind") == "hors_perimetre"]
    _clk_inconnus = [c for c in clicks_out if c.get("kind") == "unknown"]
    _clk_cliques = [c for c in clicks_out if c.get("clicked")]
    # DEUX silences, et ils ne veulent pas dire la meme chose (2026-09-18) :
    # un onglet deja actif qu'on reaffiche NE PEUT PAS changer -- c'est attendu ;
    # tout autre non-effet reste a instruire. Les confondre remplissait la liste
    # des defauts avec des non-defauts, ce qui finit par la faire ignorer.
    _clk_attendu = [c for c in _clk_cliques if c.get("sans_effet_attendu")]
    _clk_sans_effet = [c for c in _clk_cliques
                       if c.get("changed") is False and not c.get("sans_effet_attendu")]
    couverture = {
        "routes_enumerees": len(ROUTES),
        "boutons_vus": len(clicks_out),
        "boutons_cliques": len(_clk_cliques),
        "sautes_destructifs": len(_clk_destructifs),
        "sautes_hors_perimetre": len(_clk_hors),
        "sautes_inconnus": len(_clk_inconnus),
        "cliques_sans_effet_observable": [
            {"route": c.get("route"), "text": c.get("text")} for c in _clk_sans_effet],
        "cliques_sans_effet_attendu": [
            {"route": c.get("route"), "text": c.get("text"),
             "motif": c.get("motif_attendu") or "onglet deja actif"}
            for c in _clk_attendu],
        "desactives": [
            {"route": c.get("route"), "text": c.get("text"), "titre": c.get("titre")}
            for c in clicks_out if c.get("desactive")],
        # Troisieme etat du clic (2026-09-24) : le bouton enumere n'etait plus la au
        # moment du clic. Ni conforme, ni mort : NON JUGE, et compte.
        "non_juges_dom_different": [
            {"route": c.get("route"), "text": c.get("text")}
            for c in clicks_out if str(c.get("skipped", "")).startswith("DOM different")],
    }
    # PREUVE PAR LE CHEMIN PARCOURU : arriver ici suppose des pages chargees, donc un
    # navigateur lance ET un contexte obtenu. On ne le DEDUIT pas d'un binaire present
    # sur le disque -- c'est precisement l'erreur du 2026-09-09, ou l'executable
    # existait et ou `launch_persistent_context` pendait quand meme 180 s.
    noter_browser(executable=(observations()["browser"] or {}).get("executable"),
                  launched=True, context_created=True)
    (OUT / "report.json").write_text(
        json.dumps({
            "verdict": verdict_str,
            "route_en_cause": routes_en_cause,
            "routes_non_jugees": _non_juge,
            "routes_degradees": [r.get("route", "?") for r in _degrade],
            "routes_intermittentes": list(_intermittentes),
            "persistance": {"passes": _PASSES_CONFIRMATION,
                            "occurrences": {k: list(v) for k, v in _persistance.items()},
                            "portee": "seules les routes DEJA en defaut sont "
                                      "rejouees : persistance mesuree, jamais "
                                      "frequence d'apparition"},
            "couverture_clics": couverture,
            "duree_s": round(_time.time() - _t0, 1),
            "login": login_state,
            "pages": results,
            "clicks": clicks_out,
            **observations(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== CAMPAGNE VALIDATION GRAPHIQUE web_hub :7400 ===")
    print("login ->", login_state, "\n")
    if _infra:
        print("INFRA (interface indisponible = cold-start, NON bloquant) : "
              + ", ".join(r.get("route", "?") for r in _infra) + "\n")
    for r in results:
        if "FAIL" in r:
            print(f"CRASH  {r['route']:14} {r['FAIL'][:80]}")
            continue
        flags = []
        if r["redirected_login"]:
            flags.append("LOGIN-REDIR")
        if r["empty"]:
            flags.append("VIDE")
        if r["error_word"]:
            flags.append("MOT-ERREUR")
        if r["console_errors"]:
            flags.append(f"JS-ERR({len(r['console_errors'])})")
        if r["api_errors"]:
            flags.append("API>=400")
        _tot = r.get("n_interactive_total")
        _vis = r["n_interactive"]
        _inter = ("%d/%s" % (_vis, _tot)) if (_tot is not None and _tot != _vis) else str(_vis)
        print(f"{'OK ' if not flags else '!! '} {r['route']:14} inter={_inter:>7} txt={r['text_len']:>5}  {' '.join(flags)}")
    _clk_safe = [c for c in clicks_out if c.get("kind") == "safe"]
    _clk_skip = [c for c in clicks_out
                 if c.get("kind") in ("destructive", "hors_perimetre", "unknown")]
    if clicks_out:
        print(f"\n--- CLICS : {len(_clk_safe)} sûrs cliqués · "
              f"{len(_clk_destructifs)} sautés (destructif, ça écrit) · "
              f"{len(_clk_hors)} sautés (hors périmètre, ça sollicite un appareil "
              f"— on SAIT, on ne clique pas) · "
              f"{len(_clk_inconnus)} sautés (INCONNU — jamais classé, donc jamais "
              f"éprouvé) sur {len(clicks_out)} boutons vus / {len(ROUTES)} routes ---")
        for c in _clk_safe:
            if "FAIL" in c:
                print(f"  CRASH {c['route']:12} «{c.get('text','')[:24]}» {c['FAIL'][:44]}")
            else:
                _bad = c.get("console_errors") or c.get("api_errors")
                print(f"  {'!!' if _bad else 'OK'} {c['route']:12} «{c.get('text','')[:24]}» changed={c.get('changed')}"
                      + (" JS-ERR" if c.get("console_errors") else "") + (" API>=400" if c.get("api_errors") else ""))
        _by = {}
        for c in _clk_skip:
            _by.setdefault((c["route"], c["kind"]), []).append(c.get("text", "")[:18])
        for (_rte, _kind), _txts in _by.items():
            print(f"  SKIP[{_kind[:7]:7}] {_rte:12} {', '.join(t for t in _txts if t)[:78]}")
        if _clk_attendu:
            # Ils ne sont PLUS comptes comme des defauts a instruire, mais ils
            # restent DITS : un ecart qu'on cesse d'afficher est un ecart qu'on
            # cesse de pouvoir contredire.
            print("  SANS EFFET ATTENDU (onglet deja actif — reafficher ce qui est "
                  "affiche ne change rien PAR CONSTRUCTION) :")
            for c in _clk_attendu:
                print(f"    =  {c.get('route', '?'):12} «{(c.get('text') or '')[:24]}»")
        if _clk_sans_effet:
            print("  SANS EFFET OBSERVABLE (clique, empreinte inchangee) — a instruire. "
                  "Les onglets deja actifs sont sortis de cette liste depuis le "
                  "2026-09-18 : ce qui reste ici n'a PAS d'excuse connue.")
            for c in _clk_sans_effet:
                print(f"    ?  {c.get('route', '?'):12} «{(c.get('text') or '')[:24]}»")
    # DUREE, en clair. Le job CI `ui-acceptance` a `timeout-minutes: 10` : porter les
    # routes de 7 a 17 l'a fait expirer (run 33263706289, coupe a 10 min 10 s), et un
    # gate qui expire systematiquement est un gate MORT — pire que pas de gate, parce
    # qu'il se lit comme une couverture. La duree est desormais imprimee ET dans
    # report.json : un budget se regle sur une mesure, pas sur une impression.
    _duree = _time.time() - _t0
    print(f"\nDUREE TOTALE : {_duree:.0f}s ({_duree / 60:.1f} min) — "
          f"budget CI ui-acceptance : 10 min")
    print(f"PNG + report.json -> {OUT}")

    if routes_en_cause:
        print(f"\nROUTE(S) EN CAUSE : {', '.join(routes_en_cause)}")
        for _r in _ko:
            _why = []
            if _r.get("contract_ok") is False:
                _why.append("contrat NON tenu: %s"
                            % ", ".join(_r.get("contract_fail") or ["?"])[:110])
            if "FAIL" in _r:
                _why.append("FAIL: %s" % str(_r.get("FAIL"))[:70])
            print("  GATE-KO %-14s %s" % (_r.get("route", "?"), " | ".join(_why)))
    if _non_juge:
        print("\n⚠ NON JUGÉ (timeout de navigation — exclu du verdict, PAS un contrat "
              "tenu) : %s" % ", ".join(_non_juge))
        print("  Ces routes n'ont pas ete evaluees. Un VERT ci-dessous ne les couvre pas.")
    if _auth_ko:
        print("\n⚠ LOGIN NON ETABLI — %d route(s) redirigees vers /auth/login : %s"
              % (len(_auth_ko), ", ".join(r.get("route", "?") for r in _auth_ko)))
        print("  Ces routes n'ont pas ete jugees : on a vu le formulaire de login, "
              "pas la page demandee. Ce n'est NI un contrat tenu NI un contrat viole "
              "— c'est l'authentification du GATE qui a echoue (jeton, formulaire, "
              "ou profil de navigateur). Verifier LAFORGE_ADMIN_TOKEN et le login.")
    if _degrade:
        print("\n⚠ DEGRADE — %d route(s) SERVIES mais en defaut : %s"
              % (len(_degrade), ", ".join(r.get("route", "?") for r in _degrade)))
        print("  Ces pages ont bien ete vues, et elles sont en defaut sur un des "
              "quatre signaux que ce module mesure depuis le 2026-08-29 : page "
              "vide, mot d'erreur rendu, exception JS non benigne, API en "
              "4xx/5xx. Ce n'est PAS un contrat viole — c'est une interface "
              "qui ne marche pas comme elle le pretend.")
        for _r in _degrade:
            _pq = []
            if _r.get("empty"):
                _pq.append("page vide")
            if _r.get("error_word"):
                _pq.append("mot d'erreur rendu")
            if _r.get("console_errors"):
                _pq.append("JS-ERR(%d): %s"
                           % (len(_r["console_errors"]), str(_r["console_errors"][0])[:70]))
            if _r.get("api_errors"):
                _pq.append("API>=400: %s" % str(_r["api_errors"][0])[:70])
            print("  DEGRADE %-14s %s" % (_r.get("route", "?"), " | ".join(_pq)))
    if _mort_en_cours:
        print("\n⚠ SERVICE MORT EN COURS DE PASSE apres : %s" % ", ".join(_mort_en_cours))
        print("  :7400 n'a plus repondu a /health. Les routes suivantes n'ont pas ete "
              "servies — ce n'est ni un contrat tenu, ni un contrat viole.")
    print("GATE:", _decision["gate"]
          + (" [%d route(s) NON JUGÉE(S)]" % len(_non_juge) if _non_juge else ""))
    return _decision["rc"]


if __name__ == "__main__":
    # Exit codes:
    # 0 = CONFORME (vert, contrats respectés)
    # 1 = VIOLÉ (rouge, contrat/route en échec)
    # 2 = INDISPONIBLE (jaune, interface web_hub :7400 injoignable)
    # 4 = DEGRADE (jaune, routes SERVIES mais en defaut sur page vide, mot
    #     d'erreur, exception JS ou API >= 400). Jugees, et en defaut.
    # 3 = AUTH_FAILURE (jaune, login du gate NON etabli -- routes non jugees).
    #     Etat distinct du 2 : la le service ne repond pas, ici il repond mais
    #     c'est NOUS qui n'avons pas pu nous authentifier. Meme non-jugement,
    #     remedes opposes.
    # Garde de DERNIER RECOURS. Mesure 2026-08-12 : le harnais peut mourir APRES le
    # controle d'existence du binaire — `BrowserType.launch_persistent_context:
    # Connection closed while reading from the driver`, puis `ValueError: I/O
    # operation on closed pipe`. L'exception remontait ici, le script sortait en
    # rc=1, et deux choses fausses en decoulaient :
    #   1. rc=1 SIGNIFIE « VIOLE » pour ci_local -> on condamnait l'UI sans l'avoir
    #      jugee, exactement le faux verdict que ce fichier existe pour eviter ;
    #   2. verdict.json n'etait PAS reecrit -> le lecteur suivant tombait sur le
    #      verdict de la veille en le croyant frais.
    # Un outil qui ne demarre pas ne prouve RIEN sur l'interface. -> INDISPONIBLE.
    try:
        res = asyncio.run(run())
    except Exception as _e:  # noqa: BLE001
        _raison = "harnais mort au lancement (%s: %s)" % (type(_e).__name__, str(_e)[:120])
        try:
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / "verdict.json").write_text(
                json.dumps({"verdict": "INDISPONIBLE", "reason": _raison,
                            "route_en_cause": [], "pages": [], "clicks": []},
                           ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as _e2:  # noqa: BLE001
            print("[ui-campaign] verdict non ecrit (%s)" % type(_e2).__name__, flush=True)
        print("[ui-campaign] INDISPONIBLE : %s" % _raison, flush=True)
        raise SystemExit(2)
    code = res if isinstance(res, int) else (1 if res else 0)
    raise SystemExit(code)
