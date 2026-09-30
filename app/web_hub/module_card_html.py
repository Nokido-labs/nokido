# GÉNÉRÉ par forge_ui_moulinette depuis design_handoff_nokido/components/modules/ModuleCard.
# Cœur déterministe (0 token cloud). Cible web_hub HTMX/Alpine + tokens laforge-ds.
from __future__ import annotations


def render_module_card(m):
    """Généré par forge_ui_moulinette (déterministe). Cible web_hub HTMX/Alpine/laforge-ds."""
    import html as _h
    _e = lambda v: _h.escape(str(v))
    parts = []
    accent = 'var(--domain-%s)' % m.get('domain', 'transport')
    dim = bool(m.get('coming_soon') or not m.get('enabled', True))
    _bg = 'var(--bg-1)' if dim else 'var(--bg-2)'
    _op = '0.55' if m.get('coming_soon') else '1'
    _dot = {'up':'var(--green)','down':'var(--red)','warn':'var(--yellow)'}.get(m.get('status'))
    _prov = {'local':'LOCAL','hybrid':'HYBRIDE','remote':'DISTANT'}.get(m.get('provenance'))
    _provc = {'local':'var(--prov-local)','hybrid':'var(--prov-hybrid)','remote':'var(--prov-remote)'}.get(m.get('provenance'))
    _titlec = 'var(--text-secondary)' if dim else 'var(--text-primary)'
    parts.append('<div style="position:relative;border:1px solid var(--border);border-radius:var(--radius-md);padding:16px;overflow:hidden;background:' + _e(_bg) + ';opacity:' + _e(_op) + '" data-domain="' + _e(m['domain']) + '" data-testid="module-' + _e(m['domain']) + '">')
    parts.append('<div style="position:absolute;left:0;top:0;bottom:0;width:3px;background:' + _e(accent) + '">')
    parts.append('</div>')
    parts.append('<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px">')
    parts.append('<div style="display:inline-flex;align-items:center;justify-content:center;height:40px;width:40px;border-radius:var(--radius-sm);color:' + _e(accent) + ';background:color-mix(in srgb, ' + _e(accent) + ' 16%, transparent)">')
    parts.append('<i data-lucide="' + _e(m['icon']) + '">')
    parts.append('</i>')
    parts.append('</div>')
    if m.get('coming_soon'):
        parts.append('<span style="font-family:var(--font-mono);font-size:9.5px;font-weight:700;color:var(--text-dim);border:1px solid var(--border);border-radius:4px;padding:1px 6px">')
        parts.append('BIENTÔT')
        parts.append('</span>')
    else:
        if m.get('toggleable'):
            parts.append('<button aria-label="Activer le module" type="button" data-testid="module-' + _e(m['domain']) + '-toggle" style="width:38px;height:22px;border-radius:var(--radius-pill);border:none;cursor:pointer;position:relative;flex-shrink:0;background:' + _e(accent) + '" hx-post="/module/' + _e(m['domain']) + '/toggle" hx-swap="outerHTML">')
            parts.append('<span style="position:absolute;top:3px;left:19px;width:16px;height:16px;border-radius:50%;background:#fff">')
            parts.append('</span>')
            parts.append('</button>')
        else:
            if _dot:
                parts.append('<span style="width:10px;height:10px;border-radius:50%;background:' + _e(_dot) + '">')
                parts.append('</span>')
    parts.append('</div>')
    parts.append('<h3 style="margin:12px 0 0;font-size:16px;font-weight:700;color:' + _e(_titlec) + ';display:flex;align-items:center;gap:7px">')
    parts.append('<span style="display:contents">')
    parts.append(_e(m['title']))
    parts.append('</span>')
    if m.get('pinned'):
        parts.append('<span style="color:' + _e(accent) + ';font-size:12px">')
        parts.append('📌')
        parts.append('</span>')
    parts.append('</h3>')
    if m.get('desc'):
        parts.append('<p style="margin:4px 0 0;font-size:12.5px;color:var(--text-secondary);line-height:1.45">')
        parts.append(_e(m['desc']))
        parts.append('</p>')
    if _prov:
        parts.append('<div style="margin-top:12px">')
        parts.append('<span style="display:inline-flex;align-items:center;gap:6px;font-family:var(--font-mono);font-size:10px;font-weight:600;color:' + _e(_provc) + '">')
        parts.append('<span style="width:6px;height:6px;border-radius:50%;background:currentColor">')
        parts.append('</span>')
        parts.append('<span style="display:contents">')
        parts.append(_e(_prov))
        parts.append('</span>')
        parts.append('</span>')
        parts.append('</div>')
    parts.append('</div>')
    return ''.join(parts)
