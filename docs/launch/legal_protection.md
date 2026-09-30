# ⚖️ Legal protection — pre-launch hardening

Open-sourcing under AGPLv3 doesn't transfer copyright — you keep **full
ownership** and only license usage rights. But the AGPLv3 text alone
isn't enough to win a lawsuit ; you need **evidence of authorship** and
**hardening of the repo** so bad actors can't fork-and-rebrand.

Estimated total cost : **~225-450 €** + ~30 min setup. Recommended
before flipping visibility public.

---

## 1. Antériorité — prove authorship at a fixed date

### 🥇 eSoleau INPI (recommended)

**Cost** : ~15 € · **Time** : <24h · **Effect** : sealed cryptographic
hash + date, recognized by French courts.

**Process** :

1. Bundle the current `alpha` tip into a single archive :

   ```powershell
   cd "~/Script python IA"
   git -C Nokido archive --format=zip --prefix=laforge-v0.1.0-rc/ HEAD `
       -o laforge-v0.1.0-rc.zip
   ```

2. Compute SHA-256 (for your own audit trail) :

   ```powershell
   Get-FileHash laforge-v0.1.0-rc.zip -Algorithm SHA256
   ```

3. Go to <https://www.inpi.fr/fr/services-en-ligne/depot-de-creation-en-ligne-e-soleau>.

4. Create an account (~5 min), then submit "Nouvelle enveloppe e-Soleau" :
   - Type : *Œuvre logicielle / code source*
   - Title : `Nokido v0.1.0-rc — Autonomous Local-First AI OS`
   - Attach the zip (max 10 MB, you may need to split if larger).
   - Pay 15 € by card.

5. Within 24h, you receive a PDF receipt with the INPI seal + date +
   hash of the deposit. **Keep this PDF forever.** It's your shield.

If Nokido ever ends up in court for someone claiming prior authorship,
this PDF is hard evidence dated **before** any GitHub public timestamp.

### 🥈 Agence pour la Protection des Programmes (APP)

**Cost** : ~200-400 € · **Time** : 2-3 weeks · **Effect** : signed
certificate, dissuasive in B2B disputes.

The APP (<https://app.legalis.net>) is the historical French registry
for software. It's overkill for hobby projects but **strongly recommended
once revenue is involved** (commercial license customers).

Process : online submission, ID verification, source code escrow with
APP under NDA, certificate issued.

When to do this :
- After eSoleau, once you have first commercial customers.
- Or directly if you anticipate B2B clients within 6 months.

### Cheap alternative : public timestamp

If you can't pay eSoleau immediately, a **minimum free option** :

```bash
# Compute archive hash
shasum -a 256 laforge-v0.1.0-rc.zip > laforge-v0.1.0-rc.sha256

# Post the hash + a short message on a public, timestamped service :
#   - X / Twitter (timestamp embedded in tweet URL)
#   - Mastodon
#   - A GitHub Gist (public, immutable URL with creation date)
#   - Internet Archive (web.archive.org snapshot of the gist)
```

Lower legal weight than eSoleau, but **still better than nothing**.
Use it as a temporary measure if eSoleau is delayed.

---

## 2. Trademark protection — protect the name

The copyright law protects **your code**. It does **not** protect the
**name "Nokido"**. A competitor could legally fork, rewrite, and
sell *"Nokido Enterprise"* without infringing your code copyright.

The fix : **register "Nokido" as a verbal trademark**.

### INPI verbal trademark registration

**Cost** : ~210 € for 1 class + 42 € per additional class · **Time** :
5-6 months for full registration (but the *priority date* is the day of
deposit — instant protection if your trademark is granted).

**Classes for Nokido** :
- **Class 9** : software, downloadable computer programs.
- **Class 42** : SaaS, software design / development services.

If you anticipate international expansion :
- **EUIPO** (EU-wide) : ~850 € for 1 class.
- **WIPO Madrid** (US + JP + CN + etc.) : variable, ~2000-3000 € for
  major markets.

For solo dev at launch : **start with INPI France classes 9 + 42** :
~252 € total. Upgrade to EUIPO if revenue justifies.

### How

1. Go to <https://www.inpi.fr/fr/proteger-vos-creations/proteger-votre-marque>.
2. Search the existing trademark database for conflicts :
   <https://data.inpi.fr/recherche_avancee/marques>
3. Verify "Nokido" is available (or near-available) in classes 9 + 42.
4. Submit online application (~30 min, English available).
5. Pay.
6. INPI examines (3 months silent period for opposition).
7. If no opposition, you're granted.

**Practical tip** : even before grant, you can use **™** next to the
name to signal trademark intent. After grant, use **®**.

---

## 3. Technical watermarking — detect unauthorized commercial use

You can't legally fight someone you don't know is infringing. Plant
technical fingerprints so you can **detect** unauthorized SaaS
deployments from outside.

### Headers HTTP signatures

The hub already emits `Server: ...` and similar. Add a permanent custom
header on every response :

```python
# In tools/nokido_hub.py, in the StarletteMiddleware chain :
@app.middleware("http")
async def nokido_signature(request, call_next):
    response = await call_next(request)
    response.headers["X-Powered-By"] = "LaForge-Core/0.1.0"
    response.headers["X-LaForge-Build"] = f"{GIT_SHA[:8]}"
    return response
```

When you suspect a SaaS uses Nokido, you `curl -sI` their endpoint and
look for these headers.

### Error fingerprints

Customize error messages with a unique typographic signature :

```python
# Use a specific Unicode separator unlikely to appear in other systems
ERR_PREFIX = "⌬ Nokido:"  # cyclohexane-emoji prefix

raise SemanticFirewallError(f"{ERR_PREFIX} prompt blocked by pre_flight ...")
```

If an end-user of an unauthorized SaaS pastes a stack trace into a forum,
the `⌬ Nokido:` prefix is your beacon. Search for it monthly on Google,
StackOverflow, GitHub issues.

### Optional canary update check

This one is **invasive** and must be **transparent** to comply with GDPR.

```python
# tools/forge_update_check.py — DISABLED by default
async def check_for_updates():
    """Phone home to version.nokido.example to log unique deployments.
    Disabled unless LAFORGE_UPDATE_CHECK=1 is set. Logs your machine
    fingerprint + Nokido version (NO personal data) for the
    maintainer's awareness of where Nokido is deployed.
    Disable any time : LAFORGE_UPDATE_CHECK=0
    """
    if os.environ.get("LAFORGE_UPDATE_CHECK") != "1":
        return
    ...
```

**Pro** : you see unauthorized deployments in your server logs.
**Con** : even disabled-by-default, this is sensitive ; some users will
hate it on principle and downvote you. **Recommendation : skip this for
the initial launch**, add it later only if commercial leakage is detected.

---

## 4. Git hygiene — make the repo tamper-resistant

### Sign commits with GPG or SSH

GitHub displays a green **"Verified"** badge next to verified commits.
This proves cryptographically that **you** signed the commit, not an
impostor.

**SSH-key signing (simpler than GPG)** :

```powershell
# Generate key (or reuse existing SSH key)
ssh-keygen -t ed25519 -f ~/.ssh/nokido_signing -C "user@users.noreply.github.com"

# Tell git to use it
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/nokido_signing.pub
git config --global commit.gpgsign true

# Upload public key to GitHub for verification
# → Settings → SSH and GPG keys → "New SSH key" → Title "Nokido signing" → Type "Signing key"
```

From now on, every commit shows "Verified" on GitHub.

**Important** : Memory rule (`feedback_no_coauthor_trailer`) — repo
Nokido.git is **signed by user alone**, no `Co-Authored-By` trailers.

### Branch protection on `main`

GitHub Pro tier required, OR use **Rulesets** (free tier limited).
Settings → Branches (or Rules) → Add rule for `main` :

- ✅ Require pull request before merging
- ✅ Require status checks to pass (`unit-tests`, `lint`, `secrets-scan`)
- ✅ Require signed commits
- ✅ Restrict who can push (force push prohibited)
- ✅ Require linear history (optional, for clean log)

For `beta`, slightly looser (PR required but no signed-commits enforce —
you push directly from local).

For `alpha`, no protection — dev branch.

### Tag the launch version

```bash
git -C Nokido tag -s v0.1.0-rc -m "v0.1.0 release candidate — pre-public"
git -C Nokido push origin v0.1.0-rc
```

The `-s` flag signs the tag with your GPG/SSH key. This is the
canonical version the eSoleau archive corresponds to.

---

## 5. The launch checklist (compressed)

In order, before flipping `gh repo edit --visibility public` :

1. ⏳ Generate `laforge-v0.1.0-rc.zip` (git archive of beta tip).
2. ⏳ Upload to eSoleau INPI — keep PDF receipt.
3. ⏳ (Optional) APP deposit if revenue expected within 6 months.
4. ⏳ Submit INPI trademark "Nokido" in classes 9 + 42.
5. ⏳ Configure GPG/SSH signing on git, push a signed tag `v0.1.0-rc`.
6. ⏳ Enable branch protection on `main` (Rulesets if free tier).
7. ⏳ Add `X-Powered-By` header middleware in `nokido_hub.py`.
8. ⏳ Search Google / DuckDuckGo for `"Nokido AI"` to check no
   collision exists.
9. ✅ Flip visibility public.

Items 1, 5, 6 can be done in one afternoon. Items 2, 4 take weeks but
the **priority date** is the submission date — start them today, paint
finishes later.

---

## 6. What to do if you discover unauthorized use

You see your `X-Powered-By: LaForge-Core` header on a competitor's SaaS
that doesn't appear on your commercial license customer list :

1. **Don't panic, don't tweet.** Quiet investigation first.
2. Curl the suspect endpoint, save full HTTP headers + body.
3. Check if their public marketing / GitHub mentions Nokido —
   sometimes they did sign a commercial license and you forgot.
4. If genuinely unauthorized :
   - Email the company's legal contact (form letter — "we detected
     Nokido usage, would like to discuss licensing").
   - 90% of cases : they sign a commercial license retroactively.
   - 10% : you escalate to a lawyer (INPI + APP records become weapons).
5. **Document everything** in a dated journal. Court evidence chain.

The eSoleau + APP + trademark trio gives you **the equivalent of a
nuclear deterrent** — most actors back down once they see official
French / EU records. Litigation is rare.

---

## 7. Recommended now (J-1 from launch)

Do **today** :
1. `git archive` → `laforge-v0.1.0-rc.zip`.
2. eSoleau upload (15 €, 20 min).
3. Configure SSH signing on git.
4. Tag + sign `v0.1.0-rc`, push.

Do **this week** :
5. INPI trademark submission (~30 min web form, 210 €).
6. (Optional) APP deposit if you anticipate B2B revenue.

Do **post-launch** :
7. Add HTTP header middleware (cosmetic, do once you breathe).
8. Monthly Google search for `"Nokido AI"` / `"LaForge-Core"` —
   detect uses you didn't authorize.

This three-layer defense (antériorité + marque + watermarking) covers
the realistic threat model for a solo-dev open-source project that
also sells commercial licenses.
