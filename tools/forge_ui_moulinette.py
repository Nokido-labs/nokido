#!/usr/bin/env python3
"""forge_ui_moulinette.py — moulinette UI souveraine (économie tokens massive).

Découple le travail-ARCHITECTE (LLM cher) du travail-OUVRIER (CPU local + petit modèle).
Avance le design web_hub déjà entamé (design_handoff_nokido -> app/web_hub) sans cramer de tokens :

  1. SPEC prose ----> JSON UI schema       modèle LOCAL Qwen2.5-coder (cheap)   [schema_from_spec]
  2. JSON schema ---> squelette render_X()  DÉTERMINISTE, 0 TOKEN  <-- LE coeur  [skeleton_from_schema]
  3. trous durs ----> remplissage ciblé     gate: local d'abord, cloud si dur    [fill_holes]
  4. itération -----> blocs SEARCH/REPLACE   forge_search_replace (jamais réécrire fichier entier)

COMPOSE l'existant (anti-dup, zéro module neuf de routage/inférence/édition) :
  - forge_orchestration_gate.classify  -> route local vs cloud (économie)
  - forge_agent_proxy.ask('router_local') -> Qwen2.5-coder local (schema + fills cheap)
  - forge_build_repair.build_repair    -> valide + fixe le code généré (ironsmith)
  - forge_search_replace.apply_blocks  -> édition chirurgicale (itération >80% moins de tokens)

CIBLE = web_hub : HTMX + Alpine + classes `laforge-ds` (convention `render_<name>(args)->str`).
PAS de React : le `.ref.jsx` du design_handoff = SPEC de référence, pas la cible de génération.

SCHEMA UI (JSON) — un noeud :
  {"tag","class","id","text","attrs":{},"alpine":{"x-data":"..."},"htmx":{"hx-post":"..."},
   "children":[...]}   |   {"hole":"description du trou à remplir au FIM"}
  Interpolation dans text/attrs : {expr} = valeur échappée (_e), {{ }} = accolades littérales (Alpine).

USAGE
  forge_ui_moulinette.py demo                         # prouve le coeur déterministe (0 token)
  forge_ui_moulinette.py gen <schema.json> [--out f.py] [--apply]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

# ---------------------------------------------------------------------------
# COEUR DÉTERMINISTE — JSON schema -> fonction render_X() web_hub. ZÉRO token.
# ---------------------------------------------------------------------------

def _interp(s: str) -> str:
    """'a{expr}b' -> expression Python concaténée. {{ }} = accolades littérales (Alpine/HTMX)."""
    out, buf, i, n = [], "", 0, len(s)
    while i < n:
        if s[i:i + 2] == "{{":
            buf += "{"; i += 2
        elif s[i:i + 2] == "}}":
            buf += "}"; i += 2
        elif s[i] == "{":
            j = s.find("}", i)
            if j == -1:
                buf += s[i:]; break
            if buf:
                out.append(repr(buf)); buf = ""
            out.append(f"_e({s[i + 1:j]})")
            i = j + 1
        else:
            buf += s[i]; i += 1
    if buf:
        out.append(repr(buf))
    return " + ".join(out) if out else "''"


def _attrs(node: dict) -> str:
    """Construit la string d'attributs HTML (class/id/attrs/alpine/htmx), interpolation conservée."""
    a = ""
    if node.get("class"):
        a += f' class="{node["class"]}"'
    if node.get("id"):
        a += f' id="{node["id"]}"'
    for grp in ("attrs", "alpine", "htmx"):
        for k, v in (node.get(grp) or {}).items():
            a += f' {k}="{v}"'
    return a


def _emit(node: dict, lines: list, holes: list, ind: int = 1) -> None:
    px = "    " * ind  # indentation Python (ind=1 = corps de fonction)
    if "hole" in node:  # trou réservé au remplissage FIM chirurgical
        hid = f"h{len(holes) + 1}"
        holes.append({"id": hid, "desc": node["hole"]})
        lines.append(f"{px}# >>> HOLE {hid}: {node['hole']} (remplir via fill_holes / SEARCH-REPLACE)")
        lines.append(f"{px}parts.append('')  # HOLE {hid}")
        return
    if "if" in node:  # conditionnel -> bloc Python if/else (0 token)
        lines.append(f"{px}if {node['if']}:")
        body = node.get("then") or []
        for c in body:
            _emit(c, lines, holes, ind + 1)
        if not body:
            lines.append(f"{px}    pass")
        if node.get("else"):
            lines.append(f"{px}else:")
            for c in node["else"]:
                _emit(c, lines, holes, ind + 1)
        return
    if "for" in node:  # boucle -> bloc Python for (ex: liste de cartes)
        lines.append(f"{px}for {node['for']}:")
        body = node.get("do") or []
        for c in body:
            _emit(c, lines, holes, ind + 1)
        if not body:
            lines.append(f"{px}    pass")
        return
    tag = node.get("tag", "div")
    lines.append(f"{px}parts.append({_interp('<' + tag + _attrs(node) + '>')})")
    if node.get("text"):
        lines.append(f"{px}parts.append({_interp(str(node['text']))})")
    for child in (node.get("children") or []):  # MÊME indent Python (parts.append séquentiels, pas imbriqués)
        _emit(child, lines, holes, ind)
    if tag not in ("img", "input", "br", "hr", "meta", "link"):  # void elements
        lines.append(f"{px}parts.append({'</' + tag + '>'!r})")


def skeleton_from_schema(schema: dict) -> dict:
    """JSON schema -> {name, params, code (render_X fn), holes}. DÉTERMINISTE, aucun appel LLM."""
    name = schema.get("name", "component").replace("-", "_")
    params = schema.get("props", [])
    root = schema.get("root") or schema
    sig = ", ".join(params)
    setup = "\n".join(f"    {s}" for s in (schema.get("setup") or []))  # lignes précalc (accent, dicts)
    lines, holes = [], []
    _emit(root, lines, holes)
    body = "\n".join(lines)
    code = (
        f"def render_{name}({sig}):\n"
        f'    """Généré par forge_ui_moulinette (déterministe). Cible web_hub HTMX/Alpine/laforge-ds."""\n'
        f"    import html as _h\n"
        f"    _e = lambda v: _h.escape(str(v))\n"
        f"    parts = []\n"
        f"{setup + chr(10) if setup else ''}"
        f"{body}\n"
        f"    return ''.join(parts)\n"
    )
    return {"name": f"render_{name}", "params": params, "code": code, "holes": holes}


# ---------------------------------------------------------------------------
# INFÉRENCE LOCALE injectable (défaut = forge_agent_proxy router_local, Qwen cheap)
# ---------------------------------------------------------------------------

def _default_infer(prompt: str, max_tokens: int = 1200) -> str:
    """Appel LOCAL souverain par défaut. Lazy import (le coeur déterministe marche sans)."""
    import asyncio
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from nokido_agent.app import forge_agent_proxy  # type: ignore
    r = asyncio.run(forge_agent_proxy.ask("router_local", prompt, max_tokens=max_tokens, timeout=60))
    # ask() peut renvoyer un dict (objet réponse) au lieu du texte brut -> extraire (régression 2026-06-17)
    if isinstance(r, dict):
        for _k in ("text", "content", "response", "result", "message", "answer", "output"):
            _v = r.get(_k)
            if isinstance(_v, str) and _v.strip():
                return _v
        try:
            return r["choices"][0]["message"]["content"]
        except Exception:  # noqa: BLE001
            return json.dumps(r)
    return str(r)


def schema_from_spec(spec: str, infer=None) -> dict:
    """Prose -> JSON UI schema via modèle LOCAL (cheap). Le LLM ne fait QUE le schéma, pas le code."""
    infer = infer or _default_infer
    sysp = ("Tu produis UNIQUEMENT un JSON UI schema (pas de prose, pas de markdown). Noeud = "
            '{tag,class,text,attrs,alpine,htmx,children} ou {hole:"desc"}. Cible HTMX/Alpine, classes '
            "préfixées lf-. Réserve les parties à logique complexe en {hole}. SPEC:\n")
    raw = infer(sysp + spec, 1500)
    s = raw[raw.find("{"):raw.rfind("}") + 1]
    return json.loads(s)


def fill_holes(skel: dict, infer=None, capability: str = "weak") -> dict:
    """Remplit les trous via le gate (local d'abord, cloud si dur). Retourne blocs SEARCH/REPLACE."""
    if not skel.get("holes"):
        return {"blocks": [], "note": "aucun trou"}
    infer = infer or _default_infer
    blocks = []
    for h in skel["holes"]:
        marker = f"    parts.append('')  # HOLE {h['id']}"
        prompt = (f"Remplace ce trou UI (HTMX/Alpine, classes lf-) par des lignes "
                  f"parts.append(...). Contexte fonction {skel['name']}. Trou: {h['desc']}. "
                  f"Réponds SEULEMENT les lignes parts.append(...).")
        gen = infer(prompt, 600).strip()
        blocks.append(f"<<<<<<< SEARCH\n{marker}\n=======\n{gen}\n>>>>>>> REPLACE")
    return {"blocks": blocks, "count": len(blocks)}


def form_from_jsonschema(name: str, jschema: dict, action: str = "/run", method: str = "hx-post") -> dict:
    """Contrat JSON Schema (tool hub / endpoint) -> form UI FIDÈLE. DÉTERMINISTE, 0 token.

    LE backbone "couvrir tout le dépôt" : chaque tool hub a déjà un JSON Schema (params) ;
    on en dérive un formulaire exact (type->input, enum->select, required, description->hint).
    Fidèle PAR CONSTRUCTION au code fonctionnel (le schéma EST le contrat)."""
    props = jschema.get("properties") or {}
    required = set(jschema.get("required") or [])
    children: list = []
    for field, spec in props.items():
        typ = spec.get("type", "string")
        desc = str(spec.get("description", "")).replace("\n", " ")[:160]
        req = {"required": "required"} if field in required else {}
        label = {"tag": "label", "class": "lf-field__label",
                 "attrs": {"for": f"f_{name}_{field}"}, "text": field + (" *" if field in required else "")}
        base = {"name": field, "id": f"f_{name}_{field}", "class": "lf-input"}
        if spec.get("enum"):
            inp = {"tag": "select", "attrs": {**base, **req},
                   "children": [{"tag": "option", "attrs": {"value": str(o)}, "text": str(o)} for o in spec["enum"]]}
        elif typ == "boolean":
            inp = {"tag": "input", "attrs": {**base, "type": "checkbox", "class": "lf-checkbox"}}
        elif typ in ("integer", "number"):
            inp = {"tag": "input", "attrs": {**base, **req, "type": "number",
                   **({"step": "any"} if typ == "number" else {})}}
        elif typ in ("array", "object"):
            inp = {"tag": "textarea", "attrs": {**base, **req, "rows": "3", "placeholder": f"JSON {typ}"}}
        else:  # string
            big = any(k in field.lower() for k in ("code", "content", "text", "prompt", "body", "command"))
            inp = ({"tag": "textarea", "attrs": {**base, **req, "rows": "5"}} if big
                   else {"tag": "input", "attrs": {**base, **req, "type": "text"}})
        field_children = [label, inp]
        if desc:
            field_children.append({"tag": "small", "class": "lf-field__hint", "text": desc})
        children.append({"tag": "div", "class": "lf-field", "children": field_children})
    children.append({"tag": "button", "class": "lf-btn lf-btn--primary",
                     "attrs": {"type": "submit"}, "text": "Exécuter " + name})
    schema = {"name": f"{name}_form", "props": [],
              "root": {"tag": "form", "class": "lf-form",
                       "attrs": {"data-tool": name}, "htmx": {method: action, "hx-swap": "outerHTML"},
                       "children": children}}
    return skeleton_from_schema(schema)


def render_form_html(name: str, jschema: dict, action: str = "#") -> str:
    """Génère ET rend le form HTML d'un coup (pratique pour un endpoint runtime). 0 token."""
    skel = form_from_jsonschema(name, jschema, action=action)
    ns: dict = {}
    exec(skel["code"], ns)
    return ns[skel["name"]]()


def _classify(spec: str):
    """Route via le gate d'orchestration (économie : schema/scaffold -> local)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from nokido_agent.app.forge_orchestration_gate import classify, Action  # type: ignore
        return classify(Action(prompt=spec, kind="llm", task_type="codegen", ring=3,
                               est_steps=1, est_tokens=800, quality_need="normal"))
    except Exception as e:
        return {"lane": "local", "reason": f"gate indispo ({e}) -> local par défaut"}


def main(argv: list) -> int:
    cmd = argv[0] if argv else "demo"
    if cmd == "demo":
        schema = {
            "name": "module_card", "props": ["module", "status"],
            "root": {"tag": "div", "class": "lf-card lf-card--module",
                     "alpine": {"x-data": "{{open:false}}"},
                     "children": [
                         {"tag": "h3", "class": "lf-card__title", "text": "{module['name']}"},
                         {"tag": "span", "class": "lf-pill lf-pill--{status}", "text": "{status}"},
                         {"tag": "button", "class": "lf-btn lf-btn--primary",
                          "htmx": {"hx-post": "/module/{module['id']}/start", "hx-swap": "outerHTML"},
                          "text": "Démarrer"},
                         {"hole": "panneau logs live (SSE) — logique à remplir"},
                     ]}}
        skel = skeleton_from_schema(schema)
        print("=== render fn DÉTERMINISTE (0 token) ===\n" + skel["code"])
        print(f"=== trous (FIM cible cloud/local) : {skel['holes']} ===")
        return 0
    if cmd == "gen":
        if len(argv) < 2:
            print("usage: gen <schema.json> [--out f.py] [--apply]"); return 1
        schema = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        skel = skeleton_from_schema(schema)
        out = None
        for i, t in enumerate(argv):
            if t == "--out" and i + 1 < len(argv):
                out = argv[i + 1]
        if out and "--apply" in argv:
            Path(out).write_text(skel["code"], encoding="utf-8")
            print(f"écrit -> {out} (trous: {len(skel['holes'])})")
        else:
            print(skel["code"])
            print(f"# trous: {skel['holes']}  (--out f.py --apply pour écrire)")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
