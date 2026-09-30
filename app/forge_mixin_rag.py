"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_mixin_rag
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
rag_mixin.py — RAGMixin pour DevOpsApp (Nokido v13.6+).
self est toujours l'instance DevOpsApp finale (MRO Python).
"""


try:
    import aiohttp
except ImportError:
    aiohttp = None
import asyncio, re, sys as _sys
import logging

logger = logging.getLogger(__name__)

from pathlib import Path as _Path_lp

# Chemins calculés depuis __file__ — fiables même hors __main__
_APP_DIR = _Path_lp(__file__).resolve().parent  # …/LaForge/app/
_ROOT_DIR = _APP_DIR.parent  # …/LaForge/
_DATA_DIR = _ROOT_DIR / "data"
_LOGS_DIR = _ROOT_DIR / "logs"
try:
    from textual.app import App, ComposeResult
    from textual.widgets import Static, Input, Button, RichLog, Label, ListView
    from textual import events
    from rich.markup import escape as _rich_escape
    from rich.text import Text
except ImportError:
    App = object
    Widget = object
    RichLog = object
    Static = object
    Button = object
    Input = object
    events = None
    _rich_escape = str
    Text = str


_LAFORGE_REF = None


def _lf() -> object:
    """Lf."""
    global _LAFORGE_REF
    if _LAFORGE_REF is not None:
        return _LAFORGE_REF
    m = _sys.modules.get("__main__")
    if m is not None and hasattr(m, "_DATA_DIR"):
        _LAFORGE_REF = m
        return m
    import os as _os

    _here = _os.path.dirname(_os.path.abspath(__file__))
    for mod in list(_sys.modules.values()):
        f = getattr(mod, "__file__", None) or ""
        if f and _os.path.dirname(_os.path.abspath(f)) == _here:
            if hasattr(mod, "_DATA_DIR"):
                _LAFORGE_REF = mod
                return mod
    return m


class RAGMixin:
    """Mixin extrait de DevOpsApp — RAGMixin."""

    async def _rag_self_warmup(self) -> None:
        """
        Auto-enrichissement RAG au démarrage :
        1. Code source Nokido découpé en sections logiques
        2. Documentation dense de TOUS les modules/capacités intégrés
        3. Fiches techniques capacités (SNMP, SSH, scan, IDS, CI/CD…)
        Clé "text" partout (champ utilisé par RAGEngine.search).
        """
        if not _lf().rag_engine:
            return
        await asyncio.sleep(3)

        chat = self._chat_log()
        indexed = 0

        # ── 1. Code source Nokido — découpé par sections ─────────────
        try:
            import pathlib as _pl, re as _re2

            _src_text = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _pl.Path(__file__).read_text(encoding="utf-8", errors="replace")
            )
            _sections = _re2.split(r"\n# [=]{10,}\n", _src_text)
            _cs, _ol = 2000, 150
            _chunks = []
            for _sec in _sections:
                for _i in range(0, len(_sec), _cs - _ol):
                    _blk = _sec[_i : _i + _cs].strip()
                    if len(_blk) > 80:
                        _chunks.append(
                            {
                                "text": _blk,
                                "source": f"source:Nokido.py:off{_i}",
                                "embedding": None,
                            }
                        )
            await asyncio.sleep(0)
            if _chunks:
                _lf().rag_engine.chunks.extend(_chunks)
                indexed += len(_chunks)
                logger.info(f"RAG warmup: {len(_chunks)} chunks source")
                import gc as _gc

                _gc.collect()
        except Exception as _e:
            logger.debug(f"RAG self-index: {_e}")

        # ── 2. Docs techniques ─────────────────────────────────────────
        _tool_docs = {
            "SNMP pysnmp": (
                "SNMP (Simple Network Management Protocol) permet d'interroger des équipements réseau. "
                "pysnmp est la bibliothèque Python principale. "
                "Usage: getCmd(SnmpEngine(), CommunityData('public', mpModel=0), "
                "UdpTransportTarget((ip, 161), timeout=2, retries=1), ContextData(), "
                "ObjectType(ObjectIdentity('SNMPv2-MIB','sysDescr',0))). "
                "Appeler next(iterator) retourne (errorIndication, errorStatus, errorIndex, varBinds). "
                "OIDs utiles: sysDescr=1.3.6.1.2.1.1.1.0 (description), "
                "sysName=1.3.6.1.2.1.1.5.0 (nom), sysUpTime=1.3.6.1.2.1.1.3.0 (uptime), "
                "ifDescr=1.3.6.1.2.1.2.2.1.2 (interfaces). "
                "SNMP v1/v2c utilisent CommunityData. SNMP v3 utilise UsmUserData. "
                "Fingerprint marques: cisco/hp/aruba/juniper/mikrotik/huawei/fortinet dans sysDescr. "
                "Toujours vérifier errorIndication avant de lire varBinds."
            ),
            "SSH paramiko asyncssh": (
                "SSH (Secure Shell) permet l'accès distant sécurisé. "
                "paramiko: ssh=SSHClient(); ssh.set_missing_host_key_policy(AutoAddPolicy()); "
                "ssh.connect(host, username=u, password=p, timeout=3, look_for_keys=False). "
                "exec_command(cmd) retourne (stdin, stdout, stderr). "
                "stdout.read().decode() récupère la sortie. "
                "asyncssh: await asyncssh.connect(host, username=u, password=p). "
                "await conn.run(cmd) pour commandes simples. "
                "conn.create_process() pour PTY interactif avec terminal. "
                "Commandes config réseau: 'show running-config' (Cisco), "
                "'display current-configuration' (HP/Huawei), 'show configuration' (Juniper), "
                "'/export' (MikroTik), 'show full-configuration' (Fortinet)."
            ),
            "Scan réseau nmap socket": (
                "Scan réseau : deux approches. "
                "Mode complet nmap: nm=nmap.PortScanner(); nm.scan(hosts='localhost/24', "
                "arguments='-O -sS --open'). nm.all_hosts() liste les hôtes. "
                "nm[host].state() donne l'état. nm[host]['tcp'] les ports ouverts. "
                "nm[host]['osmatch'][0]['name'] pour détection OS. "
                "Mode basique socket: socket.connect_ex((ip, port))==0 si ouvert. "
                "ThreadPoolExecutor pour paralléliser 50+ sondes simultanées. "
                "ipaddress.ip_network(subnet).hosts() génère la liste d'IPs. "
                "Ports courants: 22=SSH, 23=Telnet, 80=HTTP, 443=HTTPS, 161=SNMP, "
                "445=SMB, 3389=RDP, 3306=MySQL, 5432=PostgreSQL, 8080=HTTP-alt."
            ),
            "Ollama LLM API": (
                "Ollama est un serveur LLM local sur http://localhost:11434. "
                "Chat: POST /api/chat {model, messages:[{role,content}], stream:true}. "
                "Embeddings: POST /api/embed {model:'bge-m3', input:'texte'}. "
                "Lister modèles: GET /api/tags → {models:[{name,size,modified_at}]}. "
                "Stream: chaque ligne JSON {message:{content:''}, done:bool}. "
                "Timeout réseau: aiohttp.ClientTimeout(total=120) pour gros modèles."
            ),
        }

        _new_chunks = []
        for _tname, _tdoc in _tool_docs.items():
            _new_chunks.append(
                {
                    "text": f"[Capacité: {_tname}]\n{_tdoc}",
                    "source": f"doc:{_tname.lower().replace(' ', '_').replace('/', '_')}",
                    "embedding": None,
                }
            )

        try:
            _texts = [c["text"] for c in _new_chunks]
            _embs = await _lf().rag_engine.get_embeddings(_texts)
            if _embs:
                for _c, _emb in zip(_new_chunks, _embs):
                    _c["embedding"] = _emb
            _lf().rag_engine.chunks.extend(_new_chunks)
            indexed += len(_new_chunks)
            try:
                if hasattr(_lf().rag_engine, "_rebuild_indexes"):
                    await _lf().rag_engine._rebuild_indexes()
            except Exception:
                pass
            logger.info(f"RAG warmup: {len(_new_chunks)} docs capacités indexées")
        except Exception as _e:
            logger.debug(f"RAG warmup tools: {_e}")

        # ── Phase 3 : injection vector_map.json (sémantique) ────────────────────
        try:
            await self._load_vector_map_into_rag()
        except Exception as _vme:
            logger.debug(f"[RAG warmup] vector_map: {_vme}")

        logger.info(f"[RAG warmup COMPLET] {indexed} chunks total")
        try:
            chat.write(
                f"[dim]🗄 RAG : [bold]{indexed}[/] blocs indexés "
                f"(code · modules · config · logs · patches · sémantique)[/]"
            )
        except Exception as _ce:
            logger.debug(f"[RAG warmup] chat.write final: {_ce}")

    async def _index_self_in_rag(self) -> None:
        """Index self in rag."""
        if not _lf().rag_engine:
            return
        try:
            code = _lf().version_manager.get_current_code()
            sections = re.split(r"\n# =+\n# (.+?)\n# =+\n", code)
            if len(sections) <= 1:
                await _lf().rag_engine.add_session_message(
                    "self_code", "source", f"[CODE SOURCE v{_lf().version_manager.current_version}]\n{code[:6000]}"
                )
            else:
                for i in range(0, len(sections) - 1, 2):
                    section_name = sections[i + 1] if i + 1 < len(sections) else f"section_{i}"
                    section_code = sections[i + 2] if i + 2 < len(sections) else sections[i]
                    await _lf().rag_engine.add_session_message(
                        "self_code", "section", f"[SECTION: {section_name}]\n{section_code[:2000]}"
                    )
            logger.info(f"Auto-indexation RAG : v{_lf().version_manager.current_version}")
        except Exception as e:
            logger.warning(f"Auto-indexation RAG échouée : {e}")

    async def _update_rag_info(self) -> None:
        """Update rag info."""
        while True:
            try:
                if _lf().rag_engine:
                    self.rag_info.sync()
            except Exception as _e:
                logger.debug(f"[_update_rag_info] {_e}")
            await asyncio.sleep(5)

    async def _handle_proxy(self, args: str) -> None:
        """Handle proxy.

        Args:
            args: Description.
        """
        from nokido_agent.app.forge_app_context import app_ctx as _actx

        _ac = _actx()
        prefect_manager = _ac.prefect_manager
        global proxy_conn
        parts = args.split()
        if not parts:
            self._chat_log().write("@proxy start|stop|test")
            return
        sub = parts[0].lower()
        if sub == "start":
            try:
                import asyncssh as _asyncssh

                proxy_conn = await _asyncssh.connect(
                    _lf().settings.ssh_host,
                    port=_lf().settings.ssh_port,
                    username=_lf().settings.ssh_user,
                    client_keys=[str(_lf().settings.private_key_path)],
                    known_hosts=None,
                )
                await proxy_conn.forward_socks("127.0.0.1", 8080)
                self._chat_log().write("[green]✅ Proxy SOCKS5 lancé sur 127.0.0.1:8080[/]")
            except Exception as e:
                self._chat_log().write(f"[red]❌ {e}[/]")
        elif sub == "stop":
            if proxy_conn:
                proxy_conn.close()
                await proxy_conn.wait_closed()
                proxy_conn = None
                self._chat_log().write("[yellow]🛑 Proxy arrêté[/]")
                from nokido_agent.app.forge_app_context import app_ctx as _actx

                _ac = _actx()
                prefect_manager = _ac.prefect_manager
        elif sub == "test":

            async def do_test() -> None:
                """Do test."""
                try:
                    out = await prefect_manager.run_ssh_command(
                        "curl --proxy socks5h://127.0.0.1:8080 -s --max-time 5 https://ifconfig.me"
                    )
                    self._chat_log().write(f"[green]✅ IP via proxy: {out.strip()}[/]")
                except Exception as e:
                    self._chat_log().write(f"[red]❌ {e}[/]")

            asyncio.create_task(do_test())

    async def _load_vector_map_into_rag(self) -> None:
        """
        Phase 2 — Injecte vector_map.json (généré par semantic_scanner.py)
        dans le RAGEngine au démarrage.
        Appelé depuis _rag_self_warmup() après le warmup initial.
        """
        import json as _json

        lf = _lf()
        if not lf or not getattr(lf, "rag_engine", None):
            return

        vm_path = lf._ROOT_DIR / "data" / "vector_map.json"
        if not vm_path.exists():
            logger.debug("[vector_map] absent — lance semantic_scanner.py")
            return

        try:
            vm = _json.loads(vm_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"[vector_map] lecture échouée : {e}")
            return

        chunks = []
        for module_name, module_data in vm.items():
            for node in module_data.get("nodes", []):
                kw = node.get("keywords", [])
                summary = node.get("summary", "")
                if not kw and not summary:
                    continue
                text = (
                    f"[Module: {module_name}] {node['name']} ({node['type']})\n"
                    f"Mots-clés : {', '.join(kw)}\n"
                    f"Résumé : {summary}\n"
                    + (f"Doc : {node.get('docstring', '')[:200]}" if node.get("docstring") else "")
                ).strip()
                chunks.append(
                    {
                        "text": text,
                        "source": f"vector_map:{module_name}.{node['name']}",
                        "embedding": None,
                    }
                )

        if not chunks:
            logger.info("[vector_map] aucun chunk à injecter")
            return

        try:
            embs = await lf.rag_engine.get_embeddings([c["text"] for c in chunks])
            if embs:
                for c, emb in zip(chunks, embs):
                    c["embedding"] = emb
            lf.rag_engine.chunks.extend(chunks)
            try:
                if hasattr(lf.rag_engine, "_rebuild_indexes"):
                    await lf.rag_engine._rebuild_indexes()
            except Exception:
                pass
            logger.info(f"[vector_map] {len(chunks)} nœuds injectés dans RAG")
            self._chat_log().write(f"[dim]🗺 vector_map : [bold]{len(chunks)}[/] nœuds sémantiques indexés[/]")
        except Exception as e:
            logger.warning(f"[vector_map] injection échouée : {e}")
