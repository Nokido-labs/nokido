"""
tools/forge_surgical_patcher.py — Patch chirurgical AST (Pass@1)
================================================================
Moteur de transformation sans regex ni escape hell.

Transformers disponibles:
  - _FixDecodeHexStr  : 'xx'.decode('hex') → bytes.fromhex('xx').decode('latin-1')
  - _FixBytesFromHex  : bytes.fromhex(x) → bytes.fromhex(x).decode('latin-1')
  - _FixMapOrd        : map(ord, x) → list(x)
  - _FixRangeDivision : range(a/b) → range(a//b)

NOTE: 'x'.decode('hex') est une syntaxe Python2 invalide en Python3.
Le transformer travaille en mode TEXT d'abord (regex ciblé), puis AST.
"""

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(str(__import__("pathlib").Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────
#  PHASE 1 : PRE-PROCESSING TEXTUEL (Python2-invalide → Python3-parseable)
# ─────────────────────────────────────────────────────────────


def preprocess_py2_text(code: str) -> tuple[str, list]:
    """
    Transforme les constructions Python2 non-parseable par ast.parse().
    Retourne (code_transformé, liste_des_fixes_appliqués).
    Ces patterns sont impossibles via AST car Python3 refuse de les parser.
    """
    fixes = []

    # .decode('hex') sur string littérale : '80af'.decode('hex')
    pat1 = re.compile(r"(['\"][0-9a-fA-F]+['\"])\.decode\(['\"]hex['\"]\)")
    if pat1.search(code):
        code = pat1.sub(lambda m: f"bytes.fromhex({m.group(1)}).decode('latin-1')", code)
        fixes.append("str_literal.decode('hex') → bytes.fromhex")

    # .decode('hex') sur variable : var.decode('hex')
    pat2 = re.compile(r"(\w+)\.decode\(['\"]hex['\"]\)")
    if pat2.search(code):
        code = pat2.sub(lambda m: f"bytes.fromhex({m.group(1)}).decode('latin-1')", code)
        fixes.append("var.decode('hex') → bytes.fromhex")

    # open(...).read().strip().decode('hex')
    pat3 = re.compile(r"(open\([^)]+\)\.read\(\)\.strip\(\))\.decode\(['\"]hex['\"]\)")
    if pat3.search(code):
        code = pat3.sub(lambda m: f"bytes.fromhex({m.group(1)}).decode('latin-1')", code)
        fixes.append("open().read().strip().decode('hex') → bytes.fromhex")

    # print sans parenthèses (Python2) — uniquement si suivi d'espace non-parens
    pat4 = re.compile(r"^(\s*)print ([^(\n][^\n]*)$", re.MULTILINE)
    if pat4.search(code):
        code = pat4.sub(r"\1print(\2)", code)
        fixes.append("print stmt → print()")

    # xrange → range
    pat_xrange = re.compile(r"\bxrange\b")
    if pat_xrange.search(code):
        code = pat_xrange.sub("range", code)
        fixes.append("xrange → range")

    # .iteritems() → .items()
    if ".iteritems()" in code:
        code = code.replace(".iteritems()", ".items()")
        fixes.append("iteritems → items")

    # long( → int(
    pat_long = re.compile(r"\blong\b")
    if pat_long.search(code):
        code = pat_long.sub("int", code)
        fixes.append("long → int")

    # string.lowercase → string.ascii_lowercase
    if "string.lowercase" in code:
        code = code.replace("string.lowercase", "string.ascii_lowercase")
        fixes.append("string.lowercase → ascii_lowercase")

    return code, fixes


# ─────────────────────────────────────────────────────────────
#  PHASE 2 : TRANSFORMERS AST (sur code Python3 valide)
# ─────────────────────────────────────────────────────────────


class _FixBytesFromHex(ast.NodeTransformer):
    """bytes.fromhex(x) → bytes.fromhex(x).decode('latin-1')"""

    def visit_Call(self, node):
        self.generic_visit(node)
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "bytes"
            and node.func.attr == "fromhex"
            and
            # Éviter double-wrap si déjà .decode() parent
            not (hasattr(node, "_already_wrapped"))
        ):
            new_node = ast.Call(
                func=ast.Attribute(value=node, attr="decode", ctx=ast.Load()),
                args=[ast.Constant(value="latin-1")],
                keywords=[],
            )
            new_node._already_wrapped = True
            return new_node
        return node


class _FixMapOrd(ast.NodeTransformer):
    """map(ord, x) → list(x)"""

    def visit_Call(self, node):
        self.generic_visit(node)
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "map"
            and len(node.args) == 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "ord"
        ):
            return ast.Call(
                func=ast.Name(id="list", ctx=ast.Load()), args=[node.args[1]], keywords=[]
            )
        return node


class _FixRangeDivision(ast.NodeTransformer):
    """range(a/b) → range(a//b)"""

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "range":
            new_args = []
            changed = False
            for arg in node.args:
                if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Div):
                    new_args.append(ast.BinOp(left=arg.left, op=ast.FloorDiv(), right=arg.right))
                    changed = True
                else:
                    new_args.append(arg)
            if changed:
                node.args = new_args
        return node


class _FixDoubleDecodeWrap(ast.NodeTransformer):
    """
    Évite bytes.fromhex(x).decode('latin-1').decode('latin-1') — double wrap.
    Détecte .decode('latin-1') appliqué sur un nœud qui est déjà .decode().
    """

    def visit_Call(self, node):
        self.generic_visit(node)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "decode"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "latin-1"
        ):
            inner = node.func.value
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "decode"
            ):
                return inner  # dépliage du double wrap
        return node


# ─────────────────────────────────────────────────────────────
#  ORCHESTRATEUR
# ─────────────────────────────────────────────────────────────


class _FixRemoteToProcess(ast.NodeTransformer):
    """remote('host', port) → process(['python3', server_file]) si server_file fourni."""

    server_file: str = None

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "remote" and self.server_file:
            return ast.Call(
                func=ast.Name(id="process", ctx=ast.Load()),
                args=[
                    ast.List(
                        elts=[ast.Constant("python3"), ast.Constant(self.server_file)],
                        ctx=ast.Load(),
                    )
                ],
                keywords=[],
            )
        return node


class _FixBytesJoin(ast.NodeTransformer):
    """
    b'\n'.join(list_of_str) → b'\n'.join(x.encode() for x in list_of_str)
    Détecte : Attribute(value=Constant(bytes), attr='join')
    """

    def visit_Call(self, node):
        self.generic_visit(node)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "join"
            and isinstance(node.func.value, ast.Constant)
            and isinstance(node.func.value.value, bytes)
            and node.args
        ):
            inner = node.args[0]
            # Envelopper dans un generatorexp x.encode() for x in inner
            elt = ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="x", ctx=ast.Load()), attr="encode", ctx=ast.Load()
                ),
                args=[],
                keywords=[],
            )
            gen = ast.GeneratorExp(
                elt=elt,
                generators=[
                    ast.comprehension(
                        target=ast.Name(id="x", ctx=ast.Store()), iter=inner, ifs=[], is_async=0
                    )
                ],
            )
            node.args[0] = gen
        return node


class _FixStrBytesConcat(ast.NodeTransformer):
    """
    Détecte str + bytes ou bytes + str dans BinOp Add et encode le str.
    Fonctionne uniquement sur les constantes littérales.
    """

    def visit_BinOp(self, node):
        self.generic_visit(node)
        if isinstance(node.op, ast.Add):
            l, r = node.left, node.right
            if (
                isinstance(l, ast.Constant)
                and isinstance(l.value, bytes)
                and isinstance(r, ast.Constant)
                and isinstance(r.value, str)
            ):
                r.value = r.value.encode("latin-1")
            elif (
                isinstance(l, ast.Constant)
                and isinstance(l.value, str)
                and isinstance(r, ast.Constant)
                and isinstance(r.value, bytes)
            ):
                l.value = l.value.encode("latin-1")
        return node


class SurgicalPatcher:
    """
    Interface principale. Usage:
        result = SurgicalPatcher.fix_file_direct('/tmp/forge_ctf_runner.py')
        print(result)  # {'status': 'SUCCESS', 'mutations': 3}
    """

    AST_TRANSFORMERS = [
        _FixBytesFromHex,
        _FixDoubleDecodeWrap,
        _FixMapOrd,
        _FixRangeDivision,
        _FixBytesJoin,
        _FixStrBytesConcat,
    ]

    @classmethod
    def transform(cls, source: str) -> tuple[str, list]:
        """Pipeline complet : text pre-processing → AST transforms."""
        all_fixes = []

        # Phase 1 : text (constructions invalides Python3)
        code, text_fixes = preprocess_py2_text(source)
        all_fixes.extend(text_fixes)

        # Phase 2 : AST (constructions valides mais incorrectes)
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            raise SyntaxError(f"Toujours invalide après pre-processing: {e}")

        for TransformerClass in cls.AST_TRANSFORMERS:
            before = ast.unparse(tree)
            transformer = TransformerClass()
            tree = transformer.visit(tree)
            ast.fix_missing_locations(tree)
            after = ast.unparse(tree)
            if after != before:
                all_fixes.append(TransformerClass.__name__)
                tree = ast.parse(after)  # re-parser pour normaliser

        return ast.unparse(tree), all_fixes

    @classmethod
    def patch_ctf_solver(cls, source: str, server_file: str = None) -> str:
        """
        Pipeline complet CTF : py2 fixes + remote→process + str/bytes.
        Retourne le code patchÃ© prÃªt Ã  exÃ©cuter.
        """
        code, _ = preprocess_py2_text(source)
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return source  # fallback : retourner l'original

        transformers = cls.AST_TRANSFORMERS[:]
        if server_file:
            t = _FixRemoteToProcess()
            t.server_file = server_file
            transformers.insert(0, t)

        for T in transformers:
            if isinstance(T, type):
                transformer = T()
            else:
                transformer = T
            tree = transformer.visit(tree)
            ast.fix_missing_locations(tree)
            try:
                code = ast.unparse(tree)
                tree = ast.parse(code)
            except Exception:
                break

        return ast.unparse(tree)

    @classmethod
    def fix_file_direct(cls, file_path: str) -> dict:
        """
        Patch un fichier Python en place — ecriture PROPRIOCEPTIVE.
        Validation AST + ecriture atomique : le disque ne voit JAMAIS de code
        casse (pas de fenetre necrotique, rien a rollback). Refresh carte (L1).
        """
        path = Path(file_path)
        source = path.read_text(encoding="utf-8")

        try:
            new_code, fixes = cls.transform(source)
        except SyntaxError as e:
            return {"status": "ERROR", "msg": str(e)}

        if not fixes:
            return {"status": "NOOP", "mutations": 0}

        # L0 + atomique : valide new_code EN RAM, n'ecrit que si sain (tmp->os.replace),
        # rafraichit la carte. Si KO -> disque INTACT (l'original n'est jamais ecrase).
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from nokido_agent.tools.forge_module_cards import proprioceptive_write

        res = proprioceptive_write(str(path), new_code, action="patch_ctf")
        if not res["ok"]:
            return {"status": "REJECTED", "msg": res["error"], "fixes_attempted": fixes}

        return {"status": "SUCCESS", "mutations": len(fixes), "fixes": fixes}


if __name__ == "__main__":
    import tempfile

    TEST_CASES = [
        (
            "decode_hex_literal",
            "c = '80af'.decode('hex')\n",
            "bytes.fromhex('80af').decode('latin-1')",
        ),
        ("decode_hex_var", "c = raw.decode('hex')\n", "bytes.fromhex(raw).decode('latin-1')"),
        (
            "bytes_fromhex_bare",
            "n = bytes.fromhex('dead')\n",
            "bytes.fromhex('dead').decode('latin-1')",
        ),
        ("map_ord", "vals = list(map(ord, ct))\n", "list(ct)"),
        ("range_div", "for i in range(len(s)/2):\n    pass\n", "range(len(s) // 2)"),
    ]

    passed = 0
    for name, src, expected_fragment in TEST_CASES:
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(src)
            tmp = Path(f.name)

        result = SurgicalPatcher.fix_file_direct(str(tmp))
        final = tmp.read_text()
        ok = expected_fragment in final
        status = "✅" if ok else "❌"
        print(f"{status} {name}: {result['status']} | fragment={'OK' if ok else 'MISSING'}")
        if not ok:
            print(f"   attendu: {expected_fragment!r}")
            print(f"   obtenu:  {final!r}")
        passed += ok

    print(f"\n{passed}/{len(TEST_CASES)} tests passés")
