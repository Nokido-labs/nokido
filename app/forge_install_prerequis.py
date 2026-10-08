"""forge_install_prerequis.py — registre des prerequis EXTERNES de Nokido, et sonde de presence.

POURQUOI (mesure 2026-09-19). La chaine de publication prouve qu'un paquet
`nokido-agent` s'INSTALLE et s'IMPORTE sur linux/windows/macos (job
`verify-testpypi`). Elle ne dit rien de ce dont Nokido a besoin AUTOUR de lui :
92 services declares dans `proxy_deno/core/services.toml` s'appuient sur des
binaires tiers (deno, ollama, llama-server, docker, caddy, veracrypt...) que la
wheel ne peut pas embarquer — licences, poids, builds par plateforme. Un
contributeur qui installe le dist ne lisait donc NULLE PART ce qui lui manque.

CE QUE CE MODULE FAIT, ET CE QU'IL NE FAIT PAS.

    INSTALLE  !=  DEMARRE  !=  CAPABLE

Il repond a la PREMIERE question seulement : le binaire est-il sur cette
machine ? Il ne demarre rien, n'ouvre aucun port, ne charge aucun modele. Un
`ollama.exe` present ne prouve pas qu'un runner tourne (mesure 2026-09-07 :
`/api/tags` listait 16 modeles pour zero runner). La vivacite est le travail de
`nokido_ensure_service` et de `forge_organ_agents.probe()` ; les confondre
fabriquerait un faux vert de plus.

TROIS ETATS, JAMAIS UN BOOLEEN. `PRESENT` / `ABSENT` / `ILLISIBLE`. Un capteur
qui rend `False` pour « pas la » ET pour « je n'ai pas pu regarder » fabrique des
faux negatifs indetectables (constitution semantique : `UNKNOWN != NO`). Quand
la sonde elle-meme echoue — PATH inaccessible, `shutil.which` qui leve — l'etat
est `ILLISIBLE` et porte son motif.

ANTI-PEREMPTION. Le registre ci-dessous est ecrit a la main, donc il se perimera
des qu'un service neuf arrivera avec un binaire neuf. C'est pour cela que
`exes_declares_dans_services()` re-DERIVE la surface depuis le TOML : le NR
`test_prerequis_surface_complete_nr` compare les deux et echoue si un executable
declare n'a aucune entree ici. Le registre ne se maintient pas par discipline,
il se maintient par cliquet.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

__FORGE_COLOR__ = "infra/bootstrap : registre des prerequis externes et sonde de presence a trois etats"

ROOT = Path(__file__).resolve().parents[1]
SERVICES_TOML = ROOT / "proxy_deno" / "core" / "services.toml"

# --- vocabulaire ------------------------------------------------------------
PRESENT = "PRESENT"
ABSENT = "ABSENT"
ILLISIBLE = "ILLISIBLE"

REQUIS = "REQUIS"          # sans lui, rien ne tourne
ESSENTIEL = "ESSENTIEL"    # porte un service marque `essential` dans le TOML
OPTIONNEL = "OPTIONNEL"    # une capacite s'eteint, le reste vit

# --- registre ---------------------------------------------------------------
# `binaires` : noms cherches dans le PATH, dans l'ordre (le premier trouve gagne).
# `absent_alors` : ce qui s'eteint EXACTEMENT. Jamais « ca ne marchera pas ».
PREREQUIS: tuple[dict, ...] = (
    {
        "cle": "python",
        "binaires": (),  # sonde dediee : c'est l'interpreteur courant
        "niveau": REQUIS,
        "capacite": "76 des 92 services declares, et le paquet lui-meme",
        "absent_alors": "rien ne demarre",
        "install": {"*": "python.org, pyenv, ou conda/miniforge — 3.12 minimum"},
    },
    {
        "cle": "git",
        "binaires": ("git",),
        "niveau": REQUIS,
        "capacite": "versionnement, gate d'egress, publication, 268 appels dans le code",
        "absent_alors": "toute la chaine de publication et les gates de commit",
        "install": {"windows": "winget install Git.Git", "linux": "apt install git",
                    "macos": "brew install git"},
    },
    {
        "cle": "deno",
        "binaires": ("deno",),
        "niveau": ESSENTIEL,
        "capacite": "systeme nerveux TypeScript : webhub :7401, proxy :8000, netcfg :8767",
        "absent_alors": "le webhub et les proxies ne demarrent pas (3 services essentiels)",
        "install": {"windows": "irm https://deno.land/install.ps1 | iex",
                    "*": "curl -fsSL https://deno.land/install.sh | sh"},
        # L'installeur officiel pose Deno dans ~/.deno/bin, mais n'ajoute ce dossier au PATH qu'aux NOUVEAUX
        # terminaux : sur runner Windows, doctor le declarait absent juste apres l'installation (07/10).
        "chemins_usuels": (str(Path.home() / ".deno" / "bin" / "deno.exe"),
                           str(Path.home() / ".deno" / "bin" / "deno")),
    },
    {
        "cle": "ollama",
        "binaires": ("ollama",),
        "niveau": ESSENTIEL,
        "capacite": "inference LLM locale :11434 (service NokidoOllama, marque essential)",
        "absent_alors": "plus d'inference locale par defaut ; la cascade retombe sur "
                        "llama-server ou sur un provider distant s'il est configure",
        "install": {"*": "https://ollama.com/download — puis un modele adapte a la machine : `nokido-doctor --modeles`"},
    },
    {
        "cle": "llama_server",
        "binaires": ("llama-server", "llama-server.exe"),
        "niveau": OPTIONNEL,
        "capacite": "backends llama.cpp : natif :8091, embeddings :8099, reranker, bitnet, router",
        "absent_alors": "embeddings et reranking locaux ; l'ingestion RAG retombe sur "
                        "un embedder distant ou reste en attente",
        "install": {"*": "build CPU epinglee (llama.cpp b11461, sha256 dans distribution/packs/local-llm.toml) a "
                         "extraire dans runtime/llama/ ; une build GPU se prend sur "
                         "https://github.com/ggml-org/llama.cpp/releases selon la carte"},
        # Emplacement STANDARD d'une installation Nokido (2026-10-07) : le test d'installation y extrait la build
        # epinglee, doctor l'y cherche. Avant, un llama-server installe hors PATH etait annonce absent.
        "chemins_usuels": (str(ROOT / "runtime" / "llama" / "llama-server.exe"),
                           str(ROOT / "runtime" / "llama" / "llama-server"),
                           str(ROOT / "runtime" / "llama" / "build" / "bin" / "llama-server")),
    },
    {
        "cle": "lmstudio",
        "binaires": ("lms", "lms.cmd", "lms.exe"),
        "niveau": OPTIONNEL,
        "capacite": "LM Studio en serveur local :1234",
        "absent_alors": "un backend d'inference alternatif, rien d'autre",
        "install": {"*": "https://lmstudio.ai/ — le CLI `lms` est fourni avec l'application"},
    },
    {
        "cle": "docker",
        "binaires": ("docker",),
        "niveau": OPTIONNEL,
        "capacite": "prothese de conteneurs : SearXNG, Qdrant, bacs d'execution isoles",
        "absent_alors": "la recherche web locale et le vecteur Qdrant ; "
                        "Docker est une prothese, pas un organe — eteint n'est pas en panne",
        "install": {"*": "https://docs.docker.com/get-docker/ — 24+ "},
    },
    {
        "cle": "caddy",
        "binaires": ("caddy",),
        "niveau": OPTIONNEL,
        "capacite": "terminaison TLS :8443 (service NokidoCaddyTLS)",
        "absent_alors": "l'acces HTTPS ; le loopback en clair continue de fonctionner",
        "install": {"*": "https://caddyserver.com/docs/install"},
    },
    {
        "cle": "chiffrement_at_rest",
        "binaires": ("veracrypt", "cryptsetup"),
        "niveau": OPTIONNEL,
        "capacite": "chiffrement at-rest du volume de donnees, cross-OS "
                    "(VeraCrypt sur windows/macos, LUKS via cryptsetup sur linux) — "
                    "cf. tools/forge_at_rest_veracrypt.py",
        "absent_alors": "les bases restent EN CLAIR sur le disque ; "
                        "le montage au demarrage et l'agrandissement de conteneur",
        "chemins_usuels": (r"C:\Program Files\VeraCrypt\VeraCrypt.exe",
                           "/usr/bin/veracrypt", "/usr/sbin/cryptsetup",
                           "/Applications/VeraCrypt.app/Contents/MacOS/VeraCrypt"),
        "install": {"windows": "winget install IDRIX.VeraCrypt",
                    "linux": "apt install cryptsetup  (ou veracrypt)",
                    "macos": "brew install --cask veracrypt"},
    },
    {
        "cle": "netcfg_agent",
        "binaires": (),  # sonde dediee : c'est un DEPOT voisin, pas un binaire
        "niveau": ESSENTIEL,
        "capacite": "NokidoNetcfgMCP :8768 — service marque essential, dont le cwd "
                    "pointe HORS du depot (${NETCFG_DIR})",
        "absent_alors": "le MCP netcfg ne demarre pas ; c'est un depot separe, "
                        "il n'est donc PAS livre avec le paquet nokido-agent",
        "install": {"*": "cloner netcfg-agent-mcp a cote du depot Nokido, "
                         "ou pointer ${NETCFG_DIR} vers son emplacement"},
    },
    {
        "cle": "toolchain_rust",
        "binaires": ("cargo",),
        "niveau": OPTIONNEL,
        "capacite": "compilation de forge_brain_worker.exe (service NokidoBrainWorkerRust)",
        "absent_alors": "ce binaire ne peut pas etre reconstruit ; s'il est deja "
                        "compile et present, rien ne change",
        "install": {"*": "https://rustup.rs/"},
    },
    {
        "cle": "toolchain_go",
        "binaires": ("go",),
        "niveau": OPTIONNEL,
        "capacite": "compilation de forge_dispatcher.exe (service NokidoGoDispatcher, :8779)",
        "absent_alors": "ce binaire ne peut pas etre reconstruit ; s'il est deja "
                        "compile et present, rien ne change",
        "install": {"*": "https://go.dev/dl/"},
    },
    {
        "cle": "node",
        "binaires": ("node",),
        "niveau": OPTIONNEL,
        "capacite": "serveurs MCP tiers lances par npx (browser-control, etc.)",
        "absent_alors": "les MCP tiers en JavaScript",
        "install": {"*": "https://nodejs.org/ — LTS"},
    },
    {
        "cle": "npx",
        "binaires": ("npx",),
        "niveau": OPTIONNEL,
        "capacite": "lancement des serveurs MCP publies sur npm",
        "absent_alors": "idem node : les MCP tiers JavaScript",
        "install": {"*": "fourni avec Node.js"},
    },
    {
        "cle": "uv",
        "binaires": ("uv", "uvx"),
        "niveau": OPTIONNEL,
        "capacite": "resolution rapide d'environnements Python, build des artefacts de release",
        "absent_alors": "le build local de la wheel ; pip reste utilisable",
        "install": {"*": "https://docs.astral.sh/uv/"},
    },
    {
        "cle": "ripgrep",
        "binaires": ("rg",),
        "niveau": OPTIONNEL,
        "capacite": "recherche plein texte rapide dans le depot",
        "absent_alors": "un repli plus lent en Python",
        "install": {"*": "https://github.com/BurntSushi/ripgrep#installation"},
    },
    {
        "cle": "ffmpeg",
        "binaires": ("ffmpeg",),
        "niveau": OPTIONNEL,
        "capacite": "transcodage audio/video a l'ingestion",
        "absent_alors": "l'ingestion des medias ; le texte n'est pas concerne",
        "install": {"*": "https://ffmpeg.org/download.html"},
    },
    {
        "cle": "audit_securite",
        "binaires": ("semgrep", "gitleaks", "opa"),
        "niveau": OPTIONNEL,
        "capacite": "gates d'audit : analyse statique, detection de secrets, politiques",
        "absent_alors": "ces gates rendent ILLISIBLE et NON 'aucun probleme' — "
                        "un outil introuvable qui sort une chaine vide se lit a tort "
                        "comme « 0 erreur » (mesure 2026-07-30 sur deno lint)",
        "install": {"*": "semgrep : pip install semgrep — gitleaks/opa : binaires GitHub"},
    },
    {
        "cle": "profilage",
        "binaires": ("py-spy",),
        "niveau": OPTIONNEL,
        "capacite": "profilage d'un process Python vivant",
        "absent_alors": "le diagnostic de contention CPU",
        "install": {"*": "pip install py-spy"},
    },
    {
        "cle": "gpu_nvidia",
        "binaires": ("nvidia-smi",),
        "niveau": OPTIONNEL,
        "capacite": "detection GPU NVIDIA (VRAM, charge) pour le placement des modeles",
        "absent_alors": "le placement retombe sur le CPU ; sur machine AMD, voir `gpu_amd`",
        "install": {"*": "fourni avec le pilote NVIDIA"},
    },
    {
        "cle": "gpu_amd",
        "binaires": ("amduprofcli",),
        "niveau": OPTIONNEL,
        "capacite": "compteurs AMD uProf (APU/iGPU)",
        "absent_alors": "les compteurs AMD fins ; la detection generique subsiste",
        "install": {"*": "AMD uProf"},
    },
    {
        "cle": "superviseur_windows",
        "binaires": ("nssm",),
        "niveau": OPTIONNEL,
        "plateformes": ("win32",),
        "capacite": "declaration des services Windows (les 92 services du TOML)",
        "absent_alors": "les services ne s'installent pas en services Windows ; "
                        "le lancement manuel reste possible",
        "install": {"windows": "https://nssm.cc/download"},
    },
    {
        "cle": "superviseur_linux",
        "binaires": ("systemctl",),
        "niveau": OPTIONNEL,
        "plateformes": ("linux",),
        "capacite": "equivalent systemd des services",
        "absent_alors": "idem : lancement manuel",
        "install": {"linux": "fourni par systemd"},
    },
    {
        "cle": "superviseur_macos",
        "binaires": ("launchctl",),
        "niveau": OPTIONNEL,
        "plateformes": ("darwin",),
        "capacite": "equivalent launchd des services",
        "absent_alors": "idem : lancement manuel",
        "install": {"macos": "fourni avec macOS"},
    },
)

# Images de conteneurs declarees par les fichiers compose. Une capacite peut
# arriver par une IMAGE plutot que par un binaire du PATH — c'est le cas de
# SearXNG et de crawl4ai, qui n'existent nulle part comme executable et qu'une
# sonde `which` declarerait donc absents a tort. Elles sont DECLAREES ici, pas
# sondees : interroger le demon Docker demanderait de lancer un process, et
# `INSTALLE != DEMARRE` vaut aussi pour lui.
COMPOSE_FICHIERS = (
    "docker/nokido/docker-compose.yml",
    "docker-compose.yml",
    "docker-compose.crawl4ai.yml",
)

# (image, origine, capacite) — origine : "tierce" (tiree d'un registre public)
# ou "construite" (batie depuis ce depot ou un depot voisin).
IMAGES_DOCKER_ATTENDUES: tuple[tuple[str, str, str], ...] = (
    ("ollama/ollama:latest", "tierce", "inference locale en conteneur"),
    ("searxng/searxng:latest", "tierce", "recherche web locale — aucun binaire equivalent"),
    ("unclecode/crawl4ai:latest", "tierce", "crawl web — conteneurise, jamais un binaire"),
    ("denoland/deno:alpine", "tierce", "runtime TypeScript en conteneur"),
    ("adminer:latest", "tierce", "inspection de base, profil dev"),
    ("nokido:latest", "construite", "image principale, batie depuis ce depot"),
    ("nokido:${BUILD_VARIANT:-hub}", "construite", "variante d'image selectionnee au build"),
    ("laforge-ml:latest", "construite", "variante ML (torch/faiss), batie localement"),
    ("netcfg-agent-mcp:latest", "construite", "batie depuis le depot VOISIN netcfg-agent-mcp"),
)


# Modeles de poids attendus par les services llama-server. Ils ne sont dans
# aucun paquet : ils se telechargent. Chemins relatifs a ROOT.
MODELES_ATTENDUS: tuple[tuple[str, str], ...] = (
    ("data/llm_models/bge-m3-Q8_0.gguf", "embeddings :8099"),
    ("data/llm_models/bge-reranker-v2-m3-Q8_0.gguf", "reranking"),
    ("data/llm_models/bitnet_b1_58.gguf", "backend bitnet"),
)


def _plateforme_concernee(entree: dict) -> bool:
    """Une entree limitee a d'autres OS n'est ni presente ni absente : hors sujet."""
    plats = entree.get("plateformes")
    return True if not plats else sys.platform in plats


_CACHE_VARS: dict | None = None
_ETAT_TOML: str = ILLISIBLE


def _vars_du_toml() -> dict:
    """Chemins ABSOLUS que le TOML des services declare pour les binaires tiers.

    Necessaire, et mesure le 2026-09-19 : `deno` et `ollama` TOURNAIENT sur la
    machine de reference pendant que la sonde les rendait `ABSENT`, parce que le
    TOML les lance par chemin absolu (`C:/.../deno.exe`) et qu'ils ne sont pas
    dans le PATH. Chercher dans le seul PATH revient a mesurer « present dans
    MON environnement » en affirmant « installe sur la machine » — deux objets
    differents. Un doctor qui crie a faux se fait desarmer.
    """
    global _CACHE_VARS, _ETAT_TOML
    if _CACHE_VARS is None:
        try:
            import tomllib
            with open(SERVICES_TOML, "rb") as f:
                _CACHE_VARS = tomllib.load(f).get("vars", {})
            _ETAT_TOML = PRESENT
        except FileNotFoundError:
            # Cas NORMAL depuis une installation par paquet : `proxy_deno/` n'est
            # pas dans la wheel. Ce n'est pas une panne, mais ca doit se DIRE :
            # sans le TOML, la sonde perd la voie « chemin declare » et ne voit
            # plus que le PATH. Un rapport muet la-dessus ferait passer des
            # binaires installes hors PATH pour absents.
            _CACHE_VARS, _ETAT_TOML = {}, ABSENT
        except Exception as e:
            _CACHE_VARS, _ETAT_TOML = {}, "%s: %s" % (ILLISIBLE, type(e).__name__)
    return _CACHE_VARS


def etat_toml_services() -> str:
    """PRESENT / ABSENT / ILLISIBLE pour la declaration des services elle-meme."""
    _vars_du_toml()
    return _ETAT_TOML


def _verdict_chemin(p: Path) -> str:
    """PRESENT / ABSENT / ILLISIBLE pour un chemin, sans jamais confondre les deux derniers.

    Mesure 2026-09-19 : sous le compte de service (`LaForgeSbxOffline`),
    `Path.is_file()` rend `False` pour `deno.exe` et `ollama.exe` — deux binaires
    qui TOURNENT — parce que leur dossier vit dans le profil de l'owner, hors
    ACL. Rendre `ABSENT` la aurait invente deux pannes et envoye reinstaller ce
    qui est deja installe.

    Ce qui discrimine, c'est la LISTABILITE du parent (patron du 2026-09-05,
    `forge_log_surface`) : parent listable et fichier absent = `ABSENT` ; parent
    illisible = `ILLISIBLE`, on n'a pas pu regarder. `FileNotFoundError` sur le
    parent est bien une absence, pas un refus.
    """
    try:
        if p.is_file():
            return PRESENT
    except OSError:
        return ILLISIBLE
    try:
        next(p.parent.iterdir(), None)
        return ABSENT
    except (FileNotFoundError, NotADirectoryError):
        return ABSENT
    except OSError:
        return ILLISIBLE


def _sonde_binaire(noms: tuple[str, ...], usuels: tuple[str, ...] = ()) -> tuple[str, str]:
    """Cherche le binaire par trois voies, et DIT par laquelle il l'a trouve.

    1. le PATH ; 2. les chemins absolus declares dans `[vars]` du TOML ;
    3. les emplacements d'installation usuels de l'entree.

    La voie compte : « trouve hors PATH » signifie qu'un lancement a la main
    echouera la ou le superviseur reussit. Rend `(etat, detail)` ; `ILLISIBLE`
    quand la sonde n'a pas pu regarder — ce n'est PAS une absence.
    """
    if not noms:
        return ILLISIBLE, "aucun binaire a chercher"
    cibles = {n.lower() for n in noms} | {n.lower() + ".exe" for n in noms}
    try:
        for n in noms:
            trouve = shutil.which(n)
            if trouve:
                return PRESENT, "PATH: " + trouve
        vus_illisibles = []
        for val in _vars_du_toml().values():
            s = str(val)
            if os.path.basename(s).lower() not in cibles:
                continue
            v = _verdict_chemin(Path(s))
            if v == PRESENT:
                return PRESENT, "hors PATH, chemin declare au TOML: " + s
            if v == ILLISIBLE:
                vus_illisibles.append(s)
        for cand in usuels:
            v = _verdict_chemin(Path(cand))
            if v == PRESENT:
                return PRESENT, "hors PATH, emplacement usuel: " + cand
            if v == ILLISIBLE:
                vus_illisibles.append(cand)
    except Exception as e:  # PATH illisible, ACL, encodage
        return ILLISIBLE, "sonde en echec: %s: %s" % (type(e).__name__, e)
    if not os.environ.get("PATH"):
        return ILLISIBLE, "PATH vide ou absent — impossible de conclure"
    if vus_illisibles:
        return ILLISIBLE, ("chemin declare mais NON VERIFIABLE sous le compte %s "
                           "(dossier hors ACL) : %s" % (_compte(), vus_illisibles[0]))
    return ABSENT, "ni PATH, ni chemin declare, ni emplacement usuel: " + ", ".join(noms)


def _sonde_python() -> tuple[str, str]:
    v = sys.version_info
    detail = "%d.%d.%d (%s)" % (v.major, v.minor, v.micro, sys.executable)
    if (v.major, v.minor) < (3, 12):
        return ABSENT, "3.12 minimum requis, trouve " + detail
    return PRESENT, detail


def verifier(inclure_optionnels: bool = True) -> list[dict]:
    """Etat de chaque prerequis. Aucun process lance, aucun port ouvert."""
    out = []
    for e in PREREQUIS:
        if not inclure_optionnels and e["niveau"] == OPTIONNEL:
            continue
        if not _plateforme_concernee(e):
            continue
        if e["cle"] == "python":
            etat, detail = _sonde_python()
        elif e["cle"] == "netcfg_agent":
            etat, detail = _sonde_dossier_netcfg()
        else:
            etat, detail = _sonde_binaire(e["binaires"], e.get("chemins_usuels", ()))
        out.append({
            "cle": e["cle"], "niveau": e["niveau"], "etat": etat, "detail": detail,
            "capacite": e["capacite"], "absent_alors": e["absent_alors"],
            "install": e["install"].get(_cle_os(), e["install"].get("*", "")),
        })
    return out


def _compte() -> str:
    """Un constat NOMME son environnement : sans le compte, un verdict local se
    lit comme un verdict systeme — et c'est le compte le plus faible qui parle."""
    return os.environ.get("USERNAME") or os.environ.get("USER") or "inconnu"


def _cle_os() -> str:
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def _sonde_dossier_netcfg() -> tuple[str, str]:
    """Le depot voisin netcfg-agent-mcp, designe par ${NETCFG_DIR} au TOML.

    Ce n'est pas un binaire : c'est une arborescence Python lancee en `-m`. Une
    variable non declaree rend ILLISIBLE, pas ABSENT — on ne sait alors meme pas
    ou regarder.
    """
    d = _vars_du_toml().get("NETCFG_DIR")
    if not d:
        return ILLISIBLE, "${NETCFG_DIR} non declare au TOML — rien a verifier"
    try:
        p = Path(str(d))
        if p.is_dir():
            return PRESENT, str(p)
        return ABSENT, "depot voisin introuvable: " + str(p)
    except OSError as e:
        return ILLISIBLE, "%s: %s" % (type(e).__name__, e)


def epinglages_modeles() -> dict:
    """{nom de fichier: {url, sha256, taille, licence}} des modeles EPINGLES dans distribution/packs/local-llm.toml.

    Source unique des liens de telechargement (2026-10-07) : doctor ne recopie aucune URL, il lit le manifeste que
    le test d'installation sur runners vierges utilise aussi. Manifeste illisible (installation par paquet sans
    `distribution/`) : dict vide, et la ligne du modele le DIT au lieu d'inventer un lien.
    """
    import tomllib
    try:
        with open(ROOT / "distribution" / "packs" / "local-llm.toml", "rb") as fh:
            composants = tomllib.load(fh).get("composant", [])
    except (OSError, tomllib.TOMLDecodeError):  # muet-ok : vide = « epinglage illisible », dit par verifier_modeles
        return {}
    return {c["id"]: {k: c.get(k) for k in ("url", "sha256", "taille", "licence")}
            for c in composants if c.get("source") == "url" and str(c.get("id", "")).endswith(".gguf")}


def verifier_modeles() -> list[dict]:
    """Presence des poids GGUF. Absents = a telecharger, jamais une panne : chaque ligne dit OU les prendre."""
    out = []
    pins = epinglages_modeles()
    for rel, usage in MODELES_ATTENDUS:
        p = ROOT / rel
        etat = _verdict_chemin(p)
        try:
            detail = ("%.1f Go" % (p.stat().st_size / 1e9)) if etat == PRESENT else str(p)
        except OSError as e:
            detail = "%s: %s" % (type(e).__name__, e)
        pin = pins.get(Path(rel).name)
        telecharger = ("%s (sha256 %s, %s)" % (pin["url"], pin["sha256"], pin["licence"]) if pin
                       else "NON EPINGLE dans distribution/packs/local-llm.toml : source et somme a etablir")
        out.append({"cle": rel, "usage": usage, "etat": etat, "detail": detail, "telecharger": telecharger})
    return out


def commande_image(image: str, origine: str, par_image: dict | None = None) -> str:
    """Comment OBTENIR une image : une image tierce se tire, une image construite se batit depuis le compose qui la
    declare (sinon on le DIT : elle vient d'ailleurs, p. ex. du depot voisin netcfg-agent-mcp)."""
    if origine == "tierce":
        return "docker pull %s" % image
    fichiers = (par_image or {}).get(image) or []
    if fichiers:
        return "docker compose -f %s build" % fichiers[0]
    return "construite hors des fichiers compose de ce depot : voir sa capacite"


def exes_declares_dans_services() -> dict[str, list[str]]:
    """Re-DERIVE la surface d'executables depuis le TOML des services.

    C'est la source qui fait autorite, pas le registre ci-dessus. Le NR compare
    les deux : un service neuf apportant un binaire neuf casse le test tant que
    `PREREQUIS` ne le couvre pas. Leve si le TOML est illisible — un inventaire
    qui se tait n'est pas un inventaire vide.
    """
    import tomllib
    with open(SERVICES_TOML, "rb") as f:
        d = tomllib.load(f)
    variables = d.get("vars", {})
    par_exe: dict[str, list[str]] = {}
    for s in d.get("service", []):
        brut = s.get("cmd") or s.get("startCmd") or ""
        if isinstance(brut, list):
            brut = " ".join(str(x) for x in brut)
        brut = str(brut)
        for k, val in variables.items():
            brut = brut.replace("${%s}" % k, str(val))
        brut = brut.strip().strip('"')
        if not brut:
            continue
        exe = os.path.basename(brut.split()[0] if " " in brut else brut).lower()
        par_exe.setdefault(exe, []).append(s.get("name", "?"))
    return par_exe


# Executables du TOML qui n'ont PAS a figurer au registre des prerequis tiers :
# l'interpreteur et le shell de l'hote d'une part, les binaires que le depot
# PRODUIT lui-meme d'autre part (leurs toolchains, elles, sont au registre).
EXES_NON_TIERS = frozenset({
    "python.exe", "python", "cmd.exe",
    "forge_brain_worker.exe", "forge_dispatcher.exe",
})


def exes_non_couverts() -> dict[str, list[str]]:
    """Executables declares au TOML qu'aucune entree de `PREREQUIS` ne couvre.

    C'est le CLIQUET du registre. Il est ecrit a la main, donc il se perimerait
    au premier service neuf apportant un binaire neuf ; le NR appelle cette
    fonction et echoue tant que le trou n'est pas comble. Le registre ne tient
    pas par la discipline de celui qui edite le TOML, il tient par ce test.
    """
    couvert = set(EXES_NON_TIERS)
    for e in PREREQUIS:
        for n in e["binaires"]:
            couvert.add(n.lower())
            couvert.add(n.lower() + ".exe")
    return {k: v for k, v in exes_declares_dans_services().items() if k not in couvert}


def images_declarees_dans_compose() -> dict[str, list[str]]:
    """Re-DERIVE les images depuis les fichiers compose. Autorite, comme le TOML.

    Leve si AUCUN fichier compose n'est lisible : sans eux, l'inventaire est
    inconnu, pas vide.
    """
    import re as _re
    par_image: dict[str, list[str]] = {}
    lus: list[str] = []
    illisibles: list[str] = []
    for rel in COMPOSE_FICHIERS:
        p = ROOT / rel
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:  # muet-ok : un compose optionnel absent est normal
            continue
        except OSError as e:
            # ACL, verrou, encodage : le fichier EXISTE et on ne l'a pas lu. Le
            # taire ferait passer un inventaire partiel pour un inventaire
            # complet — un filtre qui ecarte des donnees le DIT.
            illisibles.append("%s (%s)" % (rel, type(e).__name__))
            continue
        lus.append(rel)
        for m in _re.findall(r"^\s*image:\s*([^\s#]+)", txt, _re.M):
            par_image.setdefault(m.strip("\"'"), []).append(rel)
    if not lus:
        raise FileNotFoundError(
            "aucun fichier compose lisible parmi %s — inventaire INCONNU, pas vide"
            " (illisibles: %s)" % (COMPOSE_FICHIERS, illisibles or "aucun"))
    if illisibles:
        raise OSError(
            "inventaire d'images PARTIEL : %d/%d compose lus, non lus = %s. "
            "Conclure sur cette base surestimerait la couverture."
            % (len(lus), len(COMPOSE_FICHIERS), illisibles))
    return par_image


def images_non_couvertes() -> dict[str, list[str]]:
    """Images declarees par un compose qu'aucune entree ne documente. Cliquet."""
    connues = {i for i, _, _ in IMAGES_DOCKER_ATTENDUES}
    return {k: v for k, v in images_declarees_dans_compose().items() if k not in connues}


# Profils d'installation (decision owner du 2026-10-07). Ce qu'une installation EXIGE depend de l'offre servie :
#   dev     : l'offre « hub d'agents pour devs » -- Python, Git, Deno, llama-server et le modele bge-m3 (vecteurs du
#             Knowledge Pack). Ollama et netcfg-agent sont SIGNALES, jamais bloquants.
#   complet : l'organisme du poste de reference -- REQUIS + ESSENTIEL (services `essential` du TOML), comme avant.
# Une cle absente d'un profil reste listee et signalee : le profil change ce qui BLOQUE, pas ce qui se voit.
PROFILS = {
    "dev": {"prerequis": {"python", "git", "deno", "llama_server"},
            "modeles": {"data/llm_models/bge-m3-Q8_0.gguf"}},
    "complet": {"prerequis": None, "modeles": set()},
}


def bilan(inclure_optionnels: bool = True, profil: str = "complet") -> dict:
    """Agregat. Classe par liste BLANCHE : n'est sain que ce qui est PROUVE present."""
    if profil not in PROFILS:
        raise ValueError("profil inconnu %r (connus : %s)" % (profil, sorted(PROFILS)))
    lignes = verifier(inclure_optionnels)
    critique = (REQUIS, ESSENTIEL)
    exiges = PROFILS[profil]["prerequis"]

    def _bloque(l):
        return l["cle"] in exiges if exiges is not None else l["niveau"] in critique

    # Deux listes, jamais une. Classer un ILLISIBLE parmi les manquants
    # inventerait une panne ; le classer parmi les sains masquerait un trou.
    # La liste BLANCHE reste la regle (n'est sain que ce qui est PROUVE present),
    # mais un doute se nomme « indetermine », pas « bloquant ».
    manquants = [l for l in lignes if l["etat"] == ABSENT and _bloque(l)]
    indetermines = [l for l in lignes if l["etat"] == ILLISIBLE]
    modeles = verifier_modeles()
    try:
        par_image = images_declarees_dans_compose()
    except OSError:  # muet-ok : inventaire compose illisible -> commande_image le dit ligne par ligne
        par_image = {}
    modeles_manquants = ["modele:" + Path(m["cle"]).name for m in modeles
                         if m["cle"] in PROFILS[profil]["modeles"] and m["etat"] == ABSENT]
    return {
        "profil": profil,
        "os": _cle_os(),
        "compte": _compte(),
        "toml_services": etat_toml_services(),
        "toml_chemin": str(SERVICES_TOML),
        "total": len(lignes),
        "present": sum(1 for l in lignes if l["etat"] == PRESENT),
        "absent": sum(1 for l in lignes if l["etat"] == ABSENT),
        "illisible": len(indetermines),
        "bloquants": [l["cle"] for l in manquants] + modeles_manquants,
        "indetermines_critiques": [l["cle"] for l in indetermines if _bloque(l)],
        "lignes": lignes,
        "modeles": modeles,
        "images": [{"image": i, "origine": o, "capacite": c, "obtenir": commande_image(i, o, par_image)}
                   for i, o, c in IMAGES_DOCKER_ATTENDUES],
        "fichier_env": _etat_fichier_env(),
    }


def _etat_fichier_env() -> dict:
    """`Nokido.env` se copie depuis `Nokido.env.example` : son absence est une
    etape d'installation oubliee, pas une panne — et elle se DIT."""
    reel, gabarit = ROOT / "Nokido.env", ROOT / "Nokido.env.example"
    return {"fichier": "Nokido.env", "etat": _verdict_chemin(reel),
            "gabarit": _verdict_chemin(gabarit)}
