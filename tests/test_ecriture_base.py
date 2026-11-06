"""Tests sans base de données du module frigeo.ecriture_base."""

import datetime as dt
import hashlib
from types import SimpleNamespace

import pandas as pd
import pytest

from frigeo.ecriture_base import (
    PROBLEME_DECIMALES,
    PROBLEME_GRAND,
    PROBLEME_HEURE,
    PROBLEME_LONGUEUR,
    ErreurEcriture,
    empreinte_fichier,
    lignes_journal_chargement,
    longueur_sql,
    message_sans_valeur,
    preparer,
    texte_livre,
    valeurs_chargement,
    valeurs_propre,
)
from frigeo.structure_base import construire_structure


# --- Valeurs de chargement ---------------------------------------------------------


@pytest.mark.parametrize(
    "valeur, attendu",
    [
        ("  Texte ", "  Texte "),
        ("", ""),
        (None, None),
        (float("nan"), None),
        (pd.NaT, None),
        (123, "123"),
        (12.5, "12.5"),
        (12.0, "12"),
        (0.1, "0.1"),
        (1e-05, "0.00001"),
        (-0.0, "0"),
        (1234567.891, "1234567.891"),
        (dt.datetime(2025, 3, 14), "2025-03-14"),
        (dt.datetime(2025, 3, 14, 8, 30), "2025-03-14 08:30:00"),
        (pd.Timestamp("2025-03-14"), "2025-03-14"),
        (dt.date(2025, 3, 14), "2025-03-14"),
        (dt.time(8, 30), "08:30:00"),
    ],
)
def test_texte_livre(valeur, attendu):
    assert texte_livre(valeur) == attendu


def test_longueur_sql_en_unites_utf16():
    assert longueur_sql("abc") == 3
    assert longueur_sql("é") == 1
    assert longueur_sql("\U0001F600") == 2


def test_chargement_garde_fou_longueur():
    colonne = valeurs_chargement(pd.Series(["a" * 4000, "a" * 4001, "\U0001F600" * 2001, None]))
    assert colonne.problemes == {PROBLEME_LONGUEUR: 2}


# --- Valeurs de propre -------------------------------------------------------------


def test_propre_texte_vide_devient_null():
    colonne = valeurs_propre(pd.Series(["A", "", "   ", None, 12]), "texte", "texte")
    assert colonne.valeurs == ["A", None, None, None, "12"]
    assert colonne.illisibles == 0


def test_propre_dates():
    serie = pd.Series(["14/03/2025", "31/02/2025", "", None, "2025-03-14"])
    colonne = valeurs_propre(serie, "date", "date JJ/MM/AAAA")
    assert colonne.valeurs == ["2025-03-14", None, None, None, None]
    assert colonne.illisibles == 2


def test_propre_date_native_avec_heure_arrete():
    serie = pd.Series([dt.datetime(2025, 3, 14), dt.datetime(2025, 3, 14, 10, 0)], dtype=object)
    colonne = valeurs_propre(serie, "date", "date native")
    assert colonne.valeurs == ["2025-03-14", None]
    assert colonne.problemes == {PROBLEME_HEURE: 1}


def test_propre_heures():
    colonne = valeurs_propre(pd.Series(["08:30", "8h30", None]), "heure", "heure HH:MM")
    assert colonne.valeurs == ["08:30:00", None, None]
    assert colonne.illisibles == 1


def test_propre_entiers():
    colonne = valeurs_propre(pd.Series(["45", "-3", "4,5", "", "9" * 20]), "entier", "entier (texte)")
    assert colonne.valeurs == ["45", "-3", None, None, None]
    assert colonne.illisibles == 1
    assert colonne.problemes == {PROBLEME_GRAND: 1}


def test_propre_decimaux_exacts():
    virgule = valeurs_propre(
        pd.Series(["12,5", "0,1", "-3,10", "12.5", None]), "décimal", "décimal virgule (texte)"
    )
    assert virgule.valeurs == ["12.5", "0.1", "-3.1", None, None]
    assert virgule.illisibles == 1
    natif = valeurs_propre(
        pd.Series([0.1, 12.0, 7, "7", 1234.5678], dtype=object), "décimal", "nombre natif"
    )
    assert natif.valeurs == ["0.1", "12", "7", None, "1234.5678"]
    assert natif.illisibles == 1


def test_propre_decimaux_garde_fous():
    colonne = valeurs_propre(
        pd.Series([0.123456789, 1e21, 0.12345678], dtype=object), "décimal", "nombre natif"
    )
    assert colonne.valeurs == [None, None, "0.12345678"]
    assert colonne.problemes == {PROBLEME_DECIMALES: 1, PROBLEME_GRAND: 1}


def test_propre_garde_l_index_de_la_serie():
    serie = pd.Series(["1", "x", "3"], index=[10, 5, 7])
    assert valeurs_propre(serie, "entier", "entier (texte)").valeurs == ["1", None, "3"]


# --- Fichiers chargés --------------------------------------------------------------


def regles(nature="texte"):
    return {
        "obligatoire": {"regle": "obligatoire"},
        "nature": {"regle": nature},
        "valeurs": {"regle": "aucune"},
        "format": {"regle": "aucune"},
    }


@pytest.fixture
def jeu(tmp_path):
    """Périmètre de deux fichiers (un CSV, un classeur à deux feuilles), tables
    chargées et nettoyées."""
    csv = tmp_path / "interventions_2025.csv"
    csv.write_bytes(b"id;duree\r\nI1;45\r\n")
    classeur = tmp_path / "factures_2025.xlsx"
    classeur.write_bytes(b"classeur")
    perimetre = SimpleNamespace(
        fichiers=[
            {"flux": "interventions", "periode": "2025", "fichier": csv.name, "chemin": csv},
            {"flux": "factures", "periode": "2025", "fichier": classeur.name, "chemin": classeur},
        ],
        config={
            "flux": {
                "interventions": {"tables": ["interventions"]},
                "factures": {
                    "tables": {
                        "factures_entetes": {"feuille": "Entetes"},
                        "factures_lignes": {"feuille": "Lignes"},
                    }
                },
            }
        },
    )
    interventions = pd.DataFrame(
        {
            "fichier_source": [csv.name, csv.name],
            "feuille_source": [None, None],
            "num_ligne_source": [2, 3],
            "periode_export": ["2025", "2025"],
            "id_intervention": ["I1", "I2"],
            "duree_min": ["45", "x"],
            "nb_champs_source": [2, 3],
            "champs_excedentaires": [None, "en trop"],
        }
    )
    entetes = pd.DataFrame(
        {
            "fichier_source": [classeur.name],
            "feuille_source": ["Entetes"],
            "num_ligne_source": [2],
            "periode_export": ["2025"],
            "num_facture": ["F1"],
            "total_ht": [100.5],
        }
    )
    lignes = entetes.iloc[0:0][["fichier_source", "feuille_source", "num_ligne_source", "periode_export"]].assign(
        num_facture=[]
    )
    tables = {"interventions": interventions, "factures_entetes": entetes, "factures_lignes": lignes}
    nettoyees = {
        "interventions": interventions.iloc[[0]].copy(),
        "factures_entetes": entetes.copy(),
        "factures_lignes": lignes.copy(),
    }
    structure = construire_structure(
        {
            "interventions": {"id_intervention": regles(), "duree_min": regles("entier (texte)")},
            "factures_entetes": {"num_facture": regles(), "total_ht": regles("nombre natif")},
            "factures_lignes": {"num_facture": regles()},
        },
        {},
    )
    return SimpleNamespace(
        perimetre=perimetre, tables=tables, nettoyees=nettoyees, structure=structure,
        csv=csv, classeur=classeur,
    )


def test_empreinte_fichier(jeu):
    assert empreinte_fichier(jeu.csv) == hashlib.sha256(b"id;duree\r\nI1;45\r\n").hexdigest()


def test_journal_une_ligne_par_fichier_et_feuille(jeu):
    journal = lignes_journal_chargement(jeu.perimetre, jeu.tables)
    assert [(l["fichier_source"], l["feuille_source"], l["nb_lignes"]) for l in journal] == [
        ("interventions_2025.csv", None, 2),
        ("factures_2025.xlsx", "Entetes", 1),
        ("factures_2025.xlsx", "Lignes", 0),
    ]
    assert journal[1]["empreinte_sha256"] == journal[2]["empreinte_sha256"]
    assert journal[1]["empreinte_sha256"] == hashlib.sha256(b"classeur").hexdigest()
    assert {l["periode_export"] for l in journal} == {"2025"}


# --- Préparation -------------------------------------------------------------------


def test_preparation(jeu):
    preparation = preparer(jeu.perimetre, jeu.tables, jeu.nettoyees, jeu.structure)
    tables = {(p.schema, p.table.source): p for p in preparation.tables}
    assert len(tables) == 6
    chargement = tables[("chargement", "interventions")]
    assert chargement.colonnes == [
        "periode_export", "fichier_source", "feuille_source", "num_ligne_source",
        "nb_champs_source", "champs_excedentaires", "id_intervention", "duree_min",
    ]
    assert chargement.lignes == [
        ["2025", "interventions_2025.csv", None, 2, 2, None, "I1", "45"],
        ["2025", "interventions_2025.csv", None, 3, 3, "en trop", "I2", "x"],
    ]
    assert chargement.lignage == [("interventions_2025.csv", None)] * 2
    propre = tables[("propre", "interventions")]
    assert propre.colonnes == [
        "periode_export", "fichier_source", "feuille_source", "num_ligne_source",
        "id_intervention", "duree_min",
    ]
    assert propre.lignes == [["2025", "interventions_2025.csv", None, 2, "I1", "45"]]
    assert tables[("propre", "factures_entetes")].lignes == [
        ["2025", "factures_2025.xlsx", "Entetes", 2, "F1", "100.5"]
    ]
    assert tables[("chargement", "factures_entetes")].lignes[0][-1] == "100.5"
    assert tables[("propre", "factures_lignes")].lignes == []
    assert preparation.illisibles.empty
    assert len(preparation.journal) == 3


def test_preparation_compte_les_illisibles_de_propre(jeu):
    jeu.nettoyees["interventions"] = jeu.tables["interventions"].copy()
    preparation = preparer(jeu.perimetre, jeu.tables, jeu.nettoyees, jeu.structure)
    assert preparation.illisibles.to_dict("records") == [
        {"table": "interventions", "colonne": "duree_min", "cellules": 1}
    ]


def test_garde_fous_sans_valeur(jeu):
    secret = "S" * 4001
    jeu.tables["interventions"].loc[0, "id_intervention"] = secret
    jeu.nettoyees["factures_entetes"].loc[0, "total_ht"] = 0.123456789
    with pytest.raises(ErreurEcriture) as erreur:
        preparer(jeu.perimetre, jeu.tables, jeu.nettoyees, jeu.structure)
    message = str(erreur.value)
    assert (
        "chargement.interventions.id_intervention (interventions.id_intervention) : "
        f"1 cellule(s), {PROBLEME_LONGUEUR}" in message
    )
    assert (
        "propre.factures_entetes.total_ht (factures_entetes.total_ht) : "
        f"1 cellule(s), {PROBLEME_DECIMALES}" in message
    )
    assert secret not in message
    assert "0.123456789" not in message


def test_table_absente(jeu):
    del jeu.nettoyees["factures_lignes"]
    with pytest.raises(ErreurEcriture, match="factures_lignes \\(nettoyée\\)"):
        preparer(jeu.perimetre, jeu.tables, jeu.nettoyees, jeu.structure)


def test_ligne_hors_perimetre(jeu):
    jeu.perimetre.fichiers = jeu.perimetre.fichiers[1:]
    with pytest.raises(ErreurEcriture, match="chargement.interventions"):
        preparer(jeu.perimetre, jeu.tables, jeu.nettoyees, jeu.structure)


def test_message_sans_valeur_tronquee():
    erreur = Exception(
        "String or binary data would be truncated in table 'frigeo.propre.clients', "
        "column 'adresse'. Truncated value: '12 rue des Lilas'."
    )
    message = message_sans_valeur(erreur)
    assert "Lilas" not in message
    assert "column 'adresse'" in message
    francais = message_sans_valeur(Exception("Valeur tronquée : 'Dupont'."))
    assert "Dupont" not in francais
