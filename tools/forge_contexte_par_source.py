"""forge_contexte_par_source.py -- P0 economie de contexte : ventiler une transcription Claude Code par source.

__FORGE_COLOR__ = 'metabolisme-llm/instrument'

Decision owner 20/10 (ordre strict) : MESURER avant d'alleger. Le cout d'une session longue est domine par la
RELECTURE : chaque appel API relit tout le contexte. L'instrument lit une transcription `.jsonl` de Claude Code
(~/.claude/projects/<projet>/<session>.jsonl) et rend, par source :
  - `car`            caracteres envoyes au modele (hook par BALISE, outil par NOM, texte, resume de compaction) ;
  - `car_repetes`    ceux deja vus MOT POUR MOT dans le meme segment (ce qu'une deduplication economiserait) ;
  - `tours_relus`    nombre d'appels API qui ont relu le bloc (jusqu'a la compaction suivante) ;
  - `tokens_tours`   estimation tokens x tours relus = le vrai poids sur la facture.
L'estimation tokens/caractere vient d'un AJUSTEMENT sur l'entree reelle de chaque appel (usage : input +
cache lu + cache ecrit) : entree = prefixe + k x caracteres visibles. Le prefixe = ce que la transcription ne
contient pas (instructions systeme, CLAUDE.md, MEMORY.md, definitions d'outils). Moins de 3 appels : la
calibration le DIT (`source: defaut`, prefixe inconnu) au lieu d'inventer.

MESURE SEULEMENT : rien n'est retire. Un allegement (P1a hooks, P1c instructions residentes) se decide sur ce
rapport, sans perte cognitive : critere = les 3 diagnostics durs rejoues avant/apres.

Usage : LAFORGE_PYTHON tools/forge_contexte_par_source.py <transcription.jsonl> [...] [--sortie r.json] [--top 25]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

K_DEFAUT = 0.3          # tokens par caractere si l'ajustement est impossible (dit `source: defaut`)
_BALISE = re.compile(r"^\[([^\]\s]{1,40})\]")
_RAPPEL = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_INBOX = re.compile(r"\[HOOK:INBOX\].*?\[/HOOK:INBOX\]", re.S)


def _etiquette(morceau: str) -> str:
    m = _BALISE.match(morceau.lstrip())
    if m:
        return m.group(1)
    tete = morceau.strip()[:40].lower()
    if tete.startswith("caveman"):
        return "caveman"
    return "sans_balise"


def _decouper_par_balise(texte: str) -> list[tuple[str, str]]:
    """Une sortie de hook porte plusieurs balises ([sense] ... [memoire:courte] ...) : une part par balise."""
    parts, courant = [], []
    for ligne in texte.splitlines(keepends=True):
        if _BALISE.match(ligne.lstrip()) and courant:
            parts.append("".join(courant))
            courant = []
        courant.append(ligne)
    if courant:
        parts.append("".join(courant))
    return [(_etiquette(p), p) for p in parts if p]


def _texte_de(contenu) -> str:
    if isinstance(contenu, str):
        return contenu
    if isinstance(contenu, list):
        return "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in contenu)
    return ""


_HOOK_TYPES = ("hook_additional_context", "hook_success")


def _contenus_hook(att: dict) -> list[str]:
    """Sorties injectees par un hook : `content` (chaine ou liste), sinon `stdout`.

    Une chaine n'est PAS une liste de sorties : l'iterer donnait une part par caractere (mesure 22/10).
    """
    brut = att.get("content")
    if brut in (None, "", []):
        brut = att.get("stdout") or ""
    if isinstance(brut, str):
        return [brut] if brut else []
    if isinstance(brut, list):
        return [_texte_de([c]) if isinstance(c, dict) else str(c) for c in brut if isinstance(c, (str, dict))]
    return [_texte_de(brut)]


def injections_hooks(entrees) -> list[dict]:
    """Blocs reellement injectes par les hooks, dans l'ordre de la transcription. Lecture seule.

    Un hook est identifie par son `hookName` (ex. `PreToolUse:capability-gate`) et, a defaut, par son
    `hookEvent`. Rend [{'hook', 'evenement', 'type', 'texte'}]. Les evenements sans contenu
    (`hook_cancelled`, `hook_error`) ne sont pas des injections : ils sont ignores.
    """
    injections = []
    for e in entrees:
        if not isinstance(e, dict) or e.get("isSidechain") or e.get("type") != "attachment":
            continue
        att = e.get("attachment") or {}
        typ = att.get("type")
        evt = att.get("hookEvent")
        nom = att.get("hookName")
        if typ not in _HOOK_TYPES and not evt and not nom:
            continue
        texte = "\n".join(_contenus_hook(att))
        if not texte:
            continue
        injections.append({"hook": nom or evt or typ or "?", "evenement": evt or nom or "?",
                           "type": typ or "hook", "texte": texte})
    return injections


class _Segment:
    def __init__(self):
        self.blocs = []          # [source, car, repete, appels_a_l_insertion]
        self.vus = set()
        self.appels = 0
        self.texte_par_appel = []   # l'appel i a-t-il dit un mot (bloc texte non vide) ?
        self.resultats = []         # [indice de l'appel qui a demande l'outil, car, appels_a_l_insertion]

    def ajouter(self, source: str, texte: str):
        if not texte:
            return
        h = hashlib.sha1((source + "\0" + texte).encode("utf-8", "replace")).hexdigest()
        repete = h in self.vus
        self.vus.add(h)
        self.blocs.append([source, len(texte), repete, self.appels])

    def car(self) -> int:
        return sum(b[1] for b in self.blocs)


def _ajuster(points):
    """Moindres carres entree = a + k x car ; None si moins de 3 points ou x constant."""
    if len(points) < 3:
        return None
    n = len(points)
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mx) ** 2 for p in points)
    if sxx <= 0:
        return None
    k = sum((p[0] - mx) * (p[1] - my) for p in points) / sxx
    a = my - k * mx
    syy = sum((p[1] - my) ** 2 for p in points)
    sres = sum((p[1] - (a + k * p[0])) ** 2 for p in points)
    r2 = 1 - sres / syy if syy > 0 else 1.0
    if k <= 0:
        return None
    return a, k, r2


def _code_mode(segments) -> dict:
    """Chaines = au moins 2 appels successifs sans un mot (outils seulement). Leurs resultats INTERMEDIAIRES (tous
    sauf ceux du dernier maillon) tiendraient hors du contexte si la chaine etait un seul script (code mode)."""
    chaines = en_chaine = car = car_tours = 0
    for seg in segments:
        i, n = 0, len(seg.texte_par_appel)
        while i < n:
            if seg.texte_par_appel[i]:
                i += 1
                continue
            j = i
            while j + 1 < n and not seg.texte_par_appel[j + 1]:
                j += 1
            if j > i:
                chaines += 1
                en_chaine += j - i + 1
                for appel, c, a_l_insertion in seg.resultats:
                    if i <= appel < j:
                        car += c
                        car_tours += c * (seg.appels - a_l_insertion)
            i = j + 1
    return {"chaines": chaines, "appels_en_chaine": en_chaine, "car_intermediaires": car,
            "car_tours_intermediaires": car_tours}


def analyser(entrees) -> dict:
    segments = [_Segment()]
    outils = {}                  # tool_use_id -> nom
    appel_de = {}                # tool_use_id -> (segment, indice de l'appel)
    appels_vus = set()
    points = []                  # (car visibles avant l'appel, entree reelle)
    sans_rendu = 0

    for e in entrees:
        if not isinstance(e, dict) or e.get("isSidechain"):
            continue
        seg = segments[-1]
        t = e.get("type")
        if t == "system" and e.get("subtype") == "compact_boundary":
            segments.append(_Segment())
            continue
        if t == "attachment":
            att = e.get("attachment") or {}
            rendu = "".join(r.get("content", "") for r in (e.get("rendered") or []) if isinstance(r, dict))
            if att.get("type") in _HOOK_TYPES or att.get("hookEvent"):
                evt = att.get("hookEvent") or att.get("hookName") or "?"
                contenus = _contenus_hook(att)
                total_parts = 0
                for c in contenus:
                    for etiq, part in _decouper_par_balise(c):
                        seg.ajouter("hook:%s:%s" % (evt, etiq), part)
                        total_parts += len(part)
                if not rendu:
                    sans_rendu += 1
                elif len(rendu) > total_parts:
                    seg.ajouter("hook:%s:enveloppe" % evt, rendu[: len(rendu) - total_parts])
            else:
                if not rendu:
                    sans_rendu += 1
                seg.ajouter("attachment:%s" % (att.get("type") or "?"), rendu)
            continue
        msg = e.get("message") or {}
        if t == "assistant":
            rid = e.get("requestId") or msg.get("id")
            if rid and rid not in appels_vus:
                appels_vus.add(rid)
                u = msg.get("usage") or {}
                reel = sum(int(u.get(c) or 0) for c in
                           ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
                if reel > 0:
                    points.append((seg.car(), reel))
                seg.appels += 1
                seg.texte_par_appel.append(False)
            for b in msg.get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    seg.ajouter("assistant:texte", b.get("text", ""))
                    if (b.get("text") or "").strip() and seg.texte_par_appel:
                        seg.texte_par_appel[-1] = True
                elif b.get("type") == "thinking":
                    seg.ajouter("assistant:pensee", b.get("thinking", ""))
                elif b.get("type") == "tool_use":
                    outils[b.get("id")] = b.get("name") or "?"
                    appel_de[b.get("id")] = (len(segments) - 1, max(seg.appels - 1, 0))
                    seg.ajouter("appel_outil:%s" % (b.get("name") or "?"),
                                json.dumps(b.get("input") or {}, ensure_ascii=False))
            continue
        if t == "user":
            contenu = msg.get("content")
            if e.get("isCompactSummary"):
                seg.ajouter("resume_compaction", _texte_de(contenu))
                continue
            blocs = [{"type": "text", "text": contenu}] if isinstance(contenu, str) else (contenu or [])
            for b in blocs:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    texte = b.get("text", "")
                    for r in _RAPPEL.findall(texte):
                        seg.ajouter("rappel_systeme:" + _etiquette(r.replace("<system-reminder>", "").lstrip()), r)
                    seg.ajouter("user:texte", _RAPPEL.sub("", texte))
                elif b.get("type") == "tool_result":
                    texte = _texte_de(b.get("content"))
                    for r in _INBOX.findall(texte):
                        seg.ajouter("hub:inbox", r)
                    propre = _INBOX.sub("", texte)
                    seg.ajouter("outil:%s" % outils.get(b.get("tool_use_id"), "?"), propre)
                    origine = appel_de.get(b.get("tool_use_id"))
                    if origine and origine[0] == len(segments) - 1 and propre:
                        seg.resultats.append([origine[1], len(propre), seg.appels])
                elif b.get("type") == "image":
                    seg.ajouter("image", "[image]")

    fit = _ajuster(points)
    if fit:
        a, k, r2 = fit
        calibration = {"source": "ajustement", "prefixe_tokens": round(a), "tokens_par_car": round(k, 4),
                       "r2": round(r2, 4), "points": len(points)}
    else:
        k = K_DEFAUT
        calibration = {"source": "defaut", "prefixe_tokens": None, "tokens_par_car": K_DEFAUT, "r2": None,
                       "points": len(points)}

    agg = {}
    for seg in segments:
        for source, car, repete, a_l_insertion in seg.blocs:
            s = agg.setdefault(source, {"source": source, "occurrences": 0, "car": 0, "car_repetes": 0,
                                        "tours_relus": 0, "car_tours": 0})
            tours = seg.appels - a_l_insertion
            s["occurrences"] += 1
            s["car"] += car
            s["car_repetes"] += car if repete else 0
            s["tours_relus"] += tours
            s["car_tours"] += car * tours
    for s in agg.values():
        s["tokens_est"] = round(s["car"] * k)
        s["tokens_tours_est"] = round(s.pop("car_tours") * k)
    sources = sorted(agg.values(), key=lambda s: -s["tokens_tours_est"])

    total = sum(s["tokens_tours_est"] for s in sources) or 0
    familles = {}
    for s in sources:
        f = familles.setdefault(s["source"].split(":", 1)[0], {"famille": s["source"].split(":", 1)[0],
                                                               "tokens_tours_est": 0, "car": 0, "car_repetes": 0})
        f["tokens_tours_est"] += s["tokens_tours_est"]
        f["car"] += s["car"]
        f["car_repetes"] += s["car_repetes"]
    for f in familles.values():
        f["part"] = f["tokens_tours_est"] / total if total else 0.0

    final = {}
    for source, car, _r, _a in segments[-1].blocs:
        final[source] = final.get(source, 0) + car
    return {
        "segments": len(segments),
        "appels": sum(s.appels for s in segments),
        "attachments_sans_rendu": sans_rendu,
        "calibration": calibration,
        "familles": sorted(familles.values(), key=lambda f: -f["tokens_tours_est"]),
        "code_mode": _code_mode_estime(_code_mode(segments), k, total),
        "sources": sources,
        "contexte_final": [{"source": s, "car": c, "tokens_est": round(c * k)}
                           for s, c in sorted(final.items(), key=lambda x: -x[1])],
    }


def _code_mode_estime(cm: dict, k: float, total: float) -> dict:
    cm["tokens_tours_intermediaires_est"] = round(cm["car_tours_intermediaires"] * k)
    cm["part"] = cm["tokens_tours_intermediaires_est"] / total if total else 0.0
    return cm


def _lire(chemin: Path):
    illisibles = 0
    entrees = []
    with open(chemin, encoding="utf-8", errors="replace") as f:
        for ligne in f:
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                entrees.append(json.loads(ligne))
            except ValueError:
                illisibles += 1
    return entrees, illisibles


def _compteur_tokens():
    """cl100k_base via tiktoken (cache local) ; None si illisible (jamais 0 deguise)."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return lambda t: len(enc.encode(t, disallowed_special=()))
    except Exception:
        return None


def poids_schemas_outils(outils: list[dict], compter=None) -> dict:
    """Poids des schemas d'outils MCP (tools/list) : par outil caracteres, tokens, part description.
    Forme serialisee {name, description, inputSchema}. tokens = None si compteur illisible."""
    compter = compter or _compteur_tokens()
    lignes = []
    for o in outils:
        ser = json.dumps({k: o.get(k) for k in ("name", "description", "inputSchema") if k in o},
                         ensure_ascii=False, separators=(",", ":"))
        desc = o.get("description") or ""
        lignes.append({"outil": o.get("name", "UNKNOWN"), "car": len(ser),
                       "tokens": compter(ser) if compter else None,
                       "car_description": len(desc),
                       "tokens_description": compter(desc) if compter else None,
                       "part_description_car": round(len(desc) / len(ser), 4) if ser else None})
    lignes.sort(key=lambda x: -x["car"])
    return {"outils": len(lignes), "car_total": sum(x["car"] for x in lignes),
            "tokens_total": sum(x["tokens"] for x in lignes) if compter else None,
            "compteur": "tiktoken cl100k_base" if compter else "UNKNOWN", "par_outil": lignes}


def lister_outils_mcp(config: Path, serveur: str | None = None) -> list[dict]:
    """tools/list en JSON-RPC HTTP sur un serveur d'un --mcp-config. headersHelper execute, jamais affiche."""
    import subprocess
    import urllib.request
    cfg = json.loads(config.read_text(encoding="utf-8"))["mcpServers"]
    srv = cfg[serveur] if serveur else next(iter(cfg.values()))
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if srv.get("headers"):
        h.update(srv["headers"])
    if srv.get("headersHelper"):
        sortie = subprocess.run(srv["headersHelper"], shell=True, capture_output=True, text=True, timeout=30).stdout
        h.update(json.loads(sortie))

    def rpc(methode, params=None, id_=1):
        corps = {"jsonrpc": "2.0", "method": methode, "params": params or {}}
        if id_:
            corps["id"] = id_
        req = urllib.request.Request(srv["url"], json.dumps(corps).encode(), h)
        with urllib.request.urlopen(req, timeout=60) as r:
            brut = r.read().decode("utf-8", "replace")
            if r.headers.get("mcp-session-id"):
                h["Mcp-Session-Id"] = r.headers["mcp-session-id"]
        if brut.startswith(("event:", "data:")) or "\ndata:" in brut:
            brut = "".join(l[5:] for l in brut.splitlines() if l.startswith("data:"))
        return json.loads(brut) if brut.strip() else {}

    rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "poids-outils", "version": "1"}})
    rpc("notifications/initialized", id_=0)
    outils, curseur = [], None
    while True:
        res = rpc("tools/list", {"cursor": curseur} if curseur else {}, 2).get("result", {})
        outils += res.get("tools", [])
        curseur = res.get("nextCursor")
        if not curseur:
            return outils


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("transcriptions", nargs="*")
    p.add_argument("--schemas-mcp", metavar="MCP_CONFIG",
                   help="poids des schemas d'outils (tools/list) d'un --mcp-config, au lieu d'une transcription")
    p.add_argument("--serveur", help="serveur du --mcp-config (defaut : le premier)")
    p.add_argument("--sortie", help="fichier JSON du rapport (un rapport par transcription)")
    p.add_argument("--top", type=int, default=25)
    a = p.parse_args(argv)
    if a.schemas_mcp:
        r = poids_schemas_outils(lister_outils_mcp(Path(a.schemas_mcp), a.serveur))
        print("== schemas MCP : %d outils, %d car, %s tokens (%s)"
              % (r["outils"], r["car_total"], r["tokens_total"], r["compteur"]))
        for x in r["par_outil"][: a.top]:
            print("   %-40s %7d car %6s tok  desc %.0f%%" % (
                x["outil"][:40], x["car"], x["tokens"], 100 * (x["part_description_car"] or 0)))
        if a.sortie:
            Path(a.sortie).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
            print("rapport : %s" % a.sortie)
        return 0
    if not a.transcriptions:
        p.error("transcription requise (ou --schemas-mcp)")
    rapports = []
    for chemin in a.transcriptions:
        entrees, illisibles = _lire(Path(chemin))
        r = analyser(entrees)
        r.update(transcription=str(chemin), lignes=len(entrees), lignes_illisibles=illisibles)
        rapports.append(r)
        cal = r["calibration"]
        print("== %s : %d appels, %d segment(s), %d ligne(s) illisible(s)"
              % (Path(chemin).name, r["appels"], r["segments"], illisibles))
        print("   calibration %s : prefixe %s tokens, %.4f tokens/car, r2 %s, %d points"
              % (cal["source"], cal["prefixe_tokens"], cal["tokens_par_car"], cal["r2"], cal["points"]))
        total = sum(s["tokens_tours_est"] for s in r["sources"]) or 1
        cm = r["code_mode"]
        print("   code mode : %d chaine(s), %d appel(s) enchaines sans texte ; resultats intermediaires %.1f%% du cout"
              % (cm["chaines"], cm["appels_en_chaine"], 100.0 * cm["part"]))
        print("   familles : " + " | ".join("%s %.1f%% (repete %.0f%%)" % (
            f["famille"], 100.0 * f["part"], 100.0 * f["car_repetes"] / f["car"] if f["car"] else 0.0)
            for f in r["familles"]))
        print("   %-44s %6s %10s %9s %14s %6s" % ("source", "occ", "tokens", "repete%", "tokens x tours", "part%"))
        for s in r["sources"][: a.top]:
            print("   %-44s %6d %10d %8.0f%% %14d %5.1f%%" % (
                s["source"][:44], s["occurrences"], s["tokens_est"],
                100.0 * s["car_repetes"] / s["car"] if s["car"] else 0.0,
                s["tokens_tours_est"], 100.0 * s["tokens_tours_est"] / total))
        if len(r["sources"]) > a.top:
            print("   ... %d source(s) de plus dans le rapport JSON" % (len(r["sources"]) - a.top))
    if a.sortie:
        donnees = rapports[0] if len(rapports) == 1 else rapports
        Path(a.sortie).write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
        print("rapport : %s" % a.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
