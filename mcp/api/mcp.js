// Delta — serveur MCP distant, lecture seule (Streamable HTTP, sans état, sans dépendance).
// Il lit uniquement les JSON publics du site Delta (GitHub Pages). Il n'a ni jeton, ni accès à la machine de
// Sylvain, ni outil d'écriture : il ne peut pas lancer de passage /delta ni modifier quoi que ce soit.
// Deux couches (lot L3) : il lit l'ancienne route des données ou la génération commune (lib/couches.js), et répond en
// anglais par défaut, en français sur demande (`?langue=fr` sur l'adresse du serveur, ou `langue` à chaque appel).
// Il ne possède aucune donnée personnelle : sur la référence commune, avis, impacts, essais et versions installées sont
// absents et dits indisponibles ; constats internes et recommandations OPÉRER ne sont jamais rendus (lib/modeles.js).
// Lot L4 : les mêmes six outils servent le MCP stdio local (stdio.js) quand le contexte porte `source: "local"` et un
// lecteur local (lib/local.js, construit par stdio.js ou bureau.js seulement) : couche commune du miroir de l'instance et
// bloc `personnel` distinct, avec ses dates. Le serveur HTTP ne construit jamais ce contexte (`?source=` n'admet que les
// deux sources publiques) et ce fichier n'ouvre aucun fichier : la racine personnelle lui reste inaccessible.

import CONFIG from "../lib/config.js";
import { developperModeles } from "../lib/modeles.js";

import { createHash } from "node:crypto";
import { MOTS_VIDES, sansAccents, presence, pertinence, indexer } from "../lib/recherche.js";
import { validiteFiche } from "../lib/validite.js";
import { LANGUES, t, ErreurTexte, texteErreur } from "../lib/textes.js";
import { SOURCES, sourceDefaut, lireRoute, lireCommun, blocDonnees, raisonLecture, erreurFormat, texteBilingue } from "../lib/couches.js";

import { compter } from "../lib/compteur.js";

const PROTOCOLE = "2025-06-18";
const PERIMETRES = ["claude", "openai", "actu"];
const KB = { claude: ["fonctionnalites", "commandes", "skills", "plugins", "mcp", "parametres", "raccourcis"],
             openai: ["fonctionnalites", "commandes", "skills", "plugins", "mcp", "parametres", "raccourcis"] };
const STATUTS = ["utilise", "non_utilise", "inconnu"];
const PRODUITS = ["claude", "claude-code", "chatgpt", "codex"];
// D121 : les fiches de méthode locales (kb/methodes.json, rédigées à la main) et les fiches de modèles/efforts (kb/modeles.json) forment deux catégories locales hors périmètre
const CATEGORIES = [...KB.claude, "methodes", "modeles"];
const IMPACTS = ["fort", "moyen", "faible", "nul"];
const MAX_RESUME_COMMUN = 30;
const VERSION = "0.3.0";

// Contexte d'une requête : langue des textes et source lue. Défauts : DELTA_LANGUE, sinon la langue commune (en) ;
// DELTA_SOURCE, sinon l'ancienne route. L'adresse du serveur peut les fixer (`?langue=fr`, `?source=commun`).
const langueDefaut = () => (LANGUES.includes(process.env.DELTA_LANGUE) ? process.env.DELTA_LANGUE : CONFIG.langue_commune_defaut);
const contexteDefaut = () => ({ langue: langueDefaut(), source: sourceDefaut() });
// Format commun (génération versionnée) : référence publique `commun` ou miroir local de l'instance (`local`).
const estLocal = (ctx) => ctx.source === "local" && Boolean(ctx.local);
const formatCommun = (ctx) => ctx.source === "commun" || estLocal(ctx);
const lire = async (chemin, ctx) => (estLocal(ctx) ? ctx.local.lireCommun(chemin) : ctx.source === "commun" ? lireCommun(chemin) : lireRoute(chemin));
const avertir = (ctx) => t(ctx.langue, "avertissement");
// en-tête commun des réponses : avertissement, puis la source lue et ses dates (jamais « commun » pour l'ancienne route)
const entete = async (ctx) => ({ avertissement: avertir(ctx), donnees: estLocal(ctx) ? ctx.local.blocDonnees(ctx.langue) : await blocDonnees(ctx) });

// D105 : même normalisation que `normaliser_nom` (catalogue.py) et `normaliserNom` (app.js) : NFKC, espaces réduits, minuscules.
const normaliserNom = (s) => String(s || "").normalize("NFKC").split(/\s+/).filter(Boolean).join(" ").toLowerCase();
const court = (s, n = 600) => (typeof s === "string" && s.length > n ? s.slice(0, n) + " …" : s ?? null);

// ---------------------------------------------------------------------------------------------- outils

async function derniersJours(ctx) {
  const res = {};
  await Promise.all(PERIMETRES.map(async (p) => {
    try { res[p] = await lire(`${p}/index.json`, ctx); } catch (e) { res[p] = { erreur: texteErreur(e, ctx.langue) }; }
  }));
  return res;
}

const RE_DATE = /^\d{4}-\d{2}-\d{2}$/;
const parPublication = (a, b) => String(b.date_publication || "").localeCompare(String(a.date_publication || ""));

async function resumeDuJour({ date, inclure_faibles = false } = {}, ctx) {
  if (date !== undefined && !RE_DATE.test(String(date))) throw new ErreurParametre("param.date");
  if (formatCommun(ctx)) return resumeCommun(date, ctx, inclure_faibles);
  const index = await derniersJours(ctx);
  const perimetres = [];
  for (const p of PERIMETRES) {
    const idx = index[p];
    const jours = (idx && Array.isArray(idx.jours)) ? idx.jours.map((j) => j.date).sort().reverse() : [];
    const d = date || jours[0];
    if (!d || !jours.includes(d)) { perimetres.push({ perimetre: p, date: d || null, absent: true }); continue; }
    const q = await lire(`${p}/${d}.json`, ctx);
    const tous = Array.isArray(q.elements) ? q.elements : [];
    // Vue compatible (champs personnels nuls) : aucun impact personnel ne doit vider la liste ; tous les éléments, sans tri par impact.
    const sansImpact = tous.length > 0 && !tous.some((e) => IMPACTS.includes(e.impact));
    const garder = new Set(inclure_faibles ? ["fort", "moyen", "faible"] : ["fort", "moyen"]);
    const elements = (sansImpact ? [...tous].sort(parPublication) : tous.filter((e) => garder.has(e.impact))
      .sort((a, b) => ["fort", "moyen", "faible"].indexOf(a.impact) - ["fort", "moyen", "faible"].indexOf(b.impact)))
      .map((e) => ({ id: e.id ?? null, titre: e.titre ?? null, produit: e.produit, version: e.version ?? null, impact: IMPACTS.includes(e.impact) ? e.impact : null,
                     certitude: e.certitude, resume: court(e.resume), pour_toi: court(e.pour_toi), action: e.action || null, sources: (e.sources || []).map((s) => s.url) }));
    const compte = { fort: 0, moyen: 0, faible: 0, nul: 0, inconnu: 0 };
    for (const e of tous) compte[IMPACTS.includes(e.impact) ? e.impact : "inconnu"] += 1;
    const r = { perimetre: p, date: d, agent: q.agent, genere_le: q.genere_le, synthese: q.synthese ?? null, tri: sansImpact ? "publication" : "impact", compte, elements,
                sources_en_echec: (q.sources_en_echec || []).map((s) => s.id) };
    if (sansImpact) r.avis = t(ctx.langue, "resume.sans_impact");
    perimetres.push(r);
  }
  return { ...(await entete(ctx)), perimetres };
}

// Référence commune : éléments factuels du jour, tirés des publications de `veille/<périmètre>.json` (pas de synthèse rédigée en L2).
async function resumeCommun(date, ctx, inclure_faibles = false) {
  const tete = await entete(ctx);
  const perimetres = [];
  for (const p of PERIMETRES) {
    const v = await lire(`veille/${p}.json`, ctx);
    if (!Array.isArray(v.entrees) || !Array.isArray(v.jours)) throw erreurFormat(`veille/${p}.json`);
    const jours = v.jours.map((j) => j && j.date).filter((d) => typeof d === "string" && RE_DATE.test(d)).sort().reverse();
    const d = date || jours[0];
    if (!d || !jours.includes(d)) { perimetres.push({ perimetre: p, date: d || null, absent: true }); continue; }
    const tous = [];
    for (const e of v.entrees) for (const pub of e.publications || []) if (pub && pub.jour === d)
      tous.push({ id: e.id, identite: e.identite ?? null, titre: null, produit: pub.produit ?? null, version: pub.version ?? null, type: pub.type ?? null,
        impact: null, certitude: pub.certitude ?? null, date_publication: pub.date_publication ?? null, revision: pub.revision === true,
        kb_refs: Array.isArray(pub.kb_refs) ? pub.kb_refs : [], sources: (pub.sources || []).map((s) => ({ url: s.url, libelle: s.libelle ?? null, officielle: s.officielle === true })) });
    tous.sort(parPublication);
    // local : avis du jour de cette instance (impact, pour_toi, action) en bloc personnel ; s'il en existe, la sélection
    // personnelle (fort, moyen, et faible sur demande) s'applique, sinon tous les éléments, par publication
    let liste = tous, tri = "publication", compte;
    if (estLocal(ctx)) {
      const entrees = new Map(v.entrees.map((x) => [x.identite, x]));
      for (const e of tous) e.personnel = ctx.local.veille(e.identite, p, d, entrees.get(e.identite)) ?? { statut: "non_personnalise", impact: null };
      compte = { fort: 0, moyen: 0, faible: 0, nul: 0, inconnu: 0 };
      for (const e of tous) compte[IMPACTS.includes(e.personnel.impact) ? e.personnel.impact : "inconnu"] += 1;
      if (tous.some((e) => IMPACTS.includes(e.personnel.impact))) {
        const ordre = inclure_faibles ? ["fort", "moyen", "faible"] : ["fort", "moyen"];
        liste = tous.filter((e) => ordre.includes(e.personnel.impact)).sort((a, b) => ordre.indexOf(a.personnel.impact) - ordre.indexOf(b.personnel.impact));
        tri = "impact_personnel";
      }
    }
    const r = { perimetre: p, date: d, genere_le: (v.jours.find((j) => j.date === d) || {}).genere_le ?? null, synthese: null, tri,
      ...(compte ? { compte } : {}), total: liste.length, affichees: Math.min(liste.length, MAX_RESUME_COMMUN), elements: liste.slice(0, MAX_RESUME_COMMUN),
      avis: [t(ctx.langue, "resume.synthese_absente"), liste.length > MAX_RESUME_COMMUN ? t(ctx.langue, "resume.tronque", { affichees: MAX_RESUME_COMMUN, total: liste.length }) : null].filter(Boolean).join(" ; ") };
    perimetres.push(r);
  }
  return { ...tete, perimetres };
}

const FICHIERS_KB = [...Object.entries(KB).flatMap(([p, cats]) => cats.map((c) => [`${p}/${c}`, `kb/${p}/${c}.json`])),
                     ["methodes", "kb/methodes.json"], ["modeles", "kb/modeles.json"]];

async function toutesEntrees(ctx) {
  const out = [], categories_non_lues = [];
  const lots = await Promise.all(FICHIERS_KB.map(async ([categorie, chemin]) => {
    try {
      const d = await fichierLeger(chemin, ctx);
      return [categorie, categorie === "modeles" ? { ...d, entrees: developperModeles(d) } : d, null];
    }
    catch (e) { return [categorie, null, texteErreur(raisonLecture(e), ctx.langue)]; }
  }));
  for (const [categorie, d, raison] of lots) {
    if (raison !== null) { categories_non_lues.push({ categorie, raison }); continue; }
    for (const e of d.entrees) if (!e.retiree) out.push({ ...e, _validite: validiteFiche(e, d) });
  }
  return { entrees: out, categories_non_lues };
}

// D121 : une méthode ou une fiche modèle concerne plusieurs produits (`produits`) ; les autres entrées n'en ont qu'un
const duProduit = (e, produit) => e.produit === produit || (Array.isArray(e.produits) && e.produits.includes(produit));

function ficheMethode(e, complete) {
  const f = { id: e.id, nom: e.nom, produit: e.produit, produits: e.produits ?? [e.produit], categorie: e.categorie, origine: "locale",
    certitude: e.certitude ?? null, syntaxe_ou_acces: "syntaxe", usage: court(e.usage, complete ? 2000 : 400),
    description: court(e.description, complete ? 8000 : 600), verifie_le: e.verifie_le ?? null, source: (e.sources || [])[0]?.url || null };
  if (complete) Object.assign(f, { versions: e.versions ?? null, sources: (e.sources || []).map((s) => ({ url: s.url, libelle: s.libelle })) });
  return f;
}

// Description dans la langue demandée quand la fiche porte l'enveloppe bilingue L2 ; sinon le texte publié, tel quel.
function description(e, ctx, n) {
  const b = texteBilingue(e, "description", ctx.langue);
  if (b) return { description: court(b.texte, n), description_langue: b.langue, description_repli: b.repli, description_statut: b.statut };
  return null;
}
// Bloc personnel d'une fiche : absent de la référence commune, dit indisponible (jamais un avis de repli).
const personnelIndisponible = (ctx) => ({ verdict: null, pourquoi: null, statut_usage: null, avis_personnel: t(ctx.langue, "personnel.indisponible") });

function ficheModele(e, complete, ctx) {
  const f = { id: e.id, nom: e.nom, produit: e.produit, produits: e.produits ?? [e.produit], categorie: e.categorie, origine: "locale",
    famille: e.famille ?? null, fournisseur: e.fournisseur ?? null, executant: e.executant ?? null,
    modele: e.modele ?? null, modele_operer: e.modele_operer ?? null, effort: e.effort ?? null, effort_defaut: e.effort_defaut === true,
    effort_defaut_portee: e.effort_defaut_portee ?? null, effort_defaut_detail: e.effort_defaut_detail ?? null,
    syntaxe_ou_acces: "syntaxe", usage: court(e.usage, complete ? 2000 : 400),
    effet_effort: court(e.effet_effort, complete ? 2000 : 400),
    forfait: e.forfait?.nom ?? null, cout_quota: e.cout_quota ?? null,
    // la recommandation d'un couple est celle d'OPÉRER : retirée de la réponse publique (L3), sur les deux formats
    verdict: null, pourquoi: null,
    statut_usage: formatCommun(ctx) ? null : e.statut_usage ?? null, date_releve: e.date_releve ?? null, source: (e.sources || [])[0]?.url || null };
  if (complete) {
    Object.assign(f, {
      aliases: e.aliases ?? [],
      executants_operer: e.executants_operer ?? [e.executant],
      effort_defaut_modele: e.effort_defaut_modele ?? null,
      effort_defaut_detail: e.effort_defaut_detail ?? null,
      effort_defaut_portee: e.effort_defaut_portee ?? null,
      sources_internes: e.sources_internes ?? [],
      sources_champs: e.sources_champs ?? {},
      niveaux_effort_disponibles: e.niveaux_effort_disponibles ?? [],
      date_sortie: e.date_sortie ?? null,
      cutoff_connaissances: e.cutoff_connaissances ?? null,
      fenetre_contexte_jetons: e.fenetre_contexte_jetons ?? null,
      sortie_max_jetons: e.sortie_max_jetons ?? null,
      description: court(e.description, 12000),
      forfait_detail: e.forfait ?? null,
      forfaits_applicables: e.forfaits_applicables ?? [],
      prix_api: e.prix_api ?? null,
      tarifs_credits: e.tarifs_credits ?? null,
      points_forts: e.points_forts ?? [],
      points_faibles: e.points_faibles ?? [],
      benchmarks: e.benchmarks ?? [],
      certitude: e.certitude ?? null,
      verifie_le: e.verifie_le ?? null,
      sources: (e.sources || []).map((s) => ({ url: s.url, libelle: s.libelle, date: s.date ?? null, officielle: s.officielle === true })),
    });
  }
  if (ctx.source === "commun") Object.assign(f, { avis_personnel: t(ctx.langue, "personnel.indisponible") });
  // local : constats de cette instance pour ce couple (bilan OPÉRER projeté), à côté des faits publics, jamais dedans
  if (estLocal(ctx) && complete) f.constats_instance = ctx.local.constatsCouple(e.identite, e);
  return f;
}

function fiche(e, ctx, complete = false) {
  const f = { ...contenuFiche(e, complete, ctx), ...(e._validite || validiteFiche(e)) };
  // local : identité, puis bloc personnel distinct (statut, dates, avis) ; la syntaxe reste celle de la fiche commune
  if (estLocal(ctx)) Object.assign(f, { identite: e.identite ?? null, personnel: ctx.local.blocPersonnel(e.identite, e, { complet: complete }) });
  return f;
}

function contenuFiche(e, complete, ctx) {
  if (e.categorie === "methodes") return ficheMethode(e, complete);
  if (e.categorie === "modeles") return ficheModele(e, complete, ctx);
  const f = { id: e.id, nom: e.nom, produit: e.produit, categorie: e.categorie,
    syntaxe_ou_acces: e.usage_nature === "etapes" ? "acces" : "syntaxe", usage: court(e.usage, complete ? 2000 : 400),
    description: e.commentee ? e.description : null,
    description_documentation: e.commentee && !complete ? undefined : court(e.description_source, complete ? 1500 : 400),
    verdict: e.commentee && e.recommandation ? e.recommandation.verdict : t(ctx.langue, "verdict.attente"),
    pourquoi: e.commentee && e.recommandation ? e.recommandation.pourquoi : null,
    statut_usage: e.commentee ? e.statut_usage : null, source: (e.sources || [])[0]?.url || null };
  // texte bilingue (génération commune, ou vue compatible qui le porte) : il passe avant l'ancien texte, sans avis de repli
  const bilingue = description(e, ctx, complete ? 8000 : 600);
  if (bilingue) Object.assign(f, bilingue, { description_documentation: complete ? court(e.description_source, 1500) : undefined });
  if (ctx.source === "commun") Object.assign(f, personnelIndisponible(ctx));
  if (estLocal(ctx)) Object.assign(f, { verdict: null, pourquoi: null, statut_usage: null });
  if (Object.hasOwn(e, "systemes")) f.systemes = Array.isArray(e.systemes) ? e.systemes : null;
  if (complete) Object.assign(f, { exemple: e.exemple || null, exemple_origine: e.exemple ? e.exemple_origine || null : null, disponibilite: e.disponibilite || null, maj_le: e.maj_le ?? null });
  return f;
}

const resumeNonLues = (liste) => liste.map((x) => `${x.categorie} (${x.raison})`).join(", ");

async function chercherReference({ requete, produit, categorie, statut, limite = 8 } = {}, ctx) {
  if (typeof requete !== "string" || !requete.trim()) throw new ErreurParametre("param.requete");
  if (produit !== undefined && !PRODUITS.includes(produit)) throw new ErreurParametre("param.produit", { liste: PRODUITS.join(", ") });
  if (categorie !== undefined && !CATEGORIES.includes(categorie)) throw new ErreurParametre("param.categorie", { liste: CATEGORIES.join(", ") });
  if (statut !== undefined && !STATUTS.includes(statut)) throw new ErreurParametre("param.statut", { liste: STATUTS.join(", ") });
  if (statut !== undefined && ctx.source === "commun") throw new ErreurParametre("param.statut_commun");
  const n = Math.max(1, Math.min(20, Number(limite) || 8));
  const q = sansAccents(requete.trim());
  const mots = q.split(/\s+/).filter(Boolean);
  // Repli : mots d'au moins 2 caractères, hors mots vides, sans doublon ; un mot en `-` ou `/` est aussi cherché sans son préfixe.
  const retenus = [...new Set(mots.filter((m) => m.length >= 2 && !MOTS_VIDES.has(m)))];
  // D105 : le nom exact (ou la commande, l'option) de l'index `kb/noms.json` passe avant la recherche plein texte ;
  // sans index, la recherche plein texte seule, dite dans `avis`.
  let exacts = new Set(), parMot = new Map(), commandesParMot = new Set(), avis;
  try {
    const doc = await lire("kb/noms.json", ctx);
    // ancienne route : la carte nom → ids à la racine ; référence commune : sous `noms`
    const noms = formatCommun(ctx) ? doc?.noms : doc;
    if (!noms || typeof noms !== "object" || Array.isArray(noms)) throw erreurFormat("kb/noms.json");
    const ids = (nom) => { const v = Object.hasOwn(noms, nom) ? noms[nom] : []; return Array.isArray(v) ? v.filter((i) => typeof i === "string") : []; };
    exacts = new Set(ids(normaliserNom(requete)));
    // Une liste composée uniquement de noms de commandes (« model effort ») conserve chaque commande.
    if (mots.length > 1 && retenus.every((m) => /^[a-z][a-z0-9-]*$/.test(m) && ids(`/${normaliserNom(m)}`).length))
      for (const m of retenus) for (const i of ids(`/${normaliserNom(m)}`)) commandesParMot.add(i);
    if (mots.length > 1) for (const m of retenus) {
      for (const i of ids(normaliserNom(m))) parMot.set(i, (parMot.get(i) || 0) + 1);
    }  // un nom exact par mot, utile au repli seulement
    // Une commande composée peut être nommée sans ses tirets : « remote control connecter session ».
    for (let i = 0; i < retenus.length; i++) for (let taille = 2; taille <= 4 && i + taille <= retenus.length; taille++) {
      const morceau = retenus.slice(i, i + taille);
      if (!morceau.every(m => /^[a-z][a-z0-9]*$/.test(m))) continue;
      for (const id of ids(`/${morceau.join("-")}`)) parMot.set(id, (parMot.get(id) || 0) + 1);
    }
  } catch (e) { avis = t(ctx.langue, "avis.noms", { raison: texteErreur(e, ctx.langue) }); }
  const tete = await entete(ctx);
  const { entrees, categories_non_lues } = await toutesEntrees(ctx);
  const candidates = [];
  for (const e of entrees) {
    if (produit && !duProduit(e, produit)) continue;
    if (categorie && e.categorie !== categorie) continue;
    // local : le statut d'usage est celui de cette instance (bloc personnel)
    const avisLocal = estLocal(ctx) ? ctx.local.objet(e.identite) : null;
    if (statut && (estLocal(ctx) ? avisLocal?.statut_usage ?? "inconnu" : e.statut_usage) !== statut) continue;
    // D121 : le slug d’une méthode compte dans son nom ; les alias et efforts des modèles restent dans le texte indexé.
    const nom = e.categorie === "methodes"
      ? `${e.nom} ${String(e.id).replace(/^methode-/, "").replaceAll("-", " ")}`
      : e.categorie === "modeles"
        ? e.nom_modele
        : e.nom;
    const titre = sansAccents(nom);
    const textes = e.textes && e.textes.description ? Object.values(e.textes.description).map((x) => x && x.texte) : [];
    const commun = [nom, e.usage, e.description, e.description_source, ...textes, e.groupe, e.effort, e.executant, ...(e.aliases || [])].join(" ");
    // local : une seule requête cherche aussi dans l'avis de cette instance ; l'origine du fragment trouvé est rendue
    const perso = avisLocal ? [avisLocal.recommandation?.pourquoi, avisLocal.pour_toi, avisLocal.action, avisLocal.exemple_local].filter((x) => typeof x === "string").join(" ") : "";
    candidates.push([e, titre, indexer(nom), indexer(perso ? `${commun} ${perso}` : commun), perso ? [indexer(commun), indexer(perso)] : null]);
  }
  const classer = (liste) => liste.sort((a, b) => b[0] - a[0] || Number(a[1].categorie === "modeles") - Number(b[1].categorie === "modeles") || String(a[1].nom).localeCompare(String(b[1].nom)));
  const scores = [];
  const seuil = Math.max(1, Math.ceil(retenus.length / 2));
  let partiels = false;
  const litterale = retenus.length === 1 && (/^[-/]/.test(retenus[0]) || /[._:=]/.test(retenus[0]) || /-\d/.test(retenus[0]));
  const aExact = candidates.some(([e]) => exacts.has(e.id));
  const aLitterale = litterale && candidates.some(([, , , texte]) => presence(texte, retenus[0]));
  for (const [e, nom, titreIndexe, texte, parts] of candidates) {
    const aliasExact = e.categorie === "modeles" && (e.id === q || (Array.isArray(e.aliases) && e.aliases.some((a) => sansAccents(a) === q)));
    const exact = exacts.has(e.id) || aliasExact;
    if (aExact && !exact) continue;
    const commandeNommee = e.categorie === "commandes" && commandesParMot.has(e.id);
    const nomme = parMot.get(e.id) || 0;
    const complet = retenus.length > 0 && retenus.every(m => presence(texte, m));
    if (aLitterale && !exact && !complet) continue;
    const { trouves, poids } = pertinence(titreIndexe, texte, retenus, !complet);
    if (!exact && !commandeNommee && !nomme && (!retenus.length || trouves < seuil)) continue;
    let s = (exact ? 1e6 : commandeNommee ? 1e5 : 0) + poids + nomme * 500;
    if (nom === q) s += 100; else if (nom.startsWith(q)) s += 40; else if (nom.includes(q)) s += 20;
    if (e.commentee) s += 2;
    if (parts) e._trouve_dans = [["commun", parts[0]], ["personnel", parts[1]]].filter(([, x]) => retenus.some((m) => presence(x, m))).map(([c]) => c);
    scores.push([s, e]);
    if (!exact && !commandeNommee && !complet) partiels = true;
  }
  if (partiels) avis = [avis, t(ctx.langue, "avis.partiels")].filter(Boolean).join(" ; ");
  if (categories_non_lues.length) {
    avis = [avis, t(ctx.langue, "avis.incomplete", { liste: resumeNonLues(categories_non_lues) })].filter(Boolean).join(" ; ");
  }
  const aliasAmbigus = scores.filter(([, e]) => e.categorie === "modeles" && (e.aliases || []).some((a) => sansAccents(a) === q));
  if (aliasAmbigus.length > 1) avis = [avis, t(ctx.langue, "avis.alias_ambigu")].filter(Boolean).join(" ; ");
  classer(scores);
  let selection = scores;
  if (!categorie && scores.some(([, e]) => e.categorie !== "modeles") && scores.some(([, e]) => e.categorie === "modeles")) {
    const plafondModeles = Math.ceil(n / 2);
    if (n === 1) selection = scores.slice(0, 1);
    else {
      const documentation = scores.filter(([, e]) => e.categorie !== "modeles");
      const modeles = scores.filter(([, e]) => e.categorie === "modeles");
      const kD = Math.min(documentation.length, n - Math.min(modeles.length, plafondModeles));
      const kM = Math.min(modeles.length, n - kD);
      selection = [...documentation.slice(0, kD), ...modeles.slice(0, kM)];
      classer(selection);
    }
    if (scores.length > selection.length && !exacts.size) avis = [avis, t(ctx.langue, "avis.mixte", { affiches: selection.length, total: scores.length, plafond: plafondModeles })].filter(Boolean).join(" ; ");
  }
  const r = { ...tete, total: scores.length, resultats: selection.slice(0, n).map(([, e]) => {
    const f = fiche(e, ctx);
    if (estLocal(ctx)) f.trouve_dans = e._trouve_dans?.length ? e._trouve_dans : ["commun"];  // nom exact ou alias : la fiche commune
    return f;
  }) };
  if (categories_non_lues.length) r.categories_non_lues = categories_non_lues;
  if (avis) r.avis = avis;
  return r;
}

const RE_ID_FICHE = /^[A-Za-z0-9]+([._:/@-][A-Za-z0-9]+)*$/;

// Local, miroir commun indisponible : la couche personnelle reste consultable (conception §2.3), sans fiche commune,
// avis marqués à revoir (aucune compatibilité actuelle établie) ; l'indisponibilité du commun est dite dans `donnees`.
const communLocalIndisponible = (ctx) => estLocal(ctx) && ctx.local.generation().statut !== "disponible";

async function ficheReference({ id } = {}, ctx) {
  if (typeof id !== "string" || !RE_ID_FICHE.test(id)) throw new ErreurParametre("param.id");
  const tete = await entete(ctx);
  if (communLocalIndisponible(ctx)) {
    const identites = ctx.local.identitesPersonnelles(id);
    if (!identites.length) throw new ErreurTexte(`local.motif.${tete.donnees.commun.motif}`);
    return { ...tete, avis: t(ctx.langue, "local.personnel_seul"),
      fiches_personnelles: identites.map((i) => ({ identite: i, fiche: null, personnel: ctx.local.blocPersonnel(i, null, { complet: true }) })) };
  }
  const { entrees, categories_non_lues } = await toutesEntrees(ctx);
  const cible = id.toLowerCase();
  const canonique = entrees.find((x) => x.id === id || x.id === cible);
  const candidats = canonique ? [canonique] : entrees.filter((x) => x.categorie === "modeles" && (x.aliases || []).some((a) => a.toLowerCase() === cible));
  if (candidats.length > 1) return { ...tete, ambigu: true,
    avis: t(ctx.langue, "fiche.alias_ambigu"), candidats: candidats.map((e) => fiche(e, ctx)) };
  const e = candidats[0];
  if (!e && categories_non_lues.length) {
    throw new ErreurTexte("fiche.non_lues", { liste: resumeNonLues(categories_non_lues), id });
  }
  if (!e) throw new ErreurParametre("param.id_inconnu", { id });
  return { ...tete, fiche: fiche(e, ctx, true) };
}

// Versions : ancienne route = tableau historique (installée relevée sur une machine) ; référence commune = dernières
// versions publiées seules. Une installée absente vaut null et le statut « inconnu », jamais une comparaison supposée.
async function etatVersions(args, ctx) {
  const tete = await entete(ctx);
  if (communLocalIndisponible(ctx)) return { ...tete, avis: t(ctx.langue, "local.personnel_seul"),
    outils: ctx.local.versionsPersonnelles().map((v) => ({ outil: null, identite: v.identite, derniere_publiee: null, source_derniere: null,
      installee: v.installee, statut: "inconnu", releve_le: v.releve_le, methode: v.methode, note: null, couche_installee: "personnel" })) };
  const v = await lire("versions.json", ctx);
  if (formatCommun(ctx)) {
    if (!Array.isArray(v.entrees)) throw erreurFormat("versions.json");
    return { ...tete, outils: v.entrees.map((l) => {
      const commun = { outil: l.outil, identite: l.identite ?? null, derniere_publiee: l.derniere_publiee ?? null, source_derniere: l.source_derniere ?? null };
      // local : version relevée sur cette instance, comparée seulement à ce même fait commun ; sinon inconnue
      const i = estLocal(ctx) ? ctx.local.versionInstallee(l.identite, l) : null;
      if (i) return { ...commun, installee: i.installee, statut: i.statut, releve_le: i.releve_le, methode: i.methode, note: null, couche_installee: "personnel" };
      return { ...commun, installee: null, statut: "inconnu", releve_le: null,
        note: t(ctx.langue, estLocal(ctx) ? "versions.inconnue_local" : "versions.inconnue_commun") };
    }) };
  }
  if (!Array.isArray(v)) throw erreurFormat("versions.json");
  return { ...tete, outils: v.map((l) => {
    const installee = typeof l.version === "string" && l.version ? l.version : null;
    return { outil: l.outil, installee, derniere_publiee: l.derniere_publiee ?? null, statut: installee ? l.statut ?? "inconnu" : "inconnu",
      releve_le: installee ? l.detectee_le ?? null : null, note: l.note || l.raison || (installee ? null : t(ctx.langue, "versions.inconnue")) };
  }) };
}

const MAX_BASE = 30;

// Lit un fichier léger de la base (`kb/recent.json`, `kb/a-tester.json`) : absent, illisible ou de forme inattendue =
// erreur d'outil claire, jamais une liste vide muette.
async function fichierLeger(chemin, ctx) {
  const d = await lire(chemin, ctx);
  if (!d || typeof d !== "object" || !Array.isArray(d.entrees)) throw erreurFormat(chemin);
  return d;
}

const ligneBase = (e, ctx, avecPourquoi = false) => {
  const l = { id: e.id, nom: e.nom, produit: e.produit, categorie: e.categorie,
    syntaxe_ou_acces: e.usage_nature === "etapes" ? "acces" : "syntaxe", usage: court(e.usage, 400), exemple: court(e.exemple, 600),
    verdict: e.verdict ?? t(ctx.langue, "verdict.attente") };
  if (avecPourquoi) l.pourquoi = court(e.pourquoi);
  l.date_ajout = e.date_ajout ?? null;
  return l;
};

async function nouveautesBase({ jours = 7 } = {}, ctx) {
  if (!Number.isInteger(jours) || jours < 1 || jours > 30) throw new ErreurParametre("param.jours");
  const tete = await entete(ctx);
  // la génération commune ne publie pas encore de date d'ajout : réponse explicite, jamais une liste vide présentée comme complète
  if (formatCommun(ctx)) return { ...tete, jours, disponible: false, total: null, affichees: 0, entrees: [],
    avis: t(ctx.langue, "nouveautes.indisponible", { generation: estLocal(ctx) ? tete.donnees.commun.generation ?? "?" : tete.donnees.generation }) };
  const d = await fichierLeger("kb/recent.json", ctx);
  const depuis = new Date(Date.now() - jours * 864e5).toISOString().slice(0, 10);
  const fenetre = d.entrees.filter((e) => typeof e.date_ajout === "string" && e.date_ajout >= depuis);
  // recent.json garde au plus 150 entrées sur 30 jours : si la fenêtre demandée remonte avant la plus ancienne gardée, elle est coupée.
  const incomplet = d.tronque === true && (typeof d.plus_ancienne !== "string" || depuis <= d.plus_ancienne);
  const r = { ...tete, depuis, jours, genere_le: d.genere_le ?? null, total: fenetre.length, affichees: Math.min(fenetre.length, MAX_BASE),
    entrees: fenetre.slice(0, MAX_BASE).map((e) => ligneBase(e, ctx)) };
  if (incomplet) r.avis = t(ctx.langue, "avis.recent_tronque", { date: d.plus_ancienne ?? t(ctx.langue, "mot.inconnue") });
  return r;
}

const LIMITE_ESSAIS = 5, MAX_ESSAIS = 20;
const RE_CURSEUR = /^v1:[a-f0-9]{16}:[1-9][0-9]{0,8}$/;

async function aTester({ limite = LIMITE_ESSAIS, curseur, id } = {}, ctx) {
  if (!Number.isInteger(limite) || limite < 1 || limite > MAX_ESSAIS) throw new ErreurParametre("param.limite");
  if (curseur !== undefined && (typeof curseur !== "string" || !RE_CURSEUR.test(curseur))) throw new ErreurParametre("param.curseur");
  if (id !== undefined && (typeof id !== "string" || !RE_ID_FICHE.test(id))) throw new ErreurParametre("param.id_a_tester");
  if (id !== undefined && curseur !== undefined) throw new ErreurParametre("param.exclusifs");
  const tete = await entete(ctx);
  if (estLocal(ctx)) return aTesterLocal({ limite, curseur, id }, ctx, tete);
  // référence commune : aucun essai ni action personnels ; réponse vide explicite, sans copie de la liste de Sylvain
  if (ctx.source === "commun") {
    if (id !== undefined) throw new ErreurParametre("param.id_a_tester_inconnu");
    if (curseur !== undefined) throw new ErreurParametre("param.curseur_perime");
    return { ...tete, total: 0, affichees: 0, limite, curseur_suivant: null, actions_total: 0, actions: [],
      essais_base: { total: 0, affichees: 0, entrees: [] }, avis: t(ctx.langue, "a_tester.commun") };
  }
  const index = await derniersJours(ctx);
  const depuis = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10);
  const actions = [];
  for (const p of PERIMETRES) {
    if (index[p]?.erreur) throw new Error(index[p].erreur);
    const jours = (index[p]?.jours || []).map((j) => j.date).filter((d) => d >= depuis);
    for (const d of jours) {
      const q = await lire(`${p}/${d}.json`, ctx);
      for (const [position, e] of (q.elements || []).entries()) {
        if (!e.action) continue;
        const s = (e.sources || [])[0];
        actions.push({ id: `action:${p}:${d}:${position}`, id_element: e.id ?? null, date: d, produit: e.produit ?? null, date_publication: e.date_publication ?? null,
          titre: e.titre, impact: e.impact, action: e.action,
          source: s ? { url: s.url ?? null, libelle: s.libelle ?? null, officielle: s.officielle === true } : null });
      }
    }
  }
  actions.sort((a, b) => ["fort", "moyen", "faible", "nul"].indexOf(a.impact) - ["fort", "moyen", "faible", "nul"].indexOf(b.impact) || b.date.localeCompare(a.date));
  const base = await fichierLeger("kb/a-tester.json", ctx);  // déjà triée : verdict `tester` d'abord, puis `utiliser` pas encore essayées
  const restants = base.entrees.filter((e) => !e.essai);  // D119 : un essai déclaré fait par une mission n'est plus proposé
  if (id !== undefined) {
    const action = actions.find(e => e.id === id);
    if (action) return { ...tete, detail: action };
    if (restants.some(e => e.id === id)) return ficheReference({ id }, ctx);
    throw new ErreurParametre("param.id_a_tester_inconnu");
  }
  // Curseur lié au contenu : un catalogue modifié impose de recommencer, sans saut silencieux.
  const empreinte = createHash("sha256").update(JSON.stringify([actions, restants])).digest("hex").slice(0, 16);
  const debut = curseur === undefined ? 0 : Number(curseur.split(":")[2]);
  const total = actions.length + restants.length;
  if (curseur !== undefined && (curseur.split(":")[1] !== empreinte || debut >= total))
    throw new ErreurParametre("param.curseur_perime");
  const fin = Math.min(total, debut + limite);
  const pageActions = actions.slice(debut, fin).map(({ action, titre, source, ...e }) => ({ ...e, titre: court(titre, 160),
      source: source ? { ...source, url: court(source.url, 500), libelle: court(source.libelle, 160) } : null }));
  const pageBase = restants.slice(Math.max(0, debut - actions.length), Math.max(0, fin - actions.length))
    .map(e => ({ id: e.id, nom: court(e.nom, 160), produit: e.produit, categorie: e.categorie, verdict: e.verdict ?? null }));
  const essais = { total: restants.length, affichees: pageBase.length, entrees: pageBase };
  if (base.tronque === true) essais.avis = t(ctx.langue, "avis.essais_tronque");
  return { ...tete, avertissement: tete.avertissement + t(ctx.langue, "avertissement.a_tester"),
    total, affichees: fin - debut, limite, curseur_suivant: fin < total ? `v1:${empreinte}:${fin}` : null,
    actions_total: actions.length, actions: pageActions, essais_base: essais };
}

// Local : actions personnelles des 30 derniers jours de veille et fiches à essayer selon l'avis de cette instance, sans
// celles qui ont un essai déclaré (journal de la base ou essai OPÉRER). Même pagination liée au contenu que l'ancienne route.
async function aTesterLocal({ limite, curseur, id }, ctx, tete) {
  const depuis = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10);
  const actions = [];
  for (const p of PERIMETRES) {
    const v = await lire(`veille/${p}.json`, ctx);
    if (!Array.isArray(v.entrees)) throw erreurFormat(`veille/${p}.json`);
    for (const e of v.entrees) for (const pub of e.publications || []) {
      if (!pub || typeof pub.jour !== "string" || pub.jour < depuis) continue;
      const a = ctx.local.veille(e.identite, p, pub.jour, e);  // une action à revoir n'a plus d'action courante
      if (!a || !a.action) continue;
      const s = (pub.sources || [])[0];
      actions.push({ id: `action:${p}:${pub.jour}:${e.id}`, id_element: e.id, identite: e.identite, date: pub.jour, produit: pub.produit ?? null,
        date_publication: pub.date_publication ?? null, impact: a.impact, action: a.action,
        source: s ? { url: s.url ?? null, libelle: s.libelle ?? null, officielle: s.officielle === true } : null });
    }
  }
  actions.sort((a, b) => IMPACTS.indexOf(a.impact) - IMPACTS.indexOf(b.impact) || b.date.localeCompare(a.date) || a.id.localeCompare(b.id));
  const { entrees } = await toutesEntrees(ctx);
  const parIdentite = new Map(entrees.map((e) => [e.identite, e]));
  const restants = ctx.local.aTester(parIdentite).filter((x) => parIdentite.has(x.identite));
  if (id !== undefined) {
    const action = actions.find((e) => e.id === id);
    if (action) return { ...tete, detail: action };
    if (restants.some((e) => e.id === id)) return ficheReference({ id }, ctx);
    throw new ErreurParametre("param.id_a_tester_inconnu");
  }
  const empreinte = createHash("sha256").update(JSON.stringify([actions, restants])).digest("hex").slice(0, 16);
  const debut = curseur === undefined ? 0 : Number(curseur.split(":")[2]);
  const total = actions.length + restants.length;
  if (curseur !== undefined && (curseur.split(":")[1] !== empreinte || debut >= total)) throw new ErreurParametre("param.curseur_perime");
  const fin = Math.min(total, debut + limite);
  const pageActions = actions.slice(debut, fin).map(({ action, ...e }) => ({ ...e, action: court(action, 400) }));
  const pageBase = restants.slice(Math.max(0, debut - actions.length), Math.max(0, fin - actions.length)).map((x) => {
    const e = parIdentite.get(x.identite);
    return { id: e.id, identite: x.identite, nom: court(e.nom, 160), produit: e.produit, categorie: e.categorie, couche_verdict: "personnel", verdict: x.verdict };
  });
  return { ...tete, avertissement: tete.avertissement + t(ctx.langue, "avertissement.a_tester_local"),
    total, affichees: fin - debut, limite, curseur_suivant: fin < total ? `v1:${empreinte}:${fin}` : null,
    actions_total: actions.length, actions: pageActions, essais_base: { total: restants.length, affichees: pageBase.length, entrees: pageBase } };
}

const LECTURE = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false };
// Schémas des six outils ; titres et descriptions viennent du dictionnaire de la langue demandée (lib/textes.js).
const SCHEMAS = {
  resume_du_jour: { f: resumeDuJour, proprietes: {
    date: { type: "string", pattern: "^\\d{4}-\\d{2}-\\d{2}$" }, inclure_faibles: { type: "boolean", default: false } } },
  chercher_reference: { f: chercherReference, requis: ["requete"], proprietes: {
    requete: { type: "string", minLength: 1 }, produit: { type: "string", enum: PRODUITS }, categorie: { type: "string", enum: CATEGORIES },
    statut: { type: "string", enum: STATUTS }, limite: { type: "integer", minimum: 1, maximum: 20, default: 8 } } },
  fiche_reference: { f: ficheReference, requis: ["id"], proprietes: { id: { type: "string", pattern: RE_ID_FICHE.source } } },
  etat_versions: { f: etatVersions, proprietes: {} },
  a_tester: { f: aTester, proprietes: {
    limite: { type: "integer", minimum: 1, maximum: MAX_ESSAIS, default: LIMITE_ESSAIS }, curseur: { type: "string", pattern: RE_CURSEUR.source },
    id: { type: "string", pattern: RE_ID_FICHE.source } } },
  nouveautes_base: { f: nouveautesBase, proprietes: { jours: { type: "integer", minimum: 1, maximum: 30, default: 7 } } },
};
function outils(langue, source) {
  return Object.fromEntries(Object.entries(SCHEMAS).map(([nom, o]) => {
    const properties = Object.fromEntries(Object.entries(o.proprietes).map(([p, s]) => [p, { ...s, description: t(langue, `outil.${nom}.${p}`) }]));
    // paramètre de langue commun aux six outils (décision du 22/10) : défaut = langue du serveur ou de son adresse
    properties.langue = { type: "string", enum: LANGUES, default: langue, description: t(langue, "outil.langue") };
    const inputSchema = { type: "object", ...(o.requis ? { required: o.requis } : {}), properties, additionalProperties: false };
    // local : la description dit ce que rend la couche personnelle de cette instance
    const description = t(langue, `outil.${nom}.description`) + (source === "local" ? t(langue, `outil.${nom}.local`) : "");
    return [nom, { f: o.f, titre: t(langue, `outil.${nom}.titre`), description, inputSchema }];
  }));
}
const OUTILS = outils("fr");

class ErreurParametre extends ErreurTexte {}

// ---------------------------------------------------------------------------------------------- JSON-RPC

async function traiter(msg, mesure = {}, ctx = contexteDefaut()) {
  if (!msg || msg.jsonrpc !== "2.0" || typeof msg.method !== "string") return erreur(msg?.id ?? null, -32600, t(ctx.langue, "rpc.invalide"));
  const { id, method } = msg;
  const params = msg.params && typeof msg.params === "object" ? msg.params : {};
  const notification = id === undefined || id === null;
  switch (method) {
    case "initialize":
      return ok(id, { protocolVersion: typeof params.protocolVersion === "string" ? params.protocolVersion : PROTOCOLE,
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: "delta", title: t(ctx.langue, "init.titre"), version: VERSION },
        instructions: ctx.source === "local" ? t(ctx.langue, "init.instructions_local", { site: CONFIG.site_public_url })
          : t(ctx.langue, "init.instructions", { site: CONFIG.site_public_url, source: ctx.source }) });
    case "ping":
      return ok(id, {});
    case "tools/list":
      return ok(id, { tools: Object.entries(outils(ctx.langue, ctx.source)).map(([name, o]) => ({ name, title: o.titre, description: o.description,
        inputSchema: o.inputSchema, annotations: LECTURE })) });
    case "tools/call": {
      const o = SCHEMAS[params.name];
      if (!o) return erreur(id, -32602, t(ctx.langue, "rpc.outil_inconnu", { nom: params.name }));
      const { langue, ...args } = params.arguments || {};
      let c = ctx;
      try {
        if (langue !== undefined && !LANGUES.includes(langue)) throw new ErreurParametre("param.langue");
        c = { ...ctx, langue: langue ?? ctx.langue };
        const r = await o.f(args, c);
        if (params.name === "chercher_reference") mesure.nb_resultats = typeof r.total === "number" ? r.total : null;
        if (params.name === "a_tester") mesure.nb_resultats = Number.isInteger(r.affichees) ? r.affichees : r.detail || r.fiche ? 1 : null;
        return ok(id, { content: [{ type: "text", text: JSON.stringify(r, null, 1) }], structuredContent: r, isError: false });
      } catch (e) {
        const cle = e instanceof ErreurParametre ? "erreur.parametre" : c.source === "local" ? "erreur.local" : c.source === "commun" ? "erreur.commun" : "erreur.donnees";
        return ok(id, { content: [{ type: "text", text: t(c.langue, cle, { message: texteErreur(e, c.langue) }) }], isError: true });
      }
    }
    default:
      if (notification) return null;  // notifications/initialized, notifications/cancelled…
      return erreur(id, -32601, t(ctx.langue, "rpc.methode", { methode: method }));
  }
}
// ---------------------------------------------------------------------------------------------- journal (D66)
// Une ligne JSON par requête JSON-RPC, lue seulement dans les journaux Vercel : méthode, outil, client (clientInfo
// d'initialize), durée, statut, démarrage à froid, nombre de résultats. Jamais d'argument, de requête de recherche,
// de corps de réponse, d'en-tête, d'adresse IP, de User-Agent ni de session. Le serveur n'écrit que le compteur agrégé
// et anonyme de lib/compteur.js, dérivé de ces lignes, quand le stockage Upstash est relié.
// Méthodes nommées dans le journal : les quatre que le serveur traite, puis celles que les clients envoient et qui lui sont
// inutiles (notifications sans réponse, sondes resources/prompts qui reçoivent -32601, ce qui est la bonne réponse : le serveur
// ne déclare ni resources ni prompts). Toute autre notification vaut « notification », tout le reste « autre ».
const METHODES = new Set(["initialize", "tools/list", "tools/call", "ping", "notifications/initialized", "notifications/cancelled",
  "resources/list", "resources/templates/list", "prompts/list"]);
let froid = true;  // première requête traitée par cette instance

function ligneJournal(msg, reponse, mesure, duree) {
  const sansId = msg && (msg.id === undefined || msg.id === null);
  const methode = !msg || typeof msg.method !== "string" ? "autre" : METHODES.has(msg.method) ? msg.method
    : sansId && msg.method.startsWith("notifications/") ? "notification" : "autre";
  const texte = (v) => (typeof v === "string" ? v.slice(0, 80) : null);
  const info = methode === "initialize" && msg.params && typeof msg.params.clientInfo === "object" ? msg.params.clientInfo : null;
  const outil = methode === "tools/call" && msg.params && typeof msg.params.name === "string" && OUTILS[msg.params.name] ? msg.params.name
    : methode === "tools/call" ? "inconnu" : null;
  const l = { methode, outil, client: info ? { name: texte(info.name), version: texte(info.version) } : null,
    // erreur JSON-RPC : son code ; outil qui répond isError (paramètre invalide, données indisponibles) : "erreur_outil"
    duree_ms: Math.round(duree), statut: reponse && reponse.error ? reponse.error.code : reponse && reponse.result && reponse.result.isError ? "erreur_outil" : "ok",
    demarrage_froid: froid, nb_resultats: mesure.nb_resultats ?? null };
  froid = false;
  return l;
}

// `lignes` (facultatif) recueille les lignes du journal pour le compteur agrégé (lib/compteur.js).
async function traiterJournalise(msg, lignes, ctx = contexteDefaut()) {
  const debut = performance.now();
  const mesure = {};
  const reponse = await traiter(msg, mesure, ctx);
  const ligne = ligneJournal(msg, reponse, mesure, performance.now() - debut);
  console.log(JSON.stringify(ligne));
  if (lignes) lignes.push(ligne);
  return reponse;
}

const ok = (id, result) => (id === undefined || id === null ? null : { jsonrpc: "2.0", id, result });
const erreur = (id, code, message) => ({ jsonrpc: "2.0", id, error: { code, message } });

async function lireCorps(req) {
  if (req.body !== undefined) return typeof req.body === "string" ? JSON.parse(req.body) : req.body;
  const morceaux = [];
  let taille = 0;
  for await (const m of req) { taille += m.length; if (taille > 256 * 1024) throw new ErreurTexte("rpc.json"); morceaux.push(m); }
  return JSON.parse(Buffer.concat(morceaux).toString("utf8") || "null");
}

// `?langue=fr` et `?source=commun` sur l'adresse du serveur fixent la langue et la source par défaut de la session du client ;
// une valeur inconnue est ignorée (défauts du serveur). Rien de ces paramètres n'entre dans le journal ni le compteur.
function contexteRequete(req) {
  const ctx = contexteDefaut();
  let q;
  try { q = new URL(req.url || "/", "http://local").searchParams; } catch { return ctx; }
  const langue = q.get("langue") || q.get("lang");
  if (LANGUES.includes(langue)) ctx.langue = langue;
  if (SOURCES.includes(q.get("source"))) ctx.source = q.get("source");
  return ctx;
}

export default async function handler(req, res) {
  const ctx = contexteRequete(req);
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "content-type, mcp-protocol-version, mcp-session-id, authorization");
  res.setHeader("Access-Control-Allow-Methods", "POST, GET, OPTIONS");
  if (req.method === "OPTIONS") { res.statusCode = 204; return res.end(); }
  if (req.method !== "POST") {  // pas de flux SSE : serveur sans état, réponses JSON uniquement
    res.statusCode = 405; res.setHeader("Allow", "POST, OPTIONS");
    return res.end(JSON.stringify({ jsonrpc: "2.0", id: null, error: { code: -32000, message: t(ctx.langue, "rpc.post") } }));
  }
  let corps;
  try { corps = await lireCorps(req); } catch (e) {
    res.statusCode = 400; res.setHeader("Content-Type", "application/json");
    const r = erreur(null, -32700, t(ctx.langue, "rpc.json"));
    const ligne = ligneJournal(null, r, {}, 0);
    console.log(JSON.stringify(ligne));
    compter([ligne]);
    return res.end(JSON.stringify(r));
  }
  const lot = Array.isArray(corps);
  const lignes = [];
  const reponses = (await Promise.all((lot ? corps : [corps]).map((m) => traiterJournalise(m, lignes, ctx)))).filter(Boolean);
  compter(lignes);  // lancé sans attendre : la réponse au client ne dépend pas du stockage
  if (!reponses.length) { res.statusCode = 202; return res.end(); }
  res.statusCode = 200;
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify(lot ? reponses : reponses[0]));
}

export { traiter, traiterJournalise, OUTILS, outils };
