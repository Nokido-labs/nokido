"""make_tiny_onnx.py — generate a trivial ONNX model (Y = X plus one) to test if WinML
loads and runs inside the Xbox UWP AppContainer. Re-execs with the venv python (has onnx)."""

__FORGE_COLOR__ = "metabolisme/provider : genere un modele ONNX trivial pour eprouver WinML"  # organe declare le 2026-09-06 (audit de raccordement)
import os
import sys
import subprocess

VENV = r"C:/tmp/xbox_genai_venv/Scripts/python.exe"
OUT = r"C:/tmp/tiny.onnx"

try:
    import onnx  # noqa: F401
except ImportError:
    if os.path.abspath(sys.executable).lower() != os.path.abspath(VENV).lower():
        r = subprocess.run([VENV, os.path.abspath(__file__)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        print("re-exec rc=%d out=%s err=%s" % (r.returncode, r.stdout[-300:], r.stderr[-300:]))
        raise SystemExit(r.returncode)
    raise

import numpy as np
from onnx import helper, TensorProto, numpy_helper

xi = helper.make_tensor_value_info("X", TensorProto.FLOAT, [1, 4])
yo = helper.make_tensor_value_info("Y", TensorProto.FLOAT, [1, 4])
const = numpy_helper.from_array(np.ones([1, 4], dtype=np.float32), name="one")
node = helper.make_node("Add", ["X", "one"], ["Y"])
g = helper.make_graph([node], "tiny_add", [xi], [yo], initializer=[const])
m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 11)])
m.ir_version = 7
onnx.save(m, OUT)
print("written %s (%d bytes)" % (OUT, os.path.getsize(OUT)))
