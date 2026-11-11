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
            
            if func_name in ["os.system", "subprocess.run", "subprocess.Popen", "subprocess.call", "subprocess.check_call", "subprocess.check_output"]:
                args = []
                for arg in node.args:
                    if isinstance(arg, ast.Constant):
                        args.append(str(arg.value))
                    elif isinstance(arg, ast.List):
                        args.extend([str(elt.value) for elt in arg.elts if isinstance(elt, ast.Constant)])
                    elif isinstance(arg, ast.JoinedStr):
                        args.append(" ".join(str(v.value) for v in arg.values if isinstance(v, ast.Constant)))
                
                arg_str = " ".join(args).lower()
                if "install" in arg_str or "apt-get" in arg_str or "npm" in arg_str or "download" in arg_str or "curl" in arg_str or "wget" in arg_str:
                    res.append(f"{filepath}:{node.lineno} - {func_name} - {arg_str}")
    return res

results = []
for p in Path('.').rglob('*.py'):
    if 'site-packages' in p.parts or 'venv' in p.parts or '.venv' in p.parts or 'node_modules' in p.parts: continue
    results.extend(check_file(p))

for r in results:
    print(r)
