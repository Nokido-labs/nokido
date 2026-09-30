"""
tools/forge_reindex_deport.py — Reindex CODE déporté, embedding via PROVIDER cloud.
=====================================================================================

But (demande user 2026-06-05) : combler les ~797 modules à 0 chunk SANS saturer le
780M. Donc :
  Phase A (chunk) : forge_rag_index_app.index_app_dir(changed_only=False) sur app/+tools/
                    -> crée les chunks NULL (CPU léger, pas de GPU).
  Phase B (embed) : forge_rebuild_embeddings, MAIS provider `local` (brain_worker 780M)
                    RETIRÉ -> cloud bge-m3 only (HF/DeepInfra/Cloudflare/Nvidia, tous
                    BAAI/bge-m3 = compat espace vectoriel). Resource-gate intégré.

RÉUTILISE (rule 2) : index_app_dir + forge_rebuild_embeddings. Aucune logique d'embed
réécrite. Filtre juste PROVIDERS (monkeypatch, pas d'édition du tool partagé).

⚠️ COMPAT : l'index RAG = BAAI/bge-m3 CLS-pooled. forge_rebuild_embeddings n'a que des
providers bge-m3 -> sûr. (Jina/Voyage = autre espace, ABSENTS de ce tool -> OK.)

Modes (argv) :
  --probe       : clés cloud présentes ? providers enabled ? test live 1 embed (dim=1024 ?).
                  N'écrit RIEN. À lancer en trusted (host+vault) avant de fire.
  --index-only  : Phase A seule.
  --embed-only  : Phase B seule (cloud).
  (défaut)      : Phase A puis Phase B.

Log -> C:/tmp/reindex_deport.log. Idempotent (index changed_only=False ré-upsert ;
rebuild = checkpoint resume).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# RACINE aussi (2026-09-24, mesure) : `nokido_agent` est un dossier de la RACINE ; sans elle,
# NokidoDeportEmbed mourait en ModuleNotFoundError a chaque demarrage (514 fois au journal).
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
for _sub in ("app", "tools"):
    _p = str(ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

LOG = Path("C:/tmp/reindex_deport.log")
LOG.parent.mkdir(parents=True, exist_ok=True)

_CLOUD_KEYS = {
    "HF": ["HF_TOKEN"],
    "DeepInfra": ["DEEPINFRA"],
    "Nvidia": ["NVIDIA_NIM_API_KEY", "NVIDIA_API_KEY"],
    "Cloudflare": ["CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_AI_API_KEY"],
}


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] {msg}"
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    sys.stdout.buffer.write((line + "\n").encode("ascii", "replace"))


def _key_presence() -> dict:
    out = {}
    for prov, keys in _CLOUD_KEYS.items():
        out[prov] = all(bool(os.environ.get(k, "").strip()) for k in keys)
    return out


def _load_vault() -> list:
    """Injecte les secrets vault -> os.environ (le hub le fait au boot ; un job
    déporté doit le faire lui-même). Retourne les NOMS de secrets dispo (pas les
    valeurs) pour diagnostiquer un mismatch de nom de clé."""
    names: list = []
    # 1) Coffre MACHINE d'abord (DPAPI portee machine) : c'est le seul lisible par
    #    un compte de SERVICE, et c'est sa raison d'etre. `forge_env_crypt` chiffre
    #    par COMPTE (owner) : sous LaForgeTrusted il rend « DPAPI
    #    CryptUnprotectData echoue » sur CHAQUE secret, et le job partait sans
    #    aucune cle cloud alors que le coffre machine les portait toutes
    #    (mesure 2026-07-31 : CLOUDFLARE_AI_API_KEY, NVIDIA_NIM_API_KEY et
    #    CEREBRAS_API_KEY y sont, le job n'y voyait que HF_TOKEN via env_crypt).
    try:
        from nokido_agent.app.forge_machine_vault import vault_get, vault_list
        from nokido_agent.app.forge_secrets import NOMS_RESERVES

        for cle in vault_list():
            # 2b-6 (2026-09-28) : jamais un nom reserve dans l'environnement du job --
            # il y passait a chaque enfant (maitre, admin, signature JWT). Ce job ne
            # veut que des cles de fournisseurs.
            if cle in NOMS_RESERVES:
                continue
            try:
                valeur = vault_get(cle)
            except Exception:  # noqa: BLE001
                continue  # secret illisible : on le saute, sans jamais le journaliser
            if valeur and not os.environ.get(cle):
                os.environ[cle] = valeur
                names.append(cle)
        log(f"  coffre machine : {len(names)} secret(s) injecte(s)")
    except Exception as exc:  # noqa: BLE001
        log(f"coffre machine indisponible: {exc!r}")

    # 2) Coffre par compte, en complement (utile quand le job tourne cote owner).
    try:
        from nokido_agent.app.forge_env_crypt import inject_into_environ, load_secrets

        inject_into_environ()
        try:
            names = sorted(set(names) | set(load_secrets().keys()))
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        log(f"vault par compte indisponible: {exc!r}")
    return names


def _apply_vault_keys_to_fre(fre) -> list:
    """forge_rebuild_embeddings lit ses clés depuis Nokido.env (PLAINTEXT), pas le
    vault ni os.environ. On override les globals du module depuis os.environ (injecté
    du vault chiffré -> le secret reste hors plaintext) et on reconstruit PROVIDERS.
    Tous bge-m3.

    LOCAL (decision owner 2026-08-03) : le cloud garde la priorite, mais quand ses
    quatre fournisseurs sont a sec le corpus ne doit plus rester en plan. Le provider
    `local` HISTORIQUE de forge_rebuild_embeddings est inutilisable : il parle ZMQ a
    brain_worker :5557, DISABLED depuis le 2026-06-03 (OOM ONNX) -- le rebrancher tel
    quel n'aurait rendu qu'un timeout de 20 s par lot. L'embedder VIVANT est :8099
    (BGE-M3 GGUF, HTTP), deja expose par `forge_embed_router._llama8099_call` : on le
    CABLE plutot que de le reecrire. Son rythme est borne par le garde de ressources
    et par une pause entre lots, cf. `phase_b_embed`."""
    fre.HF_TOKEN = os.environ.get("HF_TOKEN", "") or getattr(fre, "HF_TOKEN", "")
    fre.DEEPINFRA = os.environ.get("DEEPINFRA", "") or getattr(fre, "DEEPINFRA", "")
    fre.NVIDIA = (os.environ.get("NVIDIA_NIM_API_KEY", "")
                  or os.environ.get("NVIDIA_API_KEY", "") or getattr(fre, "NVIDIA", ""))
    fre.CF_ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "") or getattr(fre, "CF_ACCOUNT", "")
    fre.CF_KEY = os.environ.get("CLOUDFLARE_AI_API_KEY", "") or getattr(fre, "CF_KEY", "")
    fre.PROVIDERS = [
        {"name": "HF", "fn": fre.hf_embed, "enabled": bool(fre.HF_TOKEN)},
        {"name": "DeepInfra", "fn": fre.deepinfra_embed, "enabled": bool(fre.DEEPINFRA)},
        {"name": "Cloudflare", "fn": fre.cloudflare_embed,
         "enabled": bool(fre.CF_ACCOUNT and fre.CF_KEY)},
        {"name": "Nvidia", "fn": fre.nvidia_embed, "enabled": bool(fre.NVIDIA)},
    ]
    try:
        _app = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
        if _app not in sys.path:
            sys.path.insert(0, _app)
        from nokido_agent.app.forge_embed_router import _llama8099_call as _appel_local

        def _embed_local_8099(textes: list) -> list:
            """:8099 en HTTP. LEVE si la forme est inattendue : l'election ecarte un
            provider qui echoue, elle ne saurait pas quoi faire d'un None silencieux."""
            vecs = _appel_local(textes, timeout=120.0)
            if not vecs or len(vecs) != len(textes):
                # Message ENRICHI : « shape inattendue » etait rendu pour trois causes
                # distinctes (reponse mal formee, vecteur trop court, exception), ce
                # qui a laisse ce repli casse deux jours sans diagnostic possible. La
                # cause detaillee est desormais journalisee par _llama8099_call en
                # WARNING ; on rappelle ici ou la chercher.
                raise RuntimeError(
                    "local :8099 sans reponse exploitable (%s vecteur(s) pour %d texte(s)) "
                    "— cause detaillee dans le journal, prefixe [llama8099]"
                    % (len(vecs) if vecs else "aucun", len(textes)))
            return vecs

        fre.PROVIDERS.append({"name": "local", "fn": _embed_local_8099, "enabled": True})
    except Exception as exc:  # noqa: BLE001
        log("  local :8099 non cable (%s) -> providers cloud seulement" % type(exc).__name__)
    return [p["name"] for p in fre.PROVIDERS if p["enabled"]]


def probe() -> None:
    log(f"=== PROBE === user={os.environ.get('USERNAME','?')} py={sys.executable}")
    names = _load_vault()
    embed_names = [n for n in names if any(
        t in n.upper() for t in ("HF", "HUGG", "DEEPINFRA", "NVIDIA", "CLOUDFLARE", "CF_", "JINA", "VOYAGE", "EMBED")
    )]
    log(f"  vault secrets count={len(names)} embed-related={embed_names}")
    pres = _key_presence()
    for prov, ok in pres.items():
        log(f"  key {prov:11s} present={ok}")
    try:
        from nokido_agent.tools import forge_rebuild_embeddings as fre
    except Exception as exc:  # noqa: BLE001
        log(f"import forge_rebuild_embeddings FAILED: {exc!r}")
        return
    actifs = _apply_vault_keys_to_fre(fre)
    log(f"  PROVIDERS cloud enabled (vault) = {actifs}")
    _t = os.environ.get("HF_TOKEN", "")
    log(f"  HF token sanity: len={len(_t)} starts_hf={_t.startswith('hf_')} "
        f"has_space={' ' in _t} has_quote={chr(34) in _t or chr(39) in _t} "
        f"has_nl={chr(10) in _t or chr(13) in _t}")
    cloud = [p for p in fre.PROVIDERS if p["enabled"]]
    if not cloud:
        log("  AUCUN provider cloud enabled -> clé absente/non déchiffrée. "
            "Plan bloqué tant qu'une clé bge-m3 n'est pas dispo.")
        return
    p = cloud[0]
    try:
        vecs = p["fn"](["bonjour, ceci est un test d'embedding bge-m3"])
        v = list(vecs[0])
        log(f"  test {p['name']} -> dim={len(v)} (attendu 1024) head={[round(x,4) for x in v[:3]]} "
            f"-> {'OK bge-m3 compat' if len(v) == 1024 else 'DIM INATTENDUE'}")
    except Exception as exc:  # noqa: BLE001
        log(f"  test embed {p['name']} FAILED: {exc!r}")


def whereis() -> None:
    """Longueur du HF_TOKEN par SOURCE (sans valeur) pour localiser le vrai token /
    détecter une troncature au stockage."""
    log("=== WHEREIS HF_TOKEN (len par source, no value) ===")
    import importlib
    try:
        ec = importlib.import_module("forge_env_crypt")
    except Exception as exc:  # noqa: BLE001
        log(f"  import env_crypt FAILED: {exc!r}")
        return
    try:
        kv = ec._keyring_get("HF_TOKEN")
        log(f"  keyring       HF_TOKEN len={len(kv) if kv else 0}")
    except Exception as exc:  # noqa: BLE001
        log(f"  keyring get FAILED: {exc!r}")
    try:
        secs = ec.load_secrets()
        log(f"  load_secrets  HF_TOKEN len={len(secs.get('HF_TOKEN',''))} keys={sorted(secs)}")
    except Exception as exc:  # noqa: BLE001
        log(f"  load_secrets FAILED: {exc!r}")
    try:
        backend, d = ec._read_secrets_file()
        log(f"  secrets file  backend={backend} HF_in_file={'HF_TOKEN' in d} keys={sorted(d)}")
    except Exception as exc:  # noqa: BLE001
        log(f"  _read_secrets_file FAILED: {exc!r}")
    log(f"  _KEYRING_VARS = {getattr(ec, '_KEYRING_VARS', '?')}")


def phase_a_index() -> None:
    log("=== PHASE A : index_app_dir(changed_only=False) app/+tools/ ===")
    try:
        from nokido_agent.app.forge_rag_index_app import index_app_dir
    except Exception as exc:  # noqa: BLE001
        log(f"import index_app_dir FAILED: {exc!r}")
        return
    targets = [None, ROOT / "tools"]  # None => app/ (défaut du tool)
    for tgt in targets:
        label = "app" if tgt is None else tgt.name
        try:
            kw = {"changed_only": False, "verbose": False}
            if tgt is not None:
                kw["target_dir"] = tgt
            st = index_app_dir(**kw)
            log(f"  index {label}: files={st.get('files_indexed')} "
                f"chunks={st.get('chunks_added')} dur={st.get('duration_s')}s")
        except Exception as exc:  # noqa: BLE001
            log(f"  index {label} FAILED: {exc!r}")


def phase_b_embed(limit: int = 0) -> None:
    """Embed les chunks HOT **NULL uniquement** via provider cloud bge-m3.
    Réutilise fre.hf_embed + resource gate, MAIS query NULL-only (pas le cursor de
    fre.main() qui ré-embed les 26k déjà faits + se fait piéger par un CKPT périmé)."""
    import json
    import sqlite3
    import time as _time

    log("=== PHASE B : embed HOT NULL-only via cloud bge-m3 ===")
    try:
        from nokido_agent.tools import forge_rebuild_embeddings as fre
        from nokido_agent.tools.forge_tier_policy import HOT_TIER_SQL
    except Exception as exc:  # noqa: BLE001
        log(f"import FAILED: {exc!r}")
        return
    actifs = _apply_vault_keys_to_fre(fre)
    if not actifs:
        log("  ABORT : aucun provider CLOUD enabled (clé absente).")
        return
    # Le premier provider DECLARE n'est pas forcement VIVANT : mesure 2026-07-31,
    # HF etait enabled (token present au vault) mais rendait 401, et comme il est
    # premier dans PROVIDERS le job partait dessus puis abandonnait sur le 401 --
    # sans jamais essayer Cloudflare, pourtant valide. On elit celui qui REPOND.
    # Ordre de PREFERENCE, etabli par mesure (2026-07-31) et non par l'ordre de
    # declaration : Cloudflare a traite 300 chunks en 7 s la ou HF PEND sur un
    # batch (cold start de l'Inference API : le ping passe, la charge reelle non).
    B = 20  # taille de lot, definie AVANT l'election : le test l'utilise
    _PREF = {"Cloudflare": 0, "Nvidia": 1, "DeepInfra": 2, "HF": 3, "local": 9}
    # LOCAL EN DERNIER RECOURS (decision owner 2026-08-03). Il etait exclu de
    # l'election, si bien qu'une fois les quatre providers cloud a sec le job
    # ABANDONNAIT alors qu'un embedder :8099 vivant tournait sur la machine.
    # `_PREF` le classe deja bon dernier : le cloud garde la priorite tant qu'il
    # a du quota, et le local prend le relais au lieu de laisser le corpus en plan.
    candidats = sorted([p for p in fre.PROVIDERS if p["enabled"]],
                       key=lambda p: _PREF.get(p["name"], 5))

    # Test REPRESENTATIF : un batch de 20, la taille reelle des lots. Un ping d'un
    # seul texte elisait un provider qui se bloquait ensuite indefiniment.
    prov = None
    for cand in candidats:
        t_essai = __import__("time").monotonic()
        try:
            cand["fn"](["ping"] * B)
            duree = __import__("time").monotonic() - t_essai
            if duree > 25:
                log(f"  provider {cand['name']} ecarte : trop lent ({duree:.1f}s pour {B} textes)")
                continue
            prov = cand
            log(f"  provider retenu = {cand['name']} ({duree:.1f}s pour {B} textes)")
            break
        except Exception as exc:  # noqa: BLE001
            log(f"  provider {cand['name']} ecarte : {type(exc).__name__}: {str(exc)[:90]}")
    if prov is None:
        log("  ABORT : aucun provider ne repond assez vite.")
        return
    # RYTHME du repli local : il partage la RAM et l'iGPU avec tout le reste de la
    # machine, la ou un provider cloud ne coute que du reseau. Le garde existant
    # (`_resource_gate_wait`) est CALIBRE ici plutot que laisse a son defaut de 70 %,
    # inutilisable sur ce poste : la baseline mesuree y est de 65 a 77 %, donc le
    # garde bloquerait en PERMANENCE puis abandonnerait au bout de deux heures --
    # un frein toujours serre ne freine pas, il immobilise.
    _throttle = 0.0
    _max_chars = 0
    _budget_chars = 0
    if prov["name"] == "local":
        import os as _os

        fre.MAX_RAM_PCT = float(_os.environ.get("LAFORGE_EMBEDREBUILD_MAX_RAM_PCT", "85"))
        fre.MAX_CPU_PCT = float(_os.environ.get("LAFORGE_EMBEDREBUILD_MAX_CPU_PCT", "85"))
        fre.GATE_SLEEP_S = float(_os.environ.get("LAFORGE_EMBEDREBUILD_GATE_SLEEP_S", "20"))
        _throttle = float(_os.environ.get("LAFORGE_EMBED_LOCAL_THROTTLE_S", "0.4"))
        # BORNE DE CONTEXTE, MESUREE (2026-08-03) : au-dela d'environ 5 200 caracteres
        # de texte REEL, :8099 rend HTTP 500 et le lot entier est perdu. Un test
        # synthetique ne le voit pas -- "a" repete 6 000 fois passe tres bien, parce
        # qu'une repetition se tokenise en presque rien. 19,7 % du reste a traiter
        # (65 788 chunks) depasse cette borne. On TRONQUE pour le vecteur, le texte
        # complet restant en base pour le lexical, et on COMPTE ce qui a ete tronque :
        # une troncature silencieuse ferait croire le corpus vectorise en entier.
        _max_chars = int(_os.environ.get("LAFORGE_EMBED_LOCAL_MAX_CHARS", "4500"))
        _budget_chars = int(_os.environ.get("LAFORGE_EMBED_LOCAL_BUDGET_CHARS", "4500"))
        log(f"  LOCAL retenu : garde RAM<{fre.MAX_RAM_PCT}% CPU<{fre.MAX_CPU_PCT}%, "
            f"pause {_throttle}s entre lots, troncature a {_max_chars} chars. "
            f"PAUSE a chaud : creer sandbox/embed_rebuild_pause")
    conn = sqlite3.connect(str(fre.DB), timeout=30)
    conn.execute("PRAGMA busy_timeout=15000")
    _WHERE = (f"WHERE {HOT_TIER_SQL} "
              f"AND (embedding IS NULL OR length(embedding)=0)")
    dispo = conn.execute(f"SELECT COUNT(*) FROM rag_chunks {_WHERE}").fetchone()[0]
    # PAGINATION OBLIGATOIRE. La version precedente faisait un .fetchall() sur le
    # predicat entier, ce qui ramene id + TEXTE de ~348 000 chunks en memoire, et
    # n'appliquait la borne qu'APRES : meme un lot de 20 payait le chargement
    # complet. Mesure 2026-08-03 : lance en detache sans --max, le job a ete tue
    # par son cap de 1200 Mo apres 540 chunks, sans laisser de .err.
    # On lit desormais par pages ; le curseur avance de lui-meme puisque chaque
    # chunk vectorise sort du predicat NULL.
    PAGE = 2000
    # Borne de QUOTA : les free tiers sont journaliers (Cloudflare Workers AI
    # ~10k neurons/jour). Sans borne, un lot de 400k appels deborde le gratuit
    # et bascule en facturation. Le job etant idempotent (embedding IS NULL),
    # on reprend le lendemain la ou on s'est arrete.
    total = min(limit, dispo) if limit else dispo
    if limit and limit < dispo:
        log(f"  borne --max : {limit} traites sur {dispo} disponibles (reprise au prochain run)")
    log(f"  HOT NULL chunks à embed = {total} (disponibles: {dispo}, pages de {PAGE})")
    done = 0
    t0 = None
    try:
        t0 = __import__("time").monotonic()
    except Exception:  # noqa: BLE001
        pass
    while done < total:
        page = conn.execute(
            f"SELECT id, text FROM rag_chunks {_WHERE} LIMIT ?",
            (min(PAGE, total - done),),
        ).fetchall()
        if not page:
            # Plus rien sous le predicat : soit c'est fini, soit un autre
            # embedder est passe devant. Dans les deux cas on sort SANS boucler.
            log(f"  page vide a {done}/{total} -> plus rien a traiter, arret")
            break
        _fait_page = _embed_page(conn, page, B, prov, log_progress=(total, t0, done),
                                 throttle=_throttle,
                                 gate=(fre._resource_gate_wait
                                       if prov["name"] == "local" else None),
                                 max_chars=_max_chars, budget_chars=_budget_chars)
        done += _fait_page
        if _fait_page < 0:
            conn.close()
            return
    conn.close()
    log(f"=== PHASE B terminée : {done}/{total} embeddés ===")


def _embed_page(conn, page: list, B: int, prov: dict, log_progress: tuple,
                throttle: float = 0.0, gate=None, max_chars: int = 0,
                budget_chars: int = 0) -> int:
    """Vectorise UNE page deja en memoire, par lots de B. Rend le nombre traite,
    ou -1 pour demander un arret propre (quota epuise / provider HS)."""
    import json
    import time as _time

    total, t0, deja = log_progress
    done = 0
    # Lots bornes en TOKENS, pas en nombre d'entrees. Mesure 2026-08-03, corps
    # du 400 enfin lisible : "Max context reached 61320 tokens but model supports
    # only 60000" -- la limite Workers AI porte sur la SOMME des entrees d'une
    # requete. Un B fixe casse donc des que les chunks sont denses, ce qui
    # explique un 400 survenu apres 2600 chunks et non au premier lot, et
    # pourquoi des essais a 20/40/60 passaient : ils tombaient sur du texte court.
    # Le budget est exprime en CARACTERES, pas en tokens estimes : une premiere
    # version supposait 3 caracteres par token et n'a rien coupe du tout. Ratio
    # MESURE sur le lot exact qui echouait (2026-08-03) : 40 701 caracteres ont
    # produit 61 320 tokens, soit 0,66 caractere par token -- le tokenizer de
    # Workers AI compte bien plus fin qu'un BPE classique. 25 000 caracteres
    # valent donc ~37 900 tokens, sous les 60 000 du modele, avec de la marge
    # pour un corpus plus dense encore.
    # Budget par REQUETE. 25 000 pour le cloud ; le local est bien plus etroit et sa
    # borne est AGREGEE, pas par texte : mesure du 2026-08-03 sur des chunks REELS,
    # 1 x 4500 caracteres passe, 2 x 4500 rend HTTP 500. Un test avec du texte
    # repetitif ne le voit pas (22 500 caracteres y passaient sans broncher) — la
    # borne est en TOKENS, et une repetition n'en coute presque aucun.
    MAX_CHARS = budget_chars or 25_000
    lots: list = []
    cur: list = []
    cur_tok = 0
    for row in page:
        est = len(row[1] or "")
        if cur and (len(cur) >= B or cur_tok + est > MAX_CHARS):
            lots.append(cur)
            cur = []
            cur_tok = 0
        cur.append(row)
        cur_tok += est
    if cur:
        lots.append(cur)
    tronques = 0
    for batch in lots:
        texts = [r[1] or "" for r in batch]
        if max_chars:
            _long = [i for i, t in enumerate(texts) if len(t) > max_chars]
            if _long:
                tronques += len(_long)
                texts = [t[:max_chars] for t in texts]
        echecs = 0
        while True:
            try:
                # Le garde de ressources protege l'embedding LOCAL (iGPU 780M qui
                # sature la RAM). Sur un provider CLOUD, la RAM locale n'est pas
                # sollicitee : l'appliquer bloque le job pour rien. Mesure
                # 2026-07-31 : RAM a 80,4 % pour un seuil a 70 %, le job dormait
                # 30 s en boucle sans traiter un seul chunk, alors que les appels
                # partaient vers Cloudflare/HF.
                # Le garde arrive en PARAMETRE, il n'est plus cherche dans le module.
                # Regression mesuree 2026-08-03 : en extrayant cette boucle de
                # `phase_b_embed`, la reference `fre` est restee sans que le module
                # soit importe ici -> `NameError` a chaque lot. Une dependance qu'on
                # deplace se PASSE, elle ne se retrouve pas par hasard.
                if gate is not None:
                    gate()
                vecs = prov["fn"](texts)
                for (cid, _), v in zip(batch, vecs):
                    conn.execute("UPDATE rag_chunks SET embedding=? WHERE id=?",
                                 (json.dumps(list(v)), cid))
                conn.commit()
                done += len(batch)
                if throttle:
                    # Laisser respirer la machine ENTRE les lots. Le garde de
                    # ressources arrete quand c'est deja sature ; cette pause-ci
                    # evite d'y arriver.
                    _time.sleep(throttle)
                if (deja + done) % 200 < B:
                    _n = deja + done
                    rate = (_n / (__import__("time").monotonic() - t0)) if t0 else 0
                    log(f"  embed {_n}/{total} ({100*_n//max(total,1)}%) ~{rate:.1f}/s")
                break
            except Exception as exc:  # noqa: BLE001
                # 400 caracteres, pas 90 : _post rend desormais le CORPS de la
                # reponse HTTP, et 90 s'arrete pile apres l'URL du compte, donc
                # juste avant l'explication. Mesure 2026-08-03 : un 400 survenu
                # apres 2600 chunks est reste illisible pour cette seule raison.
                m = str(exc)[:400]
                # 429 = quota epuise : c'est un arret PROPRE, pas une erreur a
                # reessayer. Sans ce cas, la branche generique dort 60 s puis
                # retente indefiniment sur un quota qui ne reviendra qu'a minuit.
                if "429" in m or "Too Many Requests" in m or "quota" in m.lower():
                    log(f"  QUOTA epuise ({m}) -> arret propre a {deja + done}/{total} ; "
                        "relancer apres le reset du free tier.")
                    return -1
                if any(c in m for c in ("400", "401", "402", "403")):
                    # 400 = requete MALFORMEE : elle ne se reparera pas toute seule.
                    # La traiter comme transitoire faisait dormir 60 s puis retenter
                    # a l'infini -- et la tache planifiee horaire empilait alors des
                    # process qui bouclaient toute la nuit (mesure 2026-07-31 :
                    # Cloudflare elu en 0,5 s, puis 400 sur le premier vrai batch).
                    log(f"  provider HS ({m}) -> ABORT à {deja + done}/{total}")
                    return -1
                # DEFAUT DE CODE : ne se repare pas en attendant. La branche
                # generique dormait 60 s et retentait a l'infini -- mesure du jour :
                # un `NameError` a fait boucler le job sans fin, exactement comme le
                # 400 traite jadis comme transitoire. On distingue ce qui peut
                # guerir tout seul (reseau, charge) de ce qui ne le peut pas.
                if isinstance(exc, (NameError, AttributeError, TypeError,
                                    ImportError, KeyError, IndexError)):
                    log("  DEFAUT DE CODE %s: %s -> ABORT (aucune attente n'y changera rien)"
                        % (type(exc).__name__, m))
                    return -1
                # Trois echecs CONSECUTIFS sur le meme lot : ce n'est plus un alea,
                # c'est un etat stable. Sans ce compteur la boucle etait INFINIE --
                # mesure du jour, un lot refuse a repete « pause 60s » sans fin.
                echecs += 1
                if echecs >= 3:
                    log("  3 echecs consecutifs sur le meme lot (%s) -> ABORT" % m[:120])
                    return -1
                log(f"  {type(exc).__name__}: {m} -> pause 60s ({echecs}/3)")
                _time.sleep(60)
    if tronques:
        log(f"  {tronques} chunk(s) TRONQUES a {max_chars} chars pour le vecteur "
            f"(texte complet conserve en base pour le lexical)")
    return done


def main() -> None:
    args = sys.argv[1:]
    log(f"=== forge_reindex_deport START args={args} ===")
    if "--whereis" in args:
        _load_vault()
        whereis()
        log("=== forge_reindex_deport END ===")
        return
    if "--probe" in args:
        probe()
        log("=== forge_reindex_deport END ===")
        return
    _load_vault()  # phases : injecter clés cloud avant import forge_rebuild_embeddings
    limit = 0
    for a in args:
        if a.startswith("--max="):
            limit = int(a.split("=", 1)[1])
        elif a == "--max":
            i = args.index(a)
            if i + 1 < len(args):
                limit = int(args[i + 1])
    # MODE BOUCLE (2026-08-05). Le quota gratuit de Workers AI s'epuise en cours de
    # route : mesure du jour, 6 016 chunks a ~9/s puis HTTP 429 et arret PROPRE. Le
    # travail se fait donc par vagues, au rythme ou le quota se recharge — ce que la
    # tache planifiee horaire devait assurer et n'a JAMAIS fait, son installation
    # exigeant une console admin jamais ouverte (mesure 2026-08-03 : 21 runs, tous
    # manuels, aucun automatique).
    #
    # Un service SUPERVISE remplace ce mecanisme mort. Il doit rester VIVANT entre
    # deux vagues plutot que sortir : le superviseur relancerait un process sorti
    # immediatement, et on repartirait dans le 429 en boucle serree.
    _watch = 0.0
    for i, a in enumerate(args):
        if a.startswith("--watch="):
            _watch = float(a.split("=", 1)[1])
        elif a == "--watch" and i + 1 < len(args):
            _watch = float(args[i + 1])

    def _une_passe() -> None:
        if "--index-only" in args:
            phase_a_index()
        elif "--full" in args:
            phase_a_index()
            phase_b_embed(limit)
        else:  # défaut + --embed-only : embed NULL-only (Phase A déjà indexé)
            phase_b_embed(limit)

    if _watch <= 0:
        _une_passe()
        log("=== forge_reindex_deport END ===")
        return
    import time as _t

    log(f"=== mode BOUCLE : une vague, puis pause de {_watch:.0f}s ===")
    _vague = 0
    while True:
        _vague += 1
        log(f"--- vague {_vague} ---")
        try:
            _une_passe()
        except Exception as _e:  # noqa: BLE001
            # Une vague qui echoue ne doit pas tuer la boucle : le quota reviendra.
            # Mais elle le DIT — un daemon qui se tait ressemble a un daemon qui
            # travaille.
            log(f"  vague {_vague} INTERROMPUE ({type(_e).__name__}: {str(_e)[:120]}) "
                f"-- la boucle continue, prochaine tentative dans {_watch:.0f}s")
        # BATTEMENT (2026-08-25). Ce daemon sortait « VIVANT MAIS DENERVE » a l'audit
        # et « mort silencieuse » a l'audit de regulation. Il tourne par vagues d'une
        # heure : sans battement, un arret se confond avec une pause — et la regulation
        # ne peut pas distinguer un organe qui digere d'un organe qui est mort.
        # Le battement est ecrit APRES la vague, reussie OU interrompue : ce qui est
        # atteste ici est que la BOUCLE vit, pas que la vague a abouti.
        try:
            import json as _hj
            import os as _ho
            from pathlib import Path as _HP

            _hb = _HP(__file__).resolve().parent.parent / "sandbox" / "reindex_deport.heartbeat"
            _hb.parent.mkdir(parents=True, exist_ok=True)
            _hb.write_text(_hj.dumps({"ts": _t.time(), "pid": _ho.getpid(),
                                      "vague": _vague}), encoding="utf-8")
        except Exception as _he:  # noqa: BLE001
            log(f"  heartbeat NON ecrit ({type(_he).__name__}) -- ce daemon redevient "
                f"invisible au contrat")
        _t.sleep(_watch)


if __name__ == "__main__":
    main()
