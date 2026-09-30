# Audit de Conformité et d'Ingestion des Normes (RFC)

**Date:** 2026-09-03 20:14
**Cible:** Base de connaissances Air-Gapped Nokido (World Model)
**Miroir local:** `%NOKIDO_ROOT%\data\rfc_mirror`
**Base vérifiée:** `%NOKIDO_DATA%\embeddings.db`

Chaque norme est ingérée depuis le miroir local (zéro réseau) puis **recomptée
en base** : la colonne « en base » est une mesure indépendante du retour de
l'outil, et non sa paraphrase. `n/d` = la base n'a pas pu être lue (état
ILLISIBLE), ce qui n'est PAS un zéro.

## Fondations Réseau & Web

- ✅ **RFC 9110** : 338 chunk(s) en base (`source=rfc:rfc9110`).
- ✅ **RFC 8259** : 18 chunk(s) en base (`source=rfc:rfc8259`).
- ✅ **RFC 8895** : 72 chunk(s) en base (`source=rfc:rfc8895`).
- ✅ **RFC 3986** : 91 chunk(s) en base (`source=rfc:rfc3986`).
- ✅ **RFC 5234** : 16 chunk(s) en base (`source=rfc:rfc5234`).
- ✅ **RFC 8785** : 27 chunk(s) en base (`source=rfc:rfc8785`).

## Authentification & Délégation (OAuth)

- ✅ **RFC 6749** : 101 chunk(s) en base (`source=rfc:rfc6749`).
- ✅ **RFC 6819** : 103 chunk(s) en base (`source=rfc:rfc6819`).
- ✅ **RFC 8693** : 42 chunk(s) en base (`source=rfc:rfc8693`).

## Sécurité Zero-Trust & Identité

- ✅ **RFC 9449** : 62 chunk(s) en base (`source=rfc:rfc9449`).
- ✅ **RFC 7519** : 40 chunk(s) en base (`source=rfc:rfc7519`).
- ✅ **RFC 8725** : 21 chunk(s) en base (`source=rfc:rfc8725`).

## IP, routage et adressage (netcfg-agent)

- ✅ **RFC 791** : 53 chunk(s) en base (`source=rfc:rfc791`).
- ✅ **RFC 1812** : 271 chunk(s) en base (`source=rfc:rfc1812`).
- ✅ **RFC 8200** : 57 chunk(s) en base (`source=rfc:rfc8200`).
- ✅ **RFC 2131** : 70 chunk(s) en base (`source=rfc:rfc2131`).
- ✅ **RFC 1918** : 15 chunk(s) en base (`source=rfc:rfc1918`).
- ✅ **RFC 9568** : 55 chunk(s) en base (`source=rfc:rfc9568`).

## QoS / DiffServ (netcfg-agent)

- ✅ **RFC 2474** : 34 chunk(s) en base (`source=rfc:rfc2474`).
- ✅ **RFC 2475** : 62 chunk(s) en base (`source=rfc:rfc2475`).
- ✅ **RFC 4594** : 99 chunk(s) en base (`source=rfc:rfc4594`).

## Supervision SNMP (netcfg-agent)

- ✅ **RFC 3411** : 84 chunk(s) en base (`source=rfc:rfc3411`).
- ✅ **RFC 3412** : 58 chunk(s) en base (`source=rfc:rfc3412`).
- ✅ **RFC 3413** : 90 chunk(s) en base (`source=rfc:rfc3413`).
- ✅ **RFC 3414** : 118 chunk(s) en base (`source=rfc:rfc3414`).
- ✅ **RFC 3415** : 46 chunk(s) en base (`source=rfc:rfc3415`).
- ✅ **RFC 3418** : 27 chunk(s) en base (`source=rfc:rfc3418`).

## Accès administratif : SSH, AAA, journaux, temps (netcfg-agent)

- ✅ **RFC 4251** : 47 chunk(s) en base (`source=rfc:rfc4251`).
- ✅ **RFC 4252** : 23 chunk(s) en base (`source=rfc:rfc4252`).
- ✅ **RFC 4253** : 44 chunk(s) en base (`source=rfc:rfc4253`).
- ✅ **RFC 4254** : 31 chunk(s) en base (`source=rfc:rfc4254`).
- ✅ **RFC 5424** : 54 chunk(s) en base (`source=rfc:rfc5424`).
- ✅ **RFC 5905** : 136 chunk(s) en base (`source=rfc:rfc5905`).
- ✅ **RFC 2865** : 87 chunk(s) en base (`source=rfc:rfc2865`).
- ✅ **RFC 2866** : 29 chunk(s) en base (`source=rfc:rfc2866`).
- ✅ **RFC 8907** : 61 chunk(s) en base (`source=rfc:rfc8907`).

## Synthèse de l'Audit
- **Normes ciblées :** 36
- **Normes présentes en base :** 36
- **Chunks RFC en base :** 2582
- **Normes traitées par ce run :** 0

> Les chunks sont stockés TEXT-ONLY ; les vecteurs sont remplis en asynchrone par `forge_embed_auto_trigger`. « En base » ne veut donc pas encore dire « vectorisé ».