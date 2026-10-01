---
type: guide
title: 19 — Knowledge Pack
status: draft
resource: repo://docs/wiki/19-Knowledge-Pack.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 19 — Knowledge Pack

<!-- revu-le: 2026-09-29 -->
> Updated: 2026-09-29

> 🌐 **English** · [Français](19-Knowledge-Pack.fr.md)

> **Status (2026-09-29)** : the export / import tools exist and work on a local file ;
> **no pack has been published yet** (no GitHub Release carries one).

The **Nokido Knowledge Pack** is an optional, pre-vectorized snapshot of
the Nokido source code chunks (modules `forge_*.py`, docs, curated
skills) shipped as a single NPZ file with BGE-M3 1024D embeddings already
computed. **Fresh installs (and forks) can import it in one command and
get instant semantic search over the Nokido codebase** without running
the local embedder on cold chunks.

## 🎯 Why ship a knowledge pack?

A fresh clone only has the **text seeds** (`seed/*.jsonl`, 11 files on 2026-09-29).
Those seeds cover lessons, ADRs, biblio, system
rules — but **not** the Nokido code itself. The user has two options
out of the box :

- Wait for the local embedder (`NokidoLlamaEmbed`, :8099 — the old `brain_worker` :5557 is
  disabled) to vectorize the forge modules : 586 `app/forge_*.py` + 840 `tools/forge_*.py`
  on 2026-09-29.
- Run BM25-only semantic search (text keyword match, no embedding
  similarity). Loses 60% of the value of the Nokido anti-duplication
  workflow described in `CLAUDE.md` §3.

The knowledge pack ships the embeddings pre-computed, so the user gets
**(1) zero waiting time, (2) immediate semantic search over the Nokido
codebase, (3) instant ability to run the anti-duplication rule before
creating a new `forge_*.py`**.

Forks especially benefit : they inherit the same vectorized base. If
they add their own modules, those get embedded locally on top of the
pre-shipped pack.

## 📦 What's in the pack

Schema (NPZ archive) :

| Field | Type | Description |
|---|---|---|
| `chunk_ids` | str[N] | Deterministic SHA-prefix ids |
| `texts` | str[N] | Sanitized text chunks (~500-1500 chars each) |
| `sources` | str[N] | Source path (`app/forge_*.py`, `docs/wiki/*.md`, …) |
| `domains` | str[N] | RAG domain (`nokido_code`, `nokido_docs`, `curated_skills`, `policy_rules`) |
| `embeddings` | float32[N, 1024] | BGE-M3 dense vectors, L2-normalized |
| `manifest` | json | version, git_sha, exported_at, count, dim, model, license |

**Sanitization applied** before export :

- Drops chunks containing real secret patterns (sk-…, ghp_…, gsk_…,
  Bearer hex64).
- Replaces personal paths (`C:/Users/<who>`, `/home/<who>`) with
  `<redacted>`.
- Replaces email addresses (gmail/proton/outlook/etc.) with `<redacted>`.
- Replaces the maintainer's personal handles (public pseudonyms, plus a
  private identity list kept outside the published code) with `<redacted>`.

Sanitization is conservative — when in doubt, the chunk is dropped, not
edited.

## 📊 Expected pack size

The first estimate of this page (3-5k chunks, 5-10 MB) was made for ~200 forge modules ;
there are 1,426 on 2026-09-29 (586 in `app/`, 840 in `tools/`) plus ~50 wiki pages.
Expect several times that size. Do not guess : `forge_knowledge_pack_export.py --dry-run`
prints the real count (scanned / kept / dropped per category) before anything is written.
Each vector weighs `1024 × 4 bytes` raw, before the NPZ zlib compression.

## 🚀 Export workflow (maintainer-side)

```bash
# 1. Make sure your local RAG base is populated and embedded
#    (i.e. you've been using Nokido for a while)
python tools/forge_knowledge_pack_export.py --verbose --dry-run
# Shows stats : scanned / kept / dropped per category

# 2. Generate the pack
python tools/forge_knowledge_pack_export.py --version 0.1.0
# → writes data/nokido_knowledge_pack_v0.1.0.npz
# → prints SHA256 (record it!)

# 3. Attach to GitHub Release
gh release create v0.1.0 \
    --title "Nokido v0.1.0 + Knowledge Pack" \
    --notes-file CHANGELOG.md \
    data/nokido_knowledge_pack_v0.1.0.npz
```

The exporter is idempotent — re-run it any time you want to refresh the
pack with newer code chunks. Each release ships its own version.

## 📥 Import workflow (user-side)

### Option A — Latest pack from GitHub Releases (one-liner)

```bash
python tools/forge_knowledge_pack_import.py --download
```

Downloads `latest` release asset, verifies SHA256 (manifest-embedded),
imports into the local RAG base. Its default repository is `Nokido-labs/nokido`, the
public showcase that carries the releases ; until it is public, use Option C.

### Option B — Specific version

```bash
python tools/forge_knowledge_pack_import.py --download --version 0.1.0
```

### Option C — Local file (air-gapped or dev)

```bash
python tools/forge_knowledge_pack_import.py \
    --from data/nokido_knowledge_pack_v0.1.0.npz
```

### Option D — Verify before importing

```bash
python tools/forge_knowledge_pack_import.py --download \
    --expect-sha256 abc123def456...
```

## 🧪 What happens on import

Per chunk in the pack :

| State in local DB | Action |
|---|---|
| Chunk doesn't exist | INSERT (text + embedding + metadata) |
| Chunk exists, embedding NULL | UPDATE embedding only (keep local text changes) |
| Chunk exists, embedding present | SKIP (don't overwrite local) — use `--overwrite` to force |

The importer preserves any local modifications you've made — your forked
edits to `forge_*.py` won't be reverted by the pack.

After import, the hub's index needs a reload. The importer calls `POST /api/rag/reload`,
but the current hub exposes **no such route** (checked 2026-09-29) : restart the hub
after an import.

## 🔄 Updating the pack

Maintainers re-export and re-release periodically (suggested cadence :
once per minor version bump). Users re-import to get newer chunks :

```bash
python tools/forge_knowledge_pack_import.py --download --overwrite
```

The `--overwrite` flag is needed only if you want **upstream chunks to
replace your locally-edited versions**. Default behavior preserves local
edits.

## 🛡️ Security

The pack contains :

- ✅ Nokido source code chunks (the same text as the repository).
- ✅ Pre-computed BGE-M3 embeddings (one-way representation, can't
  reconstruct original text exactly).
- ❌ NO conversation logs, NO agent_messages, NO sessions, NO secrets,
  NO PII.

The export sanitization is **append-only** — chunks containing secrets
are *dropped* (not redacted) to err on the safe side. The SHA256 in the
manifest lets users verify they got the file the maintainer signed.

## ❓ FAQ

### Q. Why not ship the pack inside the repo (`data/` directory)?

> A pack weighs several MB and grows with the code : too heavy for git history.
> GitHub Releases is the idiomatic distribution channel for "binary blob attached to a
> tagged release", and keeps the repo lean for users who only want the source.

### Q. Why not host on HuggingFace Datasets?

> Both work. GitHub Releases is simpler (no separate account needed,
> versioned alongside the code) but HF Datasets has better
> discoverability. We may publish a mirror on HF eventually — open an
> issue if you want to drive that.

### Q. Can I fork and ship my own knowledge pack?

> Yes — re-run `forge_knowledge_pack_export.py` on your fork's RAG,
> attach to your fork's GitHub Release. The importer `--repo` flag lets
> users target any fork.

### Q. Will the pack ever contain user data?

> No. The export filter explicitly drops `agent_messages`,
> `conversation_log`, `shared_prompt_log`, and any chunk matching PII
> heuristics. The only domains exported are `nokido_code`,
> `nokido_docs`, `curated_skills`, `policy_rules` — all source-code-
> equivalent content.

### Q. What if the BGE-M3 model version changes upstream?

> The manifest pins `model: "BAAI/bge-m3"`. If you use a different
> embedder locally, the imported vectors won't align with yours.
> There is no one-shot rebuild flag today (`forge_embed_auto_trigger.py` only takes
> `--max-passes`) : plan a re-embed with your local model before mixing vectors from two
> embedders.

### Q. Can the pack be malicious?

> Only via the text content (Nokido source code chunks). The
> embeddings are just numpy float32 arrays — no executable payload
> possible. Verify SHA256 against the manifest before importing, and
> only download from the project's official release page.
