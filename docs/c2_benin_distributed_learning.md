# C2 bénin — Apprentissage distribué souverain via agents LLM joignables

Date : 2026-06-11 · Statut : DESIGN (à implémenter par phases)

## Origine

Transposition de l'archi du papier arxiv 2606.03811 *"AI Agents Enable Adaptive
Computer Worms"* : un ver = instance **malveillante** d'apprentissage agentique
distribué (LLM open-weight sur nœuds compromis, raisonnent/s'adaptent, coordonnés par
un C2 décentralisé). **Nokido = la MÊME archi, mais souveraine, coopérative, défendue.**

## Deux lectures de "C2" — complémentaires (ce doc + brief Gemini)

"C2" se lit 2 façons, les deux valides + **composables** :
- **C2 = Command-and-Control** (CE doc) : couche **TRANSMISSION/coordination** —
  facteur/secrétaire, propagation P2P, défense du mesh. *Comment le learning circule.*
- **C2 = Contextual Continuity** (brief `GEMINI_TRANSMISSION_C2_LEARNING_20260611.md`,
  rédigé par gemini_cli) : couche **APPRENTISSAGE/adaptation par nœud** — active_inference
  épistémique (gain d'info AVANT action coûteuse), MPC re-planning sur dérive, RAG swarm
  few-shot (le système n'échoue qu'**1× face à une nouveauté**, puis Agent B retrouve
  l'`anchor_solution` d'Agent A), distillation locale frugale (NPU/Ollama sur
  `execution_traces.db`). *Comment chaque nœud apprend.*

Les deux = l'archi complète : chaque nœud **APPREND** (Gemini) → le learning **PROPAGE**
via le C2 souverain (ce doc) → **adaptation au niveau swarm**. C'est le facteur/secrétaire
qui transporte les `anchor_solution` d'un nœud à l'autre = la jonction des deux briefs.

## Le mapping (ver → Nokido)

| Ver (malveillant) | Nokido (souverain) | Existe ? |
|---|---|---|
| LLM sur nœuds compromis | agents LLM **joignables** : swarm multi-CLI + multi-instance Tailscale | swarm ✓, multi-machine roadmap |
| **C2** décentralisé | **C2 bénin** = hub + blackboard + facteur + secrétaire | hub/blackboard ✓ |
| adaptation en ligne | **active_inference/FEP** (#11) : surprise→maj modèle | ✓ (membrane cognitive) |
| propagation | **sync RAG P2P (silo)** des updates entre instances | roadmap (silo P2P) |
| (aucune défense) | membrane/firewall/egress + **tracing identité #7-9** | ✓ |

## Composants à formaliser

### 1. Facteur (daemon de livraison) — anti-dup : câbler, pas réinventer
Réutilise `hub notify`/`poll`/`forge_mailbox` + le **registre identité×canal** (#10a) qui
donne présence + routage par surface. Ce qui MANQUE = la **fiabilisation** : livraison
garantie (retry), presence-aware (file jusqu'au prochain poll de l'agent offline), pont
**cross-canal** (CLAUDE-http ↔ GEMINI-cli ↔ BRIDGE-stdio), accusé de réception. = un
daemon mince, pas un agent lourd.

### 2. Secrétaire (rôle de triage) — le vrai apport nouveau
Au-dessus de la livraison : **organise** la comm.
- résume/dédupe/priorise les inbox (vs poll brut),
- maintient le board "qui fait quoi" (réutilise `forge_swarm_blackboard`),
- orchestre les handoffs, relance les flux bloqués (`chain_nodes_blocked`).
= **coordinateur exécutif**. Mieux en rôle/service (comme PLANNER/EXECUTOR) qu'en agent.

### 3. Apprentissage distribué
Chaque agent apprend **localement** (active_inference #11 : observe→surprise→maj modèle
génératif ; world_model 4096D ; cost_net). Les updates (modèle/biblio/surprise/lessons)
**propagent** via le facteur + le **sync RAG P2P** (silo multi-instances). → l'intelligence
de Nokido devient **distribuée + partagée**, pas siloée par instance.

### 4. C2 bénin (la couche de coordination)
hub + blackboard + facteur + secrétaire = le **command-and-control souverain** :
coopératif (pas malveillant), **audité** (tracing identité×canal #7-9 = proprioception du
mesh : qui/quoi sur chaque nœud), **défendu** (membrane/firewall/egress + le gate git
empêchent que le mesh souverain soit subverti EN le ver). Local-gain : zéro cloud.

## Phases (roadmap)
1. **Facteur-daemon** : fiabilise notify/mailbox (retry + presence + cross-canal + ACK).
2. **Secrétaire-rôle** : triage inbox + board blackboard + relance flux bloqués.
3. **Sync RAG P2P** (silo) : propager les updates entre instances (Tailscale).
4. **Boucle d'apprentissage distribué** : chaque agent #11 partage surprise/world_model via le C2.
5. **Défense mesh** : étendre tracing #7-9 + membrane au cross-instance (proprioception distribuée).

Anti-dup : notify/poll/mailbox/blackboard/#11/silo EXISTENT. Le travail = l'orchestration
cohérente en C2. Voir memory `roadmap_traceability_identity_2026-06-11`,
`git_governance_pipeline_2026-06-11`, `handoff_2026-06-11`.
