# TAILSCALE_MIGRATION

Nokido Sovereign Hub - migration de bind localhost vers tailnet Tailscale.

Status : PLAN. Pas execute. Voir `tools/migrate_to_tailscale.ps1` (script
self-elevation NSSM patcher) et `tools/rollback_tailscale.ps1` (restore
backups AppParameters).

## 1. Why

Nokido tourne actuellement avec tous les services binds sur `127.0.0.1`
(audit securite 2026-05-02 : DenoProxy patche, hub deja localhost). Pour
acceder aux services depuis un deuxieme poste de dev (laptop, VM,
phone-as-router) sans ouvrir l hote au public, on passe par Tailscale.
Tailnet WireGuard mesh = chiffrement bout en bout, identite par device,
ACL fine grain, zero port public expose. Aucun NAT, aucun reverse proxy
public, pas de port forward firewall internet. Reachability uniquement
via tailnet.

## 2. Pre-requis

A faire MANUELLEMENT par l utilisateur AVANT de lancer le script.

### 2.1 Installation Tailscale

- Compte cree sur https://login.tailscale.com (Personal plan free 100
  devices suffit).
- Client Windows installe : `winget install --id Tailscale.Tailscale -e`.
- `tailscale up` execute au moins une fois sur cette machine pour
  l associer au tailnet (machine apparait dans Admin console).
- Verifier : `tailscale status` doit afficher l hote en "online" avec
  une IP `100.x.y.z`.
- Verifier : `tailscale ip -4` retourne UNE seule ligne (sinon le script
  prend la premiere).

### 2.2 ACL design

L ACL Tailscale est la couche reseau. Bearer token reste la couche
applicative (NON negociable, voir section 5).

ACL minimaliste (a coller dans Admin console > Access Controls) :

```json
{
  "tagOwners": {
    "tag:laforge-host":  ["autogroup:admin"],
    "tag:laforge-agent": ["autogroup:admin"]
  },
  "acls": [
    {
      "action": "accept",
      "src":    ["tag:laforge-agent"],
      "dst":    ["tag:laforge-host:7400,7401,8000,8090,8091,8092,8766,8767,8769,11434,1234"]
    }
  ],
  "ssh": []
}
```

Ensuite, sur Admin console > Machines :

- Tagger CETTE machine Windows (l hote Nokido) : `tag:laforge-host`.
- Tagger les devices clients (laptop autre, mobile) : `tag:laforge-agent`.

Sans ACL = tout le tailnet voit tout, ce qui defait l interet. Faire
l ACL AVANT le bind 0.0.0.0 ou tailnet IP.

### 2.3 NSSM access

Script lance avec elevation. NSSM doit etre dans
`C:\ProgramData\chocolatey\bin\nssm.exe` (deja le cas, voir
`install_netcfg_mcp_nssm.ps1`).

## 3. Decision : choix du bind

### 3.1 Options envisagees

- **A. Bind tailscale interface IP `100.x.y.z`** : un seul socket, lie
  a l interface tailnet. Si Tailscale tombe, services down. IP change
  si machine quitte le tailnet et revient.
- **B. Bind `127.0.0.1` + reverse proxy `tailscale serve`** : conserve
  le bind actuel, expose via TS userspace proxy. Avantages :
  certificats TLS automatiques (`tailscale cert`), loopback intact si
  tailnet down. Desavantage : couche supplementaire, doit etre lance
  par service ou en arriere-plan, double config.
- **C. Bind `0.0.0.0` + Windows Firewall regle stricte allow only
  `100.64.0.0/10`** : un seul socket, simple, fonctionne meme si
  Tailscale demarre en retard. Gros risque si la regle firewall saute.

### 3.2 Recommandation

**Option A : bind sur l IP tailnet `100.x.y.z`.**

Rationale :

- Surface d attaque minimale : si Tailscale tombe, le port n est plus
  joignable du tout (pas de fallback vers 0.0.0.0).
- Pas de dependance a une regle firewall fragile (option C peut casser
  silencieusement si profile reseau change Public > Private).
- Pas de couche proxy supplementaire (option B), donc pas de doubt sur
  les en-tetes Bearer token transmis.
- L IP `100.x.y.z` est stable tant que la machine reste dans le tailnet
  (Tailscale assigne une IP permanente par device).

Tradeoff accepte : si l utilisateur veut acceder depuis le poste local
lui-meme, il doit utiliser l IP tailnet ou rajouter `127.0.0.1` en bind
secondaire (nginx, ou double-NSSM). Pour la plupart des services
Nokido avec FastAPI / uvicorn, on peut binder `100.x.y.z` ET garder
loopback en parallele via deux instances. Le script migre vers le bind
unique tailnet pour rester simple. Garder loopback est explicitement
hors scope de cette premiere passe (rollback dispo si gene).

### 3.3 Snippets per service

Le script automatise tout. Pour reference, voici ce qui change manuellement :

| Service NSSM           | Param actuel                                      | Param apres                                              |
|------------------------|---------------------------------------------------|----------------------------------------------------------|
| LaForgeMCP             | `--host 127.0.0.1 --port 8766`                    | `--host 100.x.y.z --port 8766`                           |
| NokidoWebHub          | `--host 127.0.0.1 --port 7400`                    | `--host 100.x.y.z --port 7400`                           |
| NokidoDenoHubMCP      | `serve ... 127.0.0.1:8769`                        | `serve ... 100.x.y.z:8769`                               |
| NokidoDenoWebHub      | `serve ... 127.0.0.1:7401`                        | `serve ... 100.x.y.z:7401`                               |
| NokidoDenoProxy       | `--host 127.0.0.1 --port 8000`                    | `--host 100.x.y.z --port 8000`                           |
| NokidoNetcfgMCP       | `--host 127.0.0.1 --port 8767`                    | `--host 100.x.y.z --port 8767`                           |

Ollama et llama.cpp et LM Studio se configurent via env vars / GUI :

- Ollama : `setx OLLAMA_HOST "100.x.y.z:11434" /M` puis restart service.
- llama.cpp natif (`llamacpp_native` 8090/8091/8092) : meme pattern NSSM
  AppParameters `--host`.
- LM Studio :1234 : GUI > Local Server > Network > bind address.
  Ajout manuel necessaire (pas de config file expose).

### 3.4 Variables d environnement clients

Apres migration, les clients qui appellent le hub doivent pointer vers
la nouvelle IP. Mettre a jour :

- `LAFORGE_HUB_URL=http://100.x.y.z:8766` dans `.env`, `cline_mcp_settings.json`,
  `claude_desktop_config.json`.
- `OLLAMA_HOST=100.x.y.z:11434` partout ou utilise.
- `forge_python_bin.py` : aucun changement (subprocess local).

## 4. Auth posture

Tailscale est UNIQUEMENT une couche reseau. Il garantit :

- Chiffrement WireGuard.
- Identite device (cert + key par device).
- ACL grain port et tag.

Tailscale ne garantit PAS :

- Que l agent qui appelle est legitime (tag suffit pour ouvrir le port).
- Que les requetes ne sont pas replayees / falsifiees au niveau app.

**Le Bearer token reste obligatoire sur LaForgeMCP, NokidoWebHub,
NokidoDenoHubMCP, NokidoDenoWebHub, NokidoDenoProxy, netcfg-agent-mcp.**
Si un device tagge `laforge-agent` est compromis, l ACL le laissera
passer mais le token applicatif limite la casse.

### 4.1 tailscale serve (optionnel)

Pour publier le hub avec un nom DNS et un cert valide :

```powershell
tailscale serve --bg --https=443 --set-path=/ http://localhost:8766
```

Avantages : `https://machine.tailnet.ts.net/` au lieu de
`http://100.x.y.z:8766/`, cert TLS automatique. Inconvenient : couche
supplementaire, le bearer token en header Authorization passe quand
meme, mais on confond tailscale serve et bind tailnet. Recommandation :
NE PAS activer dans cette migration. A reserver pour une V2 si besoin
HTTPS interne. Plan actuel = HTTP tailnet uniquement (chiffrement deja
assure par WireGuard underlay).

## 5. Verification post-migration

A faire manuellement apres execution du script :

```powershell
# 1. Listing ports tailnet
$tsip = (tailscale ip -4 | Select-Object -First 1).Trim()
foreach ($p in 7400,7401,8000,8090,8091,8092,8766,8767,8769) {
    $r = Get-NetTCPConnection -LocalAddress $tsip -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if ($r) { "OK  $tsip`:$p" } else { "MISS $tsip`:$p" }
}

# 2. Test bearer auth depuis un autre device tailnet
curl -H "Authorization: Bearer $env:LAFORGE_TOKEN" http://100.x.y.z:8766/health

# 3. Pas de regression localhost
curl http://127.0.0.1:8766/health  # doit FAIL (refused) - confirme bind tailnet only
```

## 6. Rollback

Le script `migrate_to_tailscale.ps1` ecrit avant chaque modification un
backup dans `LaForge/sandbox/nssm-backups/<svc>-<timestamp>.txt` qui
contient l ancien AppParameters complet. Pour annuler :

```powershell
.\LaForge\tools\rollback_tailscale.ps1
```

Le rollback :

1. Liste les backups sandbox/nssm-backups/.
2. Pour chaque service, prend le BACKUP LE PLUS RECENT.
3. Restaure AppParameters via `nssm set <svc> AppParameters <old>`.
4. Restart service.
5. Verifie LISTEN sur 127.0.0.1.
6. Supprime la regle firewall `LaForge-Tailnet-Inbound` si presente.

Si un service ne redemarre pas en localhost apres rollback : verifier
les logs `<svc>.stderr.log`. Cas typique : process zombie sur l ancien
port - kill et relancer le service NSSM.

## 7. Liens entre modules co-modifies

Cette migration touche purement le PLAN RESEAU. Aucun fichier `app/`
modifie. Seuls touches :

- `LaForge/docs/TAILSCALE_MIGRATION.md` (ce fichier).
- `LaForge/tools/migrate_to_tailscale.ps1` (script forward).
- `LaForge/tools/rollback_tailscale.ps1` (script reverse).
- AppParameters NSSM des 6 services HTTP cibles (mute via nssm set).
- 1 regle Windows Firewall : `LaForge-Tailnet-Inbound`.
- Optionnellement : env vars Ollama, GUI LM Studio (manuel hors script).

Apres execution reussie, anchor obligatoire :

```python
from forge_self_correction import anchor_solution
anchor_solution(
    problem="Bind localhost limitait l acces multi-device dev",
    solution="Migration NSSM AppParameters de 127.0.0.1 vers tailnet IP via tools/migrate_to_tailscale.ps1, ACL Tailscale tag:laforge-host/agent, bearer token conserve",
    example="LaForge\\tools\\migrate_to_tailscale.ps1",
    domain="security",
)
```

## 8. Hors scope

- **Migration cloud public** : non. Si besoin acces internet, passer par
  funnel Tailscale (`tailscale funnel`) ou un VPS reverse - sujet
  separe.
- **mTLS applicatif** : non. Bearer token suffit pour ce scope.
- **Rotation IP tailnet** : non documente ici. Tailscale rassigne la
  meme IP par device tant que le device n est pas supprime du tailnet.
- **Multi-tailnet** : non. Un seul tailnet utilisateur.
- **Forge LM Studio** : config GUI manuelle, hors script.
- **Ollama OLLAMA_HOST** : commande `setx` documentee section 3.3,
  hors script (env var globale, sensible).
