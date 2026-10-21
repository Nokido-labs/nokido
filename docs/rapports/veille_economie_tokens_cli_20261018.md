# Veille 18/10 — réduire la dépense de tokens des CLI payants (Claude Code en orchestrateur)

Demande owner 18/10 : « il y a du bon à en tirer pour limiter les dépenses en tokens des CLI forts (et payants) ».
Sources ingérées EN ENTIER par `tools/forge_ingest_github_repo.py` (≈ 53 600 fragments, `github:<owner>/<repo>/…`) :
antigravity-for-claude-code, subcodex-mcp, sub-agents-mcp/skills, zen-mcp-server (PAL), crystal, claude-squad,
gsd-core, get-shit-done(-cc-ui), funsearch, alphadev, pymdp, Lean `repl`. Extraction locale deepseek-r1:14b
(job_8f0773786c96), colonne « existant Nokido » corrigée à la main (le modèle répondait « non » partout).

## Mesure de référence (la seule chiffrée)

`antigravity-for-claude-code/docs/AB-RESULTS.md` — même tâche (build ADK multi-agents + `adk eval`), 3 façons :
coût frontière pondéré **2,62 M (Claude seul @high) / 5,34 M (@max) / 1,91 M (hybride)**, qualité 3/3 partout
→ **−27 % vs @high, −64 % vs @max à qualité égale** ; le travail Gemini n'est même pas compté. Le gain croît avec la
taille ; « les petites tâches ponctuelles sont moins chères à faire directement sur Claude » (seuil de rentabilité).

## Mécanismes, confrontés à l'existant

| mécanisme (source) | ce que fait le projet | existant Nokido | écart / action |
|---|---|---|---|
| Chef d'orchestre / exécutant (antigravity, subcodex) | Claude spécifie et vérifie ; l'exécutant écrit le code et les fichiers → **Claude ne génère pas le contenu des fichiers** | tasks.db + exécuteurs (OpenCode GPTOSS/GLM/Nemotron, AGY, Codex), RED par Claude | PARTIEL : fiabilité des exécuteurs (18/10 : consigne C:/tmp illisible par AGY/GLM, fournisseur surchargé) ; consigne AUTONOME désormais (feedback 18/10) |
| Seuil de rentabilité par taille (antigravity) | petite tâche → Claude ; grosse → délégation | P1_routage_executeur_par_difficulte_20261017 (palier S/M/L owner 17/10) | PARTIEL : le palier n'est pas automatique |
| Délégation en UN lot synchrone (antigravity) | « une attente, pas de churn de cache » | run_job + Monitor (un réveil) | OUI pour les jobs ; NON pour mes sondes fines (garde d'impulsion) |
| Contrat de digest (antigravity `--digest`, `digest_warn_chars`) | le retour délégué est un résumé ; le complet va dans un fichier | SymbioticBridge (> 2 000 car.), troncature hub | PARTIEL : la taille des retours MCP n'est PAS mesurée (`result_bytes` = 0, dérogation owner en attente) |
| Contexte isolé, seul le résultat remonte (PAL `clink`, sub-agents) | sous-agent dans un contexte vierge | exécuteurs en worktree ; forge_deep_explore (recon locale, digest) | OUI |
| Détection de blocage + reprise (subcodex `stallTimeoutMinutes`=5, `maxRecoveryAttempts`=2) | relance auto | forge_job_watch_cli `--gel-s` (détecte) ; réaffectation à la main | PARTIEL : la réaffectation n'est pas automatique |
| Repli après 2 échecs / verrou de fichier Windows (subcodex mode `fallback`) | bascule vers le sous-agent | règle owner 17/10 « le corps débloque » | PARTIEL, même écart |
| Fan-out interne bon marché (agy `define_subagent` ≥ 1.0.16) | une délégation, N sous-agents côté pas cher | AGY via tâche ANTIGRAVITY | NON exploité |

## Trois recommandations, chacune avec la mesure qui décide (règle owner 16/10 : seuil fixé AVANT)

1. **Mesurer la taille des retours MCP** (lever `result_bytes` = 0) puis poser un contrat de digest au-delà d'un seuil.
   Décision : part des tokens de session due aux retours d'outils, avant/après, sur 3 sessions comparables.
2. **Palier automatique S/M/L** : une tâche dont le diff attendu dépasse un seuil part en délégation ; en dessous,
   Claude. Décision : coût frontière par tâche fermée, sur un lot témoin (protocole AB-RESULTS : même tâche, 2 voies).
3. **Réaffectation automatique** sur gel ou échec d'exécuteur (subcodex : 5 min, 2 essais). Décision : délai moyen de
   clôture d'une tâche déléguée et nombre d'interventions de Claude par tâche.
