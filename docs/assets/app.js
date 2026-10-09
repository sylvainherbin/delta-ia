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

  const etat = { index: {}, jours: {}, page: "aujourdhui", filtreProduit: "tous", archiveDate: null, semaines: { index: undefined, docs: {}, courante: null, erreur: null }, semaineDemandee: null, essaisLimite: 50, noms: undefined, kbFicheId: null };
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

  /* ---------- D105 : noms entre accents graves → fiche de la base ---------- */
  const RE_SEGMENT_CODE = /`([^`\n]+)`/g;
  // même normalisation que `normaliser_nom` de scripts/deltalib/kb/catalogue.py : NFKC, espaces réduits, minuscules
  function normaliserNom(s) { return String(s || "").normalize("NFKC").replace(/\s+/g, " ").trim().toLowerCase(); }
  // ids de la base pour un segment : son nom normalisé, à défaut son premier mot quand c'est une commande ou une option (`/add-dir ../x`)
  function idsDuNom(segment) {
    const noms = etat.noms;
    if (!noms) return [];
    const trouve = (cle) => (Object.prototype.hasOwnProperty.call(noms, cle) && Array.isArray(noms[cle]) ? noms[cle].filter((i) => typeof i === "string" && i) : []);
    const n = normaliserNom(segment);
    const ids = trouve(n);
    if (ids.length || !n.includes(" ")) return ids;
    const premier = n.split(" ")[0];
    return /^[/-]/.test(premier) ? trouve(premier) : [];
  }
  // D110 : produit d'une fiche d'après son id (`<produit>-<catégorie>-…`, voir RE_ID_KB), null si l'id n'a pas cette forme
  function produitDeId(id) {
    const m = RE_ID_KB.exec(String(id || ""));
    return m ? m[1] : null;
  }
  // D110 : parmi les ids d'un nom ambigu, ceux du produit de l'élément qui cite le segment (`produit` de l'élément = produit de la
  // fiche : claude-code ↔ fiches Claude Code, codex ↔ fiches Codex, etc.) ; la liste complète quand l'élément n'a pas de produit
  // connu ou que le produit ne départage pas (zéro fiche, ou encore plusieurs : recherche comme avant)
  function idsDuProduit(ids, produit) {
    if (ids.length < 2 || typeof produit !== "string" || !produit) return ids;
    const memes = ids.filter((i) => produitDeId(i) === produit);
    return memes.length === 1 ? memes : ids;
  }
  // texte → nœuds : chaque segment entre accents graves qui désigne une seule fiche devient un lien vers elle (un nom partagé par
  // plusieurs fiches aussi quand une seule est du produit de l'élément, `produit`), un nom encore ambigu un lien vers la recherche,
  // un segment inconnu reste en texte simple (accents graves compris)
  function enrichi(s, produit) {
    const t = typeof s === "string" ? s : String(s === null || s === undefined ? "" : s);
    if (!etat.noms) return [t];
    const out = [];
    let fin = 0;
    for (const m of t.matchAll(RE_SEGMENT_CODE)) {
      const ids = idsDuProduit(idsDuNom(m[1]), produit);
      if (!ids.length) continue;
      if (m.index > fin) out.push(t.slice(fin, m.index));
      out.push(el("a", {
        class: "ref-lien", href: ids.length === 1 ? `#reference?id=${encodeURIComponent(ids[0])}` : `#reference?q=${encodeURIComponent(m[1].trim())}`,
        title: ids.length === 1 ? "Fiche de la base de référence" : `${ids.length} fiches portent ce nom : recherche dans la référence`,
      }, el("code", { text: m[1] })));
      fin = m.index + m[0].length;
    }
    if (fin < t.length) out.push(t.slice(fin));
    return out;
  }
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
      // un agent à plusieurs périmètres (Claude Code : claude et actu) prend le passage le plus ANCIEN,
      // pour qu'un périmètre qui n'a pas tourné ne soit pas masqué par l'autre (audit du 25/09)
      if (!parAgent[idx.agent] || t < parAgent[idx.agent]) parAgent[idx.agent] = t;
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

  /* ---------- Compte et quotas : etat.json > comptes (D93, D71) ---------- */
  const QUOTAS_AFFICHES = [
    ["claude_session_5h", "Claude, session 5 h", false], ["claude_semaine", "Claude, semaine", true],
    ["claude_semaine_fable", "Claude, semaine Fable", true], ["chatgpt_semaine", "ChatGPT, semaine", true]];
  const SEUIL_ALERTE_PCT = 80;
  const PHRASE_D71 = "vérifie tes remises à zéro disponibles (Paramètres > Utilisation) avant d'économiser";
  async function chargerComptes() {
    if (etat.comptes !== undefined) return;
    try {
      const e = await lireJson("data/etat.json");
      etat.comptes = e && typeof e.comptes === "object" && e.comptes ? e.comptes : null;
    } catch (err) { etat.comptes = null; }
  }
  function jjmmHhmm(iso) {
    const d = new Date(iso);
    if (typeof iso !== "string" || Number.isNaN(d.getTime())) return null;
    const z = (n) => String(n).padStart(2, "0");
    return `${z(d.getDate())}/${z(d.getMonth() + 1)} à ${z(d.getHours())}:${z(d.getMinutes())}`;
  }
  function ageFr(iso, maintenant) {
    const ms = maintenant - new Date(iso).getTime();
    if (typeof iso !== "string" || Number.isNaN(ms)) return null;
    const min = Math.max(0, Math.round(ms / 60000));
    if (min < 60) return `il y a ${min} min`;
    if (min < 2880) return `il y a ${Math.round(min / 60)} h`;
    return `il y a ${Math.round(min / 1440)} j`;
  }
  const SEUIL_CREDIT_JOURS = 14;
  function creditsComptes(c, maintenant) {
    if (!Array.isArray(c.credits) || !c.credits.length) return null;
    const liste = el("ul", { class: "credits" });
    for (const cr of c.credits) {
      if (!cr || typeof cr !== "object") continue;
      const connu = typeof cr.solde_usd === "number" && Number.isFinite(cr.solde_usd);
      const finit = new Date(cr.expire_le).getTime();
      const datee = typeof cr.expire_le === "string" && !Number.isNaN(finit);
      const jours = datee ? (finit - maintenant) / 86400000 : null;
      const expire = datee && jours <= 0;
      const alerte = connu && datee && jours > 0 && jours <= SEUIL_CREDIT_JOURS;
      const releve = jjmmHhmm(cr.releve_le);
      const solde = connu ? `${cr.solde_usd.toFixed(2).replace(".", ",")} $` : "solde inconnu";
      const echeance = !datee ? "échéance inconnue"
        : expire ? `crédit expiré le ${jjmmHhmm(cr.expire_le)}`
        : `à utiliser avant le ${jjmmHhmm(cr.expire_le)} (${Math.ceil(jours)} j)`;
      const detail = [echeance, connu && releve ? `solde relevé le ${releve}` : null, !connu || !datee ? texte(cr.raison) : null]
        .filter(Boolean).join(" · ");
      liste.append(el("li", { class: "credit" + (alerte ? " alerte" : "") + (expire ? " perimee" : "") },
        el("span", { class: "quota-nom", text: texte(cr.nom, "Crédit") }),
        el("span", { class: "quota-pct", text: solde }),
        el("span", { class: "quota-rz", text: detail })));
    }
    return liste.children.length ? liste : null;
  }
  function blocComptes(maintenant) {
    const c = etat.comptes;
    if (!c || typeof c !== "object") return null;
    const sec = el("section", { class: "comptes", "aria-label": "Compte et quotas" }, el("h3", { text: "COMPTE ET QUOTAS" }));
    if (c.statut !== "ok" || !c.quotas || typeof c.quotas !== "object") {
      sec.append(el("p", { class: "pied-comptes", text: `Quotas inconnus${texte(c.raison) ? ` : ${c.raison}` : ""}.` }));
      const seuls = creditsComptes(c, maintenant);
      if (seuls) sec.append(seuls);
      return sec;
    }
    let alerte = false;
    const liste = el("ul", { class: "quotas" });
    for (const [cle, libelle, hebdo] of QUOTAS_AFFICHES) {
      const q = c.quotas[cle];
      if (!q || typeof q !== "object") continue;
      const connu = Number.isInteger(q.pct) && q.pct >= 0 && q.pct <= 100;
      const rz = jjmmHhmm(q.remise_a_zero);
      const perimee = rz !== null && new Date(q.remise_a_zero).getTime() < maintenant;
      const fort = connu && hebdo && q.pct > SEUIL_ALERTE_PCT && !perimee;
      if (fort) alerte = true;
      const barre = el("div", { class: "barre", role: "progressbar", "aria-label": libelle, "aria-valuemin": "0", "aria-valuemax": "100",
        "aria-valuenow": connu ? String(q.pct) : null }, el("span", { style: `width:${connu ? q.pct : 0}%` }));
      const detail = perimee ? `remise à zéro passée (${rz}) : valeur périmée`
        : rz ? `remise à zéro le ${rz}` : "remise à zéro inconnue";
      liste.append(el("li", { class: "quota" + (fort ? " alerte" : "") + (perimee ? " perimee" : "") },
        el("span", { class: "quota-nom", text: libelle }),
        el("span", { class: "quota-pct", text: connu ? `${q.pct} %` : "inconnu" }),
        barre,
        el("span", { class: "quota-rz", text: connu ? detail : texte(q.raison, "valeur absente") })));
    }
    sec.append(liste);
    const credits = creditsComptes(c, maintenant);
    if (credits) sec.append(credits);
    if (alerte) sec.append(el("p", { class: "alerte-d71", role: "status", text: `Quota hebdomadaire au-delà de ${SEUIL_ALERTE_PCT} % : ${PHRASE_D71}.` }));
    const releve = jjmmHhmm(c.releve_le);
    sec.append(el("p", { class: "pied-comptes", text: releve ? `Relevé du ${releve} (${ageFr(c.releve_le, maintenant)}).` : "Date du relevé inconnue." }));
    return sec;
  }

  /* ---------- Tes outils : versions installées (D54 à D56) ---------- */
  const STATUTS_VERSION = { a_jour: "à jour", en_retard: "en retard", inconnu: "inconnu", embarque: "embarqué", non_utilise: "non utilisée" };
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
      corps.append(el("tr", { class: note ? "avec-note" : null },
        el("td", { text: texte(l.outil, "?") }),
        el("td", { class: "v", text: l.version ? String(l.version) : "introuvable" }),
        el("td", { class: "v col-derniere", text: l.derniere_publiee ? String(l.derniere_publiee) : "—" }),
        el("td", null, el("span", { class: `statut ${statut}` }, el("span", { class: "point", "aria-hidden": "true" }), STATUTS_VERSION[statut]))));
      if (note) corps.append(el("tr", { class: "ligne-note" }, el("td", { colspan: "4", text: note })));
    }
    const date = lignes.map((l) => l && l.detectee_le).filter(Boolean).sort().pop();
    return el("section", { class: "outils", "aria-label": "Tes outils" },
      el("h3", { text: "TES OUTILS" }),
      el("table", null,
        el("thead", null, el("tr", null, el("th", { text: "Outil" }), el("th", { text: "Installée" }),
          el("th", { class: "col-derniere", text: "Dernière publiée" }), el("th", { text: "Statut" }))),
        corps),
      el("p", { class: "pied-outils", text: `Relevé le ${date ? horodatageFr(date) : "?"} sur la machine de Sylvain. « Dernière publiée » vient des sources suivies par Delta ; sans source, le statut reste inconnu. Le Codex de l'app ChatGPT suit le canal de l'app : il n'est pas comparé.` }));
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
    if (texte(e.resume)) c.append(el("p", { class: "resume" }, ...enrichi(e.resume, e.produit)));
    if (texte(e.pour_toi)) c.append(el("div", { class: "pour-toi" }, el("strong", { text: "Pour toi" }), el("p", null, ...enrichi(e.pour_toi, e.produit))));
    if (e.action && typeof e.action === "object") {
      const a = el("div", { class: "action" }, el("strong", { text: "Action" }),
        e.action.effort ? el("span", { class: "effort", text: `effort : ${e.action.effort}` }) : null,
        texte(e.action.description) ? el("p", null, ...enrichi(e.action.description, e.produit)) : null);
      if (Array.isArray(e.action.etapes) && e.action.etapes.length) {
        a.append(el("ol", null, ...e.action.etapes.map((s) => el("li", null, ...enrichi(s, e.produit)))));
      }
      const id = String(e.id || "");
      const caseFait = el("input", { type: "checkbox" });
      caseFait.checked = Boolean(faits[id]);
      caseFait.addEventListener("change", () => {
        ecrireFait(id, caseFait.checked); c.classList.toggle("fait", caseFait.checked);
        if (options.surFait) options.surFait();
      });
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
    const comptes = blocComptes(Date.now());
    if (comptes) frag.append(comptes);
    const outils = blocOutils();
    if (outils) frag.append(outils);
    frag.append(el("div", { id: "encart-kb" }));
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
  // D99 : l'encart lit docs/data/kb/recent.json (quelques dizaines de Ko), jamais la base complète (3 Mo), réservée à l'onglet Référence
  function completerEncartKb() {
    chargerRecentKb().then((recent) => {
      const zone = document.getElementById("encart-kb");
      if (!zone || etat.page !== "aujourdhui" || !recent) return;
      vider(zone);
      const p = encartNouveauKb(recent);
      if (p) zone.append(p);
    }).catch((err) => console.error("delta:encart-kb", err));
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
  const kbFiltre = { q: "", produit: "", categorie: "", verdict: "", statut: "", tri: "", depuis: "", limite: KB_PAGE };
  const KB_NOMS = { fonctionnalites: ["fonctionnalité", "fonctionnalités"], commandes: ["commande", "commandes"], skills: ["skill", "skills"], plugins: ["plugin", "plugins"], mcp: ["MCP", "MCP"], parametres: ["paramètre", "paramètres"], raccourcis: ["raccourci", "raccourcis"] };
  const KB_JOURS_RECENTS = ["7", "30"];
  const LIGNE_AJOUT = "ajoutée à l'inventaire";
  const ISO_JOUR = /^\d{4}-\d{2}-\d{2}$/;
  function sansAccents(s) { return String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase(); }
  // date d'ajout d'une entrée : ligne « ajoutée à l'inventaire » de l'historique, à défaut la plus ancienne date de l'historique, à défaut null (jamais devinée)
  function dateAjout(e) {
    const lignes = e && Array.isArray(e.historique) ? e.historique.filter((l) => l && typeof l === "object" && typeof l.date === "string" && ISO_JOUR.test(l.date)) : [];
    const ajout = lignes.filter((l) => typeof l.changement === "string" && l.changement.normalize("NFC").trim() === LIGNE_AJOUT).map((l) => l.date).sort();
    return ajout[0] || lignes.map((l) => l.date).sort()[0] || null;
  }
  function jourLocalIso(d) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }
  // premier jour AAAA-MM-JJ de la fenêtre des `jours` derniers jours, `ref` = jour de référence AAAA-MM-JJ
  function seuilJours(jours, ref) {
    const [y, m, j] = ref.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, j - Number(jours))).toISOString().slice(0, 10);
  }
  // vrai si la date d'ajout tombe dans les `jours` derniers jours (aujourd'hui compris)
  function ajouteeDepuis(e, jours, ref) {
    const a = dateAjout(e);
    if (!a || !ISO_JOUR.test(ref)) return false;
    return a >= seuilJours(jours, ref) && a <= ref;
  }
  // fichier léger des ajouts récents ; absent ou illisible : null, sans message (pas d'encart)
  async function chargerRecentKb() {
    if (etat.kbRecent !== undefined) return etat.kbRecent;
    try {
      const d = await lireJson("data/kb/recent.json");
      etat.kbRecent = d && Array.isArray(d.entrees) ? d : null;
    } catch (err) { etat.kbRecent = null; }
    return etat.kbRecent;
  }
  // D103 : essais de la base (verdicts tester puis utiliser) pour l'onglet « À tester » ; absent ou illisible : null, section omise sans message
  async function chargerATesterKb() {
    if (etat.kbATester !== undefined) return etat.kbATester;
    try {
      const d = await lireJson("data/kb/a-tester.json");
      etat.kbATester = d && Array.isArray(d.entrees) ? d : null;
    } catch (err) { etat.kbATester = null; }
    return etat.kbATester;
  }
  // D105 : index nom → ids (docs/data/kb/noms.json) pour les liens vers les fiches ; absent ou illisible : null, les segments restent en texte simple
  async function chargerNomsKb() {
    if (etat.noms !== undefined) return etat.noms;
    try {
      const d = await lireJson("data/kb/noms.json");
      etat.noms = d && typeof d === "object" && !Array.isArray(d) ? d : null;
    } catch (err) { etat.noms = null; }
    return etat.noms;
  }
  async function chargerKb() {
    const kb = etatKb();
    if (etat.kbFicheId) {
      // la fiche seule ne lit que son fichier ; id d'une autre forme ou fiche absente de ce fichier : toute la base, pour conclure juste
      const f = fichierDeIdKb(etat.kbFicheId);
      if (f) await chargerFichierKb(f[0], f[1]);
      if (!kb.entrees.some((e) => e.id === etat.kbFicheId)) { chargerResteKb(); await Promise.all(KB_FICHIERS.map(([p, c]) => chargerFichierKb(p, c))); }
      return;
    }
    await Promise.all(KB_PRIORITAIRES.flatMap((c) => KB_PERIMETRES.map((p) => chargerFichierKb(p, c))));
    console.log(`delta:kb premiers fichiers ${kb.entrees.length} entrées en ${Math.round(performance.now() - kb.debut)} ms`);
    if (kb.entrees.length) chargerResteKb();
    else { chargerResteKb(); await kb.reste; }  // rien de lisible dans les premiers fichiers : conclure sur toute la base
  }
  /* Chargement par morceaux (m-b6207baf75ca) : la base tient en 14 fichiers (périmètre × catégorie, environ 3 Mo). Les commandes et
     les fonctionnalités des deux périmètres suffisent à la première page ; le reste se charge en arrière-plan, deux fichiers à la fois,
     et un filtre qui en demande un le fait passer devant. Les compteurs ne sont exacts qu'une fois tout chargé : jusqu'alors ils sont
     annoncés provisoires. */
  const KB_PRIORITAIRES = ["commandes", "fonctionnalites"];
  const KB_ARRIERE_PLAN = ["skills", "plugins", "mcp", "raccourcis", "parametres"]; // les petits fichiers d'abord, le plus lourd à la fin
  const KB_PARALLELE = 2;
  const KB_PRODUIT_PERIMETRE = { claude: "claude", "claude-code": "claude", codex: "openai", chatgpt: "openai" };
  const KB_FICHIERS = KB_PERIMETRES.flatMap((p) => Object.keys(KB_CATEGORIES).map((c) => [p, c]));
  const RE_ID_KB = new RegExp(`^(claude-code|claude|codex|chatgpt)-(${Object.keys(KB_CATEGORIES).join("|")})-`);
  function etatKb() {
    if (!etat.kb) etat.kb = { entrees: [], erreurs: [], charges: new Set(), promesses: new Map(), debut: performance.now(), reste: null, ms: null };
    return etat.kb;
  }
  // même ordre que `localeCompare(…, "fr")`, avec un collateur construit une fois ; chaque fichier reçu est trié seul puis fusionné à la liste triée
  const COLLATEUR_KB = new Intl.Collator("fr");
  const comparerNomKb = (a, b) => COLLATEUR_KB.compare(String(a.nom), String(b.nom));
  function fusionnerParNomKb(a, b) {
    const sortie = [];
    let i = 0, j = 0;
    while (i < a.length && j < b.length) sortie.push(comparerNomKb(b[j], a[i]) < 0 ? b[j++] : a[i++]);
    while (i < a.length) sortie.push(a[i++]);
    while (j < b.length) sortie.push(b[j++]);
    return sortie;
  }
  const cleKb = (p, c) => `${p}/${c}`;
  // charge un fichier de la base une seule fois (promesse mémorisée) ; un échec va dans `erreurs`, jamais dans une liste vide muette
  function chargerFichierKb(p, c) {
    const kb = etatKb(), cle = cleKb(p, c);
    if (!kb.promesses.has(cle)) {
      kb.promesses.set(cle, (async () => {
        const nouvelles = [];
        try {
          const d = await lireJson(`data/kb/${p}/${c}.json`);
          if (!d || !Array.isArray(d.entrees)) throw new Error("fichier sans `entrees`");
          for (const e of d.entrees) if (e && typeof e === "object" && e.id) {
            e._sections = d.contexte_sections && typeof d.contexte_sections === "object" ? d.contexte_sections : null;
            e._deprecies = Array.isArray(d.contexte_deprecies) ? d.contexte_deprecies : [];
            e._ajout = dateAjout(e);
            e._texte = sansAccents([e.nom, e.description, e.description_source, e.usage, e.groupe, e.recommandation && e.recommandation.pourquoi].join(" "));
            nouvelles.push(e);
          }
        } catch (err) { kb.erreurs.push(`${cle} : ${err.message || err}`); }
        if (nouvelles.length) kb.entrees = fusionnerParNomKb(kb.entrees, nouvelles.sort(comparerNomKb));
        kb.charges.add(cle);
        if (kb.charges.size === KB_FICHIERS.length) {
          kb.ms = Math.round(performance.now() - kb.debut);
          console.log(`delta:kb complet ${kb.entrees.length} entrées en ${kb.ms} ms`);
        }
      })());
    }
    return kb.promesses.get(cle);
  }
  const kbComplet = () => etatKb().charges.size === KB_FICHIERS.length;
  // fichier d'une entrée d'après son id (`<produit>-<catégorie>-…`), null si l'id n'a pas cette forme
  function fichierDeIdKb(id) {
    const m = RE_ID_KB.exec(String(id || ""));
    return m ? [KB_PRODUIT_PERIMETRE[m[1]], m[2]] : null;
  }
  // fichiers que le filtre courant peut lire : produit → son périmètre, catégorie → ce fichier ; sans l'un ni l'autre, toute la base
  function fichiersRequisKb() {
    const perimetre = kbFiltre.produit ? KB_PRODUIT_PERIMETRE[kbFiltre.produit] : null;
    return KB_FICHIERS.filter(([p, c]) => (!perimetre || p === perimetre) && (!kbFiltre.categorie || c === kbFiltre.categorie));
  }
  // charge ce qui reste, hors fichiers déjà chargés ou en cours, KB_PARALLELE à la fois ; une seule fois
  function chargerResteKb() {
    const kb = etatKb();
    if (kb.reste) return kb.reste;
    const file = KB_ARRIERE_PLAN.flatMap((c) => KB_PERIMETRES.map((p) => [p, c]));
    const ouvrier = async () => { while (file.length) { const [p, c] = file.shift(); await chargerFichierKb(p, c); majChargementKb(); } };
    kb.reste = Promise.all(Array.from({ length: KB_PARALLELE }, ouvrier)).then(majChargementKb);
    return kb.reste;
  }
  // ligne d'état du chargement et avancement des commentaires, recalculés à chaque fichier reçu ; l'erreur d'un fichier reste affichée
  function majChargementKb() {
    const kb = etat.kb, zone = document.getElementById("kb-chargement");
    if (!kb || !zone) return;
    vider(zone);
    if (!kbComplet()) {
      zone.append(el("span", { text: `Chargement de la base en arrière-plan : ${kb.charges.size}/${KB_FICHIERS.length} fichiers. Compteurs et résultats provisoires.` }));
    }
    zone.setAttribute("aria-busy", kbComplet() ? "false" : "true");
    const faites = kb.entrees.filter((e) => e.commentee).length;
    const av = document.getElementById("kb-avancement");
    if (av) {
      av.querySelector("span").textContent = `${faites}/${kb.entrees.length} entrées commentées${kbComplet() ? "" : " (provisoire)"}`;
      const pr = av.querySelector("progress");
      pr.max = Math.max(kb.entrees.length, 1); pr.value = faites;
    }
    const err = document.getElementById("kb-erreurs");
    if (err) { err.textContent = kb.erreurs.length ? `Fichiers illisibles : ${kb.erreurs.join(" ; ")}` : ""; err.hidden = !kb.erreurs.length; }
  }
  function filtrerKb() {
    const mots = sansAccents(kbFiltre.q).split(/\s+/).filter(Boolean);
    const ref = jourLocalIso(new Date());
    const liste = etat.kb.entrees.filter((e) =>
      (!kbFiltre.depuis || ajouteeDepuis(e, kbFiltre.depuis, ref)) &&
      (!kbFiltre.produit || e.produit === kbFiltre.produit) &&
      (!kbFiltre.categorie || e.categorie === kbFiltre.categorie) &&
      (!kbFiltre.statut || e.statut_usage === kbFiltre.statut) &&
      (!kbFiltre.verdict || (kbFiltre.verdict === "attente" ? !e.commentee : e.commentee && e.recommandation && e.recommandation.verdict === kbFiltre.verdict)) &&
      mots.every((m) => e._texte.includes(m)));
    if (kbFiltre.tri !== "recent") return liste;
    // date d'ajout décroissante, alphabétique à égalité, dates inconnues en dernier
    return liste.slice().sort((a, b) => (b._ajout || "").localeCompare(a._ajout || "") || String(a.nom).localeCompare(String(b.nom), "fr"));
  }
  // encart de l'onglet Aujourd'hui : ce qui est nouveau dans la base depuis 7 jours (lu dans recent.json), absent si rien
  function encartNouveauKb(recent) {
    const ref = jourLocalIso(new Date());
    const seuil = seuilJours(7, ref);
    const compte = {};
    for (const e of recent.entrees) {
      if (e && typeof e.date_ajout === "string" && ISO_JOUR.test(e.date_ajout) && e.date_ajout >= seuil && e.date_ajout <= ref) compte[e.categorie] = (compte[e.categorie] || 0) + 1;
    }
    const parties = Object.keys(KB_CATEGORIES).filter((c) => compte[c]).map((c) => `${compte[c]} ${KB_NOMS[c][compte[c] > 1 ? 1 : 0]}`);
    if (!parties.length) return null;
    // fichier coupé avant le seuil des 7 jours : le compte est un minimum
    const minimum = recent.tronque === true && typeof recent.plus_ancienne === "string" && recent.plus_ancienne >= seuil;
    return el("p", { class: "encart-nouveau", role: "status" }, el("strong", { text: "Nouveau dans la base (7 jours) : " }), `${minimum ? "au moins " : ""}${parties.join(", ")} `,
      el("a", { href: "#reference?recent=7", text: "Voir les nouveautés" }));
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
    if (e.groupe || e._ajout) c.append(el("div", { class: "meta", text: [e.groupe, e._ajout ? `ajoutée le ${dateFr(e._ajout)}` : null, `mis à jour le ${dateFr(e.maj_le)}`].filter(Boolean).join(" · ") }));
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
    c.append(blocEnvoi(e));
    return c;
  }
  /* ---------- « Envoyer à Delta » (m-944fab565b10) : relais local sur 127.0.0.1 (scripts/relais_reference.py), qui ne lit
     que l'id et relaie l'entrée de sa base locale vers la porte des idées ; injoignable (téléphone, relais arrêté) : le texte
     de l'idée est copié pour le lanceur Delta. Le site ne dépend pas du relais (D61). ---------- */
  const RELAIS = "http://127.0.0.1:47613";
  const CLE_ENVOIS = "delta.envoisKb";
  function lireEnvois() {
    try { const v = JSON.parse(localStorage.getItem(CLE_ENVOIS) || "{}"); return v && typeof v === "object" ? v : {}; }
    catch (err) { return {}; }
  }
  function noterEnvoi(id) {
    try { const v = lireEnvois(); v[id] = jourLocalIso(new Date()); localStorage.setItem(CLE_ENVOIS, JSON.stringify(v)); }
    catch (err) { /* sans stockage : l'envoi est fait, seule la mention « envoyée le » se perd */ }
  }
  // même phrase d'ouverture que texte_idee() du relais
  function texteIdeeKb(e) {
    const cat = KB_NOMS[e.categorie] ? KB_NOMS[e.categorie][0] : String(e.categorie || "référence");
    return `idée : intégrer la référence Delta-IA « ${texte(e.nom, "(sans nom)")} » (${PRODUITS[e.produit] || String(e.produit || "produit inconnu")}, ${cat}, id ${e.id}) ` +
      "dans un workflow ou chez un agent de Delta. Juge sa pertinence pour mes projets et, si elle l'est, dis dans quel workflow ou chez quel agent elle entre et ce que ça change.";
  }
  /* Adresse de la console de pilotage (D104) : jamais dans le dépôt ni sur le site (REGLES §5), seulement dans ce navigateur.
     Elle s'y enregistre en ouvrant une fois https://sylvainherbin.github.io/delta-ia/#console=<adresse> ; le fragment est retiré
     de l'URL aussitôt. Admis : https, ou http vers une adresse Tailscale (100.64.0.0/10) ou un nom *.ts.net. */
  const CLE_CONSOLE = "delta.console";
  const IDEE_CONSOLE_MAX = 500; // limite de /api/voix
  function adresseConsole(brut) {
    let u;
    try { u = new URL(String(brut || "").trim()); } catch (err) { return null; }
    if (u.username || u.password || !u.hostname) return null;
    const h = u.hostname;
    const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(h);
    const tailscale = (m && +m[1] === 100 && +m[2] >= 64 && +m[2] <= 127 && [m[3], m[4]].every((o) => +o <= 255)) || /^[a-z0-9-]+(\.[a-z0-9-]+)*\.ts\.net$/i.test(h);
    if (u.protocol !== "https:" && !(u.protocol === "http:" && tailscale)) return null;
    return u.origin + u.pathname.replace(/\/+$/, "");
  }
  function lireConsole() {
    try { return adresseConsole(localStorage.getItem(CLE_CONSOLE)); } catch (err) { return null; }
  }
  // #console=<adresse> : enregistre (ou, vide, oublie) l'adresse, puis retire le fragment ; renvoie un message ou null
  function enregistrerConsoleDepuisUrl() {
    const h = location.hash || "";
    if (!h.startsWith("#console=")) return null;
    let brut = h.slice(9);
    try { brut = decodeURIComponent(brut); } catch (err) { /* adresse laissée telle quelle */ }
    try { history.replaceState(null, "", location.pathname + location.search); } catch (err) { location.hash = ""; }
    if (!brut) {
      try { localStorage.removeItem(CLE_CONSOLE); } catch (err) { /* rien à oublier */ }
      return "Adresse de la console oubliée dans ce navigateur.";
    }
    const adresse = adresseConsole(brut);
    if (!adresse) return "Adresse de console refusée : https, ou http vers une adresse Tailscale (100.64.0.0/10 ou *.ts.net).";
    try { localStorage.setItem(CLE_CONSOLE, adresse); } catch (err) { return "Ce navigateur refuse d'enregistrer l'adresse de la console."; }
    return "Adresse de la console enregistrée dans ce navigateur ; « Envoyer à Delta » l'ouvrira quand le relais de bureau n'est pas joignable.";
  }
  function annoncer(message) {
    const p = el("p", { class: "avis-console", role: "status", text: message });
    main.before(p);
    setTimeout(() => p.remove(), 12000);
  }
  function coupe(s, n) { return s.length <= n ? s : s.slice(0, n - 1).trimEnd() + "…"; }
  function urlConsole(adresse, e) { return `${adresse}/#idee=${encodeURIComponent(coupe(texteIdeeKb(e), IDEE_CONSOLE_MAX))}`; }
  // iPhone, iPad (qui se présente comme un Mac depuis iPadOS 13) : 127.0.0.1 n'y est pas le bureau
  function estIos() {
    const ua = navigator.userAgent || "";
    return /iPhone|iPad|iPod/.test(ua) || navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1;
  }
  // GET /etat : un navigateur qui bloque le réseau local (Brave sans autorisation, Chrome) ou un relais arrêté conclut en 3 s au plus
  async function relaisJoignable() {
    try {
      const rep = await fetch(`${RELAIS}/etat`, { signal: AbortSignal.timeout(3000) });
      return rep.ok;
    } catch (err) { return false; }
  }
  async function envoyerADelta(e, bouton, statut) {
    statut.textContent = "";
    for (const vieux of document.querySelectorAll(".envoi-secours")) vieux.remove();
    if (estIos()) return repli(e, statut, "Pas de relais de bureau sur cet appareil.");
    bouton.disabled = true;
    bouton.textContent = "Envoi…";
    let r = null;
    if (await relaisJoignable()) {
      try {
        const rep = await fetch(`${RELAIS}/reference`, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: e.id }), signal: AbortSignal.timeout(25000) });
        r = await rep.json();
      } catch (err) { r = null; }
    }
    if (r && r.ok === true) {
      noterEnvoi(e.id);
      bouton.textContent = "Envoyée";
      statut.textContent = "Delta juge sa pertinence ; la suite arrive comme pour une idée.";
      return;
    }
    bouton.disabled = false;
    bouton.textContent = "Envoyer à Delta";
    if (r) { statut.textContent = `Delta n'a pas pris la référence : ${texte(r.detail, String(r.etape || "refus"))}`; return; }
    // relais injoignable (téléphone, relais arrêté, accès au réseau local refusé) : la console, sinon le texte de l'idée pour le lanceur
    return repli(e, statut, "Relais de bureau injoignable (arrêté, ou accès au réseau local refusé par le navigateur).");
  }
  async function repli(e, statut, motif) {
    const adresse = lireConsole();
    if (adresse) {
      statut.textContent = `${motif} Ouverture de la console.`;
      const url = urlConsole(adresse, e);
      const w = window.open(url, "_blank");
      if (w) { try { w.opener = null; } catch (err) { /* sans effet */ } return; }
      statut.after(el("a", { class: "envoi-delta envoi-secours", href: url, target: "_blank", rel: "noopener", text: "Ouvrir la console" }));
      return;
    }
    statut.textContent = motif;
    if (await copierIdeeKb(e)) { statut.textContent = `${motif} Idée copiée, colle-la dans le lanceur Delta.`; return; }
    const copier = el("button", { type: "button", class: "envoi-delta envoi-secours", text: "Copier l'idée" });
    copier.addEventListener("click", async () => {
      statut.textContent = (await copierIdeeKb(e)) ? "Idée copiée : colle-la dans le lanceur Delta." : "Copie refusée par le navigateur.";
      copier.remove();
    });
    statut.after(copier);
  }
  // le presse-papier peut rester en attente sans geste récent de l'utilisateur : 1,5 s au plus
  async function copierIdeeKb(e) {
    try {
      await Promise.race([navigator.clipboard.writeText(texteIdeeKb(e)), new Promise((_, non) => setTimeout(() => non(new Error("délai")), 1500))]);
      return true;
    } catch (err) { return false; }
  }
  function blocEnvoi(e) {
    const jour = lireEnvois()[e.id];
    const statut = el("span", { class: "envoi-statut", role: "status", text: typeof jour === "string" ? `envoyée à Delta le ${dateFr(jour)}` : "" });
    const b = el("button", { type: "button", class: "envoi-delta", text: "Envoyer à Delta",
      title: "Delta juge la pertinence de cette référence et, si elle l'est, l'oriente vers un workflow ou un agent" });
    b.addEventListener("click", () => envoyerADelta(e, b, statut));
    return el("div", { class: "envoi" }, b, statut);
  }
  // D64-bis : péremption par ctx-id de CONTEXTE ; `contexte_sections: null` = commentaire antérieur à D64
  function badgeContexte(e) {
    if (!e.commentee || !e._sections) return null;
    if (e.contexte_sections === null || e.contexte_sections === undefined) return badge("anterieur", "antérieur à D64");
    if (typeof e.contexte_sections !== "object") return null;
    const changees = Object.keys(e.contexte_sections).filter((k) => {
      const v = e.contexte_sections[k];
      return e._deprecies.includes(k) || !v || typeof v !== "object" || e._sections[k] !== v.sha1;
    });
    return changees.length ? badge("perime", `commentaire à revoir : CONTEXTE ${changees.join(", ")} modifié`) : null;
  }
  function choix(libelle, cle, options, vide) {
    const s = el("select", { "aria-label": libelle });
    s.append(el("option", { value: "", text: vide || libelle }));
    for (const [v, t] of Object.entries(options)) {
      const o = el("option", { value: v, text: t });
      if (kbFiltre[cle] === v) o.selected = true;
      s.append(o);
    }
    s.addEventListener("change", () => { kbFiltre[cle] = s.value; kbFiltre.limite = KB_PAGE; rendreResultatsKb(); });
    return s;
  }
  // une fois les fichiers manquants reçus, les résultats se refont une seule fois même si plusieurs frappes ou filtres les attendaient
  let renduKb = null;
  function refaireApresChargementKb(manquants) {
    Promise.all(manquants.map(([p, c]) => chargerFichierKb(p, c))).then(() => {
      clearTimeout(renduKb);
      renduKb = setTimeout(() => { majChargementKb(); if (document.getElementById("kb-resultats")) rendreResultatsKb(); }, 0);
    });
  }
  function rendreResultatsKb() {
    const zone = document.getElementById("kb-resultats");
    if (!zone) return;
    vider(zone);
    // fichiers que ce filtre demande et qui manquent : ils partent tout de suite, le résultat se refait quand ils sont là
    const manquants = fichiersRequisKb().filter(([p, c]) => !etatKb().charges.has(cleKb(p, c)));
    if (manquants.length) refaireApresChargementKb(manquants);
    majChargementKb();
    const liste = filtrerKb();
    const commentees = liste.filter((e) => e.commentee).length;
    zone.append(el("p", { class: "sous-titre", role: "status", text: `${liste.length} entrée(s) affichable(s) · ${commentees}/${liste.length} commentée(s)${manquants.length ? " · provisoire, chargement en cours" : ""}` }));
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
    if (!kb || (!kb.entrees.length && kbComplet())) {
      frag.append(el("p", { class: "vide", text: "La base de référence n'est pas encore publiée." }));
      return frag;
    }
    if (etat.kbFicheId) {
      const fiche = kb.entrees.find((e) => e.id === etat.kbFicheId);
      frag.append(el("p", { class: "retour-ref" }, el("a", { href: "#reference", text: "← Toute la référence" })),
        fiche ? el("ul", { class: "liste" }, carteKb(fiche)) : el("p", { class: "vide", text: "Aucune fiche pour cet identifiant : la base a pu changer." }));
      window.scrollTo(0, 0);
      return frag;
    }
    const total = kb.entrees.length, faites = kb.entrees.filter((e) => e.commentee).length;
    const barre = el("div", { class: "avancement", id: "kb-avancement" }, el("span", { text: `${faites}/${total} entrées commentées` }),
      el("progress", { max: String(total), value: String(faites), "aria-label": "Avancement des commentaires" }));
    frag.append(el("p", { class: "sous-titre", text: "Fonctionnalités, commandes, skills, plugins, MCP, paramètres et raccourcis, extraits de la documentation officielle. Les entrées en attente affichent la description d'origine, en anglais." }), barre);
    frag.append(el("div", { id: "kb-chargement", class: "avancement kb-chargement", role: "status", "aria-live": "polite" }),
      el("p", { id: "kb-erreurs", class: "erreur", hidden: true }));
    const recherche = el("input", { type: "search", placeholder: "Rechercher (nom, usage, description…)", "aria-label": "Recherche plein texte", value: kbFiltre.q });
    let minuterie = null;
    recherche.addEventListener("input", () => { clearTimeout(minuterie); minuterie = setTimeout(() => { kbFiltre.q = recherche.value; kbFiltre.limite = KB_PAGE; rendreResultatsKb(); }, 150); });
    frag.append(el("div", { class: "filtres kb-filtres" }, recherche,
      choix("Produit", "produit", Object.fromEntries(["claude-code", "claude", "codex", "chatgpt"].map((p) => [p, PRODUITS[p]]))),
      choix("Catégorie", "categorie", KB_CATEGORIES),
      choix("Verdict", "verdict", { ...VERDICTS, attente: "en attente de commentaire" }),
      choix("Statut d'usage", "statut", STATUTS),
      choix("Tri", "tri", { recent: "Ajoutées récemment" }, "Tri alphabétique"),
      choix("Date d'ajout", "depuis", { 7: "Ajoutées depuis 7 jours", 30: "Ajoutées depuis 30 jours" }, "Ajoutées : toutes")));
    frag.append(el("div", { id: "kb-resultats" }));
    return frag;
  }
  const ESSAIS_PAGE = 50;
  // carte d'un essai de la base : usage et exemple en code, pourquoi, date d'ajout, case « fait » (même stockage local que les actions)
  function carteEssai(e, surFait) {
    const faits = lireFaits();
    const id = String(e.id || "");
    const c = el("li", { class: "carte kb essai" + (faits[id] ? " fait" : "") });
    const verdict = VERDICTS[e.verdict] ? e.verdict : null;
    c.append(el("div", { class: "badges" },
      badge("produit", PRODUITS[e.produit] || String(e.produit || "?")),
      badge("type", KB_CATEGORIES[e.categorie] || String(e.categorie || "?")),
      verdict ? badge(`verdict ${verdict}`, VERDICTS[verdict]) : null));
    c.append(el("h4", { text: texte(e.nom, "(sans nom)") }));
    if (ISO_JOUR.test(e.date_ajout || "")) c.append(el("div", { class: "meta", text: `ajoutée le ${dateFr(e.date_ajout)}` }));
    if (texte(e.usage)) {
      c.append(el("div", { class: "etiquette", text: e.usage_nature === "etapes" ? "Accès" : "Syntaxe" }));
      c.append(el("pre", { class: "usage" + (e.usage_nature === "etapes" ? " etapes" : "") }, el("code", { text: String(e.usage) })));
    }
    if (texte(e.exemple) && e.exemple !== e.usage) c.append(el("pre", { class: "usage exemple" }, el("code", { text: e.exemple })));
    if (texte(e.pourquoi)) c.append(el("div", { class: "pour-toi" }, el("strong", { text: "Pourquoi" }), el("p", { text: e.pourquoi })));
    const caseFait = el("input", { type: "checkbox" });
    caseFait.checked = Boolean(faits[id]);
    caseFait.addEventListener("change", () => {
      ecrireFait(id, caseFait.checked); c.classList.toggle("fait", caseFait.checked);
      if (surFait) surFait();
    });
    c.append(el("div", { class: "action" }, el("label", null, caseFait, "Fait")));
    return c;
  }
  // section « Essais de la base » : tester d'abord, puis date d'ajout décroissante (ordre du fichier) ; les faits dans une section repliée
  function sectionEssais(doc) {
    const sec = el("section", { class: "essais-base" });
    const faits = lireFaits();
    const entrees = doc.entrees.filter((e) => e && typeof e === "object" && e.id);
    const ouverts = entrees.filter((e) => !faits[String(e.id)]);
    const faitsListe = entrees.filter((e) => faits[String(e.id)]);
    const surFait = () => rendre();
    sec.append(el("h3", { class: "compte-actions", text: `Essais de la base (${ouverts.length})` }),
      el("p", { class: "sous-titre", text: "Entrées de la base de référence au verdict « à tester », puis « à utiliser » pas encore utilisées. La case « fait » reste dans ce navigateur." }));
    if (doc.tronque === true) sec.append(el("p", { class: "doux", text: `Liste coupée : ${entrees.length} essais affichables sur ${doc.total}.` }));
    const ul = el("ul", { class: "liste" }, ...ouverts.slice(0, etat.essaisLimite).map((e) => carteEssai(e, surFait)));
    sec.append(ouverts.length ? ul : el("p", { class: "vide", text: "Aucun essai ouvert." }));
    if (ouverts.length > etat.essaisLimite) {
      const b = el("button", { type: "button", class: "plus", text: `Afficher ${Math.min(ESSAIS_PAGE, ouverts.length - etat.essaisLimite)} de plus` });
      b.addEventListener("click", () => { etat.essaisLimite += ESSAIS_PAGE; rendre(); });
      sec.append(b);
    }
    if (faitsListe.length) {
      const d = el("details", { class: "actions-faites" }, el("summary", { text: `Essais faits (${faitsListe.length})` }),
        el("ul", { class: "liste" }, ...faitsListe.map((e) => carteEssai(e, surFait))));
      d.open = etat.essaisFaitsOuverts === true;
      d.addEventListener("toggle", () => { etat.essaisFaitsOuverts = d.open; });
      sec.append(d);
    }
    return sec;
  }
  function pageATester() {
    const frag = document.createDocumentFragment();
    frag.append(el("h2", { text: "À tester" }), el("p", { class: "sous-titre", text: "Les actions proposées. La case « fait » n'est enregistrée que dans ce navigateur." }), noteFenetre());
    let liste = [];
    for (const p of PERIMETRES) liste = liste.concat(elementsDe(p, datesRecentes(p)).filter((e) => e.action && typeof e.action === "object"));
    // audit du 25/09 : les actions ouvertes d'abord, avec leur nombre ; les faites à part, dans une section repliée
    const faits = lireFaits();
    const ouvertes = liste.filter((e) => !faits[String(e.id || "")]).sort(triImpact);
    const faites = liste.filter((e) => faits[String(e.id || "")]).sort(triImpact);
    const surFait = () => rendre();  // une case cochée ou décochée fait passer l'action dans l'autre section
    frag.append(el("h3", { class: "compte-actions", text: `Actions ouvertes (${ouvertes.length})` }),
      listeCartes(ouvertes, { vide: "Aucune action ouverte.", surFait }));
    if (faites.length) {
      const d = el("details", { class: "actions-faites" }, el("summary", { text: `Actions faites (${faites.length})` }),
        listeCartes(faites, { surFait }));
      d.open = etat.faitesOuvertes === true;
      d.addEventListener("toggle", () => { etat.faitesOuvertes = d.open; });
      frag.append(d);
    }
    if (etat.kbATester && etat.kbATester.entrees.length) frag.append(sectionEssais(etat.kbATester));
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

  /* ---------- Semaine (D98) : bilan de la semaine ISO, champs recopiés par scripts/semaine.py ---------- */
  const RE_SEMAINE = /^\d{4}-W\d{2}$/;
  const SOURCES_SEMAINE = { claude: "Claude", actu: "Actu", openai: "OpenAI", "kb-claude": "Base Claude", "kb-openai": "Base OpenAI" };
  async function chargerSemaine() {
    const s = etat.semaines;
    if (s.index === undefined) {
      try {
        const idx = await lireJson("data/semaine/index.json");
        if (!idx || !Array.isArray(idx.semaines)) throw new Error("index sans `semaines`");
        s.index = idx.semaines.filter((x) => x && RE_SEMAINE.test(x.semaine));
      } catch (e) { s.index = null; s.erreur = String(e.message || e); }
    }
    if (!s.index || !s.index.length) return;
    s.courante = s.index.some((x) => x.semaine === etat.semaineDemandee) ? etat.semaineDemandee : s.index[0].semaine;
    if (!s.docs[s.courante]) {
      try {
        const d = await lireJson(`data/semaine/${s.courante}.json`);
        if (!d || !Array.isArray(d.elements) || !Array.isArray(d.d71) || !Array.isArray(d.base_ajoutees) || !Array.isArray(d.base_verdicts)) throw new Error("bilan illisible");
        s.docs[s.courante] = d;
      } catch (e) { s.docs[s.courante] = { erreur: String(e.message || e) }; }
    }
  }
  function ligneSemaine(l) {
    const c = el("li", { class: `ligne-semaine impact-${IMPACTS.includes(l.impact) ? l.impact : "nul"}` });
    c.append(el("div", { class: "badges" },
      badge(`impact ${IMPACTS.includes(l.impact) ? l.impact : "nul"}`, `impact ${l.impact || "?"}`),
      badge(`certitude ${l.certitude || ""}`, CERTITUDES[l.certitude] || String(l.certitude || "?")),
      badge("produit", PRODUITS[l.produit] || String(l.produit || "?"))));
    c.append(el("h4", { text: texte(l.titre, "(sans titre)") + (l.version ? ` ${l.version}` : "") }));
    c.append(el("div", { class: "meta" }, `${dateFr(l.date_publication)} · `,
      ISO_JOUR.test(l.jour || "") ? el("a", { href: `#archives/${l.jour}`, text: `passage du ${dateFr(l.jour)}` }) : "passage inconnu"));
    c.append(texte(l.action) ? el("p", { class: "action-courte" }, el("strong", { text: "Action : " }), ...enrichi(l.action, l.produit)) : el("p", { class: "action-courte doux", text: "Aucune action demandée." }));
    return c;
  }
  function ligneKbSemaine(l, quand) {
    const c = el("li", { class: "carte kb" });
    const verdict = l.verdict_apres || l.verdict;
    const badges = el("div", { class: "badges" }, badge("produit", PRODUITS[l.produit] || String(l.produit || "?")),
      badge("type", KB_CATEGORIES[l.categorie] || String(l.categorie || "?")),
      verdict ? badge(`verdict ${verdict}`, VERDICTS[verdict] || verdict) : badge("attente", "en attente de commentaire"));
    if (l.verdict_apres) badges.append(el("span", { class: "meta", text: l.verdict_avant ? `avant : ${VERDICTS[l.verdict_avant] || l.verdict_avant}` : "premier jugement" }));
    c.append(badges, el("h4", { text: texte(l.nom, "(sans nom)") }), el("div", { class: "meta", text: quand }));
    c.append(el("pre", { class: "usage" }, el("code", { text: String(l.usage || "") })));
    if (texte(l.exemple) && l.exemple !== l.usage) {
      c.append(el("div", { class: "etiquette", text: l.exemple_origine === "source" ? "Exemple (de la documentation)" : l.exemple_origine === "compose" ? "Exemple (composé pour ton usage)" : "Exemple" }));
      c.append(el("pre", { class: "usage exemple" }, el("code", { text: l.exemple })));
    }
    if (texte(l.pourquoi)) c.append(el("div", { class: "pour-toi" }, el("strong", { text: "Pourquoi" }), el("p", { text: l.pourquoi })));
    return c;
  }
  function blocSemaine(titre, lignes, fabrique, vide) {
    const b = el("section", { class: "bloc-semaine", "aria-label": titre }, el("h3", { text: `${titre} (${lignes.length})` }));
    b.append(lignes.length ? el("ul", { class: "liste" }, ...lignes.map(fabrique)) : el("p", { class: "vide", text: vide }));
    return b;
  }
  function pageSemaine() {
    const s = etat.semaines;
    const frag = document.createDocumentFragment();
    frag.append(el("h2", { text: "Semaine" }));
    if (s.index === null) {
      frag.append(el("p", { class: "erreur", text: `Bilans de semaine indisponibles : ${s.erreur}` }));
      return frag;
    }
    if (!s.index.length) {
      frag.append(el("p", { class: "vide", text: "Aucun bilan de semaine publié pour l'instant." }));
      return frag;
    }
    const choixSemaine = el("select", { "aria-label": "Semaine affichée" });
    for (const x of s.index) {
      choixSemaine.append(el("option", { value: x.semaine, selected: x.semaine === s.courante ? true : null, text: `${x.semaine} · du ${dateFr(x.du)} au ${dateFr(x.au)}` }));
    }
    choixSemaine.addEventListener("change", () => { location.hash = `#semaine/${choixSemaine.value}`; });
    frag.append(el("div", { class: "filtres" }, choixSemaine));
    const d = s.docs[s.courante];
    if (!d || d.erreur) {
      frag.append(el("p", { class: "erreur", text: `Bilan ${s.courante} indisponible : ${d ? d.erreur : "non chargé"}` }));
      return frag;
    }
    frag.append(el("p", { class: "sous-titre", text: `Du ${dateFr(d.du)} au ${dateFr(d.au)} · produit le ${horodatageFr(d.genere_le)} à partir des fichiers quotidiens et de la base, sans rédaction. Les éléments du jour d'OpenAI y figurent au bilan suivant.` }));
    if (d.statut !== "ok") frag.append(el("p", { class: "erreur", role: "status", text: `Bilan partiel (statut ${d.statut}) : ${texte(d.raison, "raison non indiquée")}` }));
    else {
      const jours = Object.entries(SOURCES_SEMAINE).filter(([k]) => d.sources && d.sources[k] && !k.startsWith("kb-")).map(([k, nom]) => `${nom} ${d.sources[k].jours.length} j`);
      frag.append(el("p", { class: "sous-titre doux", text: `Passages lus : ${jours.join(", ")}.` }));
    }
    frag.append(blocSemaine("Compte et quotas", d.d71, ligneSemaine, "Rien sur le compte, les quotas, les tarifs ou les forfaits cette semaine."));
    frag.append(blocSemaine("À retenir (impact fort ou moyen)", d.elements, ligneSemaine, "Aucun élément d'impact fort ou moyen cette semaine."));
    const utiles = d.base_ajoutees.filter((l) => l.verdict !== "ignorer");
    const ignorees = d.base_ajoutees.filter((l) => l.verdict === "ignorer");
    const bAjout = blocSemaine("Nouveau dans la base", utiles, (l) => ligneKbSemaine(l, `ajoutée le ${dateFr(l.date_ajout)}`), ignorees.length ? "Aucune entrée à utiliser ou à tester parmi les ajouts." : "Aucune entrée ajoutée cette semaine.");
    if (ignorees.length) {
      bAjout.append(el("details", { class: "ecartes" }, el("summary", { text: `${ignorees.length} entrée(s) ajoutée(s) jugée(s) à ignorer` }),
        el("ul", { class: "liste" }, ...ignorees.map((l) => ligneKbSemaine(l, `ajoutée le ${dateFr(l.date_ajout)}`)))));
    }
    frag.append(bAjout);
    frag.append(blocSemaine("Passées à utiliser ou à tester", d.base_verdicts, (l) => ligneKbSemaine(l, `verdict du ${dateFr(l.date)}`), "Aucune entrée de la base n'a changé de verdict vers utiliser ou tester cette semaine."));
    return frag;
  }

  /* ---------- routage par ancre ---------- */
  function lireRoute() {
    const h = (location.hash || "#aujourdhui").slice(1);
    const [chemin, requete] = h.split("?");
    const [page, param] = chemin.split("/");
    etat.page = ["aujourdhui", "semaine", "changelogs", "actu", "reference", "a-tester", "archives"].includes(page) ? page : "aujourdhui";
    etat.semaineDemandee = etat.page === "semaine" && RE_SEMAINE.test(param || "") ? param : null;
    etat.archiveDate = etat.page === "archives" && /^\d{4}-\d{2}-\d{2}$/.test(param || "") ? param : null;
    // #reference?recent=7 (ou 30) : vue des entrées ajoutées récemment, la plus récente d'abord
    const recent = etat.page === "reference" ? new URLSearchParams(requete || "").get("recent") : null;
    if (KB_JOURS_RECENTS.includes(recent)) { kbFiltre.depuis = recent; kbFiltre.tri = "recent"; kbFiltre.limite = KB_PAGE; }
    // D105 : #reference?id=<id> affiche la fiche seule ; #reference?q=<nom> ouvre la référence avec cette recherche, filtres remis à zéro
    const params = etat.page === "reference" ? new URLSearchParams(requete || "") : null;
    etat.kbFicheId = params && params.get("id") ? params.get("id") : null;
    const q = params ? (params.get("q") || "").trim() : "";
    if (q && !etat.kbFicheId) Object.assign(kbFiltre, { q, produit: "", categorie: "", verdict: "", statut: "", tri: "", depuis: "", limite: KB_PAGE });
  }
  async function rendre() {
    lireRoute();
    await Promise.all([chargerNecessaire(), etat.page === "reference" ? null : chargerNomsKb()]);
    if (etat.page === "reference") await chargerKb();
    if (etat.page === "a-tester") await chargerATesterKb();
    if (etat.page === "semaine") await chargerSemaine();
    if (etat.page === "aujourdhui") await Promise.all([chargerVersions(), chargerComptes()]);
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
      case "semaine": main.append(pageSemaine()); break;
      case "changelogs": main.append(pageChangelogs()); break;
      case "actu": main.append(pageActu()); break;
      case "reference": main.append(pageReference()); rendreResultatsKb(); break;
      case "a-tester": main.append(pageATester()); break;
      case "archives": main.append(pageArchives()); break;
      default: main.append(pageAujourdhui(alertes)); completerEncartKb();
    }
    document.title = `Delta — ${document.querySelector(".onglets a.actif")?.textContent || "veille IA"}`;
  }

  async function demarrer() {
    const avisConsole = enregistrerConsoleDepuisUrl();
    if (avisConsole) annoncer(avisConsole);
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
