<!-- DEPORTE depuis CLAUDE.md le 2026-09-19 pour tenir le budget du noyau resident.
     Le contenu n'a pas ete modifie : seul son LIEU a change.
     Mesure : cette section pesait 52% de CLAUDE.md, re-facture a chaque tour. -->

# 17. STRATÉGIE BUSINESS & BENCHMARKS (Septembre 2026)

> Section de regles **deportee** hors du noyau resident. Elle n'est plus
> chargee a chaque tour ; elle se consulte a la demande (`rag`, `introspect`,
> ou lecture directe). Les pieges qu'elle decrit restent **EXECUTES** par
> `tools/hook_capability_gate.py`, dont les regles vivent dans SON code :
> deporter la prose ne desarme rien.

## 17. STRATÉGIE BUSINESS & BENCHMARKS (Septembre 2026)

Le positionnement public de Nokido a été acté le 2026-09-06 : le projet n'est pas seulement un framework, c'est un **véhicule de benchmark public pour l'orchestration multi-agent et le Edge AI**.

**Objectif "Infrastructure Partners"** :
- Utiliser Nokido pour exécuter des benchmarks rigoureux (SWE-bench, BFCL, Terminal-Bench) afin de comparer l'efficacité de l'organisme (Swarm + RAG + MCP) face aux modèles isolés.
- Métriques visées : Tokens, Latence, Coût, Résilience (recovery), Consommation énergétique.
- Démarcher les fournisseurs (AWS Activate, NVIDIA Inception, Together AI, Cloudflare) en leur proposant d'être **sponsors/partenaires d'infrastructure** pour ces benchmarks en échange de crédits compute/API.

**Actions techniques attendues du système / de Claude** :
- Préparer la rédaction d'un BENCHMARKS.md exhaustif.
- S'assurer que le code de télémétrie/audit puisse exporter des métriques standardisées pour ces fournisseurs.
- Cadrer la prochaine phase de la Roadmap sur la Qualification et la Mesure.
