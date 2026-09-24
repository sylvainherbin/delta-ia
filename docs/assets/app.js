/* Delta — application du site statique.
 * Lit docs/data/<perimetre>/index.json et les fichiers quotidiens ; aucune dépendance, aucun build.
 * Sécurité : tout texte issu des données passe par textContent ; les liens sont limités à http(s). */
(function () {
  "use strict";

  const PERIMETRES = ["claude", "openai", "actu"];
  const AGENTS = { "claude-code": "Claude Code", codex: "Codex" };
  const PRODUITS = { claude: "Claude", "claude-code": "Claude Code", chatgpt: "ChatGPT", codex: "Codex", actu: "Actu" };
  const IMPACTS = ["fort", "moyen", "faible", "nul"];
  const TYPES = { nouveaute: "nouveauté", amelioration: "amélioration", correction: "correction", changement_rupture: "rupture", depreciation: "dépréciation", actu: "actu" };
  const CERTITUDES = { officiel: "officiel", rapporte: "rapporté", non_confirme: "non confirmé" };
  const ALERTE_HEURES = 36;
  const FENETRE_JOURS = 30; // D38 : Changelogs, Actu et À tester n'affichent que les 30 derniers jours ; au-delà, les Archives
  const CLE_FAITS = "delta.faits";

  const etat = { index: {}, jours: {}, page: "aujourdhui", filtreProduit: "tous", archiveDate: null };
  const main = document.getElementById("contenu");

  /* ---------- utilitaires DOM (jamais innerHTML) ---------- */
  function el(tag, attrs, ...enfants) {
    const n = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = String(v);
      else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : String(v));
    }
    for (const e of enfants) {
      if (e === null || e === undefined || e === false) continue;
      n.append(typeof e === "string" ? document.createTextNode(e) : e);
    }
    return n;
  }
  function lienSur(url, texte) {
    if (typeof url !== "string" || !/^https?:\/\//i.test(url)) return el("span", { text: texte || String(url) });
    return el("a", { href: url, rel: "noopener noreferrer", target: "_blank", text: texte || url });
  }
  function texte(v, defaut) { return typeof v === "string" && v.trim() ? v : (defaut || ""); }
  function dateFr(iso) {
    if (typeof iso !== "string" || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return "date inconnue";
    const [a, m, j] = iso.slice(0, 10).split("-");
    return `${j}/${m}/${a}`;
  }
  function horodatageFr(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "inconnu";
    return d.toLocaleString("fr-CA", { dateStyle: "short", timeStyle: "short" });
  }
  function vider(n) { while (n.firstChild) n.removeChild(n.firstChild); }

  /* ---------- localStorage sous try/catch : le site marche sans ---------- */
  function lireFaits() {
    try { const v = JSON.parse(localStorage.getItem(CLE_FAITS) || "{}"); return v && typeof v === "object" ? v : {}; }
    catch (e) { return {}; }
  }
  function ecrireFait(id, fait) {
    try {
      const faits = lireFaits();
      if (fait) faits[id] = new Date().toISOString(); else delete faits[id];
      localStorage.setItem(CLE_FAITS, JSON.stringify(faits));
    } catch (e) { /* stockage indisponible : la case reste cochée à l'écran seulement */ }
  }

  /* ---------- éléments d'impact nul : masqués par défaut, bascule mémorisée (sous try/catch) ---------- */
  const CLE_NUL = "delta.afficherNul";
  function lireAfficherNul() { try { return localStorage.getItem(CLE_NUL) === "1"; } catch (e) { return false; } }
  function ecrireAfficherNul(v) { try { localStorage.setItem(CLE_NUL, v ? "1" : "0"); } catch (e) { /* sans stockage : pour cette page seulement */ } }
  etat.afficherNul = lireAfficherNul();
  function sansNul(elements) { return etat.afficherNul ? elements : elements.filter((e) => e.impact !== "nul"); }
  function basculeNul(elements) {
    const n = elements.filter((e) => e.impact === "nul").length;
    if (!n) return null;
    const b = el("button", { type: "button", class: "bascule-nul", "aria-pressed": String(etat.afficherNul),
      text: `${etat.afficherNul ? "Masquer" : "Afficher"} les éléments sans impact (${n})` });
    b.addEventListener("click", () => { etat.afficherNul = !etat.afficherNul; ecrireAfficherNul(etat.afficherNul); rendre(); });
    return el("div", { class: "filtres" }, b);
  }

  /* ---------- chargement des données ---------- */
  async function lireJson(chemin) {
    const r = await fetch(chemin, { cache: "no-cache" });
    if (!r.ok) throw new Error(`${chemin} : HTTP ${r.status}`);
    return r.json();
  }
  async function chargerIndex() {
    await Promise.all(PERIMETRES.map(async (p) => {
      try {
        const idx = await lireJson(`data/${p}/index.json`);
        if (!idx || !Array.isArray(idx.jours)) throw new Error("index sans `jours`");
        etat.index[p] = idx;
      } catch (e) { etat.index[p] = { erreur: String(e.message || e), jours: [] }; }
    }));
  }
  async function chargerJour(p, date) {
    const cle = `${p}/${date}`;
    if (etat.jours[cle]) return etat.jours[cle];
    try {
      const q = await lireJson(`data/${p}/${date}.json`);
      etat.jours[cle] = q && Array.isArray(q.elements) ? q : { erreur: "fichier quotidien illisible", elements: [], ecartes: [] };
    } catch (e) { etat.jours[cle] = { erreur: String(e.message || e), elements: [], ecartes: [] }; }
    return etat.jours[cle];
  }
  function datesDe(p) { return (etat.index[p]?.jours || []).map((j) => j.date).filter((d) => typeof d === "string").sort().reverse(); }
  function derniereDate(p) { return datesDe(p)[0] || null; }
  function datesRecentes(p) {
    const limite = new Date(Date.now() - FENETRE_JOURS * 864e5).toISOString().slice(0, 10);
    return datesDe(p).filter((d) => d >= limite);
  }
  function noteFenetre() {
    return el("p", { class: "sous-titre" }, `Passages des ${FENETRE_JOURS} derniers jours. Au-delà, voir les `, el("a", { href: "#archives", text: "Archives" }), ".");
  }
  async function chargerNecessaire() {
    const taches = [];
    for (const p of PERIMETRES) {
      const dates = new Set(datesRecentes(p));
      const derniere = derniereDate(p);
      if (derniere) dates.add(derniere);
      if (etat.archiveDate && datesDe(p).includes(etat.archiveDate)) dates.add(etat.archiveDate);
      for (const d of dates) taches.push(chargerJour(p, d));
    }
    await Promise.all(taches);
  }
  function elementsDe(p, dates) {
    const out = [];
    for (const d of dates) {
      const q = etat.jours[`${p}/${d}`];
      if (!q) continue;
      for (const e of q.elements) if (e && typeof e === "object") out.push({ ...e, _perimetre: p, _jour: d });
    }
    return out;
  }
  const rangImpact = (e) => { const i = IMPACTS.indexOf(e.impact); return i < 0 ? IMPACTS.length : i; };
  const triImpact = (a, b) => rangImpact(a) - rangImpact(b) || String(b.date_publication || "").localeCompare(String(a.date_publication || ""));
  const triChrono = (a, b) => String(b.date_publication || b._jour || "").localeCompare(String(a.date_publication || a._jour || ""));

  /* ---------- en-tête : dernier passage par agent, alerte au-delà de 36 h (D36) ---------- */
  function rendreEtatAgents() {
    const zone = document.getElementById("etat-agents");
    vider(zone);
    const parAgent = {};
    for (const p of PERIMETRES) {
      const idx = etat.index[p];
      if (!idx || !idx.agent) continue;
      const t = new Date(idx.maj_le || "");
      if (Number.isNaN(t.getTime())) continue;
      if (!parAgent[idx.agent] || t > parAgent[idx.agent]) parAgent[idx.agent] = t;
    }
    const alertes = [];
    for (const agent of Object.keys(AGENTS)) {
      const t = parAgent[agent];
      const heures = t ? (Date.now() - t.getTime()) / 36e5 : Infinity;
      // D36, D53 : vert jusqu'à 24 h, orange de 24 à 36 h, rouge au-delà de 36 h
      const couleur = heures > ALERTE_HEURES ? "rouge" : heures > 24 ? "orange" : "vert";
      const quand = t ? horodatageFr(t.toISOString()) : "aucun passage";
      zone.append(el("span", { class: `agent ${couleur}`, title: t ? `Dernier passage il y a ${Math.floor(heures)} h` : "Aucun passage" },
        el("span", { class: "point", "aria-hidden": "true" }), el("strong", { text: AGENTS[agent] }), ` ${quand}`,
        couleur === "rouge" ? el("span", { class: "saut", text: " (en retard)" }) : null));
      if (couleur === "rouge") alertes.push(t ? `${AGENTS[agent]} n'a pas tourné depuis ${Math.floor(heures)} h` : `${AGENTS[agent]} n'a jamais tourné`);
    }
    return alertes;
  }

  /* ---------- Tes outils : versions installées (D54 à D56) ---------- */
  const STATUTS_VERSION = { a_jour: "à jour", en_retard: "en retard", inconnu: "inconnu" };
  async function chargerVersions() {
    if (etat.versions !== undefined) return;
    try {
      const v = await lireJson("data/versions.json");
      etat.versions = Array.isArray(v) ? v : null;
    } catch (e) { etat.versions = null; }
  }
  function blocOutils() {
    const lignes = etat.versions;
    if (!Array.isArray(lignes) || !lignes.length) return null;
    const corps = el("tbody");
    for (const l of lignes) {
      if (!l || typeof l !== "object") continue;
      const statut = STATUTS_VERSION[l.statut] ? l.statut : "inconnu";
      const note = [texte(l.raison), texte(l.note)].filter(Boolean).join(" ");
      // Codex CLI est livré avec l'app de bureau : il se met à jour avec elle
      const conseil = l.outil === "Codex CLI" && statut === "en_retard" ? el("span", { class: "conseil", text: "→ mettre à jour ChatGPT Desktop" }) : null;
      corps.append(el("tr", { class: note ? "avec-note" : null },
        el("td", { text: texte(l.outil, "?") }),
        el("td", { class: "v", text: l.version ? String(l.version) : "introuvable" }),
        el("td", { class: "v col-derniere", text: l.derniere_publiee ? String(l.derniere_publiee) : "—" }),
        el("td", null, el("span", { class: `statut ${statut}` }, el("span", { class: "point", "aria-hidden": "true" }), STATUTS_VERSION[statut]), conseil)));
      if (note) corps.append(el("tr", { class: "ligne-note" }, el("td", { colspan: "4", text: note })));
    }
    const date = lignes.map((l) => l && l.detectee_le).filter(Boolean).sort().pop();
    return el("section", { class: "outils", "aria-label": "Tes outils" },
      el("h3", { text: "TES OUTILS" }),
      el("table", null,
        el("thead", null, el("tr", null, el("th", { text: "Outil" }), el("th", { text: "Installée" }),
          el("th", { class: "col-derniere", text: "Dernière publiée" }), el("th", { text: "Statut" }))),
        corps),
      el("p", { class: "pied-outils", text: `Relevé le ${date ? horodatageFr(date) : "?"} sur la machine de Sylvain. « Dernière publiée » vient des sources suivies par Delta ; sans source, le statut reste inconnu.` }));
  }

  /* ---------- rendu d'un élément ---------- */
  function badge(classe, libelle) { return el("span", { class: `badge ${classe}`, text: libelle }); }
  function carte(e, options) {
    options = options || {};
    const faits = lireFaits();
    const c = el("li", { class: `carte impact-${IMPACTS.includes(e.impact) ? e.impact : "nul"}` + (faits[e.id] ? " fait" : "") });
    const badges = el("div", { class: "badges" },
      badge(`impact ${IMPACTS.includes(e.impact) ? e.impact : "nul"}`, `impact ${e.impact || "?"}`),
      badge(`certitude ${e.certitude || ""}`, CERTITUDES[e.certitude] || String(e.certitude || "?")),
      badge("produit", PRODUITS[e.produit] || String(e.produit || "?")),
      e.type ? badge("type", TYPES[e.type] || String(e.type)) : null,
      e.revision === true ? badge("revise", "révisé") : null);
    c.append(badges);
    const titre = texte(e.titre, "(sans titre)") + (e.version ? ` ${e.version}` : "");
    c.append(el(options.niveau === 4 ? "h4" : "h3", { text: titre }));
    c.append(el("div", { class: "meta", text: `${dateFr(e.date_publication)} · passage du ${dateFr(e._jour)}` }));
    if (texte(e.resume)) c.append(el("p", { class: "resume", text: e.resume }));
    if (texte(e.pour_toi)) c.append(el("div", { class: "pour-toi" }, el("strong", { text: "Pour toi" }), el("p", { text: e.pour_toi })));
    if (e.action && typeof e.action === "object") {
      const a = el("div", { class: "action" }, el("strong", { text: "Action" }),
        e.action.effort ? el("span", { class: "effort", text: `effort : ${e.action.effort}` }) : null,
        texte(e.action.description) ? el("p", { text: e.action.description }) : null);
      if (Array.isArray(e.action.etapes) && e.action.etapes.length) {
        a.append(el("ol", null, ...e.action.etapes.map((s) => el("li", { text: String(s) }))));
      }
      const id = String(e.id || "");
      const caseFait = el("input", { type: "checkbox" });
      caseFait.checked = Boolean(faits[id]);
      caseFait.addEventListener("change", () => { ecrireFait(id, caseFait.checked); c.classList.toggle("fait", caseFait.checked); });
      a.append(el("label", null, caseFait, "Fait"));
      c.append(a);
    }
    if (Array.isArray(e.projets_concernes) && e.projets_concernes.length) {
      c.append(el("p", { class: "projets", text: `Projets : ${e.projets_concernes.map(String).join(", ")}` }));
    }
    if (Array.isArray(e.sources) && e.sources.length) {
      c.append(el("ul", { class: "sources", "aria-label": "Sources" }, ...e.sources.map((s) =>
        el("li", { class: s && s.officielle === true ? "off" : null, title: s && s.officielle === true ? "source officielle" : "source tierce" },
          lienSur(s && s.url, texte(s && s.libelle, s && s.url))))));
    }
    return c;
  }
  function listeCartes(elements, options) {
    if (!elements.length) return el("p", { class: "vide", text: (options && options.vide) || "Rien à afficher." });
    return el("ul", { class: "liste" + ((options && options.colonnes) ? " deux-colonnes" : "") }, ...elements.map((e) => carte(e, options)));
  }
  function blocSynthese(p, q, date) {
    const idx = etat.index[p] || {};
    const titre = { claude: "Claude et Claude Code", openai: "ChatGPT et Codex", actu: "Actu IA" }[p] || p;
    const b = el("section", { class: "synthese" },
      el("h3", null, titre, el("span", { class: "meta", text: `${AGENTS[idx.agent] || idx.agent || ""} · ${dateFr(date)}` })));
    if (!q || q.erreur) b.append(el("p", { class: "erreur", text: q ? `Données indisponibles : ${q.erreur}` : "Aucun passage." }));
    else {
      b.append(el("p", { text: texte(q.synthese, "Synthèse absente.") }));
      if (Array.isArray(q.sources_en_echec) && q.sources_en_echec.length) {
        b.append(el("p", { class: "echecs", text: "Sources en échec : " + q.sources_en_echec.map((s) => `${s.id}${s.partiel ? " (partiel)" : ""}`).join(", ") }));
      }
    }
    return b;
  }
  function blocEcartes(quotidiens) {
    const tous = [];
    for (const q of quotidiens) if (q && Array.isArray(q.ecartes)) tous.push(...q.ecartes);
    if (!tous.length) return null;
    return el("details", { class: "ecartes" }, el("summary", { text: `${tous.length} nouveauté(s) écartée(s) comme hors sujet` }),
      el("ul", null, ...tous.map((x) => el("li", { text: `${texte(x && x.raison, "sans raison")} — ${texte(x && x.id, "?")}` }))));
  }
  function filtresProduit(elements, surChangement) {
    const presents = [...new Set(elements.map((e) => e.produit).filter((p) => PRODUITS[p]))];
    if (presents.length < 2) return null;
    const f = el("div", { class: "filtres", role: "group", "aria-label": "Filtrer par produit" });
    for (const p of ["tous", ...presents]) {
      const b = el("button", { type: "button", "aria-pressed": String(etat.filtreProduit === p), text: p === "tous" ? "Tous" : PRODUITS[p] });
      b.addEventListener("click", () => { etat.filtreProduit = p; surChangement(); });
      f.append(b);
    }
    return f;
  }
  const filtrer = (elements) => etat.filtreProduit === "tous" ? elements : elements.filter((e) => e.produit === etat.filtreProduit);

  /* ---------- pages ---------- */
  function pageAujourdhui(alertes) {
    const frag = document.createDocumentFragment();
    if (alertes.length) frag.append(el("div", { class: "bandeau-alerte", role: "status", text: alertes.join(" · ") + "." }));
    frag.append(el("h2", { text: "Aujourd'hui" }));
    const outils = blocOutils();
    if (outils) frag.append(outils);
    const quotidiens = [];
    let elements = [];
    for (const p of PERIMETRES) {
      const d = derniereDate(p);
      const q = d ? etat.jours[`${p}/${d}`] : null;
      quotidiens.push(q);
      frag.append(blocSynthese(p, q, d));
      if (d) elements = elements.concat(elementsDe(p, [d]));
    }
    elements.sort(triImpact);
    frag.append(el("h2", { text: `Éléments (${sansNul(elements).length})` }));
    const f = filtresProduit(elements, rendre);
    if (f) frag.append(f);
    const bn = basculeNul(filtrer(elements));
    if (bn) frag.append(bn);
    frag.append(listeCartes(sansNul(filtrer(elements)), { vide: "Aucun élément pour ce filtre." }));
    const ec = blocEcartes(quotidiens);
    if (ec) frag.append(ec);
    return frag;
  }
  function pageChangelogs() {
    const frag = document.createDocumentFragment();
    frag.append(el("h2", { text: "Changelogs" }), el("p", { class: "sous-titre", text: "Par produit, du plus récent au plus ancien." }), noteFenetre());
    const tous = elementsDe("claude", datesRecentes("claude")).concat(elementsDe("openai", datesRecentes("openai")));
    const bn = basculeNul(tous);
    if (bn) frag.append(bn);
    for (const produit of ["claude-code", "claude", "codex", "chatgpt"]) {
      const liste = sansNul(tous.filter((e) => e.produit === produit)).sort(triChrono);
      frag.append(el("h3", { text: `${PRODUITS[produit]} (${liste.length})` }));
      frag.append(listeCartes(liste, { niveau: 4, vide: "Aucun élément." }));
    }
    return frag;
  }
  function pageActu() {
    const frag = document.createDocumentFragment();
    frag.append(el("h2", { text: "Actu IA" }), noteFenetre());
    const tous = elementsDe("actu", datesRecentes("actu")).sort(triChrono);
    const bn = basculeNul(tous);
    if (bn) frag.append(bn);
    frag.append(listeCartes(sansNul(tous), { vide: "Aucune actualité sur la période." }));
    const ec = blocEcartes(datesRecentes("actu").map((d) => etat.jours[`actu/${d}`]));
    if (ec) frag.append(ec);
    return frag;
  }
  /* ---------- Référence (phase 4) : base extraite de la documentation, commentée par les agents ---------- */
  const KB_PERIMETRES = ["claude", "openai"];
  const KB_CATEGORIES = { fonctionnalites: "Fonctionnalités", commandes: "Commandes", skills: "Skills", plugins: "Plugins", mcp: "MCP", parametres: "Paramètres", raccourcis: "Raccourcis" };
  const VERDICTS = { utiliser: "à utiliser", tester: "à tester", ignorer: "à ignorer" };
  const STATUTS = { utilise: "utilisé", non_utilise: "non utilisé", inconnu: "usage inconnu" };
  const KB_PAGE = 50;
  const kbFiltre = { q: "", produit: "", categorie: "", verdict: "", statut: "", limite: KB_PAGE };
  function sansAccents(s) { return String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase(); }
  async function chargerKb() {
    if (etat.kb) return;
    const t0 = performance.now();
    const entrees = [], erreurs = [];
    await Promise.all(KB_PERIMETRES.flatMap((p) => Object.keys(KB_CATEGORIES).map(async (c) => {
      try {
        const d = await lireJson(`data/kb/${p}/${c}.json`);
        if (!d || !Array.isArray(d.entrees)) throw new Error("fichier sans `entrees`");
        for (const e of d.entrees) if (e && typeof e === "object" && e.id) {
          e._ctx = typeof d.contexte_empreinte === "string" ? d.contexte_empreinte : null;
          e._sections = d.contexte_sections && typeof d.contexte_sections === "object" ? d.contexte_sections : null;
          e._texte = sansAccents([e.nom, e.description, e.description_source, e.usage, e.groupe, e.recommandation && e.recommandation.pourquoi].join(" "));
          entrees.push(e);
        }
      } catch (err) { erreurs.push(`${p}/${c} : ${err.message || err}`); }
    })));
    entrees.sort((a, b) => String(a.nom).localeCompare(String(b.nom), "fr"));
    etat.kb = { entrees, erreurs, ms: Math.round(performance.now() - t0) };
    console.log(`delta:kb ${entrees.length} entrées en ${etat.kb.ms} ms`);
  }
  function filtrerKb() {
    const mots = sansAccents(kbFiltre.q).split(/\s+/).filter(Boolean);
    return etat.kb.entrees.filter((e) =>
      (!kbFiltre.produit || e.produit === kbFiltre.produit) &&
      (!kbFiltre.categorie || e.categorie === kbFiltre.categorie) &&
      (!kbFiltre.statut || e.statut_usage === kbFiltre.statut) &&
      (!kbFiltre.verdict || (kbFiltre.verdict === "attente" ? !e.commentee : e.commentee && e.recommandation && e.recommandation.verdict === kbFiltre.verdict)) &&
      mots.every((m) => e._texte.includes(m)));
  }
  function carteKb(e) {
    const c = el("li", { class: "carte kb" + (e.commentee ? "" : " attente") });
    const verdict = e.commentee && e.recommandation ? e.recommandation.verdict : null;
    c.append(el("div", { class: "badges" },
      badge("produit", PRODUITS[e.produit] || String(e.produit || "?")),
      badge("type", KB_CATEGORIES[e.categorie] || String(e.categorie || "?")),
      verdict ? badge(`verdict ${verdict}`, VERDICTS[verdict] || verdict) : badge("attente", "en attente de commentaire"),
      e.commentee ? badge("statut", STATUTS[e.statut_usage] || String(e.statut_usage || "")) : null,
      e.retiree ? badge("revise", "retirée de la documentation") : null,
      badgeContexte(e)));
    c.append(el("h3", { text: texte(e.nom, "(sans nom)") }));
    if (e.groupe) c.append(el("div", { class: "meta", text: `${e.groupe} · mis à jour le ${dateFr(e.maj_le)}` }));
    if (e.commentee && texte(e.description)) c.append(el("p", { class: "resume", text: e.description }));
    else if (texte(e.description_source)) c.append(el("p", { class: "resume source-en", lang: "en", text: e.description_source }));
    c.append(el("div", { class: "etiquette", text: e.usage_nature === "etapes" ? "Accès" : "Syntaxe" }));  // D49
    c.append(el("pre", { class: "usage" + (e.usage_nature === "etapes" ? " etapes" : "") }, el("code", { text: String(e.usage || "") })));
    if (e.commentee && texte(e.exemple) && e.exemple !== e.usage) c.append(el("pre", { class: "usage exemple" }, el("code", { text: e.exemple })));
    if (verdict && texte(e.recommandation.pourquoi)) c.append(el("div", { class: "pour-toi" }, el("strong", { text: "Pourquoi" }), el("p", { text: e.recommandation.pourquoi })));
    if (texte(e.disponibilite)) c.append(el("p", { class: "projets", text: `Disponibilité : ${e.disponibilite}` }));
    if (Array.isArray(e.sources) && e.sources.length) {
      c.append(el("ul", { class: "sources", "aria-label": "Sources" }, ...e.sources.map((s) =>
        el("li", { class: s && s.officielle === true ? "off" : null }, lienSur(s && s.url, texte(s && s.libelle, s && s.url))))));
    }
    return c;
  }
  // D64 : péremption par section de CONTEXTE ; `contexte_sections: null` = commentaire antérieur à D64
  function badgeContexte(e) {
    if (!e.commentee || !e._sections) return null;
    if (e.contexte_sections === null || e.contexte_sections === undefined) return badge("anterieur", "antérieur à D64");
    if (typeof e.contexte_sections !== "object") return null;
    const changees = Object.keys(e.contexte_sections).filter((k) => e._sections[k] !== e.contexte_sections[k]);
    return changees.length ? badge("perime", `commentaire à revoir : CONTEXTE ${changees.map((k) => "§" + k).join(", ")} modifié`) : null;
  }
  function choix(libelle, cle, options) {
    const s = el("select", { "aria-label": libelle });
    s.append(el("option", { value: "", text: libelle }));
    for (const [v, t] of Object.entries(options)) {
      const o = el("option", { value: v, text: t });
      if (kbFiltre[cle] === v) o.selected = true;
      s.append(o);
    }
    s.addEventListener("change", () => { kbFiltre[cle] = s.value; kbFiltre.limite = KB_PAGE; rendreResultatsKb(); });
    return s;
  }
  function rendreResultatsKb() {
    const zone = document.getElementById("kb-resultats");
    if (!zone) return;
    vider(zone);
    const liste = filtrerKb();
    const commentees = liste.filter((e) => e.commentee).length;
    zone.append(el("p", { class: "sous-titre", role: "status", text: `${liste.length} entrée(s) affichable(s) · ${commentees}/${liste.length} commentée(s)` }));
    zone.append(el("ul", { class: "liste" }, ...liste.slice(0, kbFiltre.limite).map(carteKb)));
    if (liste.length > kbFiltre.limite) {
      const b = el("button", { type: "button", class: "plus", text: `Afficher ${Math.min(KB_PAGE, liste.length - kbFiltre.limite)} de plus` });
      b.addEventListener("click", () => { kbFiltre.limite += KB_PAGE; rendreResultatsKb(); });
      zone.append(b);
    }
  }
  function pageReference() {
    const frag = document.createDocumentFragment();
    frag.append(el("h2", { text: "Référence" }));
    const kb = etat.kb;
    if (!kb || !kb.entrees.length) {
      frag.append(el("p", { class: "vide", text: "La base de référence n'est pas encore publiée." }));
      return frag;
    }
    const total = kb.entrees.length, faites = kb.entrees.filter((e) => e.commentee).length;
    const barre = el("div", { class: "avancement" }, el("span", { text: `${faites}/${total} entrées commentées` }),
      el("progress", { max: String(total), value: String(faites), "aria-label": "Avancement des commentaires" }));
    frag.append(el("p", { class: "sous-titre", text: "Fonctionnalités, commandes, skills, plugins, MCP, paramètres et raccourcis, extraits de la documentation officielle. Les entrées en attente affichent la description d'origine, en anglais." }), barre);
    if (kb.erreurs.length) frag.append(el("p", { class: "erreur", text: `Fichiers illisibles : ${kb.erreurs.join(" ; ")}` }));
    const recherche = el("input", { type: "search", placeholder: "Rechercher (nom, usage, description…)", "aria-label": "Recherche plein texte", value: kbFiltre.q });
    let minuterie = null;
    recherche.addEventListener("input", () => { clearTimeout(minuterie); minuterie = setTimeout(() => { kbFiltre.q = recherche.value; kbFiltre.limite = KB_PAGE; rendreResultatsKb(); }, 150); });
    frag.append(el("div", { class: "filtres kb-filtres" }, recherche,
      choix("Produit", "produit", Object.fromEntries(["claude-code", "claude", "codex", "chatgpt"].map((p) => [p, PRODUITS[p]]))),
      choix("Catégorie", "categorie", KB_CATEGORIES),
      choix("Verdict", "verdict", { ...VERDICTS, attente: "en attente de commentaire" }),
      choix("Statut d'usage", "statut", STATUTS)));
    frag.append(el("div", { id: "kb-resultats" }));
    return frag;
  }
  function pageATester() {
    const frag = document.createDocumentFragment();
    frag.append(el("h2", { text: "À tester" }), el("p", { class: "sous-titre", text: "Les actions proposées. La case « fait » n'est enregistrée que dans ce navigateur." }), noteFenetre());
    let liste = [];
    for (const p of PERIMETRES) liste = liste.concat(elementsDe(p, datesRecentes(p)).filter((e) => e.action && typeof e.action === "object"));
    const faits = lireFaits();
    liste.sort((a, b) => (Boolean(faits[a.id]) - Boolean(faits[b.id])) || triImpact(a, b));
    frag.append(listeCartes(liste, { vide: "Aucune action ouverte." }));
    return frag;
  }
  function pageArchives() {
    const frag = document.createDocumentFragment();
    frag.append(el("h2", { text: "Archives" }));
    const toutesDates = [...new Set(PERIMETRES.flatMap(datesDe))].sort().reverse();
    if (!toutesDates.length) { frag.append(el("p", { class: "vide", text: "Aucun passage archivé." })); return frag; }
    if (etat.archiveDate && toutesDates.includes(etat.archiveDate)) {
      const d = etat.archiveDate;
      frag.append(el("p", { class: "sous-titre" }, el("a", { href: "#archives", text: "← Toutes les dates" }), ` · passage du ${dateFr(d)}`));
      const quotidiens = [];
      let elements = [];
      for (const p of PERIMETRES) {
        if (!datesDe(p).includes(d)) continue;
        const q = etat.jours[`${p}/${d}`];
        quotidiens.push(q);
        frag.append(blocSynthese(p, q, d));
        elements = elements.concat(elementsDe(p, [d]));
      }
      elements.sort(triImpact);
      frag.append(el("h3", { text: `Éléments (${elements.length})` }));
      frag.append(listeCartes(elements, { niveau: 4 }));
      const ec = blocEcartes(quotidiens);
      if (ec) frag.append(ec);
      return frag;
    }
    const ul = el("ul", { class: "jours" });
    for (const d of toutesDates) {
      const compteurs = [];
      for (const p of PERIMETRES) {
        const j = (etat.index[p]?.jours || []).find((x) => x.date === d);
        if (!j) continue;
        const imp = j.impact || {};
        compteurs.push(`${{ claude: "Claude", openai: "OpenAI", actu: "Actu" }[p]} ${j.elements ?? "?"} (${imp.fort ?? 0} fort, ${imp.moyen ?? 0} moyen)`);
      }
      ul.append(el("li", null, el("a", { href: `#archives/${d}` }, el("strong", { text: dateFr(d) }), el("span", { class: "compteurs", text: compteurs.join(" · ") }))));
    }
    frag.append(ul);
    return frag;
  }

  /* ---------- routage par ancre ---------- */
  function lireRoute() {
    const h = (location.hash || "#aujourdhui").slice(1);
    const [page, param] = h.split("/");
    etat.page = ["aujourdhui", "changelogs", "actu", "reference", "a-tester", "archives"].includes(page) ? page : "aujourdhui";
    etat.archiveDate = etat.page === "archives" && /^\d{4}-\d{2}-\d{2}$/.test(param || "") ? param : null;
  }
  async function rendre() {
    lireRoute();
    await chargerNecessaire();
    if (etat.page === "reference") await chargerKb();
    if (etat.page === "aujourdhui") await chargerVersions();
    document.querySelectorAll(".onglets a").forEach((a) => a.classList.toggle("actif", a.dataset.page === etat.page));
    const alertes = rendreEtatAgents();
    vider(main);
    const erreursIndex = PERIMETRES.filter((p) => etat.index[p] && etat.index[p].erreur);
    if (erreursIndex.length === PERIMETRES.length) {
      main.append(el("p", { class: "erreur", text: "Aucune donnée lisible. Le site doit être servi par HTTP (GitHub Pages ou `python -m http.server` dans docs/)." }));
      return;
    }
    for (const p of erreursIndex) main.append(el("p", { class: "erreur", text: `Index ${p} illisible : ${etat.index[p].erreur}` }));
    switch (etat.page) {
      case "changelogs": main.append(pageChangelogs()); break;
      case "actu": main.append(pageActu()); break;
      case "reference": main.append(pageReference()); rendreResultatsKb(); break;
      case "a-tester": main.append(pageATester()); break;
      case "archives": main.append(pageArchives()); break;
      default: main.append(pageAujourdhui(alertes));
    }
    document.title = `Delta — ${document.querySelector(".onglets a.actif")?.textContent || "veille IA"}`;
  }

  async function demarrer() {
    try {
      await chargerIndex();
      await rendre();
    } catch (e) {
      vider(main);
      main.append(el("p", { class: "erreur", text: `Erreur de chargement : ${e.message || e}` }));
      return;
    }
    window.addEventListener("hashchange", () => { rendre().catch((e) => console.error("delta:rendu", e)); });
    console.log("delta:pret", matchMedia("(prefers-color-scheme: dark)").matches ? "theme=sombre" : "theme=clair");
  }
  demarrer();
})();
