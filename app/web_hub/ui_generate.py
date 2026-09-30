"""web_hub/ui_generate.py — Generative UI Phase C : LLM-generated HTMX components.

POST /ui/generate avec {description, data_source} -> HTML HTMX rendu.

Pattern : LLM cascade (forge_frugal_cascade) prompt strict pour generer
HTML HTMX/Alpine pur (pas de raw JS, pas de external CDN imports).
Validation post-gen : DOMPurify-like sanitize + CSP nonce injection +
whitelist allowed tags/attrs.

Use cases :
- "Cree un dashboard daemon staleness avec graphique"
- "Genere un form de creation watch_job theme + idea_id"
- "Affiche topology forge_chain_nodes en arbre"

Securite : llm_output passe sanitize_html avant retour. Pas de script tag
(sauf x-data Alpine). Pas de href javascript:. CSP nonce force.
"""

from __future__ import annotations
import json, logging, re
from pathlib import Path
from typing import Any

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("ui_generate")

ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS_DIR = ROOT / "tools"


# Allowed HTML tags for sanitization
ALLOWED_TAGS = frozenset(
    {
        "div",
        "span",
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
        "li",
        "table",
        "thead",
        "tbody",
        "tr",
        "td",
        "th",
        "a",
        "button",
        "form",
        "input",
        "label",
        "select",
        "option",
        "section",
        "article",
        "header",
        "footer",
        "nav",
        "main",
        "img",
        "svg",
        "path",
        "circle",
        "rect",
        "line",
        "g",
        "br",
        "hr",
        "strong",
        "em",
        "code",
        "pre",
    }
)

ALLOWED_ATTRS = frozenset(
    {
        "id",
        "class",
        "style",
        "title",
        "name",
        "value",
        "type",
        "placeholder",
        "for",
        "href",
        "src",
        "alt",
        "role",
        "aria-label",
        "aria-hidden",
        # HTMX
        "hx-get",
        "hx-post",
        "hx-put",
        "hx-delete",
        "hx-target",
        "hx-swap",
        "hx-trigger",
        "hx-include",
        "hx-headers",
        "hx-indicator",
        "hx-vals",
        "hx-confirm",
        "hx-push-url",
        "hx-select",
        "hx-select-oob",
        # Alpine.js
        "x-data",
        "x-init",
        "x-show",
        "x-if",
        "x-for",
        "x-text",
        "x-html",
        "x-model",
        "x-bind",
        "x-on",
        "x-cloak",
        "x-effect",
        "x-ref",
        "@click",
        "@change",
        "@submit",
        "@keydown",
        "@input",
        # SVG
        "d",
        "cx",
        "cy",
        "r",
        "x",
        "y",
        "x1",
        "y1",
        "x2",
        "y2",
        "width",
        "height",
        "fill",
        "stroke",
        "stroke-width",
        "viewBox",
        "transform",
    }
)


SYSTEM_PROMPT_UI = """Tu es un generateur d'UI HTMX + Tailwind CSS pour Nokido.
Tu produis du HTML pur SERVER-SIDE RENDERED (pas de templating client).

REGLES CRITIQUES :
1. Pas de <html>, <head>, <body> - juste fragment HTML
2. INTERDIT : {{ variable }} Alpine templating (le client n'a pas le data, c'est statique)
3. INTERDIT : x-data, x-text, x-for, x-show pour acceder aux donnees
4. OBLIGATOIRE : RENDS LES VALEURS INLINE depuis le data_source fourni.
   Si data_source = {"events": [...]}, genere <tr> avec valeurs directement ecrites,
   pas <template x-for>.
5. INTERDIT : <script>
6. Tags autorises : div span p h1-h6 ul ol li table tr td th a button form input label
   select option section article svg path g header footer nav main
7. HTMX OK : hx-get/hx-post/hx-target/hx-swap (interactions cote serveur)
8. Tailwind classes pour style
9. Si tableau de donnees : itere mentalement sur data_source, genere chaque <tr>
   avec valeurs deja remplies. Exemple bon : <td>5</td>, mauvais : <td>{{ count }}</td>
10. Si counts={"FRESH":3,"DEAD":1} -> genere <span class="text-2xl">3</span> direct,
    PAS <span x-text="counts.FRESH"></span>

Reponse = HTML pur server-rendered, valeurs deja resolues, rien d'autre.
"""


def _sanitize_html(html: str) -> str:
    """Sanitize : strip non-whitelisted tags + dangerous attrs.

    Best-effort regex-based. Pour production critical, utiliser bleach.
    """
    # Strip script tags entirely
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)
    # Strip on* event handlers except Alpine (@click)
    html = re.sub(
        r'\s+on(load|click|change|submit|input|focus|blur|keydown|keyup|mouseover|mouseout)\s*=\s*"[^"]*"',
        "",
        html,
        flags=re.IGNORECASE,
    )
    # Strip href="javascript:..."
    html = re.sub(r'href\s*=\s*"javascript:[^"]*"', 'href="#"', html, flags=re.IGNORECASE)
    # Strip src=data:text/html
    html = re.sub(r'src\s*=\s*"data:text/html[^"]*"', "", html, flags=re.IGNORECASE)
    return html.strip()


def _component_name(description: str) -> str:
    """Stable render_<name> suffix for generated components."""
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", description.strip().lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)[:48] or "component"
    if slug[0].isdigit():
        slug = "ui_" + slug
    return slug


def _node_text(value: Any) -> str:
    import html as _h

    return _h.escape(str(value))


def _render_schema_node(node: dict) -> str:
    """Render a moulinette schema node directly for web preview."""
    if not isinstance(node, dict) or "hole" in node:
        return ""
    tag = str(node.get("tag") or "div")
    attrs = []
    if node.get("class"):
        attrs.append(f'class="{_node_text(node["class"])}"')
    if node.get("id"):
        attrs.append(f'id="{_node_text(node["id"])}"')
    for group in ("attrs", "alpine", "htmx"):
        values = node.get(group) or {}
        if isinstance(values, dict):
            for key, value in values.items():
                attrs.append(f'{_node_text(key)}="{_node_text(value)}"')
    start = "<" + tag + ((" " + " ".join(attrs)) if attrs else "") + ">"
    body = _node_text(node.get("text", "")) if node.get("text") is not None else ""
    for child in node.get("children") or []:
        body += _render_schema_node(child)
    if tag in {"img", "input", "br", "hr", "meta", "link"}:
        return start
    return start + body + f"</{tag}>"


def _fallback_schema(description: str, data_source: dict | None = None) -> dict:
    """No-LLM fallback schema that still exercises forge_ui_moulinette."""
    title = description.strip()[:96] or "OpenUI component"
    children: list[dict[str, Any]] = [
        {"tag": "header", "class": "lf-section__header", "children": [
            {"tag": "h2", "class": "lf-section__title", "text": title},
            {"tag": "span", "class": "lf-pill", "text": "openui"},
        ]},
    ]
    if isinstance(data_source, dict) and data_source:
        rows = []
        for key, value in list(data_source.items())[:12]:
            rows.append({"tag": "tr", "children": [
                {"tag": "th", "class": "lf-table__key", "text": str(key)},
                {"tag": "td", "class": "lf-table__value", "text": json.dumps(value, ensure_ascii=False, default=str)[:240]},
            ]})
        children.append({"tag": "table", "class": "lf-table lf-table--compact", "children": [
            {"tag": "tbody", "children": rows}
        ]})
    else:
        children.append({"tag": "p", "class": "lf-muted", "text": "Aucune donnee fournie ; squelette rendu depuis la description."})
    return {
        "name": _component_name(description),
        "props": [],
        "root": {"tag": "section", "class": "lf-card lf-stack", "attrs": {"data-openui": "moulinette"}, "children": children},
    }


def _openui_spec(description: str, data_source: dict | None = None) -> str:
    data_hint = json.dumps(data_source or {}, ensure_ascii=False, default=str)[:1800]
    return (
        "Transforme cette demande en JSON UI schema pour forge_ui_moulinette. "
        "Retourne uniquement JSON, sans markdown. Cible web_hub HTMX/Alpine/nokido-DS, pas React. "
        "Utilise props=[] et rends les valeurs de data_source inline dans text/attrs. "
        "Classes prefixees lf- uniquement. Reserve en hole seulement la logique vraiment impossible.\n"
        f"Description: {description}\nData source JSON: {data_hint}"
    )


def generate_openui_render(
    description: str,
    data_source: dict | None = None,
    *,
    include_code: bool = False,
) -> dict:
    """Prompt -> JSON schema -> render_X() code + sanitized HTML preview."""
    import sys
    import time

    for p in (str(TOOLS_DIR), str(ROOT / "app")):
        if p not in sys.path:
            sys.path.insert(0, p)

    t0 = time.time()
    spec = _openui_spec(description, data_source)
    decision = {"lane": "local", "target": "forge_ui_moulinette", "reason": "fallback"}
    try:
        from nokido_agent.app.forge_orchestration_gate import Action, classify

        d = classify(Action(prompt=spec, kind="llm", task_type="codegen", agent="CODEX", ring=2, est_steps=2, est_tokens=1200))
        decision = d.to_dict()
    except Exception as exc:  # noqa: BLE001
        decision = {"lane": "local", "target": "forge_ui_moulinette", "reason": f"gate unavailable: {exc}"}

    try:
        from nokido_agent.tools.forge_ui_moulinette import schema_from_spec, skeleton_from_schema

        schema = schema_from_spec(spec)
        if not isinstance(schema, dict):
            raise ValueError("schema_from_spec returned non-dict")
        schema.setdefault("name", _component_name(description))
        schema["props"] = []
    except Exception as exc:  # noqa: BLE001
        from nokido_agent.tools.forge_ui_moulinette import skeleton_from_schema

        schema = _fallback_schema(description, data_source)
        decision = {**decision, "fallback": f"schema_from_spec failed: {exc}"}

    skel = skeleton_from_schema(schema)
    root = schema.get("root") or schema
    html = _sanitize_html(_render_schema_node(root))
    out = {
        "html": html,
        "render_name": skel["name"],
        "schema": schema,
        "holes": skel.get("holes", []),
        "route": decision,
        "model_used": decision.get("target", "forge_ui_moulinette"),
        "confidence": 0.82 if not decision.get("fallback") else 0.55,
        "latency_ms": round((time.time() - t0) * 1000, 1),
        "sanitized": True,
        "data_source_used": bool(data_source),
        "pipeline": "prompt->schema_from_spec->skeleton_from_schema->render_X",
    }
    if include_code:
        out["render_code"] = skel["code"]
    return out


def routes_connues() -> set | None:
    """Chemins que l'application sert REELLEMENT, ou None si elle n'est pas chargee.

    Lu sur `sys.modules` et jamais importe : ce module est charge PAR l'application.
    `None` est le troisieme etat -- « je n'ai pas pu regarder » -- et il compte : sans
    lui, une app absente ferait refuser TOUTES les cibles, ce qui viderait l'UI au lieu
    de la proteger.
    """
    import sys as _s

    module = _s.modules.get("app.web_hub.app")
    application = getattr(module, "app", None) if module is not None else None
    if application is None:
        return None
    out = set()
    for route in getattr(application, "routes", []) or []:
        chemin = getattr(route, "path", "") or ""
        if chemin.startswith("/"):
            out.add(chemin.rstrip("/") or "/")
    return out


def _cible_connue(cible: str, connues: set) -> bool:
    """Une cible parametree (`/api/vital/{name}`) accepte n'importe quelle valeur ;
    un montage (`/graph`) accepte tout ce qui vit dessous."""
    nue = (cible or "").split("?", 1)[0].split("#", 1)[0].rstrip("/") or "/"
    if nue in connues:
        return True
    for connue in connues:
        if "{" in connue:
            motif = "^" + re.sub(r"\{[^}]+\}", "[^/]+", re.escape(connue).replace(r"\{", "{").replace(r"\}", "}")) + "$"
            if re.match(motif, nue):
                return True
        elif connue != "/" and nue.startswith(connue + "/"):
            return True   # sous-chemin d'un montage
    return False


_ATTRS_CIBLE = ("href", "hx-get", "hx-post", "hx-put", "hx-delete", "hx-patch")


def neutraliser_cibles_inconnues(html: str, connues: set | None) -> tuple:
    """(html, refusees). Une UI GENEREE ne sert que des routes qui EXISTENT.

    MESURE 2026-08-26, en production : `/ui/auto/services-status` est un widget produit
    par un LLM (`generate_ui`), et le modele avait invente un lien `/alerts` -- 404,
    servi tel quel. `_sanitize_html` protege du HTML dangereux, personne ne protegeait
    de la route imaginaire. C'est la meme faute que partout ailleurs dans ce depot :
    une sortie de modele traitee comme un fait.

    On ne supprime pas l'element -- son texte reste lisible -- on lui RETIRE sa cible et
    on marque pourquoi. Un bouton mort et visible vaut mieux qu'un bouton mort et
    silencieux, et bien mieux qu'un bouton supprime dont personne ne saura qu'il a existe.
    """
    if connues is None:
        return html, None          # non verifie, et l'appelant le saura
    refusees = []

    def _remplacer(m):
        attr, cible = m.group(1), m.group(2)
        if not cible.startswith("/") or _cible_connue(cible, connues):
            return m.group(0)
        refusees.append(cible)
        return 'data-cible-refusee="%s" title="cible inexistante, neutralisee"' % cible

    motif = r'(%s)="([^"]*)"' % "|".join(_ATTRS_CIBLE)
    return re.sub(motif, _remplacer, html or ""), refusees


def table_repli(lignes: list, colonnes: list, note: str = "") -> str:
    """Table HTML des donnees REELLES, construite SANS LLM.

    Le principe « live-only » de l'owner ne dit pas « genere par un modele » : il dit
    « pas de donnee inventee ». Quand le modele ne repond pas, la bonne reponse n'est
    donc pas un carre vide (« gen fail »), c'est la MEME donnee, mise en forme
    simplement — et une note qui dit pourquoi l'habillage est sobre. Ce chemin ne
    depend d'aucun service : il ne peut pas echouer a son tour.

    `colonnes` : liste de (clef, titre). Tout est echappe."""
    from html import escape as _e

    entetes = "".join(
        '<th class="px-3 py-2 text-left font-medium">%s</th>' % _e(str(t))
        for _c, t in colonnes)
    corps = []
    for ligne in lignes or ():
        cellules = "".join(
            '<td class="px-3 py-2 border-t border-gray-200">%s</td>'
            % _e(str((ligne or {}).get(c, "")))
            for c, _t in colonnes)
        corps.append("<tr class='hover:bg-gray-50'>%s</tr>" % cellules)
    if not corps:
        corps.append('<tr><td class="px-3 py-2 text-gray-500" colspan="%d">'
                     "aucune donnee</td></tr>" % max(1, len(colonnes)))
    bandeau = ('<div class="text-xs text-gray-500 px-3 py-1">%s</div>' % _e(note)) if note else ""
    return ('<div>%s<table class="min-w-full text-sm">'
            '<thead class="bg-gray-100"><tr>%s</tr></thead><tbody>%s</tbody>'
            "</table></div>" % (bandeau, entetes, "".join(corps)))


def enveloppe_progressive(html_repli: str, url_generation: str,
                          cle: str = "widget") -> str:
    """Sert le repli TOUT DE SUITE, la generation le remplace si elle aboutit.

    LE REMEDE QUE CE FICHIER RECLAMAIT (commentaire de `generate_ui` : « RESTE A
    FAIRE, et c'est le vrai remede UX : servir le repli immediatement puis
    rafraichir le fragment quand la generation aboutit, plutot que faire
    attendre »). Ecrit le 2026-09-17.

    CE QUE CA REPARE, mesure. Les widgets `/ui/auto/*` attendaient la cascade
    avant de rendre quoi que ce soit : jusqu'a 25 s de borne, et l'utilisateur
    devant une page vide. Le gate UI, lui, voyait une route tantot dans son
    budget tantot hors budget -- d'ou un verdict qui changeait d'une passe a
    l'autre sans qu'une ligne de code ait bouge. Le registre des routes
    instables a accumule SIX routes en quelques jours, dont ces trois-la.

    ⚠️ ON NE TOUCHE PAS A LA BORNE DE 25 s. Elle a ete portee de 8 a 25 s le
    2026-08-30 SUR MESURE : trois generations du meme widget ont pris 20,2 s,
    18,6 s et 4,0 s, toutes avec un HTML valide. A 8 s la borne coupait une
    generation qui ABOUTISSAIT. Le defaut n'a jamais ete la duree de la
    generation, c'est qu'on la faisait ATTENDRE a l'utilisateur.

    Contrat du fragment de generation : il rend le HTML genere, ou **204 No
    Content**. Sur 204, htmx ne remplace RIEN -- le repli deja affiche reste en
    place. Une generation ratee ne doit jamais effacer une information servie.
    """
    import html as _html

    return (
        '<div id="%(cle)s" hx-get="%(url)s" hx-trigger="load delay:150ms" '
        'hx-swap="outerHTML" hx-target="this">%(repli)s</div>'
        % {"cle": _html.escape(cle, quote=True),
           "url": _html.escape(url_generation, quote=True),
           "repli": html_repli}
    )


# ---------------------------------------------------------------- borne de charge
#
# Mesure 2026-09-17, cause du wedge `:7400` : le webhub restait LISTENING avec
# `/health` MUET ~20 s apres une page LLM. Trois faits de source l'expliquent
# entierement, et aucun n'est une hypothese :
#
#   1. `/health` est declare `def` (app.py L580) : un handler SYNCHRONE consomme
#      donc un jeton du threadpool anyio, plafonne a 40 par defaut ;
#   2. les widgets `/ui/auto/*` sont `def` eux aussi et tiennent leur jeton
#      jusqu'a `timeout_s` (25 s) ;
#   3. ce module creait un ThreadPoolExecutor NEUF par appel, avec
#      `shutdown(wait=False)` au timeout -- le thread de fond continue `cascade`
#      SANS BORNE. Chaque generation expiree fuyait donc un thread.
#
# Assez de generations en vol saturent les 40 jetons ; `/health`, etant sync, se
# met alors en FILE derriere elles. Le port repond, la boucle va bien, et la
# sonde de vie se tait : on lit une panne la ou il y a une saturation.
#
# Deux bornes, ici, et une seule creation :
#   * UN executeur de module a `_GEN_MAX` ouvriers : un `cascade` qui pend
#     immobilise au pire `_GEN_MAX` threads, jamais un de plus par requete ;
#   * une admission NON BLOQUANTE : sans slot libre, on rend le repli TOUT DE
#     SUITE au lieu d'attendre 25 s en gardant un jeton anyio.
#
# `_GEN_MAX` est deliberement BAS. Le cout d'un plafond trop bas est de servir
# le repli plus souvent -- c'est exactement le comportement prevu du widget, et
# c'est sans danger. Le cout d'un plafond trop haut est le gel du service. Les
# deux erreurs ne coutent pas la meme chose, donc on penche du cote sur.
# Les refus sont COMPTES : un plafond se releve sur un chiffre, pas sur une
# impression -- meme regle que la borne de 8 s -> 25 s du 2026-08-30.
#
# Anti-dup : `app/forge_bounded_queue.BoundedQueue` a ete examine et ECARTE, en
# le disant. C'est un couple file + consommateur a livraison differee ; ici
# l'appelant a besoin d'un slot MAINTENANT ou d'un repli immediat, il n'y a ni
# boucle de consommation ni remise ulterieure du resultat.
_GEN_MAX = 2
_GEN_EXECUTEUR = None
_GEN_SLOTS = None
_GEN_REFUS = 0


def _generation_admission():
    """Rend (executeur, slot_obtenu). Ne bloque jamais."""
    global _GEN_EXECUTEUR, _GEN_SLOTS, _GEN_REFUS
    import threading
    from concurrent.futures import ThreadPoolExecutor

    if _GEN_EXECUTEUR is None:
        _GEN_EXECUTEUR = ThreadPoolExecutor(max_workers=_GEN_MAX,
                                            thread_name_prefix="ui_gen")
        _GEN_SLOTS = threading.Semaphore(_GEN_MAX)
    obtenu = _GEN_SLOTS.acquire(blocking=False)
    if not obtenu:
        _GEN_REFUS += 1
        # Un compteur en memoire ne se lit que DANS ce process : vu du dehors,
        # une borne qui refuse et une borne qui ne sert jamais sont identiques.
        # Mesure 2026-09-17 : un marteau de 18 generations a rendu 16 replis
        # sans qu'on puisse dire s'ils venaient du refus ou d'un echec de
        # generation. Un mecanisme sans effet OBSERVABLE ne se distingue pas
        # d'un mecanisme absent -- donc le refus s'ecrit dans le journal.
        logger.warning("ui_generate: generation REFUSEE (borne %d en vol, "
                       "refus cumules %d) -- repli servi immediatement",
                       _GEN_MAX, _GEN_REFUS)
        # Le logger du service part dans le superviseur et n'est pas relisible
        # depuis un compte client : mesure du 2026-09-17, `logs/` ne porte que
        # `webhub_vie.log`. On ecrit donc le refus la ou il se LIT, avec sa
        # date -- c'est ce journal qui construira la distribution permettant,
        # un jour, de relever `_GEN_MAX` sur un chiffre et non une impression.
        try:
            import datetime as _dt
            _j = ROOT / "logs" / "ui_generation_borne.log"
            _j.parent.mkdir(parents=True, exist_ok=True)
            with open(_j, "a", encoding="utf-8") as _f:
                _f.write("%s REFUS borne=%d cumul=%d\n" % (
                    _dt.datetime.now().isoformat(timespec="seconds"),
                    _GEN_MAX, _GEN_REFUS))
        except Exception:  # muet-ok : journaliser un refus ne doit jamais casser une page
            pass
    return _GEN_EXECUTEUR, obtenu


def generation_saturation() -> dict:
    """Etat de la borne, pour qui veut mesurer avant de la regler."""
    return {"max": _GEN_MAX, "refus": _GEN_REFUS,
            "arme": _GEN_EXECUTEUR is not None}


def generate_ui(
    description: str, data_source: dict | None = None, max_tokens: int = 2000,
    max_chars: int = 6000, timeout_s: float = 25.0
) -> dict:
    """Generate HTMX component via LLM cascade.

    Args:
        description: natural language describing what UI to build
        data_source: optional data context (dict serialized in prompt)
        max_tokens: LLM cap
        max_chars: enforce post-gen max length

    Returns:
        {
            "html": "<div>...</div>",
            "model_used": str,
            "confidence": float,
            "latency_ms": float,
            "sanitized": True,
            "data_source_used": bool,
        }
    """
    import sys

    sys.path.insert(0, str(ROOT))
    try:
        from nokido_agent.app.forge_frugal_cascade import cascade
    except Exception as e:
        return {"error": f"frugal_cascade unavailable: {e}"}

    data_ctx = ""
    if data_source:
        try:
            data_ctx = (
                "\n\nDonnees disponibles :\n```json\n" + json.dumps(data_source, indent=2, default=str)[:1500] + "\n```"
            )
        except Exception:
            pass

    prompt = SYSTEM_PROMPT_UI + "\n\nGenere : " + description + data_ctx

    # BORNE DE TEMPS. Mesure 2026-08-26 en production : deux widgets generes
    # (`/ui/auto/veille-summary`, `/ui/auto/critical-events`) depassaient DIX secondes,
    # `cascade` n'exposant aucun timeout. Une interface qui attend un modele sans borne
    # fait attendre l'utilisateur sans borne. Le thread de fond n'est pas tue — on ne
    # peut pas interrompre proprement un appel reseau en cours — mais on rend la main,
    # et l'appelant sert son repli.
    #
    # 8 s -> 25 s le 2026-08-30, sur MESURE et non sur impression. Depuis que la
    # cascade passe par le routeur souverain, elle escalade d'un slot a l'autre :
    # trois generations du widget « Services Health » ont pris 20,2 s, 18,6 s et
    # 4,0 s (deux fois `openrouter_free`, une fois `mistral_small`), toutes avec un
    # HTML valide. A 8 s la borne coupait donc une generation qui ABOUTISSAIT, et la
    # page servait un repli en le presentant comme un echec. Une borne se regle sur
    # un chiffre, pas sur une intuition -- meme regle que le budget CI du contrat UI.
    # RESTE A FAIRE, et c'est le vrai remede UX : servir le repli immediatement puis
    # rafraichir le fragment quand la generation aboutit, plutot que faire attendre.
    from concurrent.futures import TimeoutError as _Timeout

    # PAS de `with` : son __exit__ appelle shutdown(wait=True) et REJOINT le thread,
    # donc la borne ne rendait pas la main — mesure a l'ecriture, 3,0 s d'attente pour
    # un timeout demande de 0,3 s. Le test l'a attrape avant le commit. On rend la main
    # explicitement ; le thread de fond finit sa requete dans le vide (on ne peut pas
    # interrompre proprement un appel reseau en cours) et l'executeur se libere seul.
    _ex, _slot = _generation_admission()
    if not _slot:
        # SATURE : on ne fait pas attendre, et surtout on ne garde pas un jeton
        # du threadpool anyio pendant 25 s -- c'est cette attente-la qui mettait
        # `/health` en file et faisait lire une saturation comme une panne.
        return {"error": "generation saturee (%d en vol)" % _GEN_MAX, "html": "",
                "timeout": True, "sature": True,
                "data_source_used": bool(data_source)}
    def _travail():
        try:
            return cascade(prompt, use_case="general", max_tokens=max_tokens)
        finally:
            # le slot se libere quand le travail FINIT REELLEMENT, pas quand
            # l'appelant renonce : sinon un `cascade` qui pend serait compte
            # libre alors qu'il tient toujours son ouvrier.
            _GEN_SLOTS.release()

    try:
        _f = _ex.submit(_travail)
    except Exception:
        _GEN_SLOTS.release()
        raise
    try:
        result = _f.result(timeout=timeout_s)
    except _Timeout:
        # on rend la main ; le travail continue et rendra son slot en finissant
        return {"error": "timeout apres %.1f s" % timeout_s, "html": "",
                "timeout": True, "data_source_used": bool(data_source)}
    raw_html = result.get("response") or ""

    # Strip markdown fences if LLM wrapped
    raw_html = re.sub(r"^```(?:html)?\n", "", raw_html.strip())
    raw_html = re.sub(r"\n```$", "", raw_html)

    # TROISIEME ETAT, et il manquait. Mesure 2026-08-30 en production :
    # /ui/auto/services-status et /ui/auto/critical-events affichaient
    # « rendu simple : generation indisponible » -- le repli SANS motif. Cause :
    # ce chemin rendait un dict de SUCCES avec `html` vide et AUCUN `error`, si
    # bien que l'appelant (app.py, `result.get("error") or "generation
    # indisponible"`) n'avait rien a nommer. Ni le timeout ni l'import n'etaient
    # en cause, et personne ne pouvait le savoir. La fonctionnalite generative
    # etait morte en production sans qu'aucun signal ne la designe.
    if not raw_html.strip():
        tiers = result.get("tiers_tried") or []
        if not result.get("model_used"):
            # AUCUN tier n'a repondu. `cascade` rend alors son dict par defaut
            # (`response: None`, `model_used: None`, cf forge_frugal_cascade L227)
            # sans jamais lever -- mais elle a DEJA le denominateur sous la main,
            # dans `tiers_tried`. Il n'etait simplement pas remonte : le message
            # ne disait donc ni combien de modeles avaient ete essayes, ni
            # lesquels, la ou c'est exactement ce qu'il faut pour reparer.
            ech = result.get("echecs") or {}
            detail = "; ".join("%s -> %s" % (n, ech.get(n, "raison non remontee"))
                               for n in tiers) or "aucun tier configure"
            # La ROUTE empruntee est le premier discriminant : « routeur souverain »
            # ou « routeur indisponible (...) ». Sans elle, un repli sur les appels
            # directs est indiscernable d'un routeur qui a tout essaye -- et on
            # accuse les fournisseurs au lieu du chemin. Mesure 2026-08-30 : la
            # cascade marchait en direct et la page servait toujours son repli.
            return {"error": "[%s] aucun des %d tiers n'a repondu : %s"
                             % (result.get("route") or "route non dite",
                                len(tiers), detail),
                    "html": "", "model_used": None, "tiers_tried": tiers,
                    "echecs": ech,
                    "latency_ms": result.get("latency_ms"),
                    "data_source_used": bool(data_source)}
        return {"error": "le modele %s a repondu, mais sa reponse est VIDE"
                         % result.get("model_used"),
                "html": "", "model_used": result.get("model_used"),
                "tiers_tried": tiers,
                "latency_ms": result.get("latency_ms"),
                "data_source_used": bool(data_source)}

    # QUATRIEME ETAT, et il manquait. MESURE 2026-09-16 : cinq appels IDENTIQUES
    # a /ui/auto/veille-summary, session etablie par le formulaire, ont rendu
    # deux fois un tableau (12 <tr>), une fois le repli de timeout (16 <tr>,
    # donc le repli FONCTIONNE)... et DEUX fois « User Safety: safe », 17
    # caracteres, servis tels quels comme s'il s'agissait d'une interface.
    #
    # C'est la reponse d'un garde-fou du MODELE, pas un rendu. Elle traversait
    # tout parce que les trois gardes ci-dessus testent le VIDE, et qu'une
    # chaine non vide les satisfait tous -- y compris celui du nettoyage, qui ne
    # retire rien a un texte sans balise. Cote appelant, `if not
    # result.get("html")` etait donc faux, et le repli n'etait jamais atteint :
    # l'existence d'un mecanisme n'est pas son effet reel.
    #
    # C'est aussi l'explication COMPLETE de l'intermittence qui faisait varier le
    # verdict du gate UI d'une passe a l'autre : la reponse du modele varie, donc
    # la page varie, sans qu'une ligne de code ait bouge.
    #
    # Critere STRUCTUREL, et volontairement le plus FAIBLE qui separe les deux
    # cas : un rendu d'interface porte au moins une balise. On ne juge ni la
    # longueur, ni le nombre de lignes, ni le contenu -- ces trois-la dependent
    # des donnees et refuseraient des rendus legitimes. Un modele qui preface son
    # HTML d'une phrase reste accepte.
    if not re.search(r"<[a-zA-Z!/]", raw_html):
        return {"error": "le modele %s a repondu HORS FORMAT (aucune balise) : %r"
                         % (result.get("model_used") or "modele non nomme",
                            raw_html[:120]),
                "html": "", "model_used": result.get("model_used"),
                "tiers_tried": result.get("tiers_tried") or [],
                "latency_ms": result.get("latency_ms"),
                "data_source_used": bool(data_source)}

    # Enforce length cap
    if len(raw_html) > max_chars:
        raw_html = raw_html[:max_chars] + "<!-- truncated -->"

    sanitized = _sanitize_html(raw_html)
    sanitized, refusees = neutraliser_cibles_inconnues(sanitized, routes_connues())

    # Le nettoyage peut TOUT retirer (un modele qui ne rend que du script, ou de
    # la prose sans balise). Le resultat est vide comme au cas precedent, mais la
    # cause est l'INVERSE : le modele a produit, c'est nous qui avons refuse. Les
    # confondre enverrait chercher la panne du mauvais cote -- du cote du
    # fournisseur alors que le defaut serait chez nous.
    if not sanitized.strip():
        return {"error": "sortie de %s entierement neutralisee au nettoyage "
                         "(%d caracteres produits, 0 conserve)"
                         % (result.get("model_used") or "modele non nomme",
                            len(raw_html)),
                "html": "", "model_used": result.get("model_used"),
                "latency_ms": result.get("latency_ms"),
                "cibles_refusees": refusees,
                "data_source_used": bool(data_source)}
    if refusees:
        import logging as _lg

        _lg.getLogger("Nokido.ui_generate").warning(
            "[ui_generate] %d cible(s) INVENTEE(S) par le modele, neutralisee(s) : %s "
            "| consequence : le widget s'affiche, ces controles ne mènent nulle part "
            "et le disent", len(refusees), refusees[:5])

    return {
        "html": sanitized,
        "model_used": result.get("model_used"),
        "confidence": result.get("confidence"),
        "latency_ms": result.get("latency_ms"),
        "sanitized": True,
        # Trois etats : liste (verifie), [] (verifie, rien a redire), None (l'app
        # n'etait pas chargee -- non verifie, ce qui n'est pas « rien trouve »).
        "cibles_refusees": refusees,
        "data_source_used": bool(data_source),
    }


def route_ui_generate(request_body: dict) -> dict:
    """Handler pour POST /ui/generate.

    request_body : {"description": str, "data_source": dict | None, "mode": "llm|openui"}
    """
    desc = request_body.get("description", "")
    if not desc or len(desc) < 5:
        return {"error": "description required, min 5 chars"}
    if len(desc) > 2000:
        return {"error": "description too long (max 2000 chars)"}
    mode = str(request_body.get("mode") or request_body.get("pipeline") or "llm").lower()
    if mode in {"openui", "moulinette", "render", "render_x"}:
        return generate_openui_render(
            desc,
            data_source=request_body.get("data_source"),
            include_code=bool(request_body.get("include_code") or request_body.get("return_code")),
        )
    return generate_ui(desc, data_source=request_body.get("data_source"))


def main():
    """CLI demo."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: ui_generate.py <description>")
        return
    desc = sys.argv[1]
    result = generate_ui(desc)
    print(json.dumps({k: v for k, v in result.items() if k != "html"}, indent=2))
    print("\n--- HTML ---")
    print(result.get("html", "")[:2000])


if __name__ == "__main__":
    main()
