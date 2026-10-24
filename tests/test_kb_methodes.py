"""D121 : fiches de méthode locales (kb-methodes/*.md → docs/data/kb/methodes.json), validation, site et accueil intacts."""

import json
import re
import shutil
import subprocess
import sys

import pytest

import valider
from conftest import RACINE
from deltalib.kb import methodes as m
from textes_site import FR

ENTETE = """---
id: {id}
nom: "Une méthode"
produits: [claude-code, codex]
verifie_le: 2026-10-13
versions:
  claude-code: 2.1.296
  codex: 0.162.1
certitude: officiel
sources:
  - url: https://code.claude.com/docs/en/headless
    libelle: "Claude Code — mode non interactif"
---

Texte de la méthode.

```bash
codex exec -s read-only -
```
"""


@pytest.fixture
def depot(tmp_path):
    (tmp_path / "kb-methodes").mkdir()
    (tmp_path / "kb-methodes" / "une-methode.md").write_text(ENTETE.format(id="une-methode"), encoding="utf-8")
    return tmp_path


def rapport(racine):
    r = valider.Rapport()
    valider.verifier_methodes(racine, r)
    return r


def test_lecture_d_une_fiche_complete(depot):
    e = m.lire_fiche(depot / "kb-methodes" / "une-methode.md")
    assert e["id"] == "methode-une-methode" and e["produit"] == "claude-code" and e["produits"] == ["claude-code", "codex"]
    assert e["categorie"] == "methodes" and e["origine"] == "locale" and e["commentee"] is True and e["retiree"] is False
    assert e["usage"] == "codex exec -s read-only -" and e["usage_nature"] == "syntaxe"
    assert e["verifie_le"] == e["maj_le"] == "2026-10-13" and e["versions"] == {"claude-code": "2.1.296", "codex": "0.162.1"}
    assert e["sources"] == [{"url": "https://code.claude.com/docs/en/headless", "libelle": "Claude Code — mode non interactif", "officielle": True}]
    assert e["fichier_source"] == "kb-methodes/une-methode.md"


@pytest.mark.parametrize("ancien, nouveau, message", [
    ("id: une-methode", "id: autre", "nom du fichier"),
    ("produits: [claude-code, codex]", "produits: [gemini]", "produits"),
    ("certitude: officiel", "certitude: sur", "certitude"),
    ("verifie_le: 2026-10-13", "verifie_le: hier", "verifie_le"),
    ("https://code.claude.com/docs/en/headless", "http://code.claude.com/docs/en/headless", "https"),
    ("    libelle: \"Claude Code — mode non interactif\"\n", "", "libelle"),
    ("versions:\n  claude-code: 2.1.296\n  codex: 0.162.1\n", "", "versions"),
    ("Texte de la méthode.\n\n```bash\ncodex exec -s read-only -\n```", "", "corps vide"),
])
def test_fiche_invalide_refusee(depot, ancien, nouveau, message):
    f = depot / "kb-methodes" / "une-methode.md"
    texte = f.read_text(encoding="utf-8")
    assert ancien in texte
    f.write_text(texte.replace(ancien, nouveau), encoding="utf-8")
    with pytest.raises(m.FicheMethodeInvalide, match=message):
        m.lire_fiche(f)


def test_entete_absent_refuse(depot):
    f = depot / "kb-methodes" / "une-methode.md"
    f.write_text("Pas d'en-tête.\n", encoding="utf-8")
    with pytest.raises(m.FicheMethodeInvalide, match="en-tête"):
        m.lire_fiche(f)


def test_generation_deterministe_et_suppression_de_la_source(depot):
    a = m.ecrire_methodes(depot)
    octets = m.chemin_methodes(depot).read_bytes()
    assert a["total"] == 1 and a["maj_le"] == "2026-10-13" and a["origine"] == "locale"
    m.ecrire_methodes(depot)
    assert m.chemin_methodes(depot).read_bytes() == octets
    (depot / "kb-methodes" / "une-methode.md").unlink()
    assert m.ecrire_methodes(depot)["entrees"] == []


def test_validation_fichier_absent_perime_ou_sensible(depot):
    r = rapport(depot)
    assert not r.ok and "absent" in r.erreurs[0]
    m.ecrire_methodes(depot)
    assert rapport(depot).ok
    chemin = m.chemin_methodes(depot)
    ok = chemin.read_text(encoding="utf-8")
    chemin.write_text(ok.replace("Texte de la méthode.", "Texte modifié."), encoding="utf-8")
    assert any("périmé" in e or "reproduit" in e or "régénér" in e or "catalogue.py methodes" in e for e in rapport(depot).erreurs)
    chemin.write_text(ok.replace("Texte de la méthode.", "Voir /home/sylvain/x."), encoding="utf-8")
    assert any("/home/" in e for e in rapport(depot).erreurs)
    chemin.write_text(ok.replace("Texte de la méthode.", "clé sk-ant-api03-" + "a" * 40), encoding="utf-8")
    assert not rapport(depot).ok
    chemin.write_text(ok, encoding="utf-8")
    (depot / "kb-methodes" / "une-methode.md").unlink()
    assert any("périmé" in e or "reproduit" in e or "régénér" in e or "catalogue.py methodes" in e for e in rapport(depot).erreurs)


def test_sans_dossier_ni_fichier_la_validation_accepte(tmp_path):
    assert rapport(tmp_path).ok


def test_la_base_du_depot_est_a_jour_et_valide():
    r = rapport(RACINE)
    assert r.ok, r.erreurs
    assert m.construire_methodes(RACINE) == json.loads(m.chemin_methodes(RACINE).read_text(encoding="utf-8"))
    doc = json.loads(m.chemin_methodes(RACINE).read_text(encoding="utf-8"))
    ids = [e["id"] for e in doc["entrees"]]
    assert "methode-consultation-croisee" in ids and len(ids) == len(set(ids))
    f = next(e for e in doc["entrees"] if e["id"] == "methode-consultation-croisee")
    assert f["produits"] == ["claude-code", "codex"] and f["certitude"] == "officiel"
    urls = {s["url"] for s in f["sources"]}
    assert {"https://code.claude.com/docs/en/headless", "https://code.claude.com/docs/en/cli-reference",
            "https://learn.chatgpt.com/docs/non-interactive-mode", "https://learn.chatgpt.com/docs/developer-commands?surface=cli"} <= urls
    assert all(u.startswith("https://") for u in urls)
    assert "/home/" not in json.dumps(doc)


def test_commande_catalogue_methodes(depot):
    def lancer(*args):
        return subprocess.run([sys.executable, str(RACINE / "scripts" / "catalogue.py"), "methodes", "--racine", str(depot), *args],
                              capture_output=True, text=True, cwd=RACINE)
    sec = lancer("--dry-run")
    assert sec.returncode == 0 and not m.chemin_methodes(depot).exists(), sec.stderr
    reel = lancer()
    assert reel.returncode == 0 and "1 fiche" in reel.stdout, reel.stderr
    assert json.loads(m.chemin_methodes(depot).read_text(encoding="utf-8"))["total"] == 1
    (depot / "kb-methodes" / "une-methode.md").write_text("sans en-tête", encoding="utf-8")
    assert lancer().returncode != 0


def test_maj_n_ecrit_pas_methodes_json():
    texte = (RACINE / "scripts" / "catalogue.py").read_text(encoding="utf-8")
    assert texte.count("ecrire_methodes") == 1 and 'a.commande == "methodes"' in texte


def test_accueil_et_fichiers_legers_n_integrent_pas_les_methodes():
    for nom in ("recent.json", "a-tester.json", "noms.json"):
        assert "methode-" not in (RACINE / "docs" / "data" / "kb" / nom).read_text(encoding="utf-8"), nom


def test_site_affiche_les_methodes_sans_innerhtml():
    app = (RACINE / "docs" / "assets" / "app.js").read_text(encoding="utf-8")
    assert '"methodes", "modeles"]' in app and FR["categorie.methodes"] == "Méthodes" and 'const KB_LOCALE = "locale"' in app and "function carteMethode" in app
    corps = app[app.index("function noeudsEnLigne"):app.index("function carteMethode")]
    assert "innerHTML" not in corps and "innerHTML" not in app[app.index("function carteMethode"):app.index("function carteMethode") + 3500]
    assert "^methode-" in app
