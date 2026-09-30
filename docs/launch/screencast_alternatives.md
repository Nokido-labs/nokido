# 🎥 Screencast alternatives (no OBS)

Pour capturer la **UI web** (provider admin, RAG explorer) sans OBS, trois
options Windows gratuites. Pour le **terminal**, voir [asciinema_script.md](asciinema_script.md).

## 🥇 ScreenToGif (recommandé — Windows)

Gratuit, open-source, ~5 MB, parfait pour des courts GIFs UI.

### Install (2 min)

```powershell
# Via winget
winget install --id NickeManarin.ScreenToGif

# OU télécharger : https://www.screentogif.com/
```

### Workflow

1. Lance ScreenToGif → **Recorder**.
2. Position la fenêtre browser sur `http://127.0.0.1:8766/admin/providers`.
3. Cale la zone de capture pour cadrer la table providers (ratio 16:9 idéal pour Twitter).
4. **F7** pour record, **F8** pour stop.
5. L'éditeur s'ouvre automatiquement :
   - Skip frames inutiles (clic droit → Delete).
   - Add caption en bas (texte court : "Provider admin UI — vault-backed key management").
   - Crop si besoin.
6. **Save as GIF** :
   - Encoder : **System** (interne ScreenToGif, meilleur que ffmpeg pour GIF).
   - Quality : 80.
   - Loop : Forever.
7. **Cible taille** : <2 MB pour Twitter (limite 5 MB strict, mais 2 MB load plus vite).

### Tips ScreenToGif

- **15 FPS** suffit pour UI (économise 30% taille vs 30 FPS).
- **Couleurs : Tweet/HN viewers regardent sur mobile** — utilise un thème dark contrasté (couleurs vives sur fond sombre).
- **Cursor highlight** : Options → Recorder → Cursor → Yellow circle → on voit où tu cliques.

## 🥈 Xbox Game Bar (built-in Windows 10/11)

Pré-installé, **Win+G** pour ouvrir.

### Workflow

1. **Win+G** → Capture widget.
2. Click "Start recording" (Win+Alt+R).
3. Performance ton démo (45-60s max).
4. Stop (Win+Alt+R again).
5. Fichier sauvé dans `%USERPROFILE%\Videos\Captures\`.

### Limitations

- **Capture fenêtre entière** seulement (pas une zone). Pré-redimensionne la fenêtre browser à la taille voulue.
- **MP4 output** — pas GIF. Conversion nécessaire.
- Capture la fenêtre **focused only**. Si tu cliques ailleurs, ça stoppe.

### Conversion MP4 → GIF avec ffmpeg

```powershell
# Install ffmpeg
winget install Gyan.FFmpeg

# Convertir (avec subtitle / caption optionnel)
ffmpeg -i ~\Videos\Captures\input.mp4 `
    -vf "fps=15,scale=800:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" `
    -loop 0 output.gif

# Vérifier taille
Get-Item output.gif | Format-List Length
# Cible: < 2_000_000 octets pour Twitter
```

## 🥉 ShareX (free, plus puissant)

Si tu veux + de control / annotations.

```powershell
winget install ShareX.ShareX
```

ShareX peut record direct en GIF, MP4, ou WebM. Hotkey **Print Screen** ou personnalisable. Plus de features mais courbe d'apprentissage.

## 🎬 Script de capture — UI providers (10-15 secondes)

À faire pendant l'enregistrement :

1. **Pre-state** : page chargée `/admin/providers`, 29 providers visibles, tableau scrollable.

2. **Action 1 (3s)** : filter par "tier" → **Free cloud**. Le tableau filtre à 16 lignes.

3. **Action 2 (4s)** : click sur le bouton **🔑 Set key** ligne `groq`. Modal apparaît.
   - Show that input field is `password` (asterisks).
   - Tape une clé fake `gsk_xxxxxxxxxxxxxxxxxxxx` pour la démo.

4. **Action 3 (3s)** : click **Save to vault**. Toast apparaît : `Saved GROQ_API_KEY → vault (***xxxx)`.

5. **Action 4 (3s)** : status badge sur la ligne `groq` change de `✗ no key` à `✓ key present`.

6. **End frame (2s)** : show la mention "DPAPI machine-scope vault — never in `.env`" en bas.

## 🎯 Captures additionnelles utiles

Si tu as 1h supplémentaire :

| Capture | Durée | Pour |
|---|---|---|
| TUI 6-panes broadcast (`@all`) | 12s | r/LocalLLaMA |
| RAG explorer (`/forge/rag`) avec query sémantique | 10s | Show HN |
| Network log live (`/forge/network`) showing 5 MCP calls/sec | 8s | Twitter thread tweet 6 |
| Provider cascade fallback (Groq quota epuisé → Cerebras auto) | 15s | HN comments si demandé |

## 📦 Bundle final

Avant de poster, garde :

```
docs/launch/media/
├── demo_terminal.cast      # asciinema raw (re-playable)
├── demo_terminal.gif       # 800px wide, 15 FPS, ~1 MB
├── demo_terminal_long.mp4  # 1080p, 45s pour YouTube
├── demo_admin_ui.gif       # 12s, ~1.5 MB
├── demo_admin_ui.mp4       # MP4 backup
└── thumbnail.png           # 1280×720 cover frame for video uploads
```

Upload tout sur **GitHub Releases** ou **asciinema.org** + lien dans le README.

## 🎨 Stylé sans devenir mainstream marketing

Le ton Nokido = technique honnête, pas startup pitch. Pour les captures :

- **Pas de mouvements caméra** (zoom in, pan) — la sobriété c'est crédible.
- **Pas d'effets transition flashy**.
- **Caption blanc sur fond noir**, police mono.
- **Une seule action par capture** — pas de demo 5-en-1 confuse.
- **Vérité > effet** : si y'a un bug visible dans la demo, c'est OK, ne le retire pas.

> "Ils te jugeront sur la transparence, pas sur le packaging."
