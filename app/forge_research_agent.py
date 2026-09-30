"""forge_research_agent.py - Agent recherche autonome zero token Claude"""

import json, sqlite3, urllib.request, urllib.parse, urllib.error, hashlib, re
from datetime import datetime, timezone
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)


def _gs(k: str) -> str:
    """Secure secret access — WCM > .env > os.environ."""
    try:
        import sys as _sys

        _sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
        from nokido_agent.app.forge_secrets import get_secret

        return get_secret(k) or ""
    except Exception:
        import os as _os

        return _os.environ.get(k, "")


ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"


def _ollama(prompt, model="qwen2.5-coder:latest", timeout=30):
    body = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate", data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()).get("response", "").strip()
    except Exception as e:
        return f"ERR:{e}"


def _modele_groq() -> str:
    """Modele Groq VIVANT, lu au slot `groq_fast` du routeur -- source unique.

    MESURE 2026-09-25 : le Llama 3 8B (fenetre 8K) code en dur ici n'est plus servi par Groq ; le routeur
    avait remplace ses modeles morts le 2026-08-18, ce jumeau n'avait pas suivi. Repli sur le
    modele que le routeur designait ce jour-la si le routeur est illisible."""
    try:
        from nokido_agent.app.forge_llm_router import get_router

        return get_router().slot("groq_fast").config["models"][0].split("groq/", 1)[-1]
    except Exception:  # noqa: BLE001 - routeur illisible : repli explicite, jamais un modele mort
        return "openai/gpt-oss-20b"


def _groq(prompt, timeout=20):
    try:
        from nokido_agent.app.forge_key_rotation import resolve as _rot_resolve, mark_http as _rot_mark_http
    except Exception:
        _rot_resolve = None
        _rot_mark_http = None

    key = None
    if _rot_resolve:
        managed, key = _rot_resolve("GROQ_API_KEY")
        if managed and not key:
            return "ERR:key_pool_exhausted"
    if not key:
        key = _gs("GROQ_API_KEY")
    if not key:
        return "ERR:no_key"

    body = json.dumps(
        {"model": _modele_groq(), "messages": [{"role": "user", "content": prompt}], "max_tokens": 1024}
    ).encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read())["choices"][0]["message"]["content"].strip()
            if _rot_mark_http:
                try:
                    _rot_mark_http("GROQ_API_KEY", key, 200)
                except Exception:  # muet-ok : sante de cle best-effort  # noqa: BLE001
                    pass
            return out
    except Exception as e:
        status_code = getattr(e, "code", None)
        if status_code and _rot_mark_http:
            try:
                _rot_mark_http("GROQ_API_KEY", key, status_code)
            except Exception:  # muet-ok : sante de cle best-effort  # noqa: BLE001
                pass
            if status_code in (401, 403, 429) and _rot_resolve:
                _managed_next, next_key = _rot_resolve("GROQ_API_KEY")
                if next_key and next_key != key:
                    return _groq(prompt, timeout=timeout)
        return f"ERR:{e}"


def _llm(prompt, provider="auto", use_case=None):
    """Router _llm vers le routeur SOUVERAIN existant (forge_llm_router.py::LLMRouter.call_cascade).
    REUTILISE LLMRouter, ses providers, ses USE_CASE_CHAINS ('strategy', 'synthesis', 'general'),
    et SemanticFirewall.pre_flight.

    Retourne un tuple (texte_reponse, provider_nom).
    """
    if not use_case:
        if "Genere" in prompt and "requetes" in prompt:
            use_case = "strategy"
        elif "Resume" in prompt or "Infos:" in prompt:
            use_case = "synthesis"
        else:
            use_case = "general"

    # Provider specifique force (ex: "ollama", "groq")
    if provider and provider != "auto":
        if provider == "ollama":
            res = _ollama(prompt)
            return res, "ollama_local"
        elif provider == "groq":
            res = _groq(prompt)
            return res, "groq"

    # Provider auto : passage par LLMRouter souverain
    try:
        from nokido_agent.app.forge_llm_router import get_router

        router = get_router()
        res_dict = router.call_cascade(prompt, use_case=use_case)
        if res_dict.get("ok") and res_dict.get("text"):
            return res_dict["text"], res_dict.get("provider", "unknown")
        _why = str(res_dict.get("error") or "reponse vide")[:70]
    except Exception as e:  # muet-ok : l'echec ne doit pas annuler la recherche,
        # mais il est NOMME dans le provider rendu au lieu d'etre avale. Un repli
        # silencieux fait passer une panne de routeur pour un choix delibere.
        _why = f"{type(e).__name__}: {e}"[:70]

    # Fallback souverain en dernier recours : Ollama local
    ollama_res = _ollama(prompt)
    if ollama_res and not ollama_res.startswith("ERR"):
        return ollama_res, f"ollama_local (repli — routeur KO: {_why})"

    # Repli Groq si dispo
    groq_res = _groq(prompt)
    if groq_res and not groq_res.startswith("ERR"):
        return groq_res, "groq"

    return "ERR:no_provider_available", "none"


_SEARXNG_DOWN_UNTIL = 0.0


def _search(q, n=5, max_retries=3):
    import os, time, random

    global _SEARXNG_DOWN_UNTIL
    now = time.monotonic()
    if now < _SEARXNG_DOWN_UNTIL:
        max_retries = 1

    base = os.environ.get("SEARXNG_URL", "http://127.0.0.1:8080")
    url = base + "/search?" + urllib.parse.urlencode({"q": q, "format": "json"})

    last_err = ""
    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=4) as r:
                _SEARXNG_DOWN_UNTIL = 0.0
                data = json.loads(r.read())
            res = data.get("results", [])[:n]
            # Moteurs MUETS != web VIDE (mesure 2026-09-26 : 4/4 veilles de la soif « no results »
            # sans erreur, SearXNG repondait sans resultat). L'API nomme ses moteurs defaillants ;
            # un zero accompagne de moteurs muets est une ERREUR, qui declenche le repli academique.
            muets = data.get("unresponsive_engines") or []
            if not res and muets:
                noms = ", ".join("%s (%s)" % (m[0], m[1]) if isinstance(m, (list, tuple)) and len(m) > 1
                                 else str(m) for m in muets[:6])
                return [], ("moteurs SearXNG muets : " + noms)[:200]
            return res, ""
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"[:120]
            # HTTP 4xx applicatif (ex: 400, 403, 404) -> pas de retry, abandon direct
            if isinstance(e, urllib.error.HTTPError) and 400 <= e.code < 500:
                return [], last_err

            # Erreur de connexion / reseau / timeout / HTTP 5xx -> reessayer avec recul et jitter
            if attempt < max_retries:
                delays = [3, 6, 10]
                base_delay = delays[attempt - 1] if attempt - 1 < len(delays) else 6
                jitter = random.uniform(0.8, 1.2)
                time.sleep(base_delay * jitter)
            else:
                _SEARXNG_DOWN_UNTIL = time.monotonic() + 30.0

    return [], last_err


# Fiche V3 memoire (23/09), DECISION : « re-sourcer les articles arXiv en /html/ ». Une page /abs/ ne porte
# que le RESUME ; /html/<id> porte l'article. Mesure 26/09 : les veilles de la soif passent par le repli
# academique (OpenAlex puis arXiv) et ingeraient donc des resumes.
_ARXIV_ABS = re.compile(r"^https?://(?:www\.)?arxiv\.org/abs/(\d{4}\.\d{4,5}(?:v\d+)?)\b")
_ARXIV_HTML_MIN = 2000  # en-dessous, la version HTML est absente ou vide : repli sur /abs/


def _fetch(url):
    m = _ARXIV_ABS.match(url or "")
    if m:
        texte = _fetch_brut("https://arxiv.org/html/%s" % m.group(1))
        if len(texte) >= _ARXIV_HTML_MIN:
            return texte
        import sys as _s
        print("[research] arXiv %s : pas de version /html/ exploitable (%d car.) -- repli sur /abs/ "
              "(RESUME seul)" % (m.group(1), len(texte)), file=_s.stderr, flush=True)
    return _fetch_brut(url)


def _fetch_brut(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LaForge/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            html = r.read().decode("utf-8", errors="replace")
        # Blocs <style> retires AVANT le retrait des balises (preuve chemin reel 26/09 : l'article DGM en
        # /html/ commencait par « /* Banner pre-dismissal ... */ html[data-banner-dismissed] ... » -- du CSS
        # ingere comme texte, a chaque page).
        html = re.sub(r"<style\b.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE))
        # 2026-09-12 : `[:6000]` coupait le contenu RECUPERE, a la source, avant
        # tout traitement — invisible en aval puisque le chunker redecoupe ce qui
        # reste. Meme famille que les trois bornes a 4000 de forge_web.
        return re.sub(r"\s+", " ", html).strip()
    except Exception as e:  # noqa: BLE001
        # Le `except:` nu avalait aussi KeyboardInterrupt et SystemExit, et rendait
        # une chaine VIDE : une page injoignable devenait indiscernable d'une page
        # sans contenu. UNKNOWN lu comme NO.
        import sys as _s
        print("[research] fetch %s illisible (%s: %s) — rendu VIDE, ce n est PAS "
              "une page sans contenu" % (url[:80], type(e).__name__, str(e)[:80]),
              file=_s.stderr, flush=True)
        return ""


# Plancher de pertinence (26/09). Mesure : les veilles RSI de la soif ingeraient « LLMs encode clinical
# knowledge », « GPT-4 Technical Report », « GLUE » pour « misevolution in self-evolving LLM agents » -- le
# repli academique rend des travaux POPULAIRES sur une requete courte, et la selection LLM (titres a 60 car.,
# repli sur les N premiers) ne filtrait rien. Seuil mesure AVANT d'etre code
# (C:/tmp/corrections/mesure_pertinence_veilles_rsi.py, sources etiquetees a la main) : >= 1 terme
# distinctif ecarte 11/14 hors sujet et 3/13 gardes (marginaux) ; >= 2 en perdait 8/13. Ce qui est ecarte
# est RENDU (`ecartees`, avec le motif) : un filtre qui ecarte le dit.
_MOTS_VIDES = frozenset((
    "llm llms model models language large based using agent agents learning evaluation system systems "
    "approach study paper towards with from their them this that these into over under which while also "
    "such have more than self own").split())
_PERTINENCE_MIN = 1


def _termes(texte):
    import unicodedata

    plat = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode().lower()
    out = set()
    for m in re.findall(r"[a-z][a-z0-9]+", plat):
        if len(m) < 4 or m in _MOTS_VIDES:
            continue
        out.add(m[:-1] if m.endswith("s") and len(m) > 4 else m)
    return out


def _pertinence(objectif, resultat):
    """Nombre de termes DISTINCTIFS de l'objectif presents dans le titre + le resume du resultat."""
    return len(_termes(objectif) & _termes("%s %s" % (resultat.get("title", ""), resultat.get("content", ""))))


def _uid(url):
    return "ra_" + hashlib.md5(url.encode()).hexdigest()[:10]


# `+active` : le `+` unaire interdit l'index sur ce terme. MESURE 26/09 (EXPLAIN QUERY PLAN sur la base
# vivante, sans ANALYZE) : avec `active = 0`, SQLite choisit idx_rag_chunks_active (egalite) plutot que la
# plage de cle primaire -- chaque controle parcourait toutes les lignes gelees d'une base de 45 Go.
_SQL_GELES = "SELECT count(*) FROM rag_chunks WHERE id >= ? AND id < ? AND +active = 0"


def _chunks_geles(conn, uid):
    """Chunks GELES (active=0) de cette source. Plage sur la cle primaire : jamais de scan de la base."""
    return conn.execute(_SQL_GELES, (uid + "_", uid + "`")).fetchone()[0]


def _chunks_geles_url(url):
    """Pre-controle LECTURE SEULE (evite de relire une source gelee). None = ILLISIBLE, jamais lu comme
    « pas gele » : c'est `_ingest`, l'ecrivain, qui tranche dans sa propre connexion."""
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % str(DB).replace("\\", "/"), uri=True, timeout=10)
        try:
            return _chunks_geles(conn, _uid(url))
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - ILLISIBLE rendu None ; l'ecrivain re-verifie avant d'ecrire
        return None


def _ingest(url, title, text, domain, role):
    if len(text) < 100:
        return False
    uid = _uid(url)
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn = sqlite3.connect(str(DB))
        # GEL respecte (26/09). `INSERT OR REPLACE` sur un id deterministe REMPLACE la ligne gelee et
        # `active` retombe a sa valeur par defaut : mesure, la relance des veilles RSI a reactive 6 sources
        # gelees 20 min plus tot sur accord owner. Un gel ne se leve que par la decision qui l'a pose.
        geles = _chunks_geles(conn, uid)
        if geles:
            conn.close()
            import sys as _s
            print("[research] %s : %d chunk(s) GELE(S) -- ingestion REFUSEE (la re-ingerer leverait le gel "
                  "en silence)" % (str(url)[:80], geles), file=_s.stderr, flush=True)
            return False
        words = text.split()
        for i, chunk in enumerate([" ".join(words[j : j + 700]) for j in range(0, len(words), 700)][:8]):
            if len(chunk) > 100:
                conn.execute(
                    "INSERT OR REPLACE INTO rag_chunks (id,text,source,domain,role_hint,author,ingested_at) VALUES (?,?,?,?,?,?,?)",
                    # 2026-09-12 : `[:4000]` sur le TEXTE amputait en silence
                    # (1 053 chunks coupes pile a 4000 en base). Le chunk fait
                    # deja 700 mots par construction ; la borne ne protegeait
                    # rien et jetait du contenu deja paye. `title[:100]` reste :
                    # il borne la colonne `author`, pas le contenu.
                    (f"{uid}_{i:02d}", f"{title}\n\n{chunk}", url, domain, role, title[:100], now),
                )
        conn.commit()
        conn.close()
        return True
    except Exception as e:  # noqa: BLE001
        # 2026-09-12 : `except:` NU rendant False — l'echec d'ECRITURE en base
        # etait indiscernable d'un refus legitime, et l'appelant ne pouvait pas
        # distinguer « rien a ingerer » de « l'ingestion a echoue ». C'est aussi
        # l'endroit ou une erreur du correctif de clef primaire pose ce jour-la
        # serait passee inapercue : un garde muet cache d'abord les defauts de
        # celui qui vient d'ecrire.
        import sys as _s
        print("[research] ingestion %s ECHOUEE (%s: %s) — aucun chunk ecrit"
              % (str(url)[:80], type(e).__name__, str(e)[:100]),
              file=_s.stderr, flush=True)
        return False


def _unpack_llm(res):
    """Extrait (texte, provider) qu'il s'agisse d'un tuple de _llm ou d'une chaine d'un mock."""
    if isinstance(res, tuple):
        return res[0], res[1]
    return str(res or ""), "mock"


def research_agent(objective, max_rounds=2, max_urls=5, domain="research", provider="auto"):
    # 0. Memoire Letta persistante : rappelle les recherches passees sur ce sujet
    _mem = None
    prior = ""
    memory_error = ""
    try:
        from nokido_agent.app.forge_memory_archival import get_agent_memory

        _mem = get_agent_memory("research_agent", session_id=hashlib.md5(objective.encode()).hexdigest()[:12])
        _recalled = _mem.recall(objective, top_k=3)
        if _recalled:
            prior = "\n".join(f"- {m.content[:200]}" for m in _recalled)
    except Exception:
        _mem = None
    _pctx = f"\nDeja su (memoire):\n{prior}\n" if prior else ""

    # 1. Queries
    # PAS de _pctx ici (2026-07-31) : _mem.recall(top_k=3) n'a AUCUN plancher de
    # pertinence -- sur un objectif neuf il rend les 3 souvenirs les moins eloignes,
    # si lointains soient-ils. Mesure : une veille passee sur JuiceFS est arrivee en
    # « Deja su » dans une recherche sur la VM WSL2, et le LLM a produit la requete
    # « JuiceFS architecture overview ». La memoire sert la SYNTHESE (etape 5), elle
    # ne doit pas choisir le SUJET.
    qs_raw, provider_q = _unpack_llm(
        _llm(
            f"Objectif: {objective}\nGenere {max_rounds + 1} requetes web courtes (1-6 mots), une par ligne, sans explication.",
            provider,
        )
    )

    def _norm_q(q: str) -> str:
        """Normalise UNE ligne de sortie LLM en requete, ou rend "" si ce n'en est
        pas une. Le prompt dit « une par ligne, sans explication » et le modele
        repond quand meme autre chose : on normalise la SORTIE au lieu de faire
        confiance a la consigne. Mesures 2026-07-31, deux formes payees :
        `1. "WSL2 Docker Desktop crash logs"` (numerotation + guillemets) puis
        '```python' et 'GET /api/test-endpoint HTTP/1.1' (bloc de code)."""
        q = q.strip()
        if q.startswith("```") or q.startswith("~~~"):
            return ""
        q = re.sub(r"^\s*(?:\d+[\.\)]|[-*•])\s*", "", q)
        q = q.strip().strip('"').strip("'").strip()
        if re.match(r"^(?:GET|POST|PUT|DELETE|HEAD|PATCH)\s+\S+\s+HTTP/", q):
            return ""
        if len(q) > 120 or "{" in q or ";" in q or q.startswith("#"):
            return ""
        return q

    queries = [
        x
        for x in (_norm_q(q) for q in qs_raw.splitlines() if q.strip() and not q.startswith("ERR"))
        if x
    ][: max_rounds + 1]
    # L'objectif lui-meme est TOUJOURS interroge : l'ancien repli `or [objective]` ne
    # se declenchait que sur une liste VIDE, jamais sur une liste MAUVAISE. Une
    # expansion qui derape ne peut donc plus faire sortir « no results » -- ce qui
    # accusait le web d'un defaut de generation.
    _obj_q = objective[:80]
    if _obj_q not in queries:
        queries.append(_obj_q)

    # 2. Search
    seen = set()
    results = []
    search_errors = []
    search_path = "searxng"
    for q in queries:
        _res, _err = _search(q, 4)
        if _err:
            search_errors.append(f"{q[:40]} -> {_err}")
        for r in _res:
            if r.get("url", "") not in seen:
                seen.add(r["url"])
                results.append(r)

    # Repli academique si SearXNG rend une erreur et aucun resultat
    if not results and search_errors:
        try:
            from nokido_agent.app.forge_watch_agent import _academic_search

            for q in queries:
                _acad_res = _academic_search(q, 4)
                for r in _acad_res:
                    if r.get("url", "") not in seen:
                        seen.add(r["url"])
                        results.append(r)
            if results:
                search_path = "academique"
        except Exception as _acad_err:
            search_errors.append(f"academic_fallback -> {_acad_err}")

    if not results:
        # Un moteur injoignable N'EST PAS un web vide : le dire, sinon la panne
        # locale se lit comme une absence de matiere et personne ne va reparer.
        return {
            "ok": False,
            "error": "moteur injoignable" if search_errors else "no results",
            "queries": queries,
            "llm_provider": provider_q,
            "search_path": search_path,
            "search_errors": search_errors[:5],
        }

    # 2bis. Plancher de pertinence (voir _PERTINENCE_MIN) : le hors sujet n'atteint ni la selection LLM ni
    # l'ingestion, et il est RENDU avec son score.
    ecartees = []
    pertinents = []
    notes = {}
    for r in results:
        score = _pertinence(objective, r)
        notes[r.get("url", "")] = score
        if score < _PERTINENCE_MIN:
            ecartees.append({"url": r.get("url", ""), "titre": str(r.get("title", ""))[:80],
                             "motif": "pertinence %d < %d terme(s) distinctif(s) de l'objectif"
                                      % (score, _PERTINENCE_MIN)})
        else:
            pertinents.append(r)
    pertinents.sort(key=lambda r: -notes.get(r.get("url", ""), 0))  # stable : l'ordre du moteur departage

    # 3. Selection par un JUGE, second observateur apres le plancher lexical (26/09). Mesure : l'ancien prompt
    # exigeait « Selectionne min(max_urls, n) numeros » -- 7 pertinents pour max_urls=8 => 7 sur 7, le juge ne
    # pouvait rien ecarter ; il ne voyait que 60 car. de titre ; et ses doublons (« 1,3,1 ») ingeraient deux fois
    # la meme source (`ingerees` gonfle). Le juge voit titre + debut du resume, peut repondre AUCUN, ses numeros
    # sont dedoublonnes. Juge ILLISIBLE (ERR, vide, ni numero ni AUCUN) : seul le plancher lexical STRICT
    # (> _PERTINENCE_MIN) retient -- un observateur de moins exige une preuve de plus -- et c'est dit.
    idxs = []
    cands = pertinents[:15]
    selection = "aucun candidat"
    if cands:
        liste = "\n".join("%d. %s -- %s" % (i + 1, str(r.get("title", ""))[:100],
                                            str(r.get("content", ""))[:200].replace("\n", " "))
                          for i, r in enumerate(cands))
        sel_raw, provider_sel = _unpack_llm(
            _llm(
                f"Objectif: {objective}\nCandidats (titre -- debut du resume):\n{liste}\n"
                f"Selectionne les numeros des candidats qui traitent DIRECTEMENT de l'objectif (au plus {max_urls}), "
                "separes par des virgules. Si aucun ne le fait, reponds AUCUN.",
                provider,
            )
        )
        brut = str(sel_raw or "").strip()
        lisible = bool(brut) and not brut.startswith("ERR")
        nums = []
        if lisible:
            for x in re.findall(r"\d+", brut):
                i = int(x) - 1
                if 0 <= i < len(cands) and i not in nums:
                    nums.append(i)
        if nums:
            idxs = nums[:max_urls]
            selection = "juge LLM (%s)" % provider_sel
        elif lisible and re.search(r"\b(?:aucun|none)\b", brut, re.IGNORECASE):
            selection = "juge LLM : AUCUN (%s)" % provider_sel
        else:
            idxs = [i for i, r in enumerate(cands) if notes.get(r.get("url", ""), 0) > _PERTINENCE_MIN][:max_urls]
            selection = "plancher lexical strict (juge illisible : %s)" % (brut[:60] or "reponse vide")
        for i, r in enumerate(cands):
            if i not in idxs:
                ecartees.append({"url": r.get("url", ""), "titre": str(r.get("title", ""))[:80],
                                 "motif": "non retenue par la selection -- %s" % selection[:60]})
    for r in pertinents[15:]:
        ecartees.append({"url": r.get("url", ""), "titre": str(r.get("title", ""))[:80],
                         "motif": "au-dela des 15 candidats presentes au juge"})

    # 4. Ingest
    ingested = 0
    texts = []
    retenues = []
    for r in [cands[i] for i in idxs]:
        geles = _chunks_geles_url(r["url"])
        if geles:
            ecartees.append({"url": r["url"], "titre": str(r.get("title", ""))[:80],
                             "motif": "source gelee (%d chunk(s) active=0) : ni relue ni re-ingeree" % geles})
            continue
        text = _fetch(r["url"]) or r.get("content", "")
        if _ingest(r["url"], r.get("title", ""), text, domain, f"research:{objective[:30]}"):
            ingested += 1
            retenues.append(r["url"])
            # La synthese lit le RESUME (repli academique : content = abstract), a defaut la page. Mesure 26/09 :
            # `text[:150]` etait l'en-tete HTML (titre, auteurs, menus) -- la synthese resumait des en-tetes.
            # 800 car. = fenetre du PROMPT de synthese ; le texte integral est ingere, rien n'est jete.
            resume = r.get("content") or ""
            if len(resume) < 200:
                resume = text
            texts.append(f"{r.get('title', '')}: {resume[:800]}")

    # 5. Synthese
    synth, provider_synth = (
        _unpack_llm(
            _llm(
                f"Objectif: {objective}{_pctx}\nInfos:\n" + "\n---\n".join(texts[:4]) + "\nResume en 3 phrases.",
                provider,
            )
        )
        if texts
        else ("Rien trouve.", "none")
    )

    # Persiste durablement l'apprentissage (survit au process ; recall futur).
    # Une synthese en ERR N'EST PAS un apprentissage : la persister la rend
    # rappelable, et `recall` la resservira en « Deja su » a la recherche voisine
    # suivante. Mesure 2026-07-31 : « ERR:HTTP Error 403: Forbidden » (refus
    # provider) allait entrer en memoire comme resultat de recherche. Un organe
    # qui memorise ses propres pannes s'empoisonne -- meme famille que le capteur
    # qui lit sa propre sortie.
    _synth_ok = bool(synth) and not synth.startswith("ERR") and synth != "Rien trouve."
    if _mem is not None and _synth_ok:
        try:
            _mem.remember("user", f"Recherche: {objective}")
            _mem.remember("assistant", f"Synthese: {synth}")
        except Exception as _e:  # muet-ok : la persistance est best-effort, son
            # echec ne doit pas annuler une recherche DEJA faite et ingeree. On le
            # dit quand meme dans le retour plutot que de l'avaler completement.
            memory_error = f"{type(_e).__name__}: {_e}"[:120]

    return {
        "ok": True,
        "objective": objective,
        "queries": queries,
        "found": len(results),
        "pertinents": len(pertinents),
        "selection": selection,
        "ingested": ingested,
        "retenues": retenues,
        # Borne d'AFFICHAGE : `ecartees_n` dit combien ont ete ecartees en tout.
        "ecartees": ecartees[:20],
        "ecartees_n": len(ecartees),
        "domain": domain,
        "synthesis": synth,
        # Troisieme etat explicite : l'ingestion peut reussir pendant que la synthese
        # echoue (provider 403). L'appelant doit pouvoir les distinguer au lieu de
        # lire une chaine d'erreur comme un resultat.
        "synthesis_ok": _synth_ok,
        "llm_provider": provider_synth if _synth_ok else provider_q,
        "search_path": search_path,
        "search_errors": search_errors[:5],
        "memory_error": memory_error,
    }


if __name__ == "__main__":
    import sys

    obj = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "MCP Streamable HTTP specification 2025"
    print(json.dumps(research_agent(obj, max_rounds=2, max_urls=4), indent=2, ensure_ascii=False))
