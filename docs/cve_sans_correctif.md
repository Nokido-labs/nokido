# Known vulnerabilities with no upstream fix — accepted risk register

A vulnerability with no released fix is **not** a vulnerability that disappears.
This file records what we measured, what an attacker would need, and under which
condition the decision must be reopened. Without those, "no fix available" quietly
degrades into "I forgot about it" — which is the failure mode this register exists
to prevent.

**Rule that produced this file:** an advisory changes, so the status must change with
it. A security state is **re-measured** before being carried over, never copied.
And *"a newer version exists"* is not *"the CVE is fixed"* — the advisory decides,
not the version number.

Last review: **2026-09-09**

---

## `diskcache` 5.6.3 — ACCEPTED

| | |
|---|---|
| **Advisory** | PYSEC-2026-2447 · CVE-2025-69872 · GHSA-w8v5-vhqr-4h9v |
| **Affected** | `through 5.6.3` (`last_affected: 5.6.3`) |
| **Fixed in** | *nothing* — 5.6.3 **is the latest release on PyPI** (84 releases) |
| **Vector** | DiskCache uses Python `pickle` for serialization by default |
| **Precondition** | the attacker needs **write access to the cache directory**; code executes when the victim application later reads that cache |
| **Actual usage here** | **no direct import** in `app/` or `tools/` (recursive search for `import diskcache` / `from diskcache`). Pulled transitively by `dspy` only |
| **Mitigation** | none available by upgrade — there is no newer version to move to |
| **Decision** | **accepted**, dated 2026-09-09 |

**Why accepted rather than mitigated.** Upgrading is not an option that exists:
5.6.3 is simultaneously the last affected version and the latest published one.
That is the state of the upstream project, not an oversight on our side — and
saying so is better than staying silent or inventing a version bound that does not
exist.

The exploitation precondition is local filesystem **write** access. An attacker who
already holds it has other execution paths on the same host; that does not make the
flaw harmless, but it places it behind the same boundary as the rest of the machine.

**Reopen this decision when either becomes true** — both are mechanically checkable,
so this acceptance is not an open-ended one:

1. a release `> 5.6.3` appears on PyPI;
2. a **direct** call site to `diskcache` appears in `app/` or `tools/`.

---

## `accelerate` — CLOSED on 2026-09-09

Kept here because the previous entry read *"no fix available"*, and that was true on
2026-09-07 and **false two days later**. It is the clearest illustration of why this
register carries a review date.

| | |
|---|---|
| **Advisory** | CVE-2026-69112 · GHSA-4j2p-28q2-5m79 |
| **Affected** | `introduced: 0`, `last_affected: 1.14.0` |
| **Installed before** | 1.13.0 — inside the vulnerable range |
| **Action** | upgraded to **1.15.0** (published 2026-09-09) |
| **Verification** | OSV query on `accelerate 1.15.0` returns **0 advisories**; functional check passes (`import accelerate`, `Accelerator(cpu=True)`, `device=cpu`) |
| **Durability** | `accelerate>=1.15.0` pinned in `requirements-ml.txt` |

**Two nuances worth keeping.** The advisory says `last_affected`, not `fixed`: the
vulnerable range stops before 1.15.0 and scanners stop reporting it, but the advisory
does not certify that a patch was shipped. It is a *range exit*, not a verified fix.

And `accelerate` was pinned **nowhere** — it is pulled transitively by `peft` and
`trl`. Without the lower bound above, the next dependency resolution could have
reinstalled 1.13.0 and silently undone the upgrade. A security fix that nothing holds
in place is not a fix.
