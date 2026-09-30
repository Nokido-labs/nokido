# Architecture d'Identité des Agents Nokido (AIP & WIMSE)

**Date :** 2026-06-16
**Statut :** Validé / Actif

## 1. Contexte & Alignement Industriel
Afin de garantir un système souverain robuste, auditable et sécurisé (Zero-Trust), Nokido s'aligne sur les brouillons de l'IETF concernant l'identification Machine-to-Machine. 
L'utilisation du préfixe `X-` pour les en-têtes personnalisés est strictement dépréciée (conformément à la RFC 6648).

## 2. En-têtes HTTP Standards (Trafic Intra-Swarm)
Désormais, tout agent, processus détaché ou CLI (Claude, Gemini, scripts Python) communiquant avec le Hub Nokido (`127.0.0.1:8766`) ou un service MCP externe doit respecter cette sémantique :

*   `User-Agent`: Surcharge obligatoire spécifiant l'écosystème, l'agent et le rôle.
    *   *Exemple :* `User-Agent: LaForge-Swarm/1.0 (Agent: claude-desktop; Role: Coder)`
> **MAJ 2026-06-16 (RFC 6648 stricte, validé user) :** les en-têtes custom sont **ORG-SCOPÉS**
> (préfixe `Nokido-`, PAS `X-`) — RFC 6648 §3 recommande d'incorporer le nom de l'organisation
> (« the parameter name could incorporate the organization's name ») pour éviter toute collision
> avec une future standardisation IETF de `Agent-*` (probable vu WIMSE/AIP). Le hub accepte en
> transition les fallbacks `Agent-Name` (interim) puis `X-Agent-Name` (legacy).

*   `LaForge-Agent-Name`: L'identifiant absolu et unique de l'instance.
    *   *Exemple :* `LaForge-Agent-Name: claude-transient-02`
*   `LaForge-Task-ID`: L'identifiant de la session ou de la tâche courante (indispensable pour le traçage RAG).
    *   *Exemple :* `LaForge-Task-ID: req-8f4a-2b1c`
*   `LaForge-Agent-Purpose`: L'intention de l'appel pour le filtrage du pare-feu sémantique.
    *   *Exemple :* `LaForge-Agent-Purpose: code-audit`
*   `User-Agent`: en-tête **standard** (pas custom → pas de préfixe), valeur structurée (cf §ci-dessus).

### 2.1 Définition formelle (modèle RFC 5064) — ABNF (RFC 5234)
```
LaForge-Agent-Name    = "LaForge-Agent-Name:"    SP token   ; instance unique, cardinalité = 1
LaForge-Task-ID       = "LaForge-Task-ID:"       SP token   ; session/tâche, cardinalité 0..1
LaForge-Agent-Purpose = "LaForge-Agent-Purpose:" SP token   ; intention firewall, cardinalité 0..1
token                 = 1*tchar                              ; RFC 7230 §3.2.6
```
Sémantique : 1 valeur par en-tête (jamais de liste). Statut IANA : **non enregistré** (usage privé
intra-swarm) — conforme RFC 6648 (pas de `X-`) + esprit RFC 4288/7595 (namespacing org `Nokido-`,
arbre vendeur `vnd.`/`prs.` transposé aux en-têtes HTTP).

## 3. Identité OAuth et WIMSE (Workload Identity)
En accord avec le draft *WIMSE* (Workload Identity in Multi Server Environments), les agents exécutant des opérations asynchrones (comme des accès GitHub via OAuth) doivent implémenter le concept de **Dual-Identity Credentials**.
Lors de la délégation, le contexte d'exécution doit prouver l'approbation de l'utilisateur humain (`user`) ET l'identité du logiciel agentique. C'est la base de la résolution du problème de Mutex OAuth rencontré le 2026-06-15.

## 4. Sécurité et Découverte (Protocoles Futurs)
*   **AIP (Agent Identity Protocol) :** À moyen terme, les requêtes d'outils sortantes devront être signées par une clé privée asymétrique éphémère détenue par l'agent, vérifiable par le `SkillGuardian`.
*   **Schéma URI de découverte (RFC 4395/7595) :** ❌ PAS `agent://` — RFC 7595 proscrit les noms de schéma « very general purpose » (collision IETF), impose le **lowercase**, et recommande pour un schéma privé un préfixe org/reverse-domain. → schéma souverain = **`web+nokido:`** (préfixe `web+` dédié aux apps web, RFC 7595) OU `nokido:` en **registration PROVISIONNELLE** IANA (nom lowercase + contact + **analyse sécurité obligatoire** + syntaxe conforme `absolute-URI`, RFC 3986).
*   **Manifeste de découverte :** `/.well-known/laforge-agent.json` (well-known URI suffix, RFC 8615 — évite la collision du générique `agent.json`).