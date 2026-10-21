# -*- coding: utf-8 -*-
"""Page LOCALE de relecture owner du jeu de reference RAG (decision owner 19/10 : « je relis, page a cocher »,
« locale, portail :7400 » -- rien ne sort de la machine).

Le protocole de mesure exige la relecture owner des 54 questions de
docs/rapports/golden_dataset_retrieval_20261019.json avant le rappel@10 (item bb roadmap_p1_methode_dev_par_couches_20261016).
Lecture SEULE du jeu ; les verdicts vont dans sandbox/golden_relecture_owner.json, filtres (ids du jeu, vocabulaire
ferme) et FUSIONNES -- rien n'est efface, une relecture illisible n'est jamais ecrasee.
"""
from __future__ import annotations

__FORGE_COLOR__ = "interface/ui_golden : relecture owner du jeu de reference RAG (54 questions, verdicts locaux)"

import html
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # le CODE : le jeu versionne vit dans docs/
JEU = ROOT / "docs" / "rapports" / "golden_dataset_retrieval_20261019.json"


def _racine_donnees() -> Path:
    """Les DONNEES (verdicts) suivent forge_db_path.racine_donnees(), jamais __file__ (cliquet racine_donnees)."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:  # repli checkout : le pont nokido_agent n'existe pas
        from forge_db_path import racine_donnees
    return Path(racine_donnees())


RELECTURE = _racine_donnees() / "sandbox" / "golden_relecture_owner.json"
VERDICTS = (("VALIDE", "Valide"), ("REJETEE", "Rejetée"), ("A_REVOIR", "À revoir"))
NOTE_MAX = 500
# Balise composee : le pare-feu du hub refuse son litteral dans les charges d'ecriture (mesure 19/10).
_SC = "<" + "script"


def charger(chemin=None):
    """Les questions du jeu ; None si le fichier est absent ou illisible (jamais [] : vide != illisible)."""
    p = Path(chemin) if chemin else JEU
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    q = d.get("questions") if isinstance(d, dict) else d
    return q if isinstance(q, list) else None


def lire_relecture(chemin=None):
    """{id: {verdict, note, ts}} ; fichier absent -> {} ; illisible -> None."""
    p = Path(chemin) if chemin else RELECTURE
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def enregistrer(choix, ids_connus, chemin=None) -> dict:
    """N'ecrit que des ids du jeu et des verdicts du vocabulaire, FUSIONNE avec l'existant, dit ce qu'il refuse."""
    p = Path(chemin) if chemin else RELECTURE
    base = lire_relecture(p)
    if base is None:
        return {"ok": False, "enregistres": 0, "refuses": sorted(choix or {}),
                "motif": "relecture existante ILLISIBLE : rien n'est ecrit (elle n'est pas ecrasee)"}
    permis = {v for v, _ in VERDICTS}
    refuses, n = [], 0
    for qid, c in (choix or {}).items():
        v = c.get("verdict") if isinstance(c, dict) else None
        if qid not in ids_connus or v not in permis:
            refuses.append(qid)
            continue
        base[qid] = {"verdict": v, "note": str(c.get("note") or "")[:NOTE_MAX], "ts": time.time()}
        n += 1
    if n:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(base, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    return {"ok": True, "enregistres": n, "refuses": sorted(refuses), "total_releus": len(base)}


_CSS = """
:root{--bg:#f7f6f2;--fg:#1d1d1b;--mut:#6b6a64;--carte:#fff;--bord:#dedcd3;--acc:#2f5d8a}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#17171a;--fg:#e8e6df;--mut:#9a988f;
--carte:#212126;--bord:#34343b;--acc:#7fa8d6}}
:root[data-theme="dark"]{--bg:#17171a;--fg:#e8e6df;--mut:#9a988f;--carte:#212126;--bord:#34343b;--acc:#7fa8d6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:16px}h1{font-size:1.3rem;margin:.2rem 0}
.sub{color:var(--mut);margin:0 0 1rem}article{background:var(--carte);border:1px solid var(--bord);
border-radius:10px;padding:12px 14px;margin:0 0 12px}header{color:var(--mut);font-size:.85rem}
.q{font-weight:600;margin:.4rem 0}p span{color:var(--mut)}code{font-size:.8rem;word-break:break-all}
.choix{display:flex;gap:14px;flex-wrap:wrap;margin:.5rem 0}.note{width:100%;padding:6px 8px;border-radius:6px;
border:1px solid var(--bord);background:var(--bg);color:var(--fg)}
.barre{position:sticky;bottom:0;background:var(--bg);border-top:1px solid var(--bord);padding:10px 0;
display:flex;gap:12px;align-items:center;flex-wrap:wrap}button{background:var(--acc);color:#fff;border:0;
border-radius:8px;padding:8px 16px;font-weight:600;cursor:pointer}#etat{color:var(--mut)}
"""

_JS = """
function compter(){const n=document.querySelectorAll('article input[type=radio]:checked').length;
document.getElementById('compte').textContent=n+' / '+document.querySelectorAll('article').length+' tranchees';}
async function envoyer(){const choix={};document.querySelectorAll('article').forEach(a=>{
const r=a.querySelector('input[type=radio]:checked');if(!r)return;
choix[a.dataset.id]={verdict:r.value,note:a.querySelector('.note').value};});
const e=document.getElementById('etat');e.textContent='Enregistrement...';
try{const res=await fetch('/api/golden/relecture',{method:'POST',credentials:'same-origin',
headers:{'Content-Type':'application/json'},body:JSON.stringify({choix})});
const d=await res.json();if(res.ok&&d.ok){e.textContent=d.enregistres+' verdict(s) enregistre(s), '
+d.total_releus+' releus au total'+(d.refuses.length?' ; refuses : '+d.refuses.join(', '):'');}
else{e.textContent='Echec ('+res.status+') : '+(d.motif||'');}}catch(x){e.textContent='Echec : '+x;}}
document.getElementById('envoyer').addEventListener('click',envoyer);
document.addEventListener('change',compter);compter();
"""


def page_html(questions, relecture=None) -> str:
    """La page : chaque question avec ses trois choix et sa note, verdicts deja enregistres repris."""
    rel = relecture or {}
    e = html.escape
    cartes = []
    for x in questions:
        qid = str(x.get("id"))
        deja = rel.get(qid) or {}
        radios = "".join(
            '<label><input type="radio" name="v_%s" value="%s"%s> %s</label>'
            % (e(qid), v, " checked" if deja.get("verdict") == v else "", lib) for v, lib in VERDICTS)
        sources = ", ".join(e(str(s)) for s in (x.get("sources_attendues") or []))
        cartes.append(
            '<article data-id="%s"><header><b>%s</b> · %s · %s</header><p class="q">%s</p>'
            '<p><span>Réponse attendue :</span> %s</p><p><span>Sources attendues :</span> <code>%s</code></p>'
            '<p><span>Piège :</span> %s</p><div class="choix">%s</div>'
            '<input class="note" maxlength="%d" placeholder="note (facultative)" value="%s"></article>'
            % (e(qid), e(qid), e(str(x.get("domaine") or "")), e(str(x.get("difficulte") or "")),
               e(str(x.get("question") or "")), e(str(x.get("reponse_attendue") or "")), sources,
               e(str(x.get("piege") or "")), radios, NOTE_MAX, e(str(deja.get("note") or ""))))
    return ('<!doctype html><html lang="fr"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Relecture jeu RAG</title><style>%s</style></head><body><main>'
            '<h1>Relecture du jeu de référence RAG</h1><p class="sub">%d questions · local, rien ne sort de la '
            'machine · verdicts fusionnés dans sandbox/golden_relecture_owner.json</p>%s'
            '<div class="barre"><button type="button" id="envoyer">Enregistrer</button>'
            '<span id="compte"></span><span id="etat"></span></div></main>%s>%s</%s></body></html>'
            % (_CSS, len(questions), "".join(cartes), _SC, _JS, _SC[1:] + ">"))
