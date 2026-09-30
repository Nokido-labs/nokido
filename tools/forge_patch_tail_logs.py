"""
tools/forge_patch_tail_logs.py — patcher one-shot du handler `read action=tail_logs`
(app/forge_mcp_registry.py est CRITICAL_FILE : governed_edit refuse, le chemin
officiel est un patcher committe lance en trusted_script).

Repare deux defauts mesures le 2026-07-25 :
  1. `path` absent -> `self.root / ""` == le DOSSIER racine -> read_text() levait
     « PermissionError [Errno 13] ... \\LaForge ». Le reflexe fondateur « le LOG de
     l'organe AVANT toute sonde » etait donc inutilisable, et l'agent contournait
     par un shell (4 fois dans la meme session).
  2. read_text() chargeait le fichier ENTIER pour n'en garder que N lignes : un log
     de 2,3 Mo saturait la sortie et partait en archive CCR.

Idempotent, verifie la compilation AVANT d'ecrire, garde un .bak horodate.
Usage : run action=trusted_script path=tools/forge_patch_tail_logs.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "app" / "forge_mcp_registry.py"

OLD = '''        if args.get("action") == "tail_logs":
            _lines = int(args.get("lines", 100))
            _pattern = args.get("pattern", "")
            if not path.exists():
                return f"Log introuvable: {path}"
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            if _pattern:
                lines = [l for l in lines if _pattern.lower() in l.lower()]
            return "\\n".join(lines[-_lines:])
'''

NEW = '''        if args.get("action") == "tail_logs":
            from pathlib import Path as _P

            _lines = int(args.get("lines", 100))
            _pattern = args.get("pattern", "")
            # `path` ABSENT -> self.root / "" == le DOSSIER racine : path.exists()
            # renvoie True et read_text() levait « PermissionError [Errno 13] ...
            # \\LaForge ». Le reflexe FONDATEUR (« le LOG de l'organe AVANT toute
            # sonde ») etait donc casse et l'agent contournait par un shell (mesure
            # 2026-07-25). On RESOUT le log de l'organe depuis `pattern` : le plus
            # recemment ecrit parmi logs/ et logs/supervisor/ dont le nom matche.
            if (not path_str) or path.is_dir():
                _cands = []
                for _d in (self.root / "logs", self.root / "logs" / "supervisor"):
                    if not _d.is_dir():
                        continue
                    for _f in _d.glob("*.log"):
                        if not _pattern or _pattern.lower() in _f.name.lower():
                            try:
                                _cands.append((_f.stat().st_mtime, str(_f)))
                            except OSError:
                                continue
                if not _cands:
                    # « rien trouve » != « pas pu voir » : dire OU l'on a cherche.
                    return (f"tail_logs: aucun .log correspondant a pattern={_pattern!r} "
                            f"dans logs/ et logs/supervisor/ (racine {self.root})")
                path = _P(max(_cands)[1])
                assert_can_read(str(path), agent, ring)
            if not path.exists():
                return f"Log introuvable: {path}"
            # TAIL par la FIN (seek) au lieu de charger tout le fichier : un log de
            # 2,3 Mo saturait la sortie pour un simple tail (mesure du jour).
            _budget = min(max(1, _lines) * (4096 if _pattern else 512), 4 * 1024 * 1024)
            try:
                with open(path, "rb") as _fh:
                    _fh.seek(0, 2)
                    _size = _fh.tell()
                    _fh.seek(max(0, _size - _budget))
                    _raw = _fh.read()
            except OSError as _e:
                return f"tail_logs: illisible ({type(_e).__name__}: {_e}): {path}"
            lines = _raw.decode("utf-8", errors="replace").splitlines()
            if _size > _budget and lines:
                lines = lines[1:]   # 1re ligne tronquee au milieu par le seek
            if _pattern:
                lines = [l for l in lines if _pattern.lower() in l.lower()]
            try:
                _shown = _P(path).relative_to(self.root)
            except ValueError:
                _shown = path
            return (f"[tail_logs {_shown} — {len(lines)} lignes, tail {_budget // 1024} Ko]\\n"
                    + "\\n".join(lines[-_lines:]))
'''


# PATCH 2 — comparaison NORMALISEE du motif avec le nom de fichier. Mesure faite
# juste apres le patch 1 : `tail_logs pattern=docker_keeper` ne trouvait RIEN alors
# que logs/supervisor/NokidoDockerKeeper.log existe, parce qu'un agent nomme l'organe
# facon module (snake_case) tandis que le superviseur ecrit en CamelCase. Sans cette
# normalisation l'outil reste inutilisable -> l'agent recontourne par un shell.
OLD2 = '''                    for _f in _d.glob("*.log"):
                        if not _pattern or _pattern.lower() in _f.name.lower():
'''

NEW2 = '''                    for _f in _d.glob("*.log"):
                        # Motif « docker_keeper » vs fichier « NokidoDockerKeeper.log » :
                        # on compare sans casse NI separateurs, sinon le match echoue
                        # toujours (mesure 2026-07-25, juste apres le 1er correctif).
                        _nf = _f.name.lower().replace("_", "").replace("-", "").replace(" ", "")
                        _np = _pattern.lower().replace("_", "").replace("-", "").replace(" ", "")
                        if not _pattern or _np in _nf:
'''

# (marqueur de deja-applique, bloc a remplacer, bloc de remplacement, libelle)
PATCHES = [
    ("tail_logs: aucun .log correspondant", OLD, NEW, "resolution du log + tail par seek"),
    ("_nf = _f.name.lower()", OLD2, NEW2, "match motif<->nom normalise (snake vs CamelCase)"),
]


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    original = src
    applied, skipped = [], []
    for marker, old, new, label in PATCHES:
        if marker in src:
            skipped.append(f"{label} (deja applique)")
            continue
        if src.count(old) != 1:
            print(f"ABORT sur « {label} »: bloc attendu introuvable ou ambigu "
                  f"(occurrences={src.count(old)}). Aucune ecriture.")
            return 3
        src = src.replace(old, new, 1)
        applied.append(label)
    for s in skipped:
        print(f"SKIP  — {s}")
    if not applied:
        print("Rien a faire (tous les patchs sont deja en place) — no-op")
        return 0
    try:
        compile(src, str(TARGET), "exec")
    except SyntaxError as e:
        print(f"ABORT: le resultat ne compile pas ({e}). Aucune ecriture.")
        return 4
    bak = TARGET.with_suffix(".py.bak_tail_logs")
    bak.write_text(original, encoding="utf-8")
    TARGET.write_text(src, encoding="utf-8")
    for a in applied:
        print(f"PATCH — {a}")
    print(f"OK — {TARGET.name} ({len(original)} -> {len(src)} octets), backup {bak.name}")
    print("ARME au prochain restart du hub (le code en memoire reste l'ancien).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
