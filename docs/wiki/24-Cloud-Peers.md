---
type: guide
title: 24 — Cloud peers (claude.ai, ChatGPT)
status: draft
resource: repo://docs/wiki/24-Cloud-Peers.md
generated: {by: claude-code@25d7339de, at: 2026-09-28T16:30:00+02:00}
sources:
  - {resource: "repo://tools/forge_pair_mcp.py"}
  - {resource: "repo://tools/forge_pair_quarantaine.py"}
  - {resource: "repo://tools/forge_passerelle_pair.py"}
  - {resource: "repo://tools/forge_bridge_oauth.py"}
  - {resource: "repo://tools/forge_bridge_launch.py"}
empreinte: INCONNUE
---

# 24 — Cloud peers (claude.ai, ChatGPT)

<!-- revu-le: 2026-09-28 -->
> Updated: 2026-09-28

Cloud assistants (claude.ai, ChatGPT) can join Nokido as **peers** : they read a
fixed, whitelisted view of the system and **deposit** proposals, messages or tasks.
Nothing they deposit acts before the owner approves it.

They talk to a **separate MCP server**, `NokidoPairMCP` (loopback `127.0.0.1:8793`),
published over HTTPS by a tunnel. The hub's own `/mcp` (`:8766`) is **never** exposed.

```
claude.ai / ChatGPT ──HTTPS──▶ tunnel (Tailscale Funnel) ──▶ 127.0.0.1:8793  NokidoPairMCP
                                                                 │  reads : state, SSoT, RAG (web sources), published commits, capsules
                                                                 └─ writes : agent_messages, status `quarantaine` ──▶ owner
```

## 🧰 Tools exposed (fixed list)

| Tool | Kind | What it does |
|---|---|---|
| `etat_corps` | read | health score, confidence, gaps |
| `point_ssot` | read | SSoT point for `roadmap` or `rules` only |
| `recherche_rag` | read | RAG search restricted to exposable sources (`https:`, `http:`, `docset:`, `watch:`) — no repository code |
| `journal_commits` | read | commits **published** on `origin/alpha` |
| `derniere_capsule` | read | last RecursiveMAS deliberation capsule published for peers |
| `proposer_fait` | deposit | SSoT fact proposal (`roadmap` / `rules`) → quarantine |
| `envoyer_message` | deposit | M2M message to `OWNER`, `CLAUDE`, `ANTIGRAVITY` or `GEMINI` → quarantine |
| `soumettre_tache` | deposit | task `deliberer` or `executer` for a local agent → quarantine |
| `lire_reponses` | read | replies addressed to **this** peer only |

Every output passes through a redaction layer (API keys, long hex tokens, then
`redact_tool_output`) and is capped. Deposits are rate-limited (30 per hour per peer).

## 🔐 Security model

- **OAuth 2.1, one local authority** (`tools/forge_bridge_oauth.py`, gateway selected by
  `NOKIDO_OAUTH_PASSERELLE`) : dynamic client registration, PKCE S256, and a
  **pairing code chosen by the owner** on the consent page. Without the code, no token.
- **Access token = capability** signed with `NOKIDO_PAIR_CAPABILITY_KEY`, audience
  `nokido-pair`, single scope `pair:collaborer` (`tools/forge_passerelle_pair.py`).
- **Intent whitelist** : a peer may only carry `COLLAB_PING`, `NEED_CLARIFY`,
  `REVIEW_FINDING`, `REVIEW_UNKNOWN`, `FACT_PROPOSED` (+ `HANDOFF_NEXT`, set by
  `soumettre_tache` itself). Never an intent that closes, authorizes, releases or
  validates (`OK_DONE`, `LOCK_*`, `AUTHZ_*`, `SCOPE_*`, `NEED_HUMAN_APPROVAL`,
  `REVIEW_OK`, `PLAN_READY`…). Re-checked at approval time.
- **Harness** : each deposit carries an `EtapeContrat` (12 columns, whitelist verdict)
  and the provenance `EXTERNE_NON_VERIFIEE`.
- **Host check kept** : FastMCP's DNS-rebinding protection stays on; only the host
  announced in `NOKIDO_PAIR_PUBLIC_URL` is added (never `*`).

## 🧾 Owner quarantine

Deposits wait in `agent_messages` (status `quarantaine`, box `OWNER_APPROBATION`);
local agents never read them.

```powershell
# list (any console)
LAFORGE_PYTHON tools/forge_pair_quarantaine.py --lister
# approve / reply : ADMINISTRATOR console of the owner account only (UAC click)
LAFORGE_PYTHON tools/forge_pair_quarantaine.py --approuver pair_<id>
LAFORGE_PYTHON tools/forge_pair_quarantaine.py --repondre <client> --pointer <ref>
# reject (safe direction, any console)
LAFORGE_PYTHON tools/forge_pair_quarantaine.py --rejeter pair_<id> --motif "..."
```

`--approuver` and `--repondre` refuse SYSTEM, the hub accounts and a **non-elevated**
owner console (where local agents run) : an agent reading « approve pair_x » in a
deposit cannot approve it itself.

What an approval does :

| Deposit | Delivered to |
|---|---|
| fact | `CLAUDE` (`pair.fait_approuve`) |
| message | its recipient (`pair.approuve`) |
| task `deliberer` | local RecursiveMAS debate (latent mode), capsule in `sandbox/capsules_pair`, reply to `PAIR:<client>` |
| task `executer` | its recipient agent (`pair.approuve`) |

## ⚙️ Setup (owner)

1. **Secrets** (machine vault, never displayed) :
   ```powershell
   # signing key — random
   LAFORGE_PYTHON -c "import sys,secrets; sys.path.insert(0, r'<repo>\app'); import forge_machine_vault as mv; print('OK' if mv.vault_set('NOKIDO_PAIR_CAPABILITY_KEY', secrets.token_urlsafe(48)) else 'ECHEC')"
   # pairing code — typed by the owner, hidden input
   LAFORGE_PYTHON app/forge_machine_vault.py set --key NOKIDO_PAIR_OAUTH_APPARIEMENT
   ```
2. **Tunnel** : `tailscale up`, enable MagicDNS + HTTPS certificates in the admin
   console, then `tailscale funnel --bg 8793` → `https://<machine>.<tailnet>.ts.net`.
3. **Service** : in `proxy_deno/core/services.toml`, block `NokidoPairMCP`, set
   `NOKIDO_PAIR_PUBLIC_URL` to the tunnel URL and `disabled = false`, then
   `tools/forge_supervisor_ctl.py reload` (a **new** service is only added by `reload`;
   `wake` answers 404).
4. **Check** : `/.well-known/oauth-protected-resource/mcp` → 200, `POST /mcp` without
   token → 401 with `resource_metadata`.
5. **Connect** :
   - claude.ai : Settings → Connectors → *Add custom connector* → `https://<machine>.<tailnet>.ts.net/mcp`.
   - ChatGPT : Settings → Apps & Connectors → Advanced → *Developer mode* → *Create*,
     same URL, authentication **OAuth**.
   The Nokido consent page asks for the pairing code. Each client registers
   separately and only reads its own replies.

**Turn it off** : `tailscale funnel --https=443 off` (public path closed at once),
then `disabled = true`.

## ⚠️ Known limitations

- The service runs as `LaForgeSbxOffline`, which can read the **non-reserved** secrets
  of the machine vault. Reserved names are closed; the rest is tracked by the vault
  hardening (step 2b). Keep the exposed surface small.
- The tunnel hostname is public (certificate transparency logs).
- ChatGPT's older connector (read-only GitHub bridge, `:8791`, via OpenAI's Secure MCP
  Tunnel) is separate and unchanged — see [OpenAI Gateway](OpenAI-Gateway.md) for the
  unrelated OpenAI-compatible API.

## 🧪 Tests

`tests/nr/test_pair_mcp_nr.py` · `test_pair_mcp_hote_public_nr.py` ·
`test_pair_quarantaine_nr.py` · `test_pair_quarantaine_geste_owner_nr.py` ·
`test_lanceur_profil_pair_nr.py` · `test_oauth_par_passerelle_nr.py`.
