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
# Poids du cache rapportes a l'entree pleine : un bloc s'ecrit une fois, puis se relit a chaque tour.
POIDS_ECRITURE_CACHE = 1.25
POIDS_LECTURE_CACHE = 0.1
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
                                        "tours_relus": 0, "car_tours": 0, "car_pondere": 0.0})
            tours = seg.appels - a_l_insertion
            s["occurrences"] += 1
            s["car"] += car
            s["car_repetes"] += car if repete else 0
            s["tours_relus"] += tours
            s["car_tours"] += car * tours
            s["car_pondere"] += car * (POIDS_ECRITURE_CACHE + POIDS_LECTURE_CACHE * tours)
    for s in agg.values():
        s["tokens_est"] = round(s["car"] * k)
        s["tokens_tours_est"] = round(s.pop("car_tours") * k)
        s["pondere_est"] = round(s.pop("car_pondere") * k)
    sources = sorted(agg.values(), key=lambda s: -s["tokens_tours_est"])

    total = sum(s["tokens_tours_est"] for s in sources) or 0
    total_pondere = sum(s["pondere_est"] for s in sources)
    for s in sources:
        s["part_ponderee"] = s["pondere_est"] / total_pondere if total_pondere else 0.0
    familles = {}
    for s in sources:
        f = familles.setdefault(s["source"].split(":", 1)[0], {"famille": s["source"].split(":", 1)[0],
                                                               "tokens_tours_est": 0, "car": 0, "car_repetes": 0,
                                                               "pondere_est": 0})
        f["tokens_tours_est"] += s["tokens_tours_est"]
        f["pondere_est"] += s["pondere_est"]
        f["car"] += s["car"]
        f["car_repetes"] += s["car_repetes"]
    for f in familles.values():
        f["part"] = f["tokens_tours_est"] / total if total else 0.0
        f["part_ponderee"] = f["pondere_est"] / total_pondere if total_pondere else 0.0

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
        sortie = subprocess.run(srv["headersHelper"], shell=True, capture_output=True, text=True,
                                errors="replace", timeout=30).stdout
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


def volume_par_demande(entrees) -> dict:
    """Caracteres rendus par les outils entre deux messages de l'owner. Notifications et contexte injecte n'en sont pas."""
    volumes, courant = [], None
    for e in entrees:
        if e.get("type") != "user" or e.get("isMeta"):
            continue
        contenu = (e.get("message") or {}).get("content")
        blocs = contenu if isinstance(contenu, list) else []
        resultats = [b for b in blocs if isinstance(b, dict) and b.get("type") == "tool_result"]
        if resultats:
            courant = (courant or 0) + sum(len(json.dumps(b.get("content"), ensure_ascii=False)) for b in resultats)
            continue
        texte = contenu if isinstance(contenu, str) else " ".join(
            str(b.get("text") or "") for b in blocs if isinstance(b, dict))
        if not texte.strip() or texte.lstrip().startswith("<"):
            continue
        if courant is not None:
            volumes.append(courant)
        courant = 0
    if courant is not None:
        volumes.append(courant)
    return _resume_volumes(volumes)


def _resume_volumes(volumes) -> dict:
    v = sorted(volumes)
    rang = lambda q: v[min(len(v) - 1, int(len(v) * q))] if v else 0  # noqa: E731
    return {"demandes": len(v), "med": rang(.5), "p90": rang(.9), "p99": rang(.99), "max": v[-1] if v else 0,
            "total": sum(v), "volumes": v}


def sorties_par_outil(entrees, plafonds=(2000, 5000)) -> list:
    """Concentration des sorties, par outil. Seul l'excedent au-dessus d'un plafond est gagnable :
    une moyenne ne dit pas si plafonner servirait. Volume brut, sans le facteur des tours.
    Une sortie compte une fois : la transcription rejoue les messages conserves apres une compaction
    (454 sorties de run comptees pour 255 reelles, le 5/11)."""
    noms, tailles, vues = {}, {}, set()
    for e in entrees:
        blocs = (e.get("message") or {}).get("content")
        for b in blocs if isinstance(blocs, list) else []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                noms[b.get("id")] = b.get("name") or "ILLISIBLE"
            elif b.get("type") == "tool_result":
                ident = b.get("tool_use_id")
                if ident in vues:
                    continue
                vues.add(ident)
                nom = noms.get(ident, "ILLISIBLE")
                tailles.setdefault(nom, []).append(len(json.dumps(b.get("content"), ensure_ascii=False)))
    lignes = []
    for nom, t in tailles.items():
        t.sort()
        lignes.append({
            "outil": nom, "n": len(t), "total": sum(t), "p50": t[len(t) // 2],
            "p90": t[int(len(t) * 0.9)], "max": t[-1],
            "gain_plafond": {str(p): sum(max(0, x - p) for x in t) for p in plafonds},
        })
    return sorted(lignes, key=lambda x: -x["total"])


def _zone_lue(chemin: str) -> str:
    c = (chemin or "").replace("\\", "/").lower()
    if "/.claude/" in c:
        return "memoire"
    if "/nokido/" in c or c.endswith("/nokido"):
        return "depot"
    if c.startswith("c:/tmp/") or "/temp/" in c:
        return "tmp"
    return "autre" if c else "ILLISIBLE"


def lectures_par_zone(entrees) -> list:
    """Read natifs ventilés par zone (depot, memoire, tmp, autre) et par forme (bornee = limit
    ou offset, entiere sinon). Mesure 9/11 : les 41 Read d'une session à 720K jetons passaient tous
    sous le seuil de taille du garde ; sans la zone, impossible de dire quel levier vise juste.
    Une sortie compte une fois (rejeu après compaction). Chemins et tailles seulement."""
    lectures, vues, lignes = {}, set(), {}
    for e in entrees:
        blocs = (e.get("message") or {}).get("content")
        for b in blocs if isinstance(blocs, list) else []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and b.get("name") == "Read":
                ti = b.get("input") or {}
                forme = "bornee" if (ti.get("limit") or ti.get("offset")) else "entiere"
                lectures[b.get("id")] = (_zone_lue(ti.get("file_path", "")), forme)
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in lectures:
                ident = b.get("tool_use_id")
                if ident in vues:
                    continue
                vues.add(ident)
                zone, forme = lectures[ident]
                x = lignes.setdefault((zone, forme), {"zone": zone, "forme": forme, "n": 0, "car": 0, "max": 0})
                taille = len(json.dumps(b.get("content"), ensure_ascii=False))
                x["n"] += 1
                x["car"] += taille
                x["max"] = max(x["max"], taille)
    return sorted(lignes.values(), key=lambda x: -x["car"])


def _rapport_sorties_outils(chemins, top=25) -> int:
    for chemin in chemins:
        entrees = _lire(Path(chemin))[0]
        for z in lectures_par_zone(entrees):
            print("   Read %-8s %-8s n=%-4d %8d car  max %d" % (z["zone"], z["forme"], z["n"], z["car"], z["max"]))
        lignes = sorties_par_outil(entrees)
        total = sum(x["total"] for x in lignes) or 1
        print("== %s : %d car rendus par les outils" % (Path(chemin).name[:8], total))
        print("   %-44s %5s %9s %6s %7s %7s %10s %10s" % (
            "outil", "n", "total", "p50", "p90", "max", "gain 2000", "gain 5000"))
        for x in lignes[:top]:
            print("   %-44s %5d %9d %6d %7d %7d %10d %10d" % (
                x["outil"][:44], x["n"], x["total"], x["p50"], x["p90"], x["max"],
                x["gain_plafond"]["2000"], x["gain_plafond"]["5000"]))
        print("   gain total : plafond 2000 %.1f%%, plafond 5000 %.1f%% du volume des sorties" % tuple(
            100.0 * sum(x["gain_plafond"][p] for x in lignes) / total for p in ("2000", "5000")))
    return 0


def _rapport_par_demande(chemins) -> int:
    """Une ligne par transcription, puis l'ensemble. Un dossier vaut ses 20 transcriptions les plus recentes."""
    fichiers = []
    for c in map(Path, chemins):
        fichiers += sorted(c.glob("*.jsonl"), key=lambda f: f.stat().st_mtime)[-20:] if c.is_dir() else [c]
    tous = []
    for f in fichiers:
        entrees, _illisibles = _lire(f)
        r = volume_par_demande(entrees)
        tous += r["volumes"]
        print("%s : demandes %d, med %d, p90 %d, max %d car" % (f.name, r["demandes"], r["med"], r["p90"], r["max"]))
    r = _resume_volumes(tous)
    print("ENSEMBLE : demandes %d, med %d, p90 %d, p99 %d, max %d, total %d car"
          % (r["demandes"], r["med"], r["p90"], r["p99"], r["max"], r["total"]))
    return 0


def ventiler_cout(entrees) -> dict:
    """Ventile le cout en tokens d'une session sans exposer le contenu des messages.

    Sortie JSON structurée :
    - tours : total
    - tours_notification : declenches par notification de tache/systeme
    - tours_owner : messages de l'owner
    - input : total input_tokens
    - cache_read : total cache_read_input_tokens
    - cache_creation : total cache_creation_input_tokens
    - output : total output_tokens
    - top_5_tours : les 5 tours les plus lourds (sans contenu)
    """
    balises_notif = ("<task-notification>", "[SYSTEM NOTIFICATION", "task-notification")
    tours_liste = []
    declencheur_courant = "owner"
    reponse_en_cours = None

    for i, e in enumerate(entrees):
        if not isinstance(e, dict) or e.get("isSidechain"):
            continue
        t = e.get("type")
        msg = e.get("message") if isinstance(e.get("message"), dict) else {}
        if t == "user":
            contenu = msg.get("content")
            texte = contenu if isinstance(contenu, str) else " ".join(
                str(b.get("text") or "") for b in contenu if isinstance(b, dict))
            if any(b in texte for b in balises_notif):
                declencheur_courant = "notification"
            else:
                declencheur_courant = "owner"
        elif t == "assistant":
            u = msg.get("usage")
            if isinstance(u, dict):
                in_tok = int(u.get("input_tokens") or 0)
                cr_tok = int(u.get("cache_read_input_tokens") or 0)
                cc_tok = int(u.get("cache_creation_input_tokens") or 0)
                out_tok = int(u.get("output_tokens") or 0)
                tot = in_tok + cr_tok + cc_tok + out_tok
                mid = msg.get("id") or f"turn_{len(tours_liste)}"
                tours_liste.append({
                    "id": mid,
                    "declencheur": declencheur_courant,
                    "input": in_tok,
                    "cache_read": cr_tok,
                    "cache_creation": cc_tok,
                    "output": out_tok,
                    "total_tokens": tot,
                })

    # Dédoublonner par mid (prendre le dernier etat pour un stream de meme id)
    par_id = {}
    for tour in tours_liste:
        par_id[tour["id"]] = tour

    tours_finaux = list(par_id.values())
    n_notif = sum(1 for t in tours_finaux if t["declencheur"] == "notification")
    n_owner = sum(1 for t in tours_finaux if t["declencheur"] == "owner")
    total_in = sum(t["input"] for t in tours_finaux)
    total_cr = sum(t["cache_read"] for t in tours_finaux)
    total_cc = sum(t["cache_creation"] for t in tours_finaux)
    total_out = sum(t["output"] for t in tours_finaux)

    top_5 = sorted(tours_finaux, key=lambda t: -t["total_tokens"])[:5]
    top_5_propres = [
        {
            "id": t["id"],
            "declencheur": t["declencheur"],
            "input": t["input"],
            "cache_read": t["cache_read"],
            "cache_creation": t["cache_creation"],
            "output": t["output"],
            "total_tokens": t["total_tokens"],
        }
        for t in top_5
    ]

    return {
        "tours": len(tours_finaux),
        "tours_notification": n_notif,
        "tours_owner": n_owner,
        "input": total_in,
        "cache_read": total_cr,
        "cache_creation": total_cc,
        "output": total_out,
        "top_5_tours": top_5_propres,
    }


def usage_reel(entrees) -> dict:
    """Tokens rapportes par l'API, l'autre unite que tokens x tours : une reponse en flux ecrit plusieurs
    lignes de meme message.id, seule la derniere compte."""
    par_id = {}
    for i, e in enumerate(entrees):
        m = e.get("message") if isinstance(e, dict) else None
        u = m.get("usage") if isinstance(m, dict) else None
        if isinstance(u, dict):
            par_id[m.get("id") or i] = u
    cles = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
    total = {k: sum(int(u.get(k) or 0) for u in par_id.values()) for k in cles}
    # Poids SUPPOSES (tarif API : entree 1, ecriture cache 1,25, lecture cache 0,1, sortie 5). Quota d'abonnement : INCONNU.
    poids = dict(zip(cles, (1.0, 1.25, 0.1, 5.0)))
    pondere = {k: total[k] * poids[k] for k in cles}
    somme = sum(pondere.values()) or 1.0
    return dict(total, reponses=len(par_id), part_ponderee={k: round(pondere[k] / somme, 3) for k in cles})


def facture_par_segment(entrees) -> dict:
    """Facture API par segment de compaction : ouverture (premiere reponse), base relue (contexte d'ouverture relu
    a chaque reponse suivante, borne par la lecture mesuree), croissance, sortie. Poids SUPPOSES, quota INCONNU."""
    segments = [{}]
    for i, e in enumerate(entrees):
        if not isinstance(e, dict) or e.get("isSidechain"):
            continue
        if e.get("type") == "system" and e.get("subtype") == "compact_boundary":
            segments.append({})
            continue
        m = e.get("message")
        u = m.get("usage") if isinstance(m, dict) else None
        if isinstance(u, dict):
            segments[-1][m.get("id") or i] = u

    def champ(u, cle):
        return int(u.get(cle) or 0)

    lignes = []
    for par_id in segments:
        us = list(par_id.values())
        s = {"reponses": len(us), "ctx_debut": 0, "ecriture_ouverture": 0, "lecture_ouverture": 0, "entree": 0,
             "ecriture": 0, "lecture": 0, "sortie": 0, "base_relue": 0}
        if us:
            s["ecriture_ouverture"] = champ(us[0], "cache_creation_input_tokens")
            s["lecture_ouverture"] = champ(us[0], "cache_read_input_tokens")
            s["ctx_debut"] = champ(us[0], "input_tokens") + s["ecriture_ouverture"] + s["lecture_ouverture"]
            s["entree"] = sum(champ(u, "input_tokens") for u in us)
            s["ecriture"] = sum(champ(u, "cache_creation_input_tokens") for u in us)
            s["lecture"] = sum(champ(u, "cache_read_input_tokens") for u in us)
            s["sortie"] = sum(champ(u, "output_tokens") for u in us)
            s["base_relue"] = min(s["ctx_debut"] * (len(us) - 1), s["lecture"] - s["lecture_ouverture"])
        lignes.append(s)

    def somme(cle):
        return sum(s[cle] for s in lignes)

    poids = {
        "ouverture": somme("ecriture_ouverture") * POIDS_ECRITURE_CACHE + somme("lecture_ouverture") * POIDS_LECTURE_CACHE,
        "base_relue": somme("base_relue") * POIDS_LECTURE_CACHE,
        "croissance": somme("entree") + (somme("ecriture") - somme("ecriture_ouverture")) * POIDS_ECRITURE_CACHE
        + (somme("lecture") - somme("lecture_ouverture") - somme("base_relue")) * POIDS_LECTURE_CACHE,
        "sortie": somme("sortie") * 5.0,
    }
    total = sum(poids.values())
    return {"segments": lignes, "total": {
        "poids": {k: round(v) for k, v in poids.items()},
        "parts": {k: round(v / total, 3) for k, v in poids.items()} if total else None,
    }}


def _rapport_facture(chemins) -> int:
    for chemin in chemins:
        r = facture_par_segment(_lire(Path(chemin))[0])
        actifs = [s for s in r["segments"] if s["reponses"]]

        def mediane(cle):
            return sorted(s[cle] for s in actifs)[len(actifs) // 2] if actifs else None

        print("== %s : %d segment(s), %d avec reponses" % (Path(chemin).name[:8], len(r["segments"]), len(actifs)))
        print("   parts (ouverture, base_relue, croissance, sortie) : %s" % json.dumps(r["total"]["parts"]))
        print("   poids : %s" % json.dumps(r["total"]["poids"]))
        print("   medianes : reponses %s, ctx_debut %s, ecriture_ouverture %s, sortie %s"
              % (mediane("reponses"), mediane("ctx_debut"), mediane("ecriture_ouverture"), mediane("sortie")))
    return 0


def simuler_plafond(entrees, plafond: int, reprise: int = 40_000) -> dict:
    """Lecture cache si le contexte retombait a `reprise` tokens en depassant `plafond` : dents de scie rejouees sur
    les increments reels. BORNE OPTIMISTE : ignore ce que la session devrait relire apres une reprise."""
    par_id = {}
    for i, e in enumerate(entrees):
        m = e.get("message") if isinstance(e, dict) else None
        u = m.get("usage") if isinstance(m, dict) else None
        if isinstance(u, dict):
            par_id[m.get("id") or i] = int(u.get("cache_read_input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0)
    reel, simule, courant, precedent, reprises = 0, 0, reprise, None, 0
    for ctx in par_id.values():
        reel += ctx
        courant += max(0, ctx - precedent) if precedent is not None else 0
        precedent = ctx
        if courant > plafond:
            courant, reprises = reprise, reprises + 1
        simule += courant
    return {"plafond": plafond, "reprises": reprises, "reel": reel, "simule": simule,
            "gain_pct": round(100.0 * (1 - simule / reel), 1) if reel else None}


def _chemin_lu(bloc) -> str:
    """Chemin normalise d'un appel de lecture, vide sinon."""
    nom = str(bloc.get("name") or "").rsplit("__", 1)[-1]
    if nom not in ("Read", "read", "read_function_body", "get_file_skeleton"):
        return ""
    entree = bloc.get("input") or {}
    return str(entree.get("file_path") or entree.get("path") or "").replace("\\", "/").lower()


def relectures_apres_compaction(entrees, fenetre: int = 60) -> list:
    """Par compaction reelle : combien de fichiers deja lus sont relus dans les `fenetre` appels qui suivent, et leur
    volume. Plancher du cout de reprise, pas une mesure de perte : ne pas relire ne prouve pas qu'on n'en avait pas besoin."""
    lus, bilans, attente, courant = set(), [], {}, None
    for e in entrees:
        if not isinstance(e, dict):
            continue
        if e.get("type") == "system" and e.get("subtype") == "compact_boundary":
            courant = {"lus_avant": len(lus), "relus": set(), "car_relus": 0, "appels": 0}
            bilans.append(courant)
            continue
        m = e.get("message")
        contenu = m.get("content") if isinstance(m, dict) else None
        if not isinstance(contenu, list):
            continue
        for b in contenu:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                chemin = _chemin_lu(b)
                if courant is not None and courant["appels"] < fenetre:
                    courant["appels"] += 1
                    if chemin and chemin in lus:
                        courant["relus"].add(chemin)
                        attente[b.get("id")] = courant
                if chemin:
                    lus.add(chemin)
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in attente:
                attente.pop(b["tool_use_id"])["car_relus"] += len(str(b.get("content") or ""))
    return [dict(x, relus=len(x["relus"])) for x in bilans]


def _rapport_relectures(chemins) -> int:
    fichiers = []
    for c in chemins:
        p = Path(c)
        fichiers += sorted(p.glob("*.jsonl"), key=lambda f: f.stat().st_mtime)[-60:] if p.is_dir() else [p]
    bilans = [b for f in fichiers for b in relectures_apres_compaction(_lire(f)[0])]
    print("%d transcription(s), %d compaction(s)" % (len(fichiers), len(bilans)))
    if bilans:
        n = len(bilans)
        print("par compaction : fichiers lus avant %.0f, relus %.1f, car relus %.0f, appels observes %.0f" % (
            sum(b["lus_avant"] for b in bilans) / n, sum(b["relus"] for b in bilans) / n,
            sum(b["car_relus"] for b in bilans) / n, sum(b["appels"] for b in bilans) / n))
        print("sans aucune relecture : %d/%d" % (sum(1 for b in bilans if not b["relus"]), n))
    return 0


def _lignes_listing(texte: str):
    """Decoupe un `skill_listing` en (skill, caracteres), la suite d'une description comptee avec sa skill."""
    courant = None
    for ligne in str(texte or "").splitlines(keepends=True):
        if ligne.startswith("- "):
            if courant:
                yield courant
            courant = [ligne[2:].split(":  ")[0].split(": ")[0].strip(), 0]
        if courant:
            courant[1] += len(ligne)
    if courant:
        yield courant


def poids_reinjections(entrees) -> list:
    """Nom par nom, ce qui revient dans le contexte : skills listees ou invoquees, fichiers d'instructions, memoires
    imbriquees, fichiers recharges. Caracteres cumules sur la transcription, en brut : le poids dans le cache depend du
    nombre de tours relus, que `analyser` calcule par source et non par nom."""
    cumul = {}

    def ajouter(genre, nom, car):
        c = cumul.setdefault((genre, str(nom or "?")), [0, 0])
        c[0] += 1
        c[1] += car

    def taille(v):
        return len(v) if isinstance(v, str) else len(json.dumps(v, ensure_ascii=False))

    for e in entrees:
        a = e.get("attachment") if isinstance(e, dict) else None
        if not isinstance(a, dict):
            continue
        genre = a.get("type")
        if genre == "skill_listing":
            for nom, car in _lignes_listing(a.get("content")):
                ajouter(genre, nom, car)
        elif genre == "instructions":
            for f in a.get("files") or []:
                ajouter(genre, f.get("path"), taille(f))
        elif genre == "nested_memory":
            ajouter(genre, a.get("path"), taille(a))
        elif genre == "file":
            ajouter(genre, a.get("filename"), taille(a))
        elif genre == "invoked_skills":
            for s in a.get("skills") or []:
                ajouter(genre, s.get("name"), taille(s))
    lignes = [{"genre": g, "nom": n, "occurrences": o, "car": c} for (g, n), (o, c) in cumul.items()]
    return sorted(lignes, key=lambda x: -x["car"])


def _rapport_reinjections(chemins, sortie=None, top=25) -> int:
    rapport = {}
    for c in chemins:
        lignes = poids_reinjections(_lire(Path(c))[0])
        rapport[Path(c).name] = lignes
        print("%s : %d nom(s), %d caracteres" % (Path(c).name, len(lignes), sum(x["car"] for x in lignes)))
        for x in lignes[:top]:
            print("%-15s %8d car %4d occ  %s" % (x["genre"], x["car"], x["occurrences"], x["nom"]))
    if sortie:
        Path(sortie).write_text(json.dumps(rapport, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("transcriptions", nargs="*")
    p.add_argument("--reinjections", action="store_true", help="poids nom par nom des skills et fichiers reinjectes")
    p.add_argument("--schemas-mcp", metavar="MCP_CONFIG",
                   help="poids des schemas d'outils (tools/list) d'un --mcp-config, au lieu d'une transcription")
    p.add_argument("--serveur", help="serveur du --mcp-config (defaut : le premier)")
    p.add_argument("--sortie", help="fichier JSON du rapport (un rapport par transcription)")
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--par-demande", action="store_true",
                   help="volume rendu par les outils entre deux messages de l'owner (fichiers ou dossiers)")
    p.add_argument("--usage", action="store_true", help="tokens rapportes par l'API (entree, cache, sortie) par transcription")
    p.add_argument("--ventilation-cout", action="store_true",
                   help="ventilation des couts tokens par session (notification vs owner, top 5)")
    p.add_argument("--relectures", action="store_true", help="fichiers relus apres chaque compaction (fichiers ou dossiers)")
    p.add_argument("--sorties-outils", action="store_true", help="concentration des sorties par outil, gain d'un plafond")
    p.add_argument("--facture-segments", action="store_true",
                   help="facture API par segment de compaction : ouverture, base relue, croissance, sortie")
    a = p.parse_args(argv)
    if a.facture_segments:
        return _rapport_facture(a.transcriptions)
    if a.sorties_outils:
        return _rapport_sorties_outils(a.transcriptions, a.top)
    if a.reinjections:
        return _rapport_reinjections(a.transcriptions, a.sortie, a.top)
    if a.relectures:
        return _rapport_relectures(a.transcriptions)
    if a.usage:
        for chemin in a.transcriptions:
            entrees = _lire(Path(chemin))[0]
            print("%s %s" % (Path(chemin).name[:8], json.dumps(usage_reel(entrees))))
            for plafond in (100_000, 200_000, 400_000):
                print("  simulation %s" % json.dumps(simuler_plafond(entrees, plafond)))
        return 0
    if a.ventilation_cout:
        rapports = []
        for chemin in a.transcriptions:
            entrees = _lire(Path(chemin))[0]
            v = ventiler_cout(entrees)
            v["transcription"] = str(chemin)
            rapports.append(v)
            print(json.dumps(v, ensure_ascii=False, indent=2))
        if a.sortie:
            donnees = rapports[0] if len(rapports) == 1 else rapports
            Path(a.sortie).write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    if a.par_demande:
        return _rapport_par_demande(a.transcriptions)
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
