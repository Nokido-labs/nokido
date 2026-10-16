// ==UserScript==
// @name         Nokido Pair - Gemini Web Client
// @namespace    https://nokido.local/pair
// @version      1.0.0
// @description  Panneau latéral souverain pour relier Gemini Web (gemini.google.com) au connecteur des pairs Nokido (lecture et quarantaine)
// @author       Nokido / AGY
// @match        https://gemini.google.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_deleteValue
// @connect      *
// @run-at       document-idle
// ==/UserScript==

(function() {
    'use strict';

    // ── CONSTANTES DE SÉCURITÉ ET PROTOCOLE ───────────────────────────────────
    // Surface MCP figée des pairs (NR test_pair_mcp_nr) : lecture + quarantaine uniquement.
    const OUTILS_LECTURE = [
        "etat_corps",
        "point_ssot",
        "recherche_rag",
        "journal_commits",
        "derniere_capsule"
    ];

    const OUTILS_PAIR = [
        "proposer_fait",
        "envoyer_message",
        "soumettre_tache",
        "lire_reponses",
        "suivre"
    ];

    const OUTILS_AUTORISES = OUTILS_LECTURE.concat(OUTILS_PAIR);

    const DESTINATAIRES_VALIDES = ["OWNER", "CLAUDE", "ANTIGRAVITY", "GEMINI"];
    const INTENTS_VALIDES = [
        "REVIEW_FINDING",
        "COLLAB_PING",
        "NEED_CLARIFY",
        "REVIEW_UNKNOWN",
        "FACT_PROPOSED"
    ];
    const DOMAINES_SSOT = ["roadmap", "rules"];

    const CLIENT_ID = "gemini_web";
    const REDIRECT_URI = "https://gemini.google.com/?nokido_pair_oauth=callback";

    // ── VALIDATION DE TRANSPORT (HTTPS STRICT) ────────────────────────────────
    function validerHttps(url) {
        if (!url || typeof url !== 'string') {
            throw new Error("URL manquante ou invalide");
        }
        const nettoye = url.trim();
        if (!nettoye.startsWith("https://")) {
            throw new Error("Seul le protocole https:// est autorisé pour les échanges avec le connecteur des pairs");
        }
        return nettoye.replace(/\/+$/, "");
    }

    // ── GESTIONNAIRE D'ÉTAT OAUTH (STOCKAGE GM SÉPARÉ DE LA PAGE) ─────────────
    function recupererConfiguration() {
        return {
            publicUrl: GM_getValue("nokido_public_url", ""),
            accessToken: GM_getValue("nokido_access_token", ""),
            refreshToken: GM_getValue("nokido_refresh_token", ""),
            tokenExpiry: GM_getValue("nokido_token_exp", 0)
        };
    }

    function sauvegarderUrlPublique(url) {
        const valide = validerHttps(url);
        GM_setValue("nokido_public_url", valide);
        return valide;
    }

    function reinitialiserSession() {
        GM_deleteValue("nokido_access_token");
        GM_deleteValue("nokido_refresh_token");
        GM_deleteValue("nokido_token_exp");
        GM_deleteValue("nokido_oauth_state");
        GM_deleteValue("nokido_oauth_verifier");
    }

    // ── VÉRIFICATION D'ORIGINE À L'EXÉCUTION (CONFINEMENT TRANSPORT STRICT) ───
    function verifierOrigineCible(urlCible) {
        const config = recupererConfiguration();
        if (!config.publicUrl) {
            journaliser("Refus de requête : aucune URL publique enregistrée pour vérifier l'origine.", true);
            return false;
        }
        let urlPubliqueObj, urlCibleObj;
        try {
            urlPubliqueObj = new URL(config.publicUrl);
        } catch (e) {
            journaliser("Refus de requête : URL publique configurée invalide (" + config.publicUrl + ") : " + e.message, true);
            return false;
        }
        try {
            urlCibleObj = new URL(urlCible);
        } catch (e) {
            journaliser("Refus de requête : URL cible invalide (" + urlCible + ") : " + e.message, true);
            return false;
        }

        // Vérification stricte : même schéma https, même hôte, même port
        if (urlCibleObj.protocol !== "https:" || urlPubliqueObj.protocol !== "https:") {
            journaliser("Refus de requête : protocole https: obligatoire (" + urlCibleObj.protocol + "). Aucune requête transmise.", true);
            return false;
        }
        if (urlCibleObj.origin !== urlPubliqueObj.origin) {
            journaliser("Refus de requête : l'origine visée (" + urlCibleObj.origin + ") diffère de l'origine publique enregistrée (" + urlPubliqueObj.origin + "). Aucune requête transmise.", true);
            return false;
        }
        return true;
    }

    function executerRequeteHttpSecurisee(options) {
        if (!options || !options.url) {
            journaliser("Refus de requête : options ou URL manquante.", true);
            return null;
        }
        // Contrôle strict à l'exécution : toute requête GM_xmlhttpRequest doit viser l'ORIGINE exacte de l'URL publique sauvegardée
        if (!verifierOrigineCible(options.url)) {
            if (typeof options.onerror === "function") {
                options.onerror({ error: "Origine cible refusée" });
            }
            return null;
        }
        return GM_xmlhttpRequest(options);
    }

    // ── CRYPTOGRAPHIE PKCE SOUVERAINE ─────────────────────────────────────────
    function fabriquerChaineAleatoire(taille) {
        const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~";
        const octets = new Uint8Array(taille || 64);
        crypto.getRandomValues(octets);
        let sortie = "";
        for (let i = 0; i < octets.length; i++) {
            sortie += alphabet[octets[i] % alphabet.length];
        }
        return sortie;
    }

    async function fabriquerChallengeSha256(chaine) {
        const encodeur = new TextEncoder();
        const donnees = encodeur.encode(chaine);
        const empreinte = await crypto.subtle.digest("SHA-256", donnees);
        const octets = new Uint8Array(empreinte);
        let binaire = "";
        for (let i = 0; i < octets.byteLength; i++) {
            binaire += String.fromCharCode(octets[i]);
        }
        return btoa(binaire)
            .replace(/\+/g, "-")
            .replace(/\//g, "_")
            .replace(/=+$/, "");
    }

    // ── FLUX D'AUTHENTIFICATION OAUTH 2.1 ─────────────────────────────────────
    async function initierOAuth() {
        const config = recupererConfiguration();
        if (!config.publicUrl) {
            journaliser("Veuillez d'abord enregistrer une URL publique valide (https://...)", true);
            return;
        }
        const base = validerHttps(config.publicUrl);
        const verificateur = fabriquerChaineAleatoire(64);
        const challenge = await fabriquerChallengeSha256(verificateur);
        const etat = fabriquerChaineAleatoire(32);

        GM_setValue("nokido_oauth_verifier", verificateur);
        GM_setValue("nokido_oauth_state", etat);

        const urlAutorisation = base + "/authorize?response_type=code" +
            "&client_id=" + encodeURIComponent(CLIENT_ID) +
            "&redirect_uri=" + encodeURIComponent(REDIRECT_URI) +
            "&scope=" + encodeURIComponent("pair:collaborer") +
            "&code_challenge=" + encodeURIComponent(challenge) +
            "&code_challenge_method=S256" +
            "&state=" + encodeURIComponent(etat);

        journaliser("Ouverture du formulaire de consentement pour validation du code d'appariement...");
        window.open(urlAutorisation, "_blank");
    }

    async function traiterRetourOAuthSiPresent() {
        if (!window.location.search) return;
        const parametres = new URLSearchParams(window.location.search);
        if (parametres.get("nokido_pair_oauth") !== "callback") return;

        function nettoyerSecretsEchange() {
            GM_deleteValue("nokido_oauth_state");
            GM_deleteValue("nokido_oauth_verifier");
        }

        const code = parametres.get("code");
        const etat = parametres.get("state");
        const etatAttendu = GM_getValue("nokido_oauth_state", "");
        const verificateur = GM_getValue("nokido_oauth_verifier", "");
        const config = recupererConfiguration();

        if (!etat || etat !== etatAttendu) {
            journaliser("Refus OAuth : paramètre 'state' absent ou non concordant.", true);
            nettoyerSecretsEchange();
            return;
        }
        if (!code || !verificateur || !config.publicUrl) {
            journaliser("Refus OAuth : paramètres de vérification incomplets.", true);
            nettoyerSecretsEchange();
            return;
        }

        const base = validerHttps(config.publicUrl);
        const urlToken = base + "/token";
        if (!verifierOrigineCible(urlToken)) {
            nettoyerSecretsEchange();
            return;
        }

        const corpsEchange = new URLSearchParams({
            grant_type: "authorization_code",
            client_id: CLIENT_ID,
            code: code,
            redirect_uri: REDIRECT_URI,
            code_verifier: verificateur
        });

        journaliser("Échange du code d'autorisation contre un jeton d'accès...");
        executerRequeteHttpSecurisee({
            method: "POST",
            url: urlToken,
            headers: {
                "Content-Type": "application/x-www-form-urlencoded"
            },
            data: corpsEchange.toString(),
            onload: function(reponse) {
                try {
                    const resultat = JSON.parse(reponse.responseText);
                    if (resultat.access_token) {
                        GM_setValue("nokido_access_token", resultat.access_token);
                        if (resultat.refresh_token) {
                            GM_setValue("nokido_refresh_token", resultat.refresh_token);
                        }
                        const expireDans = Number(resultat.expires_in) || 3600;
                        GM_setValue("nokido_token_exp", Date.now() + (expireDans * 1000));

                        window.history.replaceState({}, document.title, window.location.pathname);
                        journaliser("✅ Authentification OAuth 2.1 réussie ! Jeton enregistré en stockage sécurisé.");
                        actualiserVueEtat();
                    } else {
                        journaliser("Erreur retour jeton : " + (resultat.error_description || resultat.error || reponse.responseText), true);
                    }
                } catch (err) {
                    journaliser("Erreur de décodage réponse OAuth : " + err.message, true);
                } finally {
                    nettoyerSecretsEchange();
                }
            },
            onerror: function() {
                nettoyerSecretsEchange();
                journaliser("Erreur réseau lors de la requête vers " + urlToken, true);
            }
        });
    }

    async function assurerJetonValide() {
        const config = recupererConfiguration();
        if (!config.accessToken) {
            throw new Error("Aucun jeton d'accès présent. Veuillez lancer l'authentification OAuth.");
        }
        const delta = config.tokenExpiry - Date.now();
        if (delta > 60000) {
            return config.accessToken;
        }

        if (!config.refreshToken || !config.publicUrl) {
            throw new Error("Jeton expiré et aucun moyen de renouvellement disponible.");
        }

        const base = validerHttps(config.publicUrl);
        const urlToken = base + "/token";
        return new Promise(function(res, rej) {
            if (!verifierOrigineCible(urlToken)) {
                rej(new Error("Origine non autorisée pour le renouvellement"));
                return;
            }
            const corpsRenouvellement = new URLSearchParams({
                grant_type: "refresh_token",
                client_id: CLIENT_ID,
                refresh_token: config.refreshToken
            });

            executerRequeteHttpSecurisee({
                method: "POST",
                url: urlToken,
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                data: corpsRenouvellement.toString(),
                onload: function(rep) {
                    try {
                        const parsed = JSON.parse(rep.responseText);
                        if (parsed.access_token) {
                            GM_setValue("nokido_access_token", parsed.access_token);
                            if (parsed.refresh_token) {
                                GM_setValue("nokido_refresh_token", parsed.refresh_token);
                            }
                            const exp = Number(parsed.expires_in) || 3600;
                            GM_setValue("nokido_token_exp", Date.now() + (exp * 1000));
                            res(parsed.access_token);
                        } else {
                            rej(new Error("Échec du renouvellement de jeton : " + rep.responseText));
                        }
                    } catch (e) {
                        rej(new Error("Réponse de renouvellement illisible : " + e.message));
                    }
                },
                onerror: function() {
                    rej(new Error("Échec réseau lors du renouvellement du jeton."));
                }
            });
        });
    }

    // ── APPELS MCP SUR LA SURFACE DU CONNECTEUR DES PAIRS ─────────────────────
    async function executerOutilMcp(nomOutil, argumentsOutil) {
        if (!OUTILS_AUTORISES.includes(nomOutil)) {
            throw new Error("Outil non autorisé sur le connecteur pair : " + nomOutil);
        }
        const config = recupererConfiguration();
        const base = validerHttps(config.publicUrl);
        const jeton = await assurerJetonValide();
        const urlMcp = base + "/mcp";

        const chargeJsonRpc = {
            jsonrpc: "2.0",
            id: Date.now(),
            method: "tools/call",
            params: {
                name: nomOutil,
                arguments: argumentsOutil || {}
            }
        };

        return new Promise(function(resolve, reject) {
            if (!verifierOrigineCible(urlMcp)) {
                reject(new Error("Origine non autorisée pour l'appel MCP"));
                return;
            }
            executerRequeteHttpSecurisee({
                method: "POST",
                url: urlMcp,
                headers: {
                    "Authorization": "Bearer " + jeton,
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"
                },
                data: JSON.stringify(chargeJsonRpc),
                onload: function(reponse) {
                    if (reponse.status === 401) {
                        reject(new Error("401 Non autorisé (jeton refusé ou révoqué)."));
                        return;
                    }
                    if (reponse.status < 200 || reponse.status >= 300) {
                        reject(new Error("Erreur HTTP " + reponse.status + " : " + reponse.statusText));
                        return;
                    }
                    try {
                        const corps = JSON.parse(reponse.responseText);
                        if (corps.error) {
                            reject(new Error(corps.error.message || JSON.stringify(corps.error)));
                            return;
                        }
                        resolve(corps.result || corps);
                    } catch (err) {
                        reject(new Error("Format de réponse MCP non conforme JSON-RPC : " + err.message));
                    }
                },
                onerror: function() {
                    reject(new Error("Erreur de transport réseau vers " + urlMcp));
                }
            });
        });
    }

    // ── INTERACTION AVEC L'INTERFACE WEB DE GEMINI ────────────────────────────
    function insererTexteDansSaisie(texteAInserer) {
        if (!texteAInserer) return false;
        const selecteurs = [
            'rich-textarea div[contenteditable="true"]',
            'div.ql-editor[contenteditable="true"]',
            'div[contenteditable="true"]',
            'textarea'
        ];
        let champ = null;
        for (let i = 0; i < selecteurs.length; i++) {
            champ = document.querySelector(selecteurs[i]);
            if (champ) break;
        }

        if (!champ) {
            journaliser("Zone de saisie Gemini introuvable sur la page.", true);
            return false;
        }

        champ.focus();
        if (champ.tagName === 'TEXTAREA' || champ.tagName === 'INPUT') {
            const actuel = champ.value || "";
            champ.value = (actuel ? actuel + "\n\n" : "") + texteAInserer;
            champ.dispatchEvent(new Event("input", { bubbles: true }));
            champ.dispatchEvent(new Event("change", { bubbles: true }));
        } else {
            // Conteneur contenteditable Quill / Angular de Gemini
            const paragraphe = document.createElement("p");
            paragraphe.textContent = texteAInserer;
            champ.appendChild(paragraphe);
            champ.dispatchEvent(new Event("input", { bubbles: true }));
        }
        journaliser("Texte inséré avec succès dans la zone de saisie Gemini.");
        return true;
    }

    function extraireDerniereReponseGemini() {
        const selecteurs = [
            'message-content',
            '.model-response-text',
            '[data-test-id="model-response-text"]',
            'model-response',
            '.response-container',
            'div.markdown'
        ];
        let elements = [];
        for (let i = 0; i < selecteurs.length; i++) {
            const trouves = document.querySelectorAll(selecteurs[i]);
            if (trouves && trouves.length > 0) {
                elements = trouves;
            }
        }
        if (!elements || elements.length === 0) {
            return "";
        }
        const dernier = elements[elements.length - 1];
        return (dernier.innerText || dernier.textContent || "").trim();
    }

    // ── JOURNALISATION ET INTERFACE UTILISATEUR DU PANNEAU ─────────────────────
    let conteneurLogs = null;
    let indicateurStatut = null;

    function journaliser(message, estErreur) {
        const dateStr = new Date().toLocaleTimeString();
        const ligne = `[${dateStr}] ${message}`;
        if (conteneurLogs) {
            const elem = document.createElement("div");
            elem.style.margin = "3px 0";
            elem.style.color = estErreur ? "#ff8080" : "#a6d2ff";
            elem.textContent = ligne;
            conteneurLogs.appendChild(elem);
            conteneurLogs.scrollTop = conteneurLogs.scrollHeight;
        }
    }

    function actualiserVueEtat() {
        const config = recupererConfiguration();
        if (!indicateurStatut) return;
        if (!config.accessToken) {
            indicateurStatut.style.backgroundColor = "#ff5555";
            indicateurStatut.title = "Non connecté (aucun jeton)";
        } else if (config.tokenExpiry && Date.now() > config.tokenExpiry) {
            indicateurStatut.style.backgroundColor = "#ffcc00";
            indicateurStatut.title = "Jeton expiré (renouvellement requis)";
        } else {
            indicateurStatut.style.backgroundColor = "#55ff55";
            indicateurStatut.title = "Connecté via OAuth (jeton actif)";
        }
    }

    // ── CONSTRUCTION DE L'INTERFACE LATÉRALE ──────────────────────────────────
    function construirePanneau() {
        if (document.getElementById("nokido-pair-panel")) return;

        // Bouton flottant de bascule
        const boutonBascule = document.createElement("button");
        boutonBascule.id = "nokido-pair-toggle";
        boutonBascule.innerHTML = "🪐 Nokido Pair";
        boutonBascule.style.position = "fixed";
        boutonBascule.style.bottom = "20px";
        boutonBascule.style.right = "20px";
        boutonBascule.style.zIndex = "999999";
        boutonBascule.style.padding = "10px 16px";
        boutonBascule.style.backgroundColor = "#1a1f2c";
        boutonBascule.style.color = "#8ab4f8";
        boutonBascule.style.border = "1px solid #4a5568";
        boutonBascule.style.borderRadius = "24px";
        boutonBascule.style.cursor = "pointer";
        boutonBascule.style.boxShadow = "0 4px 12px rgba(0,0,0,0.5)";
        boutonBascule.style.fontWeight = "bold";
        boutonBascule.style.fontSize = "13px";

        // Panneau principal
        const panneau = document.createElement("div");
        panneau.id = "nokido-pair-panel";
        panneau.style.position = "fixed";
        panneau.style.top = "60px";
        panneau.style.right = "20px";
        panneau.style.width = "380px";
        panneau.style.maxHeight = "calc(100vh - 100px)";
        panneau.style.backgroundColor = "#121722";
        panneau.style.color = "#e2e8f0";
        panneau.style.border = "1px solid #2d3748";
        panneau.style.borderRadius = "12px";
        panneau.style.boxShadow = "0 8px 32px rgba(0,0,0,0.7)";
        panneau.style.zIndex = "999998";
        panneau.style.display = "none";
        panneau.style.flexDirection = "column";
        panneau.style.fontFamily = "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
        panneau.style.fontSize = "12px";
        panneau.style.overflow = "hidden";

        // En-tête
        const entete = document.createElement("div");
        entete.style.padding = "12px 16px";
        entete.style.backgroundColor = "#1a202c";
        entete.style.borderBottom = "1px solid #2d3748";
        entete.style.display = "flex";
        entete.style.alignItems = "center";
        entete.style.justifyContent = "space-between";

        const titreBloc = document.createElement("div");
        titreBloc.style.display = "flex";
        titreBloc.style.alignItems = "center";
        titreBloc.style.gap = "8px";

        indicateurStatut = document.createElement("span");
        indicateurStatut.style.width = "10px";
        indicateurStatut.style.height = "10px";
        indicateurStatut.style.borderRadius = "50%";
        indicateurStatut.style.display = "inline-block";
        indicateurStatut.style.backgroundColor = "#ff5555";

        const titreTexte = document.createElement("strong");
        titreTexte.textContent = "Nokido Pair Connector";
        titreTexte.style.color = "#8ab4f8";

        titreBloc.appendChild(indicateurStatut);
        titreBloc.appendChild(titreTexte);

        const boutonFermer = document.createElement("button");
        boutonFermer.textContent = "✕";
        boutonFermer.style.background = "none";
        boutonFermer.style.border = "none";
        boutonFermer.style.color = "#a0aec0";
        boutonFermer.style.cursor = "pointer";
        boutonFermer.style.fontSize = "16px";
        boutonFermer.onclick = function() {
            panneau.style.display = "none";
        };

        entete.appendChild(titreBloc);
        entete.appendChild(boutonFermer);
        panneau.appendChild(entete);

        // Conteneur de défilement pour les sections
        const corps = document.createElement("div");
        corps.style.padding = "14px";
        corps.style.overflowY = "auto";
        corps.style.flex = "1";
        corps.style.display = "flex";
        corps.style.flexDirection = "column";
        corps.style.gap = "14px";

        // Section 1 : Configuration et Connexion OAuth
        const sectionConfig = document.createElement("div");
        sectionConfig.style.backgroundColor = "#1a202c";
        sectionConfig.style.padding = "10px";
        sectionConfig.style.borderRadius = "8px";
        sectionConfig.style.border = "1px solid #2d3748";

        const titreConfig = document.createElement("div");
        titreConfig.innerHTML = "<strong>1. Connexion & URL Publique</strong>";
        titreConfig.style.marginBottom = "8px";
        titreConfig.style.color = "#cbd5e0";

        const champUrl = document.createElement("input");
        champUrl.type = "text";
        champUrl.placeholder = "https://nokido-pair.mon-domaine.com";
        champUrl.value = GM_getValue("nokido_public_url", "");
        champUrl.style.width = "100%";
        champUrl.style.boxSizing = "border-box";
        champUrl.style.padding = "6px 8px";
        champUrl.style.backgroundColor = "#0d1117";
        champUrl.style.color = "#e2e8f0";
        champUrl.style.border = "1px solid #4a5568";
        champUrl.style.borderRadius = "4px";
        champUrl.style.marginBottom = "8px";

        const ligneBoutonsConfig = document.createElement("div");
        ligneBoutonsConfig.style.display = "flex";
        ligneBoutonsConfig.style.gap = "6px";

        const btnSaveUrl = document.createElement("button");
        btnSaveUrl.textContent = "Sauvegarder URL";
        btnSaveUrl.style.flex = "1";
        btnSaveUrl.style.padding = "6px";
        btnSaveUrl.style.backgroundColor = "#2d3748";
        btnSaveUrl.style.color = "#e2e8f0";
        btnSaveUrl.style.border = "none";
        btnSaveUrl.style.borderRadius = "4px";
        btnSaveUrl.style.cursor = "pointer";
        btnSaveUrl.onclick = function() {
            try {
                const u = sauvegarderUrlPublique(champUrl.value);
                journaliser("URL enregistrée : " + u);
            } catch (e) {
                journaliser(e.message, true);
            }
        };

        const btnAuth = document.createElement("button");
        btnAuth.textContent = "OAuth (Appariement)";
        btnAuth.style.flex = "1.3";
        btnAuth.style.padding = "6px";
        btnAuth.style.backgroundColor = "#2b6cb0";
        btnAuth.style.color = "#ffffff";
        btnAuth.style.border = "none";
        btnAuth.style.borderRadius = "4px";
        btnAuth.style.cursor = "pointer";
        btnAuth.onclick = initierOAuth;

        const btnDeconnexion = document.createElement("button");
        btnDeconnexion.textContent = "Déconnexion";
        btnDeconnexion.style.flex = "1";
        btnDeconnexion.style.padding = "6px";
        btnDeconnexion.style.backgroundColor = "#742a2a";
        btnDeconnexion.style.color = "#ffffff";
        btnDeconnexion.style.border = "none";
        btnDeconnexion.style.borderRadius = "4px";
        btnDeconnexion.style.cursor = "pointer";
        btnDeconnexion.onclick = function() {
            reinitialiserSession();
            actualiserVueEtat();
            journaliser("Session locale réinitialisée.");
        };

        ligneBoutonsConfig.appendChild(btnSaveUrl);
        ligneBoutonsConfig.appendChild(btnAuth);
        ligneBoutonsConfig.appendChild(btnDeconnexion);

        sectionConfig.appendChild(titreConfig);
        sectionConfig.appendChild(champUrl);
        sectionConfig.appendChild(ligneBoutonsConfig);
        corps.appendChild(sectionConfig);

        // Section 2 : Outils de Lecture (Injection dans la zone de saisie)
        const sectionLecture = document.createElement("div");
        sectionLecture.style.backgroundColor = "#1a202c";
        sectionLecture.style.padding = "10px";
        sectionLecture.style.borderRadius = "8px";
        sectionLecture.style.border = "1px solid #2d3748";

        const titreLecture = document.createElement("div");
        titreLecture.innerHTML = "<strong>2. Outils de Lecture (Injecter au prompt)</strong>";
        titreLecture.style.marginBottom = "8px";
        titreLecture.style.color = "#cbd5e0";

        const grilleLecture = document.createElement("div");
        grilleLecture.style.display = "grid";
        grilleLecture.style.gridTemplateColumns = "1fr 1fr";
        grilleLecture.style.gap = "6px";

        function creerBoutonLecture(label, outil, args) {
            const b = document.createElement("button");
            b.textContent = label;
            b.style.padding = "6px 8px";
            b.style.backgroundColor = "#2d3748";
            b.style.color = "#e2e8f0";
            b.style.border = "1px solid #4a5568";
            b.style.borderRadius = "4px";
            b.style.cursor = "pointer";
            b.onclick = async function() {
                try {
                    journaliser(`Appel lecture '${outil}' en cours...`);
                    const res = await executerOutilMcp(outil, args);
                    const rendu = res.contenu || (res.content && res.content[0] && res.content[0].text) || JSON.stringify(res, null, 2);
                    const blocTexte = `[NOKIDO LECTURE : ${outil}]\n${rendu}`;
                    insererTexteDansSaisie(blocTexte);
                } catch (e) {
                    journaliser("Échec " + outil + " : " + e.message, true);
                }
            };
            return b;
        }

        grilleLecture.appendChild(creerBoutonLecture("État Corps", "etat_corps", {}));
        grilleLecture.appendChild(creerBoutonLecture("SSoT Roadmap", "point_ssot", { domaine: "roadmap" }));
        grilleLecture.appendChild(creerBoutonLecture("SSoT Rules", "point_ssot", { domaine: "rules" }));
        grilleLecture.appendChild(creerBoutonLecture("Dernière Capsule", "derniere_capsule", {}));
        grilleLecture.appendChild(creerBoutonLecture("Commits Récents", "journal_commits", { n: 10 }));

        // Recherche RAG personnalisée
        const ligneRag = document.createElement("div");
        ligneRag.style.marginTop = "8px";
        ligneRag.style.display = "flex";
        ligneRag.style.gap = "6px";

        const champRag = document.createElement("input");
        champRag.type = "text";
        champRag.placeholder = "Mots-clés RAG public...";
        champRag.style.flex = "1";
        champRag.style.padding = "5px 8px";
        champRag.style.backgroundColor = "#0d1117";
        champRag.style.color = "#e2e8f0";
        champRag.style.border = "1px solid #4a5568";
        champRag.style.borderRadius = "4px";

        const btnRag = document.createElement("button");
        btnRag.textContent = "Recherche RAG";
        btnRag.style.padding = "5px 10px";
        btnRag.style.backgroundColor = "#2b6cb0";
        btnRag.style.color = "#ffffff";
        btnRag.style.border = "none";
        btnRag.style.borderRadius = "4px";
        btnRag.style.cursor = "pointer";
        btnRag.onclick = async function() {
            const q = champRag.value.trim();
            if (!q) return;
            try {
                journaliser(`Recherche RAG pour '${q}'...`);
                const res = await executerOutilMcp("recherche_rag", { requete: q, limite: 5 });
                const rendu = res.contenu || (res.content && res.content[0] && res.content[0].text) || JSON.stringify(res, null, 2);
                insererTexteDansSaisie(`[NOKIDO RAG : ${q}]\n${rendu}`);
            } catch (e) {
                journaliser("Échec RAG : " + e.message, true);
            }
        };

        ligneRag.appendChild(champRag);
        ligneRag.appendChild(btnRag);

        sectionLecture.appendChild(titreLecture);
        sectionLecture.appendChild(grilleLecture);
        sectionLecture.appendChild(ligneRag);
        corps.appendChild(sectionLecture);

        // Section 3 : Quarantaine et Collaboration Sécurisée (Dépôts)
        const sectionQuarantaine = document.createElement("div");
        sectionQuarantaine.style.backgroundColor = "#1a202c";
        sectionQuarantaine.style.padding = "10px";
        sectionQuarantaine.style.borderRadius = "8px";
        sectionQuarantaine.style.border = "1px solid #2d3748";

        const titreQuarantaine = document.createElement("div");
        titreQuarantaine.innerHTML = "<strong>3. Collaboration en Quarantaine (gemini_web)</strong>";
        titreQuarantaine.style.marginBottom = "6px";
        titreQuarantaine.style.color = "#cbd5e0";

        const noteSecurite = document.createElement("div");
        noteSecurite.style.fontSize = "11px";
        noteSecurite.style.color = "#9ae6b4";
        noteSecurite.style.marginBottom = "8px";
        noteSecurite.textContent = "🔒 Dépôt en boîte OWNER_APPROBATION avec marquage EXTERNE_NON_VERIFIEE. Jamais d'exécution directe.";

        const zoneTexteGemini = document.createElement("textarea");
        zoneTexteGemini.placeholder = "Texte capturé de la réponse Gemini ou proposition manuelle...";
        zoneTexteGemini.rows = 4;
        zoneTexteGemini.style.width = "100%";
        zoneTexteGemini.style.boxSizing = "border-box";
        zoneTexteGemini.style.padding = "6px 8px";
        zoneTexteGemini.style.backgroundColor = "#0d1117";
        zoneTexteGemini.style.color = "#e2e8f0";
        zoneTexteGemini.style.border = "1px solid #4a5568";
        zoneTexteGemini.style.borderRadius = "4px";
        zoneTexteGemini.style.marginBottom = "6px";

        const btnCapturer = document.createElement("button");
        btnCapturer.textContent = "📋 Capturer la dernière réponse de Gemini";
        btnCapturer.style.width = "100%";
        btnCapturer.style.padding = "6px";
        btnCapturer.style.backgroundColor = "#4a5568";
        btnCapturer.style.color = "#e2e8f0";
        btnCapturer.style.border = "none";
        btnCapturer.style.borderRadius = "4px";
        btnCapturer.style.cursor = "pointer";
        btnCapturer.style.marginBottom = "8px";
        btnCapturer.onclick = function() {
            const t = extraireDerniereReponseGemini();
            if (t) {
                zoneTexteGemini.value = t;
                journaliser("Dernière réponse capturée (" + t.length + " caractères).");
            } else {
                journaliser("Aucune réponse de Gemini détectée dans le DOM.", true);
            }
        };

        // Sous-bloc Proposer Fait SSoT
        const ligneFait = document.createElement("div");
        ligneFait.style.display = "flex";
        ligneFait.style.gap = "6px";
        ligneFait.style.marginBottom = "6px";

        const selDomaineFait = document.createElement("select");
        selDomaineFait.style.backgroundColor = "#0d1117";
        selDomaineFait.style.color = "#e2e8f0";
        selDomaineFait.style.border = "1px solid #4a5568";
        selDomaineFait.style.borderRadius = "4px";
        selDomaineFait.style.padding = "4px";
        DOMAINES_SSOT.forEach(function(d) {
            const opt = document.createElement("option");
            opt.value = d;
            opt.textContent = "SSoT " + d;
            selDomaineFait.appendChild(opt);
        });

        const btnProposerFait = document.createElement("button");
        btnProposerFait.textContent = "Proposer Fait (Quarantaine)";
        btnProposerFait.style.flex = "1";
        btnProposerFait.style.padding = "6px";
        btnProposerFait.style.backgroundColor = "#2c5282";
        btnProposerFait.style.color = "#ffffff";
        btnProposerFait.style.border = "none";
        btnProposerFait.style.borderRadius = "4px";
        btnProposerFait.style.cursor = "pointer";
        btnProposerFait.onclick = async function() {
            const t = zoneTexteGemini.value.trim();
            if (!t) {
                journaliser("Texte requis pour proposer un fait.", true);
                return;
            }
            try {
                journaliser("Dépôt 'proposer_fait' sous provenance " + CLIENT_ID + "...");
                const res = await executerOutilMcp("proposer_fait", {
                    texte: t,
                    domaine: selDomaineFait.value
                });
                const rendu = res.contenu || (res.content && res.content[0] && res.content[0].text) || JSON.stringify(res);
                journaliser("Dépôt enregistré : " + rendu);
            } catch (e) {
                journaliser("Échec proposer_fait : " + e.message, true);
            }
        };

        ligneFait.appendChild(selDomaineFait);
        ligneFait.appendChild(btnProposerFait);

        // Sous-bloc Envoyer Message M2M
        const ligneMsg = document.createElement("div");
        ligneMsg.style.display = "flex";
        ligneMsg.style.gap = "6px";
        ligneMsg.style.marginBottom = "6px";

        const selDestinataire = document.createElement("select");
        selDestinataire.style.backgroundColor = "#0d1117";
        selDestinataire.style.color = "#e2e8f0";
        selDestinataire.style.border = "1px solid #4a5568";
        selDestinataire.style.borderRadius = "4px";
        selDestinataire.style.padding = "4px";
        DESTINATAIRES_VALIDES.forEach(function(dest) {
            const opt = document.createElement("option");
            opt.value = dest;
            opt.textContent = dest;
            selDestinataire.appendChild(opt);
        });

        const selIntent = document.createElement("select");
        selIntent.style.backgroundColor = "#0d1117";
        selIntent.style.color = "#e2e8f0";
        selIntent.style.border = "1px solid #4a5568";
        selIntent.style.borderRadius = "4px";
        selIntent.style.padding = "4px";
        INTENTS_VALIDES.forEach(function(it) {
            const opt = document.createElement("option");
            opt.value = it;
            opt.textContent = it;
            selIntent.appendChild(opt);
        });

        const btnEnvoyerMsg = document.createElement("button");
        btnEnvoyerMsg.textContent = "Envoyer M2M";
        btnEnvoyerMsg.style.flex = "1";
        btnEnvoyerMsg.style.padding = "6px";
        btnEnvoyerMsg.style.backgroundColor = "#3182ce";
        btnEnvoyerMsg.style.color = "#ffffff";
        btnEnvoyerMsg.style.border = "none";
        btnEnvoyerMsg.style.borderRadius = "4px";
        btnEnvoyerMsg.style.cursor = "pointer";
        btnEnvoyerMsg.onclick = async function() {
            const t = zoneTexteGemini.value.trim();
            if (!t) {
                journaliser("Texte requis pour envoyer un message.", true);
                return;
            }
            try {
                journaliser("Envoi message vers " + selDestinataire.value + " (" + selIntent.value + ")...");
                const res = await executerOutilMcp("envoyer_message", {
                    intent: selIntent.value,
                    texte: t,
                    destinataire: selDestinataire.value
                });
                const rendu = res.contenu || (res.content && res.content[0] && res.content[0].text) || JSON.stringify(res);
                journaliser("Message consigné en quarantaine : " + rendu);
            } catch (e) {
                journaliser("Échec envoyer_message : " + e.message, true);
            }
        };

        ligneMsg.appendChild(selDestinataire);
        ligneMsg.appendChild(selIntent);
        ligneMsg.appendChild(btnEnvoyerMsg);

        // Sous-bloc Suivre et Réponses
        const ligneSuivi = document.createElement("div");
        ligneSuivi.style.display = "flex";
        ligneSuivi.style.gap = "6px";

        const champIdSuivi = document.createElement("input");
        champIdSuivi.type = "text";
        champIdSuivi.placeholder = "pair_xxxxxxxxxxxxxxxx";
        champIdSuivi.style.flex = "1";
        champIdSuivi.style.padding = "4px 8px";
        champIdSuivi.style.backgroundColor = "#0d1117";
        champIdSuivi.style.color = "#e2e8f0";
        champIdSuivi.style.border = "1px solid #4a5568";
        champIdSuivi.style.borderRadius = "4px";

        const btnSuivre = document.createElement("button");
        btnSuivre.textContent = "Suivre";
        btnSuivre.style.padding = "4px 8px";
        btnSuivre.style.backgroundColor = "#2d3748";
        btnSuivre.style.color = "#e2e8f0";
        btnSuivre.style.border = "1px solid #4a5568";
        btnSuivre.style.borderRadius = "4px";
        btnSuivre.style.cursor = "pointer";
        btnSuivre.onclick = async function() {
            const id = champIdSuivi.value.trim();
            if (!id) return;
            try {
                journaliser("Suivi du dépôt " + id + "...");
                const res = await executerOutilMcp("suivre", { id: id });
                const rendu = res.contenu || (res.content && res.content[0] && res.content[0].text) || JSON.stringify(res);
                journaliser("Accusés : " + rendu);
            } catch (e) {
                journaliser("Échec suivi : " + e.message, true);
            }
        };

        const btnLireReponses = document.createElement("button");
        btnLireReponses.textContent = "Relever Réponses";
        btnLireReponses.style.padding = "4px 8px";
        btnLireReponses.style.backgroundColor = "#2d3748";
        btnLireReponses.style.color = "#e2e8f0";
        btnLireReponses.style.border = "1px solid #4a5568";
        btnLireReponses.style.borderRadius = "4px";
        btnLireReponses.style.cursor = "pointer";
        btnLireReponses.onclick = async function() {
            try {
                journaliser("Relève des réponses pour ce pair...");
                const res = await executerOutilMcp("lire_reponses", {});
                const rendu = res.contenu || (res.content && res.content[0] && res.content[0].text) || JSON.stringify(res);
                journaliser("Réponses reçues : " + rendu);
            } catch (e) {
                journaliser("Échec lire_reponses : " + e.message, true);
            }
        };

        ligneSuivi.appendChild(champIdSuivi);
        ligneSuivi.appendChild(btnSuivre);
        ligneSuivi.appendChild(btnLireReponses);

        sectionQuarantaine.appendChild(titreQuarantaine);
        sectionQuarantaine.appendChild(noteSecurite);
        sectionQuarantaine.appendChild(zoneTexteGemini);
        sectionQuarantaine.appendChild(btnCapturer);
        sectionQuarantaine.appendChild(ligneFait);
        sectionQuarantaine.appendChild(ligneMsg);
        sectionQuarantaine.appendChild(ligneSuivi);
        corps.appendChild(sectionQuarantaine);

        // Section 4 : Console de Journalisation
        const sectionLogs = document.createElement("div");
        sectionLogs.style.backgroundColor = "#0d1117";
        sectionLogs.style.padding = "8px";
        sectionLogs.style.borderRadius = "6px";
        sectionLogs.style.border = "1px solid #2d3748";
        sectionLogs.style.display = "flex";
        sectionLogs.style.flexDirection = "column";

        const titreLogs = document.createElement("div");
        titreLogs.style.display = "flex";
        titreLogs.style.justifyContent = "space-between";
        titreLogs.style.marginBottom = "4px";
        titreLogs.style.color = "#a0aec0";
        titreLogs.innerHTML = "<span>Journal d'activité</span>";

        const btnEffacerLogs = document.createElement("button");
        btnEffacerLogs.textContent = "Effacer";
        btnEffacerLogs.style.background = "none";
        btnEffacerLogs.style.border = "none";
        btnEffacerLogs.style.color = "#718096";
        btnEffacerLogs.style.cursor = "pointer";
        btnEffacerLogs.style.fontSize = "11px";
        btnEffacerLogs.onclick = function() {
            if (conteneurLogs) conteneurLogs.innerHTML = "";
        };
        titreLogs.appendChild(btnEffacerLogs);

        conteneurLogs = document.createElement("div");
        conteneurLogs.style.height = "120px";
        conteneurLogs.style.overflowY = "auto";
        conteneurLogs.style.fontFamily = "monospace";
        conteneurLogs.style.fontSize = "11px";
        conteneurLogs.style.lineHeight = "1.4";

        sectionLogs.appendChild(titreLogs);
        sectionLogs.appendChild(conteneurLogs);
        corps.appendChild(sectionLogs);

        panneau.appendChild(corps);

        // Assemblage final sur le DOM
        document.body.appendChild(boutonBascule);
        document.body.appendChild(panneau);

        boutonBascule.onclick = function() {
            panneau.style.display = (panneau.style.display === "none") ? "flex" : "none";
            actualiserVueEtat();
        };

        actualiserVueEtat();
    }

    // ── INITIALISATION AU CHARGEMENT DE LA PAGE ───────────────────────────────
    function init() {
        traiterRetourOAuthSiPresent();
        construirePanneau();
        actualiserVueEtat();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
