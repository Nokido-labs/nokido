# -*- coding: utf-8 -*-
"""forge_scalene_optimize.py — l'optimisation IA de scalene, EN CLI SOUVERAIN.

Scalene propose des optimisations, mais UNIQUEMENT dans son rapport HTML (le JS
`scalene-gui/ollama.js` appelle Ollama depuis le navigateur). Pas de navigateur
= pas de suggestion, et le `file://` bute sur le CORS. Cet outil reproduit le
workflow ENTIER en ligne de commande :

  1. lance `scalene --json` sur la cible -> profil ligne-a-ligne ;
  2. classe les lignes par cout (CPU python + natif + memoire) ;
  3. pour chaque ligne chaude, envoie la region a TON Ollama local
     (meme endpoint /api/chat, meme system prompt que ollala.js) ;
  4. imprime la suggestion dans le terminal.

Zero navigateur, zero CORS, zero egress (Ollama = localhost:11434).

    run action=trusted_script path=tools/forge_scalene_optimize.py \
        script_args="C:/chemin/script.py --model qwen2.5-coder:7b-instruct-q4_K_M --top 3"
"""

__FORGE_COLOR__ = "qualite/profiling : optimisation scalene en CLI souverain"  # organe declare le 2026-09-06 (audit de raccordement)
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

_SYSTEM = "You are an expert code assistant who only responds in Python code."


def _extraire(txt: str) -> dict | None:
    """Premier objet JSON portant 'files' dans un flux (stdout melange)."""
    dec = json.JSONDecoder()
    for i, ch in enumerate(txt or ""):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(txt[i:])
        except ValueError:
            continue
        if isinstance(obj, dict) and "files" in obj:
            return obj
    return None


def _profil_scalene(python: str, script: str, timeout: int, script_args: str = "") -> dict:
    """Lance scalene --json et rend le profil.

    ⚠️ Deux pieges mesures le 2026-08-19 : (1) `--cli` ecrase `--json` (table au
    lieu de JSON) ; (2) scalene ecrit un `profile.json` dans son CWD, et sous un
    compte a HOME invalide il n'ecrit RIEN d'exploitable. On force donc un HOME et
    un CWD INSCRIPTIBLES pour le sous-processus, on lit le `profile.json` produit,
    et a defaut on retombe sur stdout. Si tout echoue -> message clair vers
    `--from-json` (l'owner genere le profil dans sa vraie session).
    """
    import tempfile

    # cwd va changer -> le script DOIT etre absolu, sinon scalene le cherche dans
    # le tempdir (mesure 2026-08-19 : "could not find input file .../tmp/.../tools/...").
    script = os.path.abspath(script)
    work = tempfile.mkdtemp(prefix="scalene_opt_")
    env = dict(os.environ)
    for k in ("HOME", "USERPROFILE", "TEMP", "TMP"):
        env[k] = work
    # scalene (mesures 2026-08-20) : `--outfile` = TOUJOURS le rapport web HTML
    # (defaut global 'web') -> on ne le passe PAS ; `--json` ecrit `profile.json`
    # RELATIF au cwd A L'EXIT. `--no-browser` sinon le mode web gagne. `--profile-all`
    # sinon scalene n'attribue qu'au fichier cible et IGNORE le code importe
    # (app/forge_*.py) -> inutile pour profiler un chemin Nokido vivant.
    # ARGS DE LA CIBLE (2026-08-20) : sans eux, impossible de profiler un DAEMON.
    # `forge_qdrant_sync_daemon.py` boucle a l'infini ; seul son `--once` le fait
    # sortir, donc rendre un `profile.json` (scalene n'ecrit qu'A L'EXIT). Sans ce
    # passage, tout script a boucle infinie ne rend QUE le timeout, jamais un profil.
    # `scalene [options] script.py [args...]` transmet la queue a la cible.
    import shlex as _shlex

    _cible_args = _shlex.split(script_args or "")
    r = subprocess.run(
        [python, "-m", "scalene", "--json", "--no-browser", "--profile-all", script]
        + _cible_args,
        capture_output=True, text=True, errors="replace", timeout=timeout,
        cwd=work, env=env)
    for source in (os.path.join(work, "profile.json"),
                   os.path.join(os.getcwd(), "profile.json"), None):
        if source is None:
            obj = _extraire(r.stdout or "")
        elif os.path.isfile(source):
            obj = _extraire(open(source, encoding="utf-8", errors="replace").read())
        else:
            continue
        if obj:
            return obj
    # piege mesure : une cible qui os.chdir vers un dossier read-only fait ecrire
    # profile.json la-bas -> PermissionError. Diagnostic explicite plutot qu'opaque.
    err = r.stderr or ""
    hint = ""
    if "Permission denied" in err and "profile.json" in err:
        hint = ("\n>>> La cible fait os.chdir vers un dossier read-only : scalene ecrit "
                "profile.json RELATIF au cwd a l'exit. Rends un cwd writable dans un "
                "finally de la cible (cf recette scalene-sur-le-vivant).")
    raise SystemExit(
        "scalene n'a pas rendu de JSON (rc=%s).%s\nGenere-le depuis TA session :\n"
        "  scalene --json --no-browser --profile-all %s  (lit ./profile.json)\n"
        "puis relance avec --from-json profile.json\nstderr: %s"
        % (r.returncode, hint, script, err[:200]))


def _cout(ligne: dict) -> float:
    """Cout compose : CPU (python+natif) + poids memoire. Sert au classement."""
    return (float(ligne.get("n_cpu_percent_python", 0))
            + float(ligne.get("n_cpu_percent_c", 0))
            + 0.5 * float(ligne.get("n_malloc_mb", 0)))


def _ligne_optimisable(txt: str) -> bool:
    """Y a-t-il du code a REECRIRE sur cette ligne ?

    Mesure 2026-08-19 : scalene flague `import numpy` comme la ligne la plus
    chaude (cout de CHARGEMENT du module), mais un import ne s'optimise pas -> le
    LLM, faute de code a retravailler, HALLUCINE une "ligne originale". On ecarte
    donc import/from/def/class/decorateur/commentaire/vide : ces lignes chaudes
    sont reelles mais rien a proposer dessus."""
    s = (txt or "").strip()
    if not s or s.startswith(("#", "import ", "from ", "@")):
        return False
    if re.match(r"^(async\s+def|def|class)\b", s):
        return False
    return True


def _fonction_englobante(lineno: int, src: list) -> str | None:
    """Corps de la fonction/classe qui contient la ligne `lineno` (1-based).

    Un LLM optimise BIEN mieux une unite complete (toute la fonction) qu'une ligne
    isolee : il voit la logique et peut la restructurer. On remonte au `def`/`class`
    le plus proche, puis on descend jusqu'au premier dedent <= son indentation."""
    i = min(max(0, lineno - 1), len(src) - 1)
    deb, indent_def = None, 0
    for j in range(i, -1, -1):
        m = re.match(r"^(\s*)(async\s+def|def|class)\s", src[j])
        if m:
            deb, indent_def = j, len(m.group(1))
            break
    if deb is None:
        return None
    fin = len(src)
    for j in range(deb + 1, len(src)):
        s = src[j]
        if s.strip() == "":
            continue
        if (len(s) - len(s.lstrip())) <= indent_def:
            fin = j
            break
    return "".join(src[deb:fin])


def _lignes_chaudes(profil: dict, top: int, seuil: float) -> list:
    """Rend [(fichier, ligne_dict, source_lines)] pour les `top` lignes les plus
    co_teuses au-dessus de `seuil`."""
    out = []
    for fichier, bloc in (profil.get("files") or {}).items():
        lignes = bloc.get("lines") or []
        # src depuis le VRAI fichier si present (indexation par lineno exacte, tout
        # le fichier) -> un profil minimal (juste les lignes chaudes) suffit ; sinon
        # on retombe sur les textes du JSON.
        if os.path.isfile(fichier):
            src = open(fichier, encoding="utf-8", errors="replace").read().splitlines(keepends=True)
        else:
            src = [l.get("line", "") for l in lignes]
        for l in lignes:
            if _cout(l) >= seuil and _ligne_optimisable(l.get("line", "")):
                out.append((fichier, l, src))
    out.sort(key=lambda t: _cout(t[1]), reverse=True)
    return out[:top]


def _region(ligne: dict, src: list) -> str:
    """Region a optimiser, du plus riche au plus pauvre : la FONCTION englobante
    (le LLM voit toute la logique), sinon la boucle reperee par scalene, sinon la
    ligne +/- 2 de contexte."""
    n = int(ligne.get("lineno", 0))
    fn = _fonction_englobante(n, src)
    if fn and fn.strip():
        return fn
    a = ligne.get("start_outermost_loop") or (n - 2)
    b = ligne.get("end_outermost_loop") or (n + 2)
    a, b = max(1, int(a)), min(len(src), int(b))
    return "".join(src[a - 1:b])


def _demander_ollama(prompt: str, model: str, url: str, timeout: int) -> str:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": _SYSTEM},
                     {"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.3},
    }).encode()
    req = urllib.request.Request(url.rstrip("/") + "/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    return ((d.get("message") or {}).get("content") or "").strip()


def _ollama_vivant(url: str) -> list:
    """Liste les modeles (comme ollama.js fetchModelNames). [] si injoignable."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/tags", timeout=5) as r:
            return [m.get("name") for m in (json.loads(r.read()).get("models") or [])]
    except Exception:  # noqa: BLE001 - Ollama eteint : le CLI le dira clairement
        return []


def _intention() -> dict:
    """run_job ne passe AUCUN argument : config via sandbox/scalene_optimize.wanted
    (JSON {script, from_json, model, top, seuil}). Consommee a la lecture -- une
    intention ne se rejoue pas. {} si absente/illisible."""
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "sandbox", "scalene_optimize.wanted")
    try:
        if not os.path.isfile(p):
            return {}
        d = json.loads(open(p, encoding="utf-8", errors="replace").read())
        os.remove(p)
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001 - pas d'intention lisible : rien a faire
        return {}


def main() -> int:
    ap = argparse.ArgumentParser(description="Optimisation IA scalene en CLI souverain")
    ap.add_argument("script", nargs="?", default=None,
                    help="script a profiler (optionnel avec --from-json ou une intention)")
    ap.add_argument("--from-json", default=None,
                    help="profil scalene JSON deja genere (evite de relancer scalene)")
    ap.add_argument("--model", default="qwen2.5-coder:7b-instruct-q4_K_M")
    ap.add_argument("--top", type=int, default=3, help="nb de lignes chaudes a optimiser")
    ap.add_argument("--seuil", type=float, default=1.0, help="cout minimal (%%+Mo) pour retenir une ligne")
    ap.add_argument("--ollama", default="http://localhost:11434")
    ap.add_argument("--python", default=sys.executable,
                    help="interpreteur qui a scalene + les deps de la cible")
    ap.add_argument("--script-args", default="",
                    help="arguments CLI passes A LA CIBLE (ex: '--once'). "
                         "Indispensable pour profiler un daemon : scalene n'ecrit "
                         "profile.json qu'a l'exit du process profile.")
    ap.add_argument("--timeout-profil", type=int, default=180)
    ap.add_argument("--timeout-llm", type=int, default=180)
    args = ap.parse_args()

    if not args.script and not args.from_json:
        conf = _intention()
        args.script = conf.get("script") or args.script
        args.from_json = conf.get("from_json") or args.from_json
        args.model = conf.get("model") or args.model
        args.top = int(conf.get("top", args.top))
        args.seuil = float(conf.get("seuil", args.seuil))

    # Avec --from-json, `script` n'est qu'une etiquette : pas besoin qu'il existe.
    if not args.from_json and not (args.script and os.path.isfile(args.script)):
        print("script introuvable : %s" % args.script)
        return 2

    modeles = _ollama_vivant(args.ollama)
    if not modeles:
        print("Ollama injoignable sur %s -- l'allumer (avec un modele codeur) "
              "avant de relancer." % args.ollama)
        return 3
    if args.model not in modeles:
        print("[avert] modele '%s' absent d'Ollama ; dispo: %s"
              % (args.model, ", ".join(m for m in modeles if "cod" in (m or "").lower()) or modeles[:5]))

    if args.from_json:
        if not os.path.isfile(args.from_json):
            print("--from-json introuvable : %s" % args.from_json)
            return 2
        print("[1/2] lecture du profil %s ..." % os.path.basename(args.from_json), flush=True)
        profil = _extraire(open(args.from_json, encoding="utf-8", errors="replace").read())
        if profil is None:
            print("le fichier --from-json ne contient pas de profil scalene ('files')")
            return 2
    else:
        print("[1/2] profil scalene de %s ..." % os.path.basename(args.script), flush=True)
        profil = _profil_scalene(args.python, args.script, args.timeout_profil,
                                 args.script_args)
    chaudes = _lignes_chaudes(profil, args.top, args.seuil)
    # LA MESURE D'ABORD, L'AVIS ENSUITE (2026-08-20) : les lignes chaudes etaient
    # calculees ici mais n'apparaissaient qu'APRES la boucle Ollama. Mesure du jour :
    # Ollama HS (api/tags repond, api/chat ET api/ps timeout) -> le job restait
    # bloque en phase 2 et le profil, DEJA OBTENU, etait perdu. Un profileur ne doit
    # jamais dependre de la disponibilite d'un LLM pour rendre ce qu'il a mesure.
    # `_lignes_chaudes` rend des TUPLES (fichier, ligne_dict, src), pas des dicts.
    for _n, (_f, _l, _s) in enumerate(chaudes, 1):
        print("  [chaud %d] %s:%s  CPU %.0f%%  mem %.1f Mo  | %s"
              % (_n, os.path.basename(str(_f)), _l.get("lineno", "?"),
                 float(_l.get("n_cpu_percent_python", 0)) + float(_l.get("n_cpu_percent_c", 0)),
                 float(_l.get("n_malloc_mb", 0)),
                 str(_l.get("line", "")).strip()[:88]), flush=True)
    if not chaudes:
        print("aucune ligne au-dessus du seuil %.1f -- rien a optimiser (ou run trop court)."
              % args.seuil)
        return 0

    print("[2/2] %d ligne(s) chaude(s) -> %s (Ollama local)\n" % (len(chaudes), args.model), flush=True)
    for i, (fichier, ligne, src) in enumerate(chaudes, 1):
        region = _region(ligne, src)
        cpu = float(ligne.get("n_cpu_percent_python", 0)) + float(ligne.get("n_cpu_percent_c", 0))
        mo = float(ligne.get("n_malloc_mb", 0))
        entete = "L%s  CPU %.0f%%  mem %.1f Mo  |  %s" % (
            ligne.get("lineno"), cpu, mo, (ligne.get("line") or "").strip()[:80])
        print("=" * 78)
        print("[%d] %s" % (i, entete))
        print("-" * 78)
        prompt = ("Voici une region Python identifiee comme couteuse par un profil "
                  "scalene (CPU %.0f%%, memoire %.1f Mo sur cette ligne).\n\n"
                  "```python\n%s```\n\n"
                  "Reecris UNIQUEMENT cette region en Python plus rapide et/ou plus "
                  "econome en memoire, a comportement identique. Reponds en code "
                  "Python commente, rien d'autre." % (cpu, mo, region))
        try:
            print(_demander_ollama(prompt, args.model, args.ollama, args.timeout_llm))
        except Exception as e:  # noqa: BLE001 - une suggestion qui echoue ne tue pas le run
            # TimeoutError (socket) N'EST PAS un urllib.error.URLError : sur un modele
            # trop lourd pour la RAM (32b a 98 %, il pagine), le chat depasse le
            # timeout et levait un TimeoutError NON attrape -> crash rc=1 (mesure
            # 2026-08-20). On degrade : on nomme l'echec, on passe a la ligne suivante.
            print("  (Ollama a echoue : %s -- modele trop lourd / timeout %ss ? %s)"
                  % (type(e).__name__, args.timeout_llm, str(e)[:100]))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
