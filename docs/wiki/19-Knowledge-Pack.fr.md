---
type: guide
title: 19 — Knowledge Pack
status: draft
resource: repo://docs/wiki/19-Knowledge-Pack.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 19 — Knowledge Pack

<!-- revu-le: 2026-10-07 -->
> Mise à jour : 2026-10-07

> 🌐 [English](19-Knowledge-Pack.md) · **Français**

> **État (2026-10-07)** : les outils d'export / import fonctionnent sur un fichier local et le
> constructeur de release produit désormais le pack ; **aucun pack n'a encore été publié**
> (aucune GitHub Release n'en porte).

Le **Nokido Knowledge Pack** est un instantané optionnel, pré-vectorisé, des chunks du code
source de Nokido (modules `forge_*.py`, docs, skills sélectionnés), livré en un seul fichier
NPZ avec les embeddings BGE-M3 1024D déjà calculés. **Une installation neuve (ou un fork)
l'importe en une commande et obtient aussitôt une recherche sémantique sur le code de
Nokido**, sans faire tourner l'embedder local sur des chunks froids.

## 🎯 Pourquoi livrer un knowledge pack ?

Un clone neuf n'a que les **graines texte** (`seed/*.jsonl`, 11 fichiers au 2026-09-29).
Elles couvrent leçons, ADR, biblio, règles système — mais **pas** le code de Nokido
lui-même. L'utilisateur a deux options d'emblée :

- Attendre que l'embedder local (`NokidoLlamaEmbed`, :8099 — l'ancien `brain_worker` :5557
  est coupé) vectorise les modules forge : 586 `app/forge_*.py` + 840 `tools/forge_*.py`
  au 2026-09-29.
- Se contenter d'une recherche BM25 (correspondance de mots, sans similarité
  d'embeddings). On perd 60 % de la valeur du flux anti-duplication décrit dans
  `CLAUDE.md` §3.

Le pack livre les embeddings précalculés : **(1) aucune attente, (2) recherche sémantique
immédiate sur le code, (3) règle anti-duplication applicable tout de suite avant de créer
un nouveau `forge_*.py`**.

Les forks en profitent surtout : ils héritent de la même base vectorisée. S'ils ajoutent
leurs propres modules, ceux-ci sont vectorisés localement par-dessus le pack.

## 📦 Contenu du pack

Schéma (archive NPZ) :

| Champ | Type | Description |
|---|---|---|
| `embeddings` | float16[N, 1024] | Vecteurs denses BGE-M3 (relus en float32) |
| `meta` | uint8 (JSON UTF-8) | manifeste, `chunk_ids`, `sources` (chemin publié), `domains` |
| `texts` | uint8 (JSON UTF-8) | les textes des chunks, tels quels |

**Une seule règle décide de ce qui entre** : un chunk n'est retenu que si son texte (espaces
normalisés) se retrouve **mot pour mot dans un fichier publié du dépôt public**, lu au commit
promu. Son contenu est donc déjà public : rien de privé ne peut fuir, même si l'étiquette de source
d'un chunk est fausse, et rien de périmé n'entre. En plus, un chunk est écarté s'il porte un motif
de secret, une identité privée, ou un signal ROUGE du gate egress (profil public). Le pack est sous
la licence du dépôt, AGPL-3.0-or-later.

Format `nokido-knowledge-pack/2` : archive NPZ **sans objet pickle** (l'importeur la charge avec
`allow_pickle=False` : un pack téléchargé ne peut jamais exécuter de code). Domaines lus :
`nokido_doc`, `doctrine`, `forge_core`, `nokido_code`, `docs`, `policy_rules`, `policy_roles`,
`policy_security`. La mémoire, les sessions, les documentations tierces et les veilles ne sont
jamais lues.

## 📊 Taille du pack (mesurée le 2026-10-07)

Contre le dépôt public à `51d10ef` : **29 695 chunks**, 27,8 Mo de texte et environ 30 Mo de
vecteurs float16 avant compression. `forge_knowledge_pack_export.py --dry-run` imprime le vrai
compte par domaine (lus / gardés / écartés par motif) avant d'écrire quoi que ce soit. Les
vecteurs sont des vecteurs BGE-M3 : le pack a besoin de l'embedder épinglé `bge-m3-Q8_0.gguf`
(pack `local-llm`) pour répondre aux requêtes.

## 🚀 Export (côté mainteneur)

```bash
# 1. Vérifier que la base RAG locale est peuplée et vectorisée
#    (autrement dit : Nokido sert depuis un moment)
python tools/forge_knowledge_pack_export.py --dist <clone du dépôt public> --verbose --dry-run
# Affiche : lus / gardés / écartés par motif, par domaine

# 2. Générer le pack (le constructeur de release le fait avec --with-assets)
python tools/forge_knowledge_pack_export.py --dist <clone du dépôt public> --version 0.1.0
# → écrit data/nokido_knowledge_pack_v0.1.0.npz
# → imprime le SHA256 (le noter !)

# 3. L'attacher à une GitHub Release
gh release create v0.1.0 \
    --title "Nokido v0.1.0 + Knowledge Pack" \
    --notes-file CHANGELOG.md \
    data/nokido_knowledge_pack_v0.1.0.npz
```

L'exporteur est idempotent — le relancer à tout moment pour rafraîchir le pack avec du code
plus récent. Chaque release livre sa propre version.

## 📥 Import (côté utilisateur)

### Option A — Dernier pack des GitHub Releases (une ligne)

```bash
python tools/forge_knowledge_pack_import.py --download
```

Télécharge l'asset de la release `latest`, vérifie le SHA256 (inscrit au manifeste),
importe dans la base RAG locale. Son dépôt par défaut est `Nokido-labs/nokido`, la vitrine
publique qui porte les releases ; tant qu'elle n'est pas publique, utiliser l'option C.

### Option B — Version précise

```bash
python tools/forge_knowledge_pack_import.py --download --version 0.1.0
```

### Option C — Fichier local (air-gapped ou dev)

```bash
python tools/forge_knowledge_pack_import.py \
    --from data/nokido_knowledge_pack_v0.1.0.npz
```

### Option D — Vérifier avant d'importer

```bash
python tools/forge_knowledge_pack_import.py --download \
    --expect-sha256 abc123def456...
```

## 🧪 Ce qui se passe à l'import

Pour chaque chunk du pack :

| État dans la base locale | Action |
|---|---|
| Le chunk n'existe pas | INSERT (texte + embedding + métadonnées) |
| Le chunk existe, embedding NULL | UPDATE de l'embedding seul (les modifications locales du texte sont gardées) |
| Le chunk existe, embedding présent | SKIP (rien d'écrasé) — `--overwrite` pour forcer |

L'importeur préserve tes modifications locales — les éditions de ton fork sur les
`forge_*.py` ne sont pas annulées par le pack.

Après l'import, l'index du hub doit être rechargé. L'importeur appelle
`POST /api/rag/reload`, mais le hub actuel **n'expose pas cette route** (vérifié le
2026-09-29) : redémarrer le hub après un import.

## 🔄 Mettre à jour le pack

Les mainteneurs ré-exportent et republient régulièrement (cadence suggérée : une fois par
version mineure). Les utilisateurs réimportent pour récupérer les chunks récents :

```bash
python tools/forge_knowledge_pack_import.py --download --overwrite
```

`--overwrite` n'est nécessaire que si tu veux que **les chunks amont remplacent tes
versions éditées localement**. Par défaut, les éditions locales sont préservées.

## 🛡️ Sécurité

Le pack contient :

- ✅ Des chunks du code source de Nokido (le même texte que le dépôt).
- ✅ Des embeddings BGE-M3 précalculés (représentation à sens unique : on ne reconstruit
  pas le texte exact).
- ❌ AUCUN log de conversation, AUCUN agent_messages, AUCUNE session, AUCUN secret,
  AUCUNE donnée personnelle.

L'assainissement de l'export **ne fait qu'écarter** — un chunk contenant un secret est
*retiré* (pas caviardé), par prudence. Le SHA256 du manifeste permet de vérifier qu'on a
bien le fichier signé par le mainteneur.

## ❓ FAQ

### Q. Pourquoi ne pas livrer le pack dans le dépôt (`data/`) ?

> Un pack pèse plusieurs Mo et grossit avec le code : trop lourd pour l'historique git.
> Les GitHub Releases sont le canal idiomatique pour « un binaire attaché à une release
> taguée », et gardent le dépôt léger pour qui ne veut que le source.

### Q. Pourquoi pas HuggingFace Datasets ?

> Les deux marchent. Les GitHub Releases sont plus simples (pas de compte en plus,
> versionnées avec le code), HF Datasets est plus visible. Un miroir HF viendra peut-être —
> ouvrir une issue pour le porter.

### Q. Puis-je forker et livrer mon propre pack ?

> Oui — relancer `forge_knowledge_pack_export.py` sur le RAG du fork, l'attacher à la
> GitHub Release du fork. L'option `--repo` de l'importeur vise n'importe quel fork.

### Q. Le pack contiendra-t-il un jour des données utilisateur ?

> Non. Le filtre d'export écarte explicitement `agent_messages`, `conversation_log`,
> `shared_prompt_log` et tout chunk qui correspond aux heuristiques de données
> personnelles. Seuls les domaines `nokido_code`, `nokido_docs`, `curated_skills` et
> `policy_rules` sont exportés — l'équivalent du code source.

### Q. Et si la version du modèle BGE-M3 change en amont ?

> Le manifeste fixe `model: "BAAI/bge-m3"`. Avec un autre embedder local, les vecteurs
> importés ne s'aligneront pas sur les tiens. Il n'existe pas aujourd'hui d'option de
> reconstruction en une fois (`forge_embed_auto_trigger.py` ne prend que `--max-passes`) :
> prévoir une revectorisation avec ton modèle avant de mélanger des vecteurs de deux
> embedders.

### Q. Le pack peut-il être malveillant ?

> Seulement par son texte (des chunks de code Nokido). Les embeddings ne sont que des
> tableaux numpy float32 — aucune charge exécutable possible. Vérifier le SHA256 contre le
> manifeste avant d'importer, et ne télécharger que depuis la page de release officielle
> du projet.
