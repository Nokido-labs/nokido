# MAP.md — Nokido CTF + Root-Me
*Généré : 2026-04-15 | State: FORGE-2026-04-15-71CTF-ROOTME-CH88*

## Scores
- NYU CTF Bench: 71/200 (35.5%) — 3.5x meilleur publié (GPT-4 ~10%)
- Root-Me ch88 "VPN Provider": 7/8 étapes résolues, flag manquant

## Arbre de décision — 5 derniers choix techniques

### 1. SSTI invalidée (faux positif)
- Symptôme: {{config}} crashait (13420B), {{7*7}} ne crashait pas (14152B)
- Hypothèse: SSTI blind dans ip_address
- Réalité: le crash venait de sessions expirées/erreurs réseau, pas de SSTI
- Preuve: {{7*7}} ne produit pas "49" dans la page, input non reflété
- Leçon: toujours vérifier que le résultat SSTI apparaît dans la réponse

### 2. Flask port 8000 découvert via lvh.me DNS
- Problème: localhost:PORT donnait "Nothing" (nginx 301 sans bon Host)
- Solution: lvh.me résout vers 127.0.0.1 → bypass le check IP
- Test: SSRF ip_address=http://lvh.me:8000/ → textarea montre la page Flask
- Leçon: utiliser des domaines DNS qui résolvent vers 127.0.0.1

### 3. NoSQL $where exfiltration
- Méthode: $where exécute du JS MongoDB côté serveur
- Résultat: Alice a 4 champs (_id, name, age, password), Bob a 3
- Limitation: db.getCollectionNames() bloqué ("Invalid operator")
- Leçon: $where limité à this.* dans les requêtes find()

### 4. WASM reverse engineering
- Outil: wasm-decompile + Node.js dans Exegol
- Technique: XOR 12 sur chaque byte, puis ADD -13
- Résultat: access code + URL secrète du panel
- Leçon: Node.js peut instancier et appeler les fonctions WASM exportées

### 5. Score CTF corrigé 46→71
- Problème: recount post-migration avait perdu 25 challenges
- Solution: reconstruction depuis git log (commits CTF)
- Résultat: 71/200 confirmé, 13 chunks techniques ancrés dans RAG
- Leçon: toujours commit les flags avec le score dans le message

## Fichiers chauds
| Fichier | Rôle |
|---------|------|
| transfer.txt | État migration (ce fichier) |
| map.md | Carte navigation |
| sandbox/solve_vpn_provider.py | Solver Root-Me ch88 (SSTI blind - INVALIDÉ) |
| RAG/embeddings.db | 8647 chunks dont 13 CTF techniques |
| app/forge_exec.py | Exécution Docker (drun, sh, pyrun, pipe_bin) |

## Infra Root-Me ch88
```
[Exegol] → curl → [nginx:80] → Host:nxshield.com → [Flask:8000]
                                                       ↓
                                              /demo → WASM check
                                              /demo_access/.../html → NoSQL login
                                              /demo_access/.../panel → IP Checker (SSRF)
                                              /flag.txt → 404 (BLOQUÉ)
                                              
SSRF: ip_address + show=1 → requests.get(ip_address) → textarea
  ✅ http://httpbin.org/ip → fonctionne (internet)
  ✅ http://lvh.me:8000/ → fonctionne (Flask interne)
  ❌ /flag.txt → pas une route Flask
  ❌ file:///flag.txt → requests ne supporte pas
```
