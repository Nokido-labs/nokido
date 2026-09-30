# LobeHub Server self-hosted - operations guide

Stack location: `docker/lobehub-selfhost/`
Bound to `127.0.0.1` only. Never publicly exposed.

## 1. Stack components

| Service | Image                          | Container             | Host port |
|---------|--------------------------------|-----------------------|-----------|
| lobe    | lobehub/lobehub:latest         | lobehub-selfhost      | 3210      |
| db      | paradedb/paradedb:latest-pg17  | lobehub-postgres      | 5433      |
| redis   | redis:7-alpine                 | lobehub-redis         | 6380      |
| s3      | rustfs/rustfs:latest           | lobehub-rustfs        | 9100/9101 |

ParadeDB ships PGVector + Postgres 17. Default Postgres port 5432 is
remapped to 5433 to avoid collisions. Redis 6379 -> 6380. RustFS S3
9000 -> 9100, console 9001 -> 9101.

SearxNG is intentionally NOT included in this stack: host port 8080
is already taken by `llamacpp_native`. Wire LobeHub to an external
SearxNG later via `SEARXNG_URL` env var if needed.

## 2. Boot, status, logs

```powershell
cd "~\Script python IA\docker\lobehub-selfhost"

# Boot
docker compose up -d

# Status
docker compose ps

# Logs (lobe app only)
docker logs -f lobehub-selfhost

# Stop
docker compose stop

# Stop + remove containers (keeps data volumes)
docker compose down

# WIPE EVERYTHING (data included) - DANGEROUS
docker compose down -v
Remove-Item -Recurse -Force .\data
```

## 3. First-run admin setup (Better Auth)

LobeChat v2 dropped NextAuth and migrated to Better Auth. Email/password
is enabled by default; no provider config needed.

1. Open browser: <http://127.0.0.1:3210>
2. You will be redirected to `/signin`.
3. Click "Sign up" (registration link on the signin page).
4. Enter your email (e.g. `<your-gmail-oauth-account>`) + a strong password.
5. Submit. The first registered user is the implicit admin.
6. You will be redirected to the chat workspace at `/chat`.

To LOCK registration to your address only, edit `.env`:

```env
AUTH_ALLOWED_EMAILS=<your-gmail-oauth-account>
```

then `docker compose up -d --force-recreate lobe`.

To disable email/password entirely (SSO-only), set
`AUTH_DISABLE_EMAIL_PASSWORD=1`.

## 4. Programmatic API access

LobeChat exposes tRPC endpoints under `/trpc/lambda/<procedure>` and
`/trpc/edge/<procedure>`. Auth is cookie-based (Better Auth session
cookie `better-auth.session_token`).

### 4.1 Get a session cookie

After signing in via the browser, copy the cookie:

```powershell
# In Chrome/Edge: F12 -> Application -> Cookies -> http://127.0.0.1:3210
# Copy the value of `better-auth.session_token`.
$env:LOBE_COOKIE = "better-auth.session_token=PASTE_VALUE_HERE"
```

### 4.2 Sample tRPC call (list AI providers)

```python
# scripts/lobehub_smoke.py - run with LAFORGE_PYTHON
import os, httpx

BASE = "http://127.0.0.1:3210"
COOKIE = os.environ["LOBE_COOKIE"]

# tRPC HTTP batch link: GET /trpc/lambda/aiProvider.getAiProviderList
url = f"{BASE}/trpc/lambda/aiProvider.getAiProviderList"
r = httpx.get(url, headers={"cookie": COOKIE}, timeout=10)
print("status:", r.status_code)
print(r.json())
```

Run: `"~/miniforge3/python.exe" scripts/lobehub_smoke.py`

### 4.3 API keys (programmatic, no browser)

LobeChat does not yet ship a first-class API-key minting UI in v2. For
unattended scripts use the session-cookie approach above and rotate the
cookie when it expires (default 30 days).

If/when LobeChat ships API keys (track issue lobehub/lobe-chat#3xxx),
mint via `Settings -> API Keys -> Generate` and pass as
`Authorization: Bearer <key>`.

## 5. Wire Nokido defaults inside LobeHub

The `OPENAI_PROXY_URL` in `.env` is already set to
`http://host.docker.internal:7777/v1`, so the built-in OpenAI provider
will route to `forge_openai_proxy` automatically.

To expose Nokido MCP tools inside LobeHub:

1. `Settings -> Skills -> Skill Store -> Custom -> Add custom skill`
2. Paste this JSON:

```json
{
  "mcpServers": {
    "laforge": {
      "url": "http://host.docker.internal:8766/mcp",
      "type": "http",
      "headers": {
        "Authorization": "Bearer <FORGE_TOKEN_CLAUDE>"
      }
    }
  }
}
```

To add a custom OpenAI-compatible provider mirror (alongside the
default OpenAI provider that's already proxied):

1. `Settings -> AI Service Provider -> + Custom`
2. Type: OpenAI Compatible
3. Base URL: `http://host.docker.internal:7777/v1`
4. API Key: `laforge-local`
5. Auto-fetch models via `/v1/models`.

NOTE: LobeHub Desktop (Electron, host-native) reaches Nokido at
`127.0.0.1:7777` and `127.0.0.1:8766`. LobeHub Server (this stack,
containerized) MUST use `host.docker.internal` because containers
cannot reach the Windows host on `127.0.0.1`.

The `extra_hosts: host.docker.internal:host-gateway` line in the
compose file enables this on Linux-flavored Docker Desktop containers.

## 6. Migration from Desktop LobeHub

Out of scope for the initial deployment. High-level path:

1. Export Desktop data: in Desktop go to `Settings -> Data -> Export`
   and save the JSON dump.
2. Import in self-hosted: `Settings -> Data -> Import` (same UI under
   v2). Topics, agents, system prompts, and provider configs transfer.
3. Knowledge base files: re-upload manually (they live in S3 - the
   self-hosted instance has its own RustFS bucket).
4. Memory entries: white-box memory is editable, copy-paste worst case.
5. After validation, point Desktop to this self-hosted instance via
   the Wi-Fi icon -> `http://127.0.0.1:3210` and use Desktop as a
   thin client. ENABLE_OIDC=1 + JWKS_KEY are already configured.

## 7. Troubleshooting

### Lobe container restarts in a loop
Most often a deprecated env var (NextAuth left over). Tail logs:
`docker logs lobehub-selfhost`. The container prints the offending
variable name and a migration link.

### `/signin` returns 308
Normal: the route enforces a trailing slash redirect when accessed
directly. Browsers follow automatically.

### Postgres init slow first boot
ParadeDB pulls + initializes PGVector extensions on first start.
Allow ~30-60s before lobe-app starts. The healthcheck dependency
gates this correctly.

### RustFS bucket missing
The `rustfs-init` one-shot container creates the `lobe` bucket and
sets the public read policy. If avatars don't load, re-run:
`docker compose up rustfs-init` and check its logs.

### Reset everything
```powershell
cd "~\Script python IA\docker\lobehub-selfhost"
docker compose down -v
Remove-Item -Recurse -Force .\data
docker compose up -d
```

## 8. Secrets file

`.env` is git-ignored. The committed `.env.example` is a safe template.
If you rotate `KEY_VAULTS_SECRET`, all existing user-stored API keys in
the DB will become unreadable - re-enter them via the UI.
