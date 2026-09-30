import os
import re
import shutil
import sys
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
LAFORGE_APP_DIR = ROOT_DIR / "LaForge" / "app"
TEMPLATE_DIR = LAFORGE_APP_DIR / "mcp_agent_template"
ORGANIGRAMME_PATH = ROOT_DIR / "ORGANIGRAMME_AGENTS.md"

if not TEMPLATE_DIR.exists():
    print(f"Error: Template directory not found at {TEMPLATE_DIR}")
    sys.exit(1)

if not ORGANIGRAMME_PATH.exists():
    print(f"Error: Organigramme not found at {ORGANIGRAMME_PATH}")
    sys.exit(1)

def sanitize_name(name: str) -> str:
    """Convert an agent name to a safe folder/variable name."""
    # Remove 'Agent ' prefix if present for the folder name
    clean_name = name.lower()
    clean_name = re.sub(r'[^a-z0-9]+', '_', clean_name)
    clean_name = clean_name.strip('_')
    if not clean_name.startswith('agent_'):
        clean_name = 'agent_' + clean_name
    return clean_name

def process_organigramme():
    with open(ORGANIGRAMME_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    current_branch = ""
    current_discipline = ""
    agents = []

    for line in content.split('\n'):
        line = line.strip()
        
        # Match Branch (### 01. Ingénierie ...)
        branch_match = re.match(r'^###\s+\d+\.\s+(.+)$', line)
        if branch_match:
            current_branch = branch_match.group(1).strip()
            continue
            
        # Match Discipline (- **Architecture & Infrastructures**)
        discipline_match = re.match(r'^-\s+\*\*(.+)\*\*$', line)
        if discipline_match:
            current_discipline = discipline_match.group(1).strip()
            continue
            
        # Match Agent (- `Agent Architecte Cloud`)
        agent_match = re.match(r'^-\s+`Agent (.+)`$', line)
        if agent_match:
            agent_raw_name = agent_match.group(1).strip()
            agents.append({
                'raw_name': f"Agent {agent_raw_name}",
                'safe_name': sanitize_name(agent_raw_name),
                'branch': current_branch,
                'discipline': current_discipline
            })

    return agents

def create_agent(agent_data, port):
    safe_name = agent_data['safe_name']
    raw_name = agent_data['raw_name']
    branch = agent_data['branch']
    discipline = agent_data['discipline']
    
    agent_dir = LAFORGE_APP_DIR / safe_name
    
    if agent_dir.exists():
        print(f"Skipping {safe_name} (already exists)")
        return False
        
    print(f"Creating {safe_name} on port {port}...")
    
    # 1. Copy template
    shutil.copytree(TEMPLATE_DIR, agent_dir)
    
    # 2. Modify config.py
    config_path = agent_dir / "config.py"
    with open(config_path, 'r', encoding='utf-8') as f:
        config_content = f.read()
        
    config_content = re.sub(r'AGENT_NAME\s*=\s*".*"', f'AGENT_NAME = "{safe_name}"', config_content)
    config_content = re.sub(r'HTTP_PORT\s*=\s*\d+', f'HTTP_PORT = {port}', config_content)
    
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(config_content)
        
    # 3. Modify agent_core.py
    core_path = agent_dir / "agent_core.py"
    with open(core_path, 'r', encoding='utf-8') as f:
        core_content = f.read()
        
    # Define custom prompt and class docstring
    custom_docstring = f'''    """
    Cœur logique de l'{raw_name}.
    Branche : {branch}
    Discipline : {discipline}
    """'''
    
    # We will inject the prompt in the __init__ method
    init_logic = f'''        self.system_prompt = (
            "Tu es un {raw_name} spécialisé dans la discipline '{discipline}', "
            "faisant partie de la branche '{branch}'. "
            "Ton rôle est d'apporter ton expertise métier précise à l'écosystème LaForge."
        )
        print(f"[{{self.__class__.__name__}}] Initialisation de l'{raw_name}...")'''

    # Basic regex replacement to inject our custom logic
    # Replace docstring
    core_content = re.sub(
        r'    """\n    The core logic of the specialized agent.*?\n    """', 
        custom_docstring, 
        core_content, 
        flags=re.DOTALL
    )
    
    # Replace __init__ body
    core_content = re.sub(
        r'        # Here you can initialize any resources the agent needs,.*?\n        print\("Initializing AgentCore\.\.\."\)',
        init_logic,
        core_content,
        flags=re.DOTALL
    )

    # Replace capabilities specialty
    core_content = re.sub(
        r'"protocol": "mcp",',
        f'"protocol": "mcp",\n            "specialty": "{raw_name}",',
        core_content
    )

    with open(core_path, 'w', encoding='utf-8') as f:
        f.write(core_content)
        
    # 4. Modify Dockerfile
    dockerfile_path = agent_dir / "Dockerfile"
    with open(dockerfile_path, 'r', encoding='utf-8') as f:
        docker_content = f.read()
        
    docker_content = re.sub(r'COPY app/mcp_agent_template/ \./', f'COPY app/{safe_name}/ ./', docker_content)
    docker_content = re.sub(r'EXPOSE \d+', f'EXPOSE {port}', docker_content)
    
    with open(dockerfile_path, 'w', encoding='utf-8') as f:
        f.write(docker_content)
        
    return True

def main():
    agents = process_organigramme()
    print(f"Found {len(agents)} agents in the organigramme.")
    
    # Start ports from 9002 (9001 is already taken by architecte_cloud)
    base_port = 9002
    created_count = 0
    
    for i, agent in enumerate(agents):
        # Specific override: skip agent_architecte_cloud as we already created it manually on port 9001
        if agent['safe_name'] == 'agent_architecte_cloud':
            continue
            
        port = base_port + created_count
        if create_agent(agent, port):
            created_count += 1
            
    print(f"\nSuccessfully generated {created_count} new agents.")

if __name__ == "__main__":
    main()
