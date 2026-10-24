#!/usr/bin/env node
// Delta — serveur MCP local (stdio), lecture seule, pour les agents qui tournent sur la machine de l'instance (lot L4).
// Mêmes six outils que le serveur public (api/mcp.js), sur la source `local` : référence commune du miroir de l'instance
// et bloc `personnel` distinct (avis, essais, constats OPÉRER), lus sur disque par lib/local.js. Aucune écriture, aucun
// appel réseau ni de modèle, aucune télémétrie ; stdout ne porte que les réponses JSON-RPC (une par ligne).
//
// Usage : node stdio.js (--historique | --instance <profil.json>) [--langue en|fr]
//   dans une instance lancée par K1 (DELTA_INSTANCE posée), les racines viennent de l'environnement, sans option.
// Déclaration dans Claude Code : claude mcp add delta-local -- node <dépôt>/mcp/stdio.js --historique --langue fr
// Codes : 0 fin de l'entrée standard ; 2 usage ou racines non désignées.
import path from "node:path";
import readline from "node:readline";
import { fileURLToPath } from "node:url";
import { traiter } from "./api/mcp.js";
import { LANGUES, ErreurTexte, t, texteErreur } from "./lib/textes.js";
import { LecteurLocal, resoudreRacines } from "./lib/local.js";
import CONFIG from "./lib/config.js";

export function options(argv) {
  const o = { historique: false, instance: null, langue: LANGUES.includes(process.env.DELTA_LANGUE) ? process.env.DELTA_LANGUE : CONFIG.langue_commune_defaut };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--historique") o.historique = true;
    else if (a === "--instance" && argv[i + 1]) o.instance = argv[++i];
    else if (a === "--langue" && LANGUES.includes(argv[i + 1])) o.langue = argv[++i];
    else throw new ErreurTexte("local.usage", { option: a });
  }
  if (o.historique && o.instance) throw new ErreurTexte("local.usage", { option: "--historique --instance" });
  return o;
}

export function contexteLocal(o) {
  return { langue: o.langue, source: "local", local: new LecteurLocal(resoudreRacines({ instance: o.instance, historique: o.historique })) };
}

async function main() {
  let o, ctx;
  try { o = options(process.argv.slice(2)); ctx = contexteLocal(o); } catch (e) {
    process.stderr.write(`delta-local: ${texteErreur(e, o?.langue ?? "en")}\n`);
    process.exit(2);
  }
  const entree = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  let file = Promise.resolve();
  for await (const ligne of entree) {
    if (!ligne.trim()) continue;
    // une requête après l'autre, dans l'ordre reçu : les réponses sortent dans le même ordre
    file = file.then(async () => {
      let msg;
      try { msg = JSON.parse(ligne); } catch {
        process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: null, error: { code: -32700, message: t(ctx.langue, "rpc.json") } }) + "\n");
        return;
      }
      const lot = Array.isArray(msg);
      const reponses = (await Promise.all((lot ? msg : [msg]).map((m) => traiter(m, {}, ctx)))).filter(Boolean);
      if (reponses.length) process.stdout.write(JSON.stringify(lot ? reponses : reponses[0]) + "\n");
    });
  }
  await file;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) main();
