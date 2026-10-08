"""Tests de l'export du classeur de revue (frigeo.revue)."""

import pandas as pd
import pytest
from openpyxl import load_workbook

from frigeo.revue import (
    COLONNES_REGLES,
    COLONNES_VALEURS,
    LIGNES_AJOUT,
    exporter_revue,
    lignes_regles,
    lignes_valeurs,
)

PIEGES = ["076", "27", "2026-03-01", "=1+1", "Non", "Gisors  ", "a b"]


def _regle(regle, a_arbitrer, statut="observé"):
    return {"regle": regle, "statut": statut, "motif": "motif fictif", "a_arbitrer": a_arbitrer}


def _colonne(valeurs="aucune", a_arbitrer=None, vides=0, hors_nature=0):
    return {
        "obligatoire": _regle("obligatoire", {"vides": vides}),
        "nature": _regle("texte", {"hors_nature": hors_nature}),
        "valeurs": _regle(valeurs, [] if a_arbitrer is None else a_arbitrer),
    }


def _dictionnaire():
    return {
        "clients": {
            "statut": _colonne(
                ["Actif", "Inactif"], [{"valeur": "actif", "effectif": 3}], vides=5
            ),
            "code": _colonne(PIEGES),
            "type_commerce": _colonne(),
        },
        "interventions": {
            "duree": {
                "obligatoire": _regle("à décider", {"vides": 1}),
                "nature": _regle(
                    "à décider", {"nature_dominante": "entier (texte)", "hors_nature": 40}
                ),
                "valeurs": _regle("aucune", []),
            }
        },
    }


def _lire(feuille):
    lignes = list(feuille.iter_rows(values_only=True))
    return [dict(zip(lignes[0], ligne)) for ligne in lignes[1:] if any(v is not None for v in ligne)]


def test_lignes_regles():
    lignes = lignes_regles(_dictionnaire())
    cles = [(l["table"], l["colonne"], l["regle"]) for l in lignes]
    # Deux lignes par colonne, plus une ligne « valeurs » par liste proposée.
    assert len(lignes) == 4 * 2 + 2
    assert ("clients", "statut", "valeurs") in cles
    assert ("clients", "type_commerce", "valeurs") not in cles
    par_cle = dict(zip(cles, lignes))
    assert par_cle[("clients", "statut", "obligatoire")]["nb_a_arbitrer"] == 5
    assert par_cle[("clients", "statut", "valeurs")]["proposition"] == "liste de 2 valeurs"
    assert par_cle[("clients", "statut", "valeurs")]["nb_a_arbitrer"] == 1
    # Le nom de la nature dominante n'est pas compté comme un écart.
    assert par_cle[("interventions", "duree", "nature")]["nb_a_arbitrer"] == 40


def test_lignes_valeurs_sans_les_tables():
    lignes = lignes_valeurs(_dictionnaire())
    assert len(lignes) == 3 + len(PIEGES)
    assert {l["colonne"] for l in lignes} == {"statut", "code"}
    assert [l["effectif"] for l in lignes[:3]] == [None, None, 3]
    assert [l["origine"] for l in lignes[:3]] == ["liste proposée", "liste proposée", "à arbitrer"]
    remarques = {l["valeur"]: l["remarque"] for l in lignes}
    assert remarques["Gisors  "] == "espaces en bord"
    assert remarques["a b"] == "espace insécable"
    assert remarques["Actif"] == ""


def test_effectifs_comptes_dans_les_tables():
    donnees = pd.DataFrame(
        {"statut": pd.Series(["Actif"] * 7 + ["Inactif"] * 2 + ["actif", None, "  "], dtype=object)}
    )
    lignes = lignes_valeurs(_dictionnaire(), {"clients": donnees})
    assert [l["effectif"] for l in lignes[:3]] == [7, 2, 3]
    # Colonne absente des tables fournies : effectif laissé vide.
    assert lignes[3]["effectif"] is None


def test_classeur_ecrit_et_relu(tmp_path):
    chemin = exporter_revue(_dictionnaire(), "2026-03", tmp_path / "revue" / "revue.xlsx")
    classeur = load_workbook(chemin)
    assert classeur.sheetnames == ["mode_emploi", "regles", "valeurs"]
    regles, valeurs = classeur["regles"], classeur["valeurs"]
    assert tuple(c.value for c in regles[1]) == COLONNES_REGLES
    assert tuple(c.value for c in valeurs[1]) == COLONNES_VALEURS
    assert len(_lire(regles)) == 10
    assert {l["statut"] for l in _lire(regles)} == {"observé"}
    notice = " ".join(str(c.value) for c in classeur["mode_emploi"]["A"] if c.value)
    assert "2026-03" in notice
    assert "10 lignes" in notice
    assert "réimporté" in notice


def test_valeurs_conservees_comme_texte(tmp_path):
    chemin = exporter_revue(_dictionnaire(), "2026-03", tmp_path / "revue.xlsx")
    lues = [l for l in _lire(load_workbook(chemin)["valeurs"]) if l["colonne"] == "code"]
    assert [l["valeur"] for l in lues] == PIEGES
    assert all(isinstance(l["valeur"], str) for l in lues)


def test_protection_et_menus(tmp_path):
    chemin = exporter_revue(_dictionnaire(), "2026-03", tmp_path / "revue.xlsx")
    classeur = load_workbook(chemin)
    regles, valeurs = classeur["regles"], classeur["valeurs"]
    assert regles.protection.sheet and valeurs.protection.sheet
    assert classeur["mode_emploi"].protection.sheet
    # Feuille des règles : seules statut, regle_retenue et commentaire sont libres.
    libres = {c.value for c, d in zip(regles[1], regles[2]) if not d.protection.locked}
    assert libres == {"statut", "regle_retenue", "commentaire"}
    # Sur une ligne « valeurs », regle_retenue reste verrouillée.
    ligne = next(l for l in regles.iter_rows(min_row=2) if l[2].value == "valeurs")
    assert ligne[COLONNES_REGLES.index("regle_retenue")].protection.locked
    libres = {c.value for c, d in zip(valeurs[1], valeurs[2]) if not d.protection.locked}
    assert libres == {"statut", "commentaire"}
    # Lignes d'ajout en bas de la feuille des valeurs.
    ajout = valeurs[3 + len(PIEGES) + 2]
    libres = {c.value for c, d in zip(valeurs[1], ajout) if not d.protection.locked}
    assert libres == {"table", "colonne", "valeur", "statut", "commentaire"}
    assert valeurs.max_row == 1 + 3 + len(PIEGES) + LIGNES_AJOUT
    menus = [m.formula1 for m in regles.data_validations.dataValidation]
    assert '"observé,valide,invalide,documenté"' in menus
    assert '"obligatoire,facultatif,toujours vide"' in menus
    assert all(len(m) <= 255 for m in menus)
    assert len(valeurs.data_validations.dataValidation) == 1


def test_colonne_sans_liste_absente_de_la_feuille_des_valeurs(tmp_path):
    chemin = exporter_revue(_dictionnaire(), "2026-03", tmp_path / "revue.xlsx")
    colonnes = {l["colonne"] for l in _lire(load_workbook(chemin)["valeurs"])}
    assert "type_commerce" not in colonnes


def test_export_refuse_d_ecraser_un_classeur_existant(tmp_path):
    chemin = exporter_revue(_dictionnaire(), "2026-03", tmp_path / "revue.xlsx")
    with pytest.raises(FileExistsError, match="existe déjà"):
        exporter_revue(_dictionnaire(), "2026-03", chemin)
    exporter_revue(_dictionnaire(), "2026-03", chemin, ecraser=True)
