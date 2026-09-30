/* Poste de saisie des cles fournisseurs — portail :7400, routes AUTHENTIFIEES.
 *
 * Pourquoi ici et pas sur :8766/admin/providers : cette page-la est servie par le
 * hub SANS middleware d'auth (mesure 2026-09-18 : GET /admin/providers -> 200 sans
 * le moindre en-tete). Le portail, lui, a une session. La cle ne part donc que
 * depuis une surface ou l'utilisateur est identifie, et le portail la relaie au hub
 * avec le jeton du coffre — l'ecran n'a jamais a fabriquer une autorite.
 *
 * Regle owner « rien ne doit se lancer au clic » : aucun bouton ici ne DEMARRE quoi
 * que ce soit. Enregistrer/retirer une cle et tester un fournisseur sont des gestes
 * explicitement demandes, et la suppression demande confirmation.
 */
(function () {
  "use strict";

  var etat = { providers: [], filtre: "", tier: "", sansCle: false, ouvert: null };

  function $(sel) { return document.querySelector(sel); }

  function dire(msg, genre) {
    var pile = $("#toasts");
    if (!pile) return;
    var t = document.createElement("div");
    t.className = "laforge-toast laforge-toast-" + (genre || "info");
    t.textContent = msg;
    pile.appendChild(t);
    setTimeout(function () { t.remove(); }, 5000);
  }

  function texte(el, v) { el.textContent = v == null ? "" : String(v); return el; }

  function cellule(contenu, cls) {
    var td = document.createElement("td");
    if (cls) td.className = cls;
    if (contenu instanceof Node) td.appendChild(contenu); else texte(td, contenu);
    return td;
  }

  function pastille(p) {
    var s = document.createElement("span");
    if (!p.vault_key) { s.className = "laforge-status laforge-status-info"; s.textContent = "sans coffre"; return s; }
    if (p.has_key) { s.className = "laforge-status laforge-status-up"; s.textContent = "cle presente"; return s; }
    s.className = "laforge-status laforge-status-down";
    s.textContent = "cle absente";
    return s;
  }

  function visibles() {
    var f = etat.filtre.toLowerCase();
    return etat.providers.filter(function (p) {
      if (f && p.name.toLowerCase().indexOf(f) < 0) return false;
      if (etat.tier && p.tier !== etat.tier) return false;
      if (etat.sansCle && p.has_key) return false;
      return true;
    });
  }

  async function charger() {
    var corps = $("#lignes");
    texte($("#compte"), "lecture…");
    try {
      var r = await fetch("/api/providers/catalogue", { credentials: "same-origin" });
      if (r.status === 401 || r.status === 403) {
        etat.providers = [];
        rendre();
        texte($("#compte"), "session requise");
        dire("Session requise pour lire le catalogue — connecte-toi au portail.", "warn");
        return;
      }
      var j = await r.json();
      if (!j.ok) {
        etat.providers = [];
        rendre();
        // On NOMME ce qu'on n'a pas pu voir : un tableau vide n'est pas « aucun fournisseur ».
        texte($("#compte"), "illisible");
        dire("Catalogue illisible : " + (j.error || "motif non rendu"), "error");
        return;
      }
      etat.providers = j.providers || [];
      etat.hors_catalogue = j.hors_catalogue || {};
      etat.sans_lien = j.sans_lien_d_inscription || [];
      rendre();
    } catch (e) {
      etat.providers = [];
      rendre();
      texte($("#compte"), "illisible");
      dire("Catalogue injoignable : " + e, "error");
    }
  }

  function ligneEdition(p) {
    var tr = document.createElement("tr");
    var td = document.createElement("td");
    td.colSpan = 7;
    td.className = "edition";

    var champ = document.createElement("input");
    champ.type = "password";
    champ.className = "laforge-input";
    champ.placeholder = "coller la cle " + (p.vault_key || "");
    champ.autocomplete = "off";
    champ.spellcheck = false;
    champ.style.minWidth = "320px";

    var voir = document.createElement("button");
    voir.className = "laforge-btn laforge-btn-ghost";
    voir.type = "button";
    voir.textContent = "afficher";
    voir.addEventListener("click", function () {
      champ.type = champ.type === "password" ? "text" : "password";
      voir.textContent = champ.type === "password" ? "afficher" : "masquer";
    });

    var valider = document.createElement("button");
    valider.className = "laforge-btn";
    valider.type = "button";
    valider.textContent = "enregistrer au coffre";
    valider.addEventListener("click", async function () {
      var v = champ.value.trim();
      if (!v) { dire("Rien a enregistrer : le champ est vide.", "warn"); return; }
      valider.disabled = true;
      try {
        var r = await fetch("/api/providers/" + encodeURIComponent(p.name) + "/key", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ api_key: v })
        });
        var j = await r.json();
        champ.value = "";
        if (j.ok) { dire("Ecrit dans " + j.vault_key + " (" + (j.preview || "") + ")", "success"); etat.ouvert = null; await charger(); }
        else dire("Refus : " + (j.error || "motif non rendu"), "error");
      } catch (e) { dire("Echec : " + e, "error"); }
      valider.disabled = false;
    });

    var retirer = document.createElement("button");
    retirer.className = "laforge-btn laforge-btn-danger";
    retirer.type = "button";
    retirer.textContent = "retirer du coffre";
    retirer.disabled = !p.has_key;
    retirer.addEventListener("click", async function () {
      if (!window.confirm("Retirer " + p.vault_key + " du coffre ? Le fournisseur deviendra inutilisable tant qu'aucune cle n'est reposee.")) return;
      try {
        var r = await fetch("/api/providers/" + encodeURIComponent(p.name) + "/key", { method: "DELETE", credentials: "same-origin" });
        var j = await r.json();
        if (j.ok) { dire("Retire : " + j.vault_key, "success"); await charger(); }
        else dire("Refus : " + (j.error || "motif non rendu"), "error");
      } catch (e) { dire("Echec : " + e, "error"); }
    });

    var note = document.createElement("div");
    note.className = "note";
    note.textContent = "La cle part au coffre (DPAPI machine) par le portail authentifie. "
      + "Elle n'est jamais ecrite dans un journal, ni rendue par l'API : seul l'etat present/absent l'est.";

    var barre = document.createElement("div");
    barre.className = "barre";
    [champ, voir, valider, retirer].forEach(function (el) { barre.appendChild(el); });
    td.appendChild(barre);
    td.appendChild(note);
    tr.appendChild(td);
    return tr;
  }

  // RUBRIQUES (demande owner 2026-09-18 : « bien organiser les rubriques »).
  // L'ordre n'est pas esthetique, il est ACTIONNABLE : ce qui attend un geste vient en
  // premier, ce qui fonctionne ensuite, ce qui ne demande rien a la fin. Une liste
  // alphabetique de 39 lignes ne dit pas par ou commencer.
  function rubriqueDe(p) {
    if (p.perime) return "perime";
    if (!p.vault_key) return "local";
    return p.has_key ? "actif" : "a_configurer";
  }

  var RUBRIQUES = [
    { cle: "a_configurer", titre: "À configurer",
      note: "un emplacement au coffre existe, aucune clé n'y est posée" },
    { cle: "actif", titre: "Opérationnels",
      note: "une clé est présente au coffre" },
    { cle: "local", titre: "Locaux",
      note: "servis sur cette machine, aucune clé nécessaire" },
    { cle: "perime", titre: "Retirés par l'éditeur",
      note: "le backend n'existe plus ; les garder visibles évite de les recâbler par erreur" },
  ];

  function ligneGroupe(titre, note, n) {
    var tr = document.createElement("tr");
    tr.className = "groupe";
    var td = document.createElement("td");
    td.colSpan = 7;
    td.innerHTML = "";
    var t = document.createElement("span");
    t.className = "grp-titre";
    t.textContent = titre;
    var c = document.createElement("span");
    c.className = "grp-compte";
    c.textContent = n;
    var d = document.createElement("span");
    d.className = "grp-note";
    d.textContent = note;
    td.appendChild(t); td.appendChild(c); td.appendChild(d);
    tr.appendChild(td);
    return tr;
  }

  function rendre() {
    var corps = $("#lignes");
    corps.textContent = "";
    var liste = visibles();
    texte($("#compte"), liste.length + " / " + etat.providers.length + " fournisseurs");

    if (!liste.length) {
      var vide = document.createElement("tr");
      var td = cellule("Aucun fournisseur ne correspond au filtre.", "vide");
      td.colSpan = 7;
      vide.appendChild(td);
      corps.appendChild(vide);
      return;
    }

    // Tri DANS chaque rubrique, rubriques dans l'ordre d'action.
    var ordonnee = [];
    RUBRIQUES.forEach(function (r) {
      var lot = liste.filter(function (p) { return rubriqueDe(p) === r.cle; });
      if (!lot.length) return;
      lot.sort(function (a, b) { return (a.name || "").localeCompare(b.name || ""); });
      corps.appendChild(ligneGroupe(r.titre, r.note, lot.length));
      lot.forEach(function (p) { ordonnee.push(p); rendreLigne(p, corps); });
    });
    rendreHorsCatalogue();
  }

  function rendreHorsCatalogue() {
    var el = $("#hors-catalogue");
    if (!el) return;
    var hc = etat.hors_catalogue || {};
    var noms = Object.keys(hc);
    el.textContent = "";
    if (!noms.length) return;
    var p = document.createElement("p");
    p.className = "note";
    p.textContent = "Volontairement hors du catalogue de clés — une absence nommée "
      + "n'est pas un oubli :";
    el.appendChild(p);
    var ul = document.createElement("ul");
    ul.className = "hors";
    noms.forEach(function (n) {
      var li = document.createElement("li");
      var b = document.createElement("b");
      b.textContent = n;
      li.appendChild(b);
      li.appendChild(document.createTextNode(" — " + hc[n]));
      ul.appendChild(li);
    });
    el.appendChild(ul);
    if ((etat.sans_lien || []).length) {
      var q = document.createElement("p");
      q.className = "note";
      q.textContent = "Sans lien d'inscription connu (" + etat.sans_lien.length + ") : "
        + etat.sans_lien.join(", ") + " — le domaine de leur endpoint ne mène pas à un "
        + "formulaire, on ne fabrique pas d'adresse.";
      el.appendChild(q);
    }
  }

  function rendreLigne(p, corps) {
      var tr = document.createElement("tr");

      var nom = document.createElement("div");
      nom.className = "nom";
      nom.textContent = p.name;
      var bloc = document.createElement("div");
      bloc.appendChild(nom);
      if (p.perime) {
        var marque = document.createElement("div");
        marque.className = "perime";
        marque.title = p.perime;
        marque.textContent = "retire par l'editeur";
        bloc.appendChild(marque);
      }
      if (p.notes) {
        var n = document.createElement("div");
        n.className = "notes";
        n.title = p.notes;
        n.textContent = p.notes;
        bloc.appendChild(n);
      }
      // FUSION : le lien d'inscription vivait sur une SECONDE page, qui ne savait pas
      // lesquels etaient deja configures. Il est ici, sur la ligne qui porte l'etat.
      if (p.inscription) {
        var ins = document.createElement("a");
        ins.className = "inscription";
        ins.href = p.inscription;
        ins.target = "_blank";
        ins.rel = "noopener";
        ins.textContent = "s'inscrire ↗";
        ins.title = p.inscription;
        bloc.appendChild(ins);
      }
      tr.appendChild(cellule(bloc));
      tr.appendChild(cellule(String(p.tier || "").replace("_", " "), "tier tier-" + p.tier));

      var caps = document.createElement("div");
      caps.className = "caps";
      (p.capabilities || []).forEach(function (c) {
        var s = document.createElement("span");
        s.className = "cap";
        s.textContent = c;
        caps.appendChild(s);
      });
      tr.appendChild(cellule(caps));
      tr.appendChild(cellule(p.context ? p.context.toLocaleString() : "—", "mono"));
      tr.appendChild(cellule(p.vault_key || "—", "mono cle"));
      tr.appendChild(cellule(pastille(p)));

      var actions = document.createElement("div");
      actions.className = "actions";
      var saisir = document.createElement("button");
      saisir.className = "laforge-btn laforge-btn-ghost";
      saisir.type = "button";
      saisir.textContent = etat.ouvert === p.name ? "fermer" : (p.has_key ? "remplacer la cle" : "saisir la cle");
      saisir.disabled = !p.vault_key;
      if (!p.vault_key) saisir.title = "ce fournisseur n'a aucun emplacement de cle au coffre";
      saisir.addEventListener("click", function () {
        etat.ouvert = etat.ouvert === p.name ? null : p.name;
        rendre();
      });
      actions.appendChild(saisir);

      var tester = document.createElement("button");
      tester.className = "laforge-btn laforge-btn-ghost";
      tester.type = "button";
      tester.textContent = "tester";
      tester.addEventListener("click", async function () {
        tester.disabled = true;
        dire("Test de " + p.name + "…", "info");
        try {
          var r = await fetch("/api/providers/" + encodeURIComponent(p.name) + "/test", { method: "POST", credentials: "same-origin" });
          var j = await r.json();
          dire(p.name + " : " + (j.note || j.error || (j.ok ? "ok" : "sans verdict")), j.ok ? "success" : "warn");
        } catch (e) { dire("Echec : " + e, "error"); }
        tester.disabled = false;
      });
      actions.appendChild(tester);
      tr.appendChild(cellule(actions));

      corps.appendChild(tr);
      if (etat.ouvert === p.name) corps.appendChild(ligneEdition(p));
  }

  // ── Acces SSH au coffre (owner 2026-09-25) ────────────────────────────────────
  // « Il ne faut pas mettre en dur mes acces SSH sur la version dist. » Meme chemin que
  // les clefs : saisie ici, relais authentifie, liste blanche et ring gardes par le hub.
  // Aucune VALEUR n'est jamais affichee : seulement OU l'acces est trouve.
  var SOURCE_LIBELLE = {
    coffre: "au coffre DPAPI", wcm: "Credential Manager (par utilisateur)",
    dotenv: "EN CLAIR dans Nokido.env — à migrer", environ: "EN CLAIR dans l'environnement — à migrer"
  };

  async function chargerAcces() {
    var boite = $("#acces-ssh");
    if (!boite) return;
    boite.textContent = "";
    var titre = document.createElement("h3");
    titre.style.margin = "0 0 6px";
    texte(titre, "Accès SSH (TUI) — au coffre, jamais en dur");
    boite.appendChild(titre);
    var note = document.createElement("p");
    note.className = "note";
    texte(note, "Hôte, utilisateur, port et chemin de la clé privée de la console SSH. Stockés au coffre " +
                "DPAPI machine : une version distribuée n'embarque aucun accès.");
    boite.appendChild(note);
    var r, j;
    try {
      r = await fetch("/api/providers/acces", { credentials: "same-origin" });
      j = await r.json();
    } catch (e) {
      boite.appendChild(texte(document.createElement("p"), "Lecture impossible : " + e.message));
      return;
    }
    if (!r.ok || !j.acces) {
      boite.appendChild(texte(document.createElement("p"), "Lecture refusée : " + (j.error || ("HTTP " + r.status))));
      return;
    }
    var table = document.createElement("table");
    table.className = "laforge-table";
    j.acces.forEach(function (a) {
      var tr = document.createElement("tr");
      tr.appendChild(cellule(a.libelle));
      tr.appendChild(cellule(a.cle, "mono cle"));
      var etatTxt = a.source ? SOURCE_LIBELLE[a.source] || a.source : "absent";
      if (a.illisibles && a.illisibles.length) etatTxt += " (illisible : " + a.illisibles.join(", ") + ")";
      var td = cellule(etatTxt);
      if (a.en_clair) td.style.color = "var(--yellow)";
      tr.appendChild(td);
      var champ = document.createElement("input");
      champ.className = "laforge-input";
      champ.autocomplete = "off";
      champ.placeholder = a.source === "coffre" ? "remplacer…" : "saisir…";
      var poser = document.createElement("button");
      poser.className = "laforge-btn";
      poser.type = "button";
      texte(poser, "Enregistrer au coffre");
      poser.addEventListener("click", async function () {
        var v = champ.value;
        if (!v.trim()) { dire("Valeur vide", "error"); return; }
        var rr = await fetch("/api/providers/acces/" + encodeURIComponent(a.cle), {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json" }, body: JSON.stringify({ valeur: v })
        });
        champ.value = "";
        var jj = await rr.json().catch(function () { return {}; });
        dire(rr.ok ? a.cle + " enregistré au coffre" : "Refus : " + (jj.error || rr.status), rr.ok ? "success" : "error");
        chargerAcces();
      });
      var actions = document.createElement("td");
      actions.appendChild(champ);
      actions.appendChild(poser);
      if (a.source === "coffre") {
        var retirer = document.createElement("button");
        retirer.className = "laforge-btn laforge-btn-ghost";
        retirer.type = "button";
        texte(retirer, "Retirer");
        retirer.addEventListener("click", async function () {
          if (!window.confirm("Retirer " + a.cle + " du coffre ?")) return;
          var rr = await fetch("/api/providers/acces/" + encodeURIComponent(a.cle), { method: "DELETE", credentials: "same-origin" });
          dire(rr.ok ? a.cle + " retiré du coffre" : "Refus : HTTP " + rr.status, rr.ok ? "success" : "error");
          chargerAcces();
        });
        actions.appendChild(retirer);
      }
      tr.appendChild(actions);
      table.appendChild(tr);
    });
    boite.appendChild(table);
  }

  function armer() {
    $("#filtre").addEventListener("input", function (e) { etat.filtre = e.target.value; rendre(); });
    $("#tier").addEventListener("change", function (e) { etat.tier = e.target.value; rendre(); });
    $("#sans-cle").addEventListener("change", function (e) { etat.sansCle = e.target.checked; rendre(); });
    $("#relire").addEventListener("click", charger);
    charger();
    chargerAcces();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", armer);
  else armer();
})();
