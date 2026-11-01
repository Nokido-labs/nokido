# -*- coding: utf-8 -*-
"""Front ACP du web hub : sessions, flux, permissions.

Lit les journaux de tools/forge_acp_router.py (logs/acp_router/<session>.jsonl) et la file
sandbox/acp_permissions/<id>.json. Seule ecriture : la decision d'une permission, deleguee a
forge_acp_router.decider(). Cette ecriture exige un jeton ADMIN, sans derogation loopback :
un agent local ne doit pas approuver sa propre demande.

Livraison CLAUDE_HEADLESS f18445701 (ROUGE 4a468da9a), integree par governed_edit.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

log = logging.getLogger("nokido.hub.acp")

router = APIRouter()

ROOT = Path(__file__).resolve().parents[2]   # CODE (tools/) : suit le paquet


def _racine_donnees() -> Path:
    """Les DONNEES (journaux, permissions, tasks.db) suivent forge_db_path.racine_donnees(), jamais
    __file__ (cliquet racine_donnees)."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:
        from forge_db_path import racine_donnees
    return racine_donnees()


_DONNEES = _racine_donnees()
LOG_DIR = _DONNEES / "logs" / "acp_router"
PERMISSIONS_DIR = _DONNEES / "sandbox" / "acp_permissions"
TASKS_DB = _DONNEES / "sandbox" / "tasks.db"  # taches ANTIGRAVITY (hors ACP), lues en lecture seule
MAX_LECTURE = 2 * 1024 * 1024  # octets lus au plus par journal
_BLOC = 64 * 1024
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")


def _id_valide(ident: str) -> bool:
    return bool(ident) and ".." not in ident and bool(_ID_RE.match(ident))


def _est_admin(request: Request) -> bool:
    """Owner prouve, aucune exception d'adresse source : jeton admin brut, OU session JWT (delivree seulement
    apres login au jeton admin) REVERIFIEE ici -- jamais l'en-tete X-LaForge-User. Auth desactivee = refus.
    Recette owner 28/10 : le jeton brut seul rendait 401 a la session du navigateur."""
    from app.web_hub import app as hub  # import tardif : app.py inclut ce module

    jeton = hub.extract_token(dict(request.headers), request.cookies)
    if not jeton:
        return False
    if hub.admin_token_ok(hub.AUTH_CFG, jeton):
        return True
    if not getattr(hub.AUTH_CFG, "enabled", False):
        return False
    return bool(hub.verify_token(hub.AUTH_CFG, jeton))


def _par_cookie(request: Request) -> bool:
    """Vrai si l'authentification vient du cookie de session (navigateur), pas d'un en-tete Authorization."""
    if not request.cookies:
        return False
    from app.web_hub import app as hub  # import tardif : app.py inclut ce module

    nom = getattr(hub, "_COOKIE_NAME", None)
    if not nom or nom not in request.cookies:
        return False
    return not (request.headers.get("authorization") or "").strip()


def _meme_origine(request: Request) -> bool:
    """Defense CSRF d'une ecriture authentifiee par cookie (owner 28/10 « conforme RFC, n'abaisse pas la
    securite ») : SameSite=Lax ne protege pas d'une page servie sur 127.0.0.1:<autre port> (meme SITE). Origine
    EXACTE exigee (RFC 6454 : schema + hote + port) et Fetch Metadata `Sec-Fetch-Site: same-origin` si present."""
    origine = (request.headers.get("origin") or "").strip().rstrip("/").lower()
    if not origine or origine == "null":
        return False
    attendu = f"{request.url.scheme}://{request.headers.get('host') or request.url.netloc}".lower()
    if origine != attendu:
        return False
    sfs = request.headers.get("sec-fetch-site")
    return sfs is None or sfs.strip().lower() == "same-origin"


def _lire_queue(path, n: int) -> list:
    """n dernieres lignes JSON, lues depuis la fin, au plus MAX_LECTURE octets."""
    n = max(1, int(n))
    with open(path, "rb") as f:
        f.seek(0, 2)
        pos = f.tell()
        buf = b""
        lu = 0
        while pos > 0 and lu < MAX_LECTURE and buf.count(b"\n") <= n:
            taille = min(_BLOC, pos, MAX_LECTURE - lu)
            pos -= taille
            f.seek(pos)
            buf = f.read(taille) + buf
            lu += taille
    lignes = buf.split(b"\n")
    if pos > 0:
        lignes = lignes[1:]  # premiere ligne probablement tronquee
    out = []
    for brut in lignes[-(n + 1):]:
        if not brut.strip():
            continue
        try:
            out.append(json.loads(brut.decode("utf-8", "replace")))
        except ValueError:
            log.warning("ligne de journal illisible ignoree dans %s", path)
    return out[-n:]


def _compter_lignes(path) -> int:
    """Comptage par blocs de 64 Ko : memoire constante."""
    total = 0
    with open(path, "rb") as f:
        while True:
            bloc = f.read(_BLOC)
            if not bloc:
                return total
            total += bloc.count(b"\n")


@router.get("/api/acp/sessions")
async def api_sessions():
    out = []
    for p in sorted(LOG_DIR.glob("*.jsonl")) if LOG_DIR.is_dir() else []:
        try:
            der = _lire_queue(p, 1)
            out.append({"session": p.stem, "agent": der[0].get("agent") if der else None,
                        "dernier_ts": der[0].get("ts") if der else None,
                        "lignes": _compter_lignes(p)})
        except OSError:
            log.exception("journal illisible : %s", p)
    from app.web_hub import acp_harness

    acp_harness.DB_PATH = TASKS_DB
    out.extend(acp_harness.sessions_agy())
    return JSONResponse({"sessions": out})


@router.get("/api/acp/sessions/{sid}")
async def api_session(sid: str, n: int = 200):
    if not _id_valide(sid):
        return JSONResponse({"erreur": "identifiant invalide"}, status_code=400)
    p = LOG_DIR / f"{sid}.jsonl"
    n = min(max(n, 1), 1000)
    if not p.is_file():
        from app.web_hub import acp_harness

        acp_harness.DB_PATH = TASKS_DB
        agy = acp_harness.session_agy(sid, n)
        if agy is not None:
            return JSONResponse(agy)
        return JSONResponse({"erreur": "session inconnue"}, status_code=404)
    return JSONResponse({"session": sid, "lignes": _lire_queue(p, n)})


def _en_attente() -> list:
    out = []
    for p in sorted(PERMISSIONS_DIR.glob("*.json")) if PERMISSIONS_DIR.is_dir() else []:
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("permission illisible ignoree : %s", p)
            continue
        if isinstance(j, dict) and j.get("etat") == "EN_ATTENTE":
            out.append(j)
    return out


@router.get("/api/acp/permissions")
async def api_permissions():
    return JSONResponse({"permissions": _en_attente()})


@router.post("/api/acp/permissions/{pid}")
async def api_decider(pid: str, request: Request):
    if not _est_admin(request):
        return JSONResponse({"erreur": "jeton admin requis"}, status_code=401)
    if not _id_valide(pid):
        return JSONResponse({"erreur": "identifiant invalide"}, status_code=400)
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype != "application/json":
        # JSON strict : un formulaire ou un text/plain d'une autre origine passe sans preflight CORS
        return JSONResponse({"erreur": "Content-Type application/json exige"}, status_code=415)
    if _par_cookie(request) and not _meme_origine(request):
        return JSONResponse({"erreur": "origine refusee (CSRF) : meme origine exigee"}, status_code=403)
    try:
        corps = await request.json()
    except ValueError:
        return JSONResponse({"erreur": "JSON invalide"}, status_code=400)
    if not isinstance(corps, dict):
        return JSONResponse({"erreur": "objet JSON attendu"}, status_code=400)
    chemin = PERMISSIONS_DIR / f"{pid}.json"
    try:
        demande = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return JSONResponse({"erreur": "demande introuvable"}, status_code=404)
    refuser = bool(corps.get("refuser"))
    option = corps.get("option")
    ids = {o.get("optionId") for o in demande.get("options", []) if isinstance(o, dict)}
    if not refuser and option not in ids:
        return JSONResponse({"erreur": "option non annoncee", "options": sorted(map(str, ids))},
                            status_code=400)
    tools_dir = str(ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import forge_acp_router as R

    from app.web_hub import app as hub  # import tardif

    jeton = hub.extract_token(dict(request.headers), request.cookies)  # celui que _est_admin a verifie
    # repli direct seulement si CE processus lit la cle (hub SYSTEM) ; sinon le hub :8766 signe apres revérification
    signer = R.signer_hub if R._importer_hub().cle_signature() else R.signer_par_hub(jeton)
    try:
        decision = R.decider(pid, option=None if refuser else option, refuser=refuser,
                             dossier=PERMISSIONS_DIR, signer=signer)
    except ValueError as e:
        return JSONResponse({"erreur": str(e)}, status_code=409)
    except RuntimeError as e:  # cle privee du hub illisible depuis ce compte : decision NON ecrite
        return JSONResponse({"erreur": f"signature impossible : {e}"}, status_code=503)
    return JSONResponse({"ok": True, "decision": decision})


_PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>ACP</title>
<style>
body{font:13px sans-serif;margin:8px;background:#111;color:#ddd}
#perms .p{border:1px solid #c80;padding:6px;margin:4px 0}
#sessions{display:flex;gap:8px;overflow-x:auto}
.s{flex:1 0 320px;border:1px solid #444;padding:6px}
pre{white-space:pre-wrap;word-break:break-all;margin:2px 0;font-size:12px}
button{margin-right:4px}
</style></head><body>
<h1>ACP</h1>
<h2>Permissions en attente</h2><div id="perms"></div>
<p>Sessions AGY : taches ANTIGRAVITY de tasks.db (AGY ne parle pas ACP), lecture seule. AGY n'emet pas de permission.</p>
<h2>Sessions</h2><div id="sessions"></div>
@@OPEN@@
function el(tag, text, cls){var e=document.createElement(tag);
  if(text!==undefined){e.textContent=String(text);} if(cls){e.className=cls;} return e;}
async function jget(u){var r=await fetch(u,{credentials:'same-origin'});
  if(!r.ok){throw new Error(u+' '+r.status);} return r.json();}
async function decider(id,body){
  var r=await fetch('/api/acp/permissions/'+encodeURIComponent(id),{method:'POST',
    credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!r.ok){alert('Refuse: '+r.status);} tick();}
function permission(p){
  var d=el('div',undefined,'p');
  d.appendChild(el('div',(p.agent||'?')+' / '+(p.session||'?')));
  d.appendChild(el('pre',JSON.stringify(p.request,null,1)));
  (p.options||[]).forEach(function(o){
    var b=el('button',o.name||o.optionId);
    b.addEventListener('click',function(){decider(p.id,{option:o.optionId});});
    d.appendChild(b);});
  var n=el('button','Refuser');
  n.addEventListener('click',function(){decider(p.id,{refuser:true});});
  d.appendChild(n); return d;}
async function tick(){
  try{
    var perms=(await jget('/api/acp/permissions')).permissions;
    var pd=document.getElementById('perms');
    pd.replaceChildren.apply(pd,perms.map(permission));
    var ss=(await jget('/api/acp/sessions')).sessions;
    var cols=[];
    for(var i=0;i<ss.length;i++){
      var s=ss[i];
      var c=el('div',undefined,'s');
      c.appendChild(el('b',s.session+' ('+(s.agent||'?')+', '+s.lignes+' lignes'+(s.etat?', '+s.etat:'')+')'));
      try{
        var fl=(await jget('/api/acp/sessions/'+encodeURIComponent(s.session)+'?n=20')).lignes;
        fl.forEach(function(l){c.appendChild(el('pre',
          new Date(l.ts*1000).toISOString()+' '+l.kind+' '+JSON.stringify(l.payload)));});
      }catch(e){c.appendChild(el('pre','erreur: '+e.message));}
      cols.push(c);}
    var sd=document.getElementById('sessions');
    sd.replaceChildren.apply(sd,cols);
  }catch(e){document.getElementById('perms').replaceChildren(el('pre','erreur: '+e.message));}
}
tick(); setInterval(tick, 3000);
@@CLOSE@@</body></html>
""".replace("@@OPEN@@", "<scr" + "ipt>").replace("@@CLOSE@@", "</scr" + "ipt>")


@router.get("/acp", response_class=HTMLResponse)
async def page_acp():
    return HTMLResponse(_PAGE)
