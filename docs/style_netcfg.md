# Style netcfg-agent — référence canonique Nokido UI

**Source** : `~/Script python IA/netcfg-agent/static/style.css`
**Inspiration** : Datadog / Site24x7 (observability dark)
**Date extraction** : 2026-04-30

---

## 1. Palette (CSS custom properties)

### Backgrounds (du plus foncé au plus clair)
| Token | Hex | Usage |
|---|---|---|
| `--bg-0` | `#0C0A13` | body — fond le plus profond |
| `--bg-1` | `#14121C` | sidebar, header — strate 1 |
| `--bg-2` | `#1C1928` | cards, panels — strate 2 |
| `--bg-3` | `#252233` | hover, scrollbar thumb |
| `--bg-4` | `#2E2A3D` | active state, scrollbar hover |

### Borders
| Token | Hex | Usage |
|---|---|---|
| `--border` | `#332F44` | cadre standard |
| `--border-subtle` | `#262338` | séparateur discret |

### Texte
| Token | Hex | Usage |
|---|---|---|
| `--text-primary` | `#EDEBF4` | headings, contenu principal |
| `--text-secondary` | `#B2AEC4` | sous-titres, labels |
| `--text-dim` | `#6E6A82` | meta, timestamps, mono |
| `--text-disabled` | `#4A4759` | disabled state |

### Accents (sémantiques)
| Token | Hex | Usage |
|---|---|---|
| `--purple` | `#774AFF` | **primary brand** (boutons, links) |
| `--purple-dim` | `#4B2E9E` | hover, accent secondaire |
| `--blue` | `#3BB2D0` | info |
| `--cyan` | `#2DD4BF` | hover info |
| `--green` | `#4AC28B` | success / OK |
| `--yellow` | `#FFC22D` | warning |
| `--orange` | `#FF9142` | error léger |
| `--red` | `#F24F4F` | error / down |
| `--pink` | `#EC4899` | accent décoratif |

### Sévérité (severity-coded)
| Token | Hex | Sens |
|---|---|---|
| `--sev-aligned` | `#4AC28B` | conforme |
| `--sev-light` | `#FFC22D` | drift léger |
| `--sev-medium` | `#FF9142` | drift moyen |
| `--sev-heavy` | `#F24F4F` | drift critique |
| `--sev-unknown` | `#6E6A82` | non audité |

### Charts (7 couleurs cyclables)
`#774AFF`, `#3BB2D0`, `#4AC28B`, `#FFC22D`, `#FF9142`, `#EC4899`, `#2DD4BF`

### Effets
| Token | Valeur |
|---|---|
| `--shadow-md` | `0 4px 12px rgba(0,0,0,0.4)` |
| `--shadow-lg` | `0 8px 32px rgba(0,0,0,0.5)` |
| `--shadow-glow` | `0 0 24px rgba(119,74,255,0.15)` (purple glow) |

### Layout
| Token | Valeur |
|---|---|
| `--radius-sm` | `6px` |
| `--radius-md` | `10px` |
| `--radius-lg` | `14px` |
| `--sidebar-w` | `220px` |
| `--topbar-h` | `52px` |

---

## 2. Typographie

| Usage | Font-family |
|---|---|
| Default body | `'Inter', -apple-system, BlinkMacSystemFont, sans-serif` |
| Code / monospace | `'JetBrains Mono', 'Consolas', monospace` |
| Mono accents (host names, timestamps, list items dim) | `'JetBrains Mono', monospace` |

**Tailles canoniques** :
- body : `13.5px` line-height `1.5`
- widget subtitle / list-item-sub / mono accents : `11px`
- host-sub : `10.5px`
- meta : `10px` (timestamps)

**Anti-aliasing** : `-webkit-font-smoothing: antialiased`

---

## 3. Architecture composants (extrait via grep classes)

| Classe | Rôle |
|---|---|
| `.sidebar` | nav latérale fixe gauche, `var(--sidebar-w)` |
| `.topbar` | header haut, `var(--topbar-h)` |
| `.widget` / `.widget-title` / `.widget-subtitle` | cards |
| `.list-item` / `.list-item-sub` | listes dans widgets |
| `.host` / `.host-sub` | host network entries |
| `.mono` | force font monospace |

---

## 4. Patterns notables

- **Body overflow:hidden** + scroll dans panels (pas de scroll global du body)
- **Scrollbar custom** 10px, thumb `var(--bg-3)`, hover `var(--bg-4)`
- **Pas de framework CSS externe** — tout est custom (pas de Tailwind, Bootstrap, Bulma)
- **Pas de framework JS** — vanilla DOM/fetch dans les templates
- **Sidebar fixed left** + main content shifted via padding-left

---

## 5. Mockups référence

7+ mockups HTML disponibles pour design reference :
- `docs/demo/v4_build/mockups/00_teaser.html` (page de garde)
- `01_dashboard.html` — dashboard principal
- `02_sites.html` — liste sites réseau
- `03_racks.html` — racks équipement
- `04_topology.html` — graphe topology
- `05_switches.html` — détail switches
- `03a_tui_boot.html` / `03c_tui_multivendor.html` / `03d_tui_identity.html` — capture TUI
- `03e_mcp_bonus.html` — endpoint MCP

(Path : `~/Script python IA/netcfg-agent/docs/demo/v4_build/mockups/`)

---

## 6. Adoption dans Nokido

Tous les fichiers suivants doivent **importer** `app/web_hub/static/nokido.css` (qui réplique cette palette au format custom properties) :

- `app/web_hub/sidebar.html` (à migrer — actuellement palette GitHub Dark)
- `app/web_hub/dashboard.html`
- `app/web_hub/rag_dashboard.html`
- `app/forge_graph_explorer.py` (templates inline)
- `app/forge_router_gateway.py`
- `app/ctf_web/app.py`
- `recon_silo/_ui.html`

Les fichiers `docs/laforge_*.html` (présentation/demo) sont **archive** — ne pas modifier.

---

**FIN doc style** — version 1.0, 2026-04-30. Mettre à jour si la palette netcfg-agent change.
