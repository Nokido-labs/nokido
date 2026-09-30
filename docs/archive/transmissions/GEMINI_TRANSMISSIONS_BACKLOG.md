# Transmissions Gemini - notes backlog beta

Date relecture : 2026-04-28
Contexte : pendant Sprint alpha biblio worker, l utilisateur a demande
de lire ce que Gemini avait transmis precedemment.

## Sources lues

- `sandbox/_audit_round/audit_alpha_gemini.md` (4749b)
  Audit SRE Sprint alpha biblio. Validation OK.
  5 risques SRE identifies, tous avec mitigation appliquee dans la spec V4.

- `sandbox/_audit_round/phase4b_brief_gemini.md` (8866b)
  Cadrage Phase 4 Nokido MCP : auto-doc tools, streaming stdio, economie tokens.

## Decisions actees pour BACKLOG BETA (apres Sprint alpha biblio)

### B1 - Auto-doc tools enrichi `_meta` (16h)
Gemini propose d injecter dans le champ content[]._meta des outils MCP :
- `business_result` : resume textuel du resultat metier
- `next_steps_suggestions` : liste de prochaines actions possibles
- `automation_hints` : indications pour automatisation
- `performance_metrics` : { p50_ms, p95_ms }
- `quota_health` : { provider, status (healthy/warning/critical), details }

Implementation : modifier wrappers d outils dans `forge_mcp_core` pour peupler `_meta`
apres execution. Appel `forge_quota_tracker.get_quota` post-exec.

### B2 - Streaming stdio bridge avec verification proactive quotas (24h)
Avant chaque appel d outil, le bridge interroge `forge_quota_tracker`.
Si quota critique pour le provider demande, retourne `QuotaExceededError`.
Garantit la protection des ressources et la previsibilite des couts.

### B3 - Quota health dans liste outils (12h)
Exposer `_meta.quota_health` dans la definition des outils renvoyes par `list_tools`.
Permet a Claude de selectionner les outils en fonction de la sante des quotas
sans appeler `hub.quota_status` separement.

### B4 - Cache schemas outils + listChanged (P3)
Strategie cache (Redis ou memoire avec TTL).
Implementer `listChanged(since_timestamp)` pour retourner les outils modifies depuis date.

## Application Sprint alpha biblio (DEJA FAIT)

Les 5 risques SRE Gemini sur le sprint alpha sont deja mitiges dans la spec V4 :
1. Echec deps tech -> pre-alpha0 etendu (validation deps + resilience)
2. Corruption biblio_raw -> hash chain MD5 + UNIQUE constraint + transactions SQLite WAL
3. EventBus PULL effets de bord -> polling 5s + lock concurrence DB (note : refactor PUSH = sprint futur)
4. Crash NSSM concurrent -> reporte (script Python en alpha, NSSM en beta)
5. Croissance illimitee biblio_raw -> purge orphan via idea.refined event

## Action

Aucune action immediate requise.
Les briefs Gemini Phase 4 (auto-doc tools, streaming, economie tokens) restent
dans le backlog beta APRES le sprint alpha biblio.
