"""
app/web_hub/csp.py - Centralisation de la Content-Security-Policy.

Avant : f-string concatenee en dur dans app.py. Chaque nouveau CDN
impliquait de toucher le fichier principal avec risque de regression.
(Trou Gemini #3 dans la review du 2026-04-18.)

Maintenant :
  - Une source de verite : les constantes CDN_* par directive.
  - Une fonction pure : build_csp(module_ports, extra_cdns) -> str.
  - Deterministe : l'ordre des directives et tokens est stable
    (important pour snapshot-testing).
  - Extensible : ajouter un CDN = ajouter une string dans CDN_*.

PHILOSOPHIE :
  - Les modules internes (recon/graph/tui) tournent sur 127.0.0.1:74xx.
    On les autorise a la fois en http:// et ws:// pour script/style/
    img/connect. localhost est ajoute en alias parce que certains
    clients (navigateur Windows) le prefixent.
  - Les CDN externes sont limites a https:// et a des hotes precis.
  - 'unsafe-inline' reste necessaire pour le dashboard HTML inline
    (Tailwind CDN injecte du CSS inline, Cytoscape initialise en
    <script inline).
  - frame-ancestors 'none' et base-uri 'self' ferment clickjacking /
    base tag injection.

API :
  build_csp()                        -> string avec defaults
  build_csp(module_ports=[7410,...]) -> string personnalise
  build_csp(extra_cdns={'script':['https://other.example']})
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

# --- CDN externes autorises (directive-par-directive) ----------------
CDN_SCRIPT: tuple[str, ...] = (
    # Tailwind + unpkg (HTMX, Lucide) vendores en /static/ -> retires (offline souverain).
    "https://cdnjs.cloudflare.com",
    "https://cdn.jsdelivr.net",  # Vega/Vega-Lite (page epistemic) — pas encore vendore
)
CDN_STYLE: tuple[str, ...] = ()  # webfonts vendorees en /static/fonts (forge_font_vendor.py)
CDN_FONT: tuple[str, ...] = ()  # idem : 0 egress fonts, tout est same-origin ('self')

# --- Modules backend locaux (ports par defaut) ----------------------
DEFAULT_MODULE_PORTS: tuple[int, ...] = (7410, 7420, 7440)  # recon, graph, tui

# Hotes locaux : on double 127.0.0.1 + localhost pour eviter que
# certains navigateurs canonicalisent l'un ou l'autre.
_LOCAL_HOSTS: tuple[str, ...] = ("127.0.0.1", "localhost")

# --- Directives statiques -------------------------------------------
_FRAME_ANCESTORS = "'none'"
_BASE_URI = "'self'"
_DEFAULT_SRC = "'self'"


def _local_module_origins(ports: Iterable[int], scheme: str) -> list[str]:
    """Genere [scheme://host:port] pour chaque (host, port), ordre deterministe.

    Ordre : pour chaque host dans _LOCAL_HOSTS, on emet tous les
    ports (127.0.0.1:7410, :7420, :7440, puis localhost:7410, ...).
    Matche la forme historique de app.py (retrocompat stricte pour
    snapshot/regex tests).
    """
    out: list[str] = []
    for host in _LOCAL_HOSTS:
        for port in ports:
            out.append(f"{scheme}://{host}:{port}")
    return out


def _directive(name: str, *token_groups: Sequence[str]) -> str:
    """Construit 'name t1 t2 t3'. Filtre les tokens vides."""
    tokens: list[str] = []
    for group in token_groups:
        for t in group:
            if t:
                tokens.append(t)
    if not tokens:
        return name
    return f"{name} " + " ".join(tokens)


def build_csp(
    module_ports: Sequence[int] = DEFAULT_MODULE_PORTS,
    extra_cdns: Mapping[str, Sequence[str]] | None = None,
) -> str:
    """Construit la Content-Security-Policy complete.

    Args:
        module_ports: Ports locaux des modules backend a autoriser.
            Defaut : (7410, 7420, 7440) = recon/graph/tui.
        extra_cdns: dict optionnel {directive_name: [cdn, ...]} pour
            etendre SANS modifier les constantes. Clefs valides :
            'script', 'style', 'font', 'img', 'connect'.

    Returns:
        Header value pretee a etre posee telle quelle dans
        response.headers['Content-Security-Policy'].
    """
    extra_cdns = extra_cdns or {}

    http_modules = _local_module_origins(module_ports, "http")
    ws_modules = _local_module_origins(module_ports, "ws")

    directives = [
        _directive("default-src", [_DEFAULT_SRC]),
        _directive(
            "script-src",
            ["'self'", "'unsafe-inline'"],
            CDN_SCRIPT,
            extra_cdns.get("script", ()),
            http_modules,
        ),
        _directive(
            "style-src",
            ["'self'", "'unsafe-inline'"],
            CDN_STYLE,
            extra_cdns.get("style", ()),
            http_modules,
        ),
        _directive(
            "font-src",
            ["'self'"],
            CDN_FONT,
            extra_cdns.get("font", ()),
            ["data:"],
        ),
        _directive(
            "img-src",
            ["'self'", "data:"],
            extra_cdns.get("img", ()),
            http_modules,
        ),
        _directive(
            "connect-src",
            ["'self'"],
            extra_cdns.get("connect", ()),
            http_modules,
            ws_modules,
        ),
        _directive("frame-ancestors", [_FRAME_ANCESTORS]),
        _directive("base-uri", [_BASE_URI]),
    ]
    # Joint par "; " puis termine par ";" pour matcher la forme historique.
    return "; ".join(directives) + ";"


__all__ = [
    "CDN_SCRIPT",
    "CDN_STYLE",
    "CDN_FONT",
    "DEFAULT_MODULE_PORTS",
    "build_csp",
]
