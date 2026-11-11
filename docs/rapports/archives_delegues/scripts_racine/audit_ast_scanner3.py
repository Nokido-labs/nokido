import ast
import os
import json
import time

def is_call_to(node, module_names, func_names):
    if isinstance(node.func, ast.Name):
        return node.func.id in func_names
    elif isinstance(node.func, ast.Attribute):
        if isinstance(node.func.value, ast.Name):
            return node.func.value.id in module_names and node.func.attr in func_names
    return False

def get_primitive_name(node, module):
    if isinstance(node.func, ast.Name):
        return f"{module}.{node.func.id}"
    elif isinstance(node.func, ast.Attribute):
        return f"{module}.{node.func.attr}"
    return f"{module}.unknown"

def check_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return {'status': 'error', 'reason': f'read error'}
    
    try:
        tree = ast.parse(content, filename=filepath)
    except Exception as e:
        return {'status': 'error', 'reason': f'parse error'}

    findings = []
    
    class Visitor(ast.NodeVisitor):
        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id in ('eval', 'exec', 'compile', '__import__'):
                findings.append({'line': node.lineno, 'primitive': node.func.id})
            
            if isinstance(node.func, ast.Name) and node.func.id == 'type' and len(node.args) == 3:
                findings.append({'line': node.lineno, 'primitive': 'type(3-args)'})
            
            if is_call_to(node, ['pickle', '_pickle'], ['load', 'loads']):
                findings.append({'line': node.lineno, 'primitive': get_primitive_name(node, 'pickle')})
            
            if is_call_to(node, ['marshal'], ['load', 'loads']):
                findings.append({'line': node.lineno, 'primitive': get_primitive_name(node, 'marshal')})
            
            if is_call_to(node, ['importlib'], ['import_module']):
                findings.append({'line': node.lineno, 'primitive': 'importlib.import_module'})
            if isinstance(node.func, ast.Name) and node.func.id == 'import_module':
                 findings.append({'line': node.lineno, 'primitive': 'import_module'})

            if is_call_to(node, ['yaml'], ['load']):
                safe = False
                for kw in node.keywords:
                    if kw.arg == 'Loader':
                        if isinstance(kw.value, ast.Attribute) and kw.value.attr == 'SafeLoader':
                            safe = True
                if not safe:
                    findings.append({'line': node.lineno, 'primitive': 'yaml.load(!SafeLoader)'})
            
            if is_call_to(node, ['os'], ['system']):
                findings.append({'line': node.lineno, 'primitive': 'os.system'})
            if isinstance(node.func, ast.Name) and node.func.id == 'system':
                findings.append({'line': node.lineno, 'primitive': 'system'})

            if is_call_to(node, ['subprocess'], ['run', 'Popen', 'call', 'check_call', 'check_output']):
                shell_true = False
                for kw in node.keywords:
                    if kw.arg == 'shell':
                        if isinstance(kw.value, ast.Constant) and kw.value.value == True:
                            shell_true = True
                if shell_true:
                    findings.append({'line': node.lineno, 'primitive': get_primitive_name(node, 'subprocess') + '(shell=True)'})

            self.generic_visit(node)

    visitor = Visitor()
    visitor.visit(tree)
    
    return {'status': 'ok', 'findings': findings}

def main():
    root_dir = r'%NOKIDO_ROOT%'
    results = {'parsed': [], 'errors': {}, 'findings': {}}
    
    with open(os.path.join(root_dir, 'git_py_files.txt'), 'r', encoding='utf-8') as f:
        py_files = [line.strip() for line in f if line.strip()]
        
    print(f"Found {len(py_files)} Python files to parse. Parsing...")
    
    start_time = time.time()
    for relpath in py_files:
        filepath = os.path.join(root_dir, relpath)
        if not os.path.exists(filepath):
            continue
        res = check_file(filepath)
        if res['status'] == 'error':
            results['errors'][relpath] = res['reason']
        else:
            results['parsed'].append(relpath)
            if res['findings']:
                results['findings'][relpath] = res['findings']
                        
    out_path = os.path.join(root_dir, 'audit_ast_results_git.json')
    with open(out_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"DONE in {time.time()-start_time:.1f}s, parsed {len(results['parsed'])} files, wrote to {out_path}")

if __name__ == '__main__':
    main()
