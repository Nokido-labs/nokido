**1. RISQUES top-3**
- **Crash loop garanti** : NSSM restart aveugle + erreur synchrone au démarrage = cycle infini. 2s delay ne corrige rien, ça amplifie la charge.
- **Corruption silencieuse** : `UnicodeDecodeError` signale perte de contrôle sur le flux binaire. Le 0x90 est un PE header ou dump mémoire qui pollue MCP JSON. Tu ignores des données critiques.
- **Débogage à l'aveugle** : stdout 0 byte + `_bridge_log` commenté = pas de traces, pas de metrics, pas de root cause. Tu opères en mode "pray and restart".

**2. FIXES top-3 (lignes code)**
```python
# Q1+Q2: Hub _readerthread → decode avec fallback strict
# Ligne à changer dans hub.py: _readerthread()
data = os.read(self.fd, 65536).decode('utf-8', errors='replace')  # Remplace 0x90 par , pas de crash

# Q2: Force flush immédiat stdout pour NSSM
# Au début de mcp_stdio_bridge.py
import sys; sys.stdout.reconfigure(line_buffering=True, write_through=True)  # Pas de buffer, écriture synchrone

# Q3: Répare _fallback_stdio() + NameError
# L348: remplace le commentaire par
_bridge_log = logging.getLogger("mcp.bridge")  # Corrige NameError
os.execv(sys.executable, [sys.executable] + sys.argv)  # Re-exécute proprement, pas de zombie NSSM
```

**3. INSTRUMENTATION manquante**
- **Metrics exit counter** : `prometheus_client.Counter('bridge_exit_total', 'Raison', ['code'])` sur chaque `sys.exit()`. Sinon NSSM restart est invisible.
- **Structured logging** : JSON sur stderr, pas stdout. Configure `logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)` pour éviter le buffer 0 byte.
- **Process watchdog** : Thread qui `psutil.pid_exists(parent_pid)` toutes les 5s. Si hub meurt, bridge s'auto-kill (`os._exit(1)`). Évite les orphans.

**4. ARCHI 3 reco**
- **Health endpoint** : Hub expose `/healthz` qui retourne 200 + `{"bridge_pids": [...]}`. NSSM curl → restart seulement si health fail, pas sur crash aveugle.
- **Circuit breaker sur le pipe** : Si 3 `UnicodeDecodeError` en 10s, bridge coupe le flux, log l'incident, et redémarre proprement avec `os.execv`. Pas de retry immédiat.
- **Séparer bridge du hub** : Bridge en Go/rust qui gère stdio binaire → JSON vers hub HTTP. Python est trop fragile sur les pipes binaires sous Windows. Le hub ne doit jamais faire `subprocess` direct, c'est un service pur HTTP.