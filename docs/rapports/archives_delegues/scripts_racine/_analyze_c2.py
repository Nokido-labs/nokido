import ast
import os
import glob
from pathlib import Path

def check_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        tree = ast.parse(content)
    except Exception as e:
        return []
    
    res = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name):
                    func_name = node.func.value.id + "." + node.func.attr
            elif isinstance(node.func, ast.Name):
                func_name = node.func.id
            
            if "Queue" in func_name or "PriorityQueue" in func_name:
                has_maxsize = any(kw.arg == "maxsize" for kw in node.keywords) if getattr(node, 'keywords', None) else False
                if not has_maxsize and len(node.args) == 0:
                    res.append(f"{filepath}:{node.lineno} - {func_name} sans maxsize")
    return res

results = []
for p in Path('.').rglob('*.py'):
    if 'site-packages' in p.parts or 'venv' in p.parts or '.venv' in p.parts or 'node_modules' in p.parts: continue
    results.extend(check_file(p))

for r in results:
    print(r)
