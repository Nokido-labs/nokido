# Recording the launch demos (ScreenToGif / ShareX / Win+G)

Deux scripts pilotent une demo paced ; tu enregistres l ecran avec un
outil externe. Resultat = vraies captures (pas Playwright synthetique).

## Pre-requis (deja en place 2026-05-27)

- ScreenToGif `C:\Program Files\ScreenToGif\ScreenToGif.exe`
- ShareX     `C:\Program Files\ShareX\ShareX.exe`
- Hub UP sur `http://127.0.0.1:8766` (verifier : `curl /health`)
- Vault DPAPI seede (CLAUDE token + provider keys)
- Playwright + Chromium installes (dans miniforge3 base)

## 1. Demo terminal (~50s, scenario 5 sequences)

### Setup fenetre

- Windows Terminal, profile dark / police mono 14-16pt / taille ~100x30
- Onglet propre, `clear` avant
- Pas de NSSM bg log dans la fenetre

### Enregistrement

```powershell
# 1. Ouvre ScreenToGif > Recorder. Cadre la fenetre Windows Terminal.
#    Options recommandees :
#      - Encoder         : System (legacy GIF, meilleur que ffmpeg pour text)
#      - FPS             : 15
#      - Cursor highlight: Yellow circle ON
#      - Loop            : Forever
# 2. F7 pour record.
# 3. Lance le script (cle deja dans le vault, vrais appels hub) :
& "~/miniforge3/python.exe" `
  "~/Script python IA/Nokido/tools/forge_demo_runner_terminal.py"
# 4. F8 pour stop quand caption finale disparait.
# 5. Save as GIF :
#    - Quality 80
#    - Crop a la fenetre terminal (skip headers OS)
#    - Output : docs/launch/media/demo_terminal_real.gif
```

### Cibles taille

| Plateforme | Limite | Strategie |
|---|---|---|
| Twitter / X | 5 MB | gifsicle -O3 --colors 64 (vise ~1.5 MB) |
| Reddit     | 20 MB | brut |
| HN / Lobsters | illimite | brut |

### Options scripts

```powershell
# Plus rapide (1.5x speed) -- demo + courte
& "~/miniforge3/python.exe" tools/forge_demo_runner_terminal.py --speed 1.5

# Sans firewall step (si forge_semantic_firewall HS)
... --skip-firewall

# Sans couleurs ANSI (cmd.exe legacy)
... --no-color
```

## 2. Demo admin UI (~15s, scenario 6 actions)

### Setup fenetre

- Le script lance Chromium VISIBLE en 1280x800.
- Pas besoin de pre-ouvrir browser.

### Enregistrement

```powershell
# 1. Lance ScreenToGif Recorder. Place le rectangle de capture sur la
#    zone OU la fenetre Chromium va apparaitre (par defaut au centre).
# 2. F7 pour record.
# 3. Lance le script :
& "~/miniforge3/python.exe" `
  "~/Script python IA/Nokido/tools/forge_demo_runner_admin_ui.py" `
  --headed-slow
# 4. Le browser auto-pilote : filtre groq, modal, type cle fake, save, toast.
# 5. F8 quand toast disparait.
# 6. Save GIF : 15 FPS, palette 128, output demo_admin_ui_real.gif
```

### Options

```powershell
# Autre provider (cerebras / mistral / cohere / etc)
... --provider cerebras

# Garde la cle fake dans le vault (par defaut, cleanup automatique)
... --no-cleanup
```

## 2.bis Hub tour multi-scene (~90s, parcours complet UI)

Pour une demo qui couvre toutes les UI graphiques d un coup :

```powershell
# 1. ScreenToGif F7, cadre Chromium (1400x900 par defaut).
# 2. Lance tour complet :
& "~/miniforge3/python.exe" `
  "~/Script python IA/Nokido/tools/forge_demo_runner_hub_tour.py" `
  --headed-slow
# 3. F8 quand browser se ferme.

# Variantes :
# Scene unique (granular pour HN / Reddit /LocalLLaMA / Twitter):
... --scene rag         # tokenizer playground + stats
... --scene network     # live SSE network stream
... --scene providers   # LLM admin (sans modal cle)
... --scene dashboard   # FastAPI portal :7400 si UP
... --scene rbac        # RBAC mapping :7400 si UP

# Ordre custom pour --scene all :
... --order rag,network,providers  # 3 scenes au lieu de 5
```

Output naming convention :
```
docs/launch/media/
├── demo_hub_tour_full.gif         # ~3 MB, tour complet 90s
├── demo_hub_tour_rag.gif          # ~600 KB, scene RAG seule
├── demo_hub_tour_network.gif      # ~800 KB, live stream traffic
└── ...
```

## 3. Alternative ShareX (annotations)

Si tu veux flecher / encadrer des zones :

1. Lance ShareX, settings > After capture > Annotate.
2. Hotkey Print Screen ou personnalise.
3. Enregistre en GIF (record screen > region > save as GIF).
4. ShareX permet annotations apres capture (flecher la table, surligner un champ).

Ne pas combiner avec ScreenToGif simultanement (conflit hotkeys).

## 4. Post-process

```powershell
# Compress GIF avec gifsicle (si winget l a installe)
gifsicle -O3 --colors 64 demo_terminal_real.gif -o demo_terminal_optimized.gif

# Convert MP4 -> GIF (si tu utilises Win+G qui sort MP4)
ffmpeg -i input.mp4 -vf "fps=15,scale=800:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" `
  -loop 0 output.gif

# Verif taille finale
Get-Item *.gif | Select Name, @{N='KB';E={[int]($_.Length/1024)}}
```

## 5. Output finaux attendus

```
docs/launch/media/
├── demo_terminal_real.gif       # ~1.5 MB, ScreenToGif, 15 FPS, 800px wide
├── demo_admin_ui_real.gif       # ~1.0 MB, ScreenToGif, 15 FPS
├── demo_terminal.gif            # Playwright synthetique (existant)
└── demo_admin_ui.gif            # Playwright synthetique (existant)
```

Garder les deux versions :
- `*_real.gif` -> README + tweet (plus credible visuellement)
- `*.gif` synthetique -> docs (reproductible, mainteneurs regenerent)

## 6. Verification finale

```powershell
# Replay GIFs dans browser
Start-Process "docs/launch/media/demo_terminal_real.gif"
Start-Process "docs/launch/media/demo_admin_ui_real.gif"

# Si trop long / sequence ratee : re-record (les scripts sont idempotents,
# la cle fake est nettoyee a chaque run)
```

## Troubleshooting

| Probleme | Cause likely | Fix |
|---|---|---|
| Terminal demo : `vault FORGE_TOKEN_CLAUDE introuvable` | Pas de vault DPAPI | `LAFORGE_PYTHON tools/forge_vault_seed_agent_tokens.py --from-env-file Nokido.env` |
| Admin UI demo : `playwright pas installe` | Pas dans miniforge3 base | `~/miniforge3/python.exe -m pip install playwright && playwright install chromium` |
| Browser apparait mais 401 | Token vault mismatch hub | `forge_mcp_json_sync.py --check` puis verif token |
| Toast jamais visible | Network slow / hub busy | Augmenter `time.sleep` ou `--headed-slow` |
| GIF trop gros | Quality trop haut | `gifsicle --colors 64 --lossy=80` |
