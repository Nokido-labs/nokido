# JEA Nokido — Niveau 3 Sandbox

## Installation (Admin requis)
```powershell
# Run as Administrator
cd '~\Script python IA\Nokido'
.\config\jea\install_jea.ps1
```

## Usage dans forge_ps_sandbox.py
```python
sb = PowerShellSandbox(mode='JEA', jea_config='Nokido_SysAdmin')
result = sb.run('Get-Service LaForgeMCP')
```

## Commandes autorisées
- Get-Process, Get-Service, Get-NetTCPConnection
- Start/Stop/Restart-Service LaForgeMCP uniquement
- netstat, ipconfig, ping
- LanguageMode = ConstrainedLanguage (N2 inclus)
