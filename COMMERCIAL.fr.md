# Nokido — Licence Commerciale

> 🌐 [English](COMMERCIAL.md) · **Français**

> ⚠️ Cette traduction est fournie pour faciliter la lecture. En cas
> d'ambiguïté, **la version anglaise [COMMERCIAL.md](COMMERCIAL.md) fait
> foi**. L'accord signé après cadrage reste le seul texte juridiquement
> contraignant.

## Vue d'ensemble

Nokido est distribué sous un **modèle de licence duale** :

| Licence | Pour qui | Ce que vous obtenez |
|---|---|---|
| [**AGPLv3-or-later**](LICENSE) (par défaut) | Projets open-source, R&D interne, particuliers | Code complet, modifications libres. **Vous devez publier vos modifications si vous hébergez Nokido sur un réseau pour des utilisateurs.** |
| **Licence Commerciale** (ce document) | Produits propriétaires, SaaS closed-source, OEM embarqué | Tous les droits AGPLv3 **plus** la possibilité de garder vos modifications privées et de livrer Nokido à l'intérieur d'offres propriétaires ou closed-source, sans le déclencheur de copyleft réseau. |

Si vous pouvez vous conformer à l'AGPLv3, vous n'avez pas besoin de
licence commerciale. Sinon, cette page est pour vous.

---

## Quand avez-vous besoin d'une licence commerciale ?

Vous en avez besoin si **l'un quelconque** des cas suivants s'applique :

1. **SaaS / service hébergé** — vous proposez Nokido (ou un dérivé)
   comme service réseau à des utilisateurs finaux *hors de votre propre
   organisation*, ET vous ne voulez pas publier la source de vos
   modifications sous AGPLv3.
2. **Produit closed-source** — vous intégrez Nokido dans un produit
   propriétaire (application desktop, mobile, appliance on-prem,
   plateforme MSP, firmware) et vous ne pouvez pas distribuer le code
   source correspondant sous AGPLv3.
3. **Refus agressif du copyleft** — votre équipe juridique exige que
   le code tiers de votre produit porte une licence permissive
   (MIT / Apache 2.0) ou commerciale, jamais une copyleft fort.
4. **OEM / redistribution** — vous packagez Nokido avec du matériel,
   vous le white-labelez, ou vous redistribuez des versions modifiées
   sous votre propre marque.

Vous **n'avez pas besoin** de licence commerciale quand :

- Vous lancez Nokido **sur votre propre machine pour usage
  personnel/interne**, peu importe ce que vous en faites.
- Vous contribuez en retour au projet Nokido (PR bienvenues sous
  l'accord de licence contributeur — voir [CLA.md](docs/CLA.md)).
- Vous construisez un projet open-source au-dessus de Nokido et
  licenciez vos propres ajouts sous AGPLv3 (ou une licence compatible).
- Vous menez un projet recherche / académique, même avec un endpoint
  web public — l'AGPLv3 n'a pas de problème avec ça tant que vous
  publiez votre source modifiée.

En cas de doute, **demandez avant de déployer** — `thomas.signorelli@proton.me`.

---

## Tarification

| Palier | Cas d'usage | Frais annuels | Ce qui est couvert |
|---|---|---|---|
| **Startup** | <10 employés, mono-site, mono-produit | Sur demande | 1 déploiement production, 1 SKU OEM, support email |
| **PME** | 10-200 employés, multi-site, multi-produit | Sur demande | Déploiements internes illimités, 3 SKU OEM, support email + GitHub prioritaire |
| **Entreprise** | >200 employés OU MSP redistribuant à des clients | Sur demande | Illimité, assistance intégration, contact nommé, SLA, input sur la roadmap fonctionnelle |
| **Redistribution OEM** | Bundle matériel, firmware embarqué, white-label | Sur demande | Royaltie à l'unité OU forfait, workflow d'approbation marketing |
| **Académique / Non-lucratif** | Labo de recherche, ONG, secteur public pré-revenue | **Gratuit** | L'AGPLv3 par défaut suffit ; licence commerciale disponible pro-bono sur demande pour les cas-limites de conformité juridique |

Les frais sont annuels, renouvelables. Nous ne faisons pas de licences
perpétuelles — l'écosystème évolue trop vite. Les licenciés existants
gardent une retombée perpétuelle vers *la dernière version qu'ils ont
payée* s'ils ne renouvellent pas, sans mise à jour / support au-delà.

Tous les tarifs sont chiffrés sur demande après un court appel de
cadrage (typiquement 30 minutes). Nous ne publions pas de tarifs car
ils varient fortement selon l'échelle de déploiement, le niveau de
support et les besoins de personnalisation.

---

## Ce qui est inclus avec une licence commerciale

- **Droits d'usage commercial** — intégrer Nokido dans des produits
  propriétaires / closed-source sans les obligations de divulgation
  source AGPLv3.
- **Réponse prioritaire** — issues et questions sécurité traitées
  avant le trafic communautaire (cible : 24h accusé de réception jour
  ouvré, 72h évaluation initiale).
- **Assistance intégration personnalisée** — sessions de pair-programming
  pour câbler Nokido dans votre stack (payant en supplément, vendu
  séparément).
- **Influence sur la roadmap** — les clients tier Entreprise ont voix
  au chapitre sur la roadmap trimestrielle.
- **Indemnisation** — indemnité limitée contre les réclamations IP
  portant sur le code Nokido lui-même (hors dépendances tierces —
  celles-ci portent leurs propres garanties amont).
- **Droits d'audit** — votre équipe juridique / conformité peut
  examiner la source pour audit sécurité sous NDA standard.

Ce qui n'est **pas** inclus :

- Support téléphonique 24/7 (disponible en option payante séparée).
- Séquestre du code source (accord séparé).
- Statut public revendeur / partenaire (programme séparé).

---

## Comment obtenir une licence commerciale

1. **Email** `thomas.signorelli@proton.me` avec pour objet
   `[Nokido Commercial License]`.
2. Indiquer dans le corps :
   - Nom de la société + juridiction (UE / US / autre).
   - Description du cas d'usage (1-2 paragraphes suffisent).
   - Échelle de déploiement attendue (nombre d'utilisateurs internes,
     nombre de clients externes si SaaS, nombre d'appareils si OEM).
   - Calendrier de démarrage souhaité.
3. Nous planifions un appel de cadrage de 30 min sous 5 jours ouvrés.
4. Nous envoyons un projet d'accord sous 10 jours ouvrés post-appel.
5. Après signature, la licence est active. Vous pouvez expédier.

Les termes standards sont **non-exclusifs, non-transférables, par
entité**. Les groupes multi-entités (holding + filiales) nécessitent un
accord cadre.

---

## Compatibilité de licence avec les dépendances tierces

Nokido dépend de plusieurs bibliothèques open-source ayant leurs
propres licences. La plupart sont permissives (MIT, Apache 2.0, BSD),
certaines sont compatibles copyleft. Lorsque vous prenez une licence
commerciale sur Nokido, vous restez responsable du respect des
licences amont de votre ensemble de dépendances.

Dépendances notables et leurs licences (non exhaustif, voir
`pyproject.toml` pour la liste actuelle) :

| Dépendance | Licence | Compatible avec notre licence commerciale ? |
|---|---|---|
| FastAPI, Starlette, Uvicorn | MIT / BSD | ✅ Oui |
| FAISS-cpu | MIT | ✅ Oui |
| Numpy, Pydantic | BSD / MIT | ✅ Oui |
| `litellm` | MIT | ✅ Oui |
| `pymdp` | MIT | ✅ Oui |
| `ncps` | Apache 2.0 | ✅ Oui |
| `sentence-transformers` | Apache 2.0 | ✅ Oui |
| Tree-sitter Python | MIT | ✅ Oui |
| Ollama (runtime, non bundled) | MIT | ✅ Oui (vous livrez le vôtre) |
| Poids modèle BGE-M3 | MIT (Beijing Academy of AI) | ✅ Oui |

Si vous comptez livrer Nokido avec un LLM tiers, vérifiez séparément
la licence des poids du LLM — certains modèles commerciaux (Claude,
GPT-4) ont des termes restrictifs même accédés via API.

---

## Questions

**Q. Puis-je évaluer Nokido sous AGPLv3 d'abord, puis convertir en
commercial plus tard ?**

Oui. L'AGPLv3 est libre d'essai. Convertissez en commercial avant de
servir des utilisateurs finaux sur un réseau avec une variante
closed-source.

**Q. Et si j'oublie de convertir et que je livre par erreur un SaaS
closed-source ?**

Vous êtes en violation de l'AGPLv3. La correction est soit (a) publier
vos modifications sous AGPLv3 rétroactivement, soit (b) acheter la
licence commerciale rétroactivement. L'option (b) convient — nous ne
litigons pas les erreurs de bonne foi.

**Q. La licence commerciale couvre-t-elle les sous-projets ?**

Elle couvre tout projet qui utilise du **code Nokido** —
`app/forge_*.py`, `tools/forge_*.py`, les services Rust, le proxy Deno.
Elle ne couvre **pas** les dépendances tierces (qui portent leurs
propres licences).

**Q. Puis-je obtenir une licence perpétuelle ?**

Non — voir section Tarification. Le monde évolue trop vite pour que ce
soit équitable des deux côtés. Vous obtenez une retombée perpétuelle
vers votre dernière version payée, ce qui vous protège du
vendor-locking.

**Q. Le projet peut-il être acquis ?**

En principe oui. Toute acquisition honorerait les engagements de
licence commerciale existants. Discutons si pertinent.

---

*Ce document est informationnel et ne constitue pas en soi une licence.
Les termes juridiquement contraignants sont dans l'accord signé échangé
après cadrage. Une re-licence du projet vers un modèle fondamentalement
différent devrait respecter tous les termes des licences commerciales
existantes.*

📧 `thomas.signorelli@proton.me` · Dernière mise à jour : 2026-05-27
