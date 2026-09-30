# ADR-003 : Gestion des secrets — WCM local + Vault si mise à l'échelle
Date : 2026-04-27 | Statut : ACTIF (WCM) | PLANIFIÉ (Vault si industrialisation)

## Actuel — Windows Credential Manager
- forge_secrets.py : WCM → os.environ → Nokido.env
- 30+ secrets dans WCM (GROQ, GEMINI, MISTRAL, GITHUB...)
- forge_agent_proxy._load_api_key() bypass WCM → à corriger (SecretGuard faux positif)

## Futur — Hashicorp Vault (si multi-machine / compliance / rotation auto)
Vault pertinent quand :
- 2+ machines accèdent aux secrets
- Audit trail obligatoire (SOC2, RGPD)
- Rotation automatique requise
Package : pip install hvac
Migration : migrate_secrets_to_vault.py (à créer)
Ref : https://developer.hashicorp.com/vault/docs/get-started
