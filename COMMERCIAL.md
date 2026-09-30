# Nokido — Commercial License

> 🌐 **English** · [Français](COMMERCIAL.fr.md)

## Overview

Nokido ships under a **dual-licensing model** :

| License | For whom | What you get |
|---|---|---|
| [**AGPLv3-or-later**](LICENSE) (default) | Open-source projects, internal R&D, individuals | Full code, modify freely. **You must publish modifications if you host Nokido over a network for users.** |
| **Commercial License** (this document) | Proprietary products, closed-source SaaS, embedded OEM | All AGPLv3 rights **plus** the ability to keep your modifications private and ship Nokido inside proprietary or closed-source offerings, without the network-copyleft trigger. |

If you can comply with AGPLv3, you don't need a commercial license. If you
can't, this page is for you.

---

## When do you need a commercial license ?

You need one when **any** of these applies :

1. **SaaS / hosted service** — you offer Nokido (or a derivative) as a
   network service to end-users *outside your own organization*, AND
   you do not want to publish the source of your modifications under
   AGPLv3.
2. **Closed-source product** — you embed Nokido in a proprietary
   product (desktop app, mobile app, on-prem appliance, MSP platform,
   firmware) and you cannot distribute the corresponding source code
   under AGPLv3.
3. **Aggressive copyleft refusal** — your legal team requires that
   third-party code in your product carries a permissive (MIT / Apache 2.0)
   or a commercial license, never a strong-copyleft one.
4. **OEM / redistribution** — you bundle Nokido with hardware, you
   white-label it, or you redistribute modified versions under your
   own brand.

You **don't** need a commercial license when :

- You run Nokido **on your own machine for personal/internal use**, no
  matter what you do with it.
- You contribute back to the Nokido project (PRs welcome under the
  contributor license agreement — see [CLA.md](docs/CLA.md)).
- You build an open-source project on top of Nokido and license your
  own additions under AGPLv3 (or a compatible license).
- You run a research / academic project, even if it has a public web
  endpoint — AGPLv3 has no problem here as long as you publish your
  modified source.

If unsure, **ask before deploying** — `thomas.signorelli@proton.me`.

---

## Pricing

| Tier | Use case | Annual fee | What's covered |
|---|---|---|---|
| **Startup** | <10 employees, single-site, single-product | On request | 1 production deployment, 1 OEM SKU, email support |
| **SMB** | 10-200 employees, multi-site, multi-product | On request | Unlimited internal deployments, 3 OEM SKUs, priority email + GitHub support |
| **Enterprise** | >200 employees OR MSP redistributing to customers | On request | Unlimited, integration assistance, named contact, SLA, custom feature roadmap input |
| **OEM redistribution** | Hardware bundle, embedded firmware, white-label | On request | Per-unit royalty OR flat fee, marketing approval workflow |
| **Academic / Non-profit** | Research lab, NGO, public sector pre-revenue | **Free** | AGPLv3 default works; commercial license available pro-bono on request for legal-compliance edge cases |

Pricing is per-year, renewable. We don't do perpetual licenses — the
ecosystem moves too fast. Existing licensees get a perpetual fallback
to the *latest version they paid for* if they don't renew, with no
update / support beyond that point.

All fees are quoted on request after a short scoping call (typically
30 minutes). We don't list public rates because they vary wildly with
deployment scale, support level, and customization needs.

---

## What's included with a commercial license

- **Commercial use rights** — embed Nokido in proprietary / closed-source
  products without AGPLv3 source-disclosure obligations.
- **Priority response** — issues and security questions handled before
  community-tier traffic (target: 24h business-day acknowledgement,
  72h initial assessment).
- **Custom integration assistance** — pair-programming sessions to wire
  Nokido into your stack (paid extra, sold separately).
- **Roadmap influence** — Enterprise-tier customers get input on the
  quarterly roadmap.
- **Indemnification** — limited indemnity against IP claims on the
  Nokido codebase itself (excludes third-party dependencies — those
  carry their own upstream warranties).
- **Audit rights** — your legal / compliance team can review the source
  for security audit purposes under standard NDA.

What's **not** included :

- 24/7 phone support (available as a separate paid add-on).
- Source code escrow (separate agreement).
- Public reseller / partner status (separate program).

---

## How to acquire a commercial license

1. **Email** `thomas.signorelli@proton.me` with subject
   `[Nokido Commercial License]`.
2. Include in the body :
   - Company name + jurisdiction (EU / US / other).
   - Use case description (1-2 paragraphs is fine).
   - Expected deployment scale (number of internal users, number of
     external customers if SaaS, number of devices if OEM).
   - Preferred starting timeline.
3. We schedule a 30-min scoping call within 5 business days.
4. We send a draft agreement within 10 business days post-call.
5. After signature, license is active. You can ship.

Standard terms are **non-exclusive, non-transferable, per-entity**.
Multi-entity groups (holding + subsidiaries) need a master agreement.

---

## License compatibility with third-party dependencies

Nokido depends on several open-source libraries with their own
licenses. Most are permissive (MIT, Apache 2.0, BSD), some are
copyleft-compatible. When you take a commercial license on Nokido,
you remain responsible for complying with the upstream licenses of
your dependency set.

Notable dependencies and their licenses (non-exhaustive, check
`pyproject.toml` for the current pin list) :

| Dependency | License | Compatible with our commercial license ? |
|---|---|---|
| FastAPI, Starlette, Uvicorn | MIT / BSD | ✅ Yes |
| FAISS-cpu | MIT | ✅ Yes |
| Numpy, Pydantic | BSD / MIT | ✅ Yes |
| `litellm` | MIT | ✅ Yes |
| `pymdp` | MIT | ✅ Yes |
| `ncps` | Apache 2.0 | ✅ Yes |
| `sentence-transformers` | Apache 2.0 | ✅ Yes |
| Tree-sitter Python | MIT | ✅ Yes |
| Ollama (runtime, not bundled) | MIT | ✅ Yes (you ship your own) |
| BGE-M3 model weights | MIT (Beijing Academy of AI) | ✅ Yes |

If you intend to ship Nokido with a third-party LLM, check that LLM's
weights license separately — some commercial models (Claude, GPT-4)
have restrictive terms even when accessed via API.

---

## Questions

**Q. Can I evaluate Nokido under AGPLv3 first, then convert to commercial later ?**

Yes. AGPLv3 is free to try. Convert to commercial before you start
serving end-users over a network with a closed-source variant.

**Q. What if I forget to convert and ship a closed-source SaaS by mistake ?**

You're in breach of AGPLv3. The fix is either (a) publish your
modifications under AGPLv3, retroactively, or (b) buy the commercial
license retroactively. Option (b) is fine — we don't litigate good-faith
mistakes.

**Q. Does the commercial license cover sub-projects ?**

It covers any project that uses **Nokido code** — `app/forge_*.py`,
`tools/forge_*.py`, the Rust services, the Deno proxy. It does **not**
cover third-party dependencies (those carry their own licenses).

**Q. Can I get a perpetual license ?**

No — see Pricing section. The world moves too fast for that to be
fair to either side. You get a perpetual fallback to your last paid
version, which protects you against vendor lock-in.

**Q. Can the project be acquired ?**

In principle yes. Any acquisition would honor existing commercial
license commitments. Talk to us if relevant.

---

*This document is informational and does not by itself constitute a
license. The legally binding terms are in the signed agreement
exchanged after scoping. Re-licensing of the project to a fundamentally
different model would require respecting all existing commercial
license terms.*

📧 `thomas.signorelli@proton.me` · Last updated: 2026-05-26
