"""Décision du 26/10/2026 02:06 (DECISIONS.md « ORQYRA AI : LE SITE AI.ORQYRA.IO PASSE AU VOUVOIEMENT ») : tous les textes français
visibles d'ai.orqyra.io vouvoient, connecteur MCP compris. Seule la forme d'adresse change ; l'anglais reste tel quel.
Ce test échoue si un tutoiement subsiste dans : le dictionnaire français de docs/assets/textes.js, les pages et manifestes
servis sous docs/fr/, les chaînes des gabarits scripts/site_langues.py et scripts/versions.py, et le dictionnaire français du
connecteur (mcp/lib/textes.js). Sont hors champ, volontairement : docs/data/ (données), la phrase envoyée au système
(app.js, relais_reference.py, adoptions.py : changée d'un seul bloc ultérieurement) et les identifiants techniques."""

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from textes_site import FR

RACINE = Path(__file__).resolve().parent.parent
DOCS = RACINE / "docs"
# 124 clés françaises dans la base 5a66288 : toute perte de couverture doit échouer.
NOMBRE_CLES_FR_MCP = 124

# Pronoms et possessifs de la 2e personne du singulier.
PRONOMS = re.compile(r"(?<![\w-])(?:tu|toi|te|ton|ta|tes)(?![\w-])|(?<![\w])t'", re.IGNORECASE)

# Impératifs de la 2e personne du singulier. Les formes en -s sont sans ambiguïté et se repèrent partout ; les formes en -e
# se confondent avec la 3e personne (« il ouvre »), donc ne comptent qu'en tête de phrase ou après « puis / et / ou ».
IMP_S = ("choisis lis relis fais prends saisis reviens tiens retiens dis écris sois aie sache vas viens reprends répète "
         "attends suis peux veux dois sais n'hésite pense")
IMP_E = ("ouvre clique utilise colle touche tape valide vérifie essaie envoie ajoute ferme sélectionne "
         "retire supprime recharge installe lance relance appelle regarde consulte appuie glisse passe mets cherche "
         "donne demande indique précise ignore évite compare corrige signale reformule commence "
         "va patiente teste relie délie décris")
# Homographes retirés de la liste (noms ou adjectifs : « Copie refusée », « note », « entre », « active », « garde », « cite »).
IMPERATIFS = re.compile(
    r"(?<![\w-])(?:%s)(?!\w)|(?:(?:^|[.!?:;…»)]\s+|\b(?:puis|et|ou|alors|ensuite)\s+)(?:%s))(?!\w)"
    % ("|".join(IMP_S.split()), "|".join(IMP_E.split())),
    re.IGNORECASE,
)

# Liste blanche : (portée, mot en minuscules) tolérés. Chaque entrée dit pourquoi.
BLANCHE: set[tuple[str, str]] = {
    # Descriptions d'outils du connecteur : sujet omis à la 3e personne (« [L'outil] cherche… », « id donne… »), pas d'adresse.
    ("mcp", "cherche"), ("mcp", "donne"), ("mcp", "demande"), ("mcp", "passe"),
    # Valeur d'énumération du filtre `statut` (utilise, non_utilise, inconnu) : identifiant, pas un verbe.
    ("mcp", "utilise"),
    # Descriptions du « à quoi ça sert » à la 3e personne, sujet omis (« [Le connecteur] donne à Claude un accès… »,
    # « [L'icône] ouvre le site… ») ; l'anglais correspondant dit « Gives », « Opens ». Aucune adresse au lecteur.
    ("site:aide.mcp.sert", "donne"),
    ("site:aide.iphone.sert", "ouvre"),
}


def trouver(portee: str, texte: str, cle: str = "") -> list[str]:
    mots = [m.group(0).strip(" .!?:;…»)").lower() for m in PRONOMS.finditer(texte)]
    mots += [m.group(0).strip(" .!?:;…»)").lower().split()[-1] for m in IMPERATIFS.finditer(texte)]
    return [m for m in mots if (portee, m) not in BLANCHE and (f"{portee}:{cle}", m) not in BLANCHE]


def texte_visible(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    html = re.sub(r"(?s)<!--.*?-->", " ", html)
    attrs = " ".join(re.findall(r'\b(?:content|title|aria-label|placeholder|alt)="([^"]*)"', html))
    return re.sub(r"<[^>]+>", " ", html) + " " + attrs


def test_dictionnaire_fr_du_site_vouvoie():
    for cle, valeur in FR.items():
        assert not trouver("site", valeur, cle), (cle, valeur)


def test_pages_fr_servies_vouvoient():
    for chemin in ("fr/index.html", "fr/manifest.webmanifest"):
        texte = texte_visible((DOCS / chemin).read_text(encoding="utf-8"))
        assert not trouver("site", texte), (chemin, trouver("site", texte))


def test_gabarits_de_scripts_vouvoient():
    for nom in ("site_langues.py", "versions.py"):
        arbre = ast.parse((RACINE / "scripts" / nom).read_text(encoding="utf-8"))
        docstrings = {id(n.body[0].value) for n in ast.walk(arbre)
                      if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
                      and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for n in ast.walk(arbre):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings:
                assert not trouver("scripts", n.value), (nom, n.lineno, n.value)


def dictionnaire_fr_du_connecteur() -> dict[str, str]:
    node_nvm = Path.home() / ".nvm" / "current" / "bin" / "node"
    node = str(node_nvm) if node_nvm.is_file() else shutil.which("node")
    assert node, "Node est nécessaire à la garde de vouvoiement du connecteur"
    module = (RACINE / "mcp" / "lib" / "textes.js").as_uri()
    rendu = subprocess.run(
        [node, "--input-type=module", "--eval",
         "const { TEXTES } = await import(process.argv[1]); process.stdout.write(JSON.stringify(TEXTES.fr));", module],
        check=True, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    return json.loads(rendu.stdout)


def test_connecteur_mcp_fr_vouvoie():
    dico = dictionnaire_fr_du_connecteur()
    assert len(dico) == NOMBRE_CLES_FR_MCP, f"{NOMBRE_CLES_FR_MCP} clés françaises attendues, {len(dico)} lues"
    for cle, valeur in dico.items():
        assert isinstance(valeur, str), (cle, valeur)
        assert not trouver("mcp", valeur, cle), (cle, valeur)


@pytest.fixture
def copie_connecteur(tmp_path, monkeypatch):
    lib = tmp_path / "mcp" / "lib"
    lib.mkdir(parents=True)
    for nom in ("textes.js", "consultation.js"):
        shutil.copy2(RACINE / "mcp" / "lib" / nom, lib / nom)
    shutil.copy2(RACINE / "mcp" / "package.json", lib.parent / "package.json")
    monkeypatch.setitem(globals(), "RACINE", tmp_path)
    return lib / "textes.js"


@pytest.mark.parametrize("cle", [
    "local.limite_consultation",
    "outil.chercher_reference.description",
    "outil.chercher_reference.limite",
])
def test_garde_mcp_detecte_un_gabarit_tutoye(copie_connecteur, cle):
    source = copie_connecteur.read_text(encoding="utf-8")
    # La clé française seule est mutée ; les constantes et les backticks échappés restent évalués par Node.
    en, fr = source.split("  fr: {", 1)
    motif = rf'(^\s*"{re.escape(cle)}":\s*`.*)(`,\s*$)'
    fr, nombre = re.subn(motif, r"\1 Tu peux continuer.\2", fr, flags=re.MULTILINE)
    assert nombre == 1
    copie_connecteur.write_text(en + "  fr: {" + fr, encoding="utf-8")
    with pytest.raises(AssertionError, match=re.escape(cle)):
        test_connecteur_mcp_fr_vouvoie()


def test_garde_mcp_refuse_une_cle_manquante(copie_connecteur):
    with copie_connecteur.open("a", encoding="utf-8") as fichier:
        fichier.write('\ndelete TEXTES.fr["local.limite_consultation"];\n')
    with pytest.raises(AssertionError, match="124 clés françaises attendues, 123 lues"):
        test_connecteur_mcp_fr_vouvoie()


def test_detecteur_attrape_un_tutoiement():
    # Garde-fou : le détecteur voit bien les tutoiements courants et ne s'émeut pas du vouvoiement.
    for tutoie in ("Ouvre la console", "Pour toi", "vérifie tes remises", "Tape un mot puis choisis", "tu peux", "colle-la"):
        assert trouver("site", tutoie), tutoie
    for vouvoie in ("Ouvrez la console", "Pour vous", "Vérifiez vos remises", "Tapez un mot puis choisissez", "Vous pouvez"):
        assert not trouver("site", vouvoie), vouvoie
