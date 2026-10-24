// Lot L4 (deux couches) : accès personnel local. Le MCP stdio et l'adaptateur du Bureau lisent la génération commune du
// miroir de l'instance et le magasin personnel ; chaque réponse porte la couche commune et un bloc personnel distinct,
// datés séparément. Instance de test dans un dossier temporaire, avec la vraie génération publiée (docs/commun/v1).
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

const ICI = path.dirname(fileURLToPath(import.meta.url));
const DOCS = path.resolve(ICI, "../../docs");
const INDEX = JSON.parse(fs.readFileSync(path.join(DOCS, "commun/v1/index.json"), "utf8"));
const GEN = INDEX.generation;
const SENTINELLE = "sentinelle" + "-avis-prive-l4";
const sha = (b) => createHash("sha256").update(b).digest("hex");
const ecrire = (f, d) => { fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, typeof d === "string" ? d : JSON.stringify(d)); };
const lireGen = (rel) => JSON.parse(fs.readFileSync(path.join(DOCS, "commun/v1", GEN, rel), "utf8"));

const ADD_DIR = "kb:claude:claude-code-commandes-add-dir";
const AGENTS = "kb:claude:claude-code-commandes-agents";
const ADVISOR = "kb:claude:claude-code-commandes-advisor";
const COUPLE = "kb:delta:modeles:modele-gpt-6-1-sol-high";
const veilleClaude = lireGen("veille/claude.json");
const JOUR = veilleClaude.jours[0].date;
const ELEMENT = veilleClaude.entrees.find((e) => e.publications.some((p) => p.jour === JOUR));
const empreinteDe = (identite) => {
  for (const rel of ["kb/claude/commandes.json", "kb/modeles.json", "versions.json", "veille/claude.json"])
    for (const e of lireGen(rel).entrees) if (e.identite === identite) return e.empreinte;
  throw new Error(identite);
};
const GROUPE = { nature: "code", executant: "codex", modele: "gpt-6.1-sol", effort: "high", missions: 12, missions_relues: 10,
  ok_premier_tour: 6, part_ok_premier_tour: 0.6, corrections_moyennes: 0.5,
  jetons: { statut: "partiel", total_mesure: 1000, missions_mesurees: 9, missions_inconnues: 3 },
  quota: { statut: "inconnu", moyenne_pct: null, missions_estimees: 0, missions_inconnues: 12, jauges: [] } };

const objet = (identite, champs = {}) => ({ objet: identite, commun_empreinte: empreinteDe(identite), statut: "importe", langue: "fr",
  observe_le: null, evalue_le: null, statut_usage: "inconnu", recommandation: null, pour_toi: null, action: null, exemple_local: null,
  essais: [], reevaluations: [], rejugements: [], historique_importe: [], ...champs });

// Instance de test : profil K1, miroir commun (copie de la génération publiée), magasin personnel facultatif.
function instance({ personnel = true } = {}) {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "delta-l4-"));
  const profil = path.join(home, "instance.json");
  ecrire(profil, { schema: "delta.instance", version: 1, identite: "essai-l4", mode: "essai", home });
  const etat = path.join(home, ".local/state/delta/essai-l4/delta-ia"), cache = path.join(home, ".cache/delta/essai-l4/delta-ia");
  fs.cpSync(path.join(DOCS, "commun/v1", GEN), path.join(cache, "commun", GEN), { recursive: true });
  ecrire(path.join(etat, "commun-actif.json"), { schema: "delta.commun", schema_version: 1, vue: "actif", generation: GEN,
    manifest_sha256: sha(fs.readFileSync(path.join(cache, "commun", GEN, "manifest.json"))), precedente: null, origine: "synchro",
    // publication et vérification datées de l'exécution du test : la fixture ne vieillit pas avec la génération commitée
    publie_le: new Date().toISOString() });
  ecrire(path.join(etat, "synchro.json"), { verifie_le: new Date().toISOString(), erreur: null });
  if (personnel) {
    const p = path.join(etat, "personnel");
    ecrire(path.join(p, "overlay.json"), { schema: "delta.personnel", schema_version: 1, vue: "overlay", commun_generation: GEN, profil_empreinte: null, objets: {
      [ADD_DIR]: objet(ADD_DIR, { recommandation: { verdict: "tester", pourquoi: `Essayer ${SENTINELLE} dans le dossier du projet.` },
        reevaluations: [{ date: "2026-10-13", id: "claude-code-commandes-add-dir", motif: "contexte" }],
        essais: [{ date: "2026-10-21", par: "m-000000000000", rapport: "rapports/essai.md", source: "kb-essais.yaml" }] }),
      [AGENTS]: objet(AGENTS, { recommandation: { verdict: "tester", pourquoi: "à essayer" } }),
      [ADVISOR]: objet(ADVISOR, { recommandation: { verdict: "utiliser", pourquoi: "utile" } }),
      [ELEMENT.identite]: objet(ELEMENT.identite, { historique_importe: [{ fichier: `docs/data/claude/${JOUR}.json`,
        champs: { impact: "fort", pour_toi: `Change ${SENTINELLE}.`, action: "Mettre à jour.", projets_concernes: [] } }] }),
      "version:claude-code": objet("version:claude-code", { historique_importe: [{ fichier: "docs/data/versions.json",
        champs: { version: "2.1.300", detectee_le: "2026-10-24T02:00:00+00:00", statut: "en_retard", methode: "claude --version" } }] }),
      [COUPLE]: objet(COUPLE, { recommandation: { verdict: "utiliser", pourquoi: "avis importé" } }),
    } });
    const bilan = { version: 1, vue: "reglages_bilan", groupes: [{ ...GROUPE, details: [{ mission: "m-000000000001" }] }] };
    const empreinte = sha(JSON.stringify(bilan));  // valeur de test : seule l'égalité avec la projection compte ici
    ecrire(path.join(p, "reglages-bilan.json"), { schema: "delta.personnel", schema_version: 1, vue: "reglages_bilan", commande: ["operer", "reglages", "bilan", "--json"],
      filtres: { depuis: null, nature: null }, version: 1, jusqu_au: "2026-10-24T15:00:00+02:00", lignes_ignorees: 0, lu_le: "2026-10-24T15:05:00+02:00", sha256: empreinte, bilan });
    ecrire(path.join(p, "modeles-efforts.json"), { schema: "delta.personnel", schema_version: 1, vue: "modeles_efforts", commun_generation: GEN,
      bilan_empreinte: empreinte, filtres: { depuis: null, nature: null }, jusqu_au: "2026-10-24T15:00:00+02:00", observe_le: "2026-10-24T15:05:00+02:00",
      objets: { [COUPLE]: { objet: COUPLE, commun_empreinte: empreinteDe(COUPLE), bilan_empreinte: empreinte, observe_le: "2026-10-24T15:05:00+02:00",
        jusqu_au: "2026-10-24T15:00:00+02:00", groupes: [GROUPE] } },
      non_rattaches: [{ nature: "code", executant: "claude:dev", modele: null, effort: null, missions: 3, motif: "modele_ou_effort_inconnu" }] });
    ecrire(path.join(p, "essais-operer.json"), { schema: "delta.personnel", schema_version: 1, vue: "essais_operer", commande: ["operer", "essai", "--json", "liste"],
      lu_le: "2026-10-24T15:05:00+02:00", sha256: "0".repeat(64), essais: [{ id: "e-1", statut: "adopte", maturite: "confirme",
        protocole: { fiche: "claude-code-commandes-agents", version: "2.1.300", titre: "agents" }, clos: { issue: "adopte", ts: "2026-10-23T10:00:00+02:00", lecon: "lec_1" } }] });
  }
  return { home, profil, etat, cache };
}

let mcp, local, stdio, bureau, inst, vide;
before(async () => {
  delete process.env.DELTA_INSTANCE;
  mcp = await import("../api/mcp.js");
  local = await import("../lib/local.js");
  stdio = await import("../stdio.js");
  bureau = await import("../bureau.js");
  inst = instance();
  vide = instance({ personnel: false });
});
after(() => { for (const i of [inst, vide]) fs.rmSync(i.home, { recursive: true, force: true }); });

const ctxLocal = (i, langue = "en") => stdio.contexteLocal({ instance: i.profil, historique: false, langue });
const appeler = async (nom, args, ctx) => (await mcp.traiter({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: nom, arguments: args } }, {}, ctx)).result;
const donnees = async (nom, args, ctx) => { const r = await appeler(nom, args, ctx); assert.equal(r.isError, false, r.content[0].text); return r.structuredContent; };

test("une requête retrouve la syntaxe commune et l'avis personnel, étiquetés et datés séparément", async () => {
  const ctx = ctxLocal(inst);
  const r = await donnees("chercher_reference", { requete: "/add-dir", limite: 1 }, ctx);
  assert.equal(r.donnees.source, "local");
  assert.equal(r.donnees.commun.couche, "commun");
  assert.equal(r.donnees.commun.generation, GEN);
  assert.equal(r.donnees.personnel.couche, "personnel");
  assert.equal(r.donnees.personnel.bilan_operer.lu_le, "2026-10-24T15:05:00+02:00");
  const [f] = r.resultats;
  assert.equal(f.identite, ADD_DIR);
  assert.match(f.usage, /^\/add-dir/);  // syntaxe : fiche commune
  assert.equal(f.verdict, null);  // aucun avis dans la partie commune
  assert.equal(f.personnel.couche, "personnel");
  assert.equal(f.personnel.statut, "importe");
  assert.equal(f.personnel.avis.verdict, "tester");
  assert.equal(f.personnel.evalue_le, "2026-10-13");
  assert.equal(f.personnel.evalue_le_origine, "reevaluation");
  assert.notEqual(f.personnel.evalue_le, r.donnees.commun.publie_le);
  // une seule requête cherche aussi dans l'avis : l'origine du fragment trouvé est rendue
  const s = await donnees("chercher_reference", { requete: SENTINELLE }, ctx);
  assert.equal(s.resultats[0].identite, ADD_DIR);
  assert.deepEqual(s.resultats[0].trouve_dans, ["personnel"]);
  // fiche complète : bloc commun inchangé, bloc personnel distinct avec ses essais et sa provenance
  const fi = (await donnees("fiche_reference", { id: "claude-code-commandes-add-dir" }, ctx)).fiche;
  assert.equal(fi.personnel.essais[0].source, "kb-essais.yaml");
  assert.deepEqual(fi.personnel.reevaluations.map((x) => x.date), ["2026-10-13"]);
  // statut filtre sur l'usage de cette instance
  assert.equal((await donnees("chercher_reference", { requete: "/add-dir", statut: "inconnu" }, ctx)).total >= 1, true);
  assert.equal((await donnees("chercher_reference", { requete: "/add-dir", statut: "utilise" }, ctx)).total, 0);
});

// Nouvelle génération du miroir où l'empreinte commune de `identite` (dans `rel`) a changé ; le pointeur bascule.
function changerFait(i, identite, rel = "kb/claude/commandes.json") {
  const nouvelle = "g-" + sha(identite + Date.now()).slice(0, 16);
  const dossier = path.join(i.cache, "commun", nouvelle);
  fs.cpSync(path.join(i.cache, "commun", GEN), dossier, { recursive: true });
  const doc = JSON.parse(fs.readFileSync(path.join(dossier, rel), "utf8"));
  doc.entrees.find((e) => e.identite === identite).empreinte = "a".repeat(64);
  const octets = Buffer.from(JSON.stringify(doc));
  fs.writeFileSync(path.join(dossier, rel), octets);
  const manifeste = JSON.parse(fs.readFileSync(path.join(dossier, "manifest.json"), "utf8"));
  Object.assign(manifeste.fichiers.find((f) => f.chemin === rel), { taille: octets.length, sha256: sha(octets) });
  manifeste.generation = nouvelle;
  const m = Buffer.from(JSON.stringify(manifeste));
  fs.writeFileSync(path.join(dossier, "manifest.json"), m);
  const actif = JSON.parse(fs.readFileSync(path.join(i.etat, "commun-actif.json"), "utf8"));
  ecrire(path.join(i.etat, "commun-actif.json"), { ...actif, generation: nouvelle, manifest_sha256: sha(m), precedente: GEN });
  return { nouvelle, fichier: path.join(dossier, rel), octets };
}
const proposees = async (ctx) => (await donnees("a_tester", { limite: 20 }, ctx)).essais_base.entrees.map((e) => e.identite);
const actionsProposees = async (ctx) => (await donnees("a_tester", { limite: 20 }, ctx)).actions.map((a) => a.identite);
const avisDuJour = async (ctx) => (await donnees("resume_du_jour", { date: JOUR }, ctx)).perimetres.find((x) => x.perimetre === "claude");

test("avis périmé signalé après un changement commun : nouvelle génération, avis à revoir et jamais courant", async () => {
  const i = instance();
  try {
    const ctx = ctxLocal(i);
    // fiche sans essai, verdict `utiliser` : proposée tant que son avis est courant
    assert.equal((await donnees("fiche_reference", { id: "claude-code-commandes-advisor" }, ctx)).fiche.personnel.statut, "importe");
    assert.deepEqual(await proposees(ctx), [ADVISOR]);
    // le fait commun change ; le lecteur relit le pointeur sans redémarrer
    const { nouvelle, fichier, octets } = changerFait(i, ADVISOR);
    const r = await donnees("fiche_reference", { id: "claude-code-commandes-advisor" }, ctx);
    assert.equal(r.donnees.commun.generation, nouvelle);
    const p = r.fiche.personnel;
    assert.equal(p.statut, "a_revoir");
    assert.equal(p.motif, "commun_modifie");
    assert.equal(p.avis, null);
    assert.equal(p.avis_precedent.verdict, "utiliser");
    // un avis à revoir n'est plus proposé à l'essai (relecture L4, BLOQUANT 1)
    assert.deepEqual(await proposees(ctx), []);
    // fichier altéré dans le miroir (lu par un nouveau lecteur) : erreur explicite, jamais une lecture de repli
    fs.writeFileSync(fichier, octets.toString("utf8") + " ");
    const e = await appeler("fiche_reference", { id: "claude-code-commandes-advisor" }, ctxLocal(i));
    assert.equal(e.isError, true);
    assert.match(e.content[0].text, /^Local Delta data unavailable: .*size or hash differs/);
  } finally { fs.rmSync(i.home, { recursive: true, force: true }); }
});

test("fraîcheur recalculée à chaque lecture : un serveur qui dure voit le commun vieillir et ses avis passer à revoir", async () => {
  const lecteur = new local.LecteurLocal(local.resoudreRacines({ instance: inst.profil, env: {} }), { maintenant: Date.now() });
  const ctx = { langue: "en", source: "local", local: lecteur };
  assert.equal((await donnees("fiche_reference", { id: "claude-code-commandes-advisor" }, ctx)).donnees.commun.fraicheur, "recente");
  assert.deepEqual(await proposees(ctx), [ADVISOR]);
  lecteur.maintenant += 2 * 864e5;  // même lecteur, deux jours plus tard, sans nouvelle synchronisation
  assert.equal((await donnees("fiche_reference", { id: "claude-code-commandes-advisor" }, ctx)).donnees.commun.fraicheur, "ancienne");
  lecteur.maintenant += 6 * 864e5;  // huit jours
  const r = await donnees("fiche_reference", { id: "claude-code-commandes-advisor" }, ctx);
  assert.equal(r.donnees.commun.fraicheur, "tres_ancienne");
  assert.equal(r.fiche.personnel.statut, "a_revoir");
  assert.equal(r.fiche.personnel.motif, "commun_tres_ancien");
  assert.deepEqual(await proposees(ctx), []);
  // les avis de veille suivent la même règle (second tour, BLOQUANT) : plus d'impact ni d'action courants
  assert.deepEqual(await actionsProposees(ctx), []);
  const jour = await avisDuJour(ctx);
  // sans impact courant, tous les éléments par publication ; l'élément porte son avis à revoir, sans impact ni action
  assert.equal(jour.tri, "publication");
  const el = jour.elements.find((e) => e.identite === ELEMENT.identite);
  assert.deepEqual([el.personnel.statut, el.personnel.motif, el.personnel.impact, el.personnel.action], ["a_revoir", "commun_tres_ancien", null, null]);
  assert.equal(el.personnel.avis_precedent.impact, "fort");
  assert.equal(jour.compte.fort, 0);
});

test("avis de veille périmé après un changement commun : action retirée, impact rendu en avis précédent", async () => {
  const i = instance();
  try {
    const ctx = ctxLocal(i);
    assert.deepEqual(await actionsProposees(ctx), [ELEMENT.identite]);
    assert.equal((await avisDuJour(ctx)).elements[0].personnel.impact, "fort");
    changerFait(i, ELEMENT.identite, "veille/claude.json");
    assert.deepEqual(await actionsProposees(ctx), []);
    const jour = await avisDuJour(ctx);
    assert.equal(jour.tri, "publication");
    const el = jour.elements.find((e) => e.identite === ELEMENT.identite);
    assert.deepEqual([el.personnel.statut, el.personnel.motif, el.personnel.impact, el.personnel.action], ["a_revoir", "commun_modifie", null, null]);
    assert.equal(el.personnel.avis_precedent.impact, "fort");
  } finally { fs.rmSync(i.home, { recursive: true, force: true }); }
});

test("miroir commun indisponible : la couche personnelle reste consultable, avis à revoir, indisponibilité dite", async () => {
  const i = instance();
  try {
    fs.rmSync(path.join(i.etat, "commun-actif.json"));
    const ctx = ctxLocal(i, "fr");
    const f = await donnees("fiche_reference", { id: "claude-code-commandes-add-dir" }, ctx);
    assert.equal(f.donnees.commun.statut, "indisponible");
    assert.equal(f.donnees.commun.motif, "aucune_generation");
    assert.match(f.avis, /couche personnelle/);
    const [fp] = f.fiches_personnelles;
    assert.equal(fp.identite, ADD_DIR);
    assert.equal(fp.fiche, null);
    assert.equal(fp.personnel.statut, "a_revoir");
    assert.equal(fp.personnel.motif, "commun_indisponible");
    assert.equal(fp.personnel.avis_precedent.verdict, "tester");
    // essais OPÉRER rattachés à l'id court, retrouvés sans fiche commune (second tour, À NOTER)
    const agents = (await donnees("fiche_reference", { id: "claude-code-commandes-agents" }, ctx)).fiches_personnelles[0].personnel;
    assert.deepEqual(agents.essais.map((e) => e.source), ["operer"]);
    const v = await donnees("etat_versions", {}, ctx);
    assert.deepEqual(v.outils.map((o) => [o.identite, o.installee, o.statut, o.derniere_publiee]), [["version:claude-code", "2.1.300", "inconnu", null]]);
    // les outils qui ne vivent que du commun le disent, sans liste vide
    const c = await appeler("chercher_reference", { requete: "/add-dir" }, ctx);
    assert.equal(c.isError, false);
    assert.ok(c.structuredContent.categories_non_lues.length > 0);
    const e = await appeler("resume_du_jour", {}, ctx);
    assert.equal(e.isError, true);
    assert.match(e.content[0].text, /aucune génération commune active/);
  } finally { fs.rmSync(i.home, { recursive: true, force: true }); }
});

test("sans profil personnel : aucun conseil, aucun essai, aucune version installée, rien de Sylvain", async () => {
  const ctx = ctxLocal(vide);
  const appels = [["resume_du_jour", {}], ["chercher_reference", { requete: "/add-dir" }], ["fiche_reference", { id: "claude-code-commandes-add-dir" }],
    ["etat_versions", {}], ["a_tester", {}], ["nouveautes_base", {}]];
  for (const [nom, args] of appels) {
    const r = await donnees(nom, args, ctx);
    assert.equal(r.donnees.personnel.statut, "absent", nom);
    assert.equal(JSON.stringify(r).includes(SENTINELLE), false, nom);
  }
  const f = (await donnees("fiche_reference", { id: "claude-code-commandes-add-dir" }, ctx)).fiche;
  assert.deepEqual(f.personnel, { couche: "personnel", statut: "non_personnalise", magasin: "absent", avis: null });
  assert.ok((await donnees("etat_versions", {}, ctx)).outils.every((o) => o.installee === null && o.statut === "inconnu"));
  const t = await donnees("a_tester", {}, ctx);
  assert.equal(t.total, 0);
  const jour = (await donnees("resume_du_jour", {}, ctx)).perimetres.find((x) => x.perimetre === "claude");
  assert.equal(jour.tri, "publication");
  assert.ok(jour.elements.length > 0 && jour.elements.every((e) => e.personnel.statut === "non_personnalise" && e.personnel.impact === null));
  const c = (await donnees("fiche_reference", { id: "modele-gpt-6-1-sol-high" }, ctx)).fiche.constats_instance;
  assert.deepEqual(c, { statut: "indisponible", motif: "bilan_absent", groupes: [] });
});

for (const [magasin, contenu] of [["absent", null], ["invalide", { schema: "delta.personnel", schema_version: 1, vue: "autre" }], ["illisible", "{pas du json"]])
  test(`essais OPÉRER sans overlay importé (${magasin}) : essais rendus, aucun avis`, async () => {
    const i = instance();
    try {
      const overlay = path.join(i.etat, "personnel/overlay.json");
      if (contenu === null) fs.rmSync(overlay); else ecrire(overlay, contenu);
      const ctx = ctxLocal(i, "fr");
      const r = await donnees("fiche_reference", { id: "claude-code-commandes-agents" }, ctx);
      assert.equal(r.donnees.personnel.statut, magasin);
      assert.equal(r.donnees.personnel.essais_operer.total, 1);
      const p = r.fiche.personnel;
      assert.deepEqual([p.couche, p.statut, p.magasin, p.avis], ["personnel", "non_personnalise", magasin, null], magasin);
      assert.deepEqual(p.essais.map((e) => [e.source, e.id, e.statut, e.issue, e.lecon_apprendre]), [["operer", "e-1", "adopte", "adopte", "lec_1"]], magasin);
      // fiche sans essai OPÉRER : bloc inchangé, et rien de l'avis privé
      const a = await donnees("fiche_reference", { id: "claude-code-commandes-add-dir" }, ctx);
      assert.deepEqual(a.fiche.personnel, { couche: "personnel", statut: "non_personnalise", magasin, avis: null }, magasin);
      assert.equal(JSON.stringify(a).includes(SENTINELLE), false, magasin);
    } finally { fs.rmSync(i.home, { recursive: true, force: true }); }
  });

test("MCP public : jamais la racine personnelle, même si elle existe sur la machine", async () => {
  const code = fs.readFileSync(new URL("../api/mcp.js", import.meta.url), "utf8");
  assert.equal(/from "node:fs"|from "fs"|import[^;]*local\.js|readFileSync|readdirSync/.test(code), false, "api/mcp.js ne lit aucun fichier");
  const { SOURCES } = await import("../lib/couches.js");
  assert.deepEqual(SOURCES, ["ancienne_route", "commun"]);  // `?source=local` n'est pas une source admise par l'adresse
  // le serveur HTTP reçoit ?source=local : défaut public, sans bloc personnel
  const reponse = await new Promise((resolve) => {
    const res = { headers: {}, statusCode: 0, setHeader(k, v) { this.headers[k] = v; }, end(corps) { resolve({ statut: this.statusCode, corps }); } };
    mcp.default({ method: "POST", url: "/mcp?source=local", body: { jsonrpc: "2.0", id: 1, method: "initialize", params: {} } }, res);
  });
  assert.equal(reponse.statut, 200);
  assert.doesNotMatch(JSON.parse(reponse.corps).result.instructions, /personnel|this Delta instance/);
});

test("couple modèle × effort : constats de l'instance égaux à la source, groupe par nature et exécutant, absence ≠ zéro", async () => {
  const ctx = ctxLocal(inst);
  const f = (await donnees("fiche_reference", { id: "modele-gpt-6-1-sol-high" }, ctx)).fiche;
  assert.equal(f.constats_instance.statut, "disponible");
  assert.equal(f.constats_instance.source, "operer reglages bilan --json");
  assert.deepEqual(f.constats_instance.groupes, [GROUPE]);  // recopiés sans recalcul
  assert.equal(f.constats_instance.bilan_empreinte, (await donnees("chercher_reference", { requete: "x" }, ctx)).donnees.personnel.bilan_operer.sha256);
  assert.equal(f.personnel.avis.verdict, "utiliser");  // avis importé : distinct des constats agrégés
  assert.equal(f.verdict, null);
  // couple sans observation : statut explicite, aucun groupe à zéro
  const autre = (await donnees("fiche_reference", { id: "modele-gpt-6-1-sol-low" }, ctx)).fiche.constats_instance;
  assert.equal(autre.statut, "aucune_observation");
  assert.deepEqual(autre.groupes, []);
  // résumé de recherche : pas de constats (fiche complète seulement), et jamais dans la réponse publique
  const pub = await mcp.traiter({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "fiche_reference", arguments: { id: "modele-gpt-6-1-sol-high" } } }, {},
    { langue: "en", source: "ancienne_route" });
  assert.equal(JSON.stringify(pub).includes("constats_instance"), false);
  // projection antérieure au dernier instantané : à revoir, groupes gardés comme précédents datés
  const i = instance();
  try {
    const f2 = path.join(i.etat, "personnel/reglages-bilan.json");
    ecrire(f2, { ...JSON.parse(fs.readFileSync(f2, "utf8")), sha256: "b".repeat(64) });
    const c = (await donnees("fiche_reference", { id: "modele-gpt-6-1-sol-high" }, ctxLocal(i))).fiche.constats_instance;
    assert.equal(c.statut, "a_revoir");
    assert.equal(c.motif, "projection_anterieure_au_bilan");
  } finally { fs.rmSync(i.home, { recursive: true, force: true }); }
});

test("veille, versions et essais : bloc personnel du jour, version de l'instance, essais de la base et d'OPÉRER sans perte", async () => {
  const ctx = ctxLocal(inst, "fr");
  const jour = (await donnees("resume_du_jour", { date: JOUR }, ctx)).perimetres.find((x) => x.perimetre === "claude");
  assert.equal(jour.tri, "impact_personnel");
  assert.equal(jour.elements[0].identite, ELEMENT.identite);
  assert.equal(jour.elements[0].personnel.impact, "fort");
  assert.equal(jour.elements[0].impact, null);  // l'élément commun ne porte pas d'impact
  assert.equal(jour.compte.fort, 1);
  const v = (await donnees("etat_versions", {}, ctx)).outils.find((o) => o.identite === "version:claude-code");
  assert.equal(v.installee, "2.1.300");
  assert.equal(v.couche_installee, "personnel");
  assert.equal(v.releve_le, "2026-10-24T02:00:00+00:00");
  const agents = (await donnees("fiche_reference", { id: "claude-code-commandes-agents" }, ctx)).fiche.personnel;
  assert.deepEqual(agents.essais.map((e) => [e.source, e.statut, e.lecon_apprendre]), [["operer", "adopte", "lec_1"]]);
  // à tester : avis de l'instance, sans les fiches déjà essayées (journal de la base ou OPÉRER), tester d'abord
  const t = await donnees("a_tester", { limite: 20 }, ctx);
  assert.deepEqual(t.essais_base.entrees.map((e) => [e.identite, e.verdict]), [[ADVISOR, "utiliser"]]);
  assert.equal(t.actions[0].identite, ELEMENT.identite);
  assert.equal(t.actions[0].impact, "fort");
});

test("MCP stdio : protocole ligne à ligne, outils décrits pour la couche personnelle, racines refusées sans source", () => {
  const entree = [{ jsonrpc: "2.0", id: 1, method: "initialize", params: {} }, { jsonrpc: "2.0", method: "notifications/initialized" },
    { jsonrpc: "2.0", id: 2, method: "tools/list" }, { jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "fiche_reference", arguments: { id: "claude-code-commandes-add-dir" } } },
    { jsonrpc: "2.0", id: 4, method: "tools/call", params: null }, { jsonrpc: "2.0", id: 5, method: "ping" }]
    .map((m) => JSON.stringify(m)).join("\n") + "\nnot json\n";
  const p = spawnSync(process.execPath, [path.join(ICI, "../stdio.js"), "--instance", inst.profil, "--langue", "fr"], { input: entree, encoding: "utf8", env: { ...process.env, DELTA_INSTANCE: "" } });
  assert.equal(p.status, 0, p.stderr);
  const lignes = p.stdout.trim().split("\n").map((l) => JSON.parse(l));
  assert.deepEqual(lignes.map((l) => l.id), [1, 2, 3, 4, 5, null]);
  assert.match(lignes[0].result.instructions, /bloc `personnel` distinct/);
  assert.equal(lignes[1].result.tools.length, 6);
  assert.ok(lignes[1].result.tools.every((o) => /Serveur local/.test(o.description)));
  assert.equal(lignes[2].result.structuredContent.fiche.personnel.avis.verdict, "tester");
  // `params: null` : réponse d'erreur, le serveur continue (relecture L4) ; puis ping, puis JSON illisible
  assert.equal(lignes[3].error.code, -32602);
  assert.deepEqual(lignes[4].result, {});
  assert.equal(lignes[5].error.code, -32700);
  const refus = spawnSync(process.execPath, [path.join(ICI, "../stdio.js")], { input: "", encoding: "utf8", env: { ...process.env, DELTA_INSTANCE: "" } });
  assert.equal(refus.status, 2);
  assert.match(refus.stderr, /instance roots not designated/);
  // erreurs de démarrage dans la langue demandée, au MCP comme au Bureau
  const fr = spawnSync(process.execPath, [path.join(ICI, "../stdio.js"), "--langue", "fr"], { input: "", encoding: "utf8", env: { ...process.env, DELTA_INSTANCE: "" } });
  assert.match(fr.stderr, /racines non désignées/);
  const b = spawnSync(process.execPath, [path.join(ICI, "../bureau.js"), "--langue", "fr", "etat"], { encoding: "utf8", env: { ...process.env, DELTA_INSTANCE: "" } });
  assert.equal(b.status, 2);
  assert.match(b.stderr, /^delta-bureau: racines non désignées/);
});

test("racines : mêmes règles que racines.py (profil K1, environnement d'instance, historique demandé)", () => {
  const home = "/srv/essai";
  const f = path.join(inst.home, "p.json");
  ecrire(f, { schema: "delta.instance", version: 1, identite: "lab", home, racines: { etat: "/srv/essai/etat" } });
  assert.deepEqual(local.resoudreRacines({ instance: f, env: {} }), { origine: "instance", profil: f, configuration: "/srv/essai/.config/delta/lab",
    etat: "/srv/essai/etat", cache: "/srv/essai/.cache/delta/lab", runtime: "/srv/essai/.local/run/delta/lab" });
  ecrire(f, { schema: "delta.instance", version: 1, identite: "lab", home, racines: { etat: "/ailleurs/etat" } });
  assert.throws(() => local.resoudreRacines({ instance: f, env: {} }), (e) => e.cle === "local.racine");
  ecrire(f, { schema: "delta.instance", version: 1, identite: "lab", home, inconnu: 1 });
  assert.throws(() => local.resoudreRacines({ instance: f, env: {} }), (e) => e.cle === "local.profil_forme");
  const env = { DELTA_INSTANCE: "lab", XDG_CONFIG_HOME: "/i/c", XDG_STATE_HOME: "/i/s", XDG_CACHE_HOME: "/i/k", XDG_RUNTIME_DIR: "/i/r" };
  assert.deepEqual(local.resoudreRacines({ env }), { origine: "environnement", profil: null, configuration: "/i/c", etat: "/i/s", cache: "/i/k", runtime: "/i/r" });
  assert.throws(() => local.resoudreRacines({ env: { DELTA_INSTANCE: "lab" } }), (e) => e.cle === "local.environnement");
  assert.deepEqual(local.resoudreRacines({ historique: true, env: {}, home: "/h" }), { origine: "historique", profil: null, configuration: "/h/.config/delta",
    etat: "/h/.local/state/delta", cache: "/h/.cache/delta", runtime: "/h/.local/run/delta" });
  assert.throws(() => local.resoudreRacines({ env: {} }), (e) => e.cle === "local.sans_racines");
});

test("Bureau : contrat `etat` et outils, mêmes couches que le MCP local, aucune écriture", async () => {
  const avant = fs.readdirSync(path.join(inst.etat, "personnel")).map((f) => [f, sha(fs.readFileSync(path.join(inst.etat, "personnel", f)))]);
  const e = await bureau.executer(["--instance", inst.profil, "etat"]);
  assert.equal(e.code, 0);
  assert.deepEqual(Object.keys(e.sortie).sort(), ["commun", "langue", "lu_le", "outils", "personnel", "schema", "schema_version", "site_public_url", "vue"]);
  assert.equal(e.sortie.vue, "bureau");
  assert.equal(e.sortie.commun.generation, GEN);
  assert.equal(e.sortie.commun.fraicheur, "recente");
  assert.equal(e.sortie.personnel.couples_observes, 1);
  assert.equal(e.sortie.personnel.groupes_non_rattaches, 1);
  const v = await bureau.executer(["--instance", inst.profil, "versions"]);
  assert.equal(v.sortie.outils.find((o) => o.identite === "version:claude-code").installee, "2.1.300");
  const f = await bureau.executer(["--instance", inst.profil, "--langue", "fr", "fiche", "modele-gpt-6-1-sol-high"]);
  assert.deepEqual(f.sortie.fiche.constats_instance.groupes, [GROUPE]);
  const inconnu = await bureau.executer(["--instance", inst.profil, "fiche", "inexistant-xyz"]);
  assert.equal(inconnu.code, 1);
  const vide_ = await bureau.executer(["--instance", vide.profil, "etat"]);
  assert.equal(vide_.sortie.personnel.statut, "absent");
  assert.equal(vide_.sortie.personnel.objets, null);
  const apres = fs.readdirSync(path.join(inst.etat, "personnel")).map((f) => [f, sha(fs.readFileSync(path.join(inst.etat, "personnel", f)))]);
  assert.deepEqual(apres, avant);
});

// ---------------------------------------------------------------------------------------------- lot 2
// Profil v2 de P1, vue « Utile pour mon ORQYRA », consultation courte et cases « fait » partagées.
const HOTE = { schema: "delta.hote", version: 1, id: "hp", socle: ["moteur", "operer", "files", "tic", "pilote"],
  couches_personnelles: [{ id: "tiroir", libelle: "Tiroir", ressources: ["tiroir/etat.json"] }], migration: [], lectures_ssh: [] };
// Instantané de l'instance tel que `couches.py personnel rafraichir` le range (instance.py) : profil présent, une case de
// réglage rattachée au couple de test.
function instanceLot2() {
  const i = instance();
  ecrire(path.join(i.etat, "personnel", "instance.json"), { schema: "delta.personnel", schema_version: 1, vue: "instance", lu_le: "2026-10-24T18:00:00+02:00",
    profil: { statut: "present", identite: "essai-l4", version: 2, mode: "essai", hote: { id: "hp", version: 1, socle: HOTE.socle,
      couches_personnelles: [{ id: "tiroir", libelle: "Tiroir" }] }, executables: ["claude"] },
    reglages: { statut: "disponible", motif: null, origine: "option", commun_generation: GEN, sha256: "1".repeat(64), cases: [
      { famille: "codex", nature: "code", taille: "*", modele: "gpt-6.1-sol", effort: "high", motif_reglage: "mesuré", couple: COUPLE,
        couple_empreinte: empreinteDe(COUPLE), non_rattache: null }] }, sha256: "2".repeat(64) });
  return i;
}
const empreinteDossier = (d) => sha(fs.readdirSync(d).sort().map((f) => f + sha(fs.readFileSync(path.join(d, f)))).join());

test("lot 2 — profil v2 de P1 : accepté avec son profil d'hôte, v1 avec hôte refusé, profil installé lu de l'environnement", () => {
  const v2 = path.join(inst.home, "instance-v2.json");
  ecrire(v2, { schema: "delta.instance", version: 2, identite: "essai-l4", mode: "essai", home: inst.home, hote: HOTE,
    installation: "0f6d3c5e-8a1b-4c2d-9e7f-123456789abc", executables: { claude: path.join(inst.home, ".local/bin/claude") } });
  const r = local.resoudreRacines({ instance: v2 });
  assert.equal(r.profil, v2);
  assert.equal(r.etat, path.join(inst.home, ".local/state/delta/essai-l4"));
  const v1 = path.join(inst.home, "instance-v1-hote.json");
  ecrire(v1, { schema: "delta.instance", version: 1, identite: "essai-l4", mode: "essai", home: inst.home, hote: HOTE });
  assert.throws(() => local.resoudreRacines({ instance: v1 }), (e) => e.cle === "local.profil_forme");
  const sansHote = path.join(inst.home, "instance-v2-sans-hote.json");
  ecrire(sansHote, { schema: "delta.instance", version: 2, identite: "essai-l4", mode: "essai", home: inst.home });
  assert.throws(() => local.resoudreRacines({ instance: sansHote }), (e) => e.cle === "local.profil_forme");
  const env = { DELTA_INSTANCE: "x", XDG_CONFIG_HOME: "/c", XDG_STATE_HOME: "/s", XDG_CACHE_HOME: "/k", XDG_RUNTIME_DIR: "/r" };
  assert.equal(local.resoudreRacines({ env }).profil, null);
  assert.equal(local.resoudreRacines({ env: { ...env, OPERER_INSTANCE_PROFIL: "/c/instance.json" } }).profil, "/c/instance.json");
  assert.equal(local.resoudreRacines({ historique: true, env: {}, home: inst.home }).profil, null);
});

test("lot 2 — vue « Utile pour mon ORQYRA » : raisons sourcées, avis courant ou absence dite, rien de déclenché", async () => {
  const i = instanceLot2();
  try {
    const avant = empreinteDossier(path.join(i.etat, "personnel"));
    const ctx = ctxLocal(i, "fr");
    const u = (await donnees("fiche_reference", { id: "claude-code-commandes-add-dir" }, ctx)).fiche.utile_pour_instance;
    assert.equal(u.vue, "utile_pour_instance");
    assert.equal(u.effet, "aucun");
    assert.equal(u.concerne, true);
    const version = u.raisons.find((x) => x.type === "version_installee");
    assert.deepEqual([version.identite, version.installee, version.source], ["version:claude-code", "2.1.300", "personnel:version"]);
    assert.equal(version.derniere_publiee, lireGen("versions.json").entrees.find((e) => e.identite === "version:claude-code").derniere_publiee);
    assert.deepEqual(u.raisons.find((x) => x.type === "executable_declare"), { type: "executable_declare", executable: "claude", source: "personnel:profil" });
    assert.equal(u.raisons.find((x) => x.type === "essais").total, 1);
    assert.deepEqual([u.recommandation.verdict, u.recommandation.source, u.sans_recommandation], ["tester", "personnel:avis", null]);
    assert.match(u.avis, /Vue en lecture seule : elle n'ouvre aucune mission/);
    assert.equal(u.instance.profil.hote.id, "hp");
    assert.deepEqual(u.instance.profil.hote.couches_personnelles, [{ id: "tiroir", libelle: "Tiroir" }]);
    assert.equal(JSON.stringify(u).includes("tiroir/etat.json"), false, "ressources du profil d'hôte non recopiées");
    // couple modèle × effort : case des réglages courants et constats OPÉRER de l'instance
    const c = (await donnees("fiche_reference", { id: "modele-gpt-6-1-sol-high" }, ctx)).fiche.utile_pour_instance;
    const reglage = c.raisons.find((x) => x.type === "reglage_courant");
    assert.deepEqual([reglage.statut, reglage.cases], ["courant", [{ famille: "codex", nature: "code", taille: "*", motif_reglage: "mesuré" }]]);
    assert.deepEqual([c.raisons.find((x) => x.type === "constats_operer").missions, c.recommandation.verdict], [12, "utiliser"]);
    // aucune raison et aucun avis : réponse valable, dite telle quelle
    const autre = lireGen("kb/openai/commandes.json").entrees[0].id;
    const n = (await donnees("fiche_reference", { id: autre }, ctx)).fiche.utile_pour_instance;
    assert.deepEqual([n.concerne, n.raisons, n.recommandation, n.sans_recommandation], [false, [], null, "aucun_avis"]);
    assert.match(n.avis, /^Rien ne relie cette fiche à cette instance/);
    // avis à revoir (commun très ancien) : aucune recommandation courante, précédent dit à part
    const tard = { langue: "en", source: "local", local: new local.LecteurLocal(local.resoudreRacines({ instance: i.profil }), { maintenant: Date.now() + 8 * 864e5 }) };
    const r = (await donnees("fiche_reference", { id: "claude-code-commandes-add-dir" }, tard)).fiche.utile_pour_instance;
    assert.deepEqual([r.recommandation, r.sans_recommandation, r.statut_avis, r.motif_avis], [null, "avis_a_revoir", "a_revoir", "commun_tres_ancien"]);
    assert.match(r.avis, /No current recommendation: the previous opinion is to review/);
    // sans couche personnelle : aucune recommandation, instance absente
    const v = (await donnees("fiche_reference", { id: "claude-code-commandes-add-dir" }, ctxLocal(vide))).fiche.utile_pour_instance;
    assert.deepEqual([v.recommandation, v.sans_recommandation, v.instance.statut], [null, "magasin_absent", "absent"]);
    assert.equal(empreinteDossier(path.join(i.etat, "personnel")), avant, "la vue n'écrit rien");
  } finally { fs.rmSync(i.home, { recursive: true, force: true }); }
});

test("lot 2 — consultation courte : quelques résumés, validité, références, cache lié à la génération et au magasin", async () => {
  const i = instanceLot2();
  try {
    const ctx = ctxLocal(i, "fr");
    const c1 = await donnees("chercher_reference", { requete: "/add-dir", forme: "consultation" }, ctx);
    assert.deepEqual([c1.forme, c1.catalogue.source, c1.catalogue.version, c1.cache.statut], ["consultation", "local", GEN, "calcule"]);
    assert.equal(c1.donnees.commun.generation, GEN);
    assert.ok(c1.resultats.length >= 1 && c1.resultats.length <= 3);
    const [f] = c1.resultats;
    assert.deepEqual([f.id, f.identite, f.know_world], ["claude-code-commandes-add-dir", ADD_DIR, { fichier: "claude/commandes.json", id: "claude-code-commandes-add-dir" }]);
    assert.ok(f.references.length >= 1 && f.references.length <= 3 && f.references.every((x) => typeof x.url === "string"));
    assert.ok("validite" in f && "perimee" in f && "verifie_le" in f);
    assert.ok(f.resume.length <= 282 && f.syntaxe.startsWith("/add-dir"));
    assert.deepEqual(f.personnel, { statut: "importe", verdict: "tester" });
    assert.equal(JSON.stringify(c1).includes(SENTINELLE), false, "aucun texte d'avis dans un résumé de consultation");
    assert.match(c1.suite, /fiche_reference/);
    // même question, même catalogue, même magasin : réponse gardée, même clé ; en-tête recalculé
    const c2 = await donnees("chercher_reference", { requete: "/add-dir", forme: "consultation" }, ctx);
    assert.deepEqual([c2.cache.cle, c2.cache.statut], [c1.cache.cle, "reutilise"]);
    assert.deepEqual(c2.resultats, c1.resultats);
    const large = await donnees("chercher_reference", { requete: "context", forme: "consultation", limite: 20 }, ctx);
    assert.ok(large.affichees <= 5 && large.total >= large.affichees);
    // un fichier du magasin personnel change : nouvelle clé, recalculée
    const ov = path.join(i.etat, "personnel", "overlay.json");
    fs.utimesSync(ov, new Date(), new Date(Date.now() + 5000));
    const c3 = await donnees("chercher_reference", { requete: "/add-dir", forme: "consultation" }, ctx);
    assert.notEqual(c3.cache.cle, c1.cache.cle);
    assert.equal(c3.cache.statut, "calcule");
    const e = await appeler("chercher_reference", { requete: "/add-dir", forme: "resume" }, ctx);
    assert.equal(e.isError, true);
    assert.match(e.content[0].text, /`forme` doit valoir : liste, consultation|`forme` must be one of: liste, consultation/);
    // la liste par défaut ne change pas de forme
    assert.equal((await donnees("chercher_reference", { requete: "/add-dir", limite: 1 }, ctx)).forme, undefined);
  } finally { fs.rmSync(i.home, { recursive: true, force: true }); }
});

test("lot 2 — Bureau : vue utile, consultation et cases « fait » partagées (essais déclarés)", async () => {
  const i = instanceLot2();
  try {
    const e = await bureau.executer(["--instance", i.profil, "etat"]);
    assert.ok(["utile", "consulter", "a-tester"].every((x) => e.sortie.outils.includes(x)));
    assert.deepEqual([e.sortie.personnel.instance.statut, e.sortie.personnel.instance.profil.hote.id, e.sortie.personnel.instance.reglages.cases],
      ["disponible", "hp", 1]);
    const u = await bureau.executer(["--instance", i.profil, "--langue", "fr", "utile", "claude-code-commandes-add-dir"]);
    assert.equal(u.code, 0);
    assert.deepEqual(Object.keys(u.sortie).sort(), ["avertissement", "donnees", "fiche", "utile_pour_instance"]);
    assert.equal(u.sortie.fiche.identite, ADD_DIR);
    const c = await bureau.executer(["--instance", i.profil, "consulter", "/add-dir"]);
    assert.equal(c.sortie.forme, "consultation");
    const t = await bureau.executer(["--instance", i.profil, "a-tester"]);
    const faits = Object.fromEntries(t.sortie.faits.entrees.map((x) => [x.id, x.sources]));
    assert.deepEqual(faits["claude-code-commandes-add-dir"], ["kb-essais.yaml"]);
    assert.deepEqual(faits["claude-code-commandes-agents"], ["operer"]);
    // une fiche « faite » n'est plus proposée à l'essai
    assert.equal(t.sortie.essais_base.entrees.some((x) => x.id in faits), false);
  } finally { fs.rmSync(i.home, { recursive: true, force: true }); }
});
