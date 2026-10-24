/* Delta — application du site statique.
 * Lit docs/data/<perimetre>/index.json et les fichiers quotidiens (ancienne route), ou la génération commune
 * docs/commun/v1/<generation>/ (deux couches, lot L3) ; aucun build.
 * Langue : <html lang> (en à la racine, fr sous /fr/) ; textes d'interface dans docs/assets/textes.js, adresses publiques
 * dans docs/assets/config.js (copie générée du bootstrap). Les données ne sont pas traduites : elles s'affichent telles quelles.
 * Le widget externe X est chargé uniquement dans Actu IA, pour les posts intégrés.
 * Sécurité : tout texte issu des données passe par textContent ; les liens sont limités à http(s). */
(function () {
  "use strict";

  /* ---------- textes (L3) : langue de la page, dictionnaire de cette langue, adresses publiques ---------- */
  const LANGUE = document.documentElement.lang === "fr" ? "fr" : "en";
  // racine du site relative à la page : "" à la racine, "../" sous /fr/ ; toutes les lectures de données la préfixent
  const RACINE = document.documentElement.getAttribute("data-racine") || "";
  const TEXTES = (window.DELTA_TEXTES && window.DELTA_TEXTES[LANGUE]) || {};
  const CONFIG = window.DELTA_CONFIG || {};
  const LOCALE = LANGUE === "fr" ? "fr-CA" : "en-CA";
  // texte d'interface `cle`, `{nom}` remplacé par vars.nom ; une clé absente se voit (la clé elle-même) et se journalise
  function t(cle, vars) {
    let s = TEXTES[cle];
    if (typeof s !== "string") { console.error("delta:texte-manquant", cle); return cle; }
    if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (Object.prototype.hasOwnProperty.call(vars, k) ? String(vars[k]) : m));
    return s;
  }
  /* ---------- fin des textes ---------- */

  const PERIMETRES = ["claude", "openai", "actu"];
  const AGENTS = { "claude-code": "Claude Code", codex: "Codex" };
  const PRODUITS = { claude: "Claude", "claude-code": "Claude Code", chatgpt: "ChatGPT", codex: "Codex", actu: t("produit.actu") };
  const IMPACTS = ["fort", "moyen", "faible", "nul"];
  const TYPES = ["nouveaute", "amelioration", "correction", "changement_rupture", "depreciation", "actu"];
  const CERTITUDES = ["officiel", "rapporte", "non_confirme"];
  const ALERTE_HEURES = 36;
  const FENETRE_JOURS = 30; // D38 : Changelogs, Actu et À tester n'affichent que les 30 derniers jours ; au-delà, les Archives
  const CLE_FAITS = "delta.faits";
  const CLE_LANGUE = "delta.langue";

  const etat = { index: {}, jours: {}, page: "aujourdhui", filtreProduit: "tous", archiveDate: null, semaines: { index: undefined, docs: {}, courante: null, erreur: null }, semaineDemandee: null, essaisLimite: 50, recherche: undefined, rq: { q: "", limite: 50 }, noms: undefined, kbFicheId: null, rendu: 0, fenetre: null };
  const main = document.getElementById("contenu");

  /* ---------- couche lue (L3) : ancienne route `data/` par défaut, génération commune sur ?couche=commun ou quand l'ancienne
     route est illisible ; jamais de repli de la couche commune vers l'ancienne route (encore mixte) ---------- */
  const COUCHE = { demandee: new URLSearchParams(location.search).get("couche") === "commun", automatique: false, mode: "ancienne", generation: null, publie_le: null, erreur: null };
  const enCommun = () => COUCHE.mode === "commun";
  function chemin(rel) { return enCommun() ? `${RACINE}commun/v1/${COUCHE.generation}/${rel}` : `${RACINE}data/${rel}`; }

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
  // texte de données en français (ancienne route) dans une page anglaise : attribut lang pour les lecteurs d'écran
  const langueDonnees = () => (LANGUE === "fr" ? null : "fr");
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
    const t0 = typeof s === "string" ? s : String(s === null || s === undefined ? "" : s);
    // noms.json se lit après le premier affichage (m-e6c49a1336e3) : en attendant, le texte à segments est repris par `completerLiens`
    if (etat.noms === undefined && t0.includes("`")) return [el("span", { "data-enrichir": t0, "data-produit": typeof produit === "string" ? produit : null }, t0)];
    if (!etat.noms) return [t0];
    const out = [];
    let fin = 0;
    for (const m of t0.matchAll(RE_SEGMENT_CODE)) {
      const ids = idsDuProduit(idsDuNom(m[1]), produit);
      if (!ids.length) continue;
      if (m.index > fin) out.push(t0.slice(fin, m.index));
      out.push(el("a", {
        class: "ref-lien", href: ids.length === 1 ? `#reference?id=${encodeURIComponent(ids[0])}` : `#reference?q=${encodeURIComponent(m[1].trim())}`,
        title: ids.length === 1 ? t("lien.fiche") : t("lien.plusieurs", { n: ids.length }),
      }, el("code", { text: m[1] })));
      fin = m.index + m[0].length;
    }
    if (fin < t0.length) out.push(t0.slice(fin));
    return out;
  }
  // date AAAA-MM-JJ affichée : JJ/MM/AAAA en français, AAAA-MM-JJ en anglais
  function dateAffichee(iso) {
    if (typeof iso !== "string" || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return t("date.inconnue");
    const [a, m, j] = iso.slice(0, 10).split("-");
    return LANGUE === "fr" ? `${j}/${m}/${a}` : `${a}-${m}-${j}`;
  }
  function horodatage(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return t("date.inconnu");
    return d.toLocaleString(LOCALE, { dateStyle: "short", timeStyle: "short" });
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

  /* ---------- sélecteur de langue : même vue (recherche et ancre) dans l'autre langue, choix mémorisé sur l'appareil,
     aucune redirection (décision du 22/10) ---------- */
  function lireLangue() { try { return localStorage.getItem(CLE_LANGUE); } catch (e) { return null; } }
  function ecrireLangue(l) { try { localStorage.setItem(CLE_LANGUE, l); } catch (e) { /* sans stockage : le lien suffit */ } }
  function majLienLangue() {
    const a = document.getElementById("choix-langue");
    if (!a) return;
    a.setAttribute("href", `${a.getAttribute("data-base") || ""}${location.search || ""}${location.hash || ""}`);
  }
  function brancherLangue() {
    const a = document.getElementById("choix-langue");
    if (!a) return;
    const cible = a.getAttribute("hreflang");
    a.addEventListener("click", () => ecrireLangue(cible));
    // choix mémorisé (au clic seulement) différent de cette page : le lien est marqué, la page ne change pas d'elle-même
    if (lireLangue() === cible) a.classList.add("prefere");
    majLienLangue();
  }

  /* ---------- éléments d'impact nul : masqués par défaut, bascule mémorisée (sous try/catch) ---------- */
  const CLE_NUL = "delta.afficherNul";
  function lireAfficherNul() { try { return localStorage.getItem(CLE_NUL) === "1"; } catch (e) { return false; } }
  function ecrireAfficherNul(v) { try { localStorage.setItem(CLE_NUL, v ? "1" : "0"); } catch (e) { /* sans stockage : pour cette page seulement */ } }
  etat.afficherNul = lireAfficherNul();
  // seul l'impact `nul` déclaré est masqué : un impact inconnu (null, couche commune ou vue compatible) reste affiché
  function sansNul(elements) { return etat.afficherNul ? elements : elements.filter((e) => e.impact !== "nul"); }
  function basculeNul(elements) {
    const n = elements.filter((e) => e.impact === "nul").length;
    if (!n) return null;
    const b = el("button", { type: "button", class: "bascule-nul", "aria-pressed": String(etat.afficherNul),
      text: t(etat.afficherNul ? "nul.masquer" : "nul.afficher", { n }) });
    b.addEventListener("click", () => { etat.afficherNul = !etat.afficherNul; ecrireAfficherNul(etat.afficherNul); rendre(); });
    return el("div", { class: "filtres" }, b);
  }

  /* ---------- adaptateurs de format (L3) : ancienne route et génération commune vers les formes lues par les pages.
     Fonctions pures (aucun DOM, aucune requête) ; un schéma ou une version majeure inconnus sont refusés, jamais lus au jugé. ---------- */
  const SCHEMA_COMMUN = "delta.commun";
  const SCHEMA_MANIFESTE = "delta.manifest";
  const RE_GENERATION = /^g-[0-9a-f]{16}$/;
  // un document de la nouvelle forme porte un schéma ; l'ancienne route n'en a pas
  const aSchema = (doc) => Boolean(doc) && typeof doc === "object" && !Array.isArray(doc) && typeof doc.schema === "string";
  function verifierSchema(doc, schema, quoi) {
    if (!aSchema(doc)) throw new Error(t("erreur.format", { quoi }));
    if (doc.schema !== schema) throw new Error(t("erreur.schema", { quoi, schema: String(doc.schema) }));
    if (doc.schema_version !== 1) throw new Error(t("erreur.schema_version", { quoi, schema, version: String(doc.schema_version) }));
    return doc;
  }
  // commun/v1/index.json : génération servie et heure de publication
  function adapterPublication(doc) {
    verifierSchema(doc, SCHEMA_MANIFESTE, "commun/v1/index.json");
    if (doc.vue !== "publication" || !RE_GENERATION.test(String(doc.generation || ""))) throw new Error(t("erreur.format", { quoi: "commun/v1/index.json" }));
    return { generation: doc.generation, publie_le: typeof doc.publie_le === "string" ? doc.publie_le : null };
  }
  function adapterManifeste(doc, generation) {
    verifierSchema(doc, SCHEMA_MANIFESTE, "manifest.json");
    if (doc.generation !== generation || !Array.isArray(doc.fichiers)) throw new Error(t("erreur.format", { quoi: "manifest.json" }));
    const requis = Array.isArray(doc.schemas_requis) ? doc.schemas_requis : [];
    const inconnu = requis.find((s) => s !== `${SCHEMA_COMMUN}@1`);
    if (inconnu) throw new Error(t("erreur.schema_requis", { schema: String(inconnu) }));
    return { langues: Array.isArray(doc.langues) ? doc.langues : [] };
  }
  // veille/<p>.json : une entrée par nouveauté, ses publications datées ; aucun titre, résumé ni impact (couche commune)
  function adapterVeille(doc, p) {
    verifierSchema(doc, SCHEMA_COMMUN, `veille/${p}.json`);
    if (doc.famille !== "veille" || !Array.isArray(doc.entrees) || !Array.isArray(doc.jours)) throw new Error(t("erreur.format", { quoi: `veille/${p}.json` }));
    const jours = {}, agents = {};
    const iso = /^\d{4}-\d{2}-\d{2}$/;
    const datesIndex = doc.jours.filter((j) => j && iso.test(j.date || "")).map((j) => ({ date: j.date, genere_le: j.genere_le ?? null }));
    for (const j of datesIndex) jours[j.date] = { elements: [], synthese: null, sources_en_echec: [], ecartes: [], commun: true };
    for (const e of doc.entrees) {
      if (!e || typeof e !== "object" || !Array.isArray(e.publications)) continue;
      for (const pub of e.publications) {
        if (!pub || !iso.test(pub.jour || "")) continue;
        if (!jours[pub.jour]) { jours[pub.jour] = { elements: [], synthese: null, sources_en_echec: [], ecartes: [], commun: true }; datesIndex.push({ date: pub.jour, genere_le: null }); }
        if (typeof pub.agent === "string") agents[pub.agent] = (agents[pub.agent] || 0) + 1;
        jours[pub.jour].elements.push({ id: e.id, identite: e.identite ?? null, produit: pub.produit ?? null, version: pub.version ?? null,
          type: pub.type ?? null, certitude: pub.certitude ?? null, date_publication: pub.date_publication ?? null,
          revision: pub.revision === true, kb_refs: Array.isArray(pub.kb_refs) ? pub.kb_refs : [], sources: Array.isArray(pub.sources) ? pub.sources : [],
          titre: null, resume: null, impact: null, pour_toi: null, action: null });
      }
    }
    const agent = Object.entries(agents).sort((a, b) => b[1] - a[1])[0];
    return { index: { perimetre: p, agent: agent ? agent[0] : null, maj_le: doc.maj_le ?? null, jours: datesIndex, commun: true }, jours };
  }
  // titre affiché d'un élément : son titre ; à défaut (couche commune), le produit (sa version suit) ou le libellé de la première source
  function titreElement(e) {
    if (texte(e.titre)) return e.titre;
    if (e.version && PRODUITS[e.produit]) return PRODUITS[e.produit];
    const s = Array.isArray(e.sources) ? e.sources.find((x) => x && texte(x.libelle)) : null;
    return s ? s.libelle : (PRODUITS[e.produit] || t("carte.sans_titre"));
  }
  // versions.json : ancienne route (tableau, version installée relevée) ou commune (dernières versions publiées seules)
  function adapterVersions(doc) {
    if (Array.isArray(doc)) {
      return { installees: true, lignes: doc.filter((l) => l && typeof l === "object").map((l) => ({ outil: l.outil, version: l.version ?? null,
        derniere_publiee: l.derniere_publiee ?? null, detectee_le: l.detectee_le ?? null, note: [texte(l.raison), texte(l.note)].filter(Boolean).join(" "),
        // sans version installée (vue compatible), aucune comparaison : statut inconnu
        statut: l.version ? l.statut : "inconnu" })) };
    }
    verifierSchema(doc, SCHEMA_COMMUN, "versions.json");
    if (doc.famille !== "versions" || !Array.isArray(doc.entrees)) throw new Error(t("erreur.format", { quoi: "versions.json" }));
    return { installees: false, lignes: doc.entrees.filter((l) => l && typeof l === "object").map((l) => ({ outil: l.outil, version: null,
      derniere_publiee: l.derniere_publiee ?? null, detectee_le: null, note: "", statut: "inconnu" })) };
  }
  // kb/noms.json : map plate (ancienne route) ou { schema, noms } (commune)
  function adapterNoms(doc) {
    if (aSchema(doc)) {
      verifierSchema(doc, SCHEMA_COMMUN, "kb/noms.json");
      if (!doc.noms || typeof doc.noms !== "object" || Array.isArray(doc.noms)) throw new Error(t("erreur.format", { quoi: "kb/noms.json" }));
      return doc.noms;
    }
    if (!doc || typeof doc !== "object" || Array.isArray(doc)) throw new Error(t("erreur.format", { quoi: "kb/noms.json" }));
    return doc;
  }
  // fichier de la base : ancienne route (`entrees`) ou commune (schéma vérifié, `entrees`)
  function adapterKb(doc, quoi) {
    if (aSchema(doc)) verifierSchema(doc, SCHEMA_COMMUN, quoi);
    if (!doc || !Array.isArray(doc.entrees)) throw new Error(t("erreur.sans_entrees"));
    return doc.entrees;
  }
  // description d'une fiche dans la langue de la page : textes bilingues (L2) d'abord, repli anglais annoncé ;
  // sans textes, l'ancienne route : description commentée (française) ou description d'origine (anglaise)
  function descriptionKb(e) {
    const d = e && e.textes && e.textes.description;
    if (d && typeof d === "object") {
      const ici = d[LANGUE] && texte(d[LANGUE].texte) ? d[LANGUE] : null;
      const en = d.en && texte(d.en.texte) ? d.en : null;
      const choisi = ici || en;
      if (choisi) return { texte: choisi.texte, langue: ici ? LANGUE : "en", repli: !ici, statut: choisi.statut ?? null };
    }
    if (e && e.commentee && texte(e.description)) return { texte: e.description, langue: "fr", repli: false, statut: "commentee" };
    if (e && texte(e.description_source)) return { texte: e.description_source, langue: "en", repli: LANGUE !== "en", statut: "source" };
    return null;
  }
  // texte de recherche d'une fiche : toutes ses descriptions, des deux langues
  function texteRechercheKb(e) {
    const d = e && e.textes && e.textes.description && typeof e.textes.description === "object" ? Object.values(e.textes.description).map((x) => x && x.texte) : [];
    return [e.nom, e.description, e.description_source, ...d, e.usage, e.groupe, e.recommandation && e.recommandation.pourquoi].join(" ");
  }
  /* ---------- fin des adaptateurs ---------- */

  /* ---------- chargement des données ---------- */
  /* m-e6c49a1336e3 : Aujourd'hui ne lit que les index, le dernier jour de chaque périmètre, etat.json et versions.json ; les 30 jours des
     trois périmètres (`chargerFenetre`) se lisent ensuite en arrière-plan pour Changelogs, Actu et À tester, qui attendent avec un indicateur.
     Chaque fichier n'est demandé qu'une fois : les lectures mémorisent leur promesse (`unefois`), même si l'on change d'onglet pendant le fond. */
  const lectures = new Map();
  function unefois(cle, lire) { if (!lectures.has(cle)) lectures.set(cle, lire()); return lectures.get(cle); }
  async function lireJson(url) {
    const r = await fetch(url, { cache: "no-cache" });
    if (!r.ok) throw new Error(t("erreur.http", { chemin: url, statut: r.status }));
    return r.json();
  }
  async function chargerIndexAncien() {
    await Promise.all(PERIMETRES.map(async (p) => {
      try {
        const idx = await lireJson(chemin(`${p}/index.json`));
        if (!idx || !Array.isArray(idx.jours)) throw new Error(t("erreur.index_sans_jours"));
        etat.index[p] = idx;
      } catch (e) { etat.index[p] = { erreur: String(e.message || e), jours: [] }; }
    }));
  }
  // génération commune : index de publication, manifeste, puis la veille des trois périmètres (une erreur reste celle de sa couche)
  async function chargerCommun() {
    COUCHE.mode = "commun";
    try {
      const pub = adapterPublication(await lireJson(`${RACINE}commun/v1/index.json`));
      COUCHE.generation = pub.generation;
      COUCHE.publie_le = pub.publie_le;
      adapterManifeste(await lireJson(chemin("manifest.json")), pub.generation);
    } catch (e) {
      COUCHE.erreur = String(e.message || e);
      for (const p of PERIMETRES) etat.index[p] = { erreur: COUCHE.erreur, jours: [] };
      return;
    }
    await Promise.all(PERIMETRES.map(async (p) => {
      try {
        const v = adapterVeille(await lireJson(chemin(`veille/${p}.json`)), p);
        etat.index[p] = v.index;
        for (const [d, q] of Object.entries(v.jours)) etat.jours[`${p}/${d}`] = q;
      } catch (e) { etat.index[p] = { erreur: String(e.message || e), jours: [] }; }
    }));
  }
  async function chargerIndex() {
    if (!COUCHE.demandee) {
      await chargerIndexAncien();
      if (PERIMETRES.some((p) => !etat.index[p].erreur)) return;
      // aucun index de l'ancienne route : la référence commune prend le relais (jamais l'inverse) ; ce qui a pu partir avant
      // (etat.json, versions.json de l'ancienne route) est oublié
      COUCHE.automatique = true;
      COUCHE.erreurAncienne = etat.index[PERIMETRES[0]].erreur;
      for (const cle of ["comptes", "versions"]) lectures.delete(cle);
      etat.comptes = undefined; etat.versions = undefined;
    }
    etat.index = {};
    await chargerCommun();
  }
  function chargerJour(p, date) {
    const cle = `${p}/${date}`;
    if (enCommun()) return Promise.resolve(etat.jours[cle] || { erreur: t("erreur.jour_absent"), elements: [], ecartes: [] });
    return unefois(`jour:${cle}`, async () => {
      try {
        const q = await lireJson(chemin(`${p}/${date}.json`));
        etat.jours[cle] = q && Array.isArray(q.elements) ? q : { erreur: t("erreur.jour_illisible"), elements: [], ecartes: [] };
      } catch (e) { etat.jours[cle] = { erreur: String(e.message || e), elements: [], ecartes: [] }; }
      return etat.jours[cle];
    });
  }
  function datesDe(p) { return (etat.index[p]?.jours || []).map((j) => j.date).filter((d) => typeof d === "string").sort().reverse(); }
  function derniereDate(p) { return datesDe(p)[0] || null; }
  function datesRecentes(p) {
    const limite = new Date(Date.now() - FENETRE_JOURS * 864e5).toISOString().slice(0, 10);
    return datesDe(p).filter((d) => d >= limite);
  }
  function noteFenetre() {
    return el("p", { class: "sous-titre" }, t("fenetre.note_debut", { n: FENETRE_JOURS }), el("a", { href: "#archives", text: t("onglet.archives") }), t("fenetre.note_fin"));
  }
  // Aujourd'hui : le dernier jour publié de chaque périmètre
  async function chargerDernierJour() {
    await Promise.all(PERIMETRES.map((p) => { const d = derniereDate(p); return d ? chargerJour(p, d) : null; }));
  }
  // Archives : les fichiers de la date demandée
  async function chargerJoursArchive() {
    await Promise.all(PERIMETRES.map((p) => (datesDe(p).includes(etat.archiveDate) ? chargerJour(p, etat.archiveDate) : null)));
  }
  // les 30 derniers jours des trois périmètres, du plus récent au plus ancien, quelques fichiers à la fois ; une seule fois par page
  const FOND_PARALLELE = 4;
  const PAGES_FENETRE = { changelogs: "onglet.changelogs", actu: "onglet.actu", "a-tester": "onglet.a_tester" };
  function texteAvancementFenetre(f) { return t("fenetre.chargement", { n: FENETRE_JOURS, faits: f.faits, total: f.total }); }
  function chargerFenetre() {
    if (etat.fenetre) return etat.fenetre;
    const taches = PERIMETRES.flatMap((p) => datesRecentes(p).map((d) => [p, d])).sort((a, b) => b[1].localeCompare(a[1]));
    const f = { total: taches.length, faits: 0, fini: false, termine: null };
    const travailleur = async () => {
      while (taches.length) {
        const [p, d] = taches.shift();
        await chargerJour(p, d);
        f.faits += 1;
        const zone = document.getElementById("fenetre-avancement");
        if (zone) zone.textContent = texteAvancementFenetre(f);
      }
    };
    f.termine = Promise.all(Array.from({ length: Math.min(FOND_PARALLELE, taches.length) }, travailleur)).then(() => { f.fini = true; });
    etat.fenetre = f;
    return f;
  }
  function pageAttenteFenetre(f) {
    const frag = document.createDocumentFragment();
    frag.append(el("h2", { text: t(PAGES_FENETRE[etat.page]) }),
      el("p", { id: "fenetre-avancement", class: "sous-titre", role: "status", "aria-busy": "true", text: texteAvancementFenetre(f) }));
    return frag;
  }
  // après le premier affichage : l'index des noms puis les 30 jours ; la Référence garde sa bande passante (D106)
  function lancerFond() {
    if (etat.page === "reference") return;
    chargerNomsKb().then(completerLiens).catch((err) => console.error("delta:noms", err));
    chargerFenetre();
  }
  // texte rendu avant l'arrivée de noms.json → liens de la base une fois l'index lu (ou texte simple s'il est illisible)
  function completerLiens() {
    for (const s of main.querySelectorAll("span[data-enrichir]")) s.replaceWith(...enrichi(s.getAttribute("data-enrichir"), s.getAttribute("data-produit") || undefined));
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
      const t0 = new Date(idx.maj_le || "");
      if (Number.isNaN(t0.getTime())) continue;
      // un agent à plusieurs périmètres (Claude Code : claude et actu) prend le passage le plus ANCIEN,
      // pour qu'un périmètre qui n'a pas tourné ne soit pas masqué par l'autre (audit du 25/09)
      if (!parAgent[idx.agent] || t0 < parAgent[idx.agent]) parAgent[idx.agent] = t0;
    }
    const alertes = [];
    for (const agent of Object.keys(AGENTS)) {
      const t0 = parAgent[agent];
      const heures = t0 ? (Date.now() - t0.getTime()) / 36e5 : Infinity;
      // D36, D53 : vert jusqu'à 24 h, orange de 24 à 36 h, rouge au-delà de 36 h
      const couleur = heures > ALERTE_HEURES ? "rouge" : heures > 24 ? "orange" : "vert";
      const quand = t0 ? horodatage(t0.toISOString()) : t("agent.aucun_passage");
      zone.append(el("span", { class: `agent ${couleur}`, title: t0 ? t("agent.dernier", { h: Math.floor(heures) }) : t("agent.aucun") },
        el("span", { class: "point", "aria-hidden": "true" }), el("strong", { text: AGENTS[agent] }), ` ${quand}`,
        couleur === "rouge" ? el("span", { class: "saut", text: t("agent.en_retard") }) : null));
      if (couleur === "rouge") alertes.push(t0 ? t("agent.alerte", { agent: AGENTS[agent], h: Math.floor(heures) }) : t("agent.jamais", { agent: AGENTS[agent] }));
    }
    return alertes;
  }
  // une ligne discrète dans le pied : couche lue, génération et date ; lien vers l'autre couche
  function rendreCouche() {
    const zone = document.getElementById("couche-lue");
    if (!zone) return;
    vider(zone);
    if (enCommun()) {
      zone.append(COUCHE.generation
        ? t("couche.commun", { generation: COUCHE.generation, date: COUCHE.publie_le ? horodatage(COUCHE.publie_le) : t("date.inconnue") })
        : t("couche.commun_sans_generation"));
      if (COUCHE.automatique) zone.append(" ", t("couche.automatique"));
      if (COUCHE.demandee) zone.append(" ", el("a", { href: `${location.pathname}${location.hash || ""}`, text: t("couche.vers_ancienne") }));
    } else {
      zone.append(t("couche.ancienne"), " ", el("a", { href: `?couche=commun${location.hash || ""}`, text: t("couche.vers_commun") }));
    }
  }

  /* ---------- Compte et quotas : etat.json > comptes (D93, D71) ; couche personnelle, jamais lue sur la référence commune ---------- */
  const QUOTAS_AFFICHES = [
    ["claude_session_5h", "quota.claude_session_5h", false], ["claude_semaine", "quota.claude_semaine", true],
    ["claude_semaine_fable", "quota.claude_semaine_fable", true], ["chatgpt_semaine", "quota.chatgpt_semaine", true]];
  const SEUIL_ALERTE_PCT = 80;
  const ANCIEN_MIN = 30;  // D120 : un relevé de plus de 30 min s'affiche « ancien » (même seuil que `fraicheur.ancien_min` d'OBSERVATORY)
  async function chargerComptes() {
    return unefois("comptes", async () => {
      if (enCommun()) { etat.comptes = null; return; }
      try {
        const e = await lireJson(chemin("etat.json"));
        etat.comptes = e && typeof e.comptes === "object" && e.comptes ? e.comptes : null;
      } catch (err) { etat.comptes = null; }
    });
  }
  function jjmmHhmm(iso) {
    const d = new Date(iso);
    if (typeof iso !== "string" || Number.isNaN(d.getTime())) return null;
    const z = (n) => String(n).padStart(2, "0");
    return t("date.jour_heure", { j: z(d.getDate()), m: z(d.getMonth() + 1), h: z(d.getHours()), min: z(d.getMinutes()) });
  }
  function age(iso, maintenant) {
    const ms = maintenant - new Date(iso).getTime();
    if (typeof iso !== "string" || Number.isNaN(ms)) return null;
    const min = Math.max(0, Math.round(ms / 60000));
    if (min < 60) return t("age.min", { n: min });
    if (min < 2880) return t("age.h", { n: Math.round(min / 60) });
    return t("age.j", { n: Math.round(min / 1440) });
  }
  function blocComptes(maintenant) {
    const c = etat.comptes;
    if (enCommun() || !c || typeof c !== "object") return null;
    const sec = el("section", { class: "comptes", "aria-label": t("comptes.titre") }, el("h3", { text: t("comptes.titre_haut") }));
    if (c.statut !== "ok" || !c.quotas || typeof c.quotas !== "object") {
      sec.append(el("p", { class: "pied-comptes", text: texte(c.raison) ? t("comptes.inconnus_raison", { raison: c.raison }) : t("comptes.inconnus") }));
      return sec;
    }
    let alerte = false;
    const liste = el("ul", { class: "quotas" });
    for (const [cle, libelleCle, hebdo] of QUOTAS_AFFICHES) {
      const q = c.quotas[cle];
      if (!q || typeof q !== "object") continue;
      const libelle = t(libelleCle);
      const connu = Number.isInteger(q.pct) && q.pct >= 0 && q.pct <= 100;
      const rz = jjmmHhmm(q.remise_a_zero);
      const perimee = rz !== null && new Date(q.remise_a_zero).getTime() < maintenant;
      const fort = connu && hebdo && q.pct > SEUIL_ALERTE_PCT && !perimee;
      const tRel = typeof q.releve_le === "string" ? new Date(q.releve_le).getTime() : NaN;
      const relevable = !Number.isNaN(tRel);
      const ancien = !relevable || maintenant - tRel > ANCIEN_MIN * 60000;
      const quand = relevable ? t("quota.releve", { quand: jjmmHhmm(q.releve_le), age: age(q.releve_le, maintenant) }) : t("quota.releve_inconnu");
      if (fort) alerte = true;
      const barre = el("div", { class: "barre", role: "progressbar", "aria-label": libelle, "aria-valuemin": "0", "aria-valuemax": "100",
        "aria-valuenow": connu ? String(q.pct) : null }, el("span", { style: `width:${connu ? q.pct : 0}%` }));
      const detail = (perimee ? t("quota.rz_passee", { rz }) : rz ? t("quota.rz", { rz }) : t("quota.rz_inconnue")) + ` · ${quand}${ancien ? ` · ${t("quota.ancien")}` : ""}`;
      liste.append(el("li", { class: "quota" + (fort ? " alerte" : "") + (perimee ? " perimee" : "") + (ancien ? " ancien" : "") },
        el("span", { class: "quota-nom", text: libelle }),
        el("span", { class: "quota-pct", text: connu ? `${q.pct} %` : t("quota.inconnu") }),
        barre,
        el("span", { class: "quota-rz", text: connu ? detail : texte(q.raison, t("quota.absente")) })));
    }
    sec.append(liste);
    if (alerte) sec.append(el("p", { class: "alerte-d71", role: "status", text: t("quota.alerte_d71", { seuil: SEUIL_ALERTE_PCT }) }));
    const releve = jjmmHhmm(c.releve_le);
    sec.append(el("p", { class: "pied-comptes", text: releve ? t("comptes.releve", { quand: releve, age: age(c.releve_le, maintenant) }) : t("comptes.releve_inconnu") }));
    return sec;
  }

  /* ---------- Tes outils : versions installées (D54 à D56) ; dernières versions publiées seules sur la référence commune ---------- */
  const STATUTS_VERSION = ["a_jour", "en_retard", "inconnu", "embarque", "non_utilise"];
  async function chargerVersions() {
    return unefois("versions", async () => {
      try { etat.versions = adapterVersions(await lireJson(chemin("versions.json"))); }
      catch (e) { etat.versions = null; }
    });
  }
  function blocOutils() {
    const v = etat.versions;
    if (!v || !v.lignes.length) return null;
    const corps = el("tbody");
    for (const l of v.lignes) {
      const statut = STATUTS_VERSION.includes(l.statut) ? l.statut : "inconnu";
      corps.append(el("tr", { class: l.note ? "avec-note" : null },
        el("td", { text: texte(l.outil, "?") }),
        el("td", { class: "v", text: l.version ? String(l.version) : t("outils.inconnue") }),
        el("td", { class: "v col-derniere", text: l.derniere_publiee ? String(l.derniere_publiee) : "—" }),
        el("td", null, el("span", { class: `statut ${statut}` }, el("span", { class: "point", "aria-hidden": "true" }), t(`version.${statut}`)))));
      if (l.note) corps.append(el("tr", { class: "ligne-note" }, el("td", { colspan: "4", text: l.note, lang: langueDonnees() })));
    }
    const date = v.lignes.map((l) => l.detectee_le).filter(Boolean).sort().pop();
    const titre = v.installees ? t("outils.titre") : t("outils.titre_publiees");
    return el("section", { class: "outils", "aria-label": titre },
      el("h3", { text: titre.toUpperCase() }),
      el("table", null,
        el("thead", null, el("tr", null, el("th", { text: t("outils.outil") }), el("th", { text: t("outils.installee") }),
          el("th", { class: "col-derniere", text: t("outils.derniere") }), el("th", { text: t("outils.statut") }))),
        corps),
      el("p", { class: "pied-outils", text: v.installees ? t("outils.pied", { quand: date ? horodatage(date) : "?" }) : t("outils.pied_commun") }));
  }

  /* ---------- rendu d'un élément ---------- */
  function badge(classe, libelle) { return el("span", { class: `badge ${classe}`, text: libelle }); }
  // impact personnel déclaré, sinon null : aucun badge ni classe fabriqués quand il manque (couche commune, vue compatible)
  const impactDe = (e) => (IMPACTS.includes(e.impact) ? e.impact : null);
  function carte(e, options) {
    options = options || {};
    const faits = lireFaits();
    const impact = impactDe(e);
    const c = el("li", { class: `carte impact-${impact || "inconnu"}` + (faits[e.id] ? " fait" : "") });
    const badges = el("div", { class: "badges" },
      impact ? badge(`impact ${impact}`, t(`impact.${impact}`)) : null,
      badge(`certitude ${e.certitude || ""}`, CERTITUDES.includes(e.certitude) ? t(`certitude.${e.certitude}`) : String(e.certitude || "?")),
      badge("produit", PRODUITS[e.produit] || String(e.produit || "?")),
      e.type ? badge("type", TYPES.includes(e.type) ? t(`type.${e.type}`) : String(e.type)) : null,
      e.revision === true ? badge("revise", t("carte.revise")) : null);
    c.append(badges);
    const titre = titreElement(e) + (e.version ? ` ${e.version}` : "");
    c.append(el(options.niveau === 4 ? "h4" : "h3", { text: titre, lang: texte(e.titre) ? langueDonnees() : null }));
    c.append(el("div", { class: "meta", text: t("carte.meta", { publication: dateAffichee(e.date_publication), passage: dateAffichee(e._jour) }) }));
    if (texte(e.resume)) c.append(el("p", { class: "resume", lang: langueDonnees() }, ...enrichi(e.resume, e.produit)));
    if (texte(e.pour_toi)) c.append(el("div", { class: "pour-toi" }, el("strong", { text: t("carte.pour_toi") }), el("p", { lang: langueDonnees() }, ...enrichi(e.pour_toi, e.produit))));
    if (e.action && typeof e.action === "object") {
      const a = el("div", { class: "action" }, el("strong", { text: t("carte.action") }),
        e.action.effort ? el("span", { class: "effort", text: t("carte.effort", { effort: e.action.effort }) }) : null,
        texte(e.action.description) ? el("p", { lang: langueDonnees() }, ...enrichi(e.action.description, e.produit)) : null);
      if (Array.isArray(e.action.etapes) && e.action.etapes.length) {
        a.append(el("ol", { lang: langueDonnees() }, ...e.action.etapes.map((s) => el("li", null, ...enrichi(s, e.produit)))));
      }
      const id = String(e.id || "");
      const caseFait = el("input", { type: "checkbox" });
      caseFait.checked = Boolean(faits[id]);
      caseFait.addEventListener("change", () => {
        ecrireFait(id, caseFait.checked); c.classList.toggle("fait", caseFait.checked);
        if (options.surFait) options.surFait();
      });
      a.append(el("label", null, caseFait, t("carte.fait")));
      c.append(a);
    }
    if (Array.isArray(e.projets_concernes) && e.projets_concernes.length) {
      c.append(el("p", { class: "projets", text: t("carte.projets", { liste: e.projets_concernes.map(String).join(", ") }) }));
    }
    if (Array.isArray(e.sources) && e.sources.length) {
      c.append(el("ul", { class: "sources", "aria-label": t("carte.sources") }, ...e.sources.map((s) =>
        el("li", { class: s && s.officielle === true ? "off" : null, title: s && s.officielle === true ? t("carte.source_officielle") : t("carte.source_tierce") },
          lienSur(s && s.url, texte(s && s.libelle, s && s.url))))));
    }
    return c;
  }
  function listeCartes(elements, options) {
    if (!elements.length) return el("p", { class: "vide", text: (options && options.vide) || t("liste.vide") });
    return el("ul", { class: "liste" + ((options && options.colonnes) ? " deux-colonnes" : "") }, ...elements.map((e) => carte(e, options)));
  }
  function blocSynthese(p, q, date) {
    const idx = etat.index[p] || {};
    const b = el("section", { class: "synthese" },
      el("h3", null, t(`perimetre.${p}`), el("span", { class: "meta", text: `${AGENTS[idx.agent] || idx.agent || ""} · ${dateAffichee(date)}` })));
    if (!q || q.erreur) b.append(el("p", { class: "erreur", text: q ? t("synthese.indisponible", { raison: q.erreur }) : t("synthese.aucun_passage") }));
    else {
      if (q.commun) b.append(el("p", { class: "doux", text: t("synthese.commun_absente", { n: q.elements.length }) }));
      else b.append(el("p", { lang: texte(q.synthese) ? langueDonnees() : null, text: texte(q.synthese, t("synthese.absente")) }));
      if (Array.isArray(q.sources_en_echec) && q.sources_en_echec.length) {
        b.append(el("p", { class: "echecs", text: t("synthese.echecs", { liste: q.sources_en_echec.map((s) => `${s.id}${s.partiel ? ` (${t("synthese.partiel")})` : ""}`).join(", ") }) }));
      }
    }
    return b;
  }
  function blocEcartes(quotidiens) {
    const tous = [];
    for (const q of quotidiens) if (q && Array.isArray(q.ecartes)) tous.push(...q.ecartes);
    if (!tous.length) return null;
    return el("details", { class: "ecartes" }, el("summary", { text: t("ecartes.resume", { n: tous.length }) }),
      el("ul", { lang: langueDonnees() }, ...tous.map((x) => el("li", { text: `${texte(x && x.raison, t("ecartes.sans_raison"))} — ${texte(x && x.id, "?")}` }))));
  }
  function filtresProduit(elements, surChangement) {
    const presents = [...new Set(elements.map((e) => e.produit).filter((p) => PRODUITS[p]))];
    if (presents.length < 2) return null;
    const f = el("div", { class: "filtres", role: "group", "aria-label": t("filtre.produit") });
    for (const p of ["tous", ...presents]) {
      const b = el("button", { type: "button", "aria-pressed": String(etat.filtreProduit === p), text: p === "tous" ? t("filtre.tous") : PRODUITS[p] });
      b.addEventListener("click", () => { etat.filtreProduit = p; surChangement(); });
      f.append(b);
    }
    return f;
  }
  const filtrer = (elements) => etat.filtreProduit === "tous" ? elements : elements.filter((e) => e.produit === etat.filtreProduit);
  // note d'une couche personnelle absente : une ligne, sans erreur
  function notePersonnel(cle) { return el("p", { class: "vide doux", role: "note", text: t(cle) }); }

  /* ---------- pages ---------- */
  // Une seule requête de script, même après navigation et reconstruction du bloc.
  let widgetsX;
  function chargerWidgetsX() {
    if (!widgetsX) widgetsX = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://platform.twitter.com/widgets.js";
      script.async = true;
      script.onload = () => resolve(window.twttr);
      script.onerror = reject;
      document.head.append(script);
    });
    return widgetsX;
  }
  function blocMurX() {
    const comptes = ["AnthropicAI", "claudeai", "ClaudeDevs", "OpenAI", "ChatGPT", "OpenAIDevs"];
    return el("section", { class: "liste-x", id: "mur-x" },
      el("h3", { text: t("x.titre") }),
      el("p", null, lienSur("https://x.com/i/lists/2113336377958084762", t("x.liste"))),
      el("ul", { class: "sources", "aria-label": t("x.comptes") },
        ...comptes.map((compte) => el("li", null, lienSur(`https://x.com/${compte}`, `@${compte}`)))),
      el("div", { class: "mur-x-posts", "aria-label": t("x.posts") },
        el("p", { text: t("x.chargement") })));
  }
  async function completerMurX() {
    const section = document.getElementById("mur-x");
    if (!section || etat.page !== "actu") return;
    const conteneur = section.querySelector(".mur-x-posts");
    let ids = [];
    // le relevé des posts n'appartient qu'à l'ancienne route : la référence commune ne le publie pas
    if (!enCommun()) try {
      const r = await fetch(chemin("actu/x-ids.json"), { cache: "no-cache" });
      if (!r.ok) throw new Error("x-ids");
      const d = await r.json();
      if (d && Array.isArray(d.ids)) ids = [...new Set(d.ids.filter((id) => typeof id === "string" && /^[0-9]{1,25}$/.test(id)))].slice(0, 30);
    } catch (_) { /* Fichier absent ou illisible : les liens restent disponibles. */ }
    // Un changement de page ou de thème a pu remplacer le mur pendant la requête.
    if (document.getElementById("mur-x") !== section || etat.page !== "actu") return;
    vider(conteneur);
    if (!ids.length) {
      conteneur.append(el("p", { text: t("x.aucun") }));
      return;
    }
    const theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    for (const id of ids) conteneur.append(el("div", { class: "mur-x-post" },
      el("blockquote", { class: "twitter-tweet", "data-theme": theme, "data-dnt": "true", "data-conversation": "none" },
        lienSur(`https://x.com/i/status/${id}`, t("x.voir")))));
    try {
      const twitter = await chargerWidgetsX();
      if (document.getElementById("mur-x") === section && etat.page === "actu") twitter.widgets.load(conteneur);
    } catch (_) { /* X bloqué ou indisponible : chaque lien de post reste visible. */ }
  }

  function pageAujourdhui(alertes) {
    const frag = document.createDocumentFragment();
    if (alertes.length) frag.append(el("div", { class: "bandeau-alerte", role: "status", text: alertes.join(" · ") + "." }));
    frag.append(el("h2", { text: t("onglet.aujourdhui") }));
    const comptes = blocComptes(Date.now());
    if (comptes) frag.append(comptes);
    else if (enCommun()) frag.append(notePersonnel("personnel.aujourdhui"));
    const outils = blocOutils();
    if (outils) frag.append(outils);
    frag.append(el("div", { id: "encart-kb" }));
    frag.append(el("p", null, el("a", { href: "#actu", text: t("x.voir_mur") })));
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
    frag.append(el("h2", { text: t("elements.titre", { n: sansNul(elements).length }) }));
    const f = filtresProduit(elements, rendre);
    if (f) frag.append(f);
    const bn = basculeNul(filtrer(elements));
    if (bn) frag.append(bn);
    frag.append(listeCartes(sansNul(filtrer(elements)), { vide: t("elements.vide_filtre") }));
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
    frag.append(el("h2", { text: t("onglet.changelogs") }), el("p", { class: "sous-titre", text: t("changelogs.sous_titre") }), noteFenetre());
    const tous = elementsDe("claude", datesRecentes("claude")).concat(elementsDe("openai", datesRecentes("openai")));
    const bn = basculeNul(tous);
    if (bn) frag.append(bn);
    for (const produit of ["claude-code", "claude", "codex", "chatgpt"]) {
      const liste = sansNul(tous.filter((e) => e.produit === produit)).sort(triChrono);
      frag.append(el("h3", { text: `${PRODUITS[produit]} (${liste.length})` }));
      frag.append(listeCartes(liste, { niveau: 4, vide: t("changelogs.vide") }));
    }
    return frag;
  }
  function pageActu() {
    const frag = document.createDocumentFragment();
    frag.append(el("h2", { text: t("onglet.actu") }), blocMurX(), noteFenetre());
    const tous = elementsDe("actu", datesRecentes("actu")).sort(triChrono);
    const bn = basculeNul(tous);
    if (bn) frag.append(bn);
    frag.append(listeCartes(sansNul(tous), { vide: t("actu.vide") }));
    const ec = blocEcartes(datesRecentes("actu").map((d) => etat.jours[`actu/${d}`]));
    if (ec) frag.append(ec);
    return frag;
  }
  /* ---------- Référence (phase 4) : base extraite de la documentation, commentée par les agents ---------- */
  const KB_PERIMETRES = ["claude", "openai"];
  const KB_CATEGORIES_CLES = ["fonctionnalites", "commandes", "skills", "plugins", "mcp", "parametres", "raccourcis", "methodes", "modeles"];
  const KB_CATEGORIES = Object.fromEntries(KB_CATEGORIES_CLES.map((c) => [c, t(`categorie.${c}`)]));
  const VERDICTS = { utiliser: t("verdict.utiliser"), tester: t("verdict.tester"), ignorer: t("verdict.ignorer") };
  const STATUTS = { utilise: t("statut.utilise"), non_utilise: t("statut.non_utilise"), inconnu: t("statut.inconnu") };
  const KB_PAGE = 50;
  const kbFiltre = { q: "", produit: "", categorie: "", verdict: "", statut: "", tri: "", depuis: "", limite: KB_PAGE };
  // nom d'une catégorie au singulier (n = 1) ou au pluriel
  const nomCategorie = (c, n) => t(`categorie.${n > 1 ? "nom_pluriel" : "nom"}.${c}`);
  const KB_JOURS_RECENTS = ["7", "30"];
  const LIGNE_AJOUT = "ajoutée à l'inventaire";  // libellé de l'historique des données (catalogue.py), pas un texte d'interface
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
  // fichier léger des ajouts récents ; absent, illisible ou référence commune (non publié) : null, sans message (pas d'encart)
  async function chargerRecentKb() {
    return unefois("kb-recent", async () => {
      if (enCommun()) { etat.kbRecent = null; return null; }
      try {
        const d = await lireJson(chemin("kb/recent.json"));
        etat.kbRecent = d && Array.isArray(d.entrees) ? d : null;
      } catch (err) { etat.kbRecent = null; }
      return etat.kbRecent;
    });
  }
  // D103 : essais de la base (verdicts tester puis utiliser) pour l'onglet « À tester » ; absent ou illisible : null, section omise sans message ;
  // couche personnelle : jamais lue sur la référence commune
  async function chargerATesterKb() {
    return unefois("kb-a-tester", async () => {
      if (enCommun()) { etat.kbATester = null; return null; }
      try {
        const d = await lireJson(chemin("kb/a-tester.json"));
        etat.kbATester = d && Array.isArray(d.entrees) ? d : null;
      } catch (err) { etat.kbATester = null; }
      return etat.kbATester;
    });
  }
  // D105 : index nom → ids (docs/data/kb/noms.json) pour les liens vers les fiches ; absent ou illisible : null, les segments restent en texte simple
  async function chargerNomsKb() {
    return unefois("kb-noms", async () => {
      try { etat.noms = adapterNoms(await lireJson(chemin("kb/noms.json"))); }
      catch (err) { etat.noms = null; }
      return etat.noms;
    });
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
    console.log(`delta:kb premiers=${kb.entrees.length} ms=${Math.round(performance.now() - kb.debut)}`);
    if (kb.entrees.length) chargerResteKb();
    else { chargerResteKb(); await kb.reste; }  // rien de lisible dans les premiers fichiers : conclure sur toute la base
    await chargerFichierKb(KB_LOCALE, "methodes");  // D121 : les méthodes et modèles locaux, après les tests de lisibilité ci-dessus
    await chargerFichierKb(KB_LOCALE, "modeles");
  }
  /* Chargement par morceaux (m-b6207baf75ca) : la base tient en 14 fichiers (périmètre × catégorie, environ 3 Mo). Les commandes et
     les fonctionnalités des deux périmètres suffisent à la première page ; le reste se charge en arrière-plan, deux fichiers à la fois,
     et un filtre qui en demande un le fait passer devant. Les compteurs ne sont exacts qu'une fois tout chargé : jusqu'alors ils sont
     annoncés provisoires. */
  const KB_PRIORITAIRES = ["commandes", "fonctionnalites"];
  const KB_ARRIERE_PLAN = ["skills", "plugins", "mcp", "raccourcis", "parametres"]; // les petits fichiers d'abord, le plus lourd à la fin
  const KB_PARALLELE = 2;
  const KB_PRODUIT_PERIMETRE = { claude: "claude", "claude-code": "claude", codex: "openai", chatgpt: "openai" };
  /* D121 : les fiches de méthode (kb-methodes/) et de modèles/efforts (kb-modeles/) tiennent dans des fichiers hors périmètre ;
     leur « périmètre » est LOCALE. */
  const KB_LOCALE = "locale";
  const KB_FICHIERS = [...KB_PERIMETRES.flatMap((p) => KB_CATEGORIES_CLES.filter((c) => c !== "methodes" && c !== "modeles").map((c) => [p, c])), [KB_LOCALE, "methodes"], [KB_LOCALE, "modeles"]];
  const RE_ID_KB = new RegExp(`^(claude-code|claude|codex|chatgpt)-(${KB_CATEGORIES_CLES.filter((c) => c !== "methodes" && c !== "modeles").join("|")})-`);
  const RE_ID_METHODE = /^methode-/;
  const RE_ID_MODELE = /^modele-/;
  // même disposition sur l'ancienne route et dans une génération commune : kb/<périmètre>/<catégorie>.json, kb/<catégorie locale>.json
  const cheminKb = (p, c) => chemin(p === KB_LOCALE ? `kb/${c}.json` : `kb/${p}/${c}.json`);
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
          const d = await lireJson(cheminKb(p, c));
          const entrees = c === "modeles" ? (await import("./kb-modeles.mjs")).developperModeles(d) : adapterKb(d, `kb/${cle}.json`);
          for (const e of entrees) if (e && typeof e === "object" && e.id) {
            e._sections = d.contexte_sections && typeof d.contexte_sections === "object" ? d.contexte_sections : null;
            e._deprecies = Array.isArray(d.contexte_deprecies) ? d.contexte_deprecies : [];
            e._ajout = dateAjout(e);
            e._desc = descriptionKb(e);
            e._texte = sansAccents(texteRechercheKb(e));
            nouvelles.push(e);
          }
        } catch (err) { kb.erreurs.push(`${cle} : ${err && err.cle ? t(err.cle, err.vars) : err.message || err}`); }
        if (nouvelles.length) kb.entrees = fusionnerParNomKb(kb.entrees, nouvelles.sort(comparerNomKb));
        kb.charges.add(cle);
        if (kb.charges.size === KB_FICHIERS.length) {
          kb.ms = Math.round(performance.now() - kb.debut);
          console.log(`delta:kb complet=${kb.entrees.length} ms=${kb.ms}`);
        }
      })());
    }
    return kb.promesses.get(cle);
  }
  const kbComplet = () => etatKb().charges.size === KB_FICHIERS.length;
  // fichier d'une entrée d'après son id (`<produit>-<catégorie>-…`), null si l'id n'a pas cette forme
  function fichierDeIdKb(id) {
    if (RE_ID_METHODE.test(String(id || ""))) return [KB_LOCALE, "methodes"];
    if (RE_ID_MODELE.test(String(id || ""))) return [KB_LOCALE, "modeles"];
    const m = RE_ID_KB.exec(String(id || ""));
    return m ? [KB_PRODUIT_PERIMETRE[m[1]], m[2]] : null;
  }
  // fichiers que le filtre courant peut lire : produit → son périmètre, catégorie → ce fichier ; sans l'un ni l'autre, toute la base
  function fichiersRequisKb() {
    const perimetre = kbFiltre.produit ? KB_PRODUIT_PERIMETRE[kbFiltre.produit] : null;
    return KB_FICHIERS.filter(([p, c]) => (!perimetre || p === perimetre || p === KB_LOCALE) && (!kbFiltre.categorie || c === kbFiltre.categorie));
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
      zone.append(el("span", { text: t("kb.chargement", { faits: kb.charges.size, total: KB_FICHIERS.length }) }));
    }
    zone.setAttribute("aria-busy", kbComplet() ? "false" : "true");
    const extraites = kb.entrees.filter((e) => e.categorie !== "methodes" && e.categorie !== "modeles");  // D121 : une méthode ou fiche modèle est rédigée, pas à commenter
    const faites = extraites.filter((e) => e.commentee).length;
    const av = document.getElementById("kb-avancement");
    if (av) {
      av.querySelector("span").textContent = t(kbComplet() ? "kb.avancement" : "kb.avancement_provisoire", { faites, total: extraites.length });
      const pr = av.querySelector("progress");
      pr.max = Math.max(extraites.length, 1); pr.value = faites;
    }
    const err = document.getElementById("kb-erreurs");
    if (err) {
      err.textContent = kb.erreurs.length ? t(enCommun() ? "kb.erreurs_commun" : "kb.erreurs", { liste: kb.erreurs.join(" ; ") }) : "";
      err.hidden = !kb.erreurs.length;
    }
  }
  function filtrerKb() {
    const mots = sansAccents(kbFiltre.q).split(/\s+/).filter(Boolean);
    const ref = jourLocalIso(new Date());
    // la référence commune ne publie pas les dates d'ajout : le filtre de date n'y retient rien de faux, il est ignoré (et dit)
    const depuis = enCommun() ? "" : kbFiltre.depuis;
    const liste = etat.kb.entrees.filter((e) =>
      (!depuis || ajouteeDepuis(e, depuis, ref)) &&
      (!kbFiltre.produit || e.produit === kbFiltre.produit || (Array.isArray(e.produits) && e.produits.includes(kbFiltre.produit))) &&
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
    const parties = KB_CATEGORIES_CLES.filter((c) => compte[c]).map((c) => `${compte[c]} ${nomCategorie(c, compte[c])}`);
    if (!parties.length) return null;
    // fichier coupé avant le seuil des 7 jours : le compte est un minimum
    const minimum = recent.tronque === true && typeof recent.plus_ancienne === "string" && recent.plus_ancienne >= seuil;
    return el("p", { class: "encart-nouveau", role: "status" }, el("strong", { text: t("encart.titre") }), `${minimum ? t("encart.au_moins") : ""}${parties.join(", ")} `,
      el("a", { href: "#reference?recent=7", text: t("encart.voir") }));
  }
  /* D121 : corps d'une fiche de méthode, en Markdown limité à ce que les fiches écrivent : titres #, paragraphes, listes « - »,
     blocs ``` et, dans le texte, `code` et **gras**. Construit en nœuds DOM, jamais en innerHTML. */
  function noeudsEnLigne(s) {
    const out = [];
    let fin = 0;
    for (const m of String(s).matchAll(/`([^`\n]+)`|\*\*([^*\n]+)\*\*/g)) {
      if (m.index > fin) out.push(s.slice(fin, m.index));
      out.push(m[1] !== undefined ? el("code", { text: m[1] }) : el("strong", { text: m[2] }));
      fin = m.index + m[0].length;
    }
    if (fin < s.length) out.push(s.slice(fin));
    return out;
  }
  function rendreMarkdownMethode(source) {
    const corps = el("div", { class: "methode-corps", lang: langueDonnees() });
    let paragraphe = [], liste = null, bloc = null;
    const fermerParagraphe = () => { if (paragraphe.length) corps.append(el("p", null, ...noeudsEnLigne(paragraphe.join(" ")))); paragraphe = []; };
    for (const ligne of String(source || "").split("\n")) {
      if (bloc) {
        if (/^```\s*$/.test(ligne)) { corps.append(el("pre", { class: "usage" }, el("code", { text: bloc.join("\n") }))); bloc = null; }
        else bloc.push(ligne);
        continue;
      }
      if (/^```/.test(ligne)) { fermerParagraphe(); liste = null; bloc = []; continue; }
      const titre = /^(#{1,3})\s+(.+)$/.exec(ligne);
      if (titre) { fermerParagraphe(); liste = null; corps.append(el("h4", null, ...noeudsEnLigne(titre[2]))); continue; }
      const puce = /^- (.+)$/.exec(ligne);
      if (puce) {
        fermerParagraphe();
        if (!liste) { liste = el("ul", null); corps.append(liste); }
        liste.append(el("li", null, ...noeudsEnLigne(puce[1])));
        continue;
      }
      if (liste && /^\s+\S/.test(ligne)) { liste.lastChild.append(" ", ...noeudsEnLigne(ligne.trim())); continue; }
      liste = null;
      if (!ligne.trim()) fermerParagraphe(); else paragraphe.push(ligne.trim());
    }
    if (bloc) corps.append(el("pre", { class: "usage" }, el("code", { text: bloc.join("\n") })));  // bloc non fermé : rendu tel quel
    fermerParagraphe();
    return corps;
  }
  function listeSources(sources) {
    return el("ul", { class: "sources", "aria-label": t("carte.sources") }, ...sources.map((s) =>
      el("li", { class: s && s.officielle === true ? "off" : null }, lienSur(s && s.url, texte(s && s.libelle, s && s.url)))));
  }
  function carteMethode(e) {
    const c = el("li", { class: "carte kb methode" });
    const produits = Array.isArray(e.produits) && e.produits.length ? e.produits : [e.produit];
    c.append(el("div", { class: "badges" },
      ...produits.map((p) => badge("produit", PRODUITS[p] || String(p || "?"))),
      badge("type", KB_CATEGORIES.methodes),
      badge("statut", t("methode.locale")),
      e.certitude === "officiel" ? badge("verdict utiliser", t("methode.officielles")) : null));
    c.append(el("h3", { text: texte(e.nom, t("kb.sans_nom")), lang: langueDonnees() }));
    const versions = e.versions && typeof e.versions === "object" ? Object.entries(e.versions).map(([p, v]) => `${PRODUITS[p] || p} ${v}`) : [];
    c.append(el("div", { class: "meta", text: [e.verifie_le ? t("methode.verifiee", { date: dateAffichee(e.verifie_le) }) : null, ...versions].filter(Boolean).join(" · ") }));
    if (texte(e.description)) c.append(rendreMarkdownMethode(e.description));
    else if (enCommun()) c.append(notePersonnel("kb.texte_commun_attente"));
    if (Array.isArray(e.sources) && e.sources.length) c.append(listeSources(e.sources));
    return c;
  }
  function carteModele(e) {
    const c = el("li", { class: "carte kb methode modele" });
    const produits = Array.isArray(e.produits) && e.produits.length ? e.produits : [e.produit];
    const verdict = e.recommandation ? e.recommandation.verdict : null;
    c.append(el("div", { class: "badges" },
      ...produits.map((p) => badge("produit", PRODUITS[p] || String(p || "?"))),
      badge("type", KB_CATEGORIES.modeles),
      verdict ? badge(`verdict ${verdict}`, VERDICTS[verdict] || verdict) : null,
      e.statut_usage ? badge("statut", STATUTS[e.statut_usage] || String(e.statut_usage)) : null,
      e.cout_quota && e.cout_quota.niveau ? badge("statut", t("modele.quota", { niveau: e.cout_quota.niveau })) : null));
    c.append(el("h3", { text: texte(e.nom, t("kb.sans_nom")) }));
    c.append(el("div", { class: "meta", text: [
      e.fournisseur ? t("modele.fournisseur", { nom: e.fournisseur }) : null,
      e.executant ? t("modele.executant", { nom: e.executant }) : null,
      e.date_releve ? t("modele.releve", { date: dateAffichee(e.date_releve) }) : null,
    ].filter(Boolean).join(" · ") }));
    c.append(el("div", { class: "etiquette", text: t("kb.syntaxe") }));
    c.append(el("pre", { class: "usage" }, el("code", { text: String(e.usage || "") })));
    if (texte(e.effet_effort) && !texte(e.description)) c.append(el("p", { class: "resume", lang: langueDonnees(), text: e.effet_effort }));
    if (texte(e.description)) c.append(rendreMarkdownMethode(e.description));
    if (Array.isArray(e.sources) && e.sources.length) c.append(listeSources(e.sources));
    return c;
  }
  function carteKb(e) {
    if (e.categorie === "methodes") return carteMethode(e);
    if (e.categorie === "modeles") return carteModele(e);
    const c = el("li", { class: "carte kb" + (e.commentee ? "" : " attente") });
    const verdict = e.commentee && e.recommandation ? e.recommandation.verdict : null;
    c.append(el("div", { class: "badges" },
      badge("produit", PRODUITS[e.produit] || String(e.produit || "?")),
      badge("type", KB_CATEGORIES[e.categorie] || String(e.categorie || "?")),
      verdict ? badge(`verdict ${verdict}`, VERDICTS[verdict] || verdict) : enCommun() ? badge("attente", t("kb.avis_indisponible")) : badge("attente", t("kb.attente")),
      e.commentee ? badge("statut", STATUTS[e.statut_usage] || String(e.statut_usage || "")) : null,
      e.retiree ? badge("revise", t("kb.retiree")) : null,
      Array.isArray(e.systemes) && e.systemes.length ? badge("statut", t("kb.systemes", { liste: e.systemes.join(", ") })) : null,
      badgeContexte(e)));
    c.append(el("h3", { text: texte(e.nom, t("kb.sans_nom")) }));
    const meta = [e.groupe, e._ajout ? t("kb.ajoutee_le", { date: dateAffichee(e._ajout) }) : null, typeof e.maj_le === "string" ? t("kb.maj_le", { date: dateAffichee(e.maj_le) }) : null].filter(Boolean);
    if (meta.length) c.append(el("div", { class: "meta", text: meta.join(" · ") }));
    const d = e._desc || descriptionKb(e);
    if (d) {
      c.append(el("p", { class: d.statut === "source" ? "resume source-en" : "resume", lang: d.langue === LANGUE ? null : d.langue, text: d.texte }));
      if (d.repli && d.langue === "en") c.append(el("p", { class: "doux repli", text: t("kb.repli_en") }));
    }
    c.append(el("div", { class: "etiquette", text: e.usage_nature === "etapes" ? t("kb.acces") : t("kb.syntaxe") }));  // D49
    c.append(el("pre", { class: "usage" + (e.usage_nature === "etapes" ? " etapes" : "") }, el("code", { text: String(e.usage || "") })));
    if (e.commentee && texte(e.exemple) && e.exemple !== e.usage) c.append(el("pre", { class: "usage exemple" }, el("code", { text: e.exemple })));
    if (verdict && texte(e.recommandation.pourquoi)) c.append(el("div", { class: "pour-toi" }, el("strong", { text: t("kb.pourquoi") }), el("p", { lang: langueDonnees(), text: e.recommandation.pourquoi })));
    if (texte(e.disponibilite)) c.append(el("p", { class: "projets", lang: langueDonnees(), text: t("kb.disponibilite", { texte: e.disponibilite }) }));
    if (Array.isArray(e.sources) && e.sources.length) c.append(listeSources(e.sources));
    c.append(blocEnvoi(e));
    return c;
  }
  /* ---------- « Envoyer à Delta » (m-944fab565b10) : relais local sur 127.0.0.1 (scripts/relais_reference.py), qui ne lit
     que l'id et relaie l'entrée de sa base locale vers la porte des idées ; injoignable (téléphone, relais arrêté) : le texte
     de l'idée passe par la console reliée à ce navigateur, sinon est copié pour le lanceur Delta (D104). ---------- */
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
  /* Mémoire d'une heure, par fiche (D104) : dernier envoi au relais ou ouverture de la console, et dernière copie, en
     millisecondes. Sans stockage, seul le relais peut conserver la règle entre deux affichages (409). */
  const CLE_HEURES = "delta.envoisHeure";
  const HEURE_MS = 3600000;
  function lireHeures() {
    try { const v = JSON.parse(localStorage.getItem(CLE_HEURES) || "{}"); return v && typeof v === "object" ? v : {}; }
    catch (err) { return {}; }
  }
  // l'heure notée pour (type, id) si elle date de moins d'une heure, sinon null ; type : "envoi", "console" ou "copie"
  function heureRecente(type, id) {
    const t0 = (lireHeures()[id] || {})[type];
    return typeof t0 === "number" && Date.now() - t0 < HEURE_MS && t0 <= Date.now() + 60000 ? t0 : null;
  }
  function noterHeure(type, id, t0) {
    try {
      const v = lireHeures(), maintenant = Date.now();
      for (const k of Object.keys(v)) if (!v[k] || typeof v[k] !== "object" || Object.values(v[k]).every((x) => typeof x !== "number" || maintenant - x >= HEURE_MS)) delete v[k];
      v[id] = Object.assign(v[id] || {}, { [type]: t0 });
      localStorage.setItem(CLE_HEURES, JSON.stringify(v));
    } catch (err) { /* sans stockage : la règle reste tenue par le relais */ }
  }
  function hhmm(t0) { const d = new Date(t0); return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; }
  /* Message destiné à Delta (pas un texte d'interface) : toujours en français, même phrase d'ouverture que texte_idee() du relais,
     quelle que soit la langue de la page ; les noms de catégorie viennent du dictionnaire français. */
  function texteIdeeKb(e) {
    const fr = (window.DELTA_TEXTES && window.DELTA_TEXTES.fr) || {};
    const cat = fr[`categorie.nom.${e.categorie}`] || String(e.categorie || "référence");
    return `idée : intégrer la référence Delta-IA « ${texte(e.nom, "(sans nom)")} » (${PRODUITS[e.produit] || String(e.produit || "produit inconnu")}, ${cat}, id ${e.id}) ` +
      "dans un workflow ou chez un agent de Delta. Juge sa pertinence pour mes projets et, si elle l'est, dis dans quel workflow ou chez quel agent elle entre et ce que ça change.";
  }
  /* Adresse de la console de pilotage (D104) : jamais dans le dépôt ni sur le site (REGLES §5), seulement dans ce navigateur.
     Elle s'y enregistre en ouvrant une fois <site>/#console=<adresse> ; le fragment est retiré
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
      return t("console.oubliee");
    }
    const adresse = adresseConsole(brut);
    if (!adresse) return t("console.refusee");
    try { localStorage.setItem(CLE_CONSOLE, adresse); } catch (err) { return t("console.stockage_refuse"); }
    return t("console.enregistree");
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
  // le bouton reste désactivé jusqu'à la fin de l'heure qui suit l'envoi
  function bloquerBouton(bouton, t0) {
    bouton.disabled = true;
    bouton.textContent = t("envoi.envoyee");
    setTimeout(() => { bouton.disabled = false; bouton.textContent = t("envoi.bouton"); }, Math.max(1000, t0 + HEURE_MS - Date.now()));
  }
  async function envoyerADelta(e, bouton, statut) {
    statut.textContent = "";
    for (const vieux of document.querySelectorAll(".envoi-secours")) vieux.remove();
    const dejaT = heureRecente("envoi", e.id);
    if (dejaT !== null) { bloquerBouton(bouton, dejaT); statut.textContent = t("envoi.deja", { heure: hhmm(dejaT) }); return; }
    if (estIos()) return repli(e, statut, t("envoi.pas_joignable"), bouton);
    bouton.disabled = true;
    bouton.textContent = t("envoi.en_cours");
    let r = null;
    if (await relaisJoignable()) {
      try {
        const rep = await fetch(`${RELAIS}/reference`, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: e.id }), signal: AbortSignal.timeout(25000) });
        r = await rep.json();
      } catch (err) { r = null; }
    }
    if (r && r.ok === true) {
      const t0 = Date.now();
      noterEnvoi(e.id);
      suiviPromesse = null;
      noterHeure("envoi", e.id, t0);
      bloquerBouton(bouton, t0);
      statut.textContent = t("envoi.ok");
      return;
    }
    if (r && r.etape === "deja_envoyee") {   // 409 du relais : envoi d'un autre navigateur ou d'un autre onglet
      const t0 = typeof r.envoye_a === "number" ? r.envoye_a * 1000 : Date.now();
      noterHeure("envoi", e.id, t0);
      bloquerBouton(bouton, t0);
      statut.textContent = texte(r.detail, t("envoi.deja", { heure: hhmm(t0) }));
      return;
    }
    bouton.disabled = false;
    bouton.textContent = t("envoi.bouton");
    if (r) { statut.textContent = t("envoi.refus", { detail: texte(r.detail, String(r.etape || "refus")) }); return; }
    // relais injoignable (téléphone, relais arrêté, accès au réseau local refusé) : la console, sinon le texte de l'idée pour le lanceur
    return repli(e, statut, t("envoi.pas_joignable"), bouton);
  }
  async function repli(e, statut, motif, bouton) {
    const adresse = lireConsole();
    if (adresse) {
      const confirmer = () => {
        const t0 = Date.now();
        noterHeure("envoi", e.id, t0);
        noterHeure("console", e.id, t0);
        bloquerBouton(bouton, t0);
        statut.textContent = t("envoi.console");
      };
      const url = urlConsole(adresse, e);
      const w = window.open(url, "_blank");
      if (w) { try { w.opener = null; } catch (err) { /* sans effet */ } confirmer(); return; }
      statut.textContent = t("envoi.ouverture_bloquee");
      const ouvrir = el("a", { class: "envoi-delta envoi-secours", href: url, target: "_blank", rel: "noopener", text: t("envoi.ouvrir_console") });
      ouvrir.addEventListener("click", (event) => {
        if (bouton.disabled) { event.preventDefault(); return; }
        confirmer();
      });
      statut.after(ouvrir);
      return;
    }
    statut.textContent = motif;
    if (await copierIdeeKb(e)) { noterHeure("copie", e.id, Date.now()); statut.textContent = `${motif} ${t("envoi.copiee")}`; return; }
    const copier = el("button", { type: "button", class: "envoi-delta envoi-secours", text: t("envoi.copier") });
    copier.addEventListener("click", async () => {
      if (await copierIdeeKb(e)) { noterHeure("copie", e.id, Date.now()); statut.textContent = `${motif} ${t("envoi.copiee")}`; }
      else statut.textContent = t("envoi.copie_refusee");
      copier.remove();
    });
    statut.after(copier);
  }
  // le presse-papier peut rester en attente sans geste récent de l'utilisateur : 1,5 s au plus
  async function copierIdeeKb(e) {
    try {
      await Promise.race([navigator.clipboard.writeText(texteIdeeKb(e)), new Promise((_, non) => setTimeout(() => non(new Error("delai")), 1500))]);
      return true;
    } catch (err) { return false; }
  }
  function blocEnvoi(e) {
    const jour = lireEnvois()[e.id], envoi = heureRecente("envoi", e.id), copie = heureRecente("copie", e.id);
    let message = typeof jour === "string" ? t("envoi.envoyee_le", { date: dateAffichee(jour) }) : "";
    if (envoi !== null) message = heureRecente("console", e.id) === envoi
      ? t("envoi.deja_console", { heure: hhmm(envoi) })
      : t("envoi.ok_a", { heure: hhmm(envoi) });
    else if (copie !== null) message = t("envoi.copiee_a", { heure: hhmm(copie) });
    const statut = el("span", { class: "envoi-statut", role: "status", text: message });
    const b = el("button", { type: "button", class: "envoi-delta", text: t("envoi.bouton"), title: t("envoi.titre") });
    if (envoi !== null) bloquerBouton(b, envoi);
    b.addEventListener("click", () => envoyerADelta(e, b, statut));
    const suivi = el("p", { class: "envoi-suivi", hidden: true });
    chargerSuivi().then((r) => remplirSuivi(suivi, r, e.id));
    return el("div", { class: "envoi" }, b, statut, suivi);
  }
  /* ---------- Boucle d'adoption (m-a04181983623) : état de la fiche projeté depuis OPÉRER par le relais local (GET /suivi,
     scripts/deltalib/adoptions.py), sur ce poste seulement : donnée personnelle, jamais publiée. Delta Lab et OBSERVATORY
     mesurent ; la page ne montre que l'état, les utilisations et où lire le résultat observé. Demandé seulement par un
     navigateur qui a déjà envoyé une fiche : un visiteur du site ne reçoit pas de demande d'accès au réseau local. ---------- */
  const ETAPES_SUIVI = ["propose", "retenu", "en_realisation", "installe"];
  let suiviPromesse = null;
  function chargerSuivi() {
    if (suiviPromesse) return suiviPromesse;
    if (enCommun() || estIos() || !Object.keys(lireEnvois()).length) return (suiviPromesse = Promise.resolve(null));
    suiviPromesse = (async () => {
      for (let essai = 0; essai < 4; essai++) {   // 503 « en_calcul » : premier calcul du relais, environ 15 s
        let rep;
        try { rep = await fetch(`${RELAIS}/suivi`, { signal: AbortSignal.timeout(5000) }); } catch (err) { return null; }
        if (rep.status === 503) { await new Promise((ok) => setTimeout(ok, 15000)); continue; }
        try {
          const r = await rep.json();
          return r && r.ok === true && r.fiches && typeof r.fiches === "object" ? r : null;
        } catch (err) { return null; }
      }
      return null;
    })();
    return suiviPromesse;
  }
  // une livraison fusionnée sans fichier installé (preuves `sans_installation`) est dite « adoptée », jamais « installée »
  function libelleInstallation(i) {
    return t(i.par === "mission_sans_installation" ? "suivi.adoption" : "suivi.installation",
      { date: ISO_JOUR.test(i.le || "") ? dateAffichee(i.le) : "?", lot: String(i.lot || "?") });
  }
  function remplirSuivi(zone, r, id) {
    const f = r && r.fiches[id];
    if (!f || typeof f !== "object") return;
    // « inconnu » : vue d'une mission liée illisible (délai, code) ; jamais une échelle devinée à sa place
    const etapes = f.etat === "inconnu" ? ["inconnu"] : f.etat === "ecarte" ? ["propose", "ecarte"] : f.etat === "adopte" ? ["propose", "retenu", "en_realisation", "adopte"] : ETAPES_SUIVI;
    const rang = etapes.indexOf(f.etat);
    zone.append(el("strong", { text: t("suivi.titre") }), " ");
    etapes.forEach((x, i) => {
      if (i) zone.append(" › ");
      zone.append(i === rang ? el("strong", { text: t(`suivi.etape.${x}`) }) : el("span", { class: i > rang ? "a-venir" : null, text: t(`suivi.etape.${x}`) }));
    });
    const details = [];
    if (typeof f.position === "string") details.push(t("suivi.position", { position: f.position }));
    for (const m of f.missions || []) if (m && m.projete === "en_realisation") details.push(t("suivi.mission", { id: m.id, etat: m.etat }));
    for (const id of Array.isArray(f.missions_illisibles) ? f.missions_illisibles : []) details.push(t("suivi.illisible", { id: String(id) }));
    if (details.length) zone.append(` (${details.join(" ; ")})`);
    const installations = Array.isArray(f.installations) ? f.installations : [];
    if (installations.length) zone.append(el("br"), t("suivi.utilisations", { liste: installations.map(libelleInstallation).join(" ; ") }));
    const observes = Array.isArray(f.resultat_observe) ? f.resultat_observe : [];
    const essais = observes.filter((o) => o && o.essai).map((o) =>
      `${o.essai} ${t(`suivi.essai.${o.statut}`)}${o.maturite ? ` · ${o.maturite}` : ""}${o.explication ? ` : ${o.explication}` : ""}`);
    const tris = observes.filter((o) => o && o.statut === "ecarte_au_tri").map((o) =>
      t("suivi.tri", { date: ISO_JOUR.test(o.le || "") ? dateAffichee(o.le) : "?", raison: String(o.explication || "") }));
    if (essais.length || tris.length) zone.append(el("br"), t("suivi.resultat", { liste: essais.concat(tris).join(" ; ") }));
    else if (f.etat === "installe" || f.etat === "adopte") zone.append(el("br"), t("suivi.resultat_aucun"));
    zone.hidden = false;
  }
  function libelleAjustement(f) {
    const r = f.ajustement && f.ajustement.reglage;
    if (!r || typeof r.cle !== "string") return null;
    return el("span", { text: t("ameliorations.ajustement", { nature: String(f.ajustement.nature || "?"), champ: r.cle.split(".").pop(),
      temoin: String(r.temoin), essai: String(r.essai) }) });
  }
  // rubrique « Améliorations appliquées » de l'onglet Référence : fiches installées ou adoptées (dit comme tel), date et lot, repliée
  function remplirAmeliorations(r) {
    const sec = document.getElementById("kb-ameliorations");
    if (!sec || !r) return;
    const installees = Object.values(r.fiches).filter((f) => f && (f.etat === "installe" || f.etat === "adopte") && Array.isArray(f.installations) && f.installations.length)
      .sort((a, b) => String(b.installations[b.installations.length - 1].le || "").localeCompare(String(a.installations[a.installations.length - 1].le || "")));
    if (!installees.length && !(r.sources_en_echec || []).length) return;
    const noms = new Map(((etat.kb && etat.kb.entrees) || []).map((e) => [e.id, e.nom]));
    const d = el("details", { class: "actions-faites" }, el("summary", { text: t("ameliorations.titre", { n: installees.length }) }),
      el("p", { class: "sous-titre", text: t("ameliorations.sous_titre") }),
      el("ul", null, ...installees.map((f) => el("li", null,
        // ajustement de réglage (lot 4, reglages_pont.py) : pas de fiche de la base, le réglage tient lieu de nom
        libelleAjustement(f) || el("a", { href: `#reference?id=${encodeURIComponent(f.id)}`, text: texte(noms.get(f.id), f.id) }),
        ` — ${f.installations.map(libelleInstallation).join(" ; ")}`))));
    if ((r.sources_en_echec || []).length) d.append(el("p", { class: "erreur", text: t("suivi.incomplet", { liste: r.sources_en_echec.join(" ; ") }) }));
    sec.append(d);
    sec.hidden = false;
  }
  // D64-bis : péremption par ctx-id de CONTEXTE ; `contexte_sections: null` = commentaire antérieur à D64
  function badgeContexte(e) {
    if (!e.commentee || !e._sections) return null;
    if (e.contexte_sections === null || e.contexte_sections === undefined) return badge("anterieur", t("kb.anterieur_d64"));
    if (typeof e.contexte_sections !== "object") return null;
    const changees = Object.keys(e.contexte_sections).filter((k) => {
      const v = e.contexte_sections[k];
      return e._deprecies.includes(k) || !v || typeof v !== "object" || e._sections[k] !== v.sha1;
    });
    return changees.length ? badge("perime", t("kb.a_revoir", { sections: changees.join(", ") })) : null;
  }
  function choix(libelle, cle, options, vide) {
    const s = el("select", { "aria-label": libelle });
    s.append(el("option", { value: "", text: vide || libelle }));
    for (const [v, txt] of Object.entries(options)) {
      const o = el("option", { value: v, text: txt });
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
    const resume = enCommun() ? t("kb.resultats_commun", { n: liste.length }) : t("kb.resultats", { n: liste.length, commentees });
    zone.append(el("p", { class: "sous-titre", role: "status", text: resume + (manquants.length ? ` · ${t("kb.provisoire")}` : "") }));
    if (enCommun() && kbFiltre.depuis) zone.append(notePersonnel("kb.recent_indisponible"));
    zone.append(el("ul", { class: "liste" }, ...liste.slice(0, kbFiltre.limite).map(carteKb)));
    if (liste.length > kbFiltre.limite) {
      const b = el("button", { type: "button", class: "plus", text: t("liste.plus", { n: Math.min(KB_PAGE, liste.length - kbFiltre.limite) }) });
      b.addEventListener("click", () => { kbFiltre.limite += KB_PAGE; rendreResultatsKb(); });
      zone.append(b);
    }
  }
  function pageReference() {
    const frag = document.createDocumentFragment();
    frag.append(el("h2", { text: t("onglet.reference") }));
    const kb = etat.kb;
    if (!kb || (!kb.entrees.length && kbComplet())) {
      frag.append(el("p", { class: "vide", text: kb && kb.erreurs.length && enCommun() ? t("kb.erreurs_commun", { liste: kb.erreurs.join(" ; ") }) : t("reference.non_publiee") }));
      return frag;
    }
    if (etat.kbFicheId) {
      const fiche = kb.entrees.find((e) => e.id === etat.kbFicheId);
      frag.append(el("p", { class: "retour-ref" }, el("a", { href: "#reference", text: t("reference.retour") })),
        fiche ? el("ul", { class: "liste" }, carteKb(fiche)) : el("p", { class: "vide", text: t("reference.fiche_absente") }));
      window.scrollTo(0, 0);
      return frag;
    }
    const extraites = kb.entrees.filter((e) => e.categorie !== "methodes");  // D121
    const commentables = extraites.filter((e) => e.categorie !== "modeles");
    const total = commentables.length, faites = commentables.filter((e) => e.commentee).length;
    if (enCommun()) frag.append(el("p", { class: "sous-titre", text: t("reference.sous_titre_commun") }));
    else {
      const barre = el("div", { class: "avancement", id: "kb-avancement" }, el("span", { text: t("kb.avancement", { faites, total }) }),
        el("progress", { max: String(total), value: String(faites), "aria-label": t("kb.avancement_titre") }));
      frag.append(el("p", { class: "sous-titre", text: t("reference.sous_titre") }), barre);
    }
    frag.append(el("div", { id: "kb-chargement", class: "avancement kb-chargement", role: "status", "aria-live": "polite" }),
      el("p", { id: "kb-erreurs", class: "erreur", hidden: true }));
    const recherche = el("input", { type: "search", placeholder: t("reference.recherche"), "aria-label": t("reference.recherche_titre"), value: kbFiltre.q });
    let minuterie = null;
    recherche.addEventListener("input", () => { clearTimeout(minuterie); minuterie = setTimeout(() => { kbFiltre.q = recherche.value; kbFiltre.limite = KB_PAGE; rendreResultatsKb(); }, 150); });
    const filtres = [recherche,
      choix(t("filtre.choix_produit"), "produit", Object.fromEntries(["claude-code", "claude", "codex", "chatgpt"].map((p) => [p, PRODUITS[p]]))),
      choix(t("filtre.categorie"), "categorie", KB_CATEGORIES)];
    // avis, usage et dates d'ajout sont personnels ou non publiés : pas de filtre qui ne pourrait rien retenir sur la référence commune
    if (!enCommun()) filtres.push(
      choix(t("filtre.verdict"), "verdict", { ...VERDICTS, attente: t("kb.attente") }),
      choix(t("filtre.statut"), "statut", STATUTS),
      choix(t("filtre.tri"), "tri", { recent: t("filtre.tri_recent") }, t("filtre.tri_alpha")),
      choix(t("filtre.date_ajout"), "depuis", { 7: t("filtre.depuis_7"), 30: t("filtre.depuis_30") }, t("filtre.depuis_toutes")));
    frag.append(el("div", { class: "filtres kb-filtres" }, ...filtres));
    if (!enCommun()) {
      frag.append(el("section", { id: "kb-ameliorations", hidden: true }));
      chargerSuivi().then(remplirAmeliorations);
    }
    frag.append(el("div", { id: "kb-resultats" }));
    return frag;
  }
  const ESSAIS_PAGE = 50;
  // D119 : essai déclaré par une mission (champ `essai` de a-tester.json, date venue de kb-essais.yaml) : fait sans geste
  function essaiDeclare(e) { return ISO_JOUR.test(e.essai || "") ? e.essai : null; }
  function essaiFait(e, faits) { return Boolean(faits[String(e.id || "")] || essaiDeclare(e)); }
  // carte d'un essai de la base : usage et exemple en code, pourquoi, date d'ajout, case « fait » (même stockage local que les actions)
  function carteEssai(e, surFait) {
    const faits = lireFaits();
    const id = String(e.id || "");
    const declare = essaiDeclare(e);
    const c = el("li", { class: "carte kb essai" + (essaiFait(e, faits) ? " fait" : "") });
    const verdict = VERDICTS[e.verdict] ? e.verdict : null;
    c.append(el("div", { class: "badges" },
      badge("produit", PRODUITS[e.produit] || String(e.produit || "?")),
      badge("type", KB_CATEGORIES[e.categorie] || String(e.categorie || "?")),
      verdict ? badge(`verdict ${verdict}`, VERDICTS[verdict]) : null));
    c.append(el("h4", { text: texte(e.nom, t("kb.sans_nom")) }));
    if (ISO_JOUR.test(e.date_ajout || "")) c.append(el("div", { class: "meta", text: t("kb.ajoutee_le", { date: dateAffichee(e.date_ajout) }) }));
    if (texte(e.usage)) {
      c.append(el("div", { class: "etiquette", text: e.usage_nature === "etapes" ? t("kb.acces") : t("kb.syntaxe") }));
      c.append(el("pre", { class: "usage" + (e.usage_nature === "etapes" ? " etapes" : "") }, el("code", { text: String(e.usage) })));
    }
    if (texte(e.exemple) && e.exemple !== e.usage) c.append(el("pre", { class: "usage exemple" }, el("code", { text: e.exemple })));
    if (texte(e.pourquoi)) c.append(el("div", { class: "pour-toi" }, el("strong", { text: t("kb.pourquoi") }), el("p", { lang: langueDonnees(), text: e.pourquoi })));
    if (declare) {  // cochée par la mission : la case ne se décoche pas, la provenance est dite
      const caseFait = el("input", { type: "checkbox", disabled: true });
      caseFait.checked = true;
      c.append(el("div", { class: "action" }, el("label", null, caseFait, t("essai.fait_mission", { date: dateAffichee(declare) }))));
      return c;
    }
    const caseFait = el("input", { type: "checkbox" });
    caseFait.checked = Boolean(faits[id]);
    caseFait.addEventListener("change", () => {
      ecrireFait(id, caseFait.checked); c.classList.toggle("fait", caseFait.checked);
      if (surFait) surFait();
    });
    c.append(el("div", { class: "action" }, el("label", null, caseFait, t("carte.fait"))));
    return c;
  }
  // section « Essais de la base » : tester d'abord, puis date d'ajout décroissante (ordre du fichier) ; les faits dans une section repliée
  function sectionEssais(doc) {
    const sec = el("section", { class: "essais-base" });
    const faits = lireFaits();
    const entrees = doc.entrees.filter((e) => e && typeof e === "object" && e.id);
    const ouverts = entrees.filter((e) => !essaiFait(e, faits));
    const faitsListe = entrees.filter((e) => essaiFait(e, faits));
    const surFait = () => rendre();
    sec.append(el("h3", { class: "compte-actions", text: t("essais.titre", { n: ouverts.length }) }),
      el("p", { class: "sous-titre", text: t("essais.sous_titre") }));
    if (doc.tronque === true) sec.append(el("p", { class: "doux", text: t("essais.tronque", { n: entrees.length, total: doc.total }) }));
    const ul = el("ul", { class: "liste" }, ...ouverts.slice(0, etat.essaisLimite).map((e) => carteEssai(e, surFait)));
    sec.append(ouverts.length ? ul : el("p", { class: "vide", text: t("essais.aucun") }));
    if (ouverts.length > etat.essaisLimite) {
      const b = el("button", { type: "button", class: "plus", text: t("liste.plus", { n: Math.min(ESSAIS_PAGE, ouverts.length - etat.essaisLimite) }) });
      b.addEventListener("click", () => { etat.essaisLimite += ESSAIS_PAGE; rendre(); });
      sec.append(b);
    }
    if (faitsListe.length) {
      const d = el("details", { class: "actions-faites" }, el("summary", { text: t("essais.faits", { n: faitsListe.length }) }),
        el("ul", { class: "liste" }, ...faitsListe.map((e) => carteEssai(e, surFait))));
      d.open = etat.essaisFaitsOuverts === true;
      d.addEventListener("toggle", () => { etat.essaisFaitsOuverts = d.open; });
      sec.append(d);
    }
    return sec;
  }
  function pageATester() {
    const frag = document.createDocumentFragment();
    frag.append(el("h2", { text: t("onglet.a_tester") }), el("p", { class: "sous-titre", text: t("atester.sous_titre") }), noteFenetre());
    let liste = [];
    for (const p of PERIMETRES) liste = liste.concat(elementsDe(p, datesRecentes(p)).filter((e) => e.action && typeof e.action === "object"));
    // audit du 25/09 : les actions ouvertes d'abord, avec leur nombre ; les faites à part, dans une section repliée
    const faits = lireFaits();
    const ouvertes = liste.filter((e) => !faits[String(e.id || "")]).sort(triImpact);
    const faites = liste.filter((e) => faits[String(e.id || "")]).sort(triImpact);
    const surFait = () => rendre();  // une case cochée ou décochée fait passer l'action dans l'autre section
    if (enCommun()) frag.append(notePersonnel("personnel.a_tester"));
    frag.append(el("h3", { class: "compte-actions", text: t("atester.ouvertes", { n: ouvertes.length }) }),
      listeCartes(ouvertes, { vide: t("atester.aucune"), surFait }));
    if (faites.length) {
      const d = el("details", { class: "actions-faites" }, el("summary", { text: t("atester.faites", { n: faites.length }) }),
        listeCartes(faites, { surFait }));
      d.open = etat.faitesOuvertes === true;
      d.addEventListener("toggle", () => { etat.faitesOuvertes = d.open; });
      frag.append(d);
    }
    if (etat.kbATester && etat.kbATester.entrees.length) frag.append(sectionEssais(etat.kbATester));
    return frag;
  }
  /* ---------- Recherche dans toute la veille (D114) : docs/data/recherche.json, écrit par scripts/recherche.py ---------- */
  const RECHERCHE_PAGE = 50;
  const RECHERCHE_MIN = 2;
  // pli de casse et d'accents qui garde la longueur du texte : la position d'un mot dans le texte plié est sa position dans l'original
  function plier(s) {
    let sortie = "";
    for (const c of String(s || "")) {
      const p = c.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
      sortie += p.length === c.length ? p : c;
    }
    return sortie;
  }
  // mots de la requête (tous doivent apparaître) ; un passage entre guillemets reste une expression
  function termesDeRecherche(q) {
    const termes = [];
    const re = /"([^"]+)"|(\S+)/g;
    const plie = plier(q);
    let m;
    while ((m = re.exec(plie))) {
      const x = (m[1] || m[2] || "").replace(/^"+|"+$/g, "").trim();
      if (x) termes.push(x);
    }
    return termes;
  }
  function ligneRechercheValide(l) {
    return l && typeof l === "object" && typeof l.id === "string" && ISO_JOUR.test(l.date || "") && PERIMETRES.includes(l.perimetre)
      && typeof l.titre === "string" && typeof l.texte === "string";
  }
  async function chargerRecherche() {
    await unefois("recherche", async () => {
      // index construit sur les textes personnels (titre, résumé, pour toi, action) : non publié dans la référence commune
      if (enCommun()) { etat.recherche = { commun: true }; return; }
      try {
        const d = await lireJson(chemin("recherche.json"));
        if (!d || !Array.isArray(d.elements)) throw new Error(t("erreur.recherche_sans_elements"));
        const lignes = d.elements.filter(ligneRechercheValide).map((l) => ({ ...l, _titre: plier(l.titre), _texte: plier(l.texte) }));
        etat.recherche = { doc: d, lignes };
      } catch (e) { etat.recherche = { erreur: String(e.message || e) }; }
    });
  }
  // l'index est déjà trié par date décroissante : l'ordre des résultats est celui du fichier
  function chercherDansVeille(lignes, termes) {
    return lignes.filter((l) => termes.every((x) => l._titre.includes(x) || l._texte.includes(x)));
  }
  // texte découpé en morceaux, les occurrences des termes dans des <mark> (positions lues sur le texte plié)
  function surligner(brut, termes) {
    const plie = plier(brut);
    const zones = [];
    for (const x of termes) for (let i = plie.indexOf(x); i >= 0; i = plie.indexOf(x, i + x.length)) zones.push([i, i + x.length]);
    zones.sort((a, b) => a[0] - b[0] || b[1] - a[1]);
    const fusion = [];
    for (const z of zones) {
      const dernier = fusion[fusion.length - 1];
      if (dernier && z[0] <= dernier[1]) dernier[1] = Math.max(dernier[1], z[1]);
      else fusion.push([z[0], z[1]]);
    }
    const morceaux = [];
    let curseur = 0;
    for (const [a, b] of fusion) {
      if (a > curseur) morceaux.push(brut.slice(curseur, a));
      morceaux.push(el("mark", { text: brut.slice(a, b) }));
      curseur = b;
    }
    if (curseur < brut.length) morceaux.push(brut.slice(curseur));
    return morceaux;
  }
  // une trentaine de mots autour de la première occurrence dans le texte, à défaut le début du texte (le mot est alors dans le titre)
  const EXTRAIT_AVANT = 70;
  const EXTRAIT_LONGUEUR = 220;
  function extraitDe(l, termes) {
    const positions = termes.map((x) => l._texte.indexOf(x)).filter((i) => i >= 0);
    const pos = positions.length ? Math.min(...positions) : 0;
    let debut = Math.max(0, pos - EXTRAIT_AVANT);
    if (debut > 0) { const espace = l.texte.indexOf(" ", debut); if (espace >= 0 && espace < pos) debut = espace + 1; }
    let fin = Math.min(l.texte.length, debut + EXTRAIT_LONGUEUR);
    if (fin < l.texte.length) { const espace = l.texte.lastIndexOf(" ", fin); if (espace > pos) fin = espace; }
    return [debut > 0 ? "… " : "", ...surligner(l.texte.slice(debut, fin), termes), fin < l.texte.length ? " …" : ""];
  }
  function carteRecherche(l, termes) {
    const impact = impactDe(l);
    const c = el("li", { class: `carte resultat impact-${impact || "inconnu"}` });
    c.append(el("div", { class: "badges" }, impact ? badge(`impact ${impact}`, t(`impact.${impact}`)) : null, badge("produit", t(`perimetre.court.${l.perimetre}`))));
    c.append(el("h4", { lang: langueDonnees() }, ...surligner(l.titre || t("carte.sans_titre"), termes)));
    c.append(el("div", { class: "meta" }, `${dateAffichee(l.date)} · `, el("a", { href: `#archives/${l.date}`, text: t("carte.passage", { date: dateAffichee(l.date) }) })));
    if (l.texte) c.append(el("p", { class: "extrait", lang: langueDonnees() }, ...extraitDe(l, termes)));
    return c;
  }
  function rendreResultatsRecherche() {
    const zone = document.getElementById("recherche-resultats");
    if (!zone || !etat.recherche || !etat.recherche.lignes) return;
    vider(zone);
    const q = etat.rq.q;
    const termes = termesDeRecherche(q);
    if (q.trim().length < RECHERCHE_MIN || !termes.length) {
      zone.append(el("p", { class: "sous-titre", text: t("recherche.aide", { n: RECHERCHE_MIN }) }));
      return;
    }
    const trouves = chercherDansVeille(etat.recherche.lignes, termes);
    if (!trouves.length) { zone.append(el("p", { class: "vide", text: t("recherche.aucun", { q: q.trim() }) })); return; }
    const affiches = trouves.slice(0, etat.rq.limite);
    zone.append(el("p", { class: "sous-titre", role: "status", text: trouves.length > affiches.length ? t("recherche.resultats_coupes", { n: trouves.length, affiches: affiches.length }) : t(trouves.length > 1 ? "recherche.resultats" : "recherche.resultat", { n: trouves.length }) }));
    zone.append(el("ul", { class: "liste" }, ...affiches.map((l) => carteRecherche(l, termes))));
    if (trouves.length > affiches.length) {
      const b = el("button", { type: "button", class: "plus", text: t("liste.plus", { n: Math.min(RECHERCHE_PAGE, trouves.length - affiches.length) }) });
      b.addEventListener("click", () => { etat.rq.limite += RECHERCHE_PAGE; rendreResultatsRecherche(); });
      zone.append(b);
    }
  }
  function sectionRecherche() {
    const r = etat.recherche;
    if (!r) return null;
    const sec = el("section", { class: "recherche" });
    if (r.commun) { sec.append(notePersonnel("personnel.recherche")); return sec; }
    if (r.erreur) { sec.append(el("p", { class: "erreur", text: t("recherche.indisponible", { raison: r.erreur }) })); return sec; }
    const champ = el("input", { type: "search", placeholder: t("recherche.placeholder"), "aria-label": t("recherche.titre"), value: etat.rq.q });
    let minuterie = null;
    champ.addEventListener("input", () => {
      clearTimeout(minuterie);
      minuterie = setTimeout(() => {
        etat.rq = { q: champ.value, limite: RECHERCHE_PAGE };
        try { history.replaceState(null, "", champ.value.trim() ? `#archives?q=${encodeURIComponent(champ.value.trim())}` : "#archives"); } catch (e) { /* adresse non mise à jour : sans effet sur la recherche */ }
        majLienLangue();
        rendreResultatsRecherche();
      }, 150);
    });
    sec.append(el("div", { class: "filtres kb-filtres" }, champ));
    const dates = r.lignes.map((l) => l.date).sort();
    sec.append(el("p", { class: "sous-titre", text: dates.length ? t("recherche.index", { n: r.lignes.length, du: dateAffichee(dates[0]), au: dateAffichee(dates[dates.length - 1]) }) : t("recherche.index_vide") }));
    if (r.doc.statut !== "ok") sec.append(el("p", { class: "erreur", text: t("recherche.incomplet", { raison: texte(r.doc.raison, t("raison.inconnue")) }) }));
    sec.append(el("div", { id: "recherche-resultats" }));
    return sec;
  }
  // compte d'un jour dans la liste des Archives : nombre d'éléments, et impacts forts et moyens seulement quand l'index les déclare
  function compteurJour(p, d) {
    const j = (etat.index[p]?.jours || []).find((x) => x.date === d);
    if (!j) return null;
    const n = Number.isInteger(j.elements) ? j.elements : (etat.jours[`${p}/${d}`]?.elements || []).length;
    const imp = j.impact && typeof j.impact === "object" ? j.impact : null;
    const nom = t(`perimetre.court.${p}`);
    return imp ? t("archives.compteur_impact", { nom, n, fort: imp.fort ?? 0, moyen: imp.moyen ?? 0 }) : t("archives.compteur", { nom, n });
  }
  function pageArchives() {
    const frag = document.createDocumentFragment();
    frag.append(el("h2", { text: t("onglet.archives") }));
    const toutesDates = [...new Set(PERIMETRES.flatMap(datesDe))].sort().reverse();
    if (!toutesDates.length) { frag.append(el("p", { class: "vide", text: t("archives.aucune") })); return frag; }
    if (etat.archiveDate && toutesDates.includes(etat.archiveDate)) {
      const d = etat.archiveDate;
      frag.append(el("p", { class: "sous-titre" }, el("a", { href: "#archives", text: t("archives.retour") }), ` · ${t("carte.passage", { date: dateAffichee(d) })}`));
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
      frag.append(el("h3", { text: t("elements.titre", { n: elements.length }) }));
      frag.append(listeCartes(elements, { niveau: 4 }));
      const ec = blocEcartes(quotidiens);
      if (ec) frag.append(ec);
      return frag;
    }
    const recherche = sectionRecherche();
    if (recherche) frag.append(recherche);
    const ul = el("ul", { class: "jours" });
    for (const d of toutesDates) {
      const compteurs = PERIMETRES.map((p) => compteurJour(p, d)).filter(Boolean);
      ul.append(el("li", null, el("a", { href: `#archives/${d}` }, el("strong", { text: dateAffichee(d) }), el("span", { class: "compteurs", text: compteurs.join(" · ") }))));
    }
    frag.append(ul);
    return frag;
  }

  /* ---------- Semaine (D98) : bilan de la semaine ISO, champs recopiés par scripts/semaine.py ; non publié en commun ---------- */
  const RE_SEMAINE = /^\d{4}-W\d{2}$/;
  const SOURCES_SEMAINE = ["claude", "actu", "openai"];
  async function chargerSemaine() {
    const s = etat.semaines;
    await unefois("semaine-index", async () => {
      if (enCommun()) { s.index = null; s.commun = true; return; }
      try {
        const idx = await lireJson(chemin("semaine/index.json"));
        if (!idx || !Array.isArray(idx.semaines)) throw new Error(t("erreur.semaine_sans_semaines"));
        s.index = idx.semaines.filter((x) => x && RE_SEMAINE.test(x.semaine));
      } catch (e) { s.index = null; s.erreur = String(e.message || e); }
    });
    if (!s.index || !s.index.length) return;
    s.courante = s.index.some((x) => x.semaine === etat.semaineDemandee) ? etat.semaineDemandee : s.index[0].semaine;
    const semaine = s.courante;
    await unefois(`semaine:${semaine}`, async () => {
      try {
        const d = await lireJson(chemin(`semaine/${semaine}.json`));
        if (!d || !Array.isArray(d.elements) || !Array.isArray(d.d71) || !Array.isArray(d.base_ajoutees) || !Array.isArray(d.base_verdicts)) throw new Error(t("erreur.bilan_illisible"));
        s.docs[semaine] = d;
      } catch (e) { s.docs[semaine] = { erreur: String(e.message || e) }; }
    });
  }
  function ligneSemaine(l) {
    const impact = impactDe(l);
    const c = el("li", { class: `ligne-semaine impact-${impact || "inconnu"}` });
    c.append(el("div", { class: "badges" },
      impact ? badge(`impact ${impact}`, t(`impact.${impact}`)) : null,
      badge(`certitude ${l.certitude || ""}`, CERTITUDES.includes(l.certitude) ? t(`certitude.${l.certitude}`) : String(l.certitude || "?")),
      badge("produit", PRODUITS[l.produit] || String(l.produit || "?"))));
    c.append(el("h4", { lang: langueDonnees(), text: texte(l.titre, t("carte.sans_titre")) + (l.version ? ` ${l.version}` : "") }));
    c.append(el("div", { class: "meta" }, `${dateAffichee(l.date_publication)} · `,
      ISO_JOUR.test(l.jour || "") ? el("a", { href: `#archives/${l.jour}`, text: t("carte.passage", { date: dateAffichee(l.jour) }) }) : t("semaine.passage_inconnu")));
    c.append(texte(l.action) ? el("p", { class: "action-courte", lang: langueDonnees() }, el("strong", { text: t("semaine.action") }), ...enrichi(l.action, l.produit)) : el("p", { class: "action-courte doux", text: t("semaine.aucune_action") }));
    return c;
  }
  function ligneKbSemaine(l, quand) {
    const c = el("li", { class: "carte kb" });
    const verdict = l.verdict_apres || l.verdict;
    const badges = el("div", { class: "badges" }, badge("produit", PRODUITS[l.produit] || String(l.produit || "?")),
      badge("type", KB_CATEGORIES[l.categorie] || String(l.categorie || "?")),
      verdict ? badge(`verdict ${verdict}`, VERDICTS[verdict] || verdict) : badge("attente", t("kb.attente")));
    if (l.verdict_apres) badges.append(el("span", { class: "meta", text: l.verdict_avant ? t("semaine.avant", { verdict: VERDICTS[l.verdict_avant] || l.verdict_avant }) : t("semaine.premier_jugement") }));
    c.append(badges, el("h4", { text: texte(l.nom, t("kb.sans_nom")) }), el("div", { class: "meta", text: quand }));
    c.append(el("pre", { class: "usage" }, el("code", { text: String(l.usage || "") })));
    if (texte(l.exemple) && l.exemple !== l.usage) {
      c.append(el("div", { class: "etiquette", text: l.exemple_origine === "source" ? t("semaine.exemple_source") : l.exemple_origine === "compose" ? t("semaine.exemple_compose") : t("semaine.exemple") }));
      c.append(el("pre", { class: "usage exemple" }, el("code", { text: l.exemple })));
    }
    if (texte(l.pourquoi)) c.append(el("div", { class: "pour-toi" }, el("strong", { text: t("kb.pourquoi") }), el("p", { lang: langueDonnees(), text: l.pourquoi })));
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
    frag.append(el("h2", { text: t("onglet.semaine") }));
    if (s.commun) { frag.append(notePersonnel("personnel.semaine")); return frag; }
    if (s.index === null) {
      frag.append(el("p", { class: "erreur", text: t("semaine.indisponible", { raison: s.erreur }) }));
      return frag;
    }
    if (!s.index.length) {
      frag.append(el("p", { class: "vide", text: t("semaine.aucune") }));
      return frag;
    }
    const choixSemaine = el("select", { "aria-label": t("semaine.choix") });
    for (const x of s.index) {
      choixSemaine.append(el("option", { value: x.semaine, selected: x.semaine === s.courante ? true : null, text: t("semaine.option", { semaine: x.semaine, du: dateAffichee(x.du), au: dateAffichee(x.au) }) }));
    }
    choixSemaine.addEventListener("change", () => { location.hash = `#semaine/${choixSemaine.value}`; });
    frag.append(el("div", { class: "filtres" }, choixSemaine));
    const d = s.docs[s.courante];
    if (!d || d.erreur) {
      frag.append(el("p", { class: "erreur", text: t("semaine.bilan_indisponible", { semaine: s.courante, raison: d ? d.erreur : t("semaine.non_charge") }) }));
      return frag;
    }
    frag.append(el("p", { class: "sous-titre", text: t("semaine.sous_titre", { du: dateAffichee(d.du), au: dateAffichee(d.au), quand: horodatage(d.genere_le) }) }));
    if (d.statut !== "ok") frag.append(el("p", { class: "erreur", role: "status", text: t("semaine.partiel", { statut: d.statut, raison: texte(d.raison, t("raison.non_indiquee")) }) }));
    else {
      const jours = SOURCES_SEMAINE.filter((k) => d.sources && d.sources[k]).map((k) => t("semaine.jours_lus", { nom: t(`perimetre.court.${k}`), n: d.sources[k].jours.length }));
      frag.append(el("p", { class: "sous-titre doux", text: t("semaine.passages_lus", { liste: jours.join(", ") }) }));
    }
    frag.append(blocSemaine(t("comptes.titre"), d.d71, ligneSemaine, t("semaine.vide_d71")));
    frag.append(blocSemaine(t("semaine.a_retenir"), d.elements, ligneSemaine, t("semaine.vide_elements")));
    const utiles = d.base_ajoutees.filter((l) => l.verdict !== "ignorer");
    const ignorees = d.base_ajoutees.filter((l) => l.verdict === "ignorer");
    const ajoutee = (l) => ligneKbSemaine(l, t("kb.ajoutee_le", { date: dateAffichee(l.date_ajout) }));
    const bAjout = blocSemaine(t("semaine.nouveau"), utiles, ajoutee, ignorees.length ? t("semaine.vide_utiles") : t("semaine.vide_ajouts"));
    if (ignorees.length) {
      bAjout.append(el("details", { class: "ecartes" }, el("summary", { text: t("semaine.ignorees", { n: ignorees.length }) }),
        el("ul", { class: "liste" }, ...ignorees.map(ajoutee))));
    }
    frag.append(bAjout);
    frag.append(blocSemaine(t("semaine.verdicts"), d.base_verdicts, (l) => ligneKbSemaine(l, t("semaine.verdict_du", { date: dateAffichee(l.date) })), t("semaine.vide_verdicts")));
    return frag;
  }

  /* ---------- Aide (D112) : texte statique, une section par onglet ou fonction ; aucune donnée personnelle, aucune adresse de console.
     Textes dans le dictionnaire : aide.<id>.titre, .sert, .geste, .limite et, pour le connecteur, aide.mcp.liste.1 à 6. ---------- */
  // sert : à quoi ça sert ; geste : comment s'en servir (bureau, iPhone) ; limite : ce que ça ne fait pas ; liste : lignes courtes (connecteur MCP)
  // les segments entre accents graves s'affichent en code ; les liens `[texte](#ancre)` ne mènent qu'à une ancre du site
  const AIDE = [
    { id: "etat" }, { id: "aujourdhui" }, { id: "quotas" }, { id: "outils" }, { id: "nouveau" }, { id: "semaine" }, { id: "changelogs" },
    { id: "actu" }, { id: "reference" }, { id: "liens" }, { id: "envoi" }, { id: "a-tester" }, { id: "archives" }, { id: "couches" },
    { id: "langue" }, { id: "mcp", liste: 6 }, { id: "iphone" },
  ];
  // adresses publiques interpolées dans l'aide, jamais écrites en dur
  const ADRESSES_AIDE = { mcp_url: CONFIG.mcp_public_url || "", site_url: CONFIG.site_public_url || "" };
  // texte d'aide → nœuds : `code` en <code>, [texte](#ancre) en lien interne ; tout le reste en texte
  function aideNoeuds(s) {
    const out = [];
    let fin = 0;
    for (const m of s.matchAll(/\[`([^`\n]+)`\]\((#[^)\s]+)\)|`([^`\n]+)`/g)) {
      if (m.index > fin) out.push(s.slice(fin, m.index));
      out.push(m[2] ? el("a", { href: m[2] }, el("code", { text: m[1] })) : el("code", { text: m[3] }));
      fin = m.index + m[0].length;
    }
    if (fin < s.length) out.push(s.slice(fin));
    return out;
  }
  function pageAide() {
    const frag = document.createDocumentFragment();
    frag.append(el("h2", { text: t("onglet.aide") }),
      el("p", { class: "sous-titre", text: t("aide.sous_titre") }));
    for (const a of AIDE) {
      const titre = t(`aide.${a.id}.titre`);
      const sec = el("section", { class: "aide-bloc", id: `aide-${a.id}`, "aria-label": titre }, el("h3", { text: titre }));
      for (const champ of ["sert", "geste", "limite"]) {
        sec.append(el("p", { class: "aide-ligne" }, el("strong", { text: t(`aide.etiquette.${champ}`) }), " ", ...aideNoeuds(t(`aide.${a.id}.${champ}`, ADRESSES_AIDE))));
        if (champ === "geste" && a.liste) sec.append(el("ul", { class: "aide-outils" }, ...Array.from({ length: a.liste }, (_, i) => el("li", null, ...aideNoeuds(t(`aide.${a.id}.liste.${i + 1}`))))));
      }
      frag.append(sec);
    }
    return frag;
  }

  /* ---------- routage par ancre ---------- */
  function lireRoute() {
    const h = (location.hash || "#aujourdhui").slice(1);
    const [cheminRoute, requete] = h.split("?");
    const [page, param] = cheminRoute.split("/");
    etat.page = ["aujourdhui", "semaine", "changelogs", "actu", "reference", "a-tester", "archives", "aide"].includes(page) ? page : "aujourdhui";
    etat.semaineDemandee = etat.page === "semaine" && RE_SEMAINE.test(param || "") ? param : null;
    etat.archiveDate = etat.page === "archives" && /^\d{4}-\d{2}-\d{2}$/.test(param || "") ? param : null;
    // D114 : #archives?q=<texte> ouvre les Archives avec cette recherche
    etat.rq = { q: etat.page === "archives" ? (new URLSearchParams(requete || "").get("q") || "") : "", limite: RECHERCHE_PAGE };
    // #reference?recent=7 (ou 30) : vue des entrées ajoutées récemment, la plus récente d'abord
    const recent = etat.page === "reference" ? new URLSearchParams(requete || "").get("recent") : null;
    if (KB_JOURS_RECENTS.includes(recent)) { kbFiltre.depuis = recent; kbFiltre.tri = "recent"; kbFiltre.limite = KB_PAGE; }
    // D105 : #reference?id=<id> affiche la fiche seule ; #reference?q=<nom> ouvre la référence avec cette recherche, filtres remis à zéro
    const params = etat.page === "reference" ? new URLSearchParams(requete || "") : null;
    etat.kbFicheId = params && params.get("id") ? params.get("id") : null;
    const q = params ? (params.get("q") || "").trim() : "";
    if (q && !etat.kbFicheId) Object.assign(kbFiltre, { q, produit: "", categorie: "", verdict: "", statut: "", tri: "", depuis: "", limite: KB_PAGE });
  }
  // les données propres à la page ; les 30 jours, eux, sont attendus à part (`chargerFenetre`)
  async function chargerDeLaPage() {
    switch (etat.page) {
      case "aujourdhui": await Promise.all([chargerDernierJour(), chargerVersions(), chargerComptes()]); break;
      case "archives": await Promise.all([chargerJoursArchive(), etat.archiveDate ? null : chargerRecherche()]); break;
      case "reference": await chargerKb(); break;
      case "a-tester": await chargerATesterKb(); break;
      case "semaine": await chargerSemaine(); break;
      default: break;
    }
  }
  async function rendre() {
    lireRoute();
    majLienLangue();
    const mien = ++etat.rendu;  // un rendu plus récent a la main : celui-ci s'arrête après ses attentes
    const fenetre = PAGES_FENETRE[etat.page] ? chargerFenetre() : null;
    if (fenetre && !fenetre.fini) {
      document.querySelectorAll(".onglets a").forEach((a) => a.classList.toggle("actif", a.dataset.page === etat.page));
      rendreEtatAgents();
      vider(main);
      main.append(pageAttenteFenetre(fenetre));
    }
    await Promise.all([chargerDeLaPage(), fenetre && fenetre.termine]);
    if (mien !== etat.rendu) return;
    document.querySelectorAll(".onglets a").forEach((a) => a.classList.toggle("actif", a.dataset.page === etat.page));
    const alertes = rendreEtatAgents();
    rendreCouche();
    vider(main);
    if (etat.page === "aide") {  // texte statique : s'affiche même si les données sont illisibles
      main.append(pageAide());
      document.title = t("titre.page", { page: t("onglet.aide") });
      return;
    }
    const erreursIndex = PERIMETRES.filter((p) => etat.index[p] && etat.index[p].erreur);
    if (erreursIndex.length === PERIMETRES.length) {
      // erreur de couche explicite : référence commune indisponible (sans repli sur l'ancienne route) ou aucune donnée lisible
      if (enCommun()) {
        if (COUCHE.automatique) main.append(el("p", { class: "erreur", text: t("erreur.ancienne_illisible", { raison: COUCHE.erreurAncienne || "" }) }));
        main.append(el("p", { class: "erreur", role: "alert", text: t("erreur.commun_indisponible", { raison: COUCHE.erreur || etat.index[PERIMETRES[0]].erreur }) }));
      } else main.append(el("p", { class: "erreur", text: t("erreur.aucune_donnee") }));
      return;
    }
    for (const p of erreursIndex) main.append(el("p", { class: "erreur", text: t(enCommun() ? "erreur.index_commun" : "erreur.index", { p, raison: etat.index[p].erreur }) }));
    switch (etat.page) {
      case "semaine": main.append(pageSemaine()); break;
      case "changelogs": main.append(pageChangelogs()); break;
      case "actu": main.append(pageActu()); completerMurX(); break;
      case "reference": main.append(pageReference()); rendreResultatsKb(); break;
      case "a-tester": main.append(pageATester()); break;
      case "archives": main.append(pageArchives()); rendreResultatsRecherche(); break;
      default: main.append(pageAujourdhui(alertes)); completerEncartKb();
    }
    document.title = t("titre.page", { page: document.querySelector(".onglets a.actif")?.textContent || t("titre.defaut") });
    lancerFond();
  }

  async function demarrer() {
    const avisConsole = enregistrerConsoleDepuisUrl();
    if (avisConsole) annoncer(avisConsole);
    brancherLangue();
    try {
      lireRoute();
      // Aujourd'hui : etat.json et versions.json partent avec les index, sans attendre leur réponse (ancienne route seulement :
      // la référence commune ne lit pas etat.json, et ses versions attendent la génération)
      if (etat.page === "aujourdhui" && !COUCHE.demandee) { chargerComptes(); chargerVersions(); }
      await chargerIndex();
      await rendre();
    } catch (e) {
      vider(main);
      main.append(el("p", { class: "erreur", text: t("erreur.chargement", { raison: e.message || e }) }));
      return;
    }
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if (etat.page === "actu") rendre().catch((e) => console.error("delta:theme-x", e));
    });
    window.addEventListener("hashchange", () => { rendre().catch((e) => console.error("delta:rendu", e)); });
    console.log("delta:pret", matchMedia("(prefers-color-scheme: dark)").matches ? "theme=sombre" : "theme=clair", `langue=${LANGUE}`, `couche=${COUCHE.mode}`);
  }
  demarrer();
})();
