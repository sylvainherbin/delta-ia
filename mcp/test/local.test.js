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
    publie_le: INDEX.publie_le });
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

test("avis périmé signalé après un changement commun : nouvelle génération, avis à revoir et jamais courant", async () => {
  const i = instance();
  try {
    const ctx = ctxLocal(i);
    assert.equal((await donnees("fiche_reference", { id: "claude-code-commandes-add-dir" }, ctx)).fiche.personnel.statut, "importe");
    // nouvelle génération où le fait commun de /add-dir a changé ; le pointeur bascule, le lecteur relit sans redémarrer
    const nouvelle = "g-" + "f".repeat(16);
    const dossier = path.join(i.cache, "commun", nouvelle);
    fs.cpSync(path.join(i.cache, "commun", GEN), dossier, { recursive: true });
    const rel = "kb/claude/commandes.json";
    const doc = JSON.parse(fs.readFileSync(path.join(dossier, rel), "utf8"));
    doc.entrees.find((e) => e.identite === ADD_DIR).empreinte = "a".repeat(64);
    const octets = Buffer.from(JSON.stringify(doc));
    fs.writeFileSync(path.join(dossier, rel), octets);
    const manifeste = JSON.parse(fs.readFileSync(path.join(dossier, "manifest.json"), "utf8"));
    Object.assign(manifeste.fichiers.find((f) => f.chemin === rel), { taille: octets.length, sha256: sha(octets) });
    manifeste.generation = nouvelle;
    const m = Buffer.from(JSON.stringify(manifeste));
    fs.writeFileSync(path.join(dossier, "manifest.json"), m);
    const actif = JSON.parse(fs.readFileSync(path.join(i.etat, "commun-actif.json"), "utf8"));
    ecrire(path.join(i.etat, "commun-actif.json"), { ...actif, generation: nouvelle, manifest_sha256: sha(m), precedente: GEN });
    const r = await donnees("fiche_reference", { id: "claude-code-commandes-add-dir" }, ctx);
    assert.equal(r.donnees.commun.generation, nouvelle);
    const p = r.fiche.personnel;
    assert.equal(p.statut, "a_revoir");
    assert.equal(p.motif, "commun_modifie");
    assert.equal(p.avis, null);
    assert.equal(p.avis_precedent.verdict, "tester");
    // un avis à revoir n'est plus proposé à l'essai
    const t = await donnees("a_tester", { limite: 20 }, ctx);
    assert.equal(t.essais_base.entrees.some((e) => e.identite === ADD_DIR), false);
    // fichier altéré dans le miroir (lu par un nouveau lecteur) : erreur explicite, jamais une lecture de repli
    fs.writeFileSync(path.join(dossier, rel), octets.toString("utf8") + " ");
    const e = await appeler("fiche_reference", { id: "claude-code-commandes-add-dir" }, ctxLocal(i));
    assert.equal(e.isError, true);
    assert.match(e.content[0].text, /^Local Delta data unavailable: .*size or hash differs/);
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
    { jsonrpc: "2.0", id: 2, method: "tools/list" }, { jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "fiche_reference", arguments: { id: "claude-code-commandes-add-dir" } } }]
    .map((m) => JSON.stringify(m)).join("\n") + "\nnot json\n";
  const p = spawnSync(process.execPath, [path.join(ICI, "../stdio.js"), "--instance", inst.profil, "--langue", "fr"], { input: entree, encoding: "utf8", env: { ...process.env, DELTA_INSTANCE: "" } });
  assert.equal(p.status, 0, p.stderr);
  const lignes = p.stdout.trim().split("\n").map((l) => JSON.parse(l));
  assert.deepEqual(lignes.map((l) => l.id), [1, 2, 3, null]);
  assert.match(lignes[0].result.instructions, /bloc `personnel` distinct/);
  assert.equal(lignes[1].result.tools.length, 6);
  assert.ok(lignes[1].result.tools.every((o) => /Serveur local/.test(o.description)));
  assert.equal(lignes[2].result.structuredContent.fiche.personnel.avis.verdict, "tester");
  assert.equal(lignes[3].error.code, -32700);
  const refus = spawnSync(process.execPath, [path.join(ICI, "../stdio.js")], { input: "", encoding: "utf8", env: { ...process.env, DELTA_INSTANCE: "" } });
  assert.equal(refus.status, 2);
  assert.match(refus.stderr, /instance roots not designated/);
});

test("racines : mêmes règles que racines.py (profil K1, environnement d'instance, historique demandé)", () => {
  const home = "/srv/essai";
  const f = path.join(inst.home, "p.json");
  ecrire(f, { schema: "delta.instance", version: 1, identite: "lab", home, racines: { etat: "/srv/essai/etat" } });
  assert.deepEqual(local.resoudreRacines({ instance: f, env: {} }), { origine: "instance", configuration: "/srv/essai/.config/delta/lab",
    etat: "/srv/essai/etat", cache: "/srv/essai/.cache/delta/lab", runtime: "/srv/essai/.local/run/delta/lab" });
  ecrire(f, { schema: "delta.instance", version: 1, identite: "lab", home, racines: { etat: "/ailleurs/etat" } });
  assert.throws(() => local.resoudreRacines({ instance: f, env: {} }), (e) => e.cle === "local.racine");
  ecrire(f, { schema: "delta.instance", version: 1, identite: "lab", home, inconnu: 1 });
  assert.throws(() => local.resoudreRacines({ instance: f, env: {} }), (e) => e.cle === "local.profil_forme");
  const env = { DELTA_INSTANCE: "lab", XDG_CONFIG_HOME: "/i/c", XDG_STATE_HOME: "/i/s", XDG_CACHE_HOME: "/i/k", XDG_RUNTIME_DIR: "/i/r" };
  assert.deepEqual(local.resoudreRacines({ env }), { origine: "environnement", configuration: "/i/c", etat: "/i/s", cache: "/i/k", runtime: "/i/r" });
  assert.throws(() => local.resoudreRacines({ env: { DELTA_INSTANCE: "lab" } }), (e) => e.cle === "local.environnement");
  assert.deepEqual(local.resoudreRacines({ historique: true, env: {}, home: "/h" }), { origine: "historique", configuration: "/h/.config/delta",
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
