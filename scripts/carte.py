#!/usr/bin/env python3
"""Carte fichiers → tests (D94) : quels tests exercent un fichier touché, sans lancer la suite complète.

La carte est calculée à la demande (ast des imports de `scripts/` et `tests/`, une fraction de seconde) : aucun
fichier généré à garder à jour. Règle de sélection pour un fichier touché :
- test : lui-même ;
- module de `scripts/` hors bibliothèque : ses tests directs et ceux de ses dépendants directs ;
- module central (`scripts/deltalib/`, importé par presque tout) : seulement ses tests directs et ceux dont le nom le
  désigne, plus `valider.py` (`valider=True`) ; ses dépendants ne sont pas ajoutés, ils rendraient la suite complète ;
- fichier hors graphe (prompt, page du site, skill, SPEC…) : les tests qui citent son chemin ou son nom ;
- fichier inconnu (aucun test ne le cite) : les tests dont le nom le désigne, plus `valider.py` ;
- socle de tests (`conftest.py`, `pytest.ini`, `requirements.txt`) : l'outillage de vérification seul, la CI fait foi.
Jamais la suite complète : la preuve de fusion est la CI GitHub sur le hash exact de la branche (CI-PREUVE).
"""
from __future__ import annotations

import ast
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CENTRAUX = ("scripts/deltalib/",)
SOCLE = ("tests/conftest.py", "pytest.ini", "requirements.txt")
# Données produites par les passages : aucun test n'en dépend, `valider.py` les contrôle.
DONNEES = ("docs/data/", "state/", "rapports/", "raw/")
GENERIQUES = ("SKILL.md", "README.md", "AGENTS.md", "CLAUDE.md.exemple", "__init__.py", "openai.yaml")
OUTILLAGE = ("tests/test_verifier.py", "tests/test_carte.py", "tests/test_skill_verify.py")


def _nom_module(rel: str) -> str:
    """`scripts/deltalib/kb/markdown.py` → `deltalib.kb.markdown` ; `tests/test_kb.py` → `test_kb`."""
    chemin = rel.removeprefix("scripts/").removeprefix("tests/").removesuffix(".py")
    return chemin.replace("/", ".").removesuffix(".__init__")


def _fichiers_python(racine: Path) -> list[str]:
    return sorted(p.relative_to(racine).as_posix() for dossier in ("scripts", "tests")
                  for p in (racine / dossier).rglob("*.py") if "fixtures" not in p.parts)


def _importes(arbre: ast.AST, paquet: list[str]) -> set[str]:
    """Noms de modules visés par les import d'un fichier, y compris `from a import b` (b peut être un sous-module)."""
    noms: set[str] = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            noms.update(a.name for a in noeud.names)
        elif isinstance(noeud, ast.ImportFrom):
            base = paquet[:len(paquet) - noeud.level + 1] if noeud.level else []
            module = ".".join(base + ([noeud.module] if noeud.module else []))
            noms.add(module)
            noms.update(f"{module}.{a.name}" for a in noeud.names)
    return noms


def generer(racine: Path = RACINE) -> dict:
    """{"imports": {fichier: [fichiers importés]}, "textes": {test: texte}} sur les fichiers Python de scripts/ et tests/."""
    fichiers = _fichiers_python(racine)
    modules = {_nom_module(rel): rel for rel in fichiers}
    imports: dict[str, list[str]] = {}
    for rel in fichiers:
        nom = _nom_module(rel)
        paquet = nom.split(".") if rel.endswith("__init__.py") else nom.split(".")[:-1]
        try:
            arbre = ast.parse((racine / rel).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            imports[rel] = []
            continue
        deps = set()
        for cible in _importes(arbre, paquet):
            morceaux = cible.split(".")
            for i in range(1, len(morceaux) + 1):  # les __init__.py des paquets s'exécutent aussi
                cle = ".".join(morceaux[:i])
                if cle in modules and modules[cle] != rel:
                    deps.add(modules[cle])
        imports[rel] = sorted(deps)
    textes = {}
    for rel in fichiers:
        if rel.startswith("tests/test_"):
            try:
                textes[rel] = (racine / rel).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                textes[rel] = ""
    return {"imports": imports, "textes": textes}


def _tests_directs(carte: dict, fichier: str) -> set[str]:
    return {t for t in carte["textes"] if fichier in carte["imports"].get(t, ())}


def _tests_du_nom(carte: dict, fichier: str) -> set[str]:
    """Tests dont le nom contient celui du fichier (`scripts/deltalib/kb/markdown.py` → `test_kb_markdown.py`, `test_kb.py` par le
    dossier) ; un nom trop court ou générique ne désigne rien."""
    parties = [Path(fichier).stem, *(p for p in Path(fichier).parent.parts if p not in ("scripts", "deltalib", "tests", "docs", "."))]
    trouves = set()
    for partie in parties:
        cle = partie.replace("-", "_").lower()
        if len(cle) < 4 or cle.startswith("__"):
            continue
        trouves.update(t for t in carte["textes"] if cle in Path(t).stem.lower())
    return trouves


def _tests_qui_citent(carte: dict, fichier: str) -> set[str]:
    """Tests dont le texte cite le chemin du fichier, `dossier/nom`, ou son seul nom s'il est distinctif (`app.js`,
    `supervision.md` ; pas `SKILL.md` ni `README.md`, que citent des tests sans rapport). Les tests composent souvent le
    chemin par morceaux (`"docs" / "assets" / "app.js"`) : la réunion des trois cas les trouve tous."""
    chemin = Path(fichier)
    candidats = [fichier, f"{chemin.parent.name}/{chemin.name}"]
    if chemin.name not in GENERIQUES and len(chemin.name) >= 5:
        candidats.append(chemin.name)
    return {t for t, texte in carte["textes"].items() if any(c in texte for c in candidats)}


def selectionner(carte: dict, chemins: list[str]) -> dict:
    """{"tests": [...], "valider": bool, "raisons": [...]} pour les fichiers touchés. Jamais la suite complète."""
    tests: set[str] = set()
    valider = False
    raisons: list[str] = []
    for chemin in sorted(set(chemins)):
        if chemin.startswith(DONNEES) or chemin in ("PROGRESSION.md", "CONTEXTE.md"):
            valider = True
            raisons.append(f"{chemin} : données ou suivi, valider.py")
        elif chemin in SOCLE:
            tests.update(OUTILLAGE)
            raisons.append(f"{chemin} : socle des tests, outillage de vérification seul (la CI fait foi)")
        elif chemin.startswith("tests/test_") and chemin.endswith(".py"):
            tests.add(chemin)
            raisons.append(f"{chemin} : test modifié")
        elif chemin in carte["imports"]:
            if chemin.startswith(CENTRAUX):
                tests.update(_tests_directs(carte, chemin) | _tests_du_nom(carte, chemin))
                valider = True
                raisons.append(f"{chemin} : module central, ses tests directs et valider.py")
            elif chemin.startswith("tests/"):  # aide de tests (autre que conftest)
                tests.update(_tests_directs(carte, chemin))
                raisons.append(f"{chemin} : aide de tests, les tests qui l'importent")
            else:
                dependants = {p for p, deps in carte["imports"].items() if chemin in deps and p.startswith("scripts/")}
                tests.update(_tests_directs(carte, chemin) | _tests_du_nom(carte, chemin))
                for dep in dependants:
                    tests.update(_tests_directs(carte, dep))
                raisons.append(f"{chemin} : module et {len(dependants)} dépendant(s) direct(s)")
        else:
            cites = _tests_qui_citent(carte, chemin)
            if cites:
                tests.update(cites)
                raisons.append(f"{chemin} : cité par {len(cites)} test(s)")
            else:
                nommes = _tests_du_nom(carte, chemin)
                tests.update(nommes or OUTILLAGE)  # jamais « aucun test » ni la suite complète
                valider = True
                raisons.append(f"{chemin} : fichier inconnu de la carte, "
                               + ("tests de même nom" if nommes else "outillage de vérification") + " et valider.py")
    return {"tests": sorted(t for t in tests if t in carte["textes"]), "valider": valider, "raisons": raisons}


def main() -> int:
    import json
    import sys
    carte = generer()
    resultat = selectionner(carte, sys.argv[1:])
    print(json.dumps(resultat, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
