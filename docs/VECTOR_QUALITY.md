# QUALITÉ BASE VECTORIELLE NOKIDO — Référence 2026
## Sources
- Vespa "Embedding Tradeoffs Quantified" (2026-01)
- Milvus "Best Embedding Model for RAG 2026" (2026-03)
- Azure AI "Vector Compression up to 92.5%" (2025-04)
- Firecrawl "Best Chunking Strategies RAG 2026"
- arXiv SSRAG Hybrid RAG (2026-01)

## Problèmes identifiés et corrigés

### 1. Vecteurs JSON bytes (CRITIQUE — corrigé)
- **Bug**: 7448 vecteurs stockés en `json.dumps(list).encode()` au lieu de `np.tobytes()`
- **Impact**: 0% participation au cosine search (frombuffer échouait silencieusement)
- **Fix**: Conversion JSON list → float32.tobytes() en une passe
- **Leçon**: Toujours stocker embedding = `np.array(v, dtype=np.float32).tobytes()`

### 2. Incohérence dimensionnelle (corrigé)
- **Bug**: Mix MiniLM dim=384 + bge-m3 dim=1024 dans la même table
- **Impact**: Cosine cross-dim = nonsense (comparaison de vecteurs incompatibles)
- **Fix**: Effacer les dim=384, re-vectoriser en bge-m3 1024d
- **Leçon**: Une seule dimension par base. Si migration, tout re-vectoriser.

### 3. Score qualité chunk (ajouté)
Heuristique sans LLM (3s pour 16k chunks) :
```python
score = (len_score * 0.4      # 200-1200 chars optimal
       + unique_ratio * 0.4   # mots uniques / total
       + structure * 0.2      # code, headers, listes
       - boilerplate * 0.3    # répétitions, points
       - title_only * 0.3)    # chunk = juste un titre
```

## Recommandations 2026 (sources)

### Matryoshka / Truncation
- bge-m3 **n'est PAS MRL** → tronquer 1024→512 = -15% MTEB quality
- Modèles MRL: Voyage 3.5, Jina v4, OpenAI text-3-large → troncature safe
- **Pour Nokido**: garder bge-m3 1024d, ne pas tronquer

### int8 Quantization
- 4x réduction espace, ~1% perte MTEB (Vespa 2026)
- SQLite: stocker en BLOB int8 + normaliser au search
- **Gain potentiel Nokido**: 12k chunks × 1024 × 4 bytes = 49MB → 12MB
- **Priorité**: faible (disque non critique ici)

### Chunking optimal (production 2026)
- Optimal: 200-800 chars, overlap 10-15%
- Semantic chunking > fixed-size pour les documents techniques
- Contextual prefix `[domain:source]` = +8% retrieval quality (validé Nokido)
- **Chunks > 4000 chars**: re-chunker obligatoire (chunks réseau apprendre_python3)

### Déduplication sémantique
- Seuil recommandé: cosine > **0.97** (0.92 trop agressif pour textes techniques)
- Méthode: greedy set cover par batch de 500, domain par domain
- **Résultat Nokido**: 0 doublons sur nokido_code (code déjà bien découpé)

### Filtres qualité production (Modern RAG 2026)
1. Supprimer chunks score < 0.1 (bruit pur)
2. Filtrer par domain lors du search (éviter beir_* dans les résultats Nokido)
3. Utiliser quality_score dans le RRF final (boost aux chunks score > 0.7)

## État actuel Nokido (2026-04-26)
```
Total chunks utiles: 16,000
  float32 bge-m3 1024d: 12,423 (77%)
  En cours re-vectorisation: 3,577
  quality_score moyen: 0.692
  Chunks score >= 0.6: 12,218 (76%)
```
