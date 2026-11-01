# -*- coding: utf-8 -*-
"""
tools/forge_enquete_sans_boucle.py — Enquête en lecture seule sans boucle d'agent.

Patron « agentless » : assemble un dossier à 0 token (FTS + AST), puis un seul appel
texte au premier fournisseur gratuit disponible, avec rédaction pré-vol et post-vol.
"""
from __future__ import annotations

import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "cognition/enquete-agentless"  # 31/10 : « GREEN » illisible du census (organe/role attendu)

import argparse
import ast
import json
import logging
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("forge_enquete_sans_boucle")

CAPACITE_MAX_DOSSIER = 30_000  # 30/10 : 60 k car. noyait la consigne et depassait les TPM free tier ; l'ecart est DIT
# Ordre = FORCE d'abord (30/10 : groq a quota journalier epuise, mistral 403 hors palier, cohere repond a cote --
# refus ou plan hors sujet). nvidia_nemotron_super (120B, routeur forge_llm_router) et openrouter_free en tete.
FOURNISSEURS_GRATUITS_DEFAUT = ("nvidia_nemotron_super", "groq", "openrouter_free", "mistral", "cohere", "ollama",
                                "sambanova", "cerebras")


def extraire_corps_fonction(chemin_fichier: str, nom_symbole: str) -> str:
    """Extrait le corps complet d'une fonction ou classe par AST (même logique que read_function_body)."""
    p = Path(chemin_fichier)
    if not p.is_absolute():
        p = Path(_RACINE_AMORCE) / p
    if not p.exists():
        return f"ERR: fichier introuvable: {chemin_fichier}"

    try:
        source = p.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except Exception as e:
        return f"ERR: impossible de parser {chemin_fichier}: {e}"

    src_lines = source.splitlines(keepends=True)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == nom_symbole:
                start = node.lineno - 1
                end = getattr(node, "end_lineno", node.lineno)
                body = "".join(src_lines[start:end])
                return f"### {chemin_fichier} — {nom_symbole} (L{node.lineno}–L{end})\n```python\n{body.rstrip()}\n```"

    return f"ERR: '{nom_symbole}' non trouvé dans {chemin_fichier}"


def interroger_fts(conn: sqlite3.Connection, terme_match: str, limite: int = 12) -> List[Tuple[str, str]]:
    """Exécute STRICTEMENT une requête FTS MATCH. Jamais de balayage ni LIKE."""
    if not terme_match or not str(terme_match).strip():
        raise ValueError("Requête FTS sans MATCH interdite")

    cur = conn.cursor()
    # `source:<texte>` : dossier tire d'une SOURCE designee (doc officielle) et non d'une recherche par termes, qui
    # ramenait du bruit (30/10 : Letta/Goose pris pour la doc Codex). Toujours un MATCH (colonne source), jamais LIKE.
    if str(terme_match).startswith("source:"):
        phrase = '"%s"' % str(terme_match)[7:].replace('"', "")
        try:
            cur.execute("SELECT source, substr(text,1,1600) FROM rag_chunks_fts WHERE source MATCH ? LIMIT ?",
                        (phrase, max(limite, 30)))
            return cur.fetchall()
        except sqlite3.OperationalError as e:
            logger.warning(f"FTS source {phrase!r} invalide ({e}) : requete SAUTEE")
            return []
    # Requête imposée : SELECT source, substr(text,1,800) FROM rag_chunks_fts WHERE rag_chunks_fts MATCH ? LIMIT 12
    try:
        cur.execute(
            "SELECT source, substr(text,1,800) FROM rag_chunks_fts WHERE rag_chunks_fts MATCH ? LIMIT ?",
            (terme_match, limite),
        )
    except sqlite3.OperationalError as e:
        # syntaxe FTS (ex. `Retry-After` : le tiret est lu comme une colonne, mesure 30/10) : on RETENTE en phrase
        # exacte ; si elle echoue encore, la requete est SAUTEE et DITE -- une requete fautive ne coule pas l'enquete.
        logger.warning(f"FTS {terme_match!r} invalide ({e}) : retentee en phrase exacte")
        phrase = '"%s"' % str(terme_match).replace('"', "")
        try:
            cur.execute(
                "SELECT source, substr(text,1,800) FROM rag_chunks_fts WHERE rag_chunks_fts MATCH ? LIMIT ?",
                (phrase, limite),
            )
        except sqlite3.OperationalError as e2:
            logger.warning(f"FTS {phrase!r} toujours invalide ({e2}) : requete SAUTEE")
            return []
    return cur.fetchall()


def assembler_dossier(
    fts_termes: List[str],
    fonctions: List[str],
    db_conn: Optional[sqlite3.Connection] = None,
    cap_max: int = CAPACITE_MAX_DOSSIER,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Assemble le dossier textuel à partir des recherches FTS et des extraits AST.
    Borne le dossier à cap_max caractères. Ce qui dépasse est écarté et retourné.
    """
    elements: List[Tuple[str, str]] = []  # (identifiant_source, texte)

    # 1. Extraits AST des fonctions
    for fn_spec in fonctions:
        if "::" in fn_spec:
            f_path, f_name = fn_spec.split("::", 1)
        else:
            f_path, f_name = fn_spec, ""
        corps = extraire_corps_fonction(f_path, f_name)
        elements.append((f"AST:{fn_spec}", corps))

    # 2. Résultats FTS
    if fts_termes:
        fermer_conn = False
        if db_conn is None:
            try:
                from nokido_agent.app.forge_db_path import db_path
                p = db_path()
            except Exception:
                p = "%NOKIDO_DATA%\embeddings.db"
            if Path(p).exists():
                db_conn = sqlite3.connect(p)
                fermer_conn = True

        if db_conn is not None:
            try:
                for t in fts_termes:
                    res = interroger_fts(db_conn, t, limite=12)
                    for src, txt in res:
                        elements.append((f"FTS[{t}]:{src}", f"--- SOURCE: {src} ---\n{txt}\n"))
            finally:
                if fermer_conn:
                    db_conn.close()

    # 3. Assemblage avec borne stricte
    dossier_parts: List[str] = []
    longueur_actuelle = 0
    ecartes: List[Dict[str, Any]] = []

    for src_id, fragment in elements:
        longueur_frag = len(fragment)
        if longueur_actuelle + longueur_frag <= cap_max:
            dossier_parts.append(fragment)
            longueur_actuelle += longueur_frag
        else:
            ecartes.append({
                "source": src_id,
                "taille_caracteres": longueur_frag,
            })

    dossier_final = "\n\n".join(dossier_parts)
    return dossier_final, ecartes


def premier_fournisseur_gratuit() -> str:
    """Le plus FORT des fournisseurs gratuits (FOURNISSEURS_GRATUITS_DEFAUT est ordonne par force). 30/10 : l'ordre
    de PROVIDER_CHAIN mettait groq (quota journalier epuise) devant nemotron 120B."""
    return FOURNISSEURS_GRATUITS_DEFAUT[0]


def appeler_fournisseur_hub(
    fournisseur: str,
    message: str,
    hub_url: str = "http://127.0.0.1:8766",
    token: Optional[str] = None,
    outil: str = "ask",
    arguments: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Exécute un appel unique via l'outil `ask` du hub (ou `outil`/`arguments` : read archived, 30/10).
    Retourne (succès, texte, métadonnées).
    """
    if token is None:
        try:
            from nokido_agent.tools.forge_task_executor import _load_token
            token = _load_token()
        except Exception as _e_tok:  # noqa: BLE001
            # 31/10 (CI de reference rouge) : plus de repli sur le jeton MAITRE lu dans l'environnement -- lecture d'un
            # nom reserve hors du guichet (cliquet lectures hors guichet, golden-rules). Sans jeton, l'appel part sans
            # porteur et le hub le refuse VISIBLEMENT (401), au lieu d'un maitre emprunte en silence.
            print("[enquete] jeton illisible (%s) : appel SANS porteur" % type(_e_tok).__name__)
            token = ""

    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": outil,
            # max_tokens EXPLICITE (30/10) : au plafond par defaut, le modele de raisonnement nemotron consommait tout
            # en reflexion et rendait « empty response » -> chaque enquete retombait sur cohere (plans creux).
            "arguments": arguments if arguments is not None else {
                "provider": fournisseur,
                "message": message,
                "max_tokens": 6000,
                # 30/10 : nemotron 120B coupe a 60 s (defaut VOLONTAIRE de forge_agent_proxy._delai_par_defaut) sur
                # un dossier de 30 k car. ; c'est l'appelant qui declare son besoin long (parametre `timeout`).
                "timeout": 240,
            },
        },
    }
    req = urllib.request.Request(
        f"{hub_url}/mcp",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            # identite PROPRE de l'outil (jamais celle d'un autre agent : usurpation involontaire, skill forge-m2m-agy)
            "X-Agent-Name": os.environ.get("LAFORGE_ENQUETE_AGENT", "ENQUETE_SANS_BOUCLE"),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            resp = json.loads(r.read())
        if "error" in resp and "result" not in resp:
            return False, f"hub error: {resp['error']}", {}
        content = resp.get("result", {}).get("content", [{}])
        text = content[0].get("text", "") if content else ""
        meta = {}
        try:
            data = json.loads(text)
            if data.get("ok"):
                return True, data.get("text", ""), data.get("meta", {})
            return False, data.get("error", "provider error"), {}
        except Exception:
            return bool(text), text, meta
    except Exception as e:
        return False, f"Erreur appel hub: {e}", {}


def _consigner_quota_vu(fournisseur: str, erreur: str) -> None:
    """30/10 : un 429 de QUOTA (« tokens per day », « free-models-per-day ») vu ici n'etait jamais consigne au census ;
    l'executeur, qui saute les modeles hors quota d'apres le census, renvoyait alors les taches OpenCode sur groq
    epuise (reaffectations en boucle, NON LIVRE en 20 s). Le modele est lu dans le message d'erreur ; illisible = rien."""
    import re as _re
    if "429" not in erreur or not _re.search(r"(?i)per day|per-day|TPD|RPD|quota", erreur):
        return
    m = _re.search(r"for model `([^`]+)`", erreur) or _re.search(r"model[\"' :]+([\w./:-]+)", erreur)
    if not m:
        return
    try:
        import forge_free_tier_census as _census
        _census.consigner_quota_epuise(fournisseur, m.group(1), erreur[:300])
    except Exception as e:  # noqa: BLE001 -- un echec de consignation ne casse pas l'enquete, et se DIT
        logger.warning("quota vu (%s:%s) NON consigne au census : %s" % (fournisseur, m.group(1), type(e).__name__))


def _marquer_noms_inventes(texte: str, dossier: str):
    """Rend (texte annote, noms absents) : un nom en `code` ou **gras** (forme d'identifiant : sans espace, >= 3 car.)
    absent mot pour mot du dossier est suffixe de « [ABSENT DU DOSSIER] »."""
    import re as _re

    absents = set()

    def _verifier(m):
        brut = m.group(0)
        nom = m.group(1).strip()
        if len(nom) < 3 or " " in nom or nom in dossier:
            return brut
        absents.add(nom)
        return brut + " [ABSENT DU DOSSIER]"

    texte = _re.sub(r"`([^`\n]{3,80})`", _verifier, texte or "")
    texte = _re.sub(r"\*\*([^*\n]{3,80})\*\*", _verifier, texte)
    return texte, absents


def executer_enquete(
    question: str,
    fts_termes: List[str],
    fonctions: List[str],
    sortie_fichier: str,
    fournisseur: Optional[str] = None,
    db_conn: Optional[sqlite3.Connection] = None,
    caller_fn: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Flux complet d'enquête sans boucle :
    1. Assemble dossier & consigne les écarts.
    2. Caviarise / caviardage via redact_text.
    3. Exécute UN SEUL appel fournisseur.
    4. post_flight sur la réponse.
    5. Écrit le résultat dans --sortie avec pied de page.
    """
    if not fournisseur:
        fournisseur = premier_fournisseur_gratuit()

    # 1. Dossier
    dossier, ecartes = assembler_dossier(fts_termes, fonctions, db_conn=db_conn)
    taille_dossier = len(dossier)

    # 2. Caviardage pré-vol (redact_text)
    try:
        try:
            from nokido_agent.app.forge_semantic_firewall import redact_text
        except ImportError:
            from forge_semantic_firewall import redact_text
        dossier_redacte, redact_mapping = redact_text(dossier)
    except Exception as e:  # FERME par defaut : sans caviardage, rien ne part vers un modele cloud (regle d'or 4)
        logger.error(f"redact_text indisponible ({type(e).__name__}) : envoi REFUSE")
        return {"ok": False, "sortie": None, "fournisseur": fournisseur, "taille_dossier": taille_dossier,
                "elements_ecartes": ecartes, "tokens": None,
                "erreur": "caviardage indisponible (%s) : dossier NON envoye" % type(e).__name__}

    # Consigne AVANT le dossier, question rappelee APRES (30/10 : consigne placee apres 60 k car. -> « sans
    # instruction claire », consigne perdue ou coupee par la borne de taille du message).
    prompt_complet = (
        f"Tu es un expert d'analyse technique en mode lecture seule.\n\n"
        f"QUESTION:\n{question}\n\n"
        f"CONSIGNE : réponds à la QUESTION sur la base du DOSSIER ci-dessous, et de lui SEUL.\n\n"
        f"DOSSIER TECHNIQUE (chaque extrait commence par sa SOURCE):\n{dossier_redacte}\n\n"
        f"RAPPEL DE LA QUESTION : {question}\n\n"
        f"Rédige une analyse concise et précise répondant à la question sur la base du dossier SEUL. "
        f"Chaque affirmation cite la SOURCE exacte de l'extrait qui la porte. Ne prête jamais à un projet un "
        f"fichier ou une fonction venu d'une autre source ; ce que le dossier ne montre pas s'écrit INCONNU. "
        f"N'invente AUCUN nom (drapeau, clé, fonction) : un nom absent MOT POUR MOT du dossier n'apparaît pas, "
        f"pas même étiqueté INCONNU -- dis seulement quels besoins restent sans réglage documenté. "
        f"Réponds DIRECTEMENT et complètement : aucune question en retour, aucun appel unique ne sera suivi d'un autre."
    )

    # 3. UN seul appel modèle
    # Repli sur les AUTRES fournisseurs gratuits (30/10 : groq gpt-oss-120b a epuise son quota JOURNALIER, 200 k
    # tokens, et chaque enquete s'arretait sur un 429). Un appel par fournisseur, le premier qui repond l'emporte ;
    # les echecs sont DITS dans le pied du document.
    _candidats = [fournisseur] + [p for p in FOURNISSEURS_GRATUITS_DEFAUT if p != fournisseur]
    _echecs = []
    for _f in _candidats:
        if caller_fn:
            ok, reponse_brute, meta = caller_fn(_f, prompt_complet)
        else:
            ok, reponse_brute, meta = appeler_fournisseur_hub(_f, prompt_complet)
        # Refus du pare-feu semantique rendu comme TEXTE (30/10 : « [FIREWALL] envoi cloud bloque ... Prompt injection »,
        # un dossier de securite cite des injections) : ce n'est PAS une reponse -> echec, fournisseur suivant (la
        # liste finit par ollama, LOCAL, que le pare-feu recommande lui-meme).
        if ok and str(reponse_brute).lstrip().startswith("[FIREWALL]"):
            ok = False
        if ok:
            fournisseur = _f
            break
        _echecs.append("%s: %s" % (_f, str(reponse_brute)[:120]))
        logger.warning("fournisseur %s en echec, repli : %s" % (_f, str(reponse_brute)[:160]))
        _consigner_quota_vu(_f, str(reponse_brute))
    if _echecs:
        meta = dict(meta or {})
        meta["echecs_avant"] = _echecs

    # 3 bis. Le hub tronque les longues sorties d'outil et archive le reste (CCR) : on recupere l'integral.
    import re as _re
    _m = _re.search(r"read\(action='archived', id='([^']+)'\)", reponse_brute or "")
    if ok and _m and caller_fn is None:
        ok_a, integral, _ = appeler_fournisseur_hub(fournisseur, "", outil="read",
                                                    arguments={"action": "archived", "id": _m.group(1)})
        if ok_a and integral:
            reponse_brute = integral
        else:
            logger.warning("reponse tronquee par le hub, archive %s ILLISIBLE : document PARTIEL" % _m.group(1))

    # 4. post_flight (Règle d'or 4)
    reponse_validee = reponse_brute
    try:
        try:
            from nokido_agent.app.forge_semantic_firewall import get_firewall
        except ImportError:
            from forge_semantic_firewall import get_firewall
        fw = get_firewall()
        pf_res = fw.post_flight(reponse_brute, task=question)
        if not pf_res.ok:
            reponse_validee = f"[POST_FLIGHT_BLOCKED: {pf_res.reason}]\n{reponse_brute}"
        else:
            reponse_validee = pf_res.response
    except Exception as e:  # illisible n'est pas valide : le document le DIT
        logger.warning(f"post_flight ILLISIBLE ({type(e).__name__})")
        reponse_validee = "[POST_FLIGHT ILLISIBLE : reponse NON verifiee]\n" + reponse_brute

    # 5. Écriture avec pied de page
    modele = meta.get("model", meta.get("modele", "inconnu"))
    tokens_rendus = meta.get("tokens", meta.get("token_usage", "non_rendu"))

    ecarts_doc = ""
    if ecartes:
        total_ecarte = sum(e["taille_caracteres"] for e in ecartes)
        details = ", ".join(f"{e['source']} ({e['taille_caracteres']} car.)" for e in ecartes)
        ecarts_doc = f"\n\n> [!WARNING]\n> Éléments écartés (dépassement {CAPACITE_MAX_DOSSIER} car.) : {total_ecarte} car. au total.\n> Sources : {details}\n"

    pied = (
        f"\n\n---\n"
        f"**Fournisseur** : {fournisseur} | **Modèle** : {modele} | "
        f"**Taille dossier** : {taille_dossier} car. | **Tokens** : {tokens_rendus}\n"
    )
    if (meta or {}).get("echecs_avant"):
        pied += "**Fournisseurs en echec avant** : " + " ; ".join(meta["echecs_avant"]) + "\n"

    # JUGE DETERMINISTE (30/10) : malgre la consigne, les modeles gratuits inventaient des noms (CODEX_MAX_TURNS,
    # context_compaction...). Chaque nom cite en `code` ou en **gras** doit figurer MOT POUR MOT dans le dossier
    # envoye ; sinon il est marque ABSENT DU DOSSIER et compte. Le lecteur ne prend que ce qui est verifie.
    reponse_validee, _absents = _marquer_noms_inventes(reponse_validee, dossier)
    if _absents:
        pied += "**Noms ABSENTS du dossier (probablement inventes)** : %d -- %s\n" % (
            len(_absents), ", ".join(sorted(_absents)[:25]))
    contenu_final = reponse_validee + ecarts_doc + pied

    p_out = Path(sortie_fichier)
    if not p_out.is_absolute():  # relatif = depuis la racine du depot, pas depuis le cwd du job (mesure 30/10)
        p_out = Path(__file__).resolve().parents[1] / p_out
    p_out.parent.mkdir(parents=True, exist_ok=True)
    p_out.write_text(contenu_final, encoding="utf-8")

    return {
        "ok": ok,
        "sortie": str(p_out),
        "fournisseur": fournisseur,
        "taille_dossier": taille_dossier,
        "elements_ecartes": ecartes,
        "tokens": tokens_rendus,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Enquête sans boucle d'agent")
    parser.add_argument("--question", required=True, help="Question de l'enquête")
    parser.add_argument("--fts", action="append", default=[], help="Termes FTS MATCH (répétable)")
    parser.add_argument("--fonction", action="append", default=[], help="Fonction chemin.py::nom (répétable)")
    parser.add_argument("--sortie", required=True, help="Chemin du fichier de sortie .md")
    parser.add_argument("--fournisseur", default=None, help="Fournisseur (défaut : premier gratuit de PROVIDER_CHAIN)")

    args = parser.parse_args()
    res = executer_enquete(
        question=args.question,
        fts_termes=args.fts,
        fonctions=args.fonction,
        sortie_fichier=args.sortie,
        fournisseur=args.fournisseur,
    )
    if res.get("ok"):
        print(f"OK: Rapport généré dans {res.get('sortie')}")
        return 0
    else:
        print(f"WARN/ERR: Rapport écrit mais avec erreur fournisseur: {res}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
