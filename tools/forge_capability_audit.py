"""forge_capability_audit.py - le README declare, le CODE decide.

POURQUOI. Audit externe du 2026-08-20 : plusieurs affirmations du README
contredisent le code (nom du paquet pip, entrypoints, nombre d'extras, taille du
corpus, chemin d'embedding, axes du scorecard). Aucune n'etait fausse a
l'ecriture -- le code a simplement bouge plus vite que sa documentation. Un
README qui survend une capacite est pire qu'un README absent : l'agent suivant
le CROIT, et construit sur une garantie qui n'existe pas.

Nettoyer le README a la main ne corrige que l'instant. Ce module transforme la
documentation en GARDE : chaque declaration verifiable est confrontee a une
mesure prise sur le depot, et la divergence devient un echec de CI.

DOCTRINE. Trois verdicts, jamais deux :
  ALIGNE      - la declaration correspond a la mesure.
  DIVERGE     - la declaration contredit la mesure. Bloquant.
  INDETERMINE - la mesure n'a PAS pu etre prise (fichier absent, format
                inattendu). Ce n'est PAS un succes : un controle qui ne mesure
                rien doit le dire, sinon il fabrique un vert sans preuve.

    LAFORGE_PYTHON tools/forge_capability_audit.py
    LAFORGE_PYTHON tools/forge_capability_audit.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ALIGNE, DIVERGE, INDETERMINE = "ALIGNE", "DIVERGE", "INDETERMINE"


def _lire(rel: str) -> str | None:
    """Contenu d'un fichier du depot, ou None -- l'absence n'est pas un verdict."""
    p = ROOT / rel
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - fichier absent/illisible -> INDETERMINE en aval
        return None


def _v(nom: str, statut: str, declare, mesure, note: str = "") -> dict:
    return {"controle": nom, "statut": statut, "declare": declare,
            "mesure": mesure, "note": note}


# ---------------------------------------------------------------------------
# Controles. Chacun rend un dict ; aucun ne leve.
# ---------------------------------------------------------------------------

def c_nom_paquet(readme: str, pyproject: str) -> dict:
    """Le nom de distribution ANNONCE doit etre celui que pyproject declare.

    DEUX SOURCES, et l'ordre a un sens (mesure 2026-09-09, P4.2a) :

      1. `<!-- DIST:nom -->` — declaration STRUCTUREE, sur le patron de la ligne
         `<!-- STATS: -->` que ce depot utilise deja ;
      2. `egg=nom` — repli, quand une commande d'installation VCS est documentee.

    POURQUOI LA PREMIERE EXISTE. Le controle ne lisait que `egg=`, donc il dependait
    d'une COMMANDE D'INSTALLATION. Le jour ou le README a cesse d'en promettre une --
    P4.2a ayant mesure qu'aucune ne fonctionnait -- le controle est retombe en
    INDETERMINE, alors que la propriete qu'il mesure (« le nom annonce est-il celui
    de pyproject ») existe independamment de toute installation.

    POURQUOI ON NE LIT PAS LA PROSE. Chercher le nom n'importe ou dans le README
    ferait revenir un faux positif deja paye le meme jour : la phrase « Making
    `pip install nokido-agent` work is a genuine migration » aurait ete prise pour
    une annonce, alors qu'elle dit exactement l'inverse. Mentionner un concept n'est
    pas le declarer.

    CE QUE CE CONTROLE NE DIT PAS : que le paquet s'installe. L'identite de
    distribution et l'installabilite sont deux proprietes distinctes ; seule une
    reproduction en environnement neuf etablit la seconde (P4).
    """
    m = re.search(r'^\s*name\s*=\s*["\']([^"\']+)["\']', pyproject, re.M)
    if not m:
        return _v("nom du paquet pip", INDETERMINE, None, None,
                  "`name` introuvable dans pyproject.toml")
    reel = m.group(1)
    cites = sorted(set(re.findall(r"<!--\s*DIST:\s*([A-Za-z0-9_.-]+)\s*-->", readme)))
    if not cites:
        cites = sorted(set(re.findall(r"egg=([A-Za-z0-9_.-]+)", readme)))
    if not cites:
        return _v("nom du paquet pip", INDETERMINE, None, reel,
                  "ni `<!-- DIST:nom -->` ni `egg=` dans le README")
    faux = [c for c in cites if c != reel]
    return _v("nom du paquet pip", DIVERGE if faux else ALIGNE, cites, reel,
              "le README installe %s" % ", ".join(faux) if faux else "")


def c_entrypoints(readme: str, pyproject: str) -> dict:
    """Les commandes citees dans le README doivent exister dans [project.scripts]."""
    bloc = re.search(r"\[project\.scripts\](.*?)(?=\n\[|\Z)", pyproject, re.S)
    if not bloc:
        return _v("commandes CLI", INDETERMINE, None, None,
                  "[project.scripts] introuvable")
    reels = set(re.findall(r"^\s*([A-Za-z0-9_-]+)\s*=", bloc.group(1), re.M))
    # Une COMMANDE est un mot en position d'invocation dans un bloc shell -- pas
    # n'importe quelle occurrence du nom. Sans cette restriction, le controle
    # ramassait `laforge-qwen` (un modele Ollama) et `laforge-sovereign` (le nom
    # du serveur MCP) et exigeait des entrypoints qui n'ont jamais existe :
    # un garde qui crie a faux se fait desarmer (mesure 2026-08-20).
    cites = set()
    # `\r?\n` : le depot est en CRLF, et un motif ancre sur `\n` seul n'extrayait
    # AUCUN bloc -- le controle rendait alors ALIGNE sans avoir rien lu.
    for bloc in re.findall(r"```(?:[a-z]*)?\r?\n(.*?)```", readme, re.S):
        for ligne in bloc.splitlines():
            # PREMIER token seulement : `docker exec laforge-ollama ...` invoque
            # `docker` et nomme un conteneur, ce n'est pas un entrypoint Python.
            m = re.match(r"\s*\$?\s*((?:laforge|nokido)-[a-z]+)\b", ligne)
            if m:
                cites.add(m.group(1))
    # Et la liste que le README declare explicitement comme entry points.
    for ligne in readme.splitlines():
        if re.search(r"entry ?points?", ligne, re.I):
            cites.update(re.findall(r"`((?:laforge|nokido)-[a-z]+)`", ligne))
    fantomes = sorted(cites - reels)
    return _v("commandes CLI", DIVERGE if fantomes else ALIGNE,
              sorted(cites), sorted(reels),
              "citees mais inexistantes : %s" % ", ".join(fantomes) if fantomes else "")


def c_extras(readme: str, pyproject: str) -> dict:
    """« N extras » doit correspondre aux extras reels, bundles exclus."""
    bloc = re.search(r"\[project\.optional-dependencies\](.*?)(?=\n\[|\Z)",
                     pyproject, re.S)
    if not bloc:
        return _v("nombre d'extras", INDETERMINE, None, None,
                  "[project.optional-dependencies] introuvable")
    tous = set(re.findall(r"^\s*([A-Za-z0-9_-]+)\s*=", bloc.group(1), re.M))
    bundles = {"full", "all"} & tous
    reels = sorted(tous - bundles)
    m = re.search(r"(\d+)\s+extras", readme, re.I)
    if not m:
        return _v("nombre d'extras", INDETERMINE, None, len(reels),
                  "le README n'annonce aucun nombre d'extras")
    declare = int(m.group(1))
    ok = declare == len(reels)
    return _v("nombre d'extras", ALIGNE if ok else DIVERGE, declare, len(reels),
              "" if ok else "%d extras + bundles %s" % (len(reels), sorted(bundles)))


def c_taille_corpus(readme: str) -> dict:
    """Le corps du README ne doit pas contredire sa propre ligne STATS."""
    m = re.search(r"rag_chunks=(\d+)", readme)
    if not m:
        return _v("taille du corpus RAG", INDETERMINE, None, None,
                  "ligne STATS absente du README")
    reel = int(m.group(1))
    # Un nombre ne compte QUE s'il qualifie des chunks. Sans cette ancre, le
    # controle ramassait « Radeon 780M » comme 780 millions de fragments et
    # « 3k » comme un corpus : un garde qui crie a faux se fait desarmer, donc
    # il ne doit crier que sur ce qu'il sait lire (mesure 2026-08-20).
    approx = []
    motif = re.compile(
        r"~?\s*([\d][\d\s.,]*)\s*([kKmM])?\s*(?:chunks?|fragments?)", re.I)
    for n, suf in motif.findall(readme):
        brut = n.replace(" ", "").replace(" ", "").strip(".,")
        if not brut:
            continue
        try:
            val = float(brut.replace(",", ".")) if suf else float(brut.replace(",", ""))
        except ValueError:  # muet-ok : tri de texte libre, jeton non numerique = pas une erreur
            continue
        # Le suffixe ne multiplie que s'il n'y a pas deja des milliers ecrits :
        # « 685 000 » suivi d'un « k » plus loin dans la phrase donnait 685 millions.
        mult = 1
        if suf and len(brut.rstrip("0")) <= 4 and val < 10_000:
            mult = 1000 if suf in "kK" else 1_000_000
        val = int(val * mult)
        # Sous 10 000, ce n'est pas le corpus : le README parle ailleurs d'un
        # SEED de bootstrap (« ~3k chunks : lessons, ADRs, biblio »). Confondre
        # l'echantillon et le corpus ferait crier le garde a faux.
        if val >= 10_000:
            approx.append(val)
    if not approx:
        # Aucun chiffre fige dans le corps : c'est l'etat VOULU. La ligne STATS
        # reste la source unique, et le README ne peut plus se perimer tout seul.
        return _v("taille du corpus RAG", ALIGNE, "aucun chiffre fige", reel,
                  "source unique = ligne STATS")
    # Tolerance large : on ne traque pas la fraicheur au chunk pres, seulement
    # les chiffres devenus FAUX d'un facteur significatif.
    faux = [a for a in approx if a and (a < reel * 0.6 or a > reel * 1.6)]
    return _v("taille du corpus RAG", DIVERGE if faux else ALIGNE, sorted(set(approx)),
              reel, "annonces incompatibles avec STATS : %s" % faux if faux else "")


def c_embedding(readme: str) -> dict:
    """« tout passe par :8099 » alors que le routeur a une cascade."""
    src = _lire("app/forge_embed_router.py")
    if src is None:
        return _v("chemin d'embedding", INDETERMINE, None, None,
                  "forge_embed_router.py illisible")
    # Les backends sont des fonctions `_<nom>_call` : c'est la forme stable du
    # module, et elle se compte sans l'importer (aucun effet de bord).
    backends = sorted(set(re.findall(r"^def _([a-z0-9_]+)_call\b", src, re.M)))
    absolu = re.search(r"[Aa]ll embeddings?[^.]{0,400}\.", readme, re.S)
    if not absolu:
        return _v("chemin d'embedding", ALIGNE, "pas d'affirmation absolue",
                  backends, "")
    # Ce qui est faux, ce n'est pas « toutes les demandes passent par le
    # routeur » -- c'est vrai -- mais « et le routeur mene a UN backend ». On
    # juge donc la promesse : la phrase reconnait-elle la cascade ?
    phrase = absolu.group(0)
    nommes = [b for b in backends if b.lower() in phrase.lower()]
    if len(backends) > 1 and len(nommes) < 2:
        return _v("chemin d'embedding", DIVERGE, "un seul backend nomme", backends,
                  "le routeur en expose %d, la phrase en cite %d"
                  % (len(backends), len(nommes)))
    return _v("chemin d'embedding", ALIGNE, "cascade reconnue (%d cites)" % len(nommes),
              backends, "")


def c_scorecard(readme: str) -> dict:
    """« N axes, 0 LLM » : le module appelle-t-il un juge ?"""
    src = _lire("app/forge_scorecard.py")
    if src is None:
        return _v("scorecard", INDETERMINE, None, None,
                  "forge_scorecard.py illisible")
    # Un juge LLM se voit a ses appels sortants, pas au mot « llm » en commentaire.
    juge = bool(re.search(r"\b(ollama|ask_llm|llm_judge|call_cascade|chat\()", src, re.I))
    # La faute a traquer est l'affirmation « 0 LLM » / « zero LLM » sur le
    # scorecard alors qu'un juge existe. Ne plus rien affirmer n'est pas un
    # defaut : c'est le README rendu prudent, donc ALIGNE.
    nie = re.search(r"forge_scorecard[^)\n]{0,40}\b(?:0|zero)\s*LLM", readme, re.I)
    if nie and juge:
        return _v("scorecard", DIVERGE, nie.group(0).strip(),
                  "appel LLM present dans le module",
                  "« zero LLM » contredit par le code")
    return _v("scorecard", ALIGNE, "pas d'affirmation « zero LLM »" if not nie
              else nie.group(0).strip(),
              "juge LLM %s" % ("present" if juge else "absent"), "")


def c_proprioception(readme: str) -> dict:
    """La route citee doit appeler ce que le README lui prete."""
    src = _lire("app/web_hub/wired_routes.py")
    if src is None:
        return _v("/api/graph/proprioception", INDETERMINE, None, None,
                  "wired_routes.py illisible")
    if "/api/graph/proprioception" not in readme:
        return _v("/api/graph/proprioception", INDETERMINE, None, None,
                  "route non citee par le README")
    # FENETRE -> FONCTION (mesure 2026-08-20). Le controle lisait 600 caracteres
    # apres le mot « proprioception » : une docstring un peu longue repoussait
    # l'import hors de la fenetre, et le garde criait a faux sur une route
    # pourtant recablee. On lit desormais le corps ENTIER de la fonction, borne
    # par le decorateur suivant -- une mesure ne doit pas dependre de la
    # verbosite du commentaire qu'elle traverse.
    # Ancre sur le DECORATEUR : la premiere occurrence du mot « proprioception »
    # est dans le docstring du MODULE, qui enumere les routes. Partir de la
    # faisait s'arreter la fenetre au premier `@router.` rencontre -- donc avant
    # d'avoir lu la moindre ligne de la fonction visee.
    bloc = re.search(r"@router\.get\(\s*[\"']/api/graph/proprioception[\"']\s*\)"
                     r".*?(?=\n@router\.|\Z)", src, re.S)
    if not bloc:
        return _v("/api/graph/proprioception", DIVERGE, "route documentee",
                  "absente de wired_routes.py", "endpoint documente non cable")
    cite_ast = bool(re.search(r"forge_ast_index|ast_index", bloc.group(0)))
    if cite_ast:
        return _v("/api/graph/proprioception", ALIGNE,
                  "imports / imported-by / call-graph (AST)", "AST", "")
    # La route ne sert pas l'AST. Le README est ALIGNE s'il le DIT ; il ne l'est
    # pas s'il laisse croire le contraire. Documenter un ecart connu vaut mieux
    # que le taire -- et le recablage reste la meilleure sortie.
    avoue = re.search(r"/api/graph/proprioception[^.\n]{0,200}graph-search", readme)
    return _v("/api/graph/proprioception", ALIGNE if avoue else DIVERGE,
              "ecart documente" if avoue else "imports / imported-by / call-graph (AST)",
              "graph-search",
              "ecart connu et ecrit ; recabler reste preferable" if avoue
              else "la route ne passe pas par l'index AST")


def c_env_docker(readme: str) -> dict:
    """Le fichier prepare par le quick-start doit etre celui que Compose lit."""
    compose = _lire("docker/docker-compose.yml") or _lire("docker-compose.yml")
    if compose is None:
        return _v("fichier .env Docker", INDETERMINE, None, None,
                  "docker-compose.yml introuvable")
    lus = sorted(set(re.findall(r"[-\s]([A-Za-z0-9_.-]+\.env)\b", compose)))
    prepares = sorted(set(re.findall(r"cp\s+([A-Za-z0-9_.-]+)\.env\.example\s+"
                                     r"([A-Za-z0-9_.-]+\.env)", readme)))
    if not lus or not prepares:
        return _v("fichier .env Docker", INDETERMINE, prepares or None, lus or None,
                  "rien a comparer")
    noms_prepares = {p[1] for p in prepares}
    manque = [f for f in noms_prepares if f not in lus]
    return _v("fichier .env Docker", DIVERGE if manque else ALIGNE,
              sorted(noms_prepares), lus,
              "prepare %s, Compose lit %s" % (manque, lus) if manque else "")


# Un SLOT n'est pas un FOURNISSEUR : `PROVIDER_SPECS` route des couples
# (fournisseur, modele) -- `mistral_large` et `mistral_small` sont deux slots
# chez UN fournisseur. Annoncer un nombre sans dire lequel des deux on compte
# est la faute que ce controle empeche. La table est DECLARATIVE : un slot
# inconnu remonte tel quel plutot que d'etre range de force.
_FAMILLES = {
    "claude": "Anthropic", "cohere": "Cohere", "gemini": "Google Gemini",
    "github": "GitHub Models", "glm": "Z.ai GLM", "hf": "HuggingFace",
    "kimi": "Moonshot Kimi", "llamacpp": "llama.cpp", "lmstudio": "LM Studio",
    "mistral": "Mistral", "nvidia": "NVIDIA NIM", "ollama": "Ollama",
    "openrouter": "OpenRouter", "openai": "OpenAI", "sambanova": "SambaNova",
    "xai": "xAI Grok", "cerebras": "Cerebras", "groq": "Groq",
    "deepseek": "DeepSeek", "perplexity": "Perplexity",
}


def _famille(slot: str) -> str:
    for prefixe, nom in _FAMILLES.items():
        # `glm4` / `glm5` sont deux versions d'UN fournisseur : le suffixe peut
        # etre un underscore ou un simple numero de generation. Sans ce cas, le
        # controle comptait deux familles la ou il n'y a qu'une maison.
        if slot == prefixe or slot.startswith(prefixe + "_") or \
                re.fullmatch(re.escape(prefixe) + r"\d+", slot):
            return nom
    return slot


def _slots_provider() -> list[str] | None:
    """Cles de PROVIDER_SPECS lues par AST -- jamais par import : un gate ne
    doit pas executer le module qu'il mesure."""
    src = _lire("app/forge_provider_specs.py")
    if src is None:
        return None
    import ast

    try:
        arbre = ast.parse(src)
    except SyntaxError:
        return None
    for n in ast.walk(arbre):
        cible = None
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            cible = n.target.id
        elif isinstance(n, ast.Assign) and n.targets and isinstance(n.targets[0], ast.Name):
            cible = n.targets[0].id
        if cible == "PROVIDER_SPECS" and isinstance(n.value, ast.Dict):
            return [k.value for k in n.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    return None


def c_providers(readme: str) -> dict:
    """« N providers » : N doit etre defini, et chaque famille doit avoir sa cartouche."""
    slots = _slots_provider()
    if not slots:
        return _v("providers", INDETERMINE, None, None,
                  "PROVIDER_SPECS illisible dans forge_provider_specs.py")
    familles = sorted({_famille(s) for s in slots})
    m = re.search(r"LLM providers?\s*\((\d+)[^)]*\)", readme, re.I)
    # Les cartouches de la section providers : `[![Nom](...)]`.
    # Les cartouches sont cherchees dans TOUT le README : `llama.cpp` figure dans
    # la section « MCP clients & runtimes », et exiger un doublon dans la section
    # providers ferait crier le garde a faux. Une cartouche est une cartouche.
    badges = {b.strip() for b in re.findall(r"\[!\[([^\]]+)\]", readme)}
    sans_cartouche = sorted(f for f in familles
                            if not any(f.lower().split()[0] in b.lower() for b in badges))
    if not m:
        return _v("providers", INDETERMINE, None,
                  "%d slots / %d familles" % (len(slots), len(familles)),
                  "le README n'annonce aucun nombre de providers")
    declare = int(m.group(1))
    if declare not in (len(slots), len(familles)):
        return _v("providers", DIVERGE, declare,
                  "%d slots / %d familles" % (len(slots), len(familles)),
                  "le nombre annonce ne correspond ni aux slots ni aux familles")
    if sans_cartouche:
        return _v("providers", DIVERGE, "%d, %d cartouches" % (declare, len(badges)),
                  "%d familles" % len(familles),
                  "familles routees SANS cartouche : %s" % ", ".join(sans_cartouche))
    return _v("providers", ALIGNE, declare,
              "%d slots / %d familles" % (len(slots), len(familles)), "")


def c_cartouches(readme: str, pyproject: str) -> dict:
    """Les badges de tete affirment des versions : elles doivent etre celles du depot."""
    ecarts = []
    m = re.search(r"\[!\[Python\]\([^)]*badge/Python-([^-?]+)", readme)
    if m and pyproject:
        # « 3.12 %7C 3.13 %7C 3.14 » -> les versions annoncees, une a une.
        annonces = re.findall(r"(\d+\.\d+)", m.group(1))
        req = re.search(r'requires-python\s*=\s*["\']([^"\']+)["\']', pyproject)
        if req and annonces:
            borne = re.search(r">=\s*(\d+)\.(\d+)", req.group(1))
            if borne:
                mini = (int(borne.group(1)), int(borne.group(2)))
                trop_bas = [a for a in annonces
                            if tuple(int(x) for x in a.split(".")) < mini]
                if trop_bas:
                    ecarts.append("Python %s annonce(s) sous requires-python %s"
                                  % (trop_bas, req.group(1)))
    m = re.search(r"\[!\[License\]\([^)]*badge/license-([^-?]+)", readme)
    if m:
        declare = m.group(1).replace("%20", " ")
        lic = re.search(r'license\s*=\s*.{0,80}?["\']([^"\']+)["\']', pyproject or "")
        if lic and declare.lower().rstrip("v3") not in lic.group(1).lower().replace("-", ""):
            ecarts.append("licence badge=%s vs pyproject=%s" % (declare, lic.group(1)))
    m = re.search(r"\[!\[Branch\]\([^)]*badge/branch-([^-?]+)", readme)
    if m:
        tete = _lire(".git/HEAD") or ""
        courante = tete.strip().rsplit("/", 1)[-1] if "ref:" in tete else ""
        if courante and m.group(1) != courante:
            ecarts.append("branche badge=%s vs HEAD=%s" % (m.group(1), courante))
    if ecarts:
        return _v("cartouches de tete", DIVERGE, "; ".join(ecarts), "depot", "")
    return _v("cartouches de tete", ALIGNE, "Python / licence / branche", "depot", "")


def c_cibles_badges(readme: str) -> dict:
    """Une cartouche qui pointe vers le depot doit viser un chemin qui EXISTE.

    Les badges Rust et Go renvoient vers `go_services/...`. Si le dossier
    disparait, le badge continue d'afficher fierement le langage et son lien
    tombe dans le vide : la cartouche survit a la capacite qu'elle annonce.
    """
    morts, verifies = [], 0
    for cible in re.findall(r"\[!\[[^\]]+\]\([^)]+\)\]\(([^)]+)\)", readme):
        # On ne juge que les liens INTERNES : une URL ou une ancre ne se verifie
        # pas ici, et un garde qui pretend juger ce qu'il ne mesure pas ment.
        if cible.startswith(("http://", "https://", "#", "mailto:")):
            continue
        verifies += 1
        if not (ROOT / cible.rstrip("/")).exists():
            morts.append(cible)
    if not verifies:
        return _v("cibles des cartouches", INDETERMINE, None, None,
                  "aucune cartouche ne pointe vers le depot")
    if morts:
        return _v("cibles des cartouches", DIVERGE, morts, "%d liens internes" % verifies,
                  "cartouche affichee, chemin absent du depot")
    return _v("cibles des cartouches", ALIGNE, "%d liens internes" % verifies,
              "tous presents", "")


def c_lnn_npu(readme: str) -> dict:
    """« runs on the local NPU » est une affirmation MATERIELLE : elle se prouve."""
    src = None
    for nom in ("app/forge_lnn_monitor.py", "app/forge_lnn.py"):
        src = _lire(nom)
        if src is not None:
            break
    if src is None:
        return _v("LNN sur NPU", INDETERMINE, None, None, "module LNN introuvable")
    # DEMENTI EXPLICITE ACCEPTE, comme partout ailleurs dans ce module : ecrire
    # « le chemin NPU sert aux embeddings, pas au moniteur LNN » n'est pas une
    # promesse, c'est la levee de l'ambiguite. Ce qu'on refuse, c'est « runs on
    # the local NPU » jete sans preuve.
    dementi = re.search(r"not for the LNN|pas (pour|au) le? moniteur LNN|"
                        r"wired for \*?\*?embeddings\*?\*?, not", readme, re.I)
    promet = bool(re.search(r"LNN|Liquid Neural|\bncps\b", readme, re.I) and
                  re.search(r"\bNPU\b", readme) and not dementi)
    # Un binding NPU se voit a son runtime, pas au mot « NPU » dans un commentaire.
    binding = re.search(r"DirectML|onnxruntime|openvino|xdna|ryzenai|QNN", src, re.I)
    if promet and not binding:
        return _v("LNN sur NPU", DIVERGE, "runs on the local NPU",
                  "ncps/PyTorch, aucun binding NPU dans le module",
                  "affirmation materielle non prouvee par le code")
    return _v("LNN sur NPU", ALIGNE,
              "NPU affirme" if promet else "pas d'affirmation NPU",
              "binding %s" % ("present" if binding else "absent"), "")


def c_mcts(readme: str) -> dict:
    """MCTS annonce facon AlphaZero : le code fait-il une remontee recursive ?"""
    src = _lire("tools/forge_ami_strategist.py") or _lire("app/forge_ami_strategist.py")
    if src is None:
        return _v("MCTS", INDETERMINE, None, None, "forge_ami_strategist introuvable")
    fort = re.search(r"MCTS[^.\n]{0,120}(DeepMind|AlphaZero)", readme, re.I)
    # La remontee dans les ancetres est CE qui distingue un MCTS d'un echantillon
    # Monte-Carlo a profondeur 1. Elle se voit a un parcours de parents.
    backprop = re.search(r"\.parent\b|backpropagat|_backup\(|remont(e|er) .{0,20}ancetre",
                         src, re.I)
    prudent = re.search(r"MCTS[^.\n]{0,120}(experimental|experimentale)", readme, re.I)
    if fort and not backprop and not prudent:
        return _v("MCTS", DIVERGE, "MCTS inspire de DeepMind",
                  "aucune remontee recursive dans le module",
                  "profondeur 1 sans backprop : dire « experimental »")
    return _v("MCTS", ALIGNE,
              "qualifie experimental" if prudent else "pas d'affirmation forte",
              "backprop %s" % ("presente" if backprop else "absente"), "")


# Formules qui promettent une propriete GLOBALE du systeme. Chacune exige une
# preuve que le depot ne fournit pas : il faudrait montrer que TOUT chemin
# d'execution y passe. Les qualifier ne les affaiblit pas -- ca les rend vraies.
_ABSOLUS = (
    (r"every prompt", "every prompt -> « governed LLM-facing paths »"),
    (r"[Ee]very change passes", "every change -> « preferred mutation path »"),
    (r"\bprovably\b", "provably -> « detects » (une detection n'est pas une preuve)"),
    (r"all executions?\b", "all executions -> nommer les chemins concernes"),
)


def c_absolus(readme: str) -> dict:
    """Un README technique ne promet pas une propriete globale sans la prouver."""
    trouves = [conseil for motif, conseil in _ABSOLUS if re.search(motif, readme)]
    if trouves:
        return _v("promesses absolues", DIVERGE, trouves,
                  "aucune preuve de couverture globale dans le depot",
                  "qualifier, ou demontrer que TOUT chemin y passe")
    return _v("promesses absolues", ALIGNE, "aucune formule absolue",
              "les capacites sont enoncees avec leur portee", "")


def c_benchmarks(readme: str) -> dict:
    """Un score sans date ni commit n'est pas reproductible : c'est un souvenir."""
    scores = re.findall(r"(HumanEval|BFCL)[^\n]{0,80}?(\d{2,3}(?:[.,]\d)?\s*%)", readme)
    if not scores:
        return _v("benchmarks dates", ALIGNE, "aucun score affiche", "-", "")
    # La section benchmarks doit porter la date ET le commit de la mesure.
    # Heading en DEBUT de ligne uniquement : sans ^…re.M, le motif matchait le
    # « # » de l'ancre (#-benchmarks) des badges d'en-tete et la zone examinee
    # etait 3000 chars de badges sans date ni commit (CI rouge 2026-08-21).
    section = re.search(r"^#{1,6}\s[^\n]*[Bb]enchmark.{0,3000}", readme, re.S | re.M)
    zone = section.group(0) if section else readme
    a_date = re.search(r"20\d\d-\d\d-\d\d", zone)
    a_commit = re.search(r"\b[0-9a-f]{7,40}\b", zone)
    # AVEU EXPLICITE ACCEPTE. Ecrire « la date et le commit ne sont pas
    # enregistres, traiter comme historique » est PLUS honnete que d'inventer un
    # horodatage : le lecteur sait alors ce qu'il ne sait pas. Ce qu'on refuse,
    # c'est le score nu, presente comme une propriete permanente du systeme.
    avoue = re.search(r"(date and commit are not recorded|non enregistr|"
                      r"treat (these|this) as historical)", readme, re.I)
    manque = [x for x, ok in (("date", a_date), ("commit", a_commit)) if not ok]
    if manque and avoue:
        return _v("benchmarks dates", ALIGNE,
                  [s[0] + " " + s[1] for s in scores],
                  "non date, mais l'absence est ECRITE",
                  "re-mesurer reste preferable a l'aveu")
    if manque:
        return _v("benchmarks dates", DIVERGE,
                  [s[0] + " " + s[1] for s in scores], "sans " + " ni ".join(manque),
                  "un score change avec le modele sans que le code bouge")
    return _v("benchmarks dates", ALIGNE, [s[0] + " " + s[1] for s in scores],
              "date et commit presents", "")


# Services declares MORTS par la doctrine (CLAUDE.md §8/§13). On ne SONDE pas le
# reseau ici : un port ferme peut etre un service a la demande (LM Studio, :8099
# reveille au besoin), et un controle qui crierait la-dessus serait desarme en une
# semaine. Seuls figurent ici les arrets DATES et documentes.
_PORTS_ARRETES = {
    "5557": "brain_worker — OOM ONNX BGE-M3, arrete le 2026-06-03 ; embedder LIVE = :8099",
    "8100": "NokidoLlamaReranker — boot-trim RAM, arrete le 2026-08-10",
    "7474": "NokidoGraphExplorer — boot-trim RAM, arrete le 2026-08-10",
}

# Un document est HONNETE s'il signale l'etat pres de la mention du port.
_SIGNAL_ARRET = re.compile(
    r"disabled|désactiv|desactiv|arrêté|arrete|OOM|deprecated|obsol|historique|"
    r"remplac|au profit|n'est plus|boot-trim|on-demand|à la demande|a la demande|"
    r"coupé|coupe\b|éteint|eteint", re.I)


def c_ports_docs(readme: str, pyproject: str) -> dict:
    """Un port ARRETE cite dans la doc doit etre cite comme arrete.

    Origine : audit AGY du 2026-08-30. Son extraction LLM a expire (timeout
    silencieux de `qwen2.5-coder:1.5b`) et son unique exemple etait FAUX --
    `ARCHITECTURE.md` porte deja l'avertissement qu'il lui reprochait d'omettre.
    Le fond, lui, tenait : d'autres documents citent bel et bien des ports morts
    sans le dire. Ce controle refait la mesure sans LLM, donc sans timeout.
    """
    docs = ROOT / "docs"
    if not docs.is_dir():
        return _v("ports arretes dans docs/", INDETERMINE, None, None, "docs/ absent")
    vus, illisibles, muets = 0, 0, {}
    for base, dn, fn in os.walk(docs):
        # `archive/` assume son statut, `i18n/` est derive du README.
        dn[:] = [d for d in dn if d not in ("archive", "i18n")]
        for f in fn:
            if not f.endswith(".md"):
                continue
            try:
                lignes = (Path(base) / f).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                illisibles += 1
                continue
            vus += 1
            rel = str((Path(base) / f).relative_to(ROOT)).replace("\\", "/")
            for port in _PORTS_ARRETES:
                hits = [i for i, l in enumerate(lignes) if (":" + port) in l]
                if not hits:
                    continue
                # fenetre de +-4 lignes autour de CHAQUE mention
                if not any(_SIGNAL_ARRET.search("\n".join(lignes[max(0, i - 4):i + 5]))
                           for i in hits):
                    muets.setdefault(port, []).append(rel)
    total = sum(len(v) for v in muets.values())
    mesure = "%d doc(s) muet(s) sur %d scanne(s), %d illisible(s)" % (total, vus, illisibles)
    if illisibles and not vus:
        return _v("ports arretes dans docs/", INDETERMINE, None, mesure,
                  "aucun document lisible : rien n'est prouve")
    if not total:
        return _v("ports arretes dans docs/", ALIGNE, sorted(_PORTS_ARRETES), mesure,
                  "chaque mention d'un port arrete signale son etat")
    detail = "; ".join("%s: %s%s" % (p, ", ".join(sorted(l)[:3]), " …" if len(l) > 3 else "")
                       for p, l in sorted(muets.items()))
    return _v("ports arretes dans docs/", DIVERGE, sorted(_PORTS_ARRETES), mesure,
              "cites comme vivants — " + detail)


CONTROLES = (
    ("nom du paquet pip", lambda r, p: c_nom_paquet(r, p)),
    ("commandes CLI", lambda r, p: c_entrypoints(r, p)),
    ("nombre d'extras", lambda r, p: c_extras(r, p)),
    ("taille du corpus RAG", lambda r, p: c_taille_corpus(r)),
    ("chemin d'embedding", lambda r, p: c_embedding(r)),
    ("scorecard", lambda r, p: c_scorecard(r)),
    ("/api/graph/proprioception", lambda r, p: c_proprioception(r)),
    ("fichier .env Docker", lambda r, p: c_env_docker(r)),
    ("providers", lambda r, p: c_providers(r)),
    ("cartouches de tete", lambda r, p: c_cartouches(r, p)),
    ("LNN sur NPU", lambda r, p: c_lnn_npu(r)),
    ("MCTS", lambda r, p: c_mcts(r)),
    ("promesses absolues", lambda r, p: c_absolus(r)),
    ("benchmarks dates", lambda r, p: c_benchmarks(r)),
    ("cibles des cartouches", lambda r, p: c_cibles_badges(r)),
    ("ports arretes dans docs/", lambda r, p: c_ports_docs(r, p)),
)


def auditer() -> dict:
    readme = _lire("README.md")
    pyproject = _lire("pyproject.toml")
    if readme is None:
        return {"ARRET": "README.md illisible", "resultats": []}
    res = []
    for nom, fn in CONTROLES:
        try:
            res.append(fn(readme, pyproject or ""))
        except Exception as exc:  # noqa: BLE001
            # Un controle qui casse est INDETERMINE, jamais ALIGNE : sinon une
            # exception se lirait comme une declaration verifiee.
            res.append(_v(nom, INDETERMINE, None, None,
                          "controle en echec : %s" % type(exc).__name__))
    compte = {ALIGNE: 0, DIVERGE: 0, INDETERMINE: 0}
    for r in res:
        compte[r["statut"]] += 1
    return {"resultats": res, "compte": compte}


def main() -> int:
    ap = argparse.ArgumentParser(description="README declare, code decide")
    ap.add_argument("--json", action="store_true", help="sortie machine")
    a = ap.parse_args()
    rapport = auditer()
    if a.json:
        print(json.dumps(rapport, ensure_ascii=False, indent=1))
    else:
        if "ARRET" in rapport:
            print("ARRET :", rapport["ARRET"])
            return 2
        largeur = max(len(r["controle"]) for r in rapport["resultats"])
        for r in rapport["resultats"]:
            print("%-*s  %-12s  declare=%s | mesure=%s%s" % (
                largeur, r["controle"], r["statut"], r["declare"], r["mesure"],
                "  <- " + r["note"] if r["note"] else ""))
        c = rapport["compte"]
        print("\n%d aligne(s) - %d divergence(s) - %d non mesure(s)"
              % (c[ALIGNE], c[DIVERGE], c[INDETERMINE]))
        if c[INDETERMINE]:
            print("Les NON MESURES ne comptent pas comme alignes : un controle "
                  "qui ne mesure rien ne prouve rien.")
    return 1 if rapport.get("compte", {}).get(DIVERGE) else 0


if __name__ == "__main__":
    sys.exit(main())
