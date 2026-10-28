#!/usr/bin/env node
// Delta — adaptateur du Bureau (Delta Desktop) pour Delta-IA, côté moteur (lot L4). Une commande, une réponse JSON sur
// stdout, lue par le pont d'instance du Bureau : même lecteur (lib/local.js) et mêmes outils (api/mcp.js) que le MCP
// stdio, donc mêmes couches, mêmes dates et mêmes invalidations. Aucune écriture, aucun relevé : quotas et jauges restent
// ceux d'OBSERVATORY (le Bureau les lit déjà) ; le bilan OPÉRER vient de l'instantané partagé avec le pilote des réserves.
//
// Usage : node bureau.js (--historique | --instance <profil.json>) [--langue en|fr]
//   (etat | versions | fiche <id> | chercher <texte> | utile <id> | consulter <texte> [--limite 1..5] | a-tester)
// Contrat `etat` : { schema: "delta.personnel", schema_version: 1, vue: "bureau", lu_le, langue, commun, personnel,
//   site_public_url, outils } ; `personnel.instance` résume l'instance lue (profil d'hôte de P1, réglages courants).
// `versions`, `fiche`, `chercher` rendent le `structuredContent` de l'outil MCP correspondant ; `consulter` la forme
// courte de `chercher_reference` (lot 2), 3 fiches par défaut, --limite de 1 à 5 ; `utile <id>` la vue « Utile pour mon
// ORQYRA » de la fiche, avec l'en-tête des couches ; `a-tester` la page locale d'`a_tester` et les cases « fait » partagées
// (essais déclarés, `faits`).
// Codes : 0 réponse ; 1 outil en erreur (réponse JSON avec `erreur`) ; 2 usage ou racines non désignées.
import path from "node:path";
import { fileURLToPath } from "node:url";
import { traiter, LIMITE_CONSULTATION } from "./api/mcp.js";
import { ErreurTexte, texteErreur } from "./lib/textes.js";
import { contexteLocal, langueDemandee, options } from "./stdio.js";
import CONFIG from "./lib/config.js";

const COMMANDES = { versions: ["etat_versions", () => ({})], fiche: ["fiche_reference", (x) => ({ id: x })],
  chercher: ["chercher_reference", (x) => ({ requete: x })], consulter: ["chercher_reference", (x, limite = LIMITE_CONSULTATION) => ({ requete: x, forme: "consultation", limite })],
  utile: ["fiche_reference", (x) => ({ id: x })], "a-tester": ["a_tester", () => ({ limite: 20 })] };

export async function etat(ctx, maintenant = new Date()) {
  const d = ctx.local.blocDonnees(ctx.langue), p = ctx.local.personnel();
  const objets = p.objets ? Object.values(p.objets) : [];
  return { schema: "delta.personnel", schema_version: 1, vue: "bureau", lu_le: maintenant.toISOString(), langue: ctx.langue,
    commun: d.commun,
    personnel: { ...d.personnel, objets: p.objets ? objets.length : null,
      // compteurs seulement : le détail d'une fiche passe par `fiche <id>`, avec son statut recalculé à la lecture
      essais_base: p.objets ? objets.reduce((n, o) => n + (o.essais || []).length, 0) : null,
      couples_observes: p.couples ? Object.keys(p.couples.objets).length : null, groupes_non_rattaches: p.couples ? p.couples.non_rattaches.length : null },
    site_public_url: CONFIG.site_public_url, outils: ["etat", ...Object.keys(COMMANDES)] };
}

export async function executer(argv) {
  const i = argv.findIndex((a) => ["etat", ...Object.keys(COMMANDES)].includes(a));
  if (i < 0) throw new ErreurTexte("local.usage", { option: argv.join(" ") || "∅" });
  const [commande, ...reste] = argv.slice(i);
  const ctx = contexteLocal(options(argv.slice(0, i)));
  if (commande === "etat") return { code: 0, sortie: await etat(ctx) };
  const [outil, args] = COMMANDES[commande];
  let limite;
  if (commande === "consulter" && reste.length > 1) {
    if (reste.length !== 3 || reste[1] !== "--limite") throw new ErreurTexte("local.usage", { option: reste.slice(1).join(" ") });
    limite = Number(reste[2]);
    if (!Number.isInteger(limite) || limite < 1 || limite > 5) throw new ErreurTexte("local.limite_consultation");
    reste.splice(1);
  }
  if (reste.length !== args.length) throw new ErreurTexte("local.usage", { option: commande });
  const r = (await traiter({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: outil, arguments: args(reste[0], limite) } }, {}, ctx)).result;
  if (r.isError) return { code: 1, sortie: { erreur: r.content[0].text } };
  const sc = r.structuredContent;
  // vue seule : en-tête des couches, fiche désignée, raisons ; sans miroir commun, la réponse personnelle telle quelle
  if (commande === "utile" && sc.fiche) {
    const f = sc.fiche;
    return { code: 0, sortie: { avertissement: sc.avertissement, donnees: sc.donnees,
      fiche: { id: f.id, identite: f.identite, nom: f.nom, produit: f.produit, categorie: f.categorie }, utile_pour_instance: f.utile_pour_instance } };
  }
  if (commande === "a-tester") {
    const faits = ctx.local.faits();
    return { code: 0, sortie: { ...sc, faits: { total: faits.length, entrees: faits } } };
  }
  return { code: 0, sortie: sc };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  executer(process.argv.slice(2)).then(({ code, sortie }) => { process.stdout.write(JSON.stringify(sortie) + "\n"); process.exitCode = code; },
    (e) => { process.stderr.write(`delta-bureau: ${texteErreur(e, langueDemandee(process.argv.slice(2)))}\n`); process.exitCode = 2; });
}
