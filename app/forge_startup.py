# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_164356_astdoc
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0 docs
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
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
forge_startup.py — Démarrage et fonctions module (v16.5)
=========================================================
load_last_assignment, save_last_assignment, auto_select_models,
_init_smart_router, main(), _launch_in_new_terminal
"""

import asyncio, json, logging, os, sys
from pathlib import Path

logger = logging.getLogger(__name__)

from app.core.settings import get_app_attr as _g
from nokido_agent.app import forge_context  # noqa: F401


# ── load_last_assignment ──────────────────────────────────


def load_last_assignment() -> dict:
    """Charge la dernière assignation connue — démarrage instantané sans bench."""
    try:
        LAST_ASSIGNMENT_FILE = _g("LAST_ASSIGNMENT_FILE", Path("data/last_assignment.json"))
        if LAST_ASSIGNMENT_FILE.exists():
            d = json.loads(LAST_ASSIGNMENT_FILE.read_text(encoding="utf-8"))
            if all(k in d for k in ("chat", "action", "rag")):
                return d
    except Exception:
        pass
    return {}


# ── save_last_assignment ──────────────────────────────────


def save_last_assignment(chat: str, action: str, rag: str) -> None:
    """Persiste l'assignation pour le prochain démarrage."""
    try:
        LAST_ASSIGNMENT_FILE = _g("LAST_ASSIGNMENT_FILE", Path("data/last_assignment.json"))
        LAST_ASSIGNMENT_FILE.parent.mkdir(exist_ok=True)
        LAST_ASSIGNMENT_FILE.write_text(
            json.dumps({"chat": chat, "action": action, "rag": rag}, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.debug(f"save_last_assignment: {e}")


# ── auto_select_models ──────────────────────────────────


async def auto_select_models(scorer, arch=None) -> dict:
    """
    Sélectionne automatiquement le meilleur modèle pour chaque agent
    via la banque de scoring.  Retourne {"chat": m, "action": m, "rag": m}.
    """
    # Si OLLAMA_MODEL_DEFAULT est vide, on ne force rien —
    # l'orchestrateur résoudra via scorer ou le premier modèle Ollama dispo
    _s = forge_context.get_settings()
    fallback = (_s.ollama_model_default if _s else "") or ""
    _hs = _g("HAS_SCORING", False)
    if not _hs or scorer is None or not scorer.is_ready:
        return {"chat": fallback, "action": fallback, "rag": fallback}
    try:
        _AR = _g("OpsAgentRole")
        if not _AR:
            return {"chat": fallback, "action": fallback, "rag": fallback}
        model_chat = scorer.best_for(_AR.RAG_KNOWLEDGE, arch) or fallback
        model_action = scorer.best_for(_AR.ACTION_EXEC, arch, exclude=[model_chat]) or model_chat
        model_rag = scorer.best_for(_AR.MEMORY, arch, exclude=[model_chat, model_action]) or model_chat
        return {"chat": model_chat, "action": model_action, "rag": model_rag}
    except ImportError:
        # scoring/roles non trouvés — fallback silencieux
        return {"chat": fallback, "action": fallback, "rag": fallback}
    except Exception as e:
        logger.warning(f"auto_select_models: {e}")
        return {"chat": fallback, "action": fallback, "rag": fallback}


# ── _init_smart_router ──────────────────────────────────


def _init_smart_router(ollama_url: str, scorer=None) -> None:
    """SmartRouter + WebSearch + CodeSandbox + NLU. Globals résolus via _g()."""
    if not _g("HAS_ROUTAGE", False):
        return
    _settings_r = forge_context.get_settings()
    _rag_engine = forge_context.get_rag_engine()
    _init_router = _g("init_router")
    try:
        web_eng = None
        if _g("HAS_WEB_SEARCH", False):
            _gwe = _g("get_web_engine")
            if _gwe:
                web_eng = _gwe()
                logger.info("WebSearchEngine init")
        if _init_router and _settings_r:
            _init_router(
                ollama_url=ollama_url,
                max_concurrent=_settings_r.max_concurrent_tasks,
                web_engine=web_eng,
                rag_engine=_rag_engine,
                scorer=scorer,
            )
            logger.info("SmartRouter initialisé")
    except Exception as e:
        logger.warning(f"SmartRouter init: {e}")

    if _g("HAS_SANDBOX", False):
        try:
            _gs = _g("get_sandbox")
            _m = (_settings_r.ollama_model_default if _settings_r else "") or ""
            if _gs:
                _gs(ollama_url=ollama_url, model=_m, rag_engine=_rag_engine, max_retries=2, timeout=8.0)
                logger.info(f"CodeSandbox initialisé ({_m})")
        except Exception as e:
            logger.warning(f"CodeSandbox init: {e}")

    if _g("HAS_PREDICTIF", False):
        try:
            _lr = _g("load_router")
            if _lr:
                _lr()
            logger.info("PredictiveRouter NLU chargé")
        except Exception as e:
            logger.warning(f"PredictiveRouter init: {e}")


# ── main ──────────────────────────────────


async def main(_DevOpsApp=None) -> None:
    """Main.

    Args:
        _DevOpsApp: Description.
    """
    from nokido_agent.app.forge_app_context import app_ctx as _actx

    _ac = _actx()
    HAS_SCORING = _ac.HAS_SCORING
    prefect_manager = _ac.prefect_manager
    rag_engine = _ac.rag_engine
    session_name = _ac.session_name
    settings = _ac.settings
    ssh_manager = _ac.ssh_manager
    version_manager = _ac.version_manager
    for _s in (sys.stdout, sys.stderr):
        try:
            if hasattr(_s, "reconfigure"):
                _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    # Résoudre les globals Nokido via _g() — forge_startup est importé depuis Nokido.py
    _version_manager = forge_context.get_version_manager()
    _settings = forge_context.get_settings()
    try:
        from nokido_agent.app.forge_version import get as _fvget

        _start_ver = _fvget()
    except Exception:
        _start_ver = _g("__version__", "0.13.0")
    try:
        if _version_manager:
            _start_ver = _version_manager.current_version
    except Exception:
        pass
    # Résoudre TOUS les globals Nokido nécessaires à main()
    # Résoudre settings — priorité : arg passé > _g() > import direct
    # Settings : priorité runtime > forge_settings (pas de dépendance __main__)
    settings = _settings or forge_context.get_settings()
    if settings is None:
        from app.core.settings import create_settings as _cs

        settings = _cs()
    version_manager = _version_manager or forge_context.get_version_manager()
    if version_manager is None:
        try:
            from nokido_agent.app.forge_versioning import VersionManager as _VM

            version_manager = _VM()
        except Exception:
            pass
    ssh_manager = forge_context.get_ssh_manager()
    # forge_prefect n'a plus `get_prefect_manager` : l'accesseur vit dans forge_context (mesure
    # 2026-09-25, AttributeError au demarrage de la TUI v13 une fois `__main__` garde).
    prefect_manager = forge_context.get_settings() and forge_context.get_prefect_manager()
    rag_engine = forge_context.get_rag_engine()
    # HAS_TEXTUAL — import direct
    try:
        import textual as _tx

        HAS_TEXTUAL = True
    except ImportError:
        HAS_TEXTUAL = False
    # DevOpsApp — priorité : argument > __main__ > _g()
    DevOpsApp = _DevOpsApp or getattr(sys.modules.get("__main__"), "DevOpsApp", None) or _g("DevOpsApp")
    # import direct depuis forge_agents — pas via _g()
    try:
        from nokido_agent.app.forge_agents import ModelScorer, ArchitectureDetector

        HAS_SCORING = True
    except ImportError:
        HAS_SCORING, ModelScorer, ArchitectureDetector = False, None, None
    run_ssh = _g("run_ssh")

    # Détecter version_manager.py résiduel dans le dossier
    _script_dir = Path(__file__).resolve().parent
    _vm_file = _script_dir / "version_manager.py"
    if _vm_file.exists():
        print(
            f"  ⚠  version_manager.py détecté dans {_script_dir.name}/\n"
            f"     Ce fichier cause un import circulaire et doit être supprimé :\n"
            f"     del {_vm_file}",
            flush=True,
        )
    # (bannière ASCII supprimée — affichée dans la TUI via call_later)
    _env_path = Path(__file__).resolve().parent / "Nokido.env"
    print(f"  [config] {_env_path}")
    # Pas de warning inutile — forge_startup est importé par Nokido.py, c'est normal
    pass

    # ── 0. Brain worker (sidecar ZMQ) ──────────────────────────────────────────
    _brain_proc = None
    try:
        import zmq as _zmq

        # Contexte ISOLÉ — pas Context.instance() pour ne pas
        # empoisonner le contexte asyncio partagé de _ping_brain
        _ctx_probe = _zmq.Context()
        _sock = _ctx_probe.socket(_zmq.REQ)
        _sock.setsockopt(_zmq.LINGER, 0)
        _sock.setsockopt(_zmq.RCVTIMEO, 400)
        _sock.connect("tcp://127.0.0.1:5557")
        try:
            # Brain répond en msgpack — on envoie {"cmd":"ping"}
            try:
                import msgpack as _mp_p

                _sock.send(_mp_p.packb({"cmd": "ping"}, use_bin_type=True))
                _raw_p = _sock.recv()
                _rep_p = _mp_p.unpackb(_raw_p, raw=False)
            except ImportError:
                import json as _jp

                _sock.send(_jp.dumps({"cmd": "ping"}).encode())
                _raw_p = _sock.recv()
                _rep_p = _jp.loads(_raw_p.decode())
            _brain_already_running = _rep_p.get("data") == "pong"
        except Exception:
            _brain_already_running = False
        finally:
            _sock.close()
            _ctx_probe.term()
        if not _brain_already_running:
            import sys as _sys_b

            _brain_script = Path(__file__).parent / "brain_worker.py"
            if _brain_script.exists():
                import subprocess as _sp

                _brain_proc = _sp.Popen(
                    [_sys_b.executable, str(_brain_script)],
                    stdout=_sp.DEVNULL,
                    stderr=_sp.DEVNULL,
                    creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0),
                )
                print(f"  ⚡ Brain worker démarré (PID {_brain_proc.pid})", flush=True)
            else:
                print("  ⚠ brain_worker.py introuvable", flush=True)
        else:
            print("  ⚡ Brain worker déjà actif (:5557)", flush=True)
    except ImportError:
        print("  ⚠ pyzmq non installé — brain worker désactivé", flush=True)
    except Exception as _be:
        print(f"  ⚠ Brain worker : {_be}", flush=True)

    # ── 1. Charger la dernière assignation connue (instantané) ──────────────────
    _last = load_last_assignment()
    fallback_model = settings.ollama_model_default or ""
    model_chat = _last.get("chat", fallback_model)
    model_action = _last.get("action", fallback_model)
    model_rag = _last.get("rag", fallback_model)
    if _last:
        print(f"  ✅ Modèles chargés : chat={model_chat} | action={model_action} | rag={model_rag}")
    else:
        print(f"  ℹ️  Première utilisation — modèles par défaut ({fallback_model or 'non défini'})")
    session_name = "default"

    # ── 2. SSH, Scorer, SmartRouter — différés en background après TUI
    scorer = None  # initialisé dans _bg_services() après on_mount

    # ── 3. Lancement de l'application ─────────────────────────────────────────
    # ── 5. Lancement de l'application ─────────────────────────────────────────
    if HAS_TEXTUAL:
        app = DevOpsApp(
            model_chat=model_chat,
            model_action=model_action,
            model_rag=model_rag,
            session_name=session_name,
            scorer=scorer,
            arch=None,
        )

        # ── Background : discover + arch + bench + réassignation ─────────────
        if scorer is not None:

            async def _bg_startup() -> None:
                """Bg startup."""
                try:
                    await asyncio.sleep(4)
                    arch = None
                    # Découverte modèles
                    await scorer.discover()
                    # Architecture
                    try:
                        scorer._run_ssh = run_ssh
                        scorer._arch_detector = ArchitectureDetector(run_ssh)
                        arch = await scorer.get_arch()
                        app.arch = arch
                    except Exception as _ae:
                        logger.debug(f"arch detect bg: {_ae}")
                    if arch:
                        try:

                            def _show_arch() -> None:
                                """Show arch."""
                                try:
                                    app._safe_write(f"[dim]🖥 Architecture : {arch.summary()}[/]")
                                except Exception:
                                    pass

                            app.call_from_thread(_show_arch)
                        except Exception:
                            pass
                    # Benchmark
                    await scorer.refresh(bench=True)
                    logger.info(f"Benchmark terminé : {len(scorer.models)} modèles")
                    # Réassignation optimale
                    if scorer.is_ready:
                        optimal = await auto_select_models(scorer, arch)
                        nc, na, nr = optimal["chat"], optimal["action"], optimal["rag"]
                        save_last_assignment(nc, na, nr)
                        changed = []
                        if nc != app.model_chat:
                            app.model_chat = nc
                            changed.append(f"chat→{nc}")
                        if na != app.model_action:
                            app.model_action = na
                            changed.append(f"action→{na}")
                        if nr != app.model_rag:
                            app.model_rag = nr
                            changed.append(f"rag→{nr}")
                        try:
                            app._update_sidebar_title()
                            msg = ("🎯 Scoring terminé — " + " | ".join(changed)) if changed else "🎯 Scoring confirmé"
                            app._safe_write(f"[dim]{msg}[/]")
                        except Exception:
                            pass
                except asyncio.CancelledError:
                    pass
                except Exception as _be:
                    logger.debug(f"_bg_startup: {_be}")

            asyncio.create_task(_bg_startup())

        # ── diagnostic steps ──
        import pathlib as _plx

        _steplog = _plx.Path.home() / "AppData" / "Local" / "Temp" / "lf_steps.txt"
        _steplog.write_text("AVANT run_async\n", encoding="utf-8")
        # Capturer aussi les exceptions Textual silencieuses
        import sys as _sys_run

        _orig_excepthook = _sys_run.excepthook

        def _catch_all(exc_type, exc_val, exc_tb) -> None:
            """Catch all.

            Args:
                exc_type: Description.
                exc_val: Description.
                exc_tb: Description.
            """
            import traceback as _tb_all

            _steplog.write_text(
                f"EXCEPTHOOK:\n{''.join(_tb_all.format_exception(exc_type, exc_val, exc_tb))}", encoding="utf-8"
            )
            _orig_excepthook(exc_type, exc_val, exc_tb)

        _sys_run.excepthook = _catch_all
        try:
            await app.run_async()
        except Exception as _run_err:
            import traceback as _tbrx

            _steplog.write_text(f"run_async CRASH:\n{_tbrx.format_exc()}", encoding="utf-8")
            raise
        finally:
            _sys_run.excepthook = _orig_excepthook
        _steplog.write_text("APRES run_async\n", encoding="utf-8")
    else:
        print("❌ Textual non installé — interface graphique indisponible.")
        print("   Installez-le avec : pip install textual")
        print("   Puis relancez Nokido.")
        while True:
            try:
                cmd = input("> ").strip()
                if cmd in ("quit", "exit"):
                    break
                out, err, _ = await run_ssh(cmd)
                if out:
                    print(out)
                if err:
                    print(f"ERR: {err}")
            except (EOFError, KeyboardInterrupt):
                break

    print("\n🧹 Nettoyage des ressources :")
    print("  • Déconnexion du terminal (déjà effectuée dans l'application)...")
    print("  • Fermeture de la connexion SSH...", end=" ")
    if ssh_manager is not None:
        await ssh_manager.close()
    print("OK")
    print("  • Arrêt du gestionnaire Prefect...", end=" ")
    if prefect_manager is not None:
        await prefect_manager.stop()
    print("OK")
    print("  • Fermeture du moteur RAG...", end=" ")
    if rag_engine:
        await rag_engine.close()
    print("OK")
    print("  • Sauvegarde des sessions (automatique)...")
    print("✅ Nettoyage terminé.")
    print("Au revoir.")


# ── _launch_in_new_terminal ──────────────────────────────────


def _launch_in_new_terminal() -> bool:
    """
    Relance Nokido dans une nouvelle fenêtre terminal dédiée.
    La fenêtre appelante (qui a les logs) est masquée/minimisée.
    Retourne True si le relancement a réussi, False sinon.

    Ordre de préférence :
      Linux  : Windows Terminal (wt) → konsole → gnome-terminal → xterm → tmux
      macOS  : Terminal.app (osascript) → iTerm2
      Windows: Windows Terminal (wt) → cmd /K
    """
    import sys
    import os
    import subprocess as _sp

    script = os.path.abspath(sys.argv[0])
    py = sys.executable
    args = sys.argv[1:]
    cmd_args = [py, script] + args

    def _try(cmd) -> bool:
        """Try.

        Args:
            cmd: Description.
        """
        try:
            _sp.Popen(cmd, start_new_session=True, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            return True
        except (FileNotFoundError, OSError):
            return False

    plat = sys.platform

    if plat.startswith("linux"):
        # 1. Windows Terminal (disponible sur certains Linux via snap/flatpak)
        if _try(["wt", "--", "bash", "-c", " ".join(f"'{a}'" for a in cmd_args) + "; exec bash"]):
            return True
        # 2. Konsole (KDE)
        if _try(["konsole", "--noclose", "-e"] + cmd_args):
            return True
        # 3. GNOME Terminal
        if _try(
            [
                "gnome-terminal",
                "--",
            ]
            + cmd_args
        ):
            return True
        # 4. xfce4-terminal
        if _try(["xfce4-terminal", "-e", " ".join(cmd_args)]):
            return True
        # 5. xterm
        if _try(["xterm", "-e"] + cmd_args):
            return True
        # 6. tmux new-window si déjà dans une session tmux
        if os.environ.get("TMUX"):
            if _try(["tmux", "new-window"] + cmd_args):
                return True

    elif plat == "darwin":
        # macOS : osascript pour ouvrir Terminal.app
        osa_cmd = f'tell application "Terminal" to do script "{" ".join(cmd_args)}"'
        if _try(["osascript", "-e", osa_cmd]):
            return True

    elif plat == "win32":
        # Windows Terminal
        if _try(["wt", "-w", "0", "nt", "--"] + cmd_args):
            return True
        # Fallback cmd
        if _try(["cmd", "/C", "start", "cmd", "/K"] + cmd_args):
            return True

    return False  # aucun émulateur trouvé


# ── __main__ ──────────────────────────────────

if __name__ == "__main__":
    import sys
    import os

    # ── Mode normal (déjà dans la bonne fenêtre) ─────────────────────────────
    # On n'essaie de relancer dans une nouvelle fenêtre QUE si :
    #   1. Variable d'env LAFORGE_WINDOW=1 absente (évite boucle infinie)
    #   2. Pas de flag --no-window passé explicitement
    #   3. Pas déjà dans un tmux/screen (Textual gère bien ces contextes)
    _already_windowed = os.environ.get("LAFORGE_WINDOW") == "1"
    _no_window_flag = "--no-window" in sys.argv
    _in_multiplexer = bool(os.environ.get("TMUX") or os.environ.get("STY") or os.environ.get("ZELLIJ"))

    # Sur Windows : ne jamais relancer dans une nouvelle fenêtre
    # Le lanceur .bat gère le choix du terminal.
    # --force-window est le seul moyen de forcer une nouvelle fenêtre.
    _force_window = "--force-window" in sys.argv
    _in_win_terminal = sys.platform == "win32" and not _force_window

    if not _already_windowed and not _no_window_flag and not _in_multiplexer and not _in_win_terminal:
        # Tenter de relancer dans une fenêtre dédiée
        os.environ["LAFORGE_WINDOW"] = "1"
        if _launch_in_new_terminal():
            # Succès — minimiser/fermer le terminal courant proprement
            print("⚒  La Forge lancée dans une nouvelle fenêtre.")
            try:
                # Tenter de minimiser la fenêtre courante (Linux X11)
                import subprocess as _sp2

                _wid = _sp2.check_output(["xdotool", "getactivewindow"], stderr=_sp2.DEVNULL).strip()
                _sp2.Popen(["xdotool", "windowminimize", _wid], stdout=_sp2.DEVNULL, stderr=_sp2.DEVNULL)
            except Exception:
                pass
            sys.exit(0)
        # Relancement échoué → continuer normalement dans cette fenêtre
        print("⚒  Lancement direct (aucun émulateur terminal détecté).")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrompu.")
    except Exception as e:
        print(f"Erreur fatale : {e}")
        import traceback

        traceback.print_exc()


# ── _after_wizard (extrait de Nokido.py) ──────────────────────────────


async def _after_wizard(configured: bool) -> None:
    """After wizard.

    Args:
        configured: Description.
    """
    if not configured:
        app._set_ssh_mode(False)
        app._chat_log().write(
            "[yellow]⚠ Mode local — pas de connexion SSH.[/]\n"
            "  [dim]Le terminal est masqué. Tapez [bold]@ssh <host>[/] pour vous connecter.[/]"
        )
        return
    # Connexion avec les valeurs saisies dans le wizard
    try:
        await ssh_manager.connect()
        _hn = settings.ssh_host
        try:
            _o, _, _ = await run_ssh("hostname -f 2>/dev/null || hostname")
            _hn = _strip_ssh_output(_o)
        except Exception:
            pass
        _kern = ""
        try:
            _o2, _, _ = await run_ssh("uname -r")
            _kern = _strip_ssh_output(_o2)
        except Exception:
            pass
        _ks = f" · [dim]kernel {_kern}[/]" if _kern else ""
        app._set_ssh_mode(True, hostname=_hn or settings.ssh_host)
        app._chat_log().write(
            f"[green]✅ SSH[/] [bold]{_hn}[/] "
            f"[dim]({settings.ssh_host}:{settings.ssh_port})[/] "
            f"sudo={'[green]oui[/]' if ssh_manager.sudo_available else '[yellow]non[/]'}"
            f"{_ks}"
        )
    except Exception as _e:
        app._set_ssh_mode(False)
        app._chat_log().write(f"[red]❌ SSH: {_e}[/]")


# ── ping_brain (extrait Nokido.py) ────────────────────────────────


async def _ping_brain() -> None:
    """Ping silencieux : n'affiche rien si OK, message discret si KO."""
    try:
        import zmq as _zmq_b

        # Contexte isolé — ne pollue pas le contexte asyncio global
        _ctx_b = _zmq_b.Context()
        _s = _ctx_b.socket(_zmq_b.REQ)
        _s.setsockopt(_zmq_b.LINGER, 0)
        _s.setsockopt(_zmq_b.RCVTIMEO, 2000)
        _s.connect("tcp://127.0.0.1:5557")
        try:
            try:
                import msgpack as _mp_b

                _s.send(_mp_b.packb({"cmd": "status"}, use_bin_type=True))
                _raw = _s.recv()
                _rep = _mp_b.unpackb(_raw, raw=False)
            except ImportError:
                import json as _jb

                _s.send(_jb.dumps({"cmd": "status"}).encode())
                _rep = _jb.loads(_s.recv().decode())
            _d = _rep.get("data", {})
            _ep = _d.get("ep_backend", "")
            _dim = _d.get("dim", "")
            _emb = _d.get("embedder", False)
            _gen = _d.get("generator", False)
            # Afficher seulement si quelque chose ne va pas
            if not _emb or not _gen:
                _ep_str = f" [{_ep.upper()}]" if _ep else ""
                _dim_str = f" dim={_dim}" if _dim else ""
                app._chat_log().write(
                    f"[bold #a371f7]⚡ Brain[/]{_ep_str}"
                    f" emb=[{'green' if _emb else 'red'}]{'OK' if _emb else 'NON'}[/]"
                    f" gen=[{'dim' if _gen else 'red'}]{'OK' if _gen else 'NON'}[/]"
                    f"[dim]{_dim_str}[/]"
                )
            # Sinon : Brain OK, pas de bruit dans le chat
        except Exception as _pe:
            app._chat_log().write(f"[dim]⚡ Brain: non disponible ({_pe})[/]")
        finally:
            _s.close()
            _ctx_b.term()
    except ImportError:
        pass


# ── handle_after_wizard : doublon RETIRE le 2026-08-14 ──────────────────
# Ce fichier definissait `_after_wizard` DEUX fois, a l'identique (meme sha de
# source). La seconde ecrasait silencieusement la premiere a l'import : aucune
# erreur, aucun avertissement, et toute correction apportee a la premiere etait
# sans effet. Meme famille que `embed_batch` defini 2x (incident 2026-08-03).
# La definition qui subsiste est celle de la ligne 582.


async def _init_onnx_bg() -> None:
    """Init onnx bg."""
    from nokido_agent.app.forge_npu_embedder import init_onnx_backend

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: init_onnx_backend(
            load_generator=True,
            auto_launch=True,
        ),
    )
    _emb = result.get("embedder", False)
    _gen = result.get("generator", False)
    _ts = result.get("tree_sitter", False)
    from app.core.settings import get_app_attr as _gaa_onnx

    _app = _gaa_onnx("_chat_log")
    _c = _app() if callable(_app) else None
    if _c is None:
        import logging as _lg_onnx

        class _FakeChat:
            """Write.

            Args:
                m: Description.
            """

            def write(self, m) -> None:
                """Write."""
                _lg_onnx.getLogger("Nokido.NPU").info(m)

        _c = _FakeChat()

    # ── Affichage Sidecar (une ligne résumée) ──
    _parts = []
    _log_parts = []
    if _emb:
        _parts.append("[green]✅ Embeddings MiniLM[/]")
        _log_parts.append("Embeddings=MiniLM")
    else:
        _parts.append("[dim]Embeddings → Ollama[/]")
        _log_parts.append("Embeddings=Ollama")
    if _gen:
        _parts.append("[green]✅ Génération Phi-3.5[/]")
        _log_parts.append("Génération=Phi-3.5")
    else:
        _parts.append("[green]✅ Génération → Ollama[/]")
        _log_parts.append("Génération=Ollama")
    _c.write("[bold #a371f7]⚡ Sidecar[/] " + "  ".join(_parts))
    logger.info(f"[boot] Sidecar : {' | '.join(_log_parts)}")

    # ── Affichage tree-sitter ──
    if _ts:
        _c.write("[bold #a371f7]🛡️ Sentinelle[/] [green]✅ tree-sitter actif[/]")
        logger.info("[boot] Sentinelle : tree-sitter actif")
    else:
        _c.write("[bold #a371f7]🛡️ Sentinelle[/] [dim]⚠ tree-sitter inactif → audit AST natif[/]")
        logger.warning("[boot] Sentinelle : tree-sitter inactif")


def _purge_pycache() -> None:
    """Purge pycache."""
    import pathlib, shutil

    _base = pathlib.Path(__file__).parent
    _cache = _base / "__pycache__"
    if _cache.exists():
        shutil.rmtree(_cache, ignore_errors=True)
    for _pyc in _base.glob("*.pyc"):
        try:
            _pyc.unlink()
        except Exception:
            pass
    # `__main__` n'est JAMAIS retire (MESURE 2026-09-25, journal du bridge TUI :7440) : le script
    # lance EST app/Nokido.py, donc son module tombait dans ce filtre. Retire de sys.modules,
    # `inspect.getfile(DevOpsApp)` levait « source code not available » dans le constructeur
    # Textual -- la TUI mourait avant d'afficher, et le navigateur attendait sans fin.
    _mods = [
        k
        for k, v in list(sys.modules.items())
        if k != "__main__"
        and getattr(v, "__file__", None) and str(_base) in str(getattr(v, "__file__", ""))
    ]
    for _m in _mods:
        try:
            del sys.modules[_m]
        except Exception:
            pass
    print(f"  [*] Cache Python purgé (dossier: {_base.name})", flush=True)


def _read_env_file(path: str = "Nokido.env") -> None:
    """Charge un fichier .env dans os.environ (ne surcharge pas les vars existantes).
    Cherche d'abord dans le dossier du script, puis dans le CWD.
    """
    import pathlib as _pl

    # Résoudre le chemin depuis le dossier du script (robuste peu importe le CWD)
    _script_dir = _pl.Path(__file__).resolve().parent
    _candidates = [
        _script_dir / path,  # app/LaForge.env
        _script_dir.parent / path,  # LaForge/LaForge.env  ← correct
        _pl.Path(path),
    ]  # CWD fallback
    _resolved = next((p for p in _candidates if p.exists()), None)
    if _resolved is None:
        return  # fichier absent → silencieux, Settings utilisera os.environ
    path = str(_resolved)
    try:
        with open(path, encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and "=" in _line and not _line.startswith("#"):
                    _k, _, _v = _line.partition("=")
                    # Retirer les guillemets éventuels
                    _v = _v.strip().strip('"').strip("'")
                    os.environ.setdefault(_k.strip(), _v)
    except FileNotFoundError:
        pass
    except Exception as _e:
        print(f"  ⚠ Lecture {path} : {_e}", flush=True)
