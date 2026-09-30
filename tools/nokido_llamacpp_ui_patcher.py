"""tools/nokido_llamacpp_ui_patcher.py — patch UI llama.cpp → français + branding Nokido.

Récupère le bundle HTML actuel servi par llama-server :8091, applique des replaces
EN→FR + rebranding "La Forge", et stocke dans data/llamacpp_webui_fr/index.html.

Le BAT principal monte ce dossier via `--path` (option llama-server :
priorité sur le bundle interne).

Limites :
- Les strings dans le bundle JS sont parfois en concaténations dynamiques.
  Certains textes resteront EN. À itérer.
- Tout patch s'applique post-build : si llama.cpp upgrade, re-run ce script.

Usage :
    LAFORGE_PYTHON tools/nokido_llamacpp_ui_patcher.py [--port 8091] [--out data/llamacpp_webui_fr]

Ensuite ajouter au BAT :
    --path __import__("os").path.expanduser("~\\Script python IA\\LaForge\\data\\llamacpp_webui_fr")
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Replaces EN → FR + branding Nokido (string littéraux dans le bundle)
REPLACES: list[tuple[str, str]] = [
    # Branding
    ("llama.cpp Web UI", "La Forge"),
    ("Llama.cpp Web UI", "La Forge"),
    ("llama-server", "La Forge"),
    # Welcome / placeholder
    ("Type a message or upload files to get started", "Tape sur la forge"),
    ("Type a message...", "Tape sur la forge..."),
    ("Send a message", "Envoyer un message"),
    # Sidebar / chat
    ("New chat", "Nouvelle session"),
    ("New conversation", "Nouvelle conversation"),
    ("Edit conversation", "Renommer la session"),
    ("Delete conversation", "Supprimer la session"),
    ("Search conversations", "Rechercher session"),
    ("No conversations yet", "Aucune session"),
    # MCP
    ("Manage Servers", "Gestion serveurs MCP"),
    ("Add New Server", "Ajouter un serveur"),
    ("Server URL", "URL du serveur"),
    ("Custom Headers (optional)", "En-têtes (optionnel)"),
    ("MCP Servers", "Serveurs MCP"),
    ("MCP Server", "Serveur MCP"),
    ("Configure Server", "Configurer le serveur"),
    (
        "No MCP Servers configured yet. Add one to enable agentic features.",
        "Aucun serveur MCP configuré. Ajoutes-en un pour activer les agents.",
    ),
    # Settings
    ("Settings", "Paramètres"),
    ("Save", "Enregistrer"),
    ("Cancel", "Annuler"),
    ("Delete", "Supprimer"),
    ("Reset", "Réinitialiser"),
    ("Reset to default", "Valeur par défaut"),
    # Agentic (panel décrit dans le screenshot user)
    (
        "Maximum number of tool execution cycles before stopping (prevents infinite loops).",
        "Nombre maximum de cycles d'outils avant arrêt (anti-boucles infinies).",
    ),
    (
        "Always show agentic turns in conversation",
        "Toujours afficher les tours d'agent dans la session",
    ),
    ("Show tool call in progress", "Afficher les appels d'outils en cours"),
    (
        "Number of lines shown in tool output previews (last N lines). Only these previews and the final LLM response persist after the agentic loop completes.",
        "Nombre de lignes affichées dans les aperçus de sortie d'outil (dernières N lignes). Seuls ces aperçus et la réponse finale LLM persistent après la fin de la boucle agentique.",
    ),
    (
        "Automatically expand tool call details while executing and keep them expanded after completion.",
        "Étendre automatiquement les détails d'appel d'outil pendant l'exécution et les garder ouverts à la fin.",
    ),
    (
        "Settings are saved in browser's localStorage",
        "Paramètres sauvegardés dans le localStorage du navigateur",
    ),
    # Misc
    ("Theme", "Thème"),
    ("Light", "Clair"),
    ("Dark", "Sombre"),
    ("Auto", "Auto"),
    ("Loading...", "Chargement..."),
    ("Generating...", "Génération..."),
    ("Stop generating", "Arrêter"),
    ("Regenerate", "Régénérer"),
    ("Edit", "Modifier"),
    ("Copy", "Copier"),
    ("Copied!", "Copié!"),
    ("Welcome", "Bienvenue"),
    ("Available", "Disponibles"),
    ("Loaded", "Chargés"),
]

# Style override Nokido (palette netcfg-agent purple)
STYLE_OVERRIDE = """
<style id="laforge-fr-overlay">
/* Branding "La Forge" — overlay palette netcfg-agent (purple Datadog/Site24x7) */
:root {
  --laforge-purple: #774AFF;
  --laforge-bg: #0C0A13;
}
[data-theme="dark"] body, body.dark {
  --background: var(--laforge-bg);
  --primary: var(--laforge-purple);
}
/* Logo / titre header → "La Forge" en gras + violet */
header h1, header [data-testid="app-title"], .app-title, h1.title {
  font-weight: 800 !important;
  letter-spacing: 0.5px;
}
header h1::before, .app-title::before {
  content: "⚡ ";
}
</style>
"""


def fetch_html(port: int) -> str:
    url = f"http://127.0.0.1:{port}/"
    req = urllib.request.Request(url, headers={"User-Agent": "Nokido-ui-patcher/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode("utf-8", "replace")


def _build_js_translator() -> str:
    """Construit le script JS qui patch le DOM via MutationObserver après rendu Svelte."""
    pairs_js = ",\n    ".join("[" + repr(en) + ", " + repr(fr) + "]" for en, fr in REPLACES)
    return f"""
<script id="laforge-fr-translator">
(function() {{
  'use strict';
  const PAIRS = [
    {pairs_js}
  ];
  // Map for fast lookup (longest first to avoid partial replace)
  PAIRS.sort(function(a,b){{ return b[0].length - a[0].length; }});

  function translateNode(node) {{
    if (node.nodeType === Node.TEXT_NODE) {{
      let txt = node.nodeValue;
      let changed = false;
      for (let i = 0; i < PAIRS.length; i++) {{
        if (txt.indexOf(PAIRS[i][0]) !== -1) {{
          txt = txt.split(PAIRS[i][0]).join(PAIRS[i][1]);
          changed = true;
        }}
      }}
      if (changed) node.nodeValue = txt;
    }}
    // Attributs courants : placeholder, title, aria-label
    if (node.nodeType === Node.ELEMENT_NODE) {{
      ['placeholder','title','aria-label','alt','value'].forEach(function(attr) {{
        const v = node.getAttribute && node.getAttribute(attr);
        if (!v) return;
        let n = v;
        let changed = false;
        for (let i = 0; i < PAIRS.length; i++) {{
          if (n.indexOf(PAIRS[i][0]) !== -1) {{
            n = n.split(PAIRS[i][0]).join(PAIRS[i][1]);
            changed = true;
          }}
        }}
        if (changed) node.setAttribute(attr, n);
      }});
    }}
  }}

  function walk(root) {{
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, null);
    let n;
    while ((n = walker.nextNode())) translateNode(n);
  }}

  function init() {{
    walk(document.body);
    const obs = new MutationObserver(function(muts) {{
      muts.forEach(function(m) {{
        m.addedNodes.forEach(function(nd) {{
          if (nd.nodeType === Node.ELEMENT_NODE) walk(nd);
          else translateNode(nd);
        }});
        if (m.type === 'characterData') translateNode(m.target);
        if (m.type === 'attributes') translateNode(m.target);
      }});
    }});
    obs.observe(document.body, {{ childList: true, subtree: true,
                                  characterData: true, attributes: true,
                                  attributeFilter: ['placeholder','title','aria-label'] }});
    document.title = 'La Forge';
    console.log('[laforge-fr] translator active — ' + PAIRS.length + ' pairs');
  }}

  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', init);
  }} else {{
    init();
  }}
}})();
</script>
"""


def patch_html(html: str) -> tuple[str, int]:
    """Patche le HTML : (1) injects le translator JS + style overlay, (2) replace strings statiques."""
    n_static = 0
    for en, fr in REPLACES:
        if en in html:
            html = html.replace(en, fr)
            n_static += 1

    # Inject style + translator JS avant </body> (post bundle JS)
    js_translator = _build_js_translator()
    if "</body>" in html and "laforge-fr-translator" not in html:
        html = html.replace("</body>", js_translator + STYLE_OVERRIDE + "\n</body>", 1)
    elif "</head>" in html and "laforge-fr-overlay" not in html:
        html = html.replace("</head>", STYLE_OVERRIDE + "\n</head>", 1)

    html = html.replace('<html lang="en"', '<html lang="fr"')
    html = html.replace("<title>llama.cpp</title>", "<title>La Forge</title>")
    html = html.replace("<title>llama.cpp - Web UI</title>", "<title>La Forge</title>")
    return html, n_static


def main() -> int:
    ap = argparse.ArgumentParser(description="Patch UI llama.cpp → français + Nokido brand")
    ap.add_argument("--port", type=int, default=8091, help="Port du llama-server source")
    ap.add_argument(
        "--out",
        default=str(ROOT / "data" / "llamacpp_webui_fr"),
        help="Dossier de sortie (à monter via --path)",
    )
    args = ap.parse_args()

    print(f"[ui-patcher] fetch http://127.0.0.1:{args.port}/", flush=True)
    try:
        html = fetch_html(args.port)
    except Exception as e:
        print(f"[ui-patcher] ERROR fetch: {e}", flush=True)
        return 1
    print(f"[ui-patcher] fetched: {len(html)} chars", flush=True)

    html_fr, n = patch_html(html)
    print(f"[ui-patcher] applied {n}/{len(REPLACES)} replaces + style overlay", flush=True)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(html_fr, encoding="utf-8")
    print(f"[ui-patcher] wrote {out_path} ({len(html_fr)} chars)", flush=True)

    print("\n→ Pour activer côté llama-server, ajouter au BAT :", flush=True)
    print(f'  --path "{out_dir}"', flush=True)
    print("→ Puis nssm restart NokidoLlamaNative (admin).", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
