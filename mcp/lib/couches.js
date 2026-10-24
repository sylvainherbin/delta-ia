// Deux sources publiques lues par le MCP (deux couches, lot L3), sans écriture ni état :
// - `ancienne_route` : JSON de `docs/data` (format historique, encore mixte jusqu'à la bascule L5, ou vues compatibles
//   aux champs personnels nuls) ;
// - `commun` : génération commune versionnée (`commun/v1/index.json` → `<generation>/manifest.json` → fichiers),
//   schémas `delta.manifest` v1 et `delta.commun` v1 vérifiés, taille et empreinte de chaque fichier contrôlées
//   contre le manifeste. Une version majeure inconnue est refusée ; aucun repli de la couche commune sur l'ancienne route.
// Les adresses viennent de la configuration commune (lib/config.js, copie de bootstrap.json), remplaçables par
// DELTA_BASE_URL et DELTA_COMMUN_URL ; DELTA_SOURCE choisit la source par défaut (ancienne_route tant que L5 n'a pas basculé).
import { createHash } from "node:crypto";
import CONFIG from "./config.js";
import { ErreurTexte } from "./textes.js";

export const SOURCES = ["ancienne_route", "commun"];
export const RE_GENERATION = /^g-[0-9a-f]{16}$/;
const DUREE_CACHE_MS = 10 * 60 * 1000;
const sansFin = (u) => String(u).replace(/\/$/, "");
export const urlRoute = () => sansFin(process.env.DELTA_BASE_URL || CONFIG.donnees_compat_url);
export const urlCommun = () => sansFin(process.env.DELTA_COMMUN_URL || CONFIG.reference_base_url);
export const sourceDefaut = () => (process.env.DELTA_SOURCE === "commun" ? "commun" : "ancienne_route");

const cache = new Map();
async function telecharger(url, chemin) {
  const c = cache.get(url);
  if (c && Date.now() - c.t < DUREE_CACHE_MS) return c.v;
  const r = await fetch(url, { headers: { "User-Agent": "Delta-MCP/0.3" } });
  if (!r.ok) throw new ErreurTexte("lecture.message", { chemin, raison: new ErreurTexte("lecture.http", { statut: r.status }) });
  const octets = Buffer.from(await r.arrayBuffer());
  let json;
  try { json = JSON.parse(octets.toString("utf8")); } catch { throw new ErreurTexte("lecture.message", { chemin, raison: new ErreurTexte("lecture.json") }); }
  const v = { octets, json };
  cache.set(url, { t: Date.now(), v });
  return v;
}

// raison d'une erreur de lecture sans le chemin (« HTTP 404 »), pour `categories_non_lues`
export const raisonLecture = (e) => (e instanceof ErreurTexte && e.cle === "lecture.message" ? e.vars.raison : e);
export const erreurFormat = (chemin) => new ErreurTexte("lecture.message", { chemin, raison: new ErreurTexte("lecture.format") });

export async function lireRoute(chemin) {
  return (await telecharger(`${urlRoute()}/${chemin}`, chemin)).json;
}

function exigerSchema(doc, fichier, schema, version = 1) {
  if (!doc || typeof doc !== "object" || doc.schema !== schema || doc.schema_version !== version)
    throw new ErreurTexte("couche.schema", { fichier, schema: doc?.schema ?? "?", version: doc?.schema_version ?? "?", attendu: `${schema} v${version}` });
}

// Génération servie : index de publication puis manifeste ; `publie_le` vient de l'index (L2 : le manifeste le laisse nul).
export async function generationCommune() {
  const base = urlCommun();
  const index = (await telecharger(`${base}/index.json`, "index.json")).json;
  exigerSchema(index, "index.json", "delta.manifest");
  if (index.vue !== "publication" || !RE_GENERATION.test(String(index.generation))) throw new ErreurTexte("couche.generation");
  const generation = index.generation;
  const lu = await telecharger(`${base}/${generation}/manifest.json`, `${generation}/manifest.json`);
  exigerSchema(lu.json, `${generation}/manifest.json`, "delta.manifest");
  if (typeof index.manifest_sha256 === "string" && createHash("sha256").update(lu.octets).digest("hex") !== index.manifest_sha256)
    throw new ErreurTexte("couche.empreinte", { chemin: "manifest.json", generation });
  const fichiers = new Map((Array.isArray(lu.json.fichiers) ? lu.json.fichiers : []).map((f) => [f.chemin, f]));
  return { base, generation, publie_le: index.publie_le ?? null, manifeste: lu.json, fichiers };
}

export async function lireCommun(chemin) {
  const g = await generationCommune();
  const attendu = g.fichiers.get(chemin);
  if (!attendu) throw new ErreurTexte("couche.fichier_absent", { chemin, generation: g.generation });
  const lu = await telecharger(`${g.base}/${g.generation}/${chemin}`, chemin);
  if (lu.octets.length !== attendu.taille || createHash("sha256").update(lu.octets).digest("hex") !== attendu.sha256)
    throw new ErreurTexte("couche.empreinte", { chemin, generation: g.generation });
  exigerSchema(lu.json, chemin, "delta.commun");
  return lu.json;
}

// Fraîcheur de la publication commune (conception §2.3) : seuils de la configuration commune.
export function fraicheur(publie_le, maintenant = Date.now()) {
  const t = Date.parse(publie_le ?? "");
  if (Number.isNaN(t)) return null;
  const heures = (maintenant - t) / 36e5;
  if (heures > CONFIG.fraicheur.tres_ancienne_j * 24) return "tres_ancienne";
  if (heures > CONFIG.fraicheur.ancienne_h) return "ancienne";
  return "recente";
}

// Étiquette de la source lue, jointe à chaque réponse : la couche commune n'est jamais annoncée pour l'ancienne route.
export async function blocDonnees(ctx) {
  if (ctx.source !== "commun") return { source: "ancienne_route", generation: null, publie_le: null, fraicheur: null, langue: ctx.langue, personnel: "non_separe" };
  const g = await generationCommune();
  return { source: "commun", generation: g.generation, publie_le: g.publie_le, donnees_du: g.manifeste.donnees_du ?? null,
    fraicheur: fraicheur(g.publie_le), langue: ctx.langue, langues: Array.isArray(g.manifeste.langues) ? g.manifeste.langues : [], personnel: "absent" };
}

// Texte d'une enveloppe bilingue L2 (`textes.<champ>.<langue>.texte`) : la langue demandée, sinon l'anglais annoncé en repli.
export function texteBilingue(e, champ, langue) {
  const t = e && e.textes && e.textes[champ];
  if (!t || typeof t !== "object") return null;
  const choisi = t[langue] && typeof t[langue].texte === "string" ? langue : t.en && typeof t.en.texte === "string" ? "en" : null;
  if (!choisi) return null;
  return { texte: t[choisi].texte, langue: choisi, repli: choisi !== langue, statut: t[choisi].statut ?? null };
}
