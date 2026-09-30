/* Nokido — préférences persistantes partagées entre écrans (localStorage).
   Clés : nokido.power (0-100), nokido.theme (dark|light|auto), nokido.lang (fr|en|es|de).
   Charger AVANT les scripts d'app : <script src="…/assets/laforge-prefs.js"></script> */
(function () {
  "use strict";
  var NS = "nokido.";
  function get(key, fallback) {
    try {
      var raw = localStorage.getItem(NS + key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch (e) { return fallback; }
  }
  function set(key, value) {
    try { localStorage.setItem(NS + key, JSON.stringify(value)); } catch (e) {}
  }
  function applyTheme(theme) {
    var t = theme || get("theme", "dark");
    document.documentElement.setAttribute("data-theme", t);
    return t;
  }
  function cycleTheme() {
    var order = ["dark", "light", "auto"];
    var cur = get("theme", "dark");
    var next = order[(order.indexOf(cur) + 1) % order.length];
    set("theme", next);
    applyTheme(next);
    return next;
  }
  // Applique le thème mémorisé dès le chargement (évite le flash).
  applyTheme();
  window.NokidoPrefs = { get: get, set: set, applyTheme: applyTheme, cycleTheme: cycleTheme };
})();
