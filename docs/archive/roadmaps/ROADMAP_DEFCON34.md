# ROADMAP DEF CON 34 — BBB Era
# Cible : Qualifiers 22-24 mai 2026 (39 jours)
# Score actuel : 43/200 NYU CTF Bench (21.5% exploitation réelle)

## ÉTAT RÉEL

| Métrique | Valeur |
|---|---|
| Score NYU (exploits réels) | 43/200 = 21.5% |
| Flags lus sans exploit | ~80 (non comptés) |
| Latence cycle debug | ~30-60s (trop lent) |
| Infra | Ryzen 8700G + Vulkan + llama.cpp local |

## PALIER 1 — RÉACTIVITÉ (semaine 1-2, d'ici 30 avril)

### A. Supprimer les erreurs de syntaxe
- Patcher chirurgical : zéro quote PowerShell, tout passe par MCP python direct ✅ (déjà fait)
- forge_ctf_autonomy.py : docker_exec + docker_pipe = terminal natif ✅

### B. GDB Hot-Reload (Module forge_gdb_live.py)
- Connexion persistante GDB via gdb.attach() + pwntools
- API : `gdb_break(addr)`, `gdb_read_mem(addr, n)`, `gdb_heap_vis()`
- Cible : < 2s entre payload et lecture résultat GDB

### C. MCP Socket TCP persistant
- Remplacer le mode stdio MCP par TCP persistant sur 127.0.0.1:9999
- Supprimer la latence de boot (~3-5s actuellement)

## PALIER 2 — INSTRUMENTATION DYNAMIQUE (semaine 2-3, d'ici 7 mai)

### A. Heap Vision (forge_heap_vision.py)
- Visualiser l'état tcache/fastbin/smallbin en temps réel
- Détecter automatiquement : double free, UAF, heap overflow
- Intégré à forge_ctf_autonomy.py

### B. Frida Bridge (forge_frida.py)
- Hook dynamique de fonctions sans recompiler
- Utile pour : obfuscated binaries, stripped symbols, anti-debug

### C. Multi-challenge asynchrone
- Lancer N exploits en parallèle (asyncio + subprocess)
- Prioriser selon complexité estimée

## PALIER 3 — STEALTH & SOUVERAINETÉ (semaine 3-4, d'ici 14 mai)

### A. Anti-fingerprinting
- Variation des timing entre requêtes (pas de pattern régulier)
- Rotation des user agents / signatures de connexion
- SovereignContextMapper : anonymisation des requêtes Cloud

### B. Rate-limit detection
- Détecter si le service ralentit/ferme → backoff automatique
- Mode "slow brute" pour challenges avec détection

### C. P2P Swarm léger
- 2-3 instances Nokido en parallèle sur le même hardware
- Partage des résultats via SQLite WAL (déjà en place)

## PALIER 4 — ENTRAÎNEMENT DEF CON (semaine 4, d'ici 22 mai)

### A. Changer de dataset
- Quitter NYU CTF Bench → archives DEF CON (OOO, MCSB, Plaid)
- Télécharger : picoCTF, CSAW Finals, DEF CON 31-33 archives
- Focus : heap exploitation, kernel pwn, race conditions

### B. Time-boxing par challenge
- Max 15 min par challenge (vs maintenant : illimité)
- Si pas de flag → skip automatique, noter pour review

### C. Simulation Quals
- Session de 48h continue (simulation du format réel)
- Objectif : > 3 flags dans les premières 2h

## PRIORITÉS IMMÉDIATES (aujourd'hui)

1. **forge_gdb_live.py** — GDB hot-reload (impact max sur vitesse debug)
2. **Finir NYU CTF Bench** jusqu'à 50/200 pour valider les bases
3. **Premier test sur archive DEF CON 31** (pwn/misc simples)

## CE QUI RESTE DIFFICILE SANS HUMAIN

- Setup réseau spécifique (port forwarding, VPN)
- Challenges nécessitant une interaction physique (hardware CTF)
- Interprétation de screenshots/images (OCR partiel seulement)
- Validation de l'intention (is this an IA trap?)
