// Lecteur local des deux couches (lot L4, conception §2.1, §2.2, §4.1) : génération commune du miroir de l'instance et
// magasin personnel, lus sur disque, sans écriture ni appel de modèle. Utilisé par le MCP stdio (stdio.js) et l'adaptateur
// du Bureau (bureau.js) ; jamais par le serveur HTTP public (api/mcp.js n'importe pas ce module et ne reçoit la source
// `local` que d'un contexte construit ici).
// Racines : mêmes trois sources que scripts/deltalib/couches/racines.py (profil K1 v1, ou v2 avec le profil d'hôte de P1 ;
// environnement DELTA_INSTANCE ; installation historique sur demande), sans découverte d'une autre instance.
// Lot 2 : vue « Utile pour mon ORQYRA » (`utile`) : pourquoi une fiche commune concerne cette instance, d'après
// l'instantané de l'instance (profil d'hôte, réglages courants, rangés par `couches.py personnel rafraichir`), les versions
// installées et l'avis courant ; elle ne recommande rien d'elle-même et ne déclenche ni mission ni changement de politique.
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
  "prefixe_node", "superviseur", "composants", "projets", "hote", "installation"]);
const RACINES_K1 = new Set(["code", "configuration", "etat", "cache", "runtime", "lanceurs"]);
const XDG = { configuration: ["XDG_CONFIG_HOME", ".config"], etat: ["XDG_STATE_HOME", ".local/state"],
  cache: ["XDG_CACHE_HOME", ".cache"], runtime: ["XDG_RUNTIME_DIR", ".local/run"] };
const RE_GENERATION = /^g-[0-9a-f]{16}$/;
const VERDICTS_A_TESTER = ["tester", "utiliser"];
// Versions communes qui concernent un produit de fiche (identités de versions.json) : seules celles qu'un relevé de
// l'instance porte deviennent une raison de la vue « Utile pour mon ORQYRA ».
const VERSIONS_PRODUIT = { "claude-code": ["version:claude-code"], claude: ["version:claude-desktop"],
  codex: ["version:codex-cli-terminal", "version:codex-app-chatgpt"], chatgpt: ["version:chatgpt-desktop", "version:codex-app-chatgpt"] };
// Exécutables déclarés par le profil d'instance qui servent un produit (clés de `executables`, discipline instance.py).
const EXECUTABLES_PRODUIT = { "claude-code": ["claude"], codex: ["codex"] };

const absolu = (v, quoi) => {
  if (typeof v !== "string" || !v || !path.isAbsolute(v) || v.split(path.sep).includes("..")) throw new ErreurTexte("local.racine", { quoi });
  return v;
};
const dedans = (p, home) => p.startsWith(home.endsWith(path.sep) ? home : home + path.sep);

// Racines d'instance : { configuration, etat, cache, runtime, origine, profil } ; refus explicite sans source désignée.
// `profil` : le profil K1 lu (option, ou OPERER_INSTANCE_PROFIL d'une instance lancée par K1), null sur l'historique.
export function resoudreRacines({ instance, historique = false, env = process.env, home = os.homedir() } = {}) {
  if (instance) {
    let d;
    try { d = JSON.parse(fs.readFileSync(instance, "utf8")); } catch { throw new ErreurTexte("local.profil_illisible"); }
    if (!d || typeof d !== "object" || Array.isArray(d) || Object.keys(d).some((k) => !CHAMPS_K1.has(k))) throw new ErreurTexte("local.profil_forme");
    if (d.schema !== "delta.instance" || ![1, 2].includes(d.version)) throw new ErreurTexte("local.profil_forme");
    // P1 : hôte et identité d'installation n'existent qu'en version 2, qui porte toujours son profil d'hôte
    if (d.version === 1 && ("hote" in d || "installation" in d)) throw new ErreurTexte("local.profil_forme");
    if (d.version === 2 && (!d.hote || typeof d.hote !== "object" || Array.isArray(d.hote))) throw new ErreurTexte("local.profil_forme");
    if (typeof d.identite !== "string" || !/^[a-z][a-z0-9-]{0,47}$/.test(d.identite)) throw new ErreurTexte("local.profil_forme");
    const h = absolu(d.home, "home");
    const declarees = d.racines ?? {};
    if (!declarees || typeof declarees !== "object" || Object.keys(declarees).some((k) => !RACINES_K1.has(k))) throw new ErreurTexte("local.profil_forme");
    const r = { origine: "instance", profil: instance };
    for (const [nom, defaut] of Object.entries(DEFAUTS_K1)) {
      const p = nom in declarees ? absolu(declarees[nom], nom) : path.join(h, defaut, d.identite);
      if (!dedans(p, h)) throw new ErreurTexte("local.racine", { quoi: nom });
      r[nom] = p;
    }
    return r;
  }
  if (env.DELTA_INSTANCE) {
    const r = { origine: "environnement", profil: env.OPERER_INSTANCE_PROFIL ? absolu(env.OPERER_INSTANCE_PROFIL, "OPERER_INSTANCE_PROFIL") : null };
    for (const [nom, [v]] of Object.entries(XDG)) {
      if (!env[v]) throw new ErreurTexte("local.environnement", { variable: v });
      r[nom] = absolu(env[v], v);
    }
    return r;
  }
  if (historique) {
    const r = { origine: "historique", profil: null };
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
    return { statut: "disponible", generation: actif.generation, manifest_sha256: actif.manifest_sha256, origine: actif.origine ?? null, dossier, manifeste, publie_le, verifie_le,
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
      bilan: path.join(this.e.personnel, "reglages-bilan.json"), essais: path.join(this.e.personnel, "essais-operer.json"),
      instance: path.join(this.e.personnel, "instance.json") };
    const s = Object.values(f).map(signature).join("|");
    if (this.sig.personnel === s && this.p) return this.p;
    this.sig.personnel = s;
    const p = { statut: "absent", objets: null, couples: null, essais: null, bilan: null, instance: null, signature: s };
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
    try {
      // lot 2 : profil d'hôte et réglages courants de l'instance (couches.py personnel rafraichir)
      const d = lireJsonFichier(f.instance);
      if (d?.vue === "instance" && d.schema_version === 1 && d.profil && Array.isArray(d.reglages?.cases))
        p.instance = { lu_le: d.lu_le ?? null, sha256: d.sha256 ?? null, profil: d.profil, reglages: d.reglages };
    } catch { /* aucun instantané : profil et réglages inconnus */ }
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
      essais_operer: p.essais ? { statut: "disponible", lu_le: p.essais.lu_le, total: p.essais.essais.length } : { statut: "absent" },
      instance: this.resumeInstance() };
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
    // sans fiche commune (miroir indisponible), l'id court vient de l'identité : les essais OPÉRER le citent ainsi.
    // Leur instantané ne dépend pas de l'overlay : sans overlay importé, ils restent rendus, jamais un avis.
    const essais = this.essais(identite, fiche?.id ?? idCourt(identite));
    if (p.statut !== "disponible") return { couche: "personnel", statut: "non_personnalise", magasin: p.statut, avis: null, ...(essais.length ? { essais } : {}) };
    const o = p.objets[identite];
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

  // Instance lue (lot 2) : profil d'hôte de P1 (identité, socle, couches personnelles) et réglages courants, avec la date
  // de leur instantané ; `absent` tant qu'aucun rafraîchissement ne les a rangés.
  resumeInstance() {
    const i = this.personnel().instance;
    if (!i) return { statut: "absent" };
    const pr = i.profil, hote = pr.hote ?? null;
    return { statut: "disponible", lu_le: i.lu_le, sha256: i.sha256,
      profil: { statut: pr.statut, ...(pr.motif ? { motif: pr.motif } : {}), identite: pr.identite ?? null, mode: pr.mode ?? null,
        hote: hote ? { id: hote.id, socle: hote.socle, couches_personnelles: hote.couches_personnelles } : null },
      reglages: { statut: i.reglages.statut, ...(i.reglages.motif ? { motif: i.reglages.motif } : {}), origine: i.reglages.origine ?? null,
        sha256: i.reglages.sha256 ?? null, cases: i.reglages.cases.length } };
  }

  // Vue « Utile pour mon ORQYRA » d'une fiche commune : les raisons, chacune avec sa source, pour lesquelles cette fiche
  // concerne l'instance (version installée du produit, exécutable déclaré par le profil, cases des réglages courants qui
  // désignent ce couple, constats OPÉRER, essais), puis l'avis courant s'il existe. Aucune raison et aucun avis sont des
  // réponses valables, rendues comme telles ; la vue ne propose ni mission ni changement de réglage (`effet: aucun`).
  // `versions` : identité → entrée commune de versions.json (comparaison au même fait commun seulement).
  utile(identite, fiche, { versions = new Map() } = {}) {
    const p = this.personnel(), inst = p.instance;
    const produits = [...new Set([fiche?.produit, ...(Array.isArray(fiche?.produits) ? fiche.produits : [])].filter(Boolean))];
    const raisons = [];
    for (const iv of [...new Set(produits.flatMap((x) => VERSIONS_PRODUIT[x] || []))]) {
      const v = this.versionInstallee(iv, versions.get(iv) ?? null);
      if (v) raisons.push({ type: "version_installee", identite: iv, installee: v.installee, releve_le: v.releve_le, statut: v.statut,
        derniere_publiee: versions.get(iv)?.derniere_publiee ?? null, source: "personnel:version" });
    }
    if (inst?.profil?.statut === "present") for (const x of [...new Set(produits.flatMap((y) => EXECUTABLES_PRODUIT[y] || []))])
      if ((inst.profil.executables || []).includes(x)) raisons.push({ type: "executable_declare", executable: x, source: "personnel:profil" });
    if (identite?.startsWith("kb:delta:modeles:")) {
      const cases = (inst?.reglages?.cases || []).filter((c) => c.couple === identite);
      if (cases.length) {
        // une case rattachée à une version antérieure de la fiche commune est dite à revoir, pas courante
        const perime = cases.some((c) => c.couple_empreinte && fiche?.empreinte && c.couple_empreinte !== fiche.empreinte);
        raisons.push({ type: "reglage_courant", statut: perime ? "a_revoir" : "courant", origine: inst.reglages.origine ?? null,
          cases: cases.map((c) => ({ famille: c.famille, nature: c.nature, taille: c.taille, motif_reglage: c.motif_reglage ?? null })),
          lu_le: inst.lu_le, source: "personnel:reglages" });
      }
      const c = this.constatsCouple(identite, fiche);
      if (c.groupes.length) raisons.push({ type: "constats_operer", statut: c.statut, groupes: c.groupes.length,
        missions: c.groupes.reduce((n, g) => n + (Number.isInteger(g.missions) ? g.missions : 0), 0), observe_le: c.observe_le,
        bilan_empreinte: c.bilan_empreinte, source: "personnel:bilan" });
    }
    const bloc = this.blocPersonnel(identite, fiche);
    if (bloc.essais?.length) raisons.push({ type: "essais", total: bloc.essais.length,
      derniere_date: bloc.essais.map((e) => e.date ?? e.clos_le).filter((d) => typeof d === "string").sort().at(-1) ?? null, source: "personnel:essais" });
    const a = bloc.avis;
    const recommandation = a && (a.verdict || a.pour_toi || a.action)
      ? { verdict: a.verdict, pourquoi: a.pourquoi, pour_toi: a.pour_toi, action: a.action, evalue_le: bloc.evalue_le ?? null, source: "personnel:avis" } : null;
    // pourquoi il n'y a pas de recommandation : magasin absent, avis à revoir (précédent gardé à part), ou aucun avis
    const sans = recommandation ? null : p.statut !== "disponible" ? "magasin_absent" : bloc.avis_precedent ? "avis_a_revoir" : "aucun_avis";
    return { vue: "utile_pour_instance", identite: identite ?? null, instance: this.resumeInstance(), concerne: raisons.length > 0, raisons,
      recommandation, sans_recommandation: sans, ...(bloc.avis_precedent ? { statut_avis: bloc.statut, motif_avis: bloc.motif ?? null } : {}),
      effet: "aucun" };
  }

  // Cases « fait » partagées (lot 2) : fiches de la documentation des éditeurs qui ont un essai déclaré, au journal des
  // essais de la base (kb-essais.yaml, D119) ou par OPÉRER (`operer essai`). Ce sont les seules marques « fait » qu'un
  // autre lecteur (Bureau, agent) peut voir ; une case cochée dans un navigateur reste dans ce navigateur.
  faits() {
    const p = this.personnel();
    if (p.statut !== "disponible") return [];
    const out = [];
    for (const identite of Object.keys(p.objets)) {
      if (!/^kb:(claude|openai):/.test(identite)) continue;
      const id = idCourt(identite), essais = this.essais(identite, id);
      if (!essais.length) continue;
      const dates = essais.map((e) => e.date ?? e.clos_le).filter((d) => typeof d === "string").sort();
      out.push({ identite, id, essais: essais.length, derniere_date: dates.at(-1) ?? null, sources: [...new Set(essais.map((e) => e.source))].sort() });
    }
    // essais OPÉRER d'une fiche sans avis importé : rattachés par l'id de fiche de leur protocole
    for (const e of p.essais?.essais || []) {
      const f = e?.protocole?.fiche;
      if (typeof f !== "string" || out.some((x) => x.id === f || x.identite === f)) continue;
      const tous = p.essais.essais.filter((x) => x?.protocole?.fiche === f);
      out.push({ identite: null, id: f, essais: tous.length,
        derniere_date: tous.map((x) => x.clos?.ts).filter((d) => typeof d === "string").sort().at(-1) ?? null, sources: ["operer"] });
    }
    return out.sort((a, b) => String(b.derniere_date ?? "").localeCompare(String(a.derniere_date ?? "")) || a.id.localeCompare(b.id));
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
