# -*- coding: utf-8 -*-
"""One-shot patcher: Sprint 1 anti context-bomb sur app/forge_mcp_registry.py.

Ajoute le mode COMPACT du catalogue tools/list, negocie PAR CLIENT :
  - _compact_agents() : opt-in via env LAFORGE_TOOLS_COMPACT ("*" ou CSV)
    OU marqueur sandbox/tools_compact.txt (lu LIVE -> toggle sans restart,
    miroir du pattern _redteam_enabled).
  - _compact_tools() : vue telegraphique (1re phrase + hint action= preserve,
    descriptions de proprietes tronquees, enums/required INTACTS, zero
    mutation du canonique).
  - Greffe dans get_tool_list() : la visibilite ne change pas, seule la
    verbosite change pour les agents opt-in.

CRITICAL_FILE -> applique via owner trusted_script (chemin officiel), en
repliquant la securite de governed_edit : exact-match (assert count==1),
garde d'idempotence, compile() AVANT ecriture, style de newline preserve.
Abort sans ecrire au moindre mismatch. Re-runnable (idempotent).

Run : run action=trusted_script path=tools/forge_patch_registry_compact.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "app", "forge_mcp_registry.py")

# ── EDIT A : nouvelles methodes apres _inject_explanation_field ──────────────
A_OLD = (
    '            if "explanation" not in props:\n'
    '                props["explanation"] = dict(self._EXPLANATION_FIELD)\n'
    '            # NOTE : volontairement PAS ajoute dans `required` (mode warn).\n'
    '        return tools\n'
)
A_NEW = A_OLD + '''
    # ── Mode compact negocie par client (Sprint 1 anti context-bomb) ────────
    # Vue TELEGRAPHIQUE du catalogue pour les surfaces sans deferral de schemas
    # (AGY, bridge stdio, cline). Opt-in par agent : env LAFORGE_TOOLS_COMPACT
    # ("*" ou CSV de noms) OU marqueur sandbox/tools_compact.txt (CSV, lu LIVE
    # a chaque tools/list -> toggle sans restart hub, miroir _redteam_enabled).
    # Le catalogue CANONIQUE n'est jamais modifie (copie par tool).
    _COMPACT_DESC_MAX = 200
    _COMPACT_PROP_DESC_MAX = 80
    _COMPACT_EXPLANATION_DESC = "Pourquoi cet appel (1 phrase)."

    def _compact_agents(self) -> set:
        """Agents ayant negocie la vue compacte. Lu LIVE a chaque tools/list."""
        raw = os.environ.get("LAFORGE_TOOLS_COMPACT", "") or ""
        try:
            marker = Path(__file__).resolve().parent.parent / "sandbox" / "tools_compact.txt"
            if marker.exists():
                raw = raw + "," + marker.read_text(encoding="utf-8")
        except Exception:
            pass  # marqueur best-effort : jamais bloquer tools/list
        return {a.strip().upper() for a in raw.replace(";", ",").split(",") if a.strip()}

    def _compact_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Vue telegraphique : 1re phrase + hint action= ; descriptions de
        proprietes tronquees ; enums/required/types INTACTS ; zero mutation
        du canonique (copie par tool)."""
        out: List[Dict[str, Any]] = []
        for t in tools:
            t2 = dict(t)
            desc = (t2.get("description") or "").strip()
            first = desc.split("\\n", 1)[0].strip()
            cut = first.find(". ")
            if 0 < cut < self._COMPACT_DESC_MAX:
                first = first[: cut + 1]
            m = re.search(r"action=[\\w|\\-]+", desc)
            hint = m.group(0) if (m and m.group(0) not in first) else ""
            budget = self._COMPACT_DESC_MAX - (len(hint) + 1 if hint else 0)
            if len(first) > budget:
                first = first[: max(0, budget - 1)].rstrip() + "..."
            if hint:
                first = (first + " " + hint)[: self._COMPACT_DESC_MAX]
            t2["description"] = first
            schema = t2.get("inputSchema") or {}
            props: Dict[str, Any] = {}
            for k, p in (schema.get("properties") or {}).items():
                p2 = dict(p)
                if k == "explanation":
                    p2["description"] = self._COMPACT_EXPLANATION_DESC
                else:
                    pd = p2.get("description")
                    if isinstance(pd, str) and len(pd) > self._COMPACT_PROP_DESC_MAX:
                        p2["description"] = pd[: self._COMPACT_PROP_DESC_MAX - 3] + "..."
                props[k] = p2
            t2["inputSchema"] = dict(schema)
            t2["inputSchema"]["properties"] = props
            out.append(t2)
        return out
'''

# ── EDIT B : greffe dans get_tool_list (fin de fonction) ────────────────────
B_OLD = (
    '        # Outils forges dynamiques (dyn_<nom>) : noms non-statiques -> autorises a ring<=2\n'
    "        # (le ring est porte par forge_call_dynamic ; l'exec passe par SecretGuard).\n"
    '        return [t for t in self._all_tools()\n'
    '                if (t["name"] in allowed or (ring <= 2 and t["name"].startswith("dyn_")))\n'
    '                and not _blocked(t["name"])]\n'
)
B_NEW = (
    '        # Outils forges dynamiques (dyn_<nom>) : noms non-statiques -> autorises a ring<=2\n'
    "        # (le ring est porte par forge_call_dynamic ; l'exec passe par SecretGuard).\n"
    '        visible = [t for t in self._all_tools()\n'
    '                   if (t["name"] in allowed or (ring <= 2 and t["name"].startswith("dyn_")))\n'
    '                   and not _blocked(t["name"])]\n'
    '        # Sprint 1 anti context-bomb : vue telegraphique NEGOCIEE par client.\n'
    '        ca = self._compact_agents()\n'
    '        if ca and ("*" in ca or (agent or "").upper() in ca):\n'
    '            return self._compact_tools(visible)\n'
    '        return visible\n'
)

raw = open(TARGET, "rb").read().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
text = raw.replace("\r\n", "\n")

if "_compact_tools" in text:
    print("ABORT: already patched (idempotent no-op)")
    sys.exit(3)

for label, old in (("A", A_OLD), ("B", B_OLD)):
    n = text.count(old)
    if n != 1:
        print(f"ABORT: block {label} found {n} times (expected exactly 1) -> no write")
        sys.exit(2)

text = text.replace(A_OLD, A_NEW, 1)
text = text.replace(B_OLD, B_NEW, 1)

try:
    compile(text, TARGET, "exec")
except SyntaxError as e:
    print(f"ABORT: SyntaxError after patch -> no write: {e}")
    sys.exit(4)

out = text.replace("\n", nl)
open(TARGET, "wb").write(out.encode("utf-8"))
print(f"OK: compact catalog mode applied + AST valid. newline={nl!r}")
