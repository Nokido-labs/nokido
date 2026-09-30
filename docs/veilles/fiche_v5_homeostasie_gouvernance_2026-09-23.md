# Fiche de sortie — Veille V5 « Homéostasie cybernétique · quotas · gouvernance MCP · A2A » (2026-09-23)

Contrat : PATTERNS → NOKIDO_EXISTING → EVIDENCE → GAPS → MINIMAL_EXPERIMENT → NR → DECISION. Pipeline B.
Interroge V1 (supervision), V4 (reprise), et les MESURES du jour (RAM, disque, WAL).

## 1. PATTERNS (`watch:homeostasie:%`, `watch:ressources:%`, `watch:mcp_gouvernance:%`, `watch:m2m:%`)

| Pattern | Source |
|---|---|
| **MAPE-K** : Monitor → Analyze → Plan → Execute sur une Knowledge partagée (autonomic computing) | Wikipedia Autonomic computing (IBM) |
| Boucle de rétroaction ; systèmes viables à 5 niveaux de régulation (VSM) ; homéostasie = variables maintenues dans une plage | Cybernétique, VSM (Beer), Homeostasis |
| **Réconciliation** : un contrôleur compare l'état DÉSIRÉ à l'état RÉEL et agit sur l'écart, en boucle | Kubernetes controller |
| **Éviction sous pression** par seuils (mémoire, disque) et classes de priorité ; préemption | Kubernetes node-pressure eviction, priority/preemption |
| **Délestage** : refuser tôt ce qu'on ne pourra pas servir ; les reprises aggravent la surcharge | AWS délestage (FR) |
| **Limites de concurrence adaptatives** (mesurer la latence, ajuster la limite) | Netflix concurrency-limits |
| Quotas de ressources par espace | Kubernetes resource quotas |
| MCP : consentement, moindre privilège, confused deputy, jetons non transmis ; gateways de politique | MCP security best practices ; gateways MCP 2026 ; OWASP LLM Top 10 |
| Découverte d'agents par carte (Agent Card) | A2A agent discovery ; ACP |

## 2. NOKIDO_EXISTING

- Monitor : sondes de santé, `forge_health_diagnostic.run_cycle`, `forge_endpoint_monitor`, proprioception,
  capteur SNN des vitals (armable, `sandbox/snn.wanted`), système endocrinien (hormones, signaux).
- Analyze/Plan : `self_improvement_watch` (742 tirs), `remediation_cycle`, circadien (phases, NREM/REM).
- Execute : `request_resources` (échelle : caches → Ollama LRU → llama → services évinçables → docker → pilier en
  détresse) ; admission `run_job` (refus « embolie RAM ») ; caps RSS ; priorités I/O + mémoire (23/09).
- Réconciliation : `services.toml` + `supervisor.ts` (état déclaré des services), intentions `*.wanted` (TTL).
- Gouvernance outils : RBAC par rings, `forge_tool_gate`, `hook_capability_gate`, `hook_recon_first`, firewall
  sémantique, membrane souveraine ; `governed_edit`. A2A/ACP : `tools/forge_a2a_server.py` (fonction `admission`),
  verdict du 17/09 : pas de 3e protocole ; ROADMAP NEXT : autopsie runtime ACP/A2A.

## 3. EVIDENCE (mesures du jour)

| Élément | Niveau |
|---|---|
| Admission RAM refusant un job à 84-90 % | **MEASURED** (3 refus aujourd'hui) |
| `request_resources` | **MEASURED** : 4 appels → `noop` (rien d'évinçable, il manquait 0,92 Go) — l'échelle existe, ses leviers étaient vides |
| Garde disque (V: < 30 Gio → arrêt) | **VERIFIED** (arrêt propre rc=5) … mais **contourné** entre deux contrôles (V: à 3,1 Gio) → corrigé (contrôle pendant le dépôt, `ff0065762`) |
| Rétroaction « lecteur long → WAL 48 Go » | **non régulée** : aucun capteur, libéré par un redémarrage MANUEL |
| Gouvernance outils (gates, hooks) | **VERIFIED** (7 arrêts justifiés aujourd'hui : bash_guard, recon_first ×3, classifieur de suppression, firewall sur deux motifs de code dans du texte) |
| Boucle Plan→Execute autonome | **absente** : `forge_proposal_applier` non câblé + désarmé (22/09) ; *observer ≠ réparer* |

## 4. GAPS

1. **La boucle MAPE-K est ouverte** : M et A existent et tournent ; P→E n'est pas fermé (applicateur désarmé).
2. **Variables essentielles sans consigne** : RAM a une consigne (admission), le disque V: une consigne (30 Gio) ; le
   **WAL** n'en a pas (taille, âge du plus vieux lecteur) → la variable qui a failli tout arrêter n'est pas régulée.
3. **Échelle d'éviction à vide** : aujourd'hui aucun levier ne s'appliquait (pression diffuse, 80+ processus) ; pas
   de délestage côté DEMANDE (refuser de nouveaux jobs lourds tant que la pression dure) autre que l'admission.
4. Gouvernance MCP : RBAC/gates forts ; pas vérifié ici contre la liste « MCP security best practices » (confused
   deputy, passage de jetons) → audit à faire.
5. Faux positifs du firewall sur du TEXTE (fiches, NR) citant des motifs de code : coût mesuré 3 fois aujourd'hui.

## 5. MINIMAL_EXPERIMENT (observation seule — « observer avant d'enforcer »)

Capteur WAL non bloquant : taille du WAL + nombre de checkpoints busy consécutifs + âge → signal endocrine
(`STALE` ≠ `DEAD`), journalisé 24 h, AUCUNE action. Objectif : la distribution réelle avant tout seuil.

## 6. NR

`test_capteur_wal_signal_sans_action_nr` : WAL simulé > seuil + checkpoints busy ⇒ signal émis, 0 action ;
WAL sain ⇒ aucun signal (pas de faux positif).

## 7. DECISION

- **CONSERVER** admission, garde disque, gates (VERIFIED).
- **COMPLÉTER** : variable WAL régulée (d'abord observée) ; délestage côté demande.
- **NE PAS** fermer la boucle P→E ici : c'est l'armement de `forge_proposal_applier`, geste owner.
- UNKNOWN : conformité MCP aux bonnes pratiques de sécurité (audit) ; état runtime A2A/ACP (ROADMAP NEXT).
- Contradiction : aucune ; V5 relie V1 (supervision) et V4 (reprise) à une même boucle MAPE-K dont P→E est le maillon absent.
