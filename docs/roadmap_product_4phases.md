# Roadmap Produit Nokido : 4 phases (mois → an)

Source : memory `roadmap_product_nokido`. Post-vectorisation pipeline,
direction commerciale assumée.

> 🔒 **NE PART PAS AU PUBLIC — décision owner du 2026-08-30.** Ce document porte une
> grille de prix, des cibles d'acquisition nommées et des critères de valorisation :
> de la stratégie commerciale, pas un secret technique — donc aucun scanner de secrets
> ne l'arrêterait. Il est exclu du miroir par `tools/forge_public_mirror.EXCLUSIONS`
> (et purgé de l'histoire en mode `--historique`), et cette exclusion est verrouillée
> par un test : `tests/nr/test_forge_public_mirror_nr.py`. Il reste pleinement utilisable
> dans le dépôt privé.

## Phase 0 : Repo propre AGPLv3 (1-2 semaines)

> **Phase 0 : livrée** (vérifié 30/08 — chaque case ci-dessous est cochée sur la
> PRÉSENCE du fichier, pas sur un souvenir). Ce document restait décoché des mois
> après coup : une roadmap qu'on ne recoche pas fait passer du travail fait pour
> du travail dû.

### Livrables
- [x] LICENSE → AGPLv3 — vérifié : le fichier porte bien « GNU AFFERO ». Garde-fou de
      licence des dépendances : `tools/forge_license_guard.py`, câblé pre-commit + CI.
- [x] CONTRIBUTING.md + CLA léger (8 540 o)
- [x] CODE_OF_CONDUCT.md (2 798 o)
- [x] SECURITY.md (5 780 o) — politique de divulgation présente
- [x] README : tagline produit + badges alignés sur le code (41 badges, 7 traductions)
- [ ] Screenshot/GIF démo dashboard — **seul livrable Phase 0 encore ouvert**
- [x] Quick-start docker-compose — `docker/nokido/docker-compose.yml`, profils `core`/`full`/`all`/`dev`

### Critères go-public
- Tests CI green (pytest + lint)
- Pas de secrets leaked (audit gitleaks final)
- Tier policy strict : pas de code tiers proprietaire dans repo

### Gates secrets
- pre-commit hook gitleaks
- audit log toute exposition externe (Codeberg push refused si secret detected)

## Phase 1 : Docker + 30 min install (1 mois)

### Livrables
- [x] `docker-compose.yml` complet — présent dans `docker/nokido/` (vérifié 30/08)
- [x] `Dockerfile` — présent dans `docker/nokido/` ; variantes de build `core|hub|full|all`
- [ ] Vault initial via DPAPI Windows OU sealed-secret Linux
- [ ] Web installer : `curl ... | bash` script qui :
  - Check prerequis (Docker, RAM ≥ 16 GB)
  - Pull images
  - Init vault interactive
  - Boot full stack
  - Open dashboard
- [ ] Demo data ingestion (datasets exemple)
- [ ] Walkthrough video 5 min sur YouTube/PeerTube

### Plateformes cibles
1. Linux x86_64 (Ubuntu 22+/Debian 12+)
2. Linux ARM64 (Raspberry Pi 5)
3. Windows 11 Pro + WSL2
4. macOS Apple Silicon

### Bench install
Objectif : `git clone` → dashboard accessible = **< 30 min** sur Linux propre.

## Phase 2 : netcfg-agent MSP 49 €/mo (3-6 mois)

### Cible : PME (10-200 employés) qui n'ont pas d'admin sys dédié

### Stack produit
- Nokido core (auto-hosted ou cloud par MSP)
- netcfg-agent installé sur chaque machine cliente (LAN local)
- Dashboard MSP central : multi-tenant
- Alerting Slack/Teams/Email

### Use-cases
1. Visibility complete LAN (devices, ports, OS, vulns)
2. Patch management automation
3. Incident response (forensics rapide via RAG)
4. Compliance reports (NIS2/GDPR friendly)

### Pricing
- Self-hosted gratuit (AGPLv3 force partage)
- MSP-managed : 49 €/mois/PME pour ≤ 50 endpoints
- Enterprise : pricing custom (≥ 200 endpoints)

### Acquisition canaux
- ProductHunt launch
- Show HN: Sovereign LAN observability
- Reddit /r/sysadmin /r/selfhosted
- Discord communautés sécurité FR/EN
- Sponsoring podcasts sécurité (Risky Biz, Hack The Box podcast)

## Phase 3 : Acquisition / exit (12-24 mois)

### Targets potentiels
- **Synology** : extension NAS monitoring
- **Vade Secure** (FR cybersec) : ajout layer endpoint visibility
- **Datto/Kaseya** : intégration MSP RMM stack
- **Tenable / Rapid7** : vulnerability mgmt
- **Microsoft Defender** : différentiateur souveraineté EU

### Critères valuation
- ARR ≥ 1 M€ (≥ 1700 PME clients)
- Retention ≥ 90% net annual
- NPS ≥ 50
- Architecture cleanly extractable (pas trop dépendant clouds tiers)

### Alternative : sustainable indie business
Si pas d'exit attrayant : 50-200 K€/mois ARR = vivre du produit sans VC.

## Différentiateur (vs OpenHands / SuperAGI / GPT-Pilot)

| | Nokido | OpenHands | SuperAGI |
|---|---|---|---|
| Sovereign (no cloud required) | ✅ | ❌ | ❌ |
| LAN observability (netcfg) | ✅ | ❌ | ❌ |
| RAG souverain | ✅ BGE-M3 local | API cloud | API cloud |
| Veille autonome | ✅ closed loop | ❌ | ⚠️ basic |
| Multi-LLM cascade frugal | ✅ Cerebras+Groq+Mistral | ⚠️ OpenAI only | ⚠️ |
| TUI + Web dashboard | ✅ Textual v3 | ❌ web only | ❌ web only |
| Anti-saturation OS | ✅ Job Objects | ❌ | ❌ |

**Positionnement** : niche "security + souveraineté + LAN edge" vs concurrents généralistes cloud-first.

## Risques

- Concurrence Microsoft/Google = pression marketing énorme
- AGPLv3 freine adoption corporate (alternative : dual license)
- Maintenance solo difficile au-delà 50 clients → recruter tôt
- Réglementation IA EU (AI Act compliance docs requis)

## Next actions (Phase 0 quick-wins)

1. README + screenshot dashboard
2. docker-compose POC
3. LICENSE AGPLv3 file
4. Showcase video brouillon
5. Soumettre Show HN dans 4 semaines
