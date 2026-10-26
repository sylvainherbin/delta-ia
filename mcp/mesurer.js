#!/usr/bin/env node
// Banc local en lecture seule : corpus publié, mêmes fonctions que HTTP, aucun appel au service public.
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";

const RACINE = fileURLToPath(new URL("../", import.meta.url));
const sha256 = texte => createHash("sha256").update(texte).digest("hex");

export async function mesurerCorpus(corpus, appeler) {
  const questions = [];
  for (const { attendus, ...args } of corpus) {
    const formes = {};
    for (const forme of ["liste", "consultation"]) {
      const r = await appeler({ ...args, forme });
      const c = r.result?.structuredContent;
      const ids = (c?.resultats || []).map(e => e.id);
      const erreur = Boolean(r.error || !r.result || r.result.isError || !Array.isArray(c?.resultats));
      formes[forme] = {
        erreur, rang: erreur ? null : ids.findIndex(id => attendus.includes(id)) + 1 || null,
        ids, total: c?.total ?? null, categories_non_lues: c?.categories_non_lues ?? [],
        reponse_octets: Buffer.byteLength(JSON.stringify(r)),
        texte_octets: Buffer.byteLength(r.result?.content?.[0]?.text || ""),
        jetons: null,
      };
    }
    questions.push({ ...args, attendus, formes });
  }
  const mesures = Object.fromEntries(["liste", "consultation"].map(forme => {
    const lignes = questions.map(q => q.formes[forme]);
    const dans = n => lignes.filter(r => r.rang !== null && r.rang <= n).length;
    return [forme, { questions: lignes.length, erreurs: lignes.filter(r => r.erreur).length,
      incompletes: lignes.filter(r => r.categories_non_lues.length).length,
      cibles_top1: dans(1), cibles_top3: dans(3), cibles_top8: dans(8),
      taux_top8_pct: lignes.length ? 100 * dans(8) / lignes.length : null,
      reponse_octets_total: lignes.reduce((n, r) => n + r.reponse_octets, 0),
      texte_octets_total: lignes.reduce((n, r) => n + r.texte_octets, 0) }];
  }));
  return { definition: "Une réponse utile retrouve au moins une cible étiquetée dans les huit premiers résultats. Le corpus est fermé ; ce taux ne mesure pas toutes les requêtes réelles.",
    jetons: null, limite_jetons: "Aucun tokenizer de modèle exécuté : les octets ne sont pas des jetons.", mesures, questions };
}

export async function main() {
  const data = path.join(RACINE, "docs/data");
  const corpusTexte = await fs.readFile(new URL("test/requetes-reelles.json", import.meta.url), "utf8");
  const fichiers = new Map();
  const serveur = http.createServer(async (req, res) => {
    try {
      const relatif = decodeURIComponent(new URL(req.url, "http://local").pathname).slice(1);
      const fichier = path.resolve(data, relatif);
      if (!fichier.startsWith(data + path.sep)) { res.statusCode = 404; return res.end(); }
      const contenu = await fs.readFile(fichier);
      fichiers.set(relatif, sha256(contenu));
      res.setHeader("content-type", "application/json");
      res.end(contenu);
    } catch { res.statusCode = 404; res.end(); }
  });
  await new Promise(resolve => serveur.listen(0, "127.0.0.1", resolve));
  process.env.DELTA_BASE_URL = `http://127.0.0.1:${serveur.address().port}`;
  try {
    const { traiter } = await import("./api/mcp.js");
    const ctx = { langue: "fr", source: "ancienne_route" };
    const mesure = await mesurerCorpus(JSON.parse(corpusTexte), args => traiter({ jsonrpc: "2.0", id: 1,
      method: "tools/call", params: { name: "chercher_reference", arguments: args } }, {}, ctx));
    const empreintes = Object.fromEntries([...fichiers].sort(([a], [b]) => a.localeCompare(b)));
    const resultat = { releve_le: new Date().toISOString(), source: "docs/data du checkout, servi en boucle locale",
      corpus_sha256: sha256(corpusTexte), fichiers_sha256: empreintes, donnees_sha256: sha256(JSON.stringify(empreintes)), ...mesure };
    process.stdout.write(JSON.stringify(resultat, null, 2) + "\n");
    return mesure.mesures.liste.erreurs || mesure.mesures.liste.incompletes || mesure.mesures.consultation.erreurs || mesure.mesures.consultation.incompletes ? 1 : 0;
  } finally { await new Promise(resolve => serveur.close(resolve)); }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().then(code => { process.exitCode = code; }).catch(e => { console.error(e); process.exitCode = 1; });
}
