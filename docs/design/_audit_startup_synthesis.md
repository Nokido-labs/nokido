# Audit demarrage Nokido MCP Hub - synthese triangulation

Date : 2026-04-27 ~20:00 UTC
Modeles consultes : Gemini 2.5 Flash Lite + Kimi K2 Thinking + GPT-4o (arbitrage)
Statut : DOC-ONLY, lecture seule, pas de modif effectuee

================================================================================
1. CAUSE RACINE IDENTIFIEE par triangulation + repro empirique
================================================================================

Le bug : UnicodeDecodeError byte 0x90 position 79

161 occurrences dans mcp_service_err.log, toujours byte 0x90, position 79,
dans _readerthread du module subprocess.

Hypotheses initiales :
- Gemini : caractere etendu CP1252 -> errors='replace' suffit
- Kimi   : byte binaire / PE header -> fix profond requis

Verification empirique :
1. bytes([0x90]).decode('cp1252') -> ERREUR (0x90 non mappe en CP1252)
2. bytes([0x90]).decode('cp850')  -> OK = 'E' avec accent aigu majuscule
3. Reproduction : subprocess.run(['netstat','-ano'], text=True, encoding='cp850') -> succes
4. Reproduction : subprocess.run(['netstat','-ano'], text=True) avec PYTHONUTF8=1 -> CRASH IDENTIQUE

Conclusion : Kimi a raison sur 'byte non-texte hors flux JSON' mais l'origine
n'est ni un PE header ni un dump. C'est netstat qui ecrit 'Etat' en CP850 dans
la sortie console Windows fr-FR, et le hub force UTF-8 via PYTHONUTF8=1 dans
NSSM env -> crash decodage dans le thread daemon _readerthread.

Localisation exacte : tools/nokido_hub.py lignes 1561-1570 (boucle 'garde port').

L1561 : _ns = _sp.run(['netstat','-ano'], capture_output=True, text=True)
L1565 : _ci = _sp.run(['powershell','-Command', ...], capture_output=True, text=True).stdout.strip()

Aucune des 3 calls subprocess de la garde port ne specifie encoding=.
Avec PYTHONUTF8=1 injecte par NSSM, Python tente UTF-8 sur de la sortie CP850.

================================================================================
2. RISQUES CONVERGENTS Gemini + Kimi + GPT-4o
================================================================================

#1  Crash loop NSSM amplifie : si bridge crash sur input invalide, AppRestartDelay=2s
    tourne en boucle CPU/IO  [HAUTE | Kimi confirme GPT-4o]
#2  Pollution log + perte observabilite : 161 tracebacks parasites masquent les vrais
    bugs  [HAUTE | Gemini + Kimi]
#3  Regression silencieuse _fallback_stdio : commit 0e038b5 a vire l'os.execv,
    fallback non-fonctionnel  [HAUTE | Kimi - manque par Gemini]
#4  NameError _bridge_log L348 : ligne commentee en WT pour contourner
    [MOYENNE | connu transfer.txt P0]
#5  Race condition _wait_hub 30s : Claude Desktop peut snapshoter tools/list trop tot
    [MOYENNE | Gemini]
#6  mcp_service.log a 0 byte : NSSM stdout jamais ecrit
    [BASSE - cosmetique | Gemini]

================================================================================
3. PLAN CORRECTION PRIORISE (Kimi-style, valide GPT-4o)
================================================================================

P0 - Fix encoding subprocess (cause racine 0x90)
----
Modifier les 3 occurrences capture_output=True, text=True dans
tools/nokido_hub.py (L1561, L1565-1567, L1570) pour ajouter explicitement :

  subprocess.run([...], capture_output=True, text=True,
                 encoding='utf-8', errors='replace')

OU mieux (preference Kimi) : passer en text=False + decoder manuellement
avec cp850 puis re-encoder UTF-8. Plus verbose mais conserve les caracteres
accentues sans perte.

Effet attendu : 161 tracebacks/h -> 0. mcp_service_err.log redevient utile.
Risque : faible. C'est de la lecture seule (netstat, Get-WmiObject).

P1 - Fix _fallback_stdio() (regression 0e038b5)
----
Couvert dans sandbox/bridge_repair_plan.md etape R1. Restaurer os.execv
+ definir _bridge_log = logging.getLogger('mcp.bridge').

P2 - Circuit breaker NSSM (anti crash loop)
----
Augmenter AppRestartDelay de 2s a 10-30s + ajouter compteur d'exits.
Si > N restarts en 1 min, NSSM s'arrete et alerte au lieu de boucler.

  nssm set LaForgeMCP AppThrottle 10000
  nssm set LaForgeMCP AppExit 0 Restart
  nssm set LaForgeMCP AppExit 1 Exit

P3 - Race condition _wait_hub (Gemini)
----
Backoff exponentiel au lieu de polling fixe 0.5s.
Plus tolerant si hub demarre sous charge.

P4 - mcp_service.log 0 byte (cosmetique)
----
Ajouter PYTHONUNBUFFERED=1 au AppEnvironmentExtra NSSM.

================================================================================
4. RECOMMANDATIONS ARCHITECTURE (synthese 3 modeles)
================================================================================

1. Health endpoint NSSM-aware (/healthz qui retourne 200 + metriques bridges) - Kimi
2. Circuit breaker sur le pipe - Kimi (3 erreurs/10s = bridge coupe + redemarre)
3. Bridge en Go/Rust a terme - Kimi (Python fragile pipes Windows). Hors scope court terme.

GPT-4o : 'Gemini propose une solution rapide mais insuffisante. Kimi a une
vision plus robuste et systemique. GO pour Kimi.'

================================================================================
5. ORDRE RECOMMANDE D'EXECUTION
================================================================================

1. P0 - Fix encoding subprocess : 3 lignes, risque nul, effet immediat
2. P1 - Fix _fallback_stdio : selon plan bridge_repair_plan.md R1
3. P2 - NSSM throttle : 1 commande, reversible
4. P3 - _wait_hub backoff : refactor polling, ~10 lignes
5. P4 - PYTHONUNBUFFERED : 1 commande NSSM

P0 est INDEPENDANT des autres, peut etre fait isolement en premier.
Les 3 modeles convergent (meme Gemini avec errors='replace' y arrive,
juste avec fix moins propre).

================================================================================
6. SAUVEGARDES POUR EXECUTION FUTURE
================================================================================

- sandbox/backups/hub-phase3a-20260427-195013/ : hub avant intervention
  (104 KB, sha=338c786f370d3d3e)
- sandbox/_audit_kimi_startup.md     : audit Kimi brut
- sandbox/_audit_gpt4o_startup.md    : arbitrage GPT-4o
- sandbox/_startup_snapshot.json     : snapshot infra factuel

Fin de _audit_startup_synthesis.md
