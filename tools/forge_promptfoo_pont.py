"""Pont Promptfoo -> Nokido : Promptfoo COMPARE, Nokido TRANSPORTE (decision owner 15/10 : « les deux » -- matrice
etendue d'abord, Promptfoo ensuite).

Pourquoi un pont et pas la config de mai (sandbox/promptfoo_clinical) : elle appelait chaque fournisseur EN DIRECT avec
une cle lue dans l'environnement (`apiKeyEnvar`). Les cles sont au coffre et leurs lignes en clair retirees (15/10) :
cette voie part sans credential. Ici Promptfoo ne voit AUCUNE cle : son fournisseur Python `call_api` resout la voie
par la matrice (FOURNISSEURS, generer_texte) et la cle par get_secret, dans le processus.

Promptfoo vit DANS l'arborescence (runtime/promptfoo, version epinglee), jamais en npm global d'un profil : v0.121.9
etait installe en mai dans AppData de l'owner, invisible des comptes du hub -- le piege paye par Lean le meme jour.

  --provisionner      npm install promptfoo@PIN --prefix runtime/promptfoo (reseau ; geste owner, comme Lean)
  --config SORTIE     voies UTILISABLES de la matrice x taches de competence (correcteurs deterministes, pas de juge LLM)
  --eval CONFIG       evaluation, telemetrie et mise a jour coupees ; resultats JSON a cote de la config
"""
from __future__ import annotations

__FORGE_COLOR__ = "cognition/fitness : pont Promptfoo, comparaison des voies de la matrice sans cle hors du coffre"

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

PIN = "0.121.9"  # version deja eprouvee ici en mai (bench_tools) ; monter = changer CETTE ligne
PREFIXE = ROOT / "runtime" / "promptfoo"
DOSSIER = ROOT / "sandbox" / "promptfoo_nokido"


def _catalogue():
    import forge_provider_catalogue as cat
    return cat


def _get_secret():
    try:
        from nokido_agent.app.forge_secrets import get_secret
    except ImportError:
        from forge_secrets import get_secret
    return get_secret


def voies_utilisables(matrice: dict) -> list:
    """(fournisseur, modele) des voies JOIGNABLES ; une voie dont la competence n'a RIEN pu mesurer est ecartee
    (un 200 a 16 tokens ne prouve pas l'usage). Ordre de la matrice, sans doublon."""
    out, vus = [], set()
    for voies in (matrice.get("familles") or {}).values():
        for v in voies:
            if v.get("etat") != "JOIGNABLE":
                continue
            comp = v.get("competence")
            if isinstance(comp, dict) and comp.get("mesurees") == 0:
                continue
            k = (v.get("fournisseur"), v.get("modele"))
            if all(k) and k not in vus:
                vus.add(k)
                out.append(k)
    return out


def construire_config(matrice: dict, taches=None, pont: Path | None = None, python_exe: str | None = None) -> dict:
    """Config Promptfoo (JSON). Aucune cle n'y entre : seuls fournisseur et modele."""
    taches = taches if taches is not None else _catalogue().TACHES_COMPETENCE
    ref = "file://" + str(pont or Path(__file__).resolve()).replace("\\", "/")
    py = python_exe or sys.executable
    return {
        "description": "Nokido -- competence par voie (matrice du %s)" % matrice.get("mesure_le", "?"),
        "prompts": ["{{prompt}}"],
        "providers": [{"id": ref, "label": "%s:%s" % (f, m),
                       "config": {"fournisseur": f, "modele": m, "pythonExecutable": py}}
                      for f, m in voies_utilisables(matrice)],
        "tests": [{"description": nom, "vars": {"prompt": consigne, "tache": nom},
                   "assert": [{"type": "python", "value": ref}]} for nom, consigne, _ok in taches],
    }


def call_api(prompt, options, context, gen_fn=None, get_secret=None):
    """Fournisseur Python de Promptfoo. Un echec de TRANSPORT rend `error` (Promptfoo le compte a part : INCONNU),
    jamais une sortie vide qui serait notee « rate »."""
    cfg = (options or {}).get("config") or {}
    f, m = cfg.get("fournisseur"), cfg.get("modele")
    cat = _catalogue()
    voie = next(((k, u) for e, k, u in cat.FOURNISSEURS if e == f), None)
    if not (voie and m):
        return {"error": "voie inconnue de la matrice : %s:%s" % (f, m)}
    env_key, url = voie
    cle = (get_secret or _get_secret())(env_key) if env_key else ""
    if not cle:
        return {"error": "cle absente du coffre pour %s" % f}
    code, texte, _lat = (gen_fn or cat.generer_texte)(url, cle, m, prompt)
    if code != 200:
        return {"error": "transport %s : %s" % (code, str(texte)[:160])}
    return {"output": texte}


def get_assert(output, context):
    """Assertion Python de Promptfoo : le correcteur DETERMINISTE de la tache (jamais un juge LLM). Tache inconnue :
    echec dit, jamais un vert par defaut."""
    nom = ((context or {}).get("vars") or {}).get("tache")
    ok = next((fn for n, _c, fn in _catalogue().TACHES_COMPETENCE if n == nom), None)
    if ok is None:
        return {"pass": False, "score": 0, "reason": "tache inconnue : %r" % nom}
    reussi = bool(ok(output if isinstance(output, str) else json.dumps(output)))
    return {"pass": reussi, "score": 1 if reussi else 0, "reason": "%s %s" % (nom, "OK" if reussi else "rate")}


def binaire(prefixe: Path = PREFIXE) -> Path:
    return prefixe / "node_modules" / ".bin" / ("promptfoo.cmd" if os.name == "nt" else "promptfoo")


def provisionner(prefixe: Path = PREFIXE, executer=subprocess.run) -> dict:
    """npm local au depot, version epinglee, jamais `-g`. Verifie la version installee."""
    npm = "npm.cmd" if os.name == "nt" else "npm"
    prefixe.mkdir(parents=True, exist_ok=True)
    r = executer([npm, "install", "--prefix", str(prefixe), "promptfoo@" + PIN, "--no-audit", "--no-fund"],
                 capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        return {"ok": False, "etape": "npm install", "rc": r.returncode, "detail": (r.stderr or "")[-400:]}
    v = executer([str(binaire(prefixe)), "--version"], capture_output=True, text=True, timeout=120)
    lue = (v.stdout or "").strip()
    return {"ok": lue == PIN, "version": lue or "ILLISIBLE", "attendue": PIN}


def evaluer(config: Path, executer=subprocess.run) -> dict:
    b = binaire()
    if not b.exists():
        return {"ok": False, "raison": "promptfoo absent de runtime/ : lancer --provisionner (INCONNU, pas un echec)"}
    sortie = config.with_suffix(".resultats.json")
    env = dict(os.environ, PROMPTFOO_DISABLE_TELEMETRY="1", PROMPTFOO_DISABLE_UPDATE="1",
               PROMPTFOO_PYTHON=sys.executable, PROMPTFOO_CONFIG_DIR=str(DOSSIER / ".promptfoo"))
    r = executer([str(b), "eval", "-c", str(config), "-o", str(sortie), "--no-cache", "-j", "2"],
                 capture_output=True, text=True, timeout=3600, env=env)
    return {"ok": r.returncode in (0, 100), "rc": r.returncode, "resultats": str(sortie),
            "fin": (r.stdout or "")[-600:]}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--provisionner", action="store_true")
    g.add_argument("--config", metavar="SORTIE")
    g.add_argument("--eval", metavar="CONFIG")
    a = ap.parse_args(argv)
    if a.provisionner:
        r = provisionner()
    elif a.config:
        m = json.loads(_catalogue().MATRICE.read_text(encoding="utf-8"))
        c = construire_config(m)
        Path(a.config).parent.mkdir(parents=True, exist_ok=True)
        Path(a.config).write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
        r = {"ok": bool(c["providers"]), "voies": len(c["providers"]), "taches": len(c["tests"]), "config": a.config}
    else:
        r = evaluer(Path(a.eval))
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
