<string>:30: SyntaxWarning: invalid escape sequence '\l'
<string>:36: SyntaxWarning: invalid escape sequence '\{'
@REM symlinks pour mode ROUTER llama-server (genere automatiquement)
@REM Lancer en PowerShell ADMIN depuis le repo root.
@echo off
set "DEST=data\llm_models"
if not exist "%DEST%\" mkdir "%DEST%"

mklink "%DEST%\qwen2.5-coder-7b-q4_K_M.gguf" "%USERPROFILE%\.ollama\models\blobs\sha256-60e05f2100071479f596b964f89f510f057ce397ea22f2833a0cfe029bfc2463"
mklink "%DEST%\qwen2.5-coder-1.5b-q4_K_M.gguf" "%USERPROFILE%\.ollama\models\blobs\sha256-29d8c98fa6b098e200069bfb88b9508dc3e85586d20cba59f8dda9a808165104"
mklink "%DEST%\laforge-qwen-1b-q4_K_M.gguf" "%USERPROFILE%\.ollama\models\blobs\sha256-29d8c98fa6b098e200069bfb88b9508dc3e85586d20cba59f8dda9a808165104"
mklink "%DEST%\qwen3-8b-q4_K_M.gguf" "%USERPROFILE%\.ollama\models\blobs\sha256-a3de86cd1c132c822487ededd47a324c50491393e6565cd14bafa40d0b8e686f"
mklink "%DEST%\deepseek-coder-6.7b-q4_0.gguf" "%USERPROFILE%\.ollama\models\blobs\sha256-59bb50d8116b6a1f9bfbb940d6bb946a05554e591e30c8c2429ed6c854867ecb"
mklink "%DEST%\gemma4-e4b-q4_K_M.gguf" "%USERPROFILE%\.ollama\models\blobs\sha256-4c27e0f5b5adf02ac956c7322bd2ee7636fe3f45a8512c9aba5385242cb6e09a"
