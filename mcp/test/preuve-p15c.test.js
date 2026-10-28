// M86, reprise des deux témoins M76 : contrôle TAP réel et confinement des fixtures P15c.
// Exécuter par verrou-tests-dev ; aucun fetch ni aucune écoute, y compris dans les enfants Node.
import { test, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import net from "node:net";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const RACINE = fileURLToPath(new URL("../../", import.meta.url));
const RECETTE = fs.readFileSync(new URL("../preuve-p15c.sh", import.meta.url), "utf8");
const NOMS = ["P15c R176 : erreurs des essais orientées vers le catalogue de référence",
  "P15c R178 : Bureau suit la constante de consultation"];
const preuves = fs.mkdtempSync(path.join(os.tmpdir(), "delta-preuve-p15c-"));
after(() => fs.rmSync(preuves, { recursive: true, force: true }));
const observateur = path.join(preuves, "observer.mjs");
const interdire = () => { throw new Error("M86 : réseau et écoutes interdits"); };
globalThis.fetch = interdire;
net.Server.prototype.listen = interdire;
fs.writeFileSync(observateur, `
import fs from "node:fs";
import net from "node:net";
const creer = fs.mkdtempSync;
fs.mkdtempSync = function (...args) {
  const resultat = creer.apply(this, args);
  if (process.env.M86_CREATIONS) fs.appendFileSync(process.env.M86_CREATIONS, JSON.stringify(resultat) + "\\n");
  return resultat;
};
const interdire = () => { throw new Error("M86 : réseau et écoutes interdits"); };
globalThis.fetch = interdire;
net.Server.prototype.listen = interdire;
`);
const lancer = (cmd, args, options = {}) => {
  const env = { ...process.env, ...options.env,
    NODE_OPTIONS: `${process.env.NODE_OPTIONS || ""} --import=${JSON.stringify(observateur)}` };
  // Runners autonomes : ne pas hériter du protocole interne de node:test.
  delete env.NODE_TEST_CONTEXT;
  const r = spawnSync(cmd, args, { cwd: RACINE, encoding: "utf8", timeout: 120000,
    maxBuffer: 4 * 1024 * 1024, ...options, env });
  assert.ifError(r.error);
  return r;
};

test("M76 : verdict P15c refuse deux erreurs de chargement sans assertion exécutée", () => {
  const dossier = fs.mkdtempSync(path.join(preuves, "verdict-"));
  const fichiers = ["mcp", "local"].map(nom => path.join(dossier, `${nom}.test.mjs`));
  for (const fichier of fichiers) fs.writeFileSync(fichier, 'import "./dependance-absente.mjs";\n');
  const executer = () => lancer(process.execPath,
    ["--test", "--test-reporter=tap", "--test-timeout=120000", ...fichiers]);
  const rouge = executer();
  assert.equal(rouge.status, 1);
  assert.match(rouge.stdout, /ERR_MODULE_NOT_FOUND/);
  assert.match(rouge.stdout, /^# tests 2$/m);
  assert.match(rouge.stdout, /^# fail 2$/m);
  // Même fonction que les phases rouge et verte de la recette.
  const fonction = RECETTE.match(/^verdict\(\) \{\n[\s\S]*?^JS\n\}/m)?.[0];
  assert.ok(fonction, "fonction verdict de la recette réelle");
  const valider = (log, echecs) => {
    const journal = path.join(dossier, "tap.log");
    fs.writeFileSync(journal, log);
    return lancer("bash", ["-c", 'noeud="$1"\n' + fonction + '\nverdict "$2" 2 "$3" "${@:4}"',
      "m86", process.execPath, journal, String(echecs), ...NOMS]);
  };
  const validation = valider(rouge.stdout + rouge.stderr, 2);
  console.log(`M76 preuve : deux ERR_MODULE_NOT_FOUND, zéro assertion métier ; verdict=${validation.status}`);
  assert.notEqual(validation.status, 0,
    "La preuve accepte deux modules impossibles à charger comme les deux témoins rouges attendus");

  const ecrire = corps => fichiers.forEach((fichier, i) => fs.writeFileSync(fichier,
    `import { test } from "node:test";\nimport assert from "node:assert/strict";\ntest(${JSON.stringify(NOMS[i])}, () => { ${corps} });\n`));
  ecrire('assert.fail("témoin rouge");');
  const assertions = executer();
  assert.equal(assertions.status, 1);
  const rougeValide = valider(assertions.stdout, 2);
  assert.equal(rougeValide.status, 0, "deux assertions rouges nommées acceptées : " + rougeValide.stderr);
  assert.notEqual(valider(assertions.stdout.replace(" - " + NOMS[0], " - autre témoin"), 2).status, 0);
  assert.notEqual(valider(assertions.stdout.replace(" - " + NOMS[1], " - " + NOMS[0]), 2).status, 0, "noms uniques");
  assert.notEqual(valider(assertions.stdout.replace("code: 'ERR_ASSERTION'", "code: 'ERR_TEST_FAILURE'"), 2).status, 0,
    "chaque témoin rouge doit échouer sur une assertion");
  assert.notEqual(valider(assertions.stdout + "# Error [ERR_MODULE_NOT_FOUND]: panne de chargement\n", 2).status, 0);

  ecrire("assert.equal(1, 1);");
  const vert = executer();
  assert.equal(vert.status, 0);
  const vertValide = valider(vert.stdout, 0);
  assert.equal(vertValide.status, 0, "deux témoins verts nommés acceptés : " + vertValide.stderr);
  assert.equal(valider(vert.stdout + "# M76 preuve : deux ERR_MODULE_NOT_FOUND rejetés\n", 0).status, 0,
    "un compte rendu de panne rejetée ne constitue pas lui-même une panne de chargement");
  assert.notEqual(valider(vert.stdout.replace(" - " + NOMS[0], " - autre témoin"), 0).status, 0);
  assert.notEqual(valider(vert.stdout.replace(/^ok /m, "not ok "), 0).status, 0, "ok exigé malgré les totaux verts");
  assert.notEqual(valider(vert.stdout.replace(/^# tests 2$/m, "# tests 3"), 0).status, 0);
  console.log("M86 preuve : noms exacts, assertions individuelles et ok verts contrôlés");
});

test("M76 : les instances temporaires du témoin P15c restent dans sa copie", () => {
  const dossier = fs.mkdtempSync(path.join(preuves, "isolation-"));
  const copie = path.join(dossier, "copie"), tempUtilisateur = path.join(dossier, "temp-utilisateur");
  fs.mkdirSync(tempUtilisateur);
  const journal = path.join(dossier, "creations.jsonl");
  // Préparation réelle avant les archives ; fournir les seuls fichiers de R178 rend ce test
  // utilisable aussi dans une archive sans .git. Ni mutation du code ni recette complète.
  const finPreparation = RECETTE.indexOf("\ninstantane_avant=");
  assert.ok(finPreparation > 0);
  const preparation = RECETTE.slice(0, finPreparation);
  assert.doesNotMatch(preparation, /--test/);
  const variantes = RECETTE.match(/^for variante in parametres constante; do\n[\s\S]*?^done/m)?.[0];
  const commande = RECETTE.match(/^"\$noeud" --test --test-reporter=tap(?: --test-timeout=\d+)? --test-name-pattern='\^P15c R178' \\\n  "\$copie\/constante\/mcp\/test\/local.test.js" > "\$copie\/constante-4.log" 2>&1/m)?.[0];
  assert.ok(variantes && commande, "étapes ciblées de la recette réelle");
  const r = lancer("bash", ["-c", preparation + '\ncp -R mcp "$copie/tete/mcp"\nln -s "$PWD/docs" "$copie/tete/docs"\n'
    + variantes + "\n" + commande, path.join(RACINE, "mcp/preuve-p15c.sh"), copie], {
    env: { TMPDIR: tempUtilisateur, M86_CREATIONS: journal },
  });
  const tap = fs.existsSync(path.join(copie, "constante-4.log"))
    ? fs.readFileSync(path.join(copie, "constante-4.log"), "utf8") : "";
  assert.equal(r.status, 0, r.stderr + tap);
  assert.match(tap, /^# tests 1$/m);
  assert.match(tap, /^# pass 1$/m);
  const creations = fs.readFileSync(journal, "utf8").trim().split("\n").map(JSON.parse)
    .filter(f => path.basename(f).startsWith("delta-l4-"));
  assert.ok(creations.length >= 3, "les vraies fixtures locales ont été créées");
  const horsCopie = creations.filter(f => !f.startsWith(copie + path.sep));
  console.log(`M76 preuve : R178 vert ; ${horsCopie.length}/${creations.length} instances temporaires hors copie`);
  assert.deepEqual(horsCopie, [],
    "La recette hérite de TMPDIR au lieu de confiner les fixtures dans la copie annoncée");
  assert.equal(fs.existsSync(path.join(copie, "tmp")), false, "TMPDIR nettoyé après succès");
  const echec = path.join(dossier, "copie-echec");
  const arret = lancer("bash", ["-c", preparation + "\nexit 17", path.join(RACINE, "mcp/preuve-p15c.sh"), echec], {
    env: { TMPDIR: tempUtilisateur },
  });
  assert.equal(arret.status, 17);
  assert.equal(fs.existsSync(path.join(echec, "tmp")), false, "TMPDIR nettoyé après échec");
});
