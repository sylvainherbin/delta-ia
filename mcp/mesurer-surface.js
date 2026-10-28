#!/usr/bin/env node
// P15 : catalogue exposé et pertes de signal mesurés séparément. Lecture du checkout, aucun modèle ni service public.
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";

const RACINE = fileURLToPath(new URL("../", import.meta.url));
const sha256 = contenu => createHash("sha256").update(contenu).digest("hex");
export const VARIANTES = [
  { nom: "liste8", forme: "liste", limite: 8 },
  ...[1, 2, 3, 4, 5].map(limite => ({ nom: `consultation${limite}`, forme: "consultation", limite })),
];

export function evaluerReponse(r, question) {
  const c = r.result?.structuredContent;
  const erreur = Boolean(r.error || !r.result || r.result.isError || !Array.isArray(c?.resultats));
  const incomplet = Boolean(c?.categories_non_lues?.length);
  const resultats = Array.isArray(c?.resultats) ? c.resultats : [];
  const position = resultats.findIndex(e => question.attendus.includes(e.id));
  const cible = resultats[position];
  const faits = question.faits.find(e => e.id === cible?.id);
  // Retrouver un id ne suffit pas : syntaxe complète et première source doivent encore être présentes.
  const syntaxe = Boolean(faits && (cible.syntaxe ?? cible.usage) === faits.syntaxe);
  const source = Boolean(faits && (cible.source === faits.source || cible.references?.some(s => s.url === faits.source)));
  const validite = Boolean(cible && Object.hasOwn(cible, "validite") && Object.hasOwn(cible, "perimee") && Object.hasOwn(cible, "verifie_le"));
  return { erreur, incomplet, rang: !erreur && position >= 0 ? position + 1 : null,
    ids: resultats.map(e => e.id), syntaxe, source, validite,
    utile: !erreur && !incomplet && syntaxe && source && validite,
    reponse_octets: Buffer.byteLength(JSON.stringify(r)), texte_octets: Buffer.byteLength(r.result?.content?.[0]?.text || ""), jetons: null };
}

export async function mesurerReductions(corpus, appeler) {
  const questions = [];
  for (const question of corpus) {
    const { attendus, faits, ...args } = question;
    const variantes = {};
    for (const { nom, forme, limite } of VARIANTES)
      variantes[nom] = evaluerReponse(await appeler({ ...args, forme, limite }), question);
    questions.push({ ...question, variantes });
  }
  const mesures = Object.fromEntries(VARIANTES.map(({ nom }) => {
    const lignes = questions.map(q => q.variantes[nom]);
    const pertes = questions.filter(q => q.variantes.liste8.utile && !q.variantes[nom].utile).map(q => q.requete);
    const gains = questions.filter(q => !q.variantes.liste8.utile && q.variantes[nom].utile).map(q => q.requete);
    return [nom, { questions: lignes.length, erreurs: lignes.filter(r => r.erreur).length,
      incompletes: lignes.filter(r => r.incomplet).length, cibles: lignes.filter(r => r.rang !== null).length,
      utiles: lignes.filter(r => r.utile).length, pertes, gains,
      conserve_signal_liste8: !pertes.length && lignes.every(r => !r.erreur && !r.incomplet),
      reponse_octets_total: lignes.reduce((n, r) => n + r.reponse_octets, 0),
      texte_octets_total: lignes.reduce((n, r) => n + r.texte_octets, 0), jetons: null }];
  }));
  const candidates = Object.entries(mesures).filter(([, m]) => m.conserve_signal_liste8);
  candidates.sort((a, b) => a[1].reponse_octets_total - b[1].reponse_octets_total);
  return { definition: "Utile = une cible du corpus avec syntaxe exacte, première source et champs de validité, sans erreur ni catégorie non lue. Conserver le signal exige de conserver chaque question utile de liste8, pas seulement le même taux.",
    jetons: null, limite: "Octets JSON-RPC (texte et structuredContent), sans tokenizer. Minimum borné aux six variantes et aux questions du corpus ; aucune optimalité générale ni qualité factuelle/native déduite.",
    minimum_octets_sans_perte: candidates[0]?.[0] ?? null, mesures, questions };
}

export async function main() {
  const data = path.join(RACINE, "docs/data");
  const corpusTexte = await fs.readFile(new URL("test/corpus-signal-p15.json", import.meta.url), "utf8");
  const fichiers = new Map();
  const serveur = http.createServer(async (req, res) => {
    try {
      const relatif = decodeURIComponent(new URL(req.url, "http://local").pathname).slice(1);
      const fichier = path.resolve(data, relatif);
      if (!fichier.startsWith(data + path.sep)) { res.statusCode = 404; return res.end(); }
      const contenu = await fs.readFile(fichier);
      fichiers.set(relatif, sha256(contenu));
      res.setHeader("content-type", "application/json"); res.end(contenu);
    } catch { res.statusCode = 404; res.end(); }
  });
  await new Promise(resolve => serveur.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${serveur.address().port}`;
  const ancienBase = process.env.DELTA_BASE_URL, ancienFetch = globalThis.fetch;
  process.env.DELTA_BASE_URL = base;
  globalThis.fetch = (url, options) => {
    if (new URL(url).origin !== base) throw new Error("Mesure P15 : réseau hors boucle locale refusé");
    return ancienFetch(url, { ...options, redirect: "error" });
  };
  try {
    const { traiter } = await import("./api/mcp.js");
    const ctx = { langue: "fr", source: "ancienne_route" };
    const catalogues = {};
    for (const surface of ["compatible", "service", "reference"]) {
      const r = await traiter({ jsonrpc: "2.0", id: 1, method: "tools/list" }, {}, { ...ctx, surface });
      catalogues[surface] = { noms: r.result.tools.map(t => t.name), outils: r.result.tools.length,
        reponse_octets: Buffer.byteLength(JSON.stringify(r)), jetons: null };
    }
    const mesure = await mesurerReductions(JSON.parse(corpusTexte).questions, args => traiter({ jsonrpc: "2.0", id: 1,
      method: "tools/call", params: { name: "orqyra_ai_chercher_reference", arguments: args } }, {}, { ...ctx, surface: "reference" }));
    const empreintes = Object.fromEntries([...fichiers].sort(([a], [b]) => a.localeCompare(b)));
    const code = {};
    for (const f of ["mcp/api/mcp.js", "mcp/lib/textes.js", "mcp/mesurer-surface.js"])
      code[f] = sha256(await fs.readFile(path.join(RACINE, f)));
    const sortie = { releve_le: new Date().toISOString(), source: "docs/data du checkout servi en boucle locale ; appels au traitement MCP réel sans journal ni compteur",
      corpus_sha256: sha256(corpusTexte), code_sha256: code, fichiers_sha256: empreintes, donnees_sha256: sha256(JSON.stringify(empreintes)), catalogues, ...mesure };
    process.stdout.write(JSON.stringify(sortie, null, 2) + "\n");
    return Object.values(mesure.mesures).some(m => m.erreurs || m.incompletes) ? 1 : 0;
  } finally {
    globalThis.fetch = ancienFetch;
    if (ancienBase === undefined) delete process.env.DELTA_BASE_URL; else process.env.DELTA_BASE_URL = ancienBase;
    await new Promise(resolve => serveur.close(resolve));
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url))
  main().then(code => { process.exitCode = code; }).catch(e => { console.error(e); process.exitCode = 1; });
