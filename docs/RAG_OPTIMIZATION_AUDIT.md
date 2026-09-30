# RAG Optimization Audit
*Inspiré de LEANN, qmd et SPI_VecDB*

## 1. État Actuel de Nokido RAG

### 1.1 Volume et Stockage
Suite à la requête d'audit sur `embeddings.db` :
- **Nombre de chunks indexés** : 534 483
- **Taille moyenne de la chaîne d'embedding (JSON)** : ~9 899 octets
- **Taille totale estimée des vecteurs** : ~5.03 Go uniquement pour les données vectorielles (en format texte/JSON).
- **Structure** : Les embeddings actuels sont très probablement des tableaux de flottants (float32, 768 dimensions), stockés sous forme de chaînes JSON dans SQLite. 

### 1.2 Latence et Performance
Bien que la latence exacte dépende de la requête (actuellement en recherche exhaustive ou similaire sur SQLite), le décodage JSON et le calcul de similarité cosinus sur un demi-million de vecteurs non-compressés en mémoire posent d'importants défis de passage à l'échelle (scalabilité) pour une exécution locale.

---

## 2. Analyse des 3 Approches Inspirantes

### 2.1 LEANN (Graph-based Selective Recomputation)
- **Concept** : Le plus petit index vectoriel. Au lieu de stocker tous les embeddings, LEANN stocke uniquement le graphe de navigation (HNSW/DiskANN) et recalcule les embeddings à la volée ("on-demand") grâce à un élagage préservant le haut degré du graphe (high-degree preserving pruning).
- **Compression/Stockage** : 97% de réduction d'espace (ex: 6Go au lieu de 200Go pour 60M de documents). Les embeddings ne sont physiquement pas stockés, seul le graphe de proximité (format CSR) est conservé.
- **Licence** : MIT
- **Vitesse/Hardware** : CPU/GPU, optimisé pour les environnements à ressources très limitées (PC portables).

### 2.2 qmd (Lightweight Local Search Engine)
- **Concept** : Moteur de recherche local hybride (BM25 + sémantique vectorielle) écrit en Rust. 
- **Techniques** : Implémente la recherche hybride avec expansion de requêtes et reranking (Re-classement). L'architecture privilégie la vitesse et la légèreté sur l'indexation de texte complet (FTS) en combinaison avec les vecteurs.
- **Licence** : MIT / Apache 2.0
- **Vitesse/Hardware** : Très rapide (Rust), adapté pour l'intégration via MCP (déjà prévu dans qmd-mcp).

### 2.3 SPI_VecDB (Semantic Pyramid Indexing)
- **Concept** : Recherche adaptative multi-résolution. Les embeddings sont raffinés à travers plusieurs niveaux (coarse-to-fine). Un contrôleur basé sur l'entropie décide de la profondeur de recherche pour chaque requête.
- **Compression/Stockage** : Utilise des caches de compression INT8 et PQ (Product Quantization) via FAISS ou HNSW.
- **Vitesse/Hardware** : Diminution de latence de 5.7x et 1.8x moins de mémoire requise avec garantie de rappel. Testé sur GPU (RTX 4090 / H100).
- **Licence** : Apache 2.0

---

## 3. Recommandation pour Nokido

**Approche Combinée : Hybride (qmd) + Compression INT8/PQ (SPI_VecDB)**

*Pourquoi cette recommandation ?*
1. **Éviter le "Recompute" pur (LEANN)** : Bien que LEANN soit brillant pour l'économie de stockage (97%), le recalcul à la volée lors des navigations de graphe dépend très fortement de la latence du modèle d'embedding (NPU/CPU). Pour Nokido, l'économie de stockage (5 Go) n'est pas encore critique au point de sacrifier le temps CPU/NPU à chaque recherche.
2. **Hybride Local (qmd)** : L'intégration d'un score BM25 (déjà partiellement en place via `rag_fts` dans Nokido) avec une recherche vectorielle est le meilleur moyen d'augmenter la pertinence sans surcharger le calcul sémantique.
3. **Quantification (SPI_VecDB)** : C'est le point d'action immédiat. Transformer nos JSON floats en blobs INT8 ou PQ (Product Quantization) permettra de diviser la taille de stockage par 4 à 32x. Passer de ~9900 octets/JSON à ~768 octets (float32 en BLOB) voire ~192 octets (int8 en BLOB) libérera massivement la RAM pour le cache OS et SQLite.

---

## 4. Plan de Migration Progressive

La migration doit se faire en douceur (Shadow Mutation / Blue-Green) pour ne pas casser la base existante.

- **Phase 1 : Changement du type de stockage**
  - Modifier le RAG store pour convertir les listes JSON `[0.1, -0.4, ...]` en objets `BLOB` compressés via `numpy.tobytes()` (Float32 pur).
  - *Gain immédiat :* 9900 octets → 3072 octets (division par 3). Vitesse de chargement I/O grandement améliorée.
  
- **Phase 2 : Quantification Scalaire (INT8)**
  - Implémenter une quantification Min-Max ou symétrique pour ramener les 768 dimensions float32 à 768 entiers 8-bits.
  - *Gain :* 3072 octets → 768 octets. SQLite restera extrêmement réactif même pour 1 million de chunks.

- **Phase 3 : Indexation HNSW en mémoire (Faiss/DiskANN)**
  - Brancher l'algorithme HNSW sur les blobs INT8 plutôt qu'un scan cosinus exhaustif en Python (actuellement O(N)). 
  - Déploiement en "Shadow Mode" : le nouvel algorithme tourne en parallèle de l'ancien, et les résultats sont comparés de manière asynchrone avant bascule officielle.

- **Phase 4 : Expansion BM25 (Inspiration qmd)**
  - Consolider la table `rag_fts` existante pour faire du reranking hybride (score vecteur + score FTS).

---

## 5. Métriques Attendues Après Migration

| Métrique | Actuel (JSON Float32) | Après Phase 1 (BLOB Float32) | Après Phase 2 (BLOB INT8) | Après Phase 3 (HNSW + INT8) |
|----------|----------------------|------------------------------|---------------------------|-----------------------------|
| **Stockage par Chunk** | ~9 899 bytes | 3 072 bytes | **768 bytes** | ~800 bytes (avec graphe) |
| **Taille DB (500k chunks)** | ~5.0 Go | ~1.5 Go | **~380 Mo** | ~400 Mo |
| **Latence Query (Brute)** | O(N) Lente, I/O bound | O(N) Moyenne | O(N) Rapide | **O(log N) Ultra-Rapide** |
| **Compatibilité NPU** | N/A | Oui | **Oui (Optimisé)** | Oui |

Cette migration offrira à Nokido les performances de moteurs comme qmd ou SPI_VecDB tout en conservant l'autonomie et l'architecture "Full SQLite" actuelle qui fait sa force.
