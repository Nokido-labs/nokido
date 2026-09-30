"""web_hub/htmx_helpers.py — HTMX + Alpine.js helpers Generative UI Phase A.

Roadmap Generative UI Phase A : remplace vanilla JS inline par HTMX
(hypermedia) + Alpine.js (reactivity). UI partials rendus server-side
+ swap via hx-target/hx-swap.

Pattern :
- htmx_layout(title, body) : page complete avec includes HTMX 2.0 + Alpine 3
- htmx_partial(html) : retour fragment pour swap (sans <html><head>)
- htmx_alert(message, kind) : toast notification
- htmx_modal(title, body) : modal pre-style

Endpoints utilisateur : declare juste @route('/foo') -> htmx_partial(...)
+ HTMX fetch hx-get='/foo' hx-target='#zone' hx-swap='innerHTML'

CSP : strict avec nonce. Inline JS interdit (hors event handlers htmx/alpine
qui sont declarative attributes).
"""

from __future__ import annotations
import secrets


HTMX_VERSION = "2.0.4"
ALPINE_VERSION = "3.14.8"
TAILWIND_CDN = "https://cdn.tailwindcss.com"  # dev only

# ALPINE N'EST PLUS CHARGE PAR CE LAYOUT (2026-08-29) — la balise est neutralisee
# (type text/plain, plus de src), pas supprimee, pour que la raison reste sous les
# yeux du prochain lecteur.
#
# Mesure : la CSP du hub interdit `eval` (script-src sans 'unsafe-eval') et Alpine 3
# compile ses expressions avec `new Function`. Il mourait donc a l'init sur les deux
# seules pages qui passent par ici — /ui/playground et /dashboard/diag — en crachant
# 17 erreurs console POUR RIEN : ni l'une ni l'autre n'a la moindre directive Alpine
# (elles sont en htmx : hx-get / hx-trigger / hx-swap), aucun des 47 formulaires de
# forms/ n'a de x-data, et le seul vrai consommateur du depot — render_hub_shell —
# n'est plus servi depuis que /hub redirige vers la maquette React. Une bibliotheque
# que personne n'utilise ne coute pas 45 ko : elle fabrique des erreurs qu'on prend
# ensuite pour des pannes.
#
# POUR LA REBRANCHER : `toast()` et `modal()` en dependent (x-data, x-show, @click,
# setTimeout inline). Cela demande un choix EXPLICITE, jamais de rendre juste le src :
#   * build CSP d'Alpine (@alpinejs/csp) — sans eval, mais les expressions inline
#     doivent devenir des Alpine.data() ; ou
#   * 'unsafe-eval' dans script-src — une ligne, et un affaiblissement de la CSP qui
#     se defend devant quelqu'un, pas en passant.


def nonce() -> str:
    """Per-request CSP nonce."""
    return secrets.token_urlsafe(16)


def htmx_head(title: str, csp_nonce: str | None = None) -> str:
    n = csp_nonce or nonce()
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="csp-nonce" content="{n}">
<script src="/static/htmx.min.js" defer></script>
<script data-retire-le="2026-08-29" data-motif="csp-eval" type="text/plain"
        data-src="/static/alpine.min.js"></script>
<script src="/static/tailwind.min.js"></script>
<link rel="stylesheet" href="/static/nokido.css">
<style>
[x-cloak] {{ display: none !important; }}
.htmx-indicator {{ display: none; }}
.htmx-request .htmx-indicator {{ display: inline-block; }}
.htmx-request.htmx-indicator {{ display: inline-block; }}
.spinner {{ display: inline-block; width: 1em; height: 1em; border: 2px solid #999;
  border-top-color: transparent; border-radius: 50%; animation: spin 0.6s linear infinite; }}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
</style>
</head>
"""


def htmx_layout(title: str, body: str, csp_nonce: str | None = None) -> str:
    """Page complete HTMX + Alpine + Tailwind. Body = HTML string."""
    n = csp_nonce or nonce()
    return f"""{htmx_head(title, n)}
<body class="bg-gray-100 text-gray-900 font-sans" hx-headers='{{"X-CSRF-Nonce":"{n}"}}'>
<div id="toast-container" class="fixed top-4 right-4 z-50 space-y-2"
     x-data="{{ toasts: [] }}" x-init="$watch('toasts', v=>{{}})"></div>
{body}
</body>
</html>"""


def htmx_partial(html: str) -> str:
    """Fragment HTML (sans head/body) pour swap HTMX hx-target."""
    return html


def htmx_alert(message: str, kind: str = "info") -> str:
    """Toast notification. kind : info | success | warning | error."""
    color_map = {
        "info": "bg-blue-100 text-blue-800 border-blue-300",
        "success": "bg-green-100 text-green-800 border-green-300",
        "warning": "bg-yellow-100 text-yellow-800 border-yellow-300",
        "error": "bg-red-100 text-red-800 border-red-300",
    }
    cls = color_map.get(kind, color_map["info"])
    safe_msg = (message or "").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<div class="px-4 py-2 border-l-4 rounded shadow {cls}"
                   x-data="{{ show: true }}" x-show="show" x-cloak
                   x-init="setTimeout(()=>show=false, 5000)">
{safe_msg}
</div>"""


def htmx_modal(title: str, body: str, modal_id: str = "modal") -> str:
    """Modal Alpine. Trigger via x-show.

    Usage : htmx_partial(htmx_modal('Title', 'Body html'))
    """
    safe_title = (title or "").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<div id="{modal_id}" class="fixed inset-0 z-40 flex items-center justify-center bg-black/50"
                    x-data="{{ open: true }}" x-show="open" x-cloak
                    @keydown.escape.window="open=false">
  <div class="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 p-6"
       @click.outside="open=false">
    <div class="flex justify-between items-center mb-4">
      <h2 class="text-lg font-semibold">{safe_title}</h2>
      <button class="text-gray-400 hover:text-gray-600" @click="open=false">×</button>
    </div>
    <div class="text-sm">{body}</div>
  </div>
</div>"""


def htmx_button(
    label: str,
    hx_get: str | None = None,
    hx_post: str | None = None,
    target: str = "#main",
    swap: str = "innerHTML",
    cls: str = "px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700",
    testid: str = "",
) -> str:
    """Button HTMX with hx-get or hx-post."""
    if hx_get:
        action = f'hx-get="{hx_get}"'
    elif hx_post:
        action = f'hx-post="{hx_post}"'
    else:
        action = ""
    tid = f' data-testid="{testid}"' if testid else ""
    return f"""<button {action}{tid} hx-target="{target}" hx-swap="{swap}"
                       class="{cls}">
  {label}
  <span class="htmx-indicator spinner ml-1"></span>
</button>"""


def htmx_table(headers: list[str], rows: list[list[str]], cls: str = "") -> str:
    """Simple table generator. Each cell HTML-escaped."""

    def esc(s):
        return (str(s) if s is not None else "").replace("<", "&lt;").replace(">", "&gt;")

    head_html = "".join(f"<th class='px-3 py-2 text-left font-semibold border-b'>{esc(h)}</th>" for h in headers)
    rows_html = ""
    for row in rows:
        cells = "".join(f"<td class='px-3 py-2 border-b'>{esc(c)}</td>" for c in row)
        rows_html += f"<tr class='hover:bg-gray-50'>{cells}</tr>"
    return f"""<table class="min-w-full bg-white border {cls}">
<thead class="bg-gray-100"><tr>{head_html}</tr></thead>
<tbody>{rows_html}</tbody>
</table>"""


def htmx_form(
    fields: list[dict], action_url: str, submit_label: str = "Submit", method: str = "post", target: str = "#result"
) -> str:
    """Generate form. fields = [{name, label, type, value, required}, ...]"""
    field_html = ""
    for f in fields:
        name = f.get("name", "")
        label = f.get("label", name)
        ftype = f.get("type", "text")
        value = f.get("value", "")
        required = "required" if f.get("required") else ""
        field_html += f"""<div class="mb-3">
<label class="block text-sm font-medium mb-1">{label}</label>
<input type="{ftype}" name="{name}" value="{value}" {required} data-testid="field-{name}"
       class="w-full px-3 py-2 border rounded focus:ring-2 focus:ring-blue-500">
</div>"""
    hx_attr = f'hx-{method}="{action_url}"'
    return f"""<form {hx_attr} hx-target="{target}" hx-swap="innerHTML"
                     class="space-y-3 p-4 bg-white rounded shadow">
{field_html}
<button type="submit" data-testid="form-submit" class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700">
  {submit_label}
  <span class="htmx-indicator spinner ml-1"></span>
</button>
</form>"""
