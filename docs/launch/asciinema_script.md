# 🎬 Asciinema demo script

Script pas-à-pas pour enregistrer un cast terminal propre de 45-60s qui
montre Nokido en action.

## 🛠️ Install asciinema (5 min)

### Windows (recommandé)

asciinema natif ne marche pas Windows direct. Deux options :

**Option A — WSL (recommandé si tu as WSL)** :
```bash
wsl -d Debian
sudo apt install asciinema
asciinema --version
```

**Option B — termtosvg + render** (Windows natif) :
```powershell
pip install termtosvg
```
Plus simple : enregistre avec `termtosvg` puis converti SVG → GIF avec ffmpeg.

**Option C — terminalizer (Node)** :
```bash
npm install -g terminalizer
terminalizer init
terminalizer record demo
terminalizer render demo --output demo.gif
```

### Linux / macOS

```bash
# Linux
sudo apt install asciinema   # ou dnf/pacman
# macOS
brew install asciinema
```

## 🎬 Script complet — copier-coller dans le terminal

### Setup avant l'enregistrement

```bash
# 1. Fenêtre terminal propre, taille 100x30 (idéal pour SVG/GIF lisible)
# 2. Theme dark (cohérent avec capture web UI)
# 3. Désactive prompts colorés ennuyeux : prompt simple "$ "
# 4. Hub up
curl -s http://localhost:8766/health
# Attendu: {"ok":true,"version":"18.3"}

# 5. Clear
clear
```

### Démarrer l'enregistrement

```bash
# WSL / Linux / macOS
asciinema rec -t "Nokido — Autonomous Local-First AI OS" \
    -i 1.5 --overwrite ~/nokido_demo.cast

# Windows termtosvg
termtosvg nokido_demo.svg
```

Tape les commandes ci-dessous avec **pauses ~1s entre chaque** pour donner
le temps au viewer de lire :

### Sequence (~50 secondes)

```bash
# === Sequence 1 — vérification rapide hub (5s) ===
clear
echo "# Nokido — local-first autonomous AI OS"
curl -s http://localhost:8766/health | python -m json.tool

# === Sequence 2 — list tools MCP (10s) ===
clear
echo "# 25 MCP tools exposed by the hub:"
curl -s -X POST http://localhost:8766/mcp \
    -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
    | python -c "import sys,json; tools=json.load(sys.stdin)['result']['tools']; print('\n'.join(['  - '+t['name'] for t in tools[:15]])); print(f'  ... ({len(tools)} total)')"

# === Sequence 3 — first ask via local Ollama (15s) ===
clear
echo "# Routing to local Ollama (no cloud egress):"
curl -s -X POST http://localhost:8766/mcp \
    -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"ask","arguments":{"provider":"ollama_local","message":"In one sentence: what is RAG?"}}}' \
    | python -c "import sys,json; r=json.load(sys.stdin); print(r['result']['content'][0]['text'][:300])"

# === Sequence 4 — semantic firewall in action (10s) ===
clear
echo "# Semantic firewall pre-flight on a prompt with sensitive data:"
python -c "
import sys
sys.path.insert(0, 'app')
from forge_semantic_firewall import get_firewall
fw = get_firewall()
pf = fw.pre_flight('My API key is sk-proj-secret123; what is RAG?', context='', ring=2)
print(f'  Block reason: {pf.reason}' if not pf.ok else '  OK after redaction')
print(f'  Safe task: {pf.safe_task[:120]}...')
print(f'  Mapping aliases: {len(pf.mapping)} sensitive tokens replaced')
"

# === Sequence 5 — RAG persistent memory (10s) ===
clear
echo "# RAG search in 380k+ chunks (BGE-M3 1024D + FTS5 + reranker):"
curl -s -X POST http://localhost:8766/mcp \
    -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"rag","arguments":{"action":"search","topic":"neuromorphic computing","limit":3}}}' \
    | python -c "import sys,json; r=json.load(sys.stdin)['result']['content'][0]['text']; print(r[:400])"

# === Final caption (5s) ===
clear
cat << 'EOF'
Nokido — Local-first · Neuro-symbolic · AGPLv3

  github.com/user/Nokido
  Manifesto + Wiki in repo

  Tested on AMD Ryzen 7 8700G + Radeon 780M iGPU
  HumanEval 87.8% · BFCL v4 90-96% · 29 LLM providers
EOF
```

### Arrêter

```bash
exit          # ou Ctrl+D, ferme asciinema
```

### Vérifier + uploader

```bash
# Local replay pour check
asciinema play ~/nokido_demo.cast

# Upload sur asciinema.org (gratuit, public)
asciinema upload ~/nokido_demo.cast
# Renvoie une URL https://asciinema.org/a/<ID>

# Récupère le .cast file pour embed direct si tu préfères self-host :
# git add ~/nokido_demo.cast → docs/launch/media/demo.cast
```

## 🎞️ Convertir en GIF pour Twitter / Reddit

```bash
# Install agg (asciinema → GIF converter)
cargo install --git https://github.com/asciinema/agg

# Convertir
agg ~/nokido_demo.cast nokido_demo.gif \
    --theme github-dark \
    --font-size 14 \
    --speed 1.5 \
    --idle-time-limit 1.5

# Optimiser avec gifsicle pour < 2 MB (limite Twitter)
gifsicle -O3 --colors 64 nokido_demo.gif -o nokido_demo_optimized.gif
ls -lh nokido_demo_optimized.gif
# Cible: < 15 MB pour HN, < 5 MB pour Twitter
```

## 🎯 Conseils visuels

- **Police 14-16 pt**, fond sombre (cohérent avec admin UI).
- **Vitesse 1.3-1.5×** au render — donne du rythme sans presser.
- **Pas de typos** — pré-écris les commandes dans un .sh, copie-colle.
- **Première frame doit montrer un truc cool** (l'autoplay GIF Twitter ne joue
  que si tu cliques — la preview frame compte autant que le contenu).
- **Garde une caption finale** : repo URL + 3 chiffres clés. Reste affichée
  2-3 secondes.

## 📝 Si tu veux pré-tester sans WSL

Sur Windows natif, le plus simple = **Windows Terminal + screencast Win+G**
(voir [screencast_alternatives.md](screencast_alternatives.md)). asciinema
n'est pas obligatoire, c'est juste le plus joli pour du terminal pur.
