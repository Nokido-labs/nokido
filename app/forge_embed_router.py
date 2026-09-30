"""forge_embed_router.py — cascade embedding providers.

Priorite REELLE : elle est donnee par `config/pillar_policy.json` (`backends.embed`),
pas par cette docstring ni par l'ordre de PROVIDERS -- les deux cascades, unitaire
(`embed`) et par lot (`embed_batch_fast`), la lisent a chaque appel. Au 2026-09-06 :
llama8099 (local :8099, bge-m3, 15,6 chunks/s, RSS borne ~2,5 Go) > cloudflare
(Workers AI @cf/baai/bge-m3, quota journalier) > modal (A10G self-hosted, workspace
404 depuis le 2026-09-01).

⚠️ Les chiffres de quota ecrits dans ce fichier sont DATES et se periment : ne pas
budgeter dessus sans une mesure du jour (outils : `tools/forge_embed_cloudflare_lot.py`
pour le quota Cloudflare, `tools/forge_embed_8099_mesure_bornee.py` pour la RAM locale).

Compat existing rag_chunks.embedding format = 1024D float32 binaire.

API :
    embed(text)              -> list[float] (1024D) ou None
    embed_batch(texts, k=8)  -> list[list[float]] (parallel where possible)
    health_providers()       -> dict status
"""

from __future__ import annotations
import argparse
import json
import logging
import os
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("embed_router")


# --- Provider 1 : brain_worker local ZMQ ---


def _brain_worker_call(texts: list[str], timeout: float = 60.0) -> list[list[float]] | None:
    """ZMQ submit batch BGE-M3. Retourne liste de vecteurs (None si KO)."""
    try:
        import zmq
        import msgpack
    except ImportError:
        return None
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.RCVTIMEO, int(timeout * 1000))
    sock.setsockopt(zmq.SNDTIMEO, 3000)
    try:
        sock.connect("tcp://localhost:5557")
        sock.send(msgpack.packb({"cmd": "submit", "type": "embed", "texts": texts}, use_bin_type=True))
        rep = msgpack.unpackb(sock.recv(), raw=False)
        task_id = rep.get("task_id")
        if not task_id:
            return None
        for _ in range(int(timeout / 0.5)):
            sock.send(msgpack.packb({"cmd": "check", "task_id": task_id}, use_bin_type=True))
            r = msgpack.unpackb(sock.recv(), raw=False)
            status = r.get("status", "pending")
            if status == "completed":
                data = r.get("data")
                vecs = data.get("vecs", []) if isinstance(data, dict) else data
                return [list(v) for v in vecs] if vecs else None
            if status == "error":
                return None
            time.sleep(0.5)
        return None
    except Exception as e:
        logger.debug(f"brain_worker batch KO: {e}")
        return None
    finally:
        try:
            sock.close()
        except Exception:  # muet-ok socket close cleanup
            pass


def _embed_brain_worker(text: str, timeout: float = 30.0) -> list[float] | None:
    """Wrapper single text -> batch=1."""
    result = _brain_worker_call([text], timeout=timeout)
    return result[0] if result else None


# --- Provider 2 : HuggingFace Inference API ---

# HF Inference Providers (free 2025+) — remplace api-inference.huggingface.co deprecated
HF_BGE_M3_URL = "https://router.huggingface.co/hf-inference/models/BAAI/bge-m3/pipeline/feature-extraction"


def _embed_hf(text: str, timeout: float = 15.0) -> list[float] | None:
    """HF Inference API BAAI/bge-m3 -- MEME espace vectoriel que le local.

    Le « free tier ~1k req/jour » d'origine est PERIME : le gratuit HF est desormais
    un credit mensuel en dollars sur les Inference Providers, non convertible en
    requetes sans le prix CPU de la route. Repli d'appoint, jamais moteur de campagne.
    """
    try:
        from nokido_agent.app.forge_secrets import get_secret  # type: ignore

        key = get_secret("HF_TOKEN")
    except Exception:  # muet-ok secrets import fallback
        key = get_secret("HF_TOKEN") or ""
    if not key:
        return None
    body = json.dumps({"inputs": text[:8000]}).encode()
    req = urllib.request.Request(
        HF_BGE_M3_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key.strip()}",
            "User-Agent": "Mozilla/5.0 LaForge-Embed",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        # HF format : peut etre liste directe OR dict avec 'embeddings'
        if isinstance(data, list) and data and isinstance(data[0], (int, float)):
            return data
        if isinstance(data, list) and data and isinstance(data[0], list):
            return data[0]
        if isinstance(data, dict):
            emb = data.get("embeddings") or data.get("embedding")
            if isinstance(emb, list) and emb:
                if isinstance(emb[0], list):
                    return emb[0]
                return emb
        return None
    except urllib.error.HTTPError as e:
        logger.debug(f"HF HTTP {e.code}: {e.read()[:200]}")
        return None
    except Exception as e:
        logger.debug(f"HF KO: {e}")
        return None


# --- Provider 3 : Jina embeddings v3 ---

JINA_URL = "https://api.jina.ai/v1/embeddings"


def _jina_call(texts: list[str], timeout: float = 30.0) -> list[list[float]] | None:
    """Jina batch API : jusqu a 2048 inputs en 1 call = 1 RTT au lieu de N."""
    try:
        from nokido_agent.app.forge_secrets import get_secret

        key = get_secret("JINA_API_KEY")
    except Exception:  # muet-ok secrets import fallback
        key = get_secret("JINA_API_KEY") or ""
    if not key:
        return None
    body = json.dumps(
        {
            "model": "jina-embeddings-v3",
            "task": "retrieval.passage",
            "dimensions": 1024,
            "input": [t[:8000] for t in texts],
        }
    ).encode()
    req = urllib.request.Request(
        JINA_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key.strip()}",
            "User-Agent": "Mozilla/5.0 LaForge-Embed",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        items = data.get("data", [])
        if not items:
            return None
        return [it.get("embedding") for it in items if it.get("embedding")]
    except urllib.error.HTTPError as e:
        logger.debug(f"Jina HTTP {e.code}: {e.read()[:200]}")
        return None
    except Exception as e:
        logger.debug(f"Jina KO: {e}")
        return None


def _embed_jina(text: str, timeout: float = 15.0) -> list[float] | None:
    """Single wrapper -> batch=1."""
    result = _jina_call([text], timeout=timeout)
    return result[0] if result else None


# --- Provider Voyage AI (200M tokens trial gratuit, batch 128 max) ---

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"


def _voyage_call(texts: list[str], timeout: float = 30.0) -> list[list[float]] | None:
    """Voyage AI batch API : jusqu'a 128 inputs/call. voyage-3 = 1024D."""
    key = None
    try:
        from nokido_agent.app.forge_secrets import get_secret

        key = get_secret("VOYAGE_API_KEY")
    except Exception as exc:  # noqa: BLE001
        # PAS de muet-ok ici : un coffre illisible se lit alors comme "pas de cle
        # Voyage", donc comme un provider non configure. C'est exactement le faux
        # negatif paye le 2026-07-31, ou un DPAPI casse sous le compte de service
        # a fait conclure qu'un token VALIDE etait mort -- on a failli le revoquer.
        logger.debug(f"VOYAGE_API_KEY illisible ({type(exc).__name__}) -> provider ignore")
    if not key:
        key = get_secret("VOYAGE_API_KEY") or ""
    if not key:
        return None
    body = json.dumps(
        {
            "model": "voyage-3",
            "input": [t[:8000] for t in texts[:128]],  # cap 128 inputs/call
            "input_type": "document",
            "output_dimension": 1024,
        }
    ).encode()
    req = urllib.request.Request(
        VOYAGE_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key.strip()}",
            "User-Agent": "Mozilla/5.0 LaForge-Embed",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        items = data.get("data", [])
        if not items:
            return None
        return [it.get("embedding") for it in items if it.get("embedding")]
    except urllib.error.HTTPError as e:
        logger.debug(f"Voyage HTTP {e.code}: {e.read()[:200]}")
        return None
    except Exception as e:
        logger.debug(f"Voyage KO: {e}")
        return None


def _embed_voyage(text: str, timeout: float = 15.0) -> list[float] | None:
    result = _voyage_call([text], timeout=timeout)
    return result[0] if result else None


# --- Provider 4 : Modal (placeholder, requiert deploy custom) ---

MODAL_ENDPOINT_ENV = "LAFORGE_MODAL_EMBED_URL"


def _modal_url() -> str:
    """URL de l'endpoint Modal, lue AU COFFRE puis a l'environnement.

    Regle owner 2026-08-19 : « TOUS les clients passent par le vault ». Ce
    provider lisait `os.environ` SEUL : l'endpoint deploye le 19/08
    (`https://naarobb--bge-m3-embed.modal.run`, pose au coffre DPAPI) restait
    donc invisible, et `health_providers()` rendait `not_configured` sur une
    app parfaitement vivante. `get_secret` porte deja la chaine de precedence
    (coffre -> WCM -> Nokido.env -> environnement) : on la reutilise plutot que
    d'en ecrire une seconde.
    """
    try:
        from nokido_agent.app.forge_secrets import get_secret

        v = get_secret(MODAL_ENDPOINT_ENV)
        if v:
            return v
    except Exception:  # noqa: BLE001 - coffre indisponible : repli sur l'environnement
        pass
    return os.environ.get(MODAL_ENDPOINT_ENV) or ""


def _modal_call(texts: list[str], timeout: float = 20.0) -> list[list[float]] | None:
    """Modal batch endpoint (deploy via tools/deploy_modal_bge_m3.py).
    Format compat : POST {texts: [...]} -> {embeddings: [[...], ...], dim: 1024}."""
    url = _modal_url()
    if not url:
        return None
    try:
        body = json.dumps({"texts": [t[:8000] for t in texts]}).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 LaForge-Embed",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        emb = data.get("embeddings")
        return emb if isinstance(emb, list) else None
    except Exception as e:
        logger.debug(f"Modal batch KO: {e}")
        return None


def _embed_modal(text: str, timeout: float = 10.0) -> list[float] | None:
    """Single wrapper -> batch=1."""
    result = _modal_call([text], timeout=timeout)
    return result[0] if result else None


# --- Router cascade ---

# Ordre LOCAL-FIRST (Golden Rule "worker le moins coûteux d'abord", 2026-06-03) :
# brain_worker :5557 (loopback, sans egress, souverain) AVANT le cloud. L'ancien
# ordre cloud-first (modal/voyage en tête) produisait des embeddings NULL dans les
# contextes SANS internet (ex: ChainExecutor veille, trusted = egress bloqué) ->
# corpus non cherchable. Cloud = fallback pour contextes avec egress uniquement.
_WANT_TS: dict = {}


def declare_wanted(flag: str, cooldown: float = 300.0, motif: str = "") -> bool:
    """Pose l'intention `sandbox/<flag>` — le corps VEUT ce pilier maintenant.

    Vocabulaire COMMUN a tout l'organisme (docker.wanted / llama.wanted /
    rerank.wanted / embed.wanted / snn.wanted) : lu par forge_resource_manager pour
    EPARGNER le service, et par forge_llama_keeper._piliers_on_demand pour le
    RALLUMER. Un lecteur sans declarant ne vaut rien — c'est l'asymetrie payee sur
    llama.wanted (73 arrets en 7,6 j, 312,94 Go rechargees — [PERIME 2026-08-20],
    recompte sur lifecycle_actions.jsonl : 32 `llm stop` + 4 `llm evict` sur
    7 j, soit ~2x MOINS ; garder l'ancien chiffre visible, il date le regime
    d'avant et c'est lui qui a motive le drapeau) : quatre organes
    lisaient l'intention, un seul reveilleur sur six la posait.

    Rend True si l'intention vient d'etre posee, False si cooldown OU ecriture
    refusee — et le DIT : une ecriture refusee ne doit pas passer pour un succes.
    """
    import time as _t

    # Le corps ARBITRE avant que le client ne pose son drapeau. Sans cet appel une
    # reclamation valait un ORDRE : le client echouait, posait l'intention, le keeper
    # rallumait le pilier, la regulation l'evincait pour rendre la RAM, et le client
    # recommencait 19 s plus tard (mesure 2026-09-01, machine a 98 %).
    try:
        from nokido_agent.app.forge_pillar_arbiter import reclamer

        verdict = reclamer(flag, motif)
        if not verdict.get("accorde", True):
            logger.warning(
                "[intention] %s NON POSEE -- le corps refuse : %s%s", flag,
                verdict.get("motif") or "sans motif",
                (" | substitut : " + str(verdict["substitut"]))
                if verdict.get("substitut") else "")
            return False
    except Exception as exc:  # noqa: BLE001 - arbitre indisponible : on ne bloque pas
        logger.debug("[intention] arbitre indisponible (%r) -- reclamation non filtree", exc)

    import pathlib as _pl

    _sb = _pl.Path(__file__).resolve().parent.parent / "sandbox"
    _cible = _sb / flag

    now = _t.time()
    if now - _WANT_TS.get(flag, 0.0) < cooldown:
        # LE COOLDOWN RAISONNE SUR LA MEMOIRE DU PROCESSUS, JAMAIS SUR LE DISQUE.
        # MESURE RUNTIME 2026-09-20 : `sandbox/rerank.wanted` a 0 octet depuis
        # 69,6 min -> `_intention_voulue()` rend False et le corps se croit sans
        # demande, alors qu'un organe venait d'en exprimer une. Le test de cooldown
        # tombait AVANT toute lecture du fichier : un drapeau VIDE ou EFFACE restait
        # donc dans cet etat pendant toute la duree du cooldown.
        #
        # Le cooldown reste necessaire -- il evite de repiler une intention identique
        # a chaque appel, et un drapeau VALIDE continue d'etre protege (un NR le garde
        # explicitement, sinon supprimer le frein passerait pour un correctif).
        # Ce qu'on corrige est plus etroit : un drapeau ILLISIBLE n'est pas une
        # intention posee. Pour le consommateur, absent et vide disent la meme chose.
        # « attempt != success », applique cette fois a la REPARATION.
        try:
            _restant = _cible.read_bytes()
        except FileNotFoundError:
            _restant = b""          # efface -> il n'y a plus d'intention a proteger
        except OSError as _exc:
            # ILLISIBLE n'est pas ABSENT, mais le consommateur n'en tirera rien non
            # plus : on le DIT et on repose, plutot que de laisser le corps aveugle.
            logger.warning("[intention] %s ILLISIBLE sous cooldown (%r) -- repose", flag, _exc)
            _restant = b""
        if _restant.strip():
            return False            # intention valide et fraiche : le frein tient
        logger.warning(
            "[intention] %s cooldown OUTREPASSE -- le drapeau sur disque est %s, "
            "donc AUCUNE intention n'est posee pour le consommateur", flag,
            "absent" if not _cible.exists() else "vide")
    try:
        _sb.mkdir(parents=True, exist_ok=True)
        _cible.write_text(str(now), encoding="utf-8")
        # RELECTURE OBLIGATOIRE — une ecriture qui rend la main n'est pas une
        # intention posee. MESURE 2026-09-20 : `sandbox/rerank.wanted` a 0 octet
        # avec un mtime de 25 min, pendant que le journal ne portait AUCUNE ligne
        # « NON posee ». Un drapeau vide ne se lit PAS comme une intention --
        # `forge_audit_intention_effet` rendait `rerank: false` et `chaines=0` --
        # donc l'annoncer posee fabrique un FAUX CALME : le corps croit avoir
        # reclame le pilier, `_piliers_on_demand` ne voit rien a rallumer, et
        # NokidoEpistemicSoif attend derriere une dep :8100 qui n'ouvrira jamais.
        # « attempt != success », applique ici a l'ecriture elle-meme.
        _relu = _cible.read_bytes()
        if not _relu.strip():
            logger.warning(
                "[intention] %s NON POSEE -- ecriture relue VIDE (%d o) : le "
                "drapeau existe mais ne porte aucune intention lisible", flag,
                len(_relu))
            return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("[intention] %s NON POSEE (%r)", flag, exc)
        return False
    _WANT_TS[flag] = now
    logger.warning("[intention] %s posee%s", flag, (" -- " + motif) if motif else "")
    # DECLARER ce qu'on vient d'ECRIRE. La docstring ci-dessus nomme deja le defaut
    # -- « un lecteur sans declarant ne vaut rien » -- mais ce poseur ne l'alimentait
    # pas lui-meme. Mesure du 2026-09-20 par forge_signal_coupling :
    #     llama.wanted     COUPLE                 em=1
    #     rerank.wanted    DECOY_LECTEUR_PASSIF   em=0
    #     lmstudio.wanted  DECOY_LECTEUR_PASSIF   em=0
    #     docker.wanted    DECOY_LECTEUR_PASSIF   em=0  (+ DEGENERESCENCE)
    # Or rerank.wanted N'EST PAS sans emetteur : le fichier existe, 326 lignes de
    # journal, ZERO ligne « NON posee ». `em` ne mesure pas l'emission mais la
    # DECLARATION -- et forge_signal_coupling l'exige explicitement parce qu'un grep
    # mentait (« 14 lectures et 0 ecriture, et c'etait FAUX »). C'etait donc un
    # DECLARANT MANQUANT, pas un emetteur absent.
    # UN SEUL point suffit : ce poseur est commun aux trois appelants qui l'importent
    # sous l'alias `_dw` (forge_mcp_registry, forge_rag_engine, forge_resource_manager).
    # Place APRES l'ecriture et sur le seul chemin qui rend True : un cooldown, un
    # refus de l'arbitre ou une ecriture refusee ne sont PAS des emissions, et les
    # compter ferait passer pour couple un signal qui ne sort jamais.
    try:
        from nokido_agent.app.forge_signal_coupling import emit_signal as _emit
        _emit(flag)
    except Exception as _exc:  # noqa: BLE001
        # muet-ok : un capteur de couplage ne doit JAMAIS casser l'emission qu'il
        # observe -- ce serait pire que le defaut qu'il cherche.
        logger.debug("[intention] %s posee mais NON declaree (%r)", flag, _exc)
    return True


def _campagne_cloud_bat(fraicheur_s: float = 180.0) -> bool:
    """Une campagne d'embeddings CLOUD couvre-t-elle deja la file ?

    Mesure 2026-09-01 : `:8099` a ete RALLUME 19 s apres son arret, parce que le
    drain ne le trouvait plus et a pose `embed.wanted` — pendant qu'une campagne
    Modal vectorisait la meme file 26 fois plus vite. Resultat : 12 Go d'embedder
    local repris pour rien, la machine a 98 % de RAM, et les deux ecrivains en
    collision sur l'unique writer SQLite.

    Reclamer un pilier dont un autre chemin fait deja le travail n'est pas une
    intention, c'est du bruit. On lit donc le battement de la campagne AVANT de
    declarer. Battement perime ou fini => la campagne ne couvre plus rien, et la
    reclamation redevient legitime.
    """
    import json as _j
    import pathlib as _pl
    import time as _t

    p = _pl.Path(__file__).resolve().parent.parent / "sandbox" / "modal_campagne.heartbeat"
    try:
        d = _j.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except Exception:  # noqa: BLE001 - illisible : on ne bloque pas une reclamation
        return False
    if d.get("fini"):
        return False
    return (_t.time() - float(d.get("ts") or 0)) < fraicheur_s


def declare_embed_wanted(cooldown: float = 300.0) -> bool:
    """Declare que quelquun ATTEND lembedder :8099 (patron sandbox/*.wanted).

    Depuis le boot-trim RAM du 2026-08-10, NokidoLlamaEmbed demarre disabled. Sans ce
    declarant, lingestion echoue en silence et le corpus accumule des chunks SANS
    vecteur -- le mecanisme meme des 278512 chunks non vectorises. On POSE lintention,
    on ne demarre rien soi-meme : le client declare, le corps enacte (meme vocabulaire
    que docker.wanted / llama.wanted / rerank.wanted, lu par forge_resource_manager).

    Rend True si lintention vient detre posee, False si cooldown OU ecriture refusee --
    et le DIT dans les logs : une ecriture refusee ne doit pas passer pour un succes.
    """
    if _campagne_cloud_bat():
        logger.info("[intention] embed.wanted NON posee : une campagne cloud "
                    "couvre deja la file (eviter 12 Go d'embedder redondant)")
        return False
    return declare_wanted(
        "embed.wanted", cooldown,
        ":8099 injoignable ; sans reveil, les nouveaux chunks entrent SANS vecteur")


def _role_embed_local_autorise() -> bool:
    """Le corps autorise-t-il le backend d'embedding LOCAL :8099 ?

    TROIS portes tapent :8099 -- `_embed_llama8099`, `_llama8099_call` et le POST
    inline de `embed_batch`. Filtrer la seule cascade `PROVIDERS` n'en fermait
    AUCUNE des deux dernieres, qui sont justement le chemin de MASSE (vectorisation
    par lots). La garde est donc ici, au ras du socket, et non au-dessus.

    Arbitre absent ou illisible => True : on ne coupe pas un backend par omission.
    """
    try:
        from nokido_agent.app.forge_pillar_arbiter import backend_autorise

        return backend_autorise("embed", "llama8099")
    except Exception as exc:  # noqa: BLE001 - arbitre indisponible : on ne coupe rien
        logger.debug("[arbitre] indisponible (%r) -- backend local non filtre", exc)
        return True


def _embed_llama8099(text: str, timeout: float = 30.0) -> list[float] | None:
    """LOCAL BGE-M3 via NokidoLlamaEmbed :8099 (GGUF llama.cpp GPU). 1024d, gratuit, pas
    d'egress, urllib pur (zéro litellm). Remplace brain_worker :5557 (ONNX 'bad allocation'
    OOM, disabled 2026-06-03) comme 1er provider local VIVANT. Endpoint OpenAI /v1/embeddings."""
    if not _role_embed_local_autorise():
        return None
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8099/v1/embeddings",
            data=json.dumps({"input": text}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
        emb = d.get("data", [{}])[0].get("embedding") if "data" in d else d.get("embedding")
        if emb and isinstance(emb[0], list):
            emb = emb[0]
        return emb if emb and len(emb) >= 256 else None
    except Exception as e:
        logger.debug(f"llama8099 embed failed: {e}")
        declare_embed_wanted()
        return None


def _llama8099_call(texts: list[str], timeout: float = 60.0) -> list[list[float]] | None:
    """Batch BGE-M3 via :8099 (OpenAI /v1/embeddings accepte input=[liste]). Préserve l'ordre
    (data[].index si présent). Local, GPU, sans egress -> 1er essai du batch souverain."""
    if not _role_embed_local_autorise():
        return None
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8099/v1/embeddings",
            data=json.dumps({"input": texts}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
        data = d.get("data")
        if not data or len(data) != len(texts):
            # TROIS causes rendaient le MEME None, et l'appelant n'annoncait qu'une
            # « shape inattendue » quelle que soit la vraie raison. Le repli local du
            # deport est reste « casse » du 2026-08-03 au 2026-08-05 sans que personne
            # ne puisse dire pourquoi : c'est le diagnostic qui manquait, pas le code.
            logger.warning(
                "[llama8099] reponse INEXPLOITABLE : %d vecteur(s) pour %d texte(s) "
                "| consequence: l'appelant verra un None indistinguable d'une panne "
                "reseau", len(data or []), len(texts))
            return None
        if all("index" in it for it in data):
            data = sorted(data, key=lambda it: it["index"])
        out = []
        for it in data:
            emb = it.get("embedding")
            if not emb or len(emb) < 256:
                logger.warning(
                    "[llama8099] vecteur de dimension %s (< 256) — reponse rejetee | "
                    "consequence: un embedder qui repond mais mal est plus trompeur "
                    "qu'un embedder muet", len(emb or []))
                return None
            out.append(emb)
        return out
    except Exception as e:
        # `debug` rendait cette cause INVISIBLE en production. C'est ici que se
        # perdait le motif REEL (proxy, timeout, HTTP 500 sur un texte trop long),
        # et l'appelant ne recevait qu'un None muet.
        logger.warning(
            "[llama8099] appel ECHOUE (%s: %s) — %d texte(s) | consequence: le repli "
            "local est ecarte de l'election et le corpus attend un provider cloud",
            type(e).__name__, str(e)[:120], len(texts))
        declare_embed_wanted()
        return None


import http.client as _hc  # noqa: E402
import socket  # noqa: E402


class _ConnexionIPv4(_hc.HTTPSConnection):
    """Connexion HTTPS qui sort en IPv4, pour CETTE connexion seulement.

    MESURE 2026-09-16, et elle corrige une conclusion fausse. Workers AI rendait
    `code 10000 Authentication error` ; la lecture naturelle est « cle expiree ou
    revoquee ». Le token est VALIDE. Ce qui est refuse, c'est l'ADRESSE SOURCE :

        sortie IPv6 (defaut de Python) -> HTTP 403, code 9109,
                                          « Cannot use the access token from location: <IPv6> »
        sortie IPv4 forcee             -> HTTP 200, puis embedding bge-m3 dim 1024

    Le token porte une allowlist d'adresses qui contient l'IPv4 et pas l'IPv6.
    `getaddrinfo` prefere l'IPv6 des que l'acces en annonce une : le jour ou cette
    IPv6 est apparue, un provider cable et fonctionnel depuis le 2026-08-20 s'est
    mis a repondre « authentification », sans que rien n'ait ete touche.

    POURQUOI PAS UN PATCH GLOBAL de `socket.getaddrinfo` : le hub est multi-thread
    et ce module est appele en lot ; changer le resolveur du process forcerait la
    famille d'adresse d'appels CONCURRENTS qui n'ont rien demande. La contrainte
    reste donc attachee a la connexion.

    A SAVOIR pour le diagnostic : un code d'erreur d'authentification ne nomme
    jamais sa cause. Quatre cas s'y ecrivent pareil -- token mort, token sans la
    permission, mauvais account, adresse source refusee -- et un seul se repare
    sans toucher au secret. Sonder `/user/tokens/verify` puis `/accounts/<id>`
    les separe.
    """

    def connect(self):  # noqa: D102 - contrat de http.client
        infos = socket.getaddrinfo(self.host, self.port,
                                   socket.AF_INET, socket.SOCK_STREAM)
        derniere = None
        sock = None
        for af, styp, proto, _canon, sa in infos:
            s = socket.socket(af, styp, proto)
            try:
                if self.timeout is not None:
                    s.settimeout(self.timeout)
                s.connect(sa)
                sock = s
                derniere = None
                break
            except OSError as e:
                s.close()
                derniere = e
        if sock is None:
            raise derniere or OSError("aucune adresse IPv4 pour %s" % self.host)
        self.sock = sock
        if self._tunnel_host:
            self._tunnel()
        self.sock = self._context.wrap_socket(
            self.sock, server_hostname=self._tunnel_host or self.host)


def _opener_ipv4():
    """Opener urllib dont les connexions HTTPS sortent en IPv4."""
    import urllib.request as _ur  # noqa: PLC0415

    class _HandlerIPv4(_ur.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(_ConnexionIPv4, req)

    return _ur.build_opener(_HandlerIPv4())


def _cloudflare_call(texts: list[str], timeout: float = 30.0) -> list[list[float]] | None:
    """Workers AI `@cf/baai/bge-m3` — LE MEME MODELE que le local :8099.

    POURQUOI JUSTE APRES LE LOCAL, avant jina/hf/voyage : ces trois-la servent
    d'AUTRES modeles, donc un AUTRE espace vectoriel. Melanger deux espaces dans
    la meme colonne `embedding` rend les distances incomparables — un vecteur
    voyage et un vecteur bge-m3 ne se comparent pas, et rien dans le schema ne
    signale le melange. Cloudflare rend du bge-m3 1024D : ses vecteurs sont
    directement comparables aux ~1 000 368 deja en base.

    CAPACITE DORMANTE (mesure 2026-08-20) : `tools/forge_rebuild_embeddings.py`
    savait deja appeler cet endpoint, `forge_provider_catalogue` declarait la
    cle, `forge_llm_budget` lui donnait meme un quota — mais le ROUTEUR ne l'a
    jamais eue dans PROVIDERS. Ecrite partout, branchee nulle part.
    """
    import json as _j
    import urllib.request as _u

    try:
        from nokido_agent.app.forge_secrets import get_secret as _gs
    except Exception:  # noqa: BLE001
        def _gs(k):
            return os.environ.get(k or "", "")
    acc = _gs("CLOUDFLARE_ACCOUNT_ID") or os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    key = _gs("CLOUDFLARE_AI_API_KEY")
    # UN PROVIDER MUET EST UN FAUX-VERT (mesure 2026-08-20) : rendre `None` sans
    # dire POURQUOI rend le diagnostic impossible — on ne sait pas distinguer
    # « pas configure » de « refuse par l'API » ni de « forme inattendue ».
    # Chaque sortie nomme donc sa cause. Jamais la valeur des secrets.
    if not (acc and key):
        logger.warning("[embed:cloudflare] non configure (account_id=%s, api_key=%s)",
                       bool(acc), bool(key))
        return None
    req = _u.Request(
        "https://api.cloudflare.com/client/v4/accounts/%s/ai/run/@cf/baai/bge-m3" % acc,
        data=_j.dumps({"text": texts}).encode("utf-8"),
        headers={"Authorization": "Bearer %s" % key, "Content-Type": "application/json"},
    )
    try:
        # SORTIE IPv4 : l'allowlist du token refuse l'IPv6 (code 9109). Voir
        # `_ConnexionIPv4` pour la mesure qui l'etablit.
        with _opener_ipv4().open(req, timeout=timeout) as r:
            d = _j.loads(r.read())
    except Exception as e:  # noqa: BLE001
        _corps = ""
        _lire = getattr(e, "read", None)
        if callable(_lire):
            try:
                _corps = _lire().decode("utf-8", "replace")[:220]
            except Exception:  # noqa: BLE001
                _corps = ""
        logger.warning("[embed:cloudflare] appel KO (%s) %s", type(e).__name__, _corps)
        return None
    if not d.get("success", True):
        logger.warning("[embed:cloudflare] API refuse : %s", str(d.get("errors"))[:200])
        return None
    res = d.get("result") or {}
    data = res.get("data") or res.get("response") or res.get("embeddings")
    # SHAPE VERIFIEE, pas supposee : un provider qui rend 200 avec une forme
    # inattendue ecrirait des vecteurs faux, silencieusement.
    if not data or len(data) != len(texts) or len(data[0]) != 1024:
        logger.warning("[embed:cloudflare] shape inattendue : type=%s n=%s dim=%s cles=%s",
                       type(data).__name__,
                       (len(data) if isinstance(data, list) else "?"),
                       (len(data[0]) if isinstance(data, list) and data
                        and isinstance(data[0], list) else "?"),
                       list(res)[:6])
        return None
    return data


OPENROUTER_URL = "https://openrouter.ai/api/v1/embeddings"


def _openrouter_call(texts: list[str], timeout: float = 30.0) -> list[list[float]] | None:
    """OpenRouter `baai/bge-m3` -- MEME espace vectoriel que le local et Cloudflare.

    PAYANT (~0,01 $ / M jetons au 2026-09-06, soit ~0,30 $ pour les ~122 000 chunks en
    attente a ~250 jetons piece). C'est pourquoi il figure dans `_PAYANTS` : il n'est
    JAMAIS tente par defaut -- il faut que `config/pillar_policy.json` le NOMME dans
    `backends.embed`. Une politique muette ne doit pas se traduire par une depense.
    Mesure 2026-09-06 (tools/forge_embed_cloud_probe.py) : HTTP 200, dim 1024.
    """
    # La cle vient du COFFRE, jamais de l'environnement (regle d'or
    # `laforge-cloud-secret-from-env`) : un secret cloud lisible dans l'env fuite par
    # toute cmdline, tout dump et tout sous-processus. Un coffre illisible est DIT et
    # distingue d'une cle absente -- confondre les deux a failli faire revoquer un
    # jeton valide le 2026-07-31.
    key = ""
    try:
        from nokido_agent.app.forge_secrets import get_secret

        key = get_secret("OPENROUTER_API_KEY") or ""
    except Exception as e:  # noqa: BLE001
        logger.warning("[embed:openrouter] coffre illisible (%s) -- provider ignore, "
                       "ce n'est PAS une absence de cle", type(e).__name__)
        return None
    if not key:
        logger.warning("[embed:openrouter] non configure (OPENROUTER_API_KEY absente du coffre)")
        return None
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps({"model": "baai/bge-m3", "input": [t[:8000] for t in texts]}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer %s" % key.strip()},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        corps = ""
        lire = getattr(e, "read", None)
        if callable(lire):
            try:
                corps = lire().decode("utf-8", "replace")[:220]
            except Exception:  # noqa: BLE001
                corps = ""
        logger.warning("[embed:openrouter] appel KO (%s) %s", type(e).__name__, corps)
        return None
    items = d.get("data") or []
    if len(items) != len(texts):
        logger.warning("[embed:openrouter] %d vecteur(s) pour %d texte(s) -- lot rejete",
                       len(items), len(texts))
        return None
    items.sort(key=lambda x: x.get("index", 0))
    vecs = [x.get("embedding") for x in items]
    if any((not v) or len(v) != 1024 for v in vecs):
        logger.warning("[embed:openrouter] dimension inattendue (attendu 1024) -- lot rejete")
        return None
    return vecs


def _embed_openrouter(text: str, timeout: float = 30.0) -> list[float] | None:
    out = _openrouter_call([text], timeout=timeout)
    return out[0] if out else None


def _embed_cloudflare(text: str, timeout: float = 20.0) -> list[float] | None:
    out = _cloudflare_call([text], timeout=timeout)
    return out[0] if out else None


PROVIDERS = [
    ("llama8099", _embed_llama8099),  # LOCAL :8099 BGE-M3 GGUF GPU — VIVANT, free, pas d'egress -> 1er
    ("cloudflare", _embed_cloudflare),  # Workers AI @cf/baai/bge-m3 = MEME espace vectoriel que le local
    ("brain_worker", _embed_brain_worker),  # LOCAL :5557 (ONNX, disabled 2026-06-03 -> down ; gardé si réactivé)
    # ⚠️ ESPACES VECTORIELS (a relire avant d'en promouvoir un) : seuls llama8099,
    # cloudflare, hf et modal servent bge-m3 (1024D, comparable a la base). jina rend
    # du `jina-embeddings-v3` et voyage du `voyage-3` : 1024 dimensions AUSSI, mais un
    # AUTRE espace -- les melanger dans `rag_chunks.embedding` rend les distances
    # incomparables et rien dans le schema ne signale le melange. La politique du corps
    # (`config/pillar_policy.json`) est ce qui les tient a l'ecart : ne pas s'appuyer
    # sur l'ordre de cette liste pour cela.
    ("jina", _embed_jina),  # AUTRE ESPACE (jina-embeddings-v3). Quotas a re-verifier :
    # le « 1M tok/mois » ci-dessous datait de 2026 debut ; les conditions publiques
    # actuelles parlent d'un credit initial, pas d'un renouvellement mensuel.
    ("hf", _embed_hf),  # bge-m3 via HF serverless. Le « 1k req/jour » du haut de ce
    # fichier est PERIME : le free tier HF est desormais un credit mensuel en dollars,
    # non convertible en requetes sans le prix CPU de la route -- donc repli, pas moteur.
    ("voyage", _embed_voyage),  # AUTRE ESPACE (voyage-3). Le « trial 200M tokens » ne
    # porte plus sur voyage-3 dans les conditions actuelles : ne pas le budgeter.
    ("modal", _embed_modal),  # self-hosted A10G bge-m3, seulement si LAFORGE_MODAL_EMBED_URL.
    # Cout GPU ~1,10 $/h par A10G : `min_containers` > 0 consomme les credits en continu
    # (cf. tools/deploy_modal_bge_m3.py, remis a 0 par defaut le 2026-09-06).
    ("openrouter", _embed_openrouter),  # bge-m3 1024D PAYANT -- voir _PAYANTS juste dessous
]

# BACKENDS PAYANTS : jamais tentes tant que la politique du corps ne les NOMME pas.
# Un backend gratuit qui echoue coute une latence ; un backend payant qui reussit coute
# de l'argent -- la difference doit etre portee par le code, pas par la vigilance de
# celui qui edite la politique. Regle : politique muette => les payants sont RETIRES
# des deux cascades (unitaire et par lot).
_PAYANTS = {"openrouter"}


def _sans_payants(essais: list) -> list:
    return [e for e in essais if e[0] not in _PAYANTS]


def _provider_has_creds(name: str) -> bool:
    """Skip les providers cloud NON configurés (pas de clé / URL) => pas de circuit
    breaker inutile + fallthrough rapide vers le local. brain_worker (local :5557)
    est toujours tenté (pas de credential ; timeout rapide si down). 2026-06-03 :
    fix corpus NULL (modal not_configured + voyage sans egress claquaient le breaker)."""
    if name in ("brain_worker", "llama8099"):
        return True
    if name == "modal":
        return bool(_modal_url())
    try:
        from nokido_agent.app.forge_secrets import get_secret
    except Exception:  # muet-ok secrets import fallback
        get_secret = lambda k: os.environ.get(k or "", "")  # noqa: E731
    if name == "hf":
        return bool(get_secret("HF_TOKEN"))
    if name == "jina":
        return bool(get_secret("JINA_API_KEY"))
    if name == "cloudflare":
        # Les DEUX sont requis : l'URL Workers AI porte l'account id.
        return bool((get_secret("CLOUDFLARE_ACCOUNT_ID")
                     or os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""))
                    and get_secret("CLOUDFLARE_AI_API_KEY"))
    if name == "voyage":
        # Le second terme repetait le PREMIER nom : le repli n'existait pas.
        return bool(get_secret("VOYAGE_API_KEY") or get_secret("VOYAGE_KEY"))
    return True


# --- Circuit breaker per-provider (anti-cascade hang sur GPU mutex serialise) ---

_CB_STATE: dict[str, dict] = {}  # provider -> {consecutive_failures, opened_until_ts}
_CB_THRESHOLD = 3
_CB_COOLDOWN_S = 60
_CB_TIMEOUT_PROVIDER = {
    # Timeout per call par provider (anti-hang sur Rust mutex serialise queue longue)
    "llama8099": 30.0,  # GGUF GPU local, 1er call / long text peut etre lent
    "cloudflare": 20.0,  # Workers AI, edge : rapide, mais egress -> pas illimite
    "brain_worker": 30.0,  # CPU/DirectML local, peut etre lent si queue
    "modal": 20.0,
    "voyage": 15.0,
    "jina": 15.0,
    "hf": 10.0,
}


def _cb_can_call(provider: str) -> bool:
    """Circuit breaker check : True si call autorise."""
    st = _CB_STATE.get(provider)
    if not st:
        return True
    if st.get("opened_until_ts", 0) > time.time():
        return False
    return True


def _cb_record(provider: str, ok: bool):
    """Update circuit breaker state apres call."""
    st = _CB_STATE.setdefault(provider, {"consecutive_failures": 0, "opened_until_ts": 0})
    if ok:
        st["consecutive_failures"] = 0
    else:
        st["consecutive_failures"] += 1
        if st["consecutive_failures"] >= _CB_THRESHOLD:
            st["opened_until_ts"] = time.time() + _CB_COOLDOWN_S
            logger.warning(
                f"circuit breaker OPEN {provider} for {_CB_COOLDOWN_S}s "
                f"({st['consecutive_failures']} consecutive failures)"
            )


def embed_batch(texts: list, timeout: float = 60.0, prefer: str | None = None) -> list:
    """Batch LOCAL-FIRST (lot #8 2026-07-07) : UN POST :8099 /v1/embeddings
    (input=list, meme contrat OpenAI que le single _embed_llama8099) ;
    fallback per-text via embed() (cascade gouvernee providers/breaker).
    Retourne une liste ALIGNEE sur texts ([] pour un texte en echec).

    `prefer` absorbe la signature de l'ancienne def sequentielle qui shadowait
    celle-ci (supprimee 2026-08-03) : elle rendait None en echec la ou celle-ci
    rend [], ce qui plantait forge_semantic_route._norm(). N'agit que sur le
    fallback per-text, le POST batch :8099 restant local-first par construction."""
    texts = [t if isinstance(t, str) else str(t or "") for t in texts]
    if not texts:
        return []
    if not _role_embed_local_autorise():
        # Ce POST est HORS cascade : sans cette porte, la politique du corps n'aurait
        # ferme que `PROVIDERS`. On rend la main au chemin batch gouverne (un lot par
        # appel), jamais a N appels unitaires qui couteraient N aller-retours.
        return [v if v else [] for v in embed_batch_fast(texts, batch_size=32)]
    try:
        import json as _j
        import urllib.request as _u

        body = _j.dumps({"input": texts}).encode()
        req = _u.Request(
            "http://127.0.0.1:8099/v1/embeddings", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with _u.urlopen(req, timeout=timeout) as r:
            data = _j.loads(r.read())["data"]
        vecs = [d["embedding"] for d in sorted(data, key=lambda x: x.get("index", 0))]
        if len(vecs) == len(texts):
            return vecs
    except Exception as e:
        logger.debug(f"embed_batch :8099 KO ({e}) -> fallback per-text")
    return [embed(t, prefer=prefer) or [] for t in texts]


def embed(text: str, prefer: str | None = None) -> list[float] | None:
    """Cascade embedding. Si prefer fournit, essaie ce provider d'abord."""
    if not text or len(text.strip()) < 3:
        return None

    # BudgetManager pour tracking
    try:
        from nokido_agent.app.forge_llm_budget import BudgetManager

        bm = BudgetManager.singleton()
    except Exception:  # muet-ok budget manager import fallback
        bm = None

    providers = list(PROVIDERS)
    # La politique du corps prime sur l'ordre code en dur : un backend ecarte ne doit
    # meme pas etre TENTE, puisqu'un essai local qui echoue RECLAME le pilier.
    try:
        from nokido_agent.app.forge_pillar_arbiter import backends_autorises

        _autorises = backends_autorises("embed")
        if not _autorises:
            providers = _sans_payants(providers)
        else:
            _filtres = [p for p in providers if p[0] in _autorises]
            if _filtres:
                providers = sorted(_filtres, key=lambda p: _autorises.index(p[0]))
            else:
                providers = _sans_payants(providers)
                logger.warning(
                    "[arbitre] aucun provider declare ne figure dans la politique "
                    "d'embedding (%s) -- cascade laissee INTACTE plutot que vide",
                    ", ".join(_autorises))
    except Exception as exc:  # noqa: BLE001 - arbitre indisponible : cascade intacte
        # Arbitre muet : on garde la cascade, MAIS sans les payants -- ne pas depenser
        # parce qu'on n'a pas pu lire la politique.
        providers = _sans_payants(providers)
        logger.debug("[arbitre] indisponible (%r) -- ordre PROVIDERS inchange, "
                     "backends payants retires", exc)
    if prefer:
        providers.sort(key=lambda x: (0 if x[0] == prefer else 1, x[0]))

    for name, fn in providers:
        # Skip provider cloud non-configuré (pas de clé/URL) -> évite breaker inutile.
        if not _provider_has_creds(name):
            logger.debug(f"{name} skipped: not configured (no credential)")
            continue
        # Circuit breaker check : skip si provider en cooldown
        if not _cb_can_call(name):
            logger.debug(f"{name} skipped: circuit breaker open")
            continue
        if bm:
            ok, _reason = bm.can_call(name, "embed", est_tokens=200)
            if not ok:
                continue
        t0 = time.time()
        timeout = _CB_TIMEOUT_PROVIDER.get(name, 20.0)
        # Wrap dans concurrent.futures timeout (anti-hang Rust mutex serialise)
        try:
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as _TO

            with ThreadPoolExecutor(max_workers=1) as exe:
                future = exe.submit(fn, text)
                try:
                    vec = future.result(timeout=timeout)
                except _TO:
                    logger.debug(f"{name} timeout after {timeout}s")
                    vec = None
                    _cb_record(name, ok=False)
                    continue
        except Exception as e:
            logger.debug(f"{name} exception: {e}")
            vec = None
        dt = time.time() - t0
        if vec and len(vec) >= 256:
            logger.debug(f"embed via {name} in {dt * 1000:.0f}ms (dim={len(vec)})")
            _cb_record(name, ok=True)
            if bm:
                bm.record_call(name, "embed", tokens_in=len(text) // 4, tokens_out=0, ok=True)
            return vec
        _cb_record(name, ok=False)
        if bm:
            bm.record_call(name, "embed", tokens_in=len(text) // 4, tokens_out=0, ok=False)
    return None


def _politique_embed() -> list[str] | None:
    """Backends d'embedding autorises par la politique des piliers, dans SON ordre.
    None = politique muette ou arbitre indisponible : rien n'est refuse (une politique
    muette ne coupe jamais en silence, cf. config/pillar_policy.json)."""
    try:
        from nokido_agent.app.forge_pillar_arbiter import backends_autorises

        return backends_autorises("embed") or None
    except Exception as exc:  # noqa: BLE001 - arbitre indisponible : cascade intacte
        logger.debug("[arbitre] indisponible (%r) -- cascade batch inchangee", exc)
        return None


# Cascade BATCH, un essai par backend (nom = celui de la politique et de PROVIDERS).
# Mesure 2026-09-06 : cette cascade ne lisait PAS la politique que `embed()` respecte
# depuis le 2026-09-01 (incident de pollution Voyage) : le drain (forge_embed_auto_trigger)
# tentait Voyage puis Jina - d'AUTRES espaces vectoriels - des que :8099 et Modal se
# taisaient, et n'essayait JAMAIS Cloudflare en lot (seulement texte par texte via
# embed(), soit 32x plus de requetes pour le meme quota). Un backend ecarte ne doit meme
# pas etre TENTE ; un backend autorise doit l'etre en LOT.
def _essais_batch(batch_texts: list[str]) -> list[tuple[str, "callable"]]:
    def _voyage_lots() -> list[list[float]] | None:
        if len(batch_texts) <= 128:
            return _voyage_call(batch_texts, timeout=30.0)
        out: list[list[float]] = []
        for i in range(0, len(batch_texts), 128):
            sub = batch_texts[i : i + 128]
            sv = _voyage_call(sub, timeout=30.0)
            if not sv or len(sv) != len(sub):
                return None
            out.extend(sv)
        return out

    return [
        ("llama8099", lambda: _llama8099_call(batch_texts, timeout=60.0)),
        ("modal", lambda: _modal_call(batch_texts, timeout=30.0)),
        ("cloudflare", lambda: _cloudflare_call(batch_texts, timeout=30.0)),
        ("voyage", _voyage_lots),
        ("jina", lambda: _jina_call(batch_texts, timeout=30.0)),
        ("brain_worker", lambda: _brain_worker_call(batch_texts, timeout=120.0)),
        ("openrouter", lambda: _openrouter_call(batch_texts, timeout=30.0)),  # PAYANT
    ]


def _essais_selon_politique(essais: list[tuple[str, "callable"]], autorises: list[str] | None) -> list[tuple[str, "callable"]]:
    """Filtre + ordonne les essais batch selon la politique (meme regle que embed())."""
    if not autorises:
        return _sans_payants(essais)
    filtres = [e for e in essais if e[0] in autorises]
    if not filtres:
        logger.warning(
            "[arbitre] aucun essai batch ne figure dans la politique d'embedding (%s) "
            "-- cascade batch laissee INTACTE plutot que vide, mais SANS les backends "
            "payants (une politique illisible ne doit pas se traduire par une depense)",
            ", ".join(autorises))
        return _sans_payants(essais)
    return sorted(filtres, key=lambda e: autorises.index(e[0]))


def embed_batch_fast(texts: list[str], batch_size: int = 32, max_workers: int = 4) -> list[list[float] | None]:
    """Throughput optimal :
       1. Group texts en batches de batch_size
       2. Pour chaque batch, essai cascade BATCH API (1 call N textes)
          - Jina batch (jusqu a 2048 inputs) = 5ms/text effective
          - brain_worker ZMQ batch (20 textes/submit) = 25ms/text
       3. Multiple batches en parallel via ThreadPoolExecutor (HTTP threads OK)
       4. Si batch API fail -> degradation gracieuse single embed cascade

    Args:
        texts: liste textes a vectoriser
        batch_size: taille batch par appel API (32 = sweet spot Jina free tier)
        max_workers: threads paralleles (4 = safe pour rate limit cloud)

    Returns:
        liste [vec ou None] meme taille que texts.
    """
    if not texts:
        return []

    # Split en batches
    batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]
    results: dict[int, list[float] | None] = {}

    _autorises = _politique_embed()

    def _process_batch(batch_idx: int, batch_texts: list[str]) -> tuple[int, list[list[float] | None]]:
        # Ordre par defaut (politique muette) : :8099 local (souverain, GPU) > Modal A10G
        # > Cloudflare Workers AI (meme bge-m3) > Voyage > Jina > brain_worker ZMQ.
        # Sous politique : seuls les backends nommes, dans l'ordre de la politique.
        for name, fn in _essais_selon_politique(_essais_batch(batch_texts), _autorises):
            try:
                vecs = fn()
                if vecs and len(vecs) == len(batch_texts):
                    return batch_idx, vecs
            except Exception as e:  # noqa: BLE001
                logger.debug(f"{name} batch KO: {e}")

        # Degradation : single embed cascade (elle-meme sous politique) texte par texte
        return batch_idx, [embed(t) for t in batch_texts]

    # Parallelize batches via ThreadPool (HTTP I/O OK avec threads)
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=max_workers) as exe:
            futures = {exe.submit(_process_batch, i, b): i for i, b in enumerate(batches)}
            batch_results: dict[int, list[list[float] | None]] = {}
            for fut in as_completed(futures):
                idx, vecs = fut.result()
                batch_results[idx] = vecs
        # Flatten in original order
        out = []
        for i in range(len(batches)):
            out.extend(batch_results.get(i, [None] * len(batches[i])))
        return out
    except Exception as e:
        logger.warning(f"parallel batch failed, fallback sequential: {e}")
        return [embed(t) for t in texts]


def health_providers() -> dict:
    """Status check de chaque provider sans appel coûteux."""
    out = {}
    # brain_worker port :5557
    import socket as _sk

    try:
        s = _sk.socket(_sk.AF_INET, _sk.SOCK_STREAM)
        s.settimeout(0.5)
        r = s.connect_ex(("127.0.0.1", 5557))
        s.close()
        out["brain_worker"] = "up" if r == 0 else "down"
    except Exception:  # muet-ok brain worker socket check
        out["brain_worker"] = "unknown"

    # HF / Jina / Modal : check key/env present
    try:
        from nokido_agent.app.forge_secrets import get_secret
    except Exception:  # muet-ok secrets import fallback
        get_secret = lambda k: None
    out["hf"] = "configured" if get_secret("HF_TOKEN") else "no_key"
    out["jina"] = "configured" if get_secret("JINA_API_KEY") else "no_key"
    out["voyage"] = "configured" if (get_secret("VOYAGE_API_KEY") or get_secret("VOYAGE_API_KEY")) else "no_key"
    # `_modal_url()` porte deja la chaine coffre -> WCM -> Nokido.env -> environnement.
    # Lire `os.environ` SEUL ici reproduisait, dans le rapport de sante, le defaut
    # que `_modal_url` avait justement corrige le 2026-08-19 : l'endpoint vit au
    # coffre DPAPI, donc `health_providers()` annoncait `not_configured` sur une app
    # Modal parfaitement vivante. Un rapport de sante qui ment sur un
    # provider disponible coute un repli cloud inutile — mesure 2026-09-01, ou il fallait
    # justement choisir un provider 1024D sans bruler de quota gratuit.
    out["modal"] = "configured" if _modal_url() else "not_configured"
    return out


# --- Encode embedding to BLOB (compat rag_chunks) ---


def encode_blob(vec: list[float]) -> bytes:
    """Encode 1024D float vector en blob float32 binaire (compat rag_chunks)."""
    if not vec:
        return b""
    return struct.pack(f"{len(vec)}f", *vec)


def decode_blob(blob: bytes) -> list[float] | None:
    if not blob:
        return None
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


# --- CLI test ---


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", default="Nokido sovereign AI hub with RAG retrieval", help="Text to embed")
    ap.add_argument("--prefer", choices=["modal", "hf", "jina", "brain_worker"], default=None)
    ap.add_argument("--health", action="store_true")
    ap.add_argument("--bench", action="store_true", help="Bench tous les providers avec timings")
    args = ap.parse_args()

    if args.health:
        print(json.dumps(health_providers(), indent=2))
        return

    if args.bench:
        results = {}
        for name, fn in PROVIDERS:
            t0 = time.time()
            try:
                vec = fn(args.text)
            except Exception as e:
                vec = None
                logger.debug(f"{name} bench KO: {e}")
            dt = time.time() - t0
            results[name] = {
                "elapsed_ms": round(dt * 1000, 1),
                "vec_dim": len(vec) if vec else 0,
                "ok": bool(vec),
            }
        print(json.dumps(results, indent=2))
        return

    t0 = time.time()
    vec = embed(args.text, prefer=args.prefer)
    dt = time.time() - t0
    if vec:
        print(f"OK dim={len(vec)} elapsed={dt * 1000:.0f}ms")
        print(f"first_5={vec[:5]}")
    else:
        print("FAIL aucun provider n'a repondu")


if __name__ == "__main__":
    main()
