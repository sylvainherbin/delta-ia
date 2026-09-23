# CONTEXTE — Sylvain Herbin, usage de l'IA

Ce fichier alimente une veille IA quotidienne. Claude Code et Codex s'en servent pour formuler des
recommandations personnalisées sur l'usage de Claude, Claude Code, ChatGPT et Codex. Il se lit
seul, sans autre document.

Légende : **[observé]** vu dans un fichier ou une commande · **[déduit]** conclu à partir
d'observations · **[déclaré]** réponse directe de Sylvain · **[inconnu]** ni observable ni déclaré.

Profil : céramiste dentaire indépendant (sous-traitant pour des laboratoires), qui développe seul
des projets logiciels personnels avec des agents IA **[observé : sites, skills]**. Il travaille en
français et tutoie les agents **[observé : CLAUDE.md, AGENTS.md]**. Abonnement Claude **Max (5x)**
**[observé : page Utilisation]**. Abonnement ChatGPT **Pro** **[déclaré]**.

**Priorité actuelle : trading-sim** [déclaré]. **Irritant principal** [déclaré] : ne pas connaître
assez bien les commandes et les fonctionnalités de Claude Code, de l'app Claude et de Codex pour
en tirer le maximum. **La veille doit donc surtout signaler les nouvelles fonctionnalités** et la
façon de s'en servir concrètement sur ses projets ; l'éditeur de la veille choisit la longueur.

---

## 1. Environnement

| Élément | Valeur | Nature |
|---|---|---|
| OS | Linux Mint 22.1 (base Ubuntu 24.04), bureau Cinnamon, noyau 6.8 | [observé] |
| Machine | Portable HP, AMD A10-7300 (4 cœurs), 14 Gio de RAM, zram 7,3 Gio | [observé] |
| Disques | disque interne ~954 Go signalé non rotatif ; disque USB externe ~931 Go (sauvegardes Timeshift) | [observé] |
| Réseau | Wi-Fi seul (clé USB TP-Link), débit plafonné vers 9 Mbit/s, pas de repli cellulaire | [observé] |
| Outils CLI | git 2.43, gh 2.45, Python 3.12.3, tmux, nvm (Node 24.20 via le bundle Codex) , `python3.12-venv` (installé le 23/09) ; pas de `sqlite3` ; `pytest` absent du système, présent seulement dans `delta-ia/.venv` (9.1.1) | [observé] |
| Claude Code | 2.1.280, installation native, mise à jour faite le 22/09 (2.1.278 → 2.1.280) | [observé] |
| Codex | codex-cli 0.155.0-alpha.16, fourni par l'app de bureau ChatGPT/Codex (build 26.917) | [observé] |
| Apps de bureau | Claude Desktop (Electron) et ChatGPT Desktop (avec Codex intégré) | [observé] |
| Mobile | iPhone : pilote le PC à distance (Remote Control de Claude Code, app Claude iOS) | [observé] |

La machine est modeste : les calculs lourds (campagnes de simulation) sont bridés dans une tranche
systemd dédiée `calculs.slice` (CPUWeight 20, MemoryMax 9G, pas de swap) **[observé]**.

### Architecture multi-sessions Claude Code [observé]

Six services systemd utilisateur `claude-session@{mint,dev,carnet,trading,delta,delta-ia}` lancent chacun une
session tmux qui exécute `claude --resume <id> --remote-control herbin-<nom>`. Elles sont
pilotées depuis l'iPhone. Depuis le 23/09, `dev` ne démarre plus automatiquement : elle s'allume
et s'éteint au besoin depuis la console de pilotage (bouton réservé à `dev` et `delta`), pour
économiser environ 300 Mio de RAM par session.

| Session | Rôle |
|---|---|
| herbin-mint | gestionnaire de la machine : système, réseau, revue « machine » des calculs lourds avant lancement |
| herbin-dev | développement général (sites, console de pilotage) |
| herbin-carnet | « coach » : écrit le plan d'entraînement du jour dans le dépôt carnet |
| herbin-trading | exécution des missions trading-sim (noyaux, campagnes de calcul) |
| herbin-delta (« Dev-delta ») | développement de la web app de veille `delta-ia` (créée le 23/09, dossier `~/projets/delta-ia`) |
| delta-ia | exécution des passages quotidiens de la veille (`/delta`) |

Les sessions se parlent via `SendMessage` / `ListAgents` et Sylvain relaie des prompts entre elles
**[observé : transcripts]**.

---

## 2. Projets

### 2.1 carnet — PWA de suivi d'entraînement (projet le plus actif)

- **Objectif** [observé] : PWA personnelle, hors ligne, mono-utilisateur, surtout sur iPhone :
  séances de musculation série par série, poids, décision du matin (maintenu / allégé / repos),
  résumé de la nuit à partir de l'Apple Watch.
- **Stack** [observé] : React 19, Vite, Tailwind v4, Recharts, sans backend. Synchronisation par
  l'API GitHub Contents sur `carnet-data.json` (le `sha` sert de verrou optimiste). Hébergement
  GitHub Pages (branche `gh-pages`) via `scripts/deploy.sh`, service worker versionné.
- **Chaîne de données** [observé] : des raccourcis iOS lisent Santé et déposent des JSON dans le
  dépôt (`daily/`, `fc/`) ; la session Claude « coach » écrit `plan/AAAA-MM-JJ.json` ; l'app lit
  le tout. Toute la logique est dans l'app, les raccourcis sont de simples transports.
- **Tests** [observé] : `node --test`, 13 fichiers de test sur des copies figées de vrais fichiers ;
  lint `oxlint`. Pas de CI GitHub Actions.
- **État / rythme** [observé] : 403 commits en 60 jours (10 → 22 sept.), jusqu'à 47 par jour.
  Environ 65 commits de fonctionnalités ; le reste est de la donnée automatique (« Synchro
  carnet », « Relevé quotidien », « Plan du coach », « FC séance »).
- **Travail en cours** [observé] : courbes de nuit dans l'onglet Stats (durée de sommeil avec
  seuil, SpO2), corrections de saisie.
- **Difficultés visibles** [déduit] : formats hétérogènes déposés par les raccourcis (JSON
  dupliqués, virgules décimales, clés absentes dans les anciens fichiers) ; modifier les
  raccourcis iOS coûte cher, donc tout est absorbé côté app.
- **IA** [observé] : `AGENTS.md` détaillé partagé ; `CLAUDE.md` se limite à `@AGENTS.md`. Claude
  Code (développement + coach). **Aucun usage de Codex sur carnet** [déclaré], bien que
  l'AGENTS.md le prévoie.
- **Dépôt public** : il ne doit contenir aucun secret ni donnée personnelle [observé : AGENTS.md].

### 2.2 trading-sim — robot de trading en simulation stricte (projet le plus exigeant)

- **Objectif** [observé] : tester **en simulation uniquement** si des règles adaptatives peuvent
  battre « acheter et garder » sur le CAC 40. Zéro argent réel, zéro ordre, zéro courtier.
- **Stack** [observé] : Python 3.12, bibliothèque standard, tests `unittest` (16 fichiers de
  test, 31 fichiers .py au total) ; pas de `pyproject`, pas de `.venv` dans ce projet
  (le paquet `python3.12-venv` est désormais disponible sur la machine).
- **Méthode** [observé] : spécification d'architecture versionnée et gelée
  (`TRADING-SIM-ARCHITECTURE-V1.0`, révisions r3 → r3.4.1), registre de protocole scellé
  (`protocol/ledger.jsonl`), 17 rapports d'audit Codex dans `docs/audits/`, décisions de phase
  consignées dans `docs/decisions/`.
- **État** [observé] : dépôt privé, 20 commits en 60 jours, par salves (17-18 sept., puis 22
  sept.) ; phase 0 en cours. Une modification locale de la spécification (passage à r3.5) reste
  non commitée, car l'audit correspondant l'a rejetée.
- **Politique de capacités** [observé] : `.claude/settings.json` interdit WebFetch, WebSearch, le
  navigateur et tous les connecteurs claude.ai (Gmail, Drive, Notion…) sur ce projet.
- **Difficultés visibles** [déduit] : cycles longs de vérification formelle (plusieurs révisions
  gelées puis rejetées), coût élevé en jetons des audits contradictoires, machine lente pour les
  campagnes exhaustives.

### 2.3 chatgpt-trading-sim — espace de travail d'orchestration (hors git)

- **Nature** [observé] : dossier local non versionné, 37 entrées, dont 27 fichiers .md depuis le
  1er septembre. Il contient les missions rédigées par ChatGPT (`NEXT-CLAUDE-MISSION-*`,
  `STEERING-CLAUDE-*`, `NEXT-CODEX-AUDIT-*`, `NEXT-HERBIN-MINT-*`), les rapports de retour et les
  noyaux Python gelés (`modeld-v2-frozen`, `modeld-v3`, `recovery-authority-kernel`).
- **Rôle** [observé] : sur trading-sim, **ChatGPT (appelé « Work ») est l'architecte et
  l'arbitre**. « Work » ne travaille que sur trading-sim [déclaré] ; Claude Code exécute (noyaux, campagnes) ; Codex fait l'audit adversarial ;
  herbin-mint relit les missions lourdes (intégrité SHA-256, coût, charge machine) avant
  lancement.
- **Conventions** [observé] : empreinte SHA-256 dans un fichier `.sha256` séparé (jamais dans le
  document lui-même), noyaux gelés en lecture seule, verdicts en blocs `CLÉ = VALEUR` lisibles par
  machine.

### 2.4 ceramist — portfolio professionnel (sylvainherbin.ca)

- [observé] Site statique HTML (FR + `en/`), GitHub Pages, domaine personnalisé, sitemap et
  robots. 52 commits, surtout les 5-6 et 14-15 août via « Add files via upload » (interface web
  de GitHub). Dernier commit le 30 août (SEO : `x-default`, `lastmod`). Pas de CLAUDE.md ni
  d'AGENTS.md.
- [déduit] Projet en maintenance ; l'IA intervient ponctuellement (skill `deploy-site`).

### 2.5 restoration-id — site produit (restoration-id.com)

- [observé] Site statique (EN + `fr/`) : « identité numérique des restaurations sur implants ».
  8 commits, tous le 16 août, par upload web. Pas de CLAUDE.md ni d'AGENTS.md.
- [déclaré] Pas d'évolution du produit pour l'instant. Un Projet claude.ai privé lui est
  consacré (« Application Identité Numérique Implant… ») [observé : capture].

Hors périmètre, pour mémoire [observé : GitHub] : `console-mur` (dépôt privé, console de pilotage
à distance depuis l'iPhone) et d'anciens dépôts de cosmologie (2025, inactifs).

---

## 3. Configuration Claude Code

| Élément | Contenu | Usage | Nature |
|---|---|---|---|
| `~/.claude/CLAUDE.md` global | absent | — | [observé] |
| Skills perso | `maintenance-mint`, `deploy-site`, `latex-manuscrit`, `verif-numerique` | maintenance-mint ×2, deploy-site ×1 ; **latex-manuscrit et verif-numerique jamais invoqués** dans les transcripts présents | [observé] |
| Skills claude.ai synchronisés | ask-the-council, orchestrator, red-team, scientific-adversary, context-engine, courriel-labo, docs/pdf/xlsx/pptx… | ask-the-council ×1 ; les autres non invoqués dans Claude Code | [observé] |
| Commandes, agents, hooks | aucun (`commands/`, `agents/`, `hooks` absents) | — | [observé] |
| Plugins | marketplace `claude-plugins-official` déclarée ; aucun plugin propre observé | — | [observé] |
| MCP locaux | aucun (`mcpServers` vide) | — | [observé] |
| Connecteurs claude.ai | Gmail, Google Drive, Google Calendar, Notion, Canva, GoDaddy, Claude Docs, Claude in Chrome | Notion ≈30 appels ; Chrome 4 (extension souvent déconnectée) ; Gmail/Drive/Calendar non observés | [observé] |
| settings.json | thème sombre, notifications push des agents, avertissement Workflow désactivé, autorisations `sudo -A` limitées à apt / timeshift / findmnt | actif | [observé] |
| Mémoire automatique | 23 mémoires (projet racine) + 4 (trading-sim) : préférences de méthode, rôles des sessions, règles machine | très utilisée | [observé] |
| Mises à jour auto | `autoUpdates: false` dans `~/.claude.json`, mais mise à jour native réussie le 22/09 | [observé] ; mécanisme exact [inconnu] |

**Usage réel des outils** [observé, 14 transcripts] : Bash ≈2 900 appels (très dominant), Write
219, Edit 177, Monitor 151, ReadNotifications 146, Read 133, WebFetch 31, SendMessage 23,
WebSearch 19, Workflow 13, Skill 7, Agent 2. Commandes tapées : `/btw`, `/remote-control`,
`/compact`.

**Modèles** [observé, messages des transcripts] : Opus 5 ≈4 970, Fable 5.1 ≈3 080, Opus 5.5 ≈590
(depuis sa sortie), Opus 4.8 ≈370, Fable 5 ≈230, Sonnet 5 ≈200. Limite hebdomadaire Fable séparée,
atteinte à 75 % en milieu de semaine ; une réinitialisation promotionnelle a été utilisée le 23/09.

---

## 4. Configuration Codex

| Élément | Contenu | Nature |
|---|---|---|
| Modèle par défaut | `gpt-6-sol` depuis le 23/09 (avant : `gpt-6-astra`, puis brièvement `gpt-5.6-sol`), raisonnement `medium`, `service_tier = "priority"` | [observé] |
| Profils | `audit` (`gpt-6-sol`, xhigh), `rapide` (`gpt-6-sol`, low), `securite` (`gpt-daybreak-blue-latest`, high, conservé volontairement) ; les trois servent | [observé] ; usage et choix [déclaré] |
| Modèles disponibles | `gpt-6-sol`, `gpt-6-astra`, `gpt-6-luna` présents dans le cache des modèles | [observé] |
| Interface | app de bureau, parce que le trio CLI + tmux + remote control ne fonctionne pas encore pour Codex | [déclaré] |
| AGENTS.md global / `prompts/` | absents | [observé] |
| AGENTS.md projet | carnet seulement ; trading-sim n'en a volontairement pas (décision différée) | [observé] |
| Plugins actifs | codex-app-tools, visualize, documents, pdf, spreadsheets, presentations, template-creator, browser, unified-computer-use | [observé] |
| Skills | uniquement les skills système (imagegen, openai-docs, review-agent, skill-creator, plugin-creator, skill-installer) | [observé] |
| MCP | `node_repl` (celui du bundle de l'app) | [observé] |
| Projets approuvés | trading-sim et un dossier de travail Codex daté | [observé] |
| Règles | `rules/default.rules` : 32 Ko pour **une seule** `prefix_rule`, qui autorise un script d'audit entier collé tel quel | [observé] |
| Activité | installé le 17/09 ; fils nommés « Auditer l'architecture », « Arbitrage », « Auditeur », « Console » ; 6 sessions CLI, l'essentiel se passe dans l'app de bureau | [observé] |
| Modèle cité dans les audits passés | GPT-5.6 Sol, raisonnement high | [observé : rapport d'audit] |

**Rôle de Codex** [déclaré] : il sert surtout à **auditer ce que fait Claude**, sur trading-sim
et ailleurs (la console de pilotage, par exemple). Modèle principal : **GPT-6 Sol**, qui remplace GPT-5.6 Sol [déclaré, 23/09].

---

## 5. Façon de travailler observée

- **Orchestration à trois IA** [observé] : ChatGPT conçoit et arbitre, Claude Code exécute, Codex
  audite. Les missions sont des fichiers .md horodatés, hachés en SHA-256, relayés par Sylvain.
- **Validation humaine pas à pas** [observé : CLAUDE.md, mémoires] : diagnostic d'abord,
  proposition, accord explicite, puis exécution, une étape à la fois. Il exige de séparer le
  factuel du déduit et veut une critique franche, sans complaisance.
- **Pilotage à distance** [observé] : l'iPhone est l'interface principale (Remote Control,
  notifications push) ; il préfère recevoir un résultat livré plutôt qu'une consigne à recopier.
- **Commits** [observé] : carnet, très fréquents et petits (moyenne ≈7/jour, messages en
  français décrivant l'effet) ; trading-sim, rares et formels (`docs:`, `fix:`, `audit:`,
  `decision:`), passés par une PR ; sites, uploads web groupés.
- **Tests** [observé] : réels sur carnet (`node:test` + fixtures) et trading-sim (`unittest`,
  tests de causalité et de nullité) ; aucun sur les sites ; aucune CI.
- **Rythme** [observé] : sessions tardives (activité régulière après minuit), travail intense
  par vagues de plusieurs jours.
- **Frictions récurrentes** [observé] : limites d'usage (hebdomadaire et Fable) ; Wi-Fi fragile
  (pannes qui coupent les sessions à distance) ; machine lente pour les calculs ; coût en jetons
  des prompts d'audit très longs ; classificateur du mode auto qui bloque certaines écritures
  système ; extension Chrome souvent déconnectée ; empreinte d'un document inscrite dans le
  document lui-même, donc périmée (erreur corrigée par l'usage d'un fichier `.sha256` séparé).

---

## 6. Pistes d'optimisation déjà visibles

1. **Pas de CLAUDE.md global** [observé] : les règles transversales (français, tutoiement,
   validation pas à pas, factuel/déduit) vivent dans les mémoires et sont répétées dans chaque
   projet. Un `~/.claude/CLAUDE.md` court les centraliserait.
2. **trading-sim/CLAUDE.md périmé** [observé] : il annonce 6,7 Go de RAM et un `.venv` prévu,
   alors que la machine a 14 Gio et que trading-sim n'a pas de `.venv`. Le fichier est gelé
   jusqu'au micro-lot « AGENT INSTRUCTIONS NORMALIZATION » ; le correctif recommandé (retirer
   ces lignes, sans les remplacer) a été soumis à ChatGPT Work le 23/09.
3. **Aucun hook** [observé] : les contrôles répétés à la main (vérification SHA-256 des missions,
   `PYTHONDONTWRITEBYTECODE=1`, interdiction de `pkill -f`) pourraient devenir des hooks.
4. **Skills dormants** [observé] : `latex-manuscrit` et `verif-numerique` ne sont jamais
   déclenchés ; à revoir, à supprimer, ou à rendre déclenchables sur trading-sim (où les
   vérifications numériques abondent).
5. **Aucune commande ni aucun agent perso** [observé] alors que des gestes reviennent souvent :
   relais d'une mission vers herbin-trading, revue machine d'une campagne, synchronisation git.
6. **Règles Codex** [observé] : `default.rules` contient un script complet autorisé tel quel,
   inutile et illisible ; mieux vaut des préfixes courts.
7. **Profils Codex réalignés le 23/09** [observé] : le défaut, `audit` et `rapide` sont sur
   `gpt-6-sol` ; `securite` reste sur Daybreak par choix [déclaré]. Point de vigilance :
   le défaut de `config.toml` avait changé dans la journée, probablement depuis l'app de
   bureau [déduit] ; si le sélecteur de modèle de l'app réécrit ce fichier, vérifier que le
   réglage tient.
12. **Codex en CLI + tmux + remote control** [déclaré] : c'est l'objectif, pas encore atteint.
    Une nouveauté Codex qui le permettrait serait une alerte prioritaire.
8. **Pas d'AGENTS.md sur trading-sim** : c'est un choix délibéré, à ne pas « corriger »
   [observé : mémoire].
9. **Connecteurs non utilisés** [observé] : Gmail, Drive, Calendar, Canva et GoDaddy sont
   connectés mais jamais appelés dans Claude Code.
10. **Pas de CI** [observé] : carnet a des tests qui ne tournent qu'en local ; un workflow
    GitHub Actions minimal ne coûterait rien sur un dépôt public.
11. **Limite Fable** [déduit] : la consommation Fable/Opus approche les plafonds hebdomadaires ;
    le choix du modèle et du niveau d'effort par session (Sonnet pour les tâches machine
    simples) pourrait étaler la charge.

---

## 7. Usage hors machine (réponses de Sylvain, 23/09) et points restant ouverts

| Sujet | Réponse | Nature |
|---|---|---|
| App Claude (iPhone) | sert surtout à piloter ses sessions Claude Code à distance | [déclaré] |
| App Claude Desktop | il veut utiliser **toutes** ses fonctionnalités utiles au développement de ses projets | [déclaré] |
| Projets claude.ai | 3 : « Web app ia » (la veille elle-même, active le 23/09), « Application Identité Numérique Implant… » (privé, restoration-id), « Prothésiste Dentaire Indépendant » (lancement de son activité de sous-traitance) | [observé : capture] |
| Mémoire claude.ai | activée et jugée utile | [déclaré] |
| Skills claude.ai | surtout **red-team** ; les autres peu ou pas | [déclaré] |
| ChatGPT | abonnement Pro ; modèle principal **GPT-6 Sol** (remplace GPT-5.6 Sol le 23/09) ; utilisé aussi hors trading-sim (console de pilotage), principalement pour **auditer le travail de Claude** | [déclaré] |
| Codex | app de bureau ; profils audit / rapide / securite tous utilisés | [déclaré] |
| Priorité | trading-sim | [déclaré] |
| Irritant | méconnaissance des commandes et fonctionnalités, donc un usage sous-optimal | [déclaré] |
| restoration-id | pas d'évolution pour l'instant | [déclaré] |
| Veille attendue | alertes sur les **nouvelles fonctionnalités** ; longueur laissée à l'éditeur | [déclaré] |

Compléments [déclaré] :
- « Work » est l'usage de ChatGPT réservé à trading-sim ; ailleurs (la console, par exemple),
  ChatGPT/Codex sert aux audits du travail de Claude.
- Codex n'est pas utilisé sur carnet.
- ChatGPT Desktop : il n'en utilise que les connecteurs.
- Claude : il utilise les **artefacts**, les **connecteurs** et les **skills**. Les autres
  fonctions (Cowork, Projets en profondeur, routines planifiées…) sont à explorer ; il veut
  exploiter tout ce qui sert au développement, c'est donc un terrain naturel pour les
  recommandations.

**Consigne pour la veille** [déduit des réponses] : partir des nouveautés (changelogs de Claude Code
et de Codex, annonces Claude et ChatGPT), les rattacher à un usage concret sur trading-sim
d'abord, puis sur carnet et les sessions à distance, et expliquer la commande ou le réglage exact
à employer. Signaler en priorité ce qui débloque Codex en CLI + tmux + remote control, ce qui
allège la consommation des limites hebdomadaires, et ce qui renforce les audits croisés
Claude ↔ Codex.

---

Généré le 23 septembre 2026 par la session herbin-mint (Claude Code 2.1.280, Opus 5.5), en lecture
seule.
