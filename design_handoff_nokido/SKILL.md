---
name: laforge-design
description: Use this skill to generate well-branded interfaces and assets for Nokido — a sovereign, local-first multi-agent superapp — either for production or throwaway prototypes/mocks. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping.
user-invocable: true
---

Read the `readme.md` file within this skill, then explore the other available files.

Nokido is a **sovereign, local-first** superapp / personal AI hub. The single most important design rule: **always show where the compute lives** (provenance: local / hybrid / remote) and the **integrity ring** of any data (draft / verified / gold). UI copy is in **French**, dark theme only, purple `#774AFF` accent.

Key files:
- `styles.css` — the only CSS entry point (consumers link this). Pulls in all tokens + fonts.
- `tokens/` — colors (incl. provenance, integrity rings, per-domain accents), typography, spacing, effects, base.
- `guidelines/` — foundation specimen cards (colors, type, spacing, brand).
- `components/` — React primitives on `window.NokidoDesignSystem_bdc2ac`: Button, Card, TextInput, Select, Badge, StatusPill, ProvenanceBadge, SovereigntyGauge, PowerSlider, ModuleCard, CapStep.
- `ui_kits/hub/` — full hub recreation (PC), interactive.

If creating visual artifacts (slides, mocks, throwaway prototypes), copy assets out and create static HTML files for the user to view. To use a component, link `styles.css`, load `_ds_bundle.js`, then `const { Button } = window.NokidoDesignSystem_bdc2ac`. If working on production code, copy assets and read the rules here to become an expert in designing with this brand.

If the user invokes this skill without other guidance, ask them what they want to build or design, ask some questions, and act as an expert designer who outputs HTML artifacts _or_ production code, depending on the need.
