# bug_homeostat_freine_au_lieu_de_liberer_20261022 : constat illisible, rien codé (25/10/2026)

## Décision
La consigne dit : si le constat est illisible ou ne désigne pas de cause, ne rien coder et rendre ce rapport. Aucun NR ni correctif n'a été écrit.

## Ce qui a été tenté
- `blackboard_read_zone architecture_rules` : la clé `bug_homeostat_freine_au_lieu_de_liberer_20261022` est absente des 50 faits les plus récents. Les filtres `category=bug` (2 faits) et `category=enquete` (0) ne la renvoient pas.
- Lecture de 90 puis 2000 faits : le résultat dépasse la limite de lecture et est déversé dans un fichier du profil utilisateur. La consigne interdit de lire ce profil, et le bac à sable refuse l'accès (PermissionError).
- `memory search` ne renvoie que la consigne de l'enquête AGY job_618d3404, pas son verdict. Cette consigne dit seulement :
  - le message « THROTTLED: pression RAM/CPU (P1 homeostat) » vient de `app/forge_sandbox_exec.py` (`spawn_as_sandbox`) ;
  - ce code tente une éviction (`_evict`, champ `missing_gb`) avant de freiner ;
  - `_why_no_evict` dit pourquoi l'éviction n'a pas eu lieu ;
  - il existe un « piège déjà payé (17/09) : la liste des reclaimers dépend d… » (texte tronqué).

## Ce qui manque
1. Le texte du constat (cause désignée, état RAM/charge à injecter pour reproduire). Seul le module est connu.
2. La fin de la phrase « la liste des reclaimers dépend d… ».
3. La cause désignée par le constat. Aucun fait lu ne la donne.

## Hypothèse non retenue
Dans `spawn_as_sandbox`, quand `get_active_intents()` signale `chains_active` ou `docker_wanted`, seul `run_reclaimers(_target)` (caches) est appelé. `request_resources` (échelle d'éviction) n'est pas appelé. Le spawn est alors refusé avec « eviction refusee: cognition active ». C'est peut-être le freinage décrit. Je ne l'ai pas codée : sans le constat, rien n'établit que c'est la cause, et le code touche au veto « l'intention est plus forte que la régulation ».

## Pour reprendre
Fournir le texte du fait. Exemple : `blackboard_read_zone` avec une clé ou un filtre qui ne renvoie que ce fait. Le correctif serait alors dans `app/forge_sandbox_exec.py`, avec le NR `tests/nr/test_homeostat_libere_au_lieu_de_freiner_nr.py`.
