# AUDIT ET MODÈLE UNIFIÉ DE L'ÉTAT MÉMOIRE (01/09/2026)

Cet audit évalue les représentations actuelles de l'état d'une mémoire dans Nokido (disponibilité, confiance, obsolescence, usage, relations) et propose un modèle unifié basé *exclusivement* sur ce qui est mesurable et alimenté.

## 1. OBSERVED (Cartographie de l'existant)

L'état d'une mémoire dans Nokido est actuellement dispersé sur plusieurs organes, avec une fracture nette entre les états *théoriques* (colonnes SQL vides) et les états *réels* (dérivés ou JSON).

### 1.1 `rag_chunks` (Le stockage théorique)
Une mesure par échantillonnage (20 000 chunks) révèle que la majorité des colonnes descriptives sont **vides ou sans variance** :
- `embedding_model` : **VIDE** (0/20 000).
- `hash` : **VIDE** (1/20 000).
- `quality_score` : **VIDE** (0/20 000).
- `epistemic_weight` : **SANS VARIANCE** (20 000/20 000 portent la valeur par défaut `0.5`).
- `superseded_by` : **VIDE** (0/20 000).
- `active` : **SANS VARIANCE** (20 000/20 000 portent la valeur `1`).
- `retraction_status` : **VIDE** (0/20 000).
- `last_validated_at` : **VIDE** (0/20 000).
- `access_count` : **QUASI-VIDE** (2/20 000 > 0).

*Preuve* : L'échantillon SQLite confirme que ces colonnes n'ont aucun émetteur actif dans l'architecture actuelle. Un taux de remplissage de 100% sur `epistemic_weight` ou `active` avec une variance nulle n'apporte aucune information discriminante.

En revanche, la colonne `meta` (JSON) est **ALIMENTÉE** (par `forge_rag_qualify.py`) et porte les vrais états de qualification : `trust_score`, `consensus_level`, `ring`.

### 1.2 `forge_memory_availability.py` (Disponibilité par canal)
- États : `AVAILABLE`, `PENDING`, `REFUSED_BY_POLICY`, `UNKNOWN`.
- **ALIMENTÉ** de manière dynamique : calculé à la volée via la présence du vecteur et le trigger `forge_tier_guard`.
- L'état n'est pas stocké, il est projeté. L'état `FAILED` est volontairement absent car aucun émetteur ne le distingue.

### 1.3 `forge_memoire_active.py` (Provenance et Obsolescence des dettes)
- États : `[OUVERT]`, `[CLOS]`, Âge.
- **ALIMENTÉ** sous forme de texte brut dans le *blackboard* (zone `active_bugs`).
- L'âge (la chronicité) est extrait du texte (`depuis=AAAA-MM-JJ`).

### 1.4 `forge_hebbian_linker.py` (Relations et topologie)
- États : `weight`, `kind`.
- **ALIMENTÉ** par co-activation (topics, ideas, search) dans la table `biblio_link`.
- La variance est mesurable : les poids décrivent une décroissance (`decay`) active.


## 2. PROPOSED (Modèle Unifié)

Le modèle proposé élimine le faux raffinement des colonnes SQL vides pour embrasser le paradigme qui fonctionne déjà dans Nokido : **La donnée sait ce qu'elle est (Meta JSON), l'état est dérivé au besoin (Availability), et les liens vivent à part (Hebbian).**

**Mapping Actuel -> Proposé (Champ par champ) :**

| Entité Cognitive | Représentation Actuelle | Représentation Proposée |
| :--- | :--- | :--- |
| **Disponibilité** | Dynamique (`forge_memory_availability.py`) | **MAINTENUE**. Reste dynamique, ne rejoint aucune table. |
| **Confiance (Trust)** | `meta.trust_score`, `meta.consensus_level` | **MAINTENUE**. La qualification JSON est la source de vérité. |
| **Autorité Lexicale** | `rag_chunks.epistemic_weight` (Défaut 0.5) | **SUPPRIMÉE**. Remplacée par `meta.trust_score` et `trust_weight()`. |
| **Obsolescence** | `rag_chunks.superseded_by`, `retraction_status` | **SUPPRIMÉES**. À migrer dans `meta` le jour où un émetteur existera. |
| **Activation** | `rag_chunks.active` (Toujours 1) | **SUPPRIMÉE**. Un chunk inactif doit être supprimé de l'index. |
| **Usage** | `rag_chunks.access_count`, `last_validated_at` | **SUPPRIMÉES**. |
| **Provenance Vectorielle**| `rag_chunks.embedding_model`, `hash` | **SUPPRIMÉES**. |
| **Relations** | `biblio_link.weight` (Hebbian decay) | **MAINTENUE**. La topologie reste déportée. |
| **Dettes (Working Mem)** | Texte (`[OUVERT ... depuis=...]`) dans blackboard | **MAINTENUE**. |


## 3. PROVEN (Ce qui fonctionne)

1. **La projection d'état (Disponibilité) :** Ne pas stocker `PENDING` ou `REFUSED_BY_POLICY` en base garantit que l'état reflète toujours la politique d'ingestion (Tier Guard) sans décalage. *Preuve : `app/forge_memory_availability.py` tourne en production et le routeur ne pénalise pas ce qui est refusé.*
2. **Le Meta JSON (Qualification) :** L'approche de `forge_rag_qualify.py` (ring, consensus, trust_score) permet des migrations rétroactives et une qualification découplée du stockage SQL strict. *Preuve : L'enrichissement MCP fonctionne et alimente la pondération via `apply_trust_weight`.*
3. **La plasticité Hebbian :** Le stockage externe dans `biblio_link` avec un *decay* permet une topologie fluide. *Preuve : Le daemon met à jour les poids en continu.*


## 4. NOT_PROVEN (Ce qui échoue)

Les 9 colonnes SQL dédiées au schéma cognitif dans `rag_chunks` :
`embedding_model`, `hash`, `quality_score`, `epistemic_weight`, `superseded_by`, `active`, `retraction_status`, `access_count`, `last_validated_at`.

*Absence de preuve :* L'échantillonnage de 20 000 chunks démontre soit un vide total (0/20 000), soit une absence stricte de variance (tous à `1` ou `0.5`). Sans émetteur dédié pour écrire ou incrémenter ces valeurs, elles constituent de la dette architecturale ("garde branché sur un signal que personne n'émet").


## 5. CHANGES_REQUESTED (Actions requises)

1. **Élagage SQL :** Prévoir une migration SQLite (`ALTER TABLE DROP COLUMN` ou recréation) pour supprimer les 9 colonnes mortes de `rag_chunks`.
2. **Standardisation JSON :** Confirmer `meta` (JSON) comme l'unique conteneur de qualification intrinsèque pour tout futur état cognitif (ex: si l'on veut réintroduire un indicateur d'obsolescence, il devra naître dans `meta`).
3. **Verrouillage de l'Availability :** Sanctuariser l'absence de l'état `FAILED` dans `forge_memory_availability.py` tant qu'aucun worker ne capture et ne stocke explicitement les erreurs d'embedding.
