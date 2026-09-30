# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_rag_warmup
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_rag_warmup.py — Auto-enrichissement RAG au démarrage
===========================================================
Extrait de Nokido.py (_rag_self_warmup) — v17 refactor.

Pipeline :
  1. Code source Nokido → sections logiques → RAG
  2. Documentation modules/capacités
  3. Fiches techniques (SNMP, SSH, scan, IDS, CI/CD...)

Usage depuis Nokido.py :
  from forge_rag_warmup import rag_self_warmup
  asyncio.create_task(rag_self_warmup(self))
"""

import asyncio, logging
import re as _re_mod
from nokido_agent.app import forge_context  # noqa

# ── Chemins Nokido ────────────────────────────────────────────────────────
_ROOT_P = __import__("pathlib").Path(__file__).resolve().parent.parent
_ROOT_DIR = _ROOT_P
_APP_DIR = _ROOT_P / "app"
_DATA_DIR = _ROOT_P / "data"
_LOGS_DIR = _ROOT_P / "logs"
_DATA_DIR.mkdir(exist_ok=True)
_LOGS_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("Nokido.RAGWarmup")
# Logger local plutot que le `_logger` PRIVE d'un autre module : importer le
# logger prive d'un voisin couple deux modules pour rien et brouille l'origine
# des lignes. Pose le 2026-09-08 en reponse au contrat des symboles a source
# unique (tests/nr/test_symboles_source_unique_nr.py).
_logger = logging.getLogger(__name__)


async def rag_self_warmup(app, _rag_warmup_done=None) -> None:
    """
    Auto-enrichissement RAG au démarrage :
    1. Code source Nokido découpé en sections logiques
    2. Documentation dense de TOUS les modules/capacités intégrés
    3. Fiches techniques capacités (SNMP, SSH, scan, IDS, CI/CD…)
    Clé "text" partout (champ utilisé par RAGEngine.search).
    """
    _re = forge_context.get_rag_engine()
    if not _re:
        return
    await asyncio.sleep(3)
    if getattr(_re, "via_hub", False):
        # Decision owner 1 du 25/09 : le RAG de la TUI passe par le HUB. Sonde du meme jour
        # (fil nomme apres fermeture) : `_warmup_app_index` -> index_app_dir -> index_file
        # faisait, PAR FICHIER d'app/ et tools/, un `source LIKE 'x%'` (insensible a la casse,
        # donc sans index : parcours des 8,25 M lignes) puis DELETE/INSERT directs dans
        # rag_chunks, hors du gate du hub -- et retenait le processus de la TUI apres sa
        # fermeture. L'indexeur n'est pas touche ; seule la TUI cesse de le declencher.
        logger.info("[RAG warmup] RAG via le hub : indexation LOCALE d'app/ et tools/ SAUTEE "
                    "(c'est le travail du hub / des reindexations deportees, pas d'un client)")
    else:
        await _warmup_app_index()
    # ── Warmup llama.cpp — précharge le modèle en RAM au boot ───────────────
    try:
        import threading as _th
        from nokido_agent.app.forge_llamacpp import get_llamacpp_bridge as _glc
        from nokido_agent.app import forge_context as _fc

        _bridge = _glc()
        if _bridge.enabled and _fc.llm_engine is None:
            _fc.llm_engine = _bridge
            _th.Thread(target=_bridge.warmup, daemon=True, name="LlamaCpp-Warmup").start()
            _logger and _logger.info("[RAG warmup] llama.cpp warmup lancé en background")
    except Exception as _e:
        pass  # llama-cpp-python non installé — silencieux

    chat = app._chat_log()
    indexed = 0

    # ── 1. Code source Nokido — découpé par sections ─────────────
    try:
        import pathlib as _pl, re as _re2

        _src_text = _pl.Path(__file__).read_text(encoding="utf-8", errors="replace")
        # Couper sur les séparateurs de sections =====
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
        if _chunks:
            forge_context.get_rag_engine().chunks.extend(_chunks)
            indexed += len(_chunks)
            logger.info(f"RAG warmup: {len(_chunks)} chunks source")
    except Exception as _e:
        logger.debug(f"RAG self-index: {_e}")

    # ── 2. Docs techniques — champ "text" correct ─────────────────
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
        "IDS détection intrusion": (
            "IDS (Intrusion Detection System) surveille le réseau pour détecter les attaques. "
            "Mode scapy: sniff(iface=iface, prn=callback, filter='tcp', store=False). "
            "Détecter SSH brute-force: multiples paquets TCP port 22 depuis même IP. "
            "Mode basique Linux: lire /proc/net/tcp, colonnes hex IP:port. "
            "Format /proc/net/tcp: local_addr remote_addr state (01=ESTABLISHED). "
            "Convertir hex little-endian: ip = '.'.join(str(int(h[i:i+2],16)) for i in (6,4,2,0)). "
            "Seuil suspect: >3 connexions SSH depuis même IP en session. "
            "pyshark (TShark wrapper): capture = pyshark.LiveCapture(interface=iface). "
            "capture.sniff_continuously(packet_count=50) pour capture async."
        ),
        "CI/CD pipeline git": (
            "CI/CD (Continuous Integration/Deployment) automatise build, test, déploiement. "
            "Détection automatique: Makefile→make test/build, pytest.ini→pytest, "
            "package.json→npm test/build, Dockerfile→docker build, docker-compose.yml→compose up. "
            "git clone --depth=1 <url> <dir> pour clone rapide. "
            "git pull && git reset --hard origin/<branch> pour mise à jour propre. "
            "pytest -v --tb=short pour tests Python avec détails. "
            "docker build -t <image>:<tag> . pour build image. "
            "docker compose -f docker-compose.yml up -d --build pour déploiement. "
            "Stratégies déploiement: restart (systemctl), compose (docker compose pull+up), "
            "docker (pull+stop+run), rollback (restaure backup /opt/<svc>_bak*)."
        ),
        "RAG FAISS BM25": (
            "RAG (Retrieval Augmented Generation) enrichit le LLM avec des documents pertinents. "
            "Architecture hybride: FAISS (similarité vectorielle) + BM25 (lexical). "
            "FAISS IndexFlatIP: produit scalaire (cosinus après normalisation L2). "
            "faiss.normalize_L2(embeddings) avant indexation. "
            "BM25Okapi: score TF-IDF amélioré, BM25Okapi(corpus.split()). "
            "Fusion: score = 0.65*faiss_norm + 0.35*bm25_norm. "
            "Chunking: découpage par phrases (~500 mots), overlap 30 mots. "
            "Embeddings: bge-m3 via Ollama /api/embed, dim=1024. "
            "Ingestion PDF: pdfplumber (tableaux+texte) > pypdf en fallback. "
            "Nettoyage: supprimer bytes invalides, espaces excessifs, non-printable."
        ),
        "Ollama LLM API": (
            "Ollama est un serveur LLM local sur http://localhost:11434. "
            "Chat: POST /api/chat {model, messages:[{role,content}], stream:true}. "
            "Embeddings: POST /api/embed {model:'bge-m3', input:'texte'}. "
            "Lister modèles: GET /api/tags → {models:[{name,size,modified_at}]}. "
            "Stream: chaque ligne JSON {message:{content:''}, done:bool}. "
            "Modèles recommandés: qwen2.5-coder:1.5b (rapide/chat), "
            "deepseek-r1:7b (raisonnement), bge-m3 (embeddings 1024d). "
            "Timeout réseau: aiohttp.ClientTimeout(total=120) pour gros modèles."
        ),
        "Textual TUI": (
            "Textual est un framework TUI Python basé sur Rich. "
            "App.compose() yield les widgets. on_mount() pour init async. "
            "Widget.render() retourne str ou Panel Rich. "
            "reactive() déclenche refresh auto. query_one('#id') accède aux widgets. "
            "CSS inline: width, height, background, color, border, padding, margin. "
            "Layout: Horizontal, Vertical, Grid. "
            "RichLog.write(markup) pour affichage coloré. "
            "App.TITLE/'app.title' pour le titre de la fenêtre terminal. "
            "Widget sans render() affiche son nom de classe — toujours définir render()."
        ),
        "boitaswitch NetworkRecoveryAgent": (
            "NetworkRecoveryAgent récupère la config d'équipements réseau (switches, routeurs). "
            "recover_config(username, password, on_step=callback) retourne SwitchResult. "
            "Workflow: scan ports parallèle → SNMP fingerprint → SSH → Telnet fallback. "
            "SwitchResult: .ok (bool), .config (str), .device_type, .protocol, .services. "
            "scan_range(targets, username, password) scan plusieurs IPs en parallèle. "
            "Marques supportées: cisco, hp, aruba, juniper, mikrotik, huawei, fortinet. "
            "Commandes config: Cisco='show running-config', HP='display current-config', "
            "Juniper='show configuration', MikroTik='/export', Fortinet='show full-configuration'."
        ),
        "chainage outils ToolChain": (
            "Chainage d'outils (tool chaining) permet d'exécuter des actions en séquence. "
            "Syntaxe: @chain <outil1> | <outil2> | <outil3> "
            "Chaque outil peut utiliser le résultat du précédent via {output}. "
            "Exemple: @chain @scan localhost/24 | @switch {ip} admin pass | @rag save. "
            "Les pipes | séparent les étapes. {output} injecte le résultat précédent. "
            "Arrêt sur erreur si un outil retourne une erreur critique. "
            "Historique des chains dans @workflow history."
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

    # Vectoriser les nouveaux chunks en batch
    try:
        _texts = [c["text"] for c in _new_chunks]
        _embs = await _re.get_embeddings(_texts)
        if _embs:
            for _c, _emb in zip(_new_chunks, _embs):
                _c["embedding"] = _emb
        _re.chunks.extend(_new_chunks)
        indexed += len(_new_chunks)
        try:
            if hasattr(_re, "_rebuild_indexes"):
                await _re._rebuild_indexes()
        except Exception:
            pass
        logger.info(f"RAG warmup: {len(_new_chunks)} docs capacités indexées")
    except Exception as _e:
        logger.debug(f"RAG warmup tools: {_e}")

    # ── 3. TOUS les modules source Python du projet ───────────────
    _MODULE_FILES = [
        "forge_agents.py",
        "forge_runtime.py",
        "forge_nlu.py",
        "forge_code.py",
        "forge_network.py",
        "forge_web.py",
        "forge_safe_integration.py",
        "onnx_backend.py",
        "scoring.py",
        "routage.py",
        "roles.py",
        "loops.py",
        "predictif.py",
        "skilltree.py",
        "modeplanner.py",
        "version_manager.py",
        "danger_guard.py",
        "boitaswitch.py",
        "codesandbox.py",
        "codetesteur.py",
    ]
    _mod_chunks = []
    for _mf in _MODULE_FILES:
        try:
            _mp = _APP_DIR / _mf
            if not _mp.exists():
                continue
            _msrc = _mp.read_text(encoding="utf-8", errors="replace")
            # Extraire : classes, fonctions publiques + docstrings (pas tout le code brut)
            import re as _re3

            _sections = _re3.split(r"\n# [=]{10,}\n", _msrc)
            _cs, _ol = 2000, 150
            for _sec in _sections:
                for _i in range(0, len(_sec), _cs - _ol):
                    _blk = _sec[_i : _i + _cs].strip()
                    if len(_blk) > 80:
                        _mod_chunks.append(
                            {
                                "text": f"[Module: {_mf}]\n{_blk}",
                                "source": f"module:{_mf}:off{_i}",
                                "embedding": None,
                            }
                        )
            logger.debug(f"[RAG warmup] module {_mf} → {len(_mod_chunks)} chunks cumulés")
        except Exception as _me:
            logger.debug(f"[RAG warmup] module {_mf} : {_me}")
    if _mod_chunks:
        try:
            _embs2 = await _re.get_embeddings([c["text"] for c in _mod_chunks])
            if _embs2:
                for _c, _emb in zip(_mod_chunks, _embs2):
                    _c["embedding"] = _emb
            _re.chunks.extend(_mod_chunks)
            indexed += len(_mod_chunks)
            logger.info(f"[RAG warmup] {len(_mod_chunks)} chunks modules indexés")
        except Exception as _me2:
            logger.debug(f"[RAG warmup] embed modules : {_me2}")

    # ── 4. Fichiers config (requirements, ARCHITECTURE, CHANGELOG) ─
    _CONFIG_FILES = [
        ("requirements.txt", "Dépendances Python du projet"),
        ("ARCHITECTURE.md", "Architecture globale Nokido"),
        ("CHANGELOG.md", "Historique des versions"),
        ("Nokido.env", "Configuration runtime (clés, chemins, modèles)"),
    ]
    _cfg_chunks = []
    for _cf, _label in _CONFIG_FILES:
        try:
            _cp = _ROOT_DIR / _cf
            if not _cp.exists():
                _cp = _APP_DIR / _cf
            if not _cp.exists():
                continue
            _ctxt = _cp.read_text(encoding="utf-8", errors="replace")
            _cfg_chunks.append(
                {
                    "text": f"[Config: {_label}]\n{_ctxt[:3000]}",
                    "source": f"config:{_cf}",
                    "embedding": None,
                }
            )
        except Exception as _cfe:
            logger.debug(f"[RAG warmup] config {_cf} : {_cfe}")
    if _cfg_chunks:
        try:
            _embs3 = await _re.get_embeddings([c["text"] for c in _cfg_chunks])
            if _embs3:
                for _c, _emb in zip(_cfg_chunks, _embs3):
                    _c["embedding"] = _emb
            _re.chunks.extend(_cfg_chunks)
            indexed += len(_cfg_chunks)
            logger.info(f"[RAG warmup] {len(_cfg_chunks)} fichiers config indexés")
        except Exception as _ce2:
            logger.debug(f"[RAG warmup] embed config : {_ce2}")

    # ── 5. Logs des sessions précédentes (résumé + erreurs critiques)
    _log_chunks = []
    try:
        _log_files = sorted(_LOGS_DIR.glob("nokido_????????_??????.log"), key=lambda p: p.stat().st_mtime)[
            -3:
        ]  # 3 dernières sessions max (RAM)
        for _lf in _log_files:
            try:
                _lines = _lf.read_text(encoding="utf-8", errors="replace").splitlines()
                # Filtrer : WARNING, ERROR, INFO clés (pas les DEBUG SSH bruts)
                _keep = [
                    l
                    for l in _lines
                    if any(
                        kw in l
                        for kw in [
                            "[WARNING]",
                            "[ERROR]",
                            "[CRITICAL]",
                            "[SSH READY]",
                            "[ROUTE]",
                            "[AI REPLY]",
                            "[on_mount START]",
                            "Archivé",
                            "Checkpoint",
                            "version_manager",
                            "[OLLAMA",
                            "RAG warmup",
                            "Benchmark",
                            "Architecture détectée",
                        ]
                    )
                ]
                if not _keep:
                    continue
                # Résumé structuré
                _n_warn = sum(1 for l in _lines if "[WARNING]" in l)
                _n_err = sum(1 for l in _lines if "[ERROR]" in l)
                _session = _lf.stem  # nokido_20260307_082020
                _summary = (
                    f"[Session log: {_session}]\n"
                    f"Durée estimée: {_lines[0][:8] if _lines else '?'} → {_lines[-1][:8] if _lines else '?'}\n"
                    f"Warnings: {_n_warn}  Errors: {_n_err}\n"
                    f"Événements clés:\n" + "\n".join(_keep[:15])
                )
                _log_chunks.append(
                    {
                        "text": _summary,
                        "source": f"log:{_session}",
                        "embedding": None,
                    }
                )
                logger.debug(f"[RAG warmup] log {_session} → {len(_keep)} lignes clés")
            except Exception as _le:
                logger.debug(f"[RAG warmup] log {_lf.name} : {_le}")
    except Exception as _lge:
        logger.debug(f"[RAG warmup] glob logs : {_lge}")

    if _log_chunks:
        try:
            _embs4 = await _re.get_embeddings([c["text"] for c in _log_chunks])
            if _embs4:
                for _c, _emb in zip(_log_chunks, _embs4):
                    _c["embedding"] = _emb
            _re.chunks.extend(_log_chunks)
            indexed += len(_log_chunks)
            logger.info(f"[RAG warmup] {len(_log_chunks)} sessions log indexées")
        except Exception as _le2:
            logger.debug(f"[RAG warmup] embed logs : {_le2}")

    # ── 6. _patch_backlog.json — mémoire des patches passés ────────
    try:
        import json as _json

        _pb = _DATA_DIR / "_patch_backlog.json"
        if not _pb.exists():
            _pb = _ROOT_DIR / "_patch_backlog.json"
        if _pb.exists():
            _backlog = _json.loads(_pb.read_text(encoding="utf-8", errors="replace"))
            if isinstance(_backlog, list) and _backlog:
                _recent = _backlog[-5:]  # 5 derniers patches (RAM)
                _bl_text = "\n".join(
                    f"v{p.get('from', '?')}→v{p.get('to', '?')} [{p.get('type', '?')}] {p.get('description', '')[:120]}"
                    for p in _recent
                )
                _bl_chunk = {
                    "text": f"[Historique patches]\n{_bl_text}",
                    "source": "config:patch_backlog",
                    "embedding": None,
                }
                _e = await _re.get_embeddings([_bl_chunk["text"]])
                if _e:
                    _bl_chunk["embedding"] = _e[0]
                _re.chunks.append(_bl_chunk)
                indexed += 1
                logger.info(f"[RAG warmup] backlog {len(_recent)} patches indexés")
    except Exception as _be:
        logger.debug(f"[RAG warmup] patch_backlog : {_be}")

    # ── Rebuild index + résumé final ──────────────────────────────
    try:
        try:
            if hasattr(_re, "_rebuild_indexes"):
                await _re._rebuild_indexes()
        except Exception:
            pass
    except Exception:
        pass
    logger.info(f"[RAG warmup COMPLET] {indexed} chunks total (source + modules + config + logs + backlog)")
    # Signaler au _bg_startup que tous les embeddings sont terminés
    if _rag_warmup_done is not None and not _rag_warmup_done.is_set():
        _rag_warmup_done.set()
        logger.debug("[MemMgr] _rag_warmup_done.set() → pre-bench autorisé")
    chat.write(f"[dim]🗄 RAG : [bold]{indexed}[/] blocs indexés (code · modules · config · logs · patches)[/]")

    # ── Bootstrap Kernel en arrière-plan (Ring1+Ring2 seulement, pas le code) ──
    async def _auto_bootstrap() -> None:
        """Auto bootstrap."""
        try:
            from nokido_agent.app.forge_ingest_self import force_self_ingestion as _fsi

            await _fsi(
                _re,
                log_fn=None,  # silencieux au boot
                include_source=False,  # Ring0 trop lourd au boot
                include_infra=True,  # Ring1 : INFRA.md + SITUATION.md
                include_session=True,  # Ring2 : décisions + backlog
            )
            logger.info("[Boot] Kernel bootstrap RAG OK (Ring1+Ring2)")
        except Exception as _be:
            logger.warning(f"[Boot] Kernel bootstrap RAG: {_be}")

    asyncio.create_task(_auto_bootstrap())

    # ── Heartbeat boot — signale que Nokido est démarré ─────────────────────
    try:
        from nokido_agent.app.forge_heartbeat import beat as _hb_beat, start_auto_beat

        _hb_beat("CLAUDE", status="idle", task="warmup_complete")
        start_auto_beat("CLAUDE", interval_sec=15.0)
    except Exception as _hb_e:
        pass


async def index_self_in_rag(app) -> None:
    """
    Auto-indexation : injecte le code source courant dans le RAG
    pour que les agents comprennent leur propre base de code.
    """
    _re = forge_context.get_rag_engine()
    _vm = forge_context.get_version_manager()
    if not _re or not _vm:
        return
    try:
        code = _vm.get_current_code()
        # Découpe en sections logiques pour des chunks pertinents
        sections = _re_mod.split(r"\n# =+\n# (.+?)\n# =+\n", code)
        if len(sections) <= 1:
            # Pas de sections → indexe tout le fichier
            await _re.add_session_message(
                "self_code", "source", f"[CODE SOURCE v{_vm.current_version}]\n{code[:6000]}"
            )
        else:
            # Indexe section par section
            for i in range(0, len(sections) - 1, 2):
                section_name = sections[i + 1] if i + 1 < len(sections) else f"section_{i}"
                section_code = sections[i + 2] if i + 2 < len(sections) else sections[i]
                await _re.add_session_message(
                    "self_code", "section", f"[SECTION: {section_name}]\n{section_code[:2000]}"
                )
        logger.info(f"Auto-indexation RAG : v{_vm.current_version}")
    except Exception as e:
        logger.warning(f"Auto-indexation RAG échouée : {e}")


async def _warmup_app_index() -> None:
    """Indexe tout app/ dans le RAG au démarrage — Manifeste §V."""
    try:
        import asyncio
        from nokido_agent.app.forge_rag_index_app import index_app_dir

        loop = asyncio.get_event_loop()
        stats = await loop.run_in_executor(None, lambda: index_app_dir(changed_only=True, verbose=False))
        logger.info(
            f"[RAG warmup] app/ indexé: {stats['files_indexed']} fichiers "
            f"{stats['chunks_added']} chunks en {stats['duration_s']}s"
        )
        # tools/ : le warmup ne couvrait QUE app/ -> 241 modules tools/forge_* jamais
        # vectorisés (constaté 2026-06-05). index_app_dir accepte target_dir -> on
        # réutilise l'indexeur incrémental prouvé pour combler le trou au boot.
        try:
            _tools_dir = _ROOT_P / "tools"
            st = await loop.run_in_executor(
                None, lambda: index_app_dir(target_dir=_tools_dir, changed_only=True, verbose=False)
            )
            logger.info(f"[RAG warmup] tools/ indexé: {st['files_indexed']} fichiers {st['chunks_added']} chunks")
        except Exception as _et:
            logger.debug(f"[RAG warmup] tools/ index skip: {_et}")
    except Exception as e:
        logger.debug(f"[RAG warmup] index_app_dir skip: {e}")


# ============================================================================
# API publique synchrone pour pluripotent_worker rag_warmer (récepteur TSH)
# ============================================================================


def _observer(signal: str) -> None:
    """Constate une LECTURE du signal (voir `_transduire` pour l'effet)."""
    try:
        from nokido_agent.app.forge_signal_coupling import observe_signal
        observe_signal(signal, consumer="forge_rag_warmup.warmup_rag")
    except Exception:
        pass  # muet-ok : mesurer la lecture ne doit pas pouvoir empecher la lecture


def _transduire(signal: str) -> None:
    """Constate qu'une branche d'effet a REELLEMENT agi sur ce signal.

    Distinction du RECEPTEUR LEURRE (revue AGY 2026-07-30) : lire un signal ne prouve
    rien, seul l'EFFET le prouve. Fail-safe absolu — l'observabilite ne doit jamais
    empecher le frein qu'elle observe de freiner.
    """
    try:
        from nokido_agent.app.forge_signal_coupling import transduce_signal
        transduce_signal(signal, consumer="forge_rag_warmup.warmup_rag")
    except Exception:
        pass  # muet-ok : mesurer l'effet ne doit pas pouvoir annuler l'effet


def warmup_rag(force: bool = False, batch_size: int = 256) -> dict:
    """API publique synchrone — appelée par PluripotentWorker.action_rag_warmer.

    (voir `_transduire` : chaque branche d'effet CONSTATE sa transduction, ce qui
    distingue ce récepteur d'un récepteur leurre qui lirait sans agir.)

    Récepteur endocrinien AGONISTE **et** ANTAGONISTE :
      * TSH_VECTORIZATION > 0.4     -> batch_size ×2  (demande accrue)
      * INSULIN_VECTORIZATION > 0.4 -> batch_size /2  (saturation, frein)

    AUDIT 2026-07-26 : l'agoniste était référencé par 6 modules, l'antagoniste par
    ZÉRO — `INSULIN_VECTORIZATION` n'apparaissait que dans sa déclaration et chez
    son émetteur. Une régulation qui n'a qu'un accélérateur n'est pas une
    régulation : c'est l'analogue d'une résistance périphérique — le signal circule,
    aucun récepteur ne le traduit en effet. Le frein se pose au MÊME site que
    l'accélérateur, sinon les deux ne s'opposent jamais vraiment.

    Renvoie {ok, chunks_processed, batch_size_used, tsh_level}.
    """
    import asyncio as _asyncio

    try:
        from nokido_agent.app.forge_endocrine import read as _hormone_read  # type: ignore

        tsh = _hormone_read("TSH_VECTORIZATION")
        insulin = _hormone_read("INSULIN_VECTORIZATION")
        # LECTURE constatée ici, EFFET constaté plus bas. Les deux sont nécessaires :
        # sans la lecture, l'absence d'effet ne distingue pas « lu sans agir » (récepteur
        # leurre) de « ce code n'a pas tourné » — et accuser le second est le faux
        # positif qui fait désarmer un garde.
        _observer("TSH_VECTORIZATION")
        _observer("INSULIN_VECTORIZATION")
        if tsh > 0.4:
            batch_size = max(batch_size, batch_size * 2)
            logger.info(f"[warmup_rag] TSH={tsh:.2f} > 0.4 → batch_size boost à {batch_size}")
            _transduire("TSH_VECTORIZATION")
        # ANTAGONISTE. L'insuline dit « saturé, ralentis ». Appliquée APRÈS le boost :
        # quand les deux signaux coexistent le frein l'emporte sur l'accélérateur.
        # Asymétrie volontaire et physiologique — le coût d'un excès (saturation,
        # éviction, gate qui ferme) dépasse celui d'un retard.
        if insulin > 0.4:
            # REPONSE PROPORTIONNELLE (2026-08-05). La glande a ete rendue GRADUEE le
            # 2026-07-30 pour permettre un dosage ; le recepteur, lui, appliquait une
            # reponse BINAIRE — une seule division par deux, quel que soit le niveau.
            # Mesure du jour : insuline lue a 0.997 (saturation quasi maximale) et le
            # batch ne descendait que de 256 a 128, insuffisant face aux ~50 requetes
            # par minute soutenues vers l'embedder, qui a gonfle de 2,73 a 6,07 Go.
            # Le facteur vaut 0.5 a l'ENTREE de la bande (identique a l'ancien
            # comportement, donc aucune regression possible) et descend a 0.125 a
            # saturation. Monotone, borne par max(16, ...), et il se relache tout seul
            # quand l'hormone retombe : rien a desarmer.
            _facteur = 0.5 * (1.0 - 0.75 * (min(insulin, 1.0) - 0.4) / 0.6)
            batch_size = max(16, int(batch_size * _facteur))
            # CONSTATER LA TRANSDUCTION, pas la lecture. Le docstring ci-dessus décrit
            # déjà le mal depuis le 26/07 — « le signal circule, aucun récepteur ne le
            # traduit en effet » — mais rien ne permettait de le MESURER : ce frein a
            # lu l'insuline pendant des mois sans jamais freiner, l'hormone valant
            # 0.0 faute d'émetteur. Un capteur qui compte les LECTURES l'aurait déclaré
            # couplé. En biologie c'est le récepteur LEURRE (OPG, ACKR3) : il fixe le
            # ligand et n'a pas de domaine de signalisation. On marque donc ici, au
            # site de l'EFFET, la seule preuve qu'une voie transduit vraiment.
            _transduire("INSULIN_VECTORIZATION")
            logger.info(f"[warmup_rag] INSULIN={insulin:.2f} > 0.4 → batch_size frein à "
                        f"{batch_size} (facteur {_facteur:.3f})")
    except Exception as e:  # noqa: BLE001
        tsh = insulin = 0.0
        # Remettre les deux hormones a 0.0 fait DISPARAITRE le frein : le warmer
        # repart a pleine cadence, et rien ne distingue « aucune saturation » de
        # « je n'ai pas pu lire l'endocrine ». C'est le defaut que ce module decrit
        # lui-meme plus haut, applique a son propre chemin d'erreur.
        logger.warning(
            "[warmup_rag] endocrine ILLISIBLE (%s: %s) — TSH et INSULINE forcees a 0.0 "
            "| consequence: le frein de saturation est DESACTIVE pour ce cycle et le "
            "batch repart a pleine taille, sans qu'aucune saturation ne l'autorise",
            type(e).__name__, str(e)[:100])

    n_processed = 0
    try:
        # Si event loop déjà actif (cas async), on ne peut pas asyncio.run
        try:
            _ = _asyncio.get_running_loop()
            return {"ok": False, "err": "event_loop_busy", "tsh_level": tsh, "batch_size_used": batch_size}
        except RuntimeError:
            pass
        _asyncio.run(_warmup_app_index())
        n_processed = 1
    except Exception as e:
        return {"ok": False, "err": f"{type(e).__name__}: {e}", "tsh_level": tsh, "batch_size_used": batch_size}

    # Indexation conversations CLI (idempotent, ~100ms)
    try:
        from nokido_agent.app.forge_conv_indexer import index_all as _idx_conv  # type: ignore

        conv_res = _idx_conv(limit_sessions=10)
        n_processed += conv_res.get("total_inserted", 0)
        logger.info("[warmup_rag] conv_indexer: %d nouveaux chunks conversations", conv_res.get("total_inserted", 0))
    except Exception as _ce:
        logger.debug("[warmup_rag] conv_indexer skip: %s", _ce)

    return {"ok": True, "chunks_processed": n_processed, "batch_size_used": batch_size, "tsh_level": tsh}
