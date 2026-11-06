"""Tests sans base de données du module frigeo.ecriture_base."""

import datetime as dt
from decimal import Decimal
import hashlib
from types import SimpleNamespace

import pandas as pd
import pytest

from frigeo.ecriture_base import (
    COLONNES_CELLULES_ILLISIBLES,
    CLE_LIGNAGE,
    SortiesQualite,
    attendus_table,
    champ_sensible,
    conformite,
    convertir_lignes,
    PROBLEME_DECIMALES,
    PROBLEME_GRAND,
    PROBLEME_HEURE,
    PROBLEME_LONGUEUR,
    ErreurEcriture,
    empreinte_fichier,
    lignes_decisions,
    lignes_journal_chargement,
    lignes_jours_feries,
    lignes_qualite,
    lignes_valeurs_liste,
    longueur_sql,
    message_sans_valeur,
    preparer,
    problemes_sorties,
    texte_livre,
    valeurs_chargement,
    valeurs_propre,
    valeur_lue,
    valeur_sql,
)
from frigeo.dictionnaire import MOTIF_SENSIBLE, est_masquee
from frigeo.nettoyage import empreinte_valeur
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


# --- Tables de qualite (7.2d) -------------------------------------------------------


def regles_colonne(nature="texte"):
    """Règles d'une colonne avec le motif de chaque règle, comme au dictionnaire."""
    resultat = regles(nature)
    for regle in resultat.values():
        regle["motif"] = "proposé"
    return resultat


def decisions_exemple():
    commun = {
        "fichier_source": "clients.csv", "feuille_source": None, "num_ligne_source": 12,
        "constat": "constat", "empreinte": "e" * 16, "nature": None, "commentaire": None,
        "decide_le": "2026-10-20 10:15:00", "classeur": "arbitrage_2026-03.xlsx",
    }
    return {
        "meta": {"structure": 1, "imports": [], "retraits": []},
        "decisions": {
            "a1": {**commun, "sorte": "cellule", "table": "clients", "champ": "adresse",
                   "decision": "corriger", "valeur_retenue": "12 rue des Lilas"},
            "b2": {**commun, "sorte": "cellule", "table": "clients", "champ": "cp",
                   "decision": "corriger", "valeur_retenue": "27000"},
            "c3": {**commun, "sorte": "ligne", "table": "clients", "champ": None,
                   "decision": "retirer", "valeur_retenue": None},
        },
    }


CLE_TEST = "0123456789abcdef" * 4


def test_lignes_decisions_masquent_les_champs_sensibles():
    dictionnaire = {"clients": {"adresse": regles_colonne(), "cp": regles_colonne()}}
    lignes = lignes_decisions(
        decisions_exemple(), dictionnaire, {"clients": frozenset({"adresse"})}, CLE_TEST
    )
    par_id = {l["id_decision"]: l for l in lignes}
    assert par_id["a1"]["valeur_retenue"] is None
    assert par_id["a1"]["empreinte_valeur_retenue"] == empreinte_valeur("12 rue des Lilas", CLE_TEST)
    assert par_id["b2"]["valeur_retenue"] == "27000"
    assert par_id["b2"]["empreinte_valeur_retenue"] is None
    assert par_id["c3"]["empreinte_valeur_retenue"] is None
    assert par_id["a1"]["table_source"] == "clients"
    assert "table" not in par_id["a1"]
    assert all("Lilas" not in str(v) for l in lignes for v in l.values())


def test_champ_sensible_par_le_dictionnaire():
    masquee = regles_colonne()
    masquee["valeurs"]["motif"] = MOTIF_SENSIBLE
    assert est_masquee(masquee["valeurs"])
    dictionnaire = {"t": {"a": masquee, "b": regles_colonne()}}
    assert champ_sensible({}, dictionnaire, "t", "a")
    assert champ_sensible({"t": frozenset({"b"})}, dictionnaire, "t", "b")
    assert not champ_sensible({}, dictionnaire, "t", "b")
    assert not champ_sensible({}, dictionnaire, "t", None)
    assert not champ_sensible({}, dictionnaire, "autre", "x")


def sorties_exemple():
    anomalies = pd.DataFrame(
        {"id_anomalie": ["x1"], "table": ["clients"], "fichier_source": ["clients.csv"],
         "feuille_source": [""], "num_ligne_source": [2.0], "valeur": ["masqué"]}
    )
    sans_ligne = pd.DataFrame(
        {"id_anomalie": ["y2"], "table": ["fec"], "fichier_source": [None],
         "feuille_source": [None], "num_ligne_source": [None], "valeur": [None]}
    )
    nettoyees = pd.DataFrame(
        anomalies.to_dict("records") + sans_ligne.to_dict("records")
    ).assign(decision_metier=["garder", None])
    bilan = pd.DataFrame({"controle": ["c"], "table": ["clients"], "taux": [0.123456]})
    return SortiesQualite(
        anomalies_brutes=anomalies, bilan_brut=bilan, non_evaluables_brutes=anomalies.iloc[0:0],
        anomalies_nettoyees=nettoyees, bilan_nettoye=bilan,
        non_evaluables_nettoyees=anomalies.iloc[0:0],
        journal_nettoyage=pd.DataFrame(
            {"regle_nettoyage": ["espaces"], "table": ["clients"],
             "fichier_source": ["clients.csv"], "feuille_source": [None]}
        ),
        bilan_nettoyage=pd.DataFrame({"regle_nettoyage": ["espaces"], "table": ["clients"]}),
        decisions=decisions_exemple(),
        dictionnaire={"clients": {"adresse": regles_colonne(), "cp": regles_colonne()}},
        cle_empreinte=CLE_TEST,
    )


def test_lignes_qualite():
    lignes = lignes_qualite(sorties_exemple(), sensibles={"clients": frozenset({"adresse"})})
    assert list(lignes) == [
        "anomalie", "non_evaluable", "bilan_controle", "journal_nettoyage",
        "bilan_nettoyage", "decision", "jour_ferie", "valeur_liste",
    ]
    anomalies = lignes["anomalie"]
    assert [(l["etat"], l["id_anomalie"]) for l in anomalies] == [
        ("brut", "x1"), ("nettoyé", "x1"), ("nettoyé", "y2"),
    ]
    assert anomalies[0]["table_source"] == "clients"
    assert anomalies[0]["valeur"] == "masqué"
    assert anomalies[0][CLE_LIGNAGE] == ("clients.csv", None)
    assert anomalies[2][CLE_LIGNAGE] is None
    assert CLE_LIGNAGE not in lignes["bilan_controle"][0]
    assert lignes["journal_nettoyage"][0][CLE_LIGNAGE] == ("clients.csv", None)
    assert "etat" not in lignes["journal_nettoyage"][0]
    assert len(lignes["decision"]) == 3
    assert lignes["jour_ferie"] == []
    assert lignes["valeur_liste"] == []


def test_lignes_jours_feries():
    jours = {2025: [dt.date(2025, 1, 1), dt.date(2025, 5, 1)], 2026: []}
    assert lignes_jours_feries(jours) == [
        {"annee": 2025, "jour": dt.date(2025, 1, 1)},
        {"annee": 2025, "jour": dt.date(2025, 5, 1)},
        {"annee": 2026, "jour": None},
    ]
    assert lignes_jours_feries({}) == []
    colonnes = {"id_execution": ("int", None, 0), "annee": ("smallint", None, 0),
                "jour": ("date", None, None)}
    noms, valeurs, problemes = convertir_lignes(
        "jour_ferie", lignes_jours_feries(jours), colonnes, {}, {"id_execution": 4}
    )
    assert problemes == []
    assert noms == ["id_execution", "annee", "jour"]
    assert valeurs == [[4, 2025, "2025-01-01"], [4, 2025, "2025-05-01"], [4, 2026, None]]


def _element(valeur, statut, origine="liste proposée"):
    return {"valeur": valeur, "statut": statut, "origine": origine}


def test_lignes_valeurs_liste():
    categorie = regles_colonne()
    categorie["valeurs"] = {"regle": "liste fermée", "motif": "proposé", "liste": [
        _element("Dépannage", "valide"),
        _element("SAV", "invalide"),
        _element("Maintenance", "observé"),
        _element("Divers", "observé", "à arbitrer"),
        _element("Installation", "documenté", "ajoutée"),
    ]}
    ouverte = regles_colonne()
    ouverte["valeurs"] = {"regle": "aucune", "motif": "proposé",
                          "liste": [_element("x", "valide")]}
    ecartee = regles_colonne()
    ecartee["valeurs"] = {"regle": "aucune", "motif": "proposé",
                          "liste": [_element("y", "observé")]}
    masquee = regles_colonne()
    masquee["valeurs"] = {"regle": "liste fermée", "motif": MOTIF_SENSIBLE,
                          "liste": [_element("CDI", "valide")]}
    classee = regles_colonne()
    classee["valeurs"] = {"regle": "liste fermée", "motif": "proposé",
                          "liste": [_element("Secret", "valide")]}
    dictionnaire = {
        "interventions": {"categorie": categorie, "commentaire": ouverte, "statut": ecartee},
        "intervenants": {"type_contrat": masquee, "poste": classee},
    }
    lignes = lignes_valeurs_liste(dictionnaire, {"intervenants": frozenset({"poste"})})
    assert lignes == [
        {"table_source": "interventions", "colonne_source": "categorie", "rang": 1,
         "valeur": "Dépannage", "statut": "valide"},
        {"table_source": "interventions", "colonne_source": "categorie", "rang": 2,
         "valeur": "Maintenance", "statut": "observé"},
        {"table_source": "interventions", "colonne_source": "categorie", "rang": 3,
         "valeur": "Installation", "statut": "documenté"},
    ]
    sorties = sorties_exemple()
    sorties.dictionnaire = dictionnaire
    sorties.jours_feries = {2025: [dt.date(2025, 1, 1)]}
    par_table = lignes_qualite(sorties, sensibles={"intervenants": frozenset({"poste"})})
    assert par_table["valeur_liste"] == lignes
    assert par_table["jour_ferie"] == [{"annee": 2025, "jour": dt.date(2025, 1, 1)}]


@pytest.mark.parametrize(
    "valeur, type_sql, echelle, attendu",
    [
        (2.0, "int", None, 2),
        ("12", "int", None, 12),
        (None, "int", None, None),
        ("", "int", None, None),
        (0.123456, "decimal", 4, "0.1235"),
        (None, "decimal", 4, None),
        (True, "bit", None, 1),
        ("masqué", "nvarchar", None, "masqué"),
        ("", "nvarchar", None, ""),
        (12.5, "nvarchar", None, "12.5"),
        ("2026-10-20 10:15:00", "datetime2", None, "2026-10-20 10:15:00"),
    ],
)
def test_valeur_sql(valeur, type_sql, echelle, attendu):
    assert valeur_sql(valeur, type_sql, echelle) == attendu


COLONNES_ANOMALIE_TEST = {
    "id_execution": ("int", None, 0),
    "etat": ("nvarchar", 10, None),
    "id_anomalie": ("nvarchar", 32, None),
    "table_source": ("nvarchar", 128, None),
    "fichier_source": ("nvarchar", 260, None),
    "feuille_source": ("nvarchar", 128, None),
    "num_ligne_source": ("int", None, 0),
    "valeur": ("nvarchar", 4000, None),
    "decision_metier": ("nvarchar", 50, None),
    "id_chargement": ("int", None, 0),
}


def test_convertir_lignes():
    lignes = lignes_qualite(sorties_exemple(), sensibles={})["anomalie"]
    noms, valeurs, problemes = convertir_lignes(
        "anomalie", lignes, COLONNES_ANOMALIE_TEST, {("clients.csv", None): 7},
        {"id_execution": 3},
    )
    assert problemes == []
    assert noms == [
        "id_execution", "etat", "id_anomalie", "table_source", "fichier_source",
        "feuille_source", "num_ligne_source", "valeur", "decision_metier", "id_chargement",
    ]
    assert valeurs[0] == [3, "brut", "x1", "clients", "clients.csv", "", 2, "masqué", None, 7]
    assert valeurs[1][-2:] == ["garder", 7]
    assert valeurs[2][-1] is None
    assert valeurs[2][6] is None


def test_convertir_lignes_refus_sans_valeur():
    lignes = lignes_qualite(sorties_exemple(), sensibles={})["anomalie"]
    lignes[0]["valeur"] = "secret " * 1000
    noms, valeurs, problemes = convertir_lignes(
        "anomalie", lignes, COLONNES_ANOMALIE_TEST, {}, {"id_execution": 3}
    )
    assert "qualite.anomalie.valeur" in problemes[0] and "1 valeur(s) de plus de 4000" in problemes[0]
    assert "2 ligne(s) dont le fichier source n'est pas dans le journal" in problemes[1]
    assert all("secret" not in p for p in problemes)
    inconnues = convertir_lignes("anomalie", [{"autre": 1}], COLONNES_ANOMALIE_TEST, {}, {})[2]
    assert inconnues == ["qualite.anomalie : colonnes inconnues en base autre"]
    assert convertir_lignes("anomalie", [], COLONNES_ANOMALIE_TEST, {}, {}) == ([], [], [])


def test_problemes_sorties_colonnes():
    problemes = problemes_sorties(sorties_exemple(), "2026-03", sensibles={}, declarations={})
    assert any(p.startswith("anomalies, état brut : ") for p in problemes)
    assert any(p.startswith("anomalies, état nettoyé : ") for p in problemes)
    assert any(p.startswith("journal du nettoyage : colonnes attendues") for p in problemes)
    assert any(p.startswith("bilan du nettoyage : colonnes attendues") for p in problemes)


# --- Vérification de bout en bout (7.2e) --------------------------------------------


def test_cellules_illisibles_avec_leur_lignage(jeu):
    jeu.nettoyees["interventions"] = jeu.tables["interventions"].copy()
    preparation = preparer(jeu.perimetre, jeu.tables, jeu.nettoyees, jeu.structure)
    assert list(preparation.cellules_illisibles.columns) == list(COLONNES_CELLULES_ILLISIBLES)
    assert preparation.cellules_illisibles.to_dict("records") == [
        {"table": "interventions", "colonne": "duree_min",
         "fichier_source": "interventions_2025.csv", "feuille_source": None,
         "num_ligne_source": 3}
    ]


def test_attendus_table(jeu):
    jeu.nettoyees["interventions"] = jeu.tables["interventions"].copy()
    jeu.structure = construire_structure(
        {
            "interventions": {"id_intervention": regles(), "duree_min": regles("entier (texte)")},
            "factures_entetes": {"num_facture": regles(), "total_ht": regles("nombre natif")},
            "factures_lignes": {"num_facture": regles()},
        },
        {"factures_entetes": frozenset({"total_ht"})},
    )
    preparation = preparer(jeu.perimetre, jeu.tables, jeu.nettoyees, jeu.structure)
    tables = {(p.schema, p.table.source): p for p in preparation.tables}
    assert attendus_table(tables[("propre", "interventions")]) == [
        ("propre.interventions : lignes", "COUNT(*)", 2, False),
        ("propre.interventions.id_intervention : cellules renseignées", "COUNT(id_intervention)", 2, False),
        ("propre.interventions.duree_min : cellules renseignées", "COUNT(duree_min)", 1, False),
        ("propre.interventions.duree_min : somme", "SUM(duree_min)", Decimal(45), False),
    ]
    assert attendus_table(tables[("propre", "factures_entetes")])[-1] == (
        "propre.factures_entetes.total_ht : somme", "SUM(total_ht)", Decimal("100.5"), True
    )
    assert [a[1] for a in attendus_table(tables[("chargement", "interventions")])] == [
        "COUNT(*)", "COUNT(id_intervention)", "COUNT(duree_min)",
    ]
    assert attendus_table(tables[("propre", "factures_lignes")]) == [
        ("propre.factures_lignes : lignes", "COUNT(*)", 0, False),
        ("propre.factures_lignes.num_facture : cellules renseignées", "COUNT(num_facture)", 0, False),
    ]


@pytest.mark.parametrize(
    "valeur, attendu",
    [
        (None, None),
        (Decimal("12.50000000"), Decimal("12.5")),
        (45, Decimal(45)),
        (dt.date(2025, 3, 14), "2025-03-14"),
        (dt.time(8, 30), "08:30:00"),
        ("texte", "texte"),
    ],
)
def test_valeur_lue(valeur, attendu):
    assert valeur_lue(valeur) == attendu


def test_conformite():
    assert conformite(3, Decimal(3))
    assert conformite(Decimal("12.5"), Decimal("12.50000000"))
    assert conformite(None, None)
    assert conformite("2025-03-14", "2025-03-14")
    assert not conformite(Decimal("12.5"), Decimal("12.4"))
    assert not conformite(2, Decimal(3))
