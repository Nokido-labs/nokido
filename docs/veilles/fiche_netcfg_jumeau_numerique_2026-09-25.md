# Fiche de sortie — Veille « netcfg : jumeau numérique d'un site pauvre » (2026-09-25)

Demande owner (25/09) : un module netcfg pleinement fonctionnel quel que soit le format (Visio ou autre,
KeePass ou autre) ; avec un fichier pauvre en données de switch, la cartographie du site se construit ;
découverte des modèles, longueurs de câbles ; « pousse au max la détection et la construction d'un schéma
potentiellement absent » ; veilles DÉTAILLÉES sur chaque dépôt cité.

Sources (clones superficiels, lecture seule, `E:\nokido_veille_netcfg\`) : netbox `785d0b9085fe` ·
netdisco `6dcb47debed9` · snmp-info `a3c0eddfb835` · oxidized `2cb5053566df` · nautobot `38953ac3004d` ·
nautobot-device-onboarding `05d5d9e5716a` · napalm `820a06b2069e` · scrapli `343e149b6eba` ·
vsdx `6703e6c2c906` · visioeditor `4e05b671c6cf` · KeepassDecrypt `87e675b5949a` ·
Keepass-access-libs `dead83a1460d`. Code netcfg = dépôt séparé `netcfg-agent-web` (servi sur :7500 par
`demo/serve_ui.py`, qui met ce dépôt en tête de `sys.path` — le jumeau `Nokido/app/netcfg` n'est PAS servi).

## 1. PATTERNS

| # | Pattern | Preuve (clone, fichier:ligne) |
|---|---|---|
| P1 | Un connecteur Visio EST un lien : `<Connect FromSheet=connecteur FromCell=BeginX/EndX ToSheet=forme>` | vsdx `vsdx/connectors.py:14-24` ; `vsdx/shapes.py:836-853` (`connected_shapes`) |
| P2 | Trois formats Visio : `.vsdx` (OOXML), `.vdx` (XML 2003), `.vsd` (binaire) | visioeditor `packages/vsdx/lib/src/parser/vsd/vsd_parser.dart`, `test/vdx_import_test.dart`, `test/vsd/libvisio_vsd_diff_test.dart` |
| P3 | Getters normalisés de découverte | napalm `napalm/base/base.py:309` `get_facts`, `:590` `get_lldp_neighbors_detail`, `:863` `get_arp_table`, `:1010` `get_mac_address_table`, `:1502` `get_optics` |
| P4 | Voisins par SNMP sans CLI | snmp-info `LLDP.pm:73` `lldp_rem_sysname => lldpRemSysName` ; `CDP.pm:64-65` `cdpCacheDeviceId` / `cdpCacheDevicePort` ; `Bridge.pm:242,253` `fw_mac` / `fw_port` (FDB) |
| P5 | **Uplink INFÉRÉ par la table MAC** quand LLDP manque | netdisco `Macsuck/Nodes.pm:567-569` « two ways to detect "uplink" : a neighbor was discovered using CDP/LLDP ; a mac addr is seen which belongs to any device port/interface » ; `:617-629` « port %s is probably an uplink » → `is_uplink => true` |
| P6 | **La topologie DÉCLARÉE à la main prime sur l'observée** | netdisco `Discover/Neighbors.pm:184-187` « has manually defined topology » → `next NEIGHBOR` |
| P7 | Le câble est un objet de premier rang : longueur + unité + statut | netbox `dcim/models/cables.py:95,139-154` (`length`, `length_unit`, `_abs_length` normalisé en mètres) ; `dcim/choices.py:2033-2039` `connected` / `planned` |
| P8 | Commandes de découverte par plateforme = données (commande + parseur + extraction) | nautobot-device-onboarding `command_mappers/hp_comware.yml:5-29` (`display device manuinfo` → numéro de série, modèle) ; `hp_procurve.yml:155` `show lldp info remote-device detail` ; 14 plateformes, dont aruba_aoscx, hp_comware, hp_procurve |
| P9 | Sauvegarde de config par modèle de constructeur | oxidized `lib/oxidized/model/{aoscx,comware,procurve,vrp,netgear}.rb` — les 5 constructeurs de netcfg couverts |
| P10 | KeePass KDBX3/4 (AES, ChaCha20, Argon2d/id) ; mot de passe maître dans le magasin d'identifiants de l'OS | KeepassDecrypt `src/test/resources/test_chacha_argon2id.kdbx` (+8) ; Keepass-access-libs `rust/kdbx-credentials/tests/credential_manager_integration.ps1:11` (`cmdkey`) |

**Absence mesurée** : aucune des 12 sources ne mesure une longueur de câble par TDR (recherche
`tdr|cable.?diag|virtual-cable-test|cable-diagnostics` : seuls des faux positifs — base64, motifs de
tirets). La longueur « observée » reste à sourcer dans la doc constructeur, jamais à inventer.

## 2. NOKIDO_EXISTING (netcfg-agent-web @ `2e53319`)

| Brique | Où | Niveau |
|---|---|---|
| Lecture des stencils (racks, équipements, U) | `netcfg/vsdx_reader.py` `classify()` | VERIFIED (tests historiques) |
| **Connecteurs → liens, extrémités/IP → nœuds, site squelette** | `vsdx_reader.py` `_extract_connects`, `indices_du_texte` ; `session.py` `vsdx_to_network_v2`, `load_user_vsdx` | **MEASURED 25/09** : NR `tests/test_visio_pauvre.py` (rouge prouvé) + sonde chemin réel (upload + 8 routes GET = 200) sur `Network Topology.vsdx` public : 6 nœuds, 5 liens |
| Longueurs de câble par géométrie de page | `netcfg/topology.py:81` `cable_lengths(network, scale_m_per_px)` | DECLARED (existe, non recoupé avec les connecteurs) |
| Catalogue de modèles (stencils constructeur) | `netcfg/stencils.py:266` `resolve_model` | DECLARED |
| KeePass en lecture seule, paresseux | `netcfg/credentials.py` `KeePassProvider` ; `session.py` `load_keepass` | DECLARED ; `pykeepass` PRÉSENT dans l'interpréteur du service (mesuré, `services.toml` `PYTHON`) |
| Commandes par constructeur | `netcfg/templates/*.yml` `commands:` (show_running, show_version, backup_startup, rollback…) | MEASURED : **aucune commande de découverte** (LLDP, table MAC, inventaire, câble) — recherche vide |
| Chemin SSH réel (gaté `offline`) + mocks constructeurs | `netcfg/core.py` `Equipment` ; `tests/mocks/vendors/*` | VERIFIED en mock, jamais sur matériel |
| Numéro de série ↔ Visio | `netcfg/inventory.py:113` `match_sn_with_visio` | DECLARED |

## 3. EVIDENCE
- Symptôme owner reproduit mot pour mot en NR (« Aucun rack ni equipement detecte dans le .vsdx »), puis levé.
- Le code portait l'aveu `links: []  # extraction <Connect> = TODO v2` : le lien était DANS le fichier.
- La provenance d'un fait (preuve `DECLARE:` / `INFERE:`) vit dans `classify()` et les avertissements,
  mais **pas dans le modèle réseau** : la liste blanche v2 (`netcfg/visio.py:34-53`) n'a aucun champ pour elle.

## 4. GAPS
1. **Provenance absente du modèle** : il faut un registre de preuves à côté du réseau v2 (par fait :
   DÉCLARÉ / OBSERVÉ / INFÉRÉ / CONTREDIT, source, horodatage), exposé par l'API — sans casser la liste
   blanche v2 (`visio._validate_network`). Règles de fusion reprises de P6 : le déclaré à la main prime ; puis
   l'observé (LLDP/CDP) ; puis le dessiné (connecteur) ; puis l'inféré (FDB P5, libellé).
2. **Aucune commande de découverte** dans les YAML constructeurs : étendre `commands:` avec des lectures
   seules (`discover_lldp`, `discover_mac_table`, `discover_inventory`), sur le modèle de P8 ; Huawei et
   Netgear n'ont pas de mapper de référence → à écrire depuis la doc, marqués DÉCLARÉ-par-doc.
3. **Inférence d'uplink par FDB** (P5) absente.
4. **Longueur de câble** : calculée depuis le connecteur (`longueur_trace_pouces`) mais non transportée
   vers `topology.cable_lengths` ; longueur OBSERVÉE (TDR) sans source fiable (voir absence mesurée).
5. **Formats** : `.vsd` binaire, `.vdx`, draw.io, inventaire CSV/XLSX, et KeePass comme PREUVE
   D'EXISTENCE d'un équipement (une entrée hôte/URL = un nœud DÉCLARÉ) — non gérés.
6. Pas de « nouveau site vide » sans fichier (le squelette n'existe qu'après un import).

## 5. MINIMAL_EXPERIMENT (sans matériel, sans écrivain RAG)
- Ajouter `discover_lldp` aux mocks existants (`tests/mocks/vendors/mock_{comware,procurve,aoscx}.py`),
  parser la sortie, fusionner avec les liens d'un Visio pauvre : compter DÉCLARÉ∩OBSERVÉ, DÉCLARÉ seul,
  OBSERVÉ seul, CONTREDIT (même port, voisin différent).
- Charger la fixture publique `Keepass-access-libs/.../it-dept.kdbx` (mot de passe de test publié) et
  lister les entrées hôte/URL comme nœuds DÉCLARÉS ; recouper avec les IP lues dans le Visio.
- Découverte sur matériel réel : **lecture seule, et seulement après confirmation owner**.

## 6. NR
- `test_fusion_declare_observe` : lien Visio A–B + LLDP A–B → OBSERVÉ confirmant ; lien Visio A–C + LLDP A:p1→D
  sur le même port → CONTREDIT, jamais écrasé en silence.
- `test_keepass_preuve_d_existence` : une entrée KeePass d'hôte localhost et un nœud Visio d'IP localhost → un
  seul nœud, deux preuves.
- `test_uplink_par_fdb` : la table MAC du switch A contient la MAC d'un port de B → lien A–B INFÉRÉ, avec
  la règle P6 (une topologie manuelle l'emporte).

## 7. DECISION
| Primitive | Décision | Raison |
|---|---|---|
| P1 connecteurs = liens | **ADOPT — fait** (`2e53319`) | mesuré sur fichier public |
| P5 uplink par FDB + P6 priorité du manuel | **ADOPT** | c'est le cœur de « construire un schéma absent » sans LLDP |
| P7 câble longueur+unité+statut planned/connected | **ADOPT** (dans le registre de preuves) | distingue DÉCLARÉ (plan) de CONNECTÉ (observé) |
| P8 commandes = données par plateforme | **ADOPT** en étendant `templates/*.yml` | pas de système parallèle : la brique existe |
| P3 napalm | DEFER | dépendance lourde ; netcfg a son SSH + ses mocks ; reprendre la FORME des getters |
| P4 SNMP::Info | DEFER | Perl ; reprendre les OID (LLDP-MIB, CDP, BRIDGE-MIB) si la voie SNMP est choisie |
| P9 oxidized | REJECT comme dépendance | Ruby ; netcfg sauvegarde déjà ; référence de commandes seulement |
| P2 `.vsd`/`.vdx` | DEFER | parseur Dart ; évaluer une conversion (LibreOffice) avant tout code |
| P10 KeePass | ADOPT les fixtures publiques ; le mot de passe maître au coffre rejoint la demande owner « accès SSH au vault » | |
