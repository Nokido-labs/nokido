# Knowledge Pack — distribuer la DB RAG efficacement

`RAG/embeddings.db` ≈ **16 GB** (float32) — trop gros pour git/GitHub (fichier 100 MB,
release-asset 2 GB, LFS quota). On ne distribue **pas** la DB brute. Modèle souverain :
**GitHub ship la SOURCE + un petit pack quantifié ; les vecteurs restent/se recalculent
en local.**

Outil : `tools/forge_knowledge_pack.py`.

## Le pack
- Corpus vectorisé réel = **les chunks avec `rag_chunks.embedding` non-null** (~**29.7k**
  sur 689k lignes ; le reste = froid/FTS-only). (La table `embeddings` = embeddings de
  *fichiers*, pas les chunks — ne pas confondre.)
- Quantization **float32 → int8** (scale par-vecteur) → **~83 MB** (1024D, 29.7k chunks
  + texte). Compressible ~45 MB (gzip, le texte compresse bien).

## Commandes
```
# Export (build le pack)
LAFORGE_PYTHON tools/forge_knowledge_pack.py --export nokido_kp_v0.1.db
# (--domain <d> pour un sous-ensemble ; défaut = tous les chunks embeddés)

# Import (charge un pack dans embeddings.db : dequant int8 -> float32)
LAFORGE_PYTHON tools/forge_knowledge_pack.py --import nokido_kp_v0.1.db

# Rebuild from source (re-embed code+docs en LOCAL via forge_rag_warmup, zéro egress)
LAFORGE_PYTHON tools/forge_knowledge_pack.py --rebuild
```
Format pack (sqlite) : `kp_chunks(id,text,domain,scale,vec int8)` + `kp_meta(k,v)`
(`version=0.1`, `dim=1024`, `count`, `domain`).

## Distribution — branche + Release v0.1
Le pack = **asset de Release** (n'alourdit pas l'historique git), tag **`v0.1`**.

⚠️ **Gotcha** : pousser une **nouvelle branche** déclenche un scan full-tree du gate
egress souverain → **bloqué** sur l'entropie des bundles minifiés vendored
(`babel.min.js`, `tailwind.min.js`, `fonts.css` = faux positifs). Deux options :
1. **Branche orphan** dédiée (sans les vendored) : `git checkout --orphan knowledge-pack`
   → n'inclure que `tools/forge_knowledge_pack.py` + ce doc → push (scan propre).
2. **Whitelister** les bundles vendored dans le gate git-egress.

Recette release (session user, `gh` authentifié) :
```
gh release create v0.1 \
  --title "Nokido Knowledge Pack v0.1" \
  --notes "Pack RAG quantifié int8 (29.7k chunks, 1024D). Import: forge_knowledge_pack.py --import" \
  --target <branche> \
  "C:/tmp/nokido_kp_v0.1.db"
```
(L'asset 83 MB s'upload côté user : `gh` utilise son auth de profil ; le tier hub ne
voit pas cet auth — même frontière profil que partout ailleurs cette session.)

## Récap
| Voie | Taille | Verdict |
|---|---|---|
| DB brute en git | 16 GB | ❌ infeasible |
| Pack int8 (Release asset) | 83 MB (~45 compressé) | ✅ |
| Rebuild from source (local) | ~0 transfert | ✅ le plus souverain |
