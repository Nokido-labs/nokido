"""Statusline Nokido -- affiche la depense, et l'ENREGISTRE au passage.

__FORGE_COLOR__ = "observabilite/trace : statusline et collecte d'usage"

Deux roles pour un seul appel, et c'est ce qui la rend interessante : le
runtime l'invoque de lui-meme a chaque rafraichissement, en lui passant les
compteurs de tokens. C'est donc un capteur GRATUIT -- il ne coute pas un seul
token de contexte, contrairement a tout ce que l'agent pourrait demander.

  1. AFFICHER  : IN / OUT / CACHE-R / CACHE-W / % de fenetre.
  2. COLLECTER : alimenter `token_usage` via `forge_llm_usage_adapters`, pour
     que Claude, Codex et AGY finissent dans la MEME table et deviennent
     comparables sur une meme tache.

INVARIANT : LA LIGNE S'AFFICHE TOUJOURS. La collecte est secondaire et ne doit
jamais empecher l'affichage -- une statusline qui plante est une statusline
qu'on retire, et on perdrait le capteur avec.

Anti-doublon : le runtime rafraichit souvent, et les compteurs ne bougent
qu'entre deux appels API. On n'ecrit que sur CHANGEMENT, sinon la table se
remplit de repetitions qui fausseraient toute agregation.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
ETAT = Path(os.environ.get("LAFORGE_STATUSLINE_DIR")
            or (Path.home() / ".claude" / "runtime")) / "statusline.json"


def _statusline_amont():
    """Ligne de la statusline DEJA installee (plugin caveman), si elle existe.

    On CHAINE au lieu de remplacer : l'emplacement `statusLine` est unique, et
    ecraser celui de l'owner pour y mettre des compteurs serait un echange
    perdant. Sa ligne d'abord, la depense ensuite.

    Le chemin du plugin porte un hash de VERSION
    (`plugins/cache/caveman/caveman/84cc3c14fa1e/...`) : le figer casserait au
    prochain update, en silence et sans rien dire. On le decouvre donc, et on
    prend le plus recent.
    """
    try:
        # `CLAUDE_CONFIG_DIR` quand il est pose, sinon le profil. La variable
        # LAFORGE_* n'existe que pour le banc d'essai : sous le compte sandbox,
        # `Path.home()` ne designe PAS le profil owner, donc le chainage y est
        # invisible -- illisible, pas casse. On teste la mecanique ici, le
        # chemin reel se verifie en session.
        base = (os.environ.get("LAFORGE_PLUGINS_DIR")
                or os.environ.get("CLAUDE_CONFIG_DIR")
                or str(Path.home() / ".claude"))
        cache = Path(base) / "plugins" / "cache"
        cands = sorted(cache.glob("**/caveman-statusline.ps1"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if not cands:
            return ""
        import subprocess
        r = subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden",
             "-ExecutionPolicy", "Bypass", "-File", str(cands[0])],
            # `errors="replace"` : en mode texte sans lui, un octet invalide
            # fait crasher le thread de lecture (anti-regression incident 47GB).
            # Une statusline qui plante est une statusline qu'on retire.
            input=_BRUT, capture_output=True, text=True, timeout=4,
            errors="replace",
        )
        return (r.stdout or "").strip()
    except Exception:  # noqa: BLE001 - muet-ok
        # muet-ok : absent, lent ou casse -> on affiche notre part seule. Le
        # chainage ne doit jamais faire disparaitre la ligne.
        return ""


def _humain(n):
    if n is None:
        return "?"       # non mesure : ne jamais afficher 0 a la place
    if n >= 1_000_000:
        return "%.1fM" % (n / 1_000_000)
    if n >= 1_000:
        return "%.1fk" % (n / 1_000)
    return str(n)


def _ligne(ev, charge):
    parts = [
        "IN %s" % _humain(ev.get("input_tokens")),
        "OUT %s" % _humain(ev.get("output_tokens")),
        "CR %s" % _humain(ev.get("cache_read_tokens")),
        "CW %s" % _humain(ev.get("cache_write_tokens")),
    ]
    if ev.get("reasoning_tokens"):
        parts.append("TH %s" % _humain(ev["reasoning_tokens"]))

    fen = charge.get("context_window") if isinstance(charge, dict) else None
    if isinstance(fen, dict):
        used = fen.get("used_percentage")
        if isinstance(used, (int, float)):
            parts.append("CTX %d%%" % used)
    modele = ev.get("model")
    if modele:
        parts.append(str(modele).replace("claude-", ""))
    return " | ".join(parts)


def _collecter(ev):
    """Ecrit dans token_usage si les compteurs ont bouge. Ne leve JAMAIS."""
    try:
        empreinte = "%s/%s/%s" % (ev.get("input_tokens"), ev.get("output_tokens"),
                                  ev.get("cache_read_tokens"))
        try:
            vu = json.loads(ETAT.read_text(encoding="utf-8")).get("empreinte")
        except Exception:  # noqa: BLE001 - muet-ok : premier passage ou illisible
            vu = None
        if vu == empreinte:
            return  # rien de neuf : ne pas polluer la table
        sys.path.insert(0, str(RACINE / "app"))

        from forge_token_monitor import log_call  # type: ignore

        # RACCORDE au recorder canonique (A3, 2026-09-12) :
        # UNIQUE_WRITER(token_usage) = app/forge_token_monitor.log_call.
        #
        # Ce site visait `m2m_path()` quand tous les autres visaient la base
        # historique : c'etait LA fracture de destination mesuree en A1. La
        # destination redevient le reglage d'un SEUL module ; la migration est
        # l'etape A4, deliberement PAS faite ici.
        #
        # Le cout est laisse au recorder, et ce n'est pas une entorse a la
        # neutralite : ce site n'a jamais ecrit UNE SEULE ligne (la table
        # n'existe pas dans m2m.db), donc il n'y a aucun historique a
        # preserver -- seulement une ecriture a rendre possible.
        # `agent_id` nomme le WRITER, pas le client : c'est ce module qui
        # ecrit. L'identite du client voyage dans `provenance`, posee par
        # l'adaptateur et RELAYEE ici -- sans ce relais, l'adaptateur remplit
        # un evenement que personne ne transmet, et la base ne voit que des
        # UNKNOWN (mesure du 2026-09-12, attrapee par la preuve de bout en
        # bout et invisible aux NR unitaires).
        log_call(
            agent_id="nokido_statusline",
            provider="claude",
            model=ev.get("model"),
            prompt_tokens=ev.get("input_tokens"),
            completion_tokens=ev.get("output_tokens"),
            latency_ms=None,
            source=ev.get("source"),
            session_id=ev.get("session_id") or "",
            cache_read_tokens=ev.get("cache_read_tokens"),
            cache_write_tokens=ev.get("cache_write_tokens"),
            reasoning_tokens=ev.get("reasoning_tokens"),
            provenance=ev.get("provenance"),
            execution_mode=ev.get("execution_mode"),
            transport=ev.get("transport"),
            measurement_kind=ev.get("measurement_kind"),
            measurement_source="client_payload",
        )
        # L'empreinte n'est posee qu'APRES le commit. La poser AVANT faisait
        # d'un echec TRANSITOIRE (base verrouillee) une perte DEFINITIVE : le
        # passage suivant relisait la meme empreinte et sortait aussitot.
        ETAT.parent.mkdir(parents=True, exist_ok=True)
        ETAT.write_text(json.dumps({"empreinte": empreinte}), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - muet pour l'AFFICHAGE seulement
        # Une statusline qui plante est une statusline qu'on retire : on ne
        # leve pas. Mais l'echec SILENCIEUX est precisement ce qui a cache
        # 100 % des collectes perdues -- on le NOMME, sans jamais lever.
        try:
            (RACINE / "sandbox" / "statusline_collecte.err").write_text(
                "%s: %s" % (type(exc).__name__, exc), encoding="utf-8")
        except Exception:  # noqa: BLE001 - muet-ok : dernier recours
            pass


_BRUT = ""


def _tracer_payload(charge):
    """Ecrit UNE fois les CLES du payload statusline, pour NOMMER ce qui manque.

    Ne journalise que des noms de champs, jamais leurs valeurs, et ne leve
    jamais : un diagnostic ne doit pas casser la ligne d'etat.
    """
    try:
        cible = RACINE / "sandbox" / "statusline_diag.json"
        if cible.exists():
            return
        vu = {"racine": sorted(charge)}
        for cle, val in charge.items():
            if not isinstance(val, dict):
                continue
            vu[cle] = sorted(val)
            for souscle, sousval in val.items():
                if isinstance(sousval, dict):
                    vu[cle + "." + souscle] = sorted(sousval)
        cible.write_text(json.dumps(vu, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001 - muet-ok
        pass


_COURT = {"CLAUDE_HEADLESS": "HEADLESS", "ANTIGRAVITY": "AGY"}


def _identites_claude(registre=None) -> list:
    """Noms et alias (minuscules) des agents d'acteur CLAUDE au registre. 3/11 : Claude Code signe en OAuth
    (`agt_oauth_nkc_...`) -- un mot dans le nom ne suffit plus. Registre illisible -> [] (filtre historique seul)."""
    p = Path(registre) if registre else RACINE / "config" / "agent_identities.json"
    try:
        reg = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # muet-ok : registre illisible -> filtre historique « claude » seul
        return []
    ag = reg.get("agents") if isinstance(reg, dict) and isinstance(reg.get("agents"), dict) else reg
    out = []
    for nom, spec in (ag or {}).items():
        if isinstance(spec, dict) and spec.get("actor") == "CLAUDE":
            out += [str(nom).lower()] + [str(a).lower() for a in spec.get("aliases", [])]
    return sorted(set(out))


def _delegations(db=None, maintenant=None, registre=None) -> str:
    """Segment des delegations de Claude en cours (▶) ou en attente (⏸), avec leur age (owner 24/10).

    Lecture seule, delai court : la ligne d'etat ne doit jamais attendre. Base illisible = « DÉL ? »
    (jamais 0) ; aucune delegation = segment absent. NR : tests/nr/test_statusline_delegations_nr.py,
    tests/nr/test_statusline_delegations_oauth_nr.py (identite OAuth, 3/11).
    """
    import sqlite3
    from datetime import datetime

    db = Path(db) if db else RACINE / "sandbox" / "tasks.db"
    if not db.exists():
        return "DÉL ?"
    ids = _identites_claude(registre)
    try:
        cx = sqlite3.connect("file:%s?mode=ro" % db.as_posix(), uri=True, timeout=0.3)
        try:
            rows = cx.execute(
                "SELECT agent, status, updated_at FROM tasks WHERE status IN ('running','pending') "
                "AND (lower(from_agent) LIKE '%%claude%%'%s) ORDER BY updated_at"
                % (" OR lower(from_agent) IN (%s)" % ",".join("?" * len(ids)) if ids else ""), ids).fetchall()
        finally:
            cx.close()
    except Exception:  # noqa: BLE001 - muet-ok : dit « DÉL ? », jamais un faux zero
        return "DÉL ?"
    now = maintenant or datetime.now()
    echecs = _causes_recentes(db, ids, now)
    if not rows and not echecs:
        return ""
    morceaux = []
    for agent, statut, maj in rows[:4]:
        nom = str(agent or "?")
        if nom.upper().startswith("OAUTH_"):
            try:
                import os
                import sys
                repo_root = os.getenv("REPO_ROOT") or str(Path(__file__).resolve().parents[1])
                if repo_root and repo_root not in sys.path:
                    sys.path.insert(0, repo_root)
                from nokido_agent.tools.forge_presence import nom_lisible
                nom = nom_lisible(nom)
            except Exception:  # noqa: BLE001  # muet-ok : repli identifiant brut
                pass
        else:
            nom = _COURT.get(nom, nom.split("_", 1)[1] if nom.startswith("OPENCODE_") else nom)
        try:
            age = "%dm" % max(0, int((now - datetime.fromisoformat(str(maj)[:26])).total_seconds() // 60))
        except Exception:  # noqa: BLE001 - muet-ok : age illisible affiche « ? »
            age = "?"
        morceaux.append("%s%s%s" % (nom, "▶" if statut == "running" else "⏸", age))
    reste = " +%d" % (len(rows) - 4) if len(rows) > 4 else ""
    return ("DÉL %d %s%s" % (len(rows), " ".join(morceaux), reste)).rstrip() + echecs


_ACQUIT = RACINE / "sandbox" / "delegations_acquittees.txt"


def _acquittees_jusqu_a():
    """Date de la derniere marque (owner 6/11 « Masquer si traite »). Absente ou illisible -> None : rien n'est masque."""
    from datetime import datetime

    try:
        return datetime.fromisoformat(_ACQUIT.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):  # muet-ok : marque absente ou illisible = causes visibles, jamais masquees
        return None


def _causes_recentes(db, ids, now, fenetre_s: int = 7200) -> str:
    """3/11 (owner « vois-tu et diagnostiques-tu les raisons des echecs ? ») : causes CLASSEES (tasks.cause_echec,
    ecrite par forge_task_executor) des delegations de Claude closes dans les 2 dernieres heures -> « ✗ CAUSE×n ».
    Un echec anterieur a la marque d'acquittement (--acquitter) n'est plus compte.
    Colonne absente ou base illisible -> rien (l'affichage d'avant), jamais une cause inventee."""
    import sqlite3
    from collections import Counter
    from datetime import datetime

    try:
        cx = sqlite3.connect("file:%s?mode=ro" % Path(db).as_posix(), uri=True, timeout=0.3)
        try:
            rows = cx.execute(
                "SELECT cause_echec, updated_at FROM tasks WHERE cause_echec IS NOT NULL "
                "AND (lower(from_agent) LIKE '%%claude%%'%s) ORDER BY updated_at DESC LIMIT 50"
                % (" OR lower(from_agent) IN (%s)" % ",".join("?" * len(ids)) if ids else ""), ids).fetchall()
        finally:
            cx.close()
    except Exception:  # noqa: BLE001 - muet-ok : colonne absente (executeur d'avant le 3/11) -> pas de segment
        return ""
    compte = Counter()
    borne = _acquittees_jusqu_a()
    for cause, maj in rows:
        try:
            quand = datetime.fromisoformat(str(maj)[:26])
            if borne and quand <= borne:
                continue
            if (now - quand).total_seconds() <= fenetre_s:
                compte[str(cause)] += 1
        except Exception:  # noqa: BLE001 - muet-ok : date illisible -> ligne ignoree, pas comptee
            continue
    if not compte:
        return ""
    return " ✗ " + " ".join(c if n == 1 else "%s×%d" % (c, n) for c, n in compte.most_common(3))


def _tours(charge, etat=None):
    """(tours, appels d'outils) de la session, depuis `transcript_path` du payload (P0, decision owner 20/10).

    Le .jsonl ecrit UNE ligne par bloc : un tour = un message.id assistant DISTINCT d'avec le precedent, un appel =
    un bloc tool_use. Lecture INCREMENTALE depuis l'offset memorise (le transcript pese des dizaines de Mo) ; seules
    les lignes COMPLETES sont lues. Autre transcript ou fichier raccourci -> repart de zero. Rend None si le
    transcript est absent ou illisible (INCONNU, pas zero). Ne leve JAMAIS."""
    try:
        chemin = (charge or {}).get("transcript_path") if isinstance(charge, dict) else None
        if not chemin or not os.path.isfile(chemin):
            return None
        etat = Path(etat) if etat else RACINE / "sandbox" / "statusline_tours.json"
        try:
            e = json.loads(etat.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - muet-ok : premier passage ou illisible
            e = {}
        taille = os.path.getsize(chemin)
        if e.get("chemin") != chemin or int(e.get("offset") or 0) > taille:
            e = {"chemin": chemin, "offset": 0, "tours": 0, "outils": 0, "dernier_id": None}
        with open(chemin, "rb") as f:
            f.seek(int(e["offset"]))
            bloc = f.read()
        fin = bloc.rfind(b"\n")
        if fin >= 0:
            for brute in bloc[:fin + 1].splitlines():
                try:
                    m = json.loads(brute.decode("utf-8", "replace")).get("message") or {}
                except Exception:  # noqa: BLE001 - muet-ok : ligne non JSON
                    continue
                if not isinstance(m, dict) or m.get("role") != "assistant":
                    continue
                if m.get("id") and m["id"] != e.get("dernier_id"):
                    e["tours"] += 1
                    e["dernier_id"] = m["id"]
                contenu = m.get("content")
                if isinstance(contenu, list):
                    e["outils"] += sum(1 for b in contenu if isinstance(b, dict) and b.get("type") == "tool_use")
            e["offset"] = int(e["offset"]) + fin + 1
            etat.parent.mkdir(parents=True, exist_ok=True)
            etat.write_text(json.dumps(e), encoding="utf-8")
        return e["tours"], e["outils"]
    except Exception:  # noqa: BLE001 - une statusline qui plante est une statusline qu'on retire
        return None


def main():
    global _BRUT
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # ▶ ⏸ hors cp1252 (sous-processus Windows)
    except Exception:  # noqa: BLE001 - muet-ok
        pass
    if "--acquitter" in sys.argv[1:]:
        from datetime import datetime

        _ACQUIT.write_text(datetime.now().isoformat(), encoding="utf-8")
        print("causes de delegation acquittees jusqu'a maintenant")
        return 0
    try:
        _BRUT = sys.stdin.read()
        charge = json.loads(_BRUT)
    except Exception:  # noqa: BLE001 - muet-ok
        print("nokido")
        return 0
    ev = None
    motif = "indisponible"
    try:
        sys.path.insert(0, str(RACINE / "app"))
        from forge_llm_usage_adapters import depuis_claude  # type: ignore
        ev = depuis_claude(charge)
        if ev is None:
            motif = "absent du payload"
            _tracer_payload(charge)
    except Exception as exc:  # noqa: BLE001 - muet-ok
        motif = "adaptateur KO (" + type(exc).__name__ + ")"
    amont = _statusline_amont()
    mien = _ligne(ev, charge) if ev else ("usage " + motif)
    tours = _tours(charge)
    if tours:
        mien = mien + " | " + ("TOURS %d OUTILS %d" % tours)
    deleg = _delegations()
    if deleg:
        mien = mien + " | " + deleg
    print((amont + " | " + mien) if amont else mien)
    if ev:
        _collecter(ev)
    return 0


if __name__ == "__main__":
    sys.exit(main())
