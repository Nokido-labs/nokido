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


def main():
    global _BRUT
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
    print((amont + " | " + mien) if amont else mien)
    if ev:
        _collecter(ev)
    return 0


if __name__ == "__main__":
    sys.exit(main())
