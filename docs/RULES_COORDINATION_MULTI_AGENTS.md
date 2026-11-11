# Coordination multi-agents — claim avant édition (anti-clobber)

Déportée VERBATIM de `RULES_SHARED.md` le 2026-11-04 (owner : « 16 % de contexte au démarrage »).

Working tree PARTAGÉ par plusieurs surfaces simultanées : Claude chat+cowork
(stdio bridge = `BRIDGE`), Claude Code (`CLAUDE`/cli_claude), Gemini, + tâches
cowork AUTONOMES. Sans coordination = elles s'écrasent (uncommitted soup, clobber).

AVANT d'éditer un fichier tracké :
1. `blackboard_read_zone zone_name=tree_locks` — si un autre agent a claim ce
   fichier (récent, TTL), NE PAS l'éditer ; coordonner (notify) ou différer.
2. En te lançant, publie : `blackboard_propose_fact zone_name=tree_locks
   key=<ton_agent> fact="<agent> édite: <fichiers> — <raison>"`.
3. Commit TÔT et PETIT (le daemon POST_COMMIT indexe en RAG = awareness partagée).
   JAMAIS `git add -A` (balaie l'uncommitted des autres).
4. Restart hub/service = coordonner (annoncer au blackboard + notify), jamais en
   solo si d'autres surfaces sont actives.

Surface autonome (cowork scheduled tasks) : scoper hors des fichiers hot, ou
opérer sur un worktree git dédié — isolation physique > protocole coopératif.

## Worktree dedie par agent (2026-09-07) — DEPORTEE

La CI de reference ne capture un sha que sur un arbre PROPRE : tout agent autonome travaille dans SON worktree (cowork : `laforge-cowork/` ; AGY : `nokido_worktrees/antigravity/`), la creation d'un worktree est un geste OWNER, et editer hors de son claim dans l'arbre partage empeche TOUS les autres de rattacher un verdict de CI. Detail : [`RULES_WORKTREE_DEDIE.md`](RULES_WORKTREE_DEDIE.md).

Un worktree se distingue par ECRIVAIN, jamais par protocole (owner 2026-10-28) : ACP, MCP ou A2A disent comment on parle a un agent, pas qui ecrit l'arbre. Une session ACP interactive pilotee depuis `/acp` ecrit dans `nokido_worktrees/acp_<cli>`, distinct du worktree de l'executeur du meme CLI (le routeur partageait `codex` avec l'executeur Codex : clobber possible).
