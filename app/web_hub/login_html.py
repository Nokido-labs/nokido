"""
app/web_hub/login_html.py - Rendu HTML page de login (CSP-strict).

Contraintes :
- Aucun script externe (pas de CDN).
- Aucun inline <script> (pour permettre CSP stricte sans nonce).
- Styles inlines minimaux (accepte via CSP style-src 'self' 'unsafe-inline'
  mais on peut migrer vers style-src 'self' + <style> file plus tard).
"""

from __future__ import annotations


_LOGIN_HTML = """<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nokido Hub - Login</title>
<link rel="icon" type="image/svg+xml" href="/static/nokido-favicon.svg">
<style>
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; height: 100%; }
  body {
    background: #0a0e14;
    color: #e6edf3;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    display: flex; align-items: center; justify-content: center;
    min-height: 100vh;
  }
  .box {
    background: #11151c;
    border: 1px solid #1f2937;
    border-radius: 12px;
    padding: 2rem 2.5rem;
    width: 100%;
    max-width: 380px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.35);
  }
  .logo {
    width: 48px; height: 48px; border-radius: 10px;
    background: linear-gradient(135deg,#3b82f6,#a855f7);
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; color: white;
    margin-bottom: 1.2rem;
  }
  h1 { font-size: 1.35rem; margin: 0 0 0.25rem; }
  p.hint { color: #94a3b8; font-size: 0.85rem; margin: 0 0 1.5rem; }
  label {
    display: block; font-size: 0.8rem; color: #94a3b8;
    margin-bottom: 0.35rem; text-transform: uppercase; letter-spacing: 0.05em;
  }
  input[type=password], input[type=text] {
    width: 100%; padding: 0.7rem 0.85rem;
    background: #0a0e14; border: 1px solid #1f2937; border-radius: 8px;
    color: #e6edf3; font-family: ui-monospace, monospace; font-size: 0.95rem;
    outline: none;
  }
  input:focus { border-color: #3b82f6; }
  button {
    width: 100%; margin-top: 1.2rem;
    padding: 0.75rem 1rem; border: 0; border-radius: 8px;
    background: #3b82f6; color: white; font-weight: 600;
    cursor: pointer; font-size: 0.95rem;
  }
  button:hover { background: #2563eb; }
  .err {
    background: #7f1d1d; border: 1px solid #991b1b; color: #fecaca;
    padding: 0.6rem 0.85rem; border-radius: 8px;
    font-size: 0.85rem; margin-bottom: 1rem;
  }
  footer {
    margin-top: 1.5rem; text-align: center; font-size: 0.75rem; color: #475569;
  }
</style>
</head><body>
<form class="box" method="post" action="/auth/login" autocomplete="off">
  <img src="/static/nokido-mark.svg" alt="Nokido" width="48" height="48">
  <h1>Nokido Hub</h1>
  <p class="hint">Authentification requise</p>
  __ERROR__
  <label for="admin_token">Admin token</label>
  <input type="password" id="admin_token" name="admin_token" required autofocus spellcheck="false" autocapitalize="off" data-testid="login-token">
  <input type="hidden" name="redirect_to" value="__REDIRECT__">
  <button type="submit" data-testid="login-submit">Entrer</button>
  <footer>v__VERSION__ &middot; cookie session httpOnly</footer>
</form>
</body></html>
"""


def render_login(version: str, error: str = "", redirect_to: str = "/") -> str:
    import html as _h

    err_html = ""
    if error:
        err_html = f'<div class="err">{_h.escape(error)}</div>'
    safe_redirect = redirect_to if redirect_to.startswith("/") else "/"
    return (
        _LOGIN_HTML.replace("__ERROR__", err_html)
        .replace("__VERSION__", _h.escape(version))
        .replace("__REDIRECT__", _h.escape(safe_redirect))
    )


__all__ = ["render_login"]
