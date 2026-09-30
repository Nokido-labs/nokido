/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
/* Nokido — Écran de verrouillage au démarrage : mot de passe + choix de langue.
   Coffre souverain : le déverrouillage est local. i18n FR/EN/ES/DE. */
const { Button, TextInput, ProvenanceBadge, Badge } = window.NokidoDesignSystem_bdc2ac;

const I18N = {
  fr: { name: "Français", title: "Déverrouille ton hub", sub: "Coffre souverain — tout reste sur ta machine.",
    pwd: "Mot de passe", ph: "Ton mot de passe local", unlock: "Déverrouiller", forgot: "Phrase de récupération",
    offline: "Hors-ligne · le coffre ne quitte jamais l'appareil", err: "Mot de passe incorrect", lang: "Langue", bio: "Déverrouiller par biométrie" },
  en: { name: "English", title: "Unlock your hub", sub: "Sovereign vault — everything stays on your machine.",
    pwd: "Password", ph: "Your local password", unlock: "Unlock", forgot: "Recovery phrase",
    offline: "Offline · the vault never leaves the device", err: "Incorrect password", lang: "Language", bio: "Unlock with biometrics" },
  es: { name: "Español", title: "Desbloquea tu hub", sub: "Bóveda soberana — todo se queda en tu máquina.",
    pwd: "Contraseña", ph: "Tu contraseña local", unlock: "Desbloquear", forgot: "Frase de recuperación",
    offline: "Sin conexión · la bóveda nunca sale del dispositivo", err: "Contraseña incorrecta", lang: "Idioma", bio: "Desbloquear con biometría" },
  de: { name: "Deutsch", title: "Entsperre dein Hub", sub: "Souveräner Tresor — alles bleibt auf deinem Gerät.",
    pwd: "Passwort", ph: "Dein lokales Passwort", unlock: "Entsperren", forgot: "Wiederherstellungsphrase",
    offline: "Offline · der Tresor verlässt das Gerät nie", err: "Falsches Passwort", lang: "Sprache", bio: "Mit Biometrie entsperren" },
};
const LANGS = ["fr", "en", "es", "de"];
const FLAG = { fr: "FR", en: "EN", es: "ES", de: "DE" };

function LIco({ n, s = 16 }) { return <i data-lucide={n} style={{ width: s, height: s }} />; }

function LogoMark({ size = 60, animated = true }) {
  return (
    <svg className={"lf-logmark" + (animated ? " anim" : "")} width={size} height={size} viewBox="0 0 64 64" fill="none" style={{ overflow: "visible" }}>
      <defs><linearGradient id="loginBolt" x1="26" y1="12" x2="40" y2="40" gradientUnits="userSpaceOnUse"><stop offset="0" stopColor="#FFE070" /><stop offset="1" stopColor="#FFC22D" /></linearGradient></defs>
      <g className="anvil" stroke="#15121F" strokeWidth="2.4" strokeLinejoin="round">
        <path d="M6 35 L20 31 H48 q4 0 4 3.5 Q52 39 47 39 H39 q-3 0 -4 3 l-1.5 3 H27 q-1 -3 -4 -3 H15 Q6 42 6 35 Z" fill="#9A90BC" />
        <path d="M28 45 h8 l-1.5 5 h-5 Z" fill="#6F6498" />
        <path d="M17 50 H47 l3 6 H14 Z" fill="#9A90BC" />
      </g>
      <g className="hammer">
        <rect x="4" y="29" width="23" height="5" rx="2.5" fill="#C77D4A" stroke="#15121F" strokeWidth="2.4" strokeLinejoin="round" />
        <rect x="25" y="21" width="11" height="21" rx="3" fill="#B7BCD2" stroke="#15121F" strokeWidth="2.4" strokeLinejoin="round" />
        <rect x="27.5" y="24" width="5.5" height="6" rx="1.5" fill="#D9DCE8" />
      </g>
      <path className="bolt" d="M31 41 L40 26 H34 L42 11 L30 28 H36 Z" fill="url(#loginBolt)" stroke="#15121F" strokeWidth="2" strokeLinejoin="round" />
    </svg>
  );
}

function LangSwitch({ lang, setLang }) {
  return (
    <div style={{ display: "inline-flex", gap: "4px", padding: "4px", background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: "var(--radius-pill)" }}>
      {LANGS.map((l) => {
        const on = lang === l;
        return (
          <button key={l} onClick={() => setLang(l)} title={I18N[l].name} aria-pressed={on} style={{
            display: "inline-flex", alignItems: "center", justifyContent: "center", minWidth: "38px", height: "30px",
            padding: "0 10px", borderRadius: "var(--radius-pill)", border: "none", cursor: "pointer",
            fontFamily: "var(--font-mono)", fontSize: "11px", fontWeight: 700, letterSpacing: "0.3px",
            background: on ? "var(--purple)" : "transparent", color: on ? "#fff" : "var(--text-secondary)",
            transition: "all var(--motion-fast)",
          }}>{FLAG[l]}</button>
        );
      })}
    </div>
  );
}

function LoginScreen({ onUnlock }) {
  const PREF = window.NokidoPrefs;
  const [lang, setLang] = React.useState(() => PREF ? PREF.get("lang", "fr") : "fr");
  const setLangP = (l) => { setLang(l); if (PREF) PREF.set("lang", l); };
  const [pwd, setPwd] = React.useState("");
  const [show, setShow] = React.useState(false);
  const [err, setErr] = React.useState(false);
  const t = I18N[lang];

  React.useEffect(() => { if (window.lucide) lucide.createIcons(); });

  const submit = (e) => {
    e && e.preventDefault();
    if (pwd.trim().length < 3) { setErr(true); return; }
    setErr(false);
    onUnlock && onUnlock();
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
      padding: "24px", boxSizing: "border-box", position: "relative" }}>

      {/* Sélecteur de langue — coin haut-droit */}
      <div style={{ position: "absolute", top: "20px", right: "20px", display: "flex", alignItems: "center", gap: "8px" }}>
        <LIco n="languages" s={15} />
        <LangSwitch lang={lang} setLang={setLangP} />
      </div>

      {/* Carte de déverrouillage */}
      <form onSubmit={submit} style={{ width: "100%", maxWidth: "380px", background: "var(--bg-1)",
        border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "30px 26px",
        boxShadow: "var(--shadow-lg)", display: "flex", flexDirection: "column", alignItems: "center", gap: "4px" }}>

        <LogoMark size={62} />
        <div style={{ display: "inline-flex", alignItems: "center", gap: "8px", marginTop: "8px" }}>
          <span style={{ fontFamily: "var(--font-sans)", fontWeight: 800, fontSize: "20px", letterSpacing: "0.3px",
            background: "linear-gradient(90deg, var(--text-primary), #B98BFF)", WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>Nokido</span>
        </div>

        <h1 style={{ margin: "10px 0 4px", fontSize: "20px", fontWeight: 700, textAlign: "center" }}>{t.title}</h1>
        <p style={{ margin: "0 0 6px", fontSize: "12.5px", color: "var(--text-secondary)", textAlign: "center", lineHeight: 1.45 }}>{t.sub}</p>

        <div style={{ margin: "8px 0 14px" }}>
          <ProvenanceBadge origin="local" label={t.offline} size="sm" />
        </div>

        <div style={{ width: "100%", position: "relative" }}>
          <TextInput
            label={t.pwd} type={show ? "text" : "password"} placeholder={t.ph}
            value={pwd} onChange={(e) => { setPwd(e.target.value); setErr(false); }}
            icon={<LIco n="lock" s={15} />} invalid={err} hint={err ? t.err : null}
          />
          <button type="button" onClick={() => setShow((s) => !s)} aria-label="show/hide" style={{
            position: "absolute", right: "10px", top: "30px", border: "none", background: "transparent",
            color: "var(--text-dim)", cursor: "pointer", display: "inline-flex", padding: "4px" }}>
            <LIco n={show ? "eye-off" : "eye"} s={16} />
          </button>
        </div>

        <Button variant="primary" size="lg" type="submit" style={{ width: "100%", marginTop: "16px" }} iconRight={<LIco n="arrow-right" s={16} />}>{t.unlock}</Button>

        <button type="button" onClick={submit} style={{ display: "inline-flex", alignItems: "center", gap: "8px", marginTop: "12px",
          border: "1px solid var(--border)", background: "transparent", color: "var(--text-secondary)", cursor: "pointer",
          padding: "8px 14px", borderRadius: "var(--radius-sm)", fontSize: "12.5px", fontFamily: "var(--font-sans)" }}>
          <LIco n="fingerprint" s={16} />{t.bio}
        </button>

        <a href="#" onClick={(e) => e.preventDefault()} style={{ fontSize: "11.5px", color: "var(--text-dim)", marginTop: "14px", fontFamily: "var(--font-mono)" }}>{t.forgot}</a>
      </form>

      <div style={{ marginTop: "18px", display: "flex", alignItems: "center", gap: "8px",
        fontFamily: "var(--font-mono)", fontSize: "10.5px", color: "var(--text-dim)" }}>
        <span className="laforge-pulse" style={{ width: "6px", height: "6px", borderRadius: "50%", background: "var(--prov-local)" }} />
        Ring 0 · nœud souverain · v18.3
      </div>

      <style>{`
        .lf-logmark.anim .hammer { transform-box: view-box; transform-origin: 6px 31px; animation: lf-swing 1.3s cubic-bezier(.5,0,.4,1) infinite; }
        .lf-logmark.anim .bolt { transform-box: view-box; transform-origin: 31px 40px; opacity:0; animation: lf-flash 1.3s linear infinite; }
        .lf-logmark.anim .anvil { transform-box: view-box; transform-origin: 32px 54px; animation: lf-squash 1.3s linear infinite; }
        @keyframes lf-swing { 0%{transform:rotate(-38deg)} 29%{transform:rotate(2deg)} 38%{transform:rotate(-5deg)} 46%{transform:rotate(0deg)} 100%{transform:rotate(-38deg)} }
        @keyframes lf-flash { 0%,26%{opacity:0;transform:scale(.4)} 31%{opacity:1;transform:scale(1.1)} 43%{opacity:1;transform:scale(1)} 58%{opacity:0} 100%{opacity:0} }
        @keyframes lf-squash { 0%,26%{transform:scaleY(1)} 31%{transform:scaleY(.93) translateY(2px)} 43%{transform:scaleY(1.02)} 50%,100%{transform:scaleY(1)} }
        @media (prefers-reduced-motion: reduce){ .lf-logmark.anim .hammer{animation:none} .lf-logmark.anim .bolt{animation:none;opacity:1} .lf-logmark.anim .anvil{animation:none} }
      `}</style>
    </div>
  );
}

Object.assign(window, { LoginScreen });
