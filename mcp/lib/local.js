// Lecteur local des deux couches (lot L4, conception §2.1, §2.2, §4.1) : génération commune du miroir de l'instance et
// magasin personnel, lus sur disque, sans écriture ni appel de modèle. Utilisé par le MCP stdio (stdio.js) et l'adaptateur
// du Bureau (bureau.js) ; jamais par le serveur HTTP public (api/mcp.js n'importe pas ce module et ne reçoit la source
// `local` que d'un contexte construit ici).
// Racines : mêmes trois sources que scripts/deltalib/couches/racines.py (profil K1, environnement DELTA_INSTANCE,
// installation historique sur demande), sans découverte d'une autre instance.
// Invalidation : pointeur de génération et fichiers personnels relus dès que leur date ou leur taille change ; une fiche dont
// l'empreinte commune diffère de celle de l'avis rend cet avis `a_revoir`, présenté comme précédent, jamais comme conseil courant.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import CONFIG from "./config.js";
import { ErreurTexte, t } from "./textes.js";

const COMPOSANT = "delta-ia";
const DEFAUTS_K1 = { configuration: ".config/delta", etat: ".local/state/delta", cache: ".cache/delta", runtime: ".local/run/delta" };
const CHAMPS_K1 = new Set(["schema", "version", "identite", "mode", "home", "racines", "executables", "path", "venv",
  "prefixe_node", "superviseur", "composants", "projets"]);
const RACINES_K1 = new Set(["code", "configuration", "etat", "cache", "runtime", "lanceurs"]);
const XDG = { configuration: ["XDG_CONFIG_HOME", ".config"], etat: ["XDG_STATE_HOME", ".local/state"],
  cache: ["XDG_CACHE_HOME", ".cache"], runtime: ["XDG_RUNTIME_DIR", ".local/run"] };
const RE_GENERATION = /^g-[0-9a-f]{16}$/;
const VERDICTS_A_TESTER = ["tester", "utiliser"];

const absolu = (v, quoi) => {
  if (typeof v !== "string" || !v || !path.isAbsolute(v) || v.split(path.sep).includes("..")) throw new ErreurTexte("local.racine", { quoi });
  return v;
};
const dedans = (p, home) => p.startsWith(home.endsWith(path.sep) ? home : home + path.sep);

// Racines d'instance : { configuration, etat, cache, runtime, origine } ; refus explicite sans source désignée.
export function resoudreRacines({ instance, historique = false, env = process.env, home = os.homedir() } = {}) {
  if (instance) {
    let d;
    try { d = JSON.parse(fs.readFileSync(instance, "utf8")); } catch { throw new ErreurTexte("local.profil_illisible"); }
    if (!d || typeof d !== "object" || Array.isArray(d) || Object.keys(d).some((k) => !CHAMPS_K1.has(k))) throw new ErreurTexte("local.profil_forme");
    if (d.schema !== "delta.instance" || d.version !== 1) throw new ErreurTexte("local.profil_forme");
    if (typeof d.identite !== "string" || !/^[a-z][a-z0-9-]{0,47}$/.test(d.identite)) throw new ErreurTexte("local.profil_forme");
    const h = absolu(d.home, "home");
    const declarees = d.racines ?? {};
    if (!declarees || typeof declarees !== "object" || Object.keys(declarees).some((k) => !RACINES_K1.has(k))) throw new ErreurTexte("local.profil_forme");
    const r = { origine: "instance" };
    for (const [nom, defaut] of Object.entries(DEFAUTS_K1)) {
      const p = nom in declarees ? absolu(declarees[nom], nom) : path.join(h, defaut, d.identite);
      if (!dedans(p, h)) throw new ErreurTexte("local.racine", { quoi: nom });
      r[nom] = p;
    }
    return r;
  }
  if (env.DELTA_INSTANCE) {
    const r = { origine: "environnement" };
    for (const [nom, [v]] of Object.entries(XDG)) {
      if (!env[v]) throw new ErreurTexte("local.environnement", { variable: v });
      r[nom] = absolu(env[v], v);
    }
    return r;
  }
  if (historique) {
    const r = { origine: "historique" };
    for (const [nom, [v, defaut]] of Object.entries(XDG)) r[nom] = path.join(env[v] ? env[v] : path.join(home, defaut), "delta");
    return r;
  }
  throw new ErreurTexte("local.sans_racines");
}

export const emplacements = (r) => ({
  personnel: path.join(r.etat, COMPOSANT, "personnel"), commun: path.join(r.cache, COMPOSANT, "commun"),
  commun_actif: path.join(r.etat, COMPOSANT, "commun-actif.json"), synchro: path.join(r.etat, COMPOSANT, "synchro.json") });

const sha256 = (b) => createHash("sha256").update(b).digest("hex");
const signature = (f) => { try { const s = fs.statSync(f); return `${s.mtimeMs}:${s.size}`; } catch { return null; } };
const lireJsonFichier = (f) => JSON.parse(fs.readFileSync(f, "utf8"));
const age = (iso, maintenant) => { const t = Date.parse(iso ?? ""); return Number.isNaN(t) ? null : (maintenant - t) / 36e5; };

// Même règle que publication.fraicheur (Python) : la pire des deux dates (vérification du miroir, publication) ;
// sans aucune des deux (instance productrice), le dernier jour des données.
export function fraicheurLocale(verifie_le, publie_le, donnees_du, maintenant = Date.now(), s = CONFIG.fraicheur) {
  let ages = [age(verifie_le, maintenant), age(publie_le, maintenant)].filter((a) => a !== null);
  if (!ages.length && typeof donnees_du === "string") ages = [age(`${donnees_du}T23:59:59+00:00`, maintenant)].filter((a) => a !== null);
  if (!ages.length) return null;
  const pire = Math.max(...ages);
  return pire > s.tres_ancienne_j * 24 ? "tres_ancienne" : pire > s.ancienne_h ? "ancienne" : "recente";
}

// Dernière valeur importée d'un champ personnel (historique_importe, dans l'ordre d'import), ou undefined.
function importe(o, champ, fichier) {
  let v;
  for (const h of o?.historique_importe || []) if ((!fichier || h.fichier === fichier) && h.champs && Object.hasOwn(h.champs, champ)) v = h.champs[champ];
  return v;
}

// Id d'origine d'une identité de fiche : `kb:claude:<id>` → `<id>`, `kb:delta:modeles:<id>` → `<id>`.
export const idCourt = (identite) => (identite.startsWith("kb:delta:") ? identite.split(":").slice(3) : identite.split(":").slice(2)).join(":");

export class LecteurLocal {
  constructor(racines, { maintenant } = {}) {
    this.racines = racines;
    this.e = emplacements(racines);
    this.maintenant = maintenant;
    this.sig = {};
    this.verifies = new Map();
  }

  heure() { return this.maintenant ?? Date.now(); }

  // --- couche commune : pointeur, manifeste et fichiers vérifiés (taille, SHA-256, schéma) ---
  generation() {
    const s = signature(this.e.commun_actif) + "|" + signature(this.e.synchro);
    if (this.sig.commun !== s || !this.g) {
      this.sig.commun = s;
      this.verifies.clear();
      this.g = this.chargerGeneration();
    }
    // la fraîcheur dépend de l'heure de la lecture, pas du chargement : un serveur stdio vit toute une session
    if (this.g.statut === "disponible") this.g.fraicheur = fraicheurLocale(this.g.verifie_le, this.g.publie_le, this.g.donnees_du, this.heure());
    return this.g;
  }

  chargerGeneration() {
    let actif;
    try { actif = lireJsonFichier(this.e.commun_actif); } catch { return { statut: "indisponible", motif: "aucune_generation" }; }
    if (!actif || actif.schema !== "delta.commun" || actif.vue !== "actif") return { statut: "indisponible", motif: "pointeur_illisible" };
    if (actif.schema_version !== 1) return { statut: "indisponible", motif: "version_inconnue" };
    if (!RE_GENERATION.test(String(actif.generation))) return { statut: "indisponible", motif: "pointeur_illisible" };
    const dossier = path.join(this.e.commun, actif.generation);
    let octets;
    try { octets = fs.readFileSync(path.join(dossier, "manifest.json")); } catch { octets = null; }
    if (!octets || sha256(octets) !== actif.manifest_sha256) return { statut: "indisponible", motif: "manifeste_different" };
    const manifeste = JSON.parse(octets.toString("utf8"));
    if (manifeste.schema !== "delta.manifest" || manifeste.schema_version !== 1) return { statut: "indisponible", motif: "version_inconnue" };
    let verifie_le = null, erreur_synchro = null;
    const publie_le = actif.origine === "synchro" ? actif.publie_le ?? null : manifeste.publie_le ?? null;
    if (actif.origine === "synchro") {
      try { const s = lireJsonFichier(this.e.synchro); verifie_le = s.verifie_le ?? null; erreur_synchro = s.erreur ?? null; } catch { /* aucune vérification connue */ }
    }
    return { statut: "disponible", generation: actif.generation, origine: actif.origine ?? null, dossier, manifeste, publie_le, verifie_le,
      erreur_synchro, donnees_du: manifeste.donnees_du ?? null, langues: Array.isArray(manifeste.langues) ? manifeste.langues : [],
      fichiers: new Map((manifeste.fichiers || []).map((f) => [f.chemin, f])), fraicheur: null };
  }

  lireCommun(chemin) {
    const g = this.generation();
    if (g.statut !== "disponible") throw new ErreurTexte(`local.motif.${g.motif}`);
    if (this.verifies.has(chemin)) return this.verifies.get(chemin);
    const attendu = g.fichiers.get(chemin);
    if (!attendu) throw new ErreurTexte("couche.fichier_absent", { chemin, generation: g.generation });
    const f = path.join(g.dossier, chemin);
    if (!f.startsWith(g.dossier + path.sep)) throw new ErreurTexte("couche.fichier_absent", { chemin, generation: g.generation });
    let octets;
    try { octets = fs.readFileSync(f); } catch { throw new ErreurTexte("couche.empreinte", { chemin, generation: g.generation }); }
    if (octets.length !== attendu.taille || sha256(octets) !== attendu.sha256) throw new ErreurTexte("couche.empreinte", { chemin, generation: g.generation });
    const doc = JSON.parse(octets.toString("utf8"));
    if (doc.schema !== "delta.commun" || doc.schema_version !== 1)
      throw new ErreurTexte("couche.schema", { fichier: chemin, schema: doc.schema ?? "?", version: doc.schema_version ?? "?", attendu: "delta.commun v1" });
    this.verifies.set(chemin, doc);
    return doc;
  }

  // --- couche personnelle : overlay (import L1), couples modèle × effort et essais OPÉRER (L4) ---
  personnel() {
    const f = { overlay: path.join(this.e.personnel, "overlay.json"), couples: path.join(this.e.personnel, "modeles-efforts.json"),
      bilan: path.join(this.e.personnel, "reglages-bilan.json"), essais: path.join(this.e.personnel, "essais-operer.json") };
    const s = Object.values(f).map(signature).join("|");
    if (this.sig.personnel === s && this.p) return this.p;
    this.sig.personnel = s;
    const p = { statut: "absent", objets: null, couples: null, essais: null, bilan: null };
    try {
      const d = lireJsonFichier(f.overlay);
      if (d?.schema === "delta.personnel" && d.schema_version === 1 && d.vue === "overlay" && d.objets && typeof d.objets === "object") {
        p.statut = "disponible"; p.objets = d.objets; p.commun_generation = d.commun_generation ?? null;
      } else p.statut = "invalide";
    } catch (e) { p.statut = e.code === "ENOENT" ? "absent" : "illisible"; }
    try {
      const d = lireJsonFichier(f.couples);
      if (d?.vue === "modeles_efforts" && d.schema_version === 1 && d.objets) p.couples = d;
    } catch { /* aucune projection : constats indisponibles */ }
    try {
      // l'instantané brut (missions et événements) reste privé et volumineux : seules ses métadonnées sont gardées ici
      const d = lireJsonFichier(f.bilan);
      if (d?.vue === "reglages_bilan" && d.schema_version === 1)
        p.bilan = { sha256: d.sha256, filtres: d.filtres, jusqu_au: d.jusqu_au ?? null, lu_le: d.lu_le ?? null, lignes_ignorees: d.lignes_ignorees ?? null,
          missions: d.bilan?.missions ?? null, groupes: Array.isArray(d.bilan?.groupes) ? d.bilan.groupes.length : null };
    } catch { /* aucun instantané */ }
    try {
      const d = lireJsonFichier(f.essais);
      if (d?.vue === "essais_operer" && Array.isArray(d.essais)) p.essais = { lu_le: d.lu_le ?? null, essais: d.essais };
    } catch { /* aucun instantané */ }
    this.p = p;
    return p;
  }

  // Étiquette de la réponse : chaque couche avec ses dates, jamais une racine « commun » pour une réponse composée.
  blocDonnees(langue) {
    const g = this.generation(), p = this.personnel();
    const commun = g.statut !== "disponible" ? { couche: "commun", statut: "indisponible", motif: g.motif, motif_texte: t(langue, `local.motif.${g.motif}`) }
      : { couche: "commun", statut: "disponible", generation: g.generation, origine: g.origine, publie_le: g.publie_le, verifie_le: g.verifie_le,
          donnees_du: g.donnees_du, fraicheur: g.fraicheur, langues: g.langues, ...(g.erreur_synchro ? { derniere_erreur_synchro: g.erreur_synchro } : {}) };
    const personnel = { couche: "personnel", statut: p.statut, commun_generation: p.commun_generation ?? null,
      bilan_operer: p.bilan ? { statut: "disponible", sha256: p.bilan.sha256, filtres: p.bilan.filtres, jusqu_au: p.bilan.jusqu_au, lu_le: p.bilan.lu_le }
        : { statut: "absent" },
      essais_operer: p.essais ? { statut: "disponible", lu_le: p.essais.lu_le, total: p.essais.essais.length } : { statut: "absent" } };
    return { source: "local", langue, commun, personnel };
  }

  // Identités personnelles d'un id de fiche (`kb:<périmètre>:<id>`, `kb:delta:<famille>:<id>`), pour lire la couche
  // personnelle quand le miroir commun est indisponible (conception §2.3 : le personnel indépendant reste consultable).
  identitesPersonnelles(id) {
    const p = this.personnel();
    if (p.statut !== "disponible") return [];
    return Object.keys(p.objets).filter((i) => i === id || (i.startsWith("kb:") && idCourt(i) === id)).sort();
  }

  // Versions relevées sur cette instance, sans le fait commun (miroir indisponible) : rien n'est comparé.
  versionsPersonnelles() {
    const p = this.personnel();
    if (p.statut !== "disponible") return [];
    return Object.keys(p.objets).filter((i) => i.startsWith("version:")).sort().map((i) => ({ identite: i, ...this.versionInstallee(i, null) }))
      .filter((v) => v.installee).map((v) => ({ ...v, statut: "inconnu" }));
  }

  objet(identite) { const p = this.personnel(); return p.statut === "disponible" ? p.objets[identite] ?? null : null; }

  // Essais d'une fiche : journal des essais de la base (importé) et essais OPÉRER qui la nomment ; chacun garde sa source.
  essais(identite, id) {
    const o = this.objet(identite);
    const base = (o?.essais || []).map((e) => ({ source: e.source ?? "kb-essais.yaml", date: e.date ?? null, par: e.par ?? null, rapport: e.rapport ?? null }));
    const p = this.personnel();
    const operer = (p.essais?.essais || []).filter((e) => e?.protocole?.fiche === id || e?.protocole?.fiche === identite).map((e) => ({
      source: "operer", id: e.id ?? null, version: e.protocole?.version ?? null, titre: e.protocole?.titre ?? null, statut: e.statut ?? null,
      maturite: e.maturite ?? null, issue: e.clos?.issue ?? null, clos_le: e.clos?.ts ?? null, lecon_apprendre: e.clos?.lecon ?? null }));
    return [...base, ...operer];
  }

  // Statut courant d'un avis (même règle que Lecteur.bloc_personnel) : commun indisponible, fait commun modifié, fiche
  // absente, commun très ancien. Seul `importe` est un conseil courant ; il vaut pour les fiches comme pour la veille.
  statutAvis(o, fiche) {
    const g = this.generation();
    if (g.statut !== "disponible" && o.statut === "importe") return { statut: "a_revoir", motif: "commun_indisponible" };
    if (fiche && o.commun_empreinte && fiche.empreinte && o.commun_empreinte !== fiche.empreinte) return { statut: "a_revoir", motif: "commun_modifie" };
    if (!fiche && o.statut === "importe" && o.commun_empreinte) return { statut: "reference_introuvable", motif: "fiche_absente" };
    if (o.statut === "importe" && g.fraicheur === "tres_ancienne") return { statut: "a_revoir", motif: "commun_tres_ancien" };
    return { statut: o.statut, motif: null };
  }

  // Bloc personnel d'une fiche : statut, dates et avis séparés de la fiche commune.
  blocPersonnel(identite, fiche, { complet = false } = {}) {
    const p = this.personnel();
    if (p.statut !== "disponible") return { couche: "personnel", statut: "non_personnalise", magasin: p.statut, avis: null };
    const o = p.objets[identite];
    // sans fiche commune (miroir indisponible), l'id court vient de l'identité : les essais OPÉRER le citent ainsi
    const essais = this.essais(identite, fiche?.id ?? idCourt(identite));
    if (!o) return { couche: "personnel", statut: "non_personnalise", magasin: "disponible", avis: null, ...(essais.length ? { essais } : {}) };
    const { statut, motif } = this.statutAvis(o, fiche);
    const rec = o.recommandation && typeof o.recommandation === "object" ? o.recommandation : null;
    const reev = (o.reevaluations || []).filter((r) => typeof r?.date === "string").map((r) => r.date).sort();
    const evalue_le = o.evalue_le ?? reev.at(-1) ?? null;
    const avis = { statut_usage: o.statut_usage ?? null, verdict: rec?.verdict ?? null, pourquoi: rec?.pourquoi ?? null,
      pour_toi: o.pour_toi ?? null, action: o.action ?? null, exemple_local: o.exemple_local ?? null };
    const courant = statut === "importe";
    const b = { couche: "personnel", statut, ...(motif ? { motif } : {}), observe_le: o.observe_le ?? null, evalue_le,
      evalue_le_origine: o.evalue_le ? "avis" : reev.length ? "reevaluation" : null, commun_empreinte_avis: o.commun_empreinte ?? null,
      // un avis à revoir reste lisible comme précédent, jamais comme conseil courant
      avis: courant ? avis : null, ...(courant ? {} : { avis_precedent: avis }), essais };
    if (complet) Object.assign(b, { reevaluations: o.reevaluations || [], rejugements: o.rejugements || [], historique_importe: o.historique_importe || [] });
    return b;
  }

  // Constats de cette instance pour un couple modèle × effort (projection du bilan OPÉRER) : groupes par nature et
  // exécutant tels que la source les donne ; absence ≠ zéro.
  constatsCouple(identite, fiche) {
    const p = this.personnel();
    if (!p.couples) return { statut: "indisponible", motif: p.bilan ? "projection_absente" : "bilan_absent", groupes: [] };
    const c = p.couples, o = c.objets[identite];
    const base = { bilan_empreinte: c.bilan_empreinte, filtres: c.filtres ?? null, observe_le: c.observe_le ?? null, jusqu_au: c.jusqu_au ?? null,
      source: "operer reglages bilan --json" };
    if (p.bilan && p.bilan.sha256 !== c.bilan_empreinte) return { statut: "a_revoir", motif: "projection_anterieure_au_bilan", ...base, groupes: o?.groupes ?? [] };
    if (!o) return { statut: "aucune_observation", ...base, groupes: [] };
    if (fiche?.empreinte && o.commun_empreinte && fiche.empreinte !== o.commun_empreinte) return { statut: "a_revoir", motif: "commun_modifie", ...base, groupes: o.groupes };
    return { statut: "disponible", ...base, groupes: o.groupes };
  }

  // Version installée relevée sur cette instance (import des relevés), comparée seulement au même fait commun.
  versionInstallee(identite, entree) {
    const o = this.objet(identite);
    const version = importe(o, "version");
    if (typeof version !== "string" || !version) return null;
    const perime = entree?.empreinte && o.commun_empreinte && entree.empreinte !== o.commun_empreinte;
    return { installee: version, releve_le: importe(o, "detectee_le") ?? null, methode: importe(o, "methode") ?? null,
      statut: perime ? "a_revoir" : importe(o, "statut") ?? "inconnu" };
  }

  // Avis du jour d'un élément de veille (impact, pour_toi, action importés de ce quotidien), validé comme l'avis d'une
  // fiche sur l'entrée commune `entree` : un avis à revoir n'a ni impact ni action courants, il reste en `avis_precedent`.
  veille(identite, perimetre, jour, entree) {
    const o = this.objet(identite);
    if (!o) return null;
    const fichier = `docs/data/${perimetre}/${jour}.json`;
    const impact = importe(o, "impact", fichier);
    if (impact === undefined) return null;
    const avis = { impact: impact ?? null, pour_toi: importe(o, "pour_toi", fichier) ?? null, action: importe(o, "action", fichier) ?? null,
      projets_concernes: importe(o, "projets_concernes", fichier) ?? [] };
    const { statut, motif } = this.statutAvis(o, entree ?? null);
    if (statut === "importe") return { statut, ...avis, observe_le: jour };
    return { statut, motif, impact: null, pour_toi: null, action: null, projets_concernes: [], observe_le: jour, avis_precedent: avis };
  }

  // Fiches proposées à l'essai : verdict local `tester` puis `utiliser`, pas encore utilisées, sans essai déclaré, et dont
  // l'avis est courant pour la fiche commune actuelle (`fiches` : identité → fiche) ; un avis à revoir n'est jamais proposé.
  aTester(fiches = new Map()) {
    const p = this.personnel();
    if (p.statut !== "disponible") return [];
    const out = [];
    for (const [identite, o] of Object.entries(p.objets)) {
      // fiches de la documentation des éditeurs seulement : l'avis d'un couple modèle × effort est une recommandation de
      // routage, pas un essai à proposer (comme kb/a-tester.json)
      if (!/^kb:(claude|openai):/.test(identite) || o.statut !== "importe") continue;
      const verdict = o.recommandation?.verdict;
      if (!VERDICTS_A_TESTER.includes(verdict) || o.statut_usage === "utilise") continue;
      const id = idCourt(identite);
      if (this.essais(identite, id).length) continue;  // D119 : un essai déclaré n'est plus proposé
      if (this.blocPersonnel(identite, fiches.get(identite) ?? null).statut !== "importe") continue;
      out.push({ identite, id, verdict });
    }
    return out.sort((a, b) => VERDICTS_A_TESTER.indexOf(a.verdict) - VERDICTS_A_TESTER.indexOf(b.verdict) || a.id.localeCompare(b.id));
  }
}

export function ouvrirLocal(options = {}) {
  return new LecteurLocal(resoudreRacines(options), options);
}
