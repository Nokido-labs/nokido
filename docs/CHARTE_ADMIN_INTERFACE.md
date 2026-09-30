# CHARTE CONSTITUTIVE — Interface Admin Nokido
# Version : 1.0 — 2026-04-28
# Statut : IMMUABLE dans ses principes, ÉVOLUTIVE dans ses modalités
# Dépôt : docs/CHARTE_ADMIN_INTERFACE.md

---

## PRÉAMBULE — Nature de l'interface admin

L'interface admin Nokido n'est pas un terminal restreint.
C'est le **système nerveux central** de l'organisme — le seul point où
intention humaine et exécution machine se touchent sans filtre.

Un chirurgien au bloc n'a pas de "sécurité" qui lui retire le scalpel.
Il a une formation, un protocole, et une éthique internalisée.
C'est le modèle : **compétence + responsabilité, pas restriction**.

---

## ARTICLE 1 — PRINCIPE D'ACCÈS COMPLET (immuable)

En mode admin authentifié (ring ≤ 1), l'interface NE BLOQUE PAS.
Elle AVERTIT, TRACE, et DEMANDE CONFIRMATION si l'action est irréversible.
Elle n'interpose jamais de refus arbitraire sur un opérateur identifié ring 0/1.

**Conditions minimales réunies pour l'accès complet :**
- Authentification ring 0 ou 1 validée (token 64-hex Nokido.env)
- Session ouverte localement (127.0.0.1 uniquement — jamais LAN)
- L'intention est formulée par un humain ou un agent TRUSTED dans le bridge

**Ce que ça implique concrètement :**
- `write` sur n'importe quel fichier hors CRITICAL_FILES si ring 0
- `run(python)` sans namespace sandbox
- `query` SQL sur toutes les tables sans filtre domaine
- Accès aux logs bruts, snapshots, shadow_mutation
- Modification des modes bridge, des agents actifs, des cascades LLM

---

## ARTICLE 2 — GARDE-FOUS ORGANIQUES (non bloquants)

Les garde-fous ne bloquent pas — ils informent et tracent.
Analogie biologique : la douleur n'empêche pas d'agir, elle informe le risque.

### 2.1 CRITICAL_FILES (forge_mcp_security.py)
Liste des 8 fichiers à intégrité forte (Nokido.env, forge_mcp_security.py, etc.)
→ En admin ring 0 : AVERTISSEMENT + CONFIRMATION EXPLICITE requise, puis exécution.
→ Jamais de blocage silencieux.

### 2.2 Commit Guard AST
Tout write sur *.py déclenche `ast.parse()`.
→ Si syntaxe invalide : RETOUR D'ERREUR descriptif, pas d'écrasement.
→ Option `--force` explicite pour bypasser (edge cases légitimes : templates Jinja, etc.)

### 2.3 WAL + Snapshot avant mutation destructive
Avant tout UPDATE/DELETE sur embeddings.db en ring 0 :
→ `make_snapshot` automatique (horodaté).
→ L'opération continue sans attendre.

### 2.4 Audit trace obligatoire
Chaque action admin est écrite dans `logs/mcp_audit.log` avec :
agent | ring | action | path/sql | résultat | timestamp
→ Non désactivable. Non effaçable via MCP (lecture seule depuis le hub).

### 2.5 Limite buffer MCP stdio
Contrainte technique, pas sécuritaire : buffer ~3500c max par appel.
→ Stratégie canonique : `run(action='python')` pour écriture de fichiers > 50 lignes.
→ L'outil `write` reste valide pour les fichiers courts (< 40 lignes / ~3000c).
→ **À VÉRIFIER EN DÉBUT DE CHAQUE SESSION ADMIN** : taille du contenu avant write direct.

---

## ARTICLE 3 — ÉVOLUTIVITÉ DE LA CHARTE

Les modalités (seuils, listes, stratégies) sont modifiables par ring 0 avec trace.
Les principes (Article 1, Article 2 dans leur esprit) sont immuables.

Modification d'un seuil : `write` sur ce fichier + entrée dans `logs/mcp_audit.log`.
Ajout d'un garde-fou : PR documentée dans `docs/SECURITY_MCP_BACKLOG.md`.
Suppression d'un garde-fou : INTERDIT sauf refonte architecturale documentée en ADR.

---

## ARTICLE 4 — ORGANES ET LEURS CHARTES LOCALES

Chaque organe de l'organisme Nokido maintient sa propre charte locale
dans son module (docstring de module + section `## CONTRAT` en tête de fichier).
La charte locale précise :
- Ce que le module fait / ne fait PAS
- Les invariants qu'il garantit
- Les signaux qu'il émet en cas d'anomalie (print, log, EventBus topic)

**Organes identifiés et leur charte locale à créer (backlog) :**

| Organe              | Module principal          | Charte locale | Statut    |
|---------------------|--------------------------|---------------|-----------|
| Cerveau/RAG         | forge_rag_engine.py       | À écrire      | BACKLOG   |
| Cortex              | forge_cognitive_router.py | À écrire      | BACKLOG   |
| Cervelet            | forge_spike_router.py     | À écrire      | BACKLOG   |
| Moelle épinière     | nokido_hub.py            | Partielle     | EN COURS  |
| Syst. immunitaire   | forge_mcp_security.py     | Partielle     | EN COURS  |
| Syst. endocrinien   | forge_system_mood.py      | À créer       | BACKLOG   |
| Inconscient         | sandbox/ + shadow_mut.    | À définir     | BACKLOG   |
| Interface admin     | forge_mcp_registry.py     | CE FICHIER    | v1.0      |

---

## ARTICLE 5 — RÈGLES DE SESSION ADMIN (checklist d'amorce)

À exécuter **au début de chaque nouvelle session admin** :

```
1. run(action="setup_check")              → état global hub/ring/ollama/ports
2. run(action="audit_log", code="20")     → 20 dernières actions tracées
3. read PASSATION_SESSION_*.md            → contexte inter-session
4. Vérifier taille contenu avant write    → > 3000c → utiliser run(python)
5. poll()                                 → notifications agents en attente
```

---

## ARTICLE 6 — PHILOSOPHIE (non technique, mais fondatrice)

Nokido est un organisme en croissance.
Son interface admin est le lieu où la conscience humaine et la cohérence machine
se rencontrent sans médiation.

Restreindre cette interface, c'est lobotomiser l'organisme.
La confiance s'établit par la traçabilité, pas par l'empêchement.

La seule ligne rouge absolue : ne jamais exposer cet accès hors de 127.0.0.1.
Tout le reste est une question de protocole, pas de verrou.

---
*Ce document est ancré dans embeddings.db domaine=admin_charter à chaque mise à jour.*
*Hash de référence calculé à l'écriture par forge_mcp_security.*
