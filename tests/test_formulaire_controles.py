"""Tests du formulaire des règles de contrôle (frigeo.formulaire_controles)."""

import pandas as pd
import pytest
from openpyxl import load_workbook

from frigeo.formulaire_controles import (
    COLONNES_BORNES,
    COLONNES_DECIMALES,
    COLONNES_DOUBLONS,
    COLONNES_LUHN,
    COLONNES_MOTIFS,
    COLONNES_TABLES,
    LIGNES_AJOUT,
    REPERE_EMPREINTE,
    empreinte_controles,
    exporter_formulaire,
    lignes_bornes,
    lignes_decimales,
    lignes_doublons,
    lignes_luhn,
    lignes_motifs,
    lignes_tables,
    observer_groupe,
    observer_luhn,
    observer_nombres,
    texte_nombre,
)

SIRET_VALIDES = ["73282932000074", "35600000000048", "44306184100047"]


def _nature(nature):
    return {"nature": {"regle": nature}}


def _jeu():
    """Deux tables fictives, leur dictionnaire (natures en vigueur) et le contenu de
    config/controles.yaml."""
    tables = {
        "factures": pd.DataFrame(
            {
                "num": ["F-1", "F-2", "F-3", "F-4"],
                "montant": [12.5, 181.45000000000002, 3, "7,25"],
                "remise": [0, 5, 15, None],
                "code": ["A1", "A2", "A3", "A4"],
                "siret": SIRET_VALIDES + ["12345678901234"],
                "salaire": [1800.5, 2500, 3100, 2000],
            }
        ),
        "parametres": pd.DataFrame({"annee": [2025], "taux": [0.42], "libelle": ["unique"]}),
    }
    dictionnaire = {
        "factures": {
            "num": _nature("texte"),
            "montant": _nature("nombre natif"),
            "remise": _nature("nombre natif"),
            "code": _nature("texte"),
            "siret": _nature("entier (texte)"),
            "salaire": _nature("nombre natif"),
        },
        "parametres": {
            "annee": _nature("nombre natif"),
            "taux": _nature("nombre natif"),
            "libelle": _nature("texte"),
        },
    }
    contenu = {
        "regles": {
            "factures": {
                "montant": {"decimales": 2},
                "remise": {"bornes": {"min": 0, "max": 15, "max_exclu": True}},
                "code": {"motif": "[A-Z][0-9]+"},
            },
        },
        "doublons": {"factures": {"cle": ["num"], "identique_hors_cle": False}},
        "ecartees": {"decimales": {"factures": ["salaire"]}, "doublons": {"factures": [["siret"]]}},
        "commentaires": {
            "bornes": {"factures": {"remise": "remise commerciale plafonnée"}},
            "doublons": {"factures": {"num": "numéro de facture"}},
        },
    }
    sensibles = {"factures": frozenset({"salaire"})}
    return tables, dictionnaire, contenu, sensibles


def _par_colonne(lignes):
    return {(ligne["table"], ligne["colonne"]): ligne for ligne in lignes}


def test_observations_des_nombres():
    serie = pd.Series([12.5, 181.45000000000002, 3, "7,25", "1 200", "abc", None, ""])
    assert observer_nombres(serie) == {"valeurs": 4, "min": 3, "max": 181.45000000000002,
                                       "decimales": 2}
    assert observer_nombres(pd.Series(["abc", None])) == {
        "valeurs": 0, "min": None, "max": None, "decimales": None,
    }
    assert texte_nombre(181.45000000000002) == "181,45"
    assert (texte_nombre(3), texte_nombre(0.5), texte_nombre(2.0)) == ("3", "0,5", "2")


def test_observations_des_cles_de_luhn_et_des_groupes():
    observation = observer_luhn(pd.Series(SIRET_VALIDES + ["12345678901234", "12 34", None]))
    assert observation == {"valeurs": 4, "part_valide": 0.75}
    assert observer_luhn(pd.Series(["abc"]))["part_valide"] is None
    donnees = pd.DataFrame({"a": ["x", "y", "x", None], "b": [1, 2, 1, 3]})
    assert observer_groupe(donnees, ["a"]) == {"lignes": 4, "renseignees": 3, "repetees": 2}
    assert observer_groupe(donnees, ["b"]) == {"lignes": 4, "renseignees": 4, "repetees": 2}
    assert observer_groupe(donnees, ["a", "b"])["repetees"] == 2


def test_lignes_des_decimales():
    lignes = _par_colonne(lignes_decimales(*_jeu()[:3]))
    # Une ligne par colonne numérique, codes compris, dans l'ordre du dictionnaire.
    assert list(lignes) == [
        ("factures", "montant"), ("factures", "remise"), ("factures", "siret"),
        ("factures", "salaire"),
        ("parametres", "annee"), ("parametres", "taux"),
    ]
    montant = lignes[("factures", "montant")]
    assert (montant["valeurs"], montant["observé"], montant["proposition"]) == (4, 2, 2)
    # Règle en vigueur : statut documenté, valeur dans la colonne à saisir.
    assert (montant["en_vigueur"], montant["statut"], montant["décimales"]) == (2, "documenté", 2)
    # Proposition écartée : statut invalide; sinon observé.
    assert lignes[("factures", "salaire")]["statut"] == "invalide"
    assert lignes[("factures", "remise")]["statut"] == "observé"
    assert lignes[("factures", "remise")]["décimales"] is None
    # Des entiers seuls n'ont aucune décimale.
    assert lignes[("parametres", "annee")]["proposition"] == 0


def test_lignes_des_bornes():
    tables, dictionnaire, contenu, sensibles = _jeu()
    lignes = _par_colonne(lignes_bornes(tables, dictionnaire, contenu, sensibles))
    remise = lignes[("factures", "remise")]
    assert (remise["observé"], remise["proposition"]) == ("de 0 à 15", "0 à 15")
    assert (remise["proposition_min"], remise["proposition_max"]) == (0, 15)
    assert (remise["en_vigueur"], remise["statut"]) == ("0 à 15 exclu", "documenté")
    assert (remise["min"], remise["min_exclu"], remise["max"], remise["max_exclu"]) == (
        0, "non", 15, "oui",
    )
    assert remise["commentaire"] == "remise commerciale plafonnée"
    montant = lignes[("factures", "montant")]
    assert (montant["proposition"], montant["statut"], montant["min"]) == (
        "3 à 181,45", "observé", None,
    )
    # Colonne sensible : minimum et maximum masqués, aucune proposition.
    salaire = lignes[("factures", "salaire")]
    assert (salaire["observé"], salaire["proposition"]) == ("masqué", "aucune")
    assert (salaire["proposition_min"], salaire["proposition_max"]) == (None, None)
    assert "1800" not in repr(salaire) and "3100" not in repr(salaire)


def test_lignes_des_cles_de_luhn():
    lignes = lignes_luhn(*_jeu()[:3])
    assert len(lignes) == 1
    siret = lignes[0]
    assert (siret["colonne"], siret["valeurs"], siret["observé"], siret["proposition"]) == (
        "siret", 4, "75 % de clés valides", "aucune",
    )
    tables, dictionnaire, contenu, _ = _jeu()
    tables["factures"]["siret"] = SIRET_VALIDES + [SIRET_VALIDES[0]]
    contenu["regles"]["factures"]["siret"] = {"cle_luhn": True}
    siret = lignes_luhn(tables, dictionnaire, contenu)[0]
    assert (siret["proposition"], siret["en_vigueur"], siret["statut"]) == (
        "oui", "oui", "documenté",
    )


def test_lignes_des_doublons():
    lignes = lignes_doublons(*_jeu()[:3])
    resume = [(l["table"], l["type"], l["colonnes"], l["origine"], l["statut"]) for l in lignes]
    # En vigueur, puis clés candidates (texte ou entier, toujours renseignées, sans
    # répétition, pas déjà déclarées seules), puis groupes écartés. Une table d'une
    # seule ligne n'a pas de candidate; un montant ou un salaire non plus.
    assert resume == [
        ("factures", "clé", "num", "en vigueur", "documenté"),
        ("factures", "unique", "code", "proposée", "observé"),
        ("factures", "unique", "siret", "écartée", "invalide"),
    ]
    assert lignes[0]["observé"] == "4 lignes renseignées sur 4, aucune répétition"
    assert lignes[0]["commentaire"] == "numéro de facture"
    # Sans clé déclarée, la première candidate est proposée comme clé.
    tables, dictionnaire, contenu, _ = _jeu()
    del contenu["doublons"]
    resume = [(l["type"], l["colonnes"]) for l in lignes_doublons(tables, dictionnaire, contenu)]
    assert resume == [("clé", "num"), ("clé", "code"), ("unique", "siret")]


def test_lignes_des_tables_et_des_motifs():
    tables, dictionnaire, contenu, _ = _jeu()
    assert lignes_tables(tables, dictionnaire, contenu) == [
        {"table": "factures", "lignes": 4, "clé_en_vigueur": "num", "identiques_hors_clé": "non"},
        {"table": "parametres", "lignes": 1, "clé_en_vigueur": None,
         "identiques_hors_clé": "oui"},
    ]
    assert lignes_motifs(contenu) == [
        {"table": "factures", "colonne": "code", "motif": "[A-Z][0-9]+"}
    ]


def test_empreinte_du_fichier_des_controles(tmp_path):
    chemin = tmp_path / "controles.yaml"
    assert empreinte_controles(chemin) == "absent"
    chemin.write_bytes(b"regles:\n  t: {}\n")
    empreinte = empreinte_controles(chemin)
    chemin.write_bytes(b"regles:\r\n  t: {}\r\n")
    assert empreinte_controles(chemin) == empreinte
    chemin.write_bytes(b"regles:\n  u: {}\n")
    assert empreinte_controles(chemin) != empreinte


def _exporter(tmp_path, nom="formulaire.xlsx"):
    tables, dictionnaire, contenu, sensibles = _jeu()
    return exporter_formulaire(
        tables, dictionnaire, contenu, sensibles, "2026-03", tmp_path / "f" / nom,
        empreinte="abc123",
    )


def _lire(feuille):
    lignes = list(feuille.iter_rows(values_only=True))
    return [dict(zip(lignes[0], l)) for l in lignes[1:] if any(v is not None for v in l)]


def test_formulaire_exporte(tmp_path):
    classeur = load_workbook(_exporter(tmp_path))
    assert classeur.sheetnames == [
        "mode_emploi", "décimales", "bornes", "clé_luhn", "doublons", "tables", "motifs",
        "listes",
    ]
    for nom, colonnes in (
        ("décimales", COLONNES_DECIMALES), ("bornes", COLONNES_BORNES),
        ("clé_luhn", COLONNES_LUHN), ("doublons", COLONNES_DOUBLONS),
        ("tables", COLONNES_TABLES), ("motifs", COLONNES_MOTIFS),
    ):
        assert tuple(c.value for c in classeur[nom][1]) == colonnes
        assert classeur[nom].protection.sheet
    assert classeur["listes"].sheet_state == "hidden"
    assert [c.value for c in classeur["listes"]["A"]] == ["factures", "parametres"]
    assert len(_lire(classeur["décimales"])) == 6
    assert len(_lire(classeur["doublons"])) == 3
    # Les nombres restent des nombres, les colonnes techniques sont masquées.
    bornes = classeur["bornes"]
    remise = next(l for l in _lire(bornes) if l["colonne"] == "remise")
    assert (remise["min"], remise["max"], remise["proposition_max"]) == (0, 15, 15)
    masquees = {
        bornes.cell(row=1, column=i).value
        for i in range(1, len(COLONNES_BORNES) + 1)
        if bornes.column_dimensions[bornes.cell(row=1, column=i).column_letter].hidden
    }
    assert masquees == {"proposition_min", "proposition_max"}
    # Repère de l'empreinte et décomptes du mode d'emploi.
    notice = classeur["mode_emploi"]
    repere = next(r for r in notice.iter_rows(values_only=True) if r[0] == REPERE_EMPREINTE)
    assert repere[1] == "abc123"
    texte = " ".join(str(c.value) for c in notice["A"] if c.value)
    assert "Feuille « décimales » : 4 lignes à « observé » sur 6" in texte
    assert "Feuille « doublons » : 1 sur 3" in texte


def test_cellules_modifiables_et_menus(tmp_path):
    classeur = load_workbook(_exporter(tmp_path))

    def libres(feuille, numero):
        return {
            c.value for c, d in zip(feuille[1], feuille[numero]) if not d.protection.locked
        }

    assert libres(classeur["décimales"], 2) == {"statut", "décimales", "commentaire"}
    assert libres(classeur["bornes"], 2) == {
        "statut", "min", "min_exclu", "max", "max_exclu", "commentaire",
    }
    assert libres(classeur["clé_luhn"], 2) == {"statut", "commentaire"}
    assert libres(classeur["doublons"], 2) == {"type", "statut", "commentaire"}
    # Lignes d'ajout en bas de la feuille des doublons.
    doublons = classeur["doublons"]
    assert libres(doublons, 5) == {"table", "type", "colonnes", "statut", "commentaire"}
    assert libres(doublons, 4 + LIGNES_AJOUT) == libres(doublons, 5)
    assert libres(doublons, 5 + LIGNES_AJOUT) == set()
    assert libres(classeur["tables"], 2) == {"identiques_hors_clé"}
    assert libres(classeur["motifs"], 2) == set()
    menus = {m.formula1 for m in doublons.data_validations.dataValidation}
    assert menus == {
        '"observé,valide,invalide,documenté"', '"clé,unique,présumé unique"',
        "'listes'!$A$1:$A$2",
    }
    menus = [m.formula1 for m in classeur["bornes"].data_validations.dataValidation]
    assert '"oui,non"' in menus
    for feuille in classeur.worksheets:
        assert all(m.showErrorMessage for m in feuille.data_validations.dataValidation)


def test_export_refuse_d_ecraser_un_formulaire(tmp_path):
    chemin = _exporter(tmp_path)
    with pytest.raises(FileExistsError, match="existe déjà"):
        _exporter(tmp_path)
    tables, dictionnaire, contenu, sensibles = _jeu()
    exporter_formulaire(
        tables, dictionnaire, contenu, sensibles, "2026-03", chemin, empreinte="x",
        ecraser=True,
    )


def test_aucune_valeur_d_une_colonne_sensible_dans_le_formulaire(tmp_path):
    classeur = load_workbook(_exporter(tmp_path))
    valeurs = {
        str(v) for feuille in classeur.worksheets for ligne in feuille.iter_rows(values_only=True)
        for v in ligne if v is not None
    }
    assert not valeurs & {"1800.5", "2500", "3100", "2000", "1800,5"}


def test_cles_du_formulaire_admises_dans_le_fichier_des_controles(tmp_path):
    from frigeo.controles import charger_regles_complementaires, lire_fichier_controles
    from frigeo.doublons import charger_declarations_doublons

    chemin = tmp_path / "controles.yaml"
    chemin.write_text(
        "regles:\n  t:\n    a: {decimales: 2}\n"
        "doublons:\n  t:\n    cle: [a]\n"
        "ecartees:\n  bornes:\n    t: [a]\n"
        "commentaires:\n  decimales:\n    t:\n      a: montant\n",
        encoding="utf-8",
    )
    assert set(lire_fichier_controles(chemin)) == {"regles", "doublons", "ecartees", "commentaires"}
    # Sans effet sur les contrôles.
    assert charger_regles_complementaires(chemin) == {"t": {"a": {"decimales": 2}}}
    assert charger_declarations_doublons(chemin) == {"t": {"cle": ["a"]}}
    chemin.write_text("regle:\n  t: {}\n", encoding="utf-8")
    with pytest.raises(ValueError) as erreur:
        lire_fichier_controles(chemin)
    assert (
        "les seules clés attendues sont « regles », « doublons », « ecartees » et "
        "« commentaires » (clé inconnue\u00a0: regle)"
    ) in str(erreur.value)
