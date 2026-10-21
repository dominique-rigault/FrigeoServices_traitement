"""Tests de l'inventaire des fichiers sur un mini jeu de fichiers fictifs."""

import copy

import openpyxl
import pandas as pd
import pytest

from frigeo.chargement import bilan_chargement, charger_tout
from frigeo.controles import CONSTAT_DECODAGE, CONSTAT_REMPLACEMENT
from frigeo.inventaire import (
    COLONNES_ENCODAGE,
    MECANISME_DOUBLE,
    MECANISME_EXCEL,
    MECANISME_PERDU,
    comparer_lignes,
    encodage_suspect,
    entetes_par_source,
    sonder_fichiers,
    sonder_texte,
    texte_export_encodage,
)
from frigeo.perimetre import decouvrir, verifier_configuration

CONFIG = {
    "periodes": {"annuelle": "2025", "premier_mois": "2026-01"},
    "flux": {
        "interventions": {
            "emplacement": "raw",
            "motif": "interventions_{p}.csv",
            "format": "texte",
            "encodage": "utf-8",
            "separateur": ";",
            "ligne_entete": 1,
            "tables": ["interventions"],
        },
        "journal": {
            "emplacement": "raw",
            "motif": "journal_{p}.txt",
            "format": "texte",
            "encodage": "iso-8859-15",
            "separateur": "\t",
            "ligne_entete": 2,
            "tables": ["journal"],
        },
        "factures": {
            "emplacement": "raw",
            "motif": "factures_{p}.xlsx",
            "format": "excel",
            "ligne_entete": 1,
            "tables": {"factures_entetes": {"feuille": "Entetes"}},
        },
        "clients": {
            "emplacement": "referentiels",
            "fichier": "clients.csv",
            "format": "texte",
            "encodage": "cp1252",
            "separateur": ";",
            "ligne_entete": 1,
            "tables": ["clients"],
        },
    },
}

# « CafÃ© » écrit en UTF-8 : texte déjà mal décodé dans la source.
INTERVENTIONS_2025 = "id;client\nA1;Café\nA2;CafÃ©\nA3;Bar;extra\n"
INTERVENTIONS_2026_01 = "id;client;duree\nB1;Brasserie;60\n"
# Première ligne de titre, en-tête en ligne 2.
JOURNAL = "Extraction du journal\nnum\tlibelle\nJ1\tachat\nJ2\tvente\n"


def ecrire_excel(chemin, feuilles):
    classeur = openpyxl.Workbook()
    classeur.remove(classeur.active)
    for nom, rangees in feuilles.items():
        feuille = classeur.create_sheet(nom)
        for rangee in rangees:
            feuille.append(rangee)
    classeur.save(chemin)


@pytest.fixture
def config():
    verifier_configuration(CONFIG)
    return copy.deepcopy(CONFIG)


@pytest.fixture
def data_dir(tmp_path):
    racine = tmp_path / "data"
    raw = racine / "raw"
    (raw / "2026").mkdir(parents=True)
    (racine / "referentiels").mkdir()
    (raw / "interventions_2025.csv").write_bytes(INTERVENTIONS_2025.encode("utf-8"))
    (raw / "2026" / "interventions_2026-01.csv").write_bytes(
        INTERVENTIONS_2026_01.encode("utf-8")
    )
    for periode in ("2025", "2026-01"):
        (raw / f"journal_{periode}.txt").write_bytes(JOURNAL.encode("iso-8859-15"))
    # Octets UTF-8 de « é » dans un fichier déclaré cp1252.
    (racine / "referentiels" / "clients.csv").write_bytes(
        "code;nom\nC1;Café\n".encode("cp1252") + "C2;Café\n".encode()
    )
    ecrire_excel(
        raw / "factures_2025.xlsx",
        {
            "Entetes": [["num", "client"], ["FA1", "CafÃ©"], ["FA2", "Bar�"]],
            "Notes": [["libre"], ["x"], ["y"], ["z"]],
        },
    )
    ecrire_excel(
        raw / "factures_2026-01.xlsx",
        {"Entetes": [["num", "client"], ["FA3", "Bar"]]},
    )
    return racine


@pytest.fixture
def perimetre(data_dir, config):
    p = decouvrir(data_dir, "2026-01", config)
    p.verifier()
    return p


@pytest.fixture
def inventaire(perimetre):
    return sonder_fichiers(perimetre)


def test_sondage_texte_lit_le_format_de_la_configuration(inventaire):
    texte = inventaire.texte.set_index("fichier")
    assert set(texte["flux"]) == {"interventions", "journal", "clients"}
    journal = texte.loc["raw/journal_2025.txt"]
    assert journal["separateur"] == "\t"
    assert journal["colonnes_entete"] == 2
    assert journal["enregistrements"] == 2
    interventions = texte.loc["raw/interventions_2025.csv"]
    assert interventions["enregistrements"] == 3
    assert interventions["longueurs"] == {2: 2, 3: 1}


def test_echec_de_decodage_signale_sans_arreter(tmp_path):
    chemin = tmp_path / "f.csv"
    chemin.write_bytes(b"a;b\n\xff;1\n")
    mesures, entete = sonder_texte(chemin, "utf-8", ";")
    assert mesures["decodage"].startswith("échec à l'octet")
    assert entete is None
    assert mesures["enregistrements"] is None


def test_marque_utf8_et_fins_de_ligne(tmp_path):
    chemin = tmp_path / "f.csv"
    chemin.write_bytes(b"\xef\xbb\xbfa;b\r\n1;2\r\n3;4\n")
    mesures, _ = sonder_texte(chemin, "utf-8", ";")
    assert mesures["bom_utf8"] is True
    assert (mesures["crlf"], mesures["lf_seul"]) == (2, 1)


def test_sondage_excel_signale_les_feuilles_non_declarees(inventaire):
    excel = inventaire.excel.set_index(["fichier", "feuille"])
    assert bool(excel.loc[("raw/factures_2025.xlsx", "Entetes"), "declaree"])
    assert not bool(excel.loc[("raw/factures_2025.xlsx", "Notes"), "declaree"])
    assert excel.loc[("raw/factures_2025.xlsx", "Entetes"), "lignes_donnees"] == 2


def test_entetes_divergents(inventaire):
    entetes = entetes_par_source(inventaire)
    interventions = entetes[entetes["flux"] == "interventions"]
    assert len(interventions) == 2
    assert interventions["divergent"].all()
    assert set(interventions["colonnes"]) == {"id|client", "id|client|duree"}
    autres = entetes[entetes["flux"] != "interventions"]
    assert not autres["divergent"].any()
    # La feuille non déclarée n'entre pas dans la comparaison des en-têtes.
    assert set(entetes.loc[entetes["flux"] == "factures", "feuille"]) == {"Entetes"}


def test_comparaison_sans_ecart(perimetre, inventaire):
    bilan = bilan_chargement(charger_tout(perimetre))
    comparaison = comparer_lignes(bilan, inventaire)
    assert comparaison["attendu"].notna().all()
    assert (comparaison["ecart"] == 0).all()


def test_comparaison_signale_des_lignes_perdues(perimetre, inventaire):
    bilan = bilan_chargement(charger_tout(perimetre))
    ligne = bilan["fichier_source"] == "journal_2025.txt"
    bilan.loc[ligne, "lignes_chargees"] -= 1
    comparaison = comparer_lignes(bilan, inventaire)
    assert comparaison.loc[comparaison["ecart"] != 0, "fichier_source"].tolist() == [
        "journal_2025.txt"
    ]


def test_encodage_suspect_decompte_sans_valeurs(perimetre):
    tables = charger_tout(perimetre)
    suspects = encodage_suspect(tables, perimetre.config)
    assert list(suspects.columns) == COLONNES_ENCODAGE
    par_cle = suspects.set_index(["table", "colonne", "constat"])

    interventions = par_cle.loc[("interventions", "client", CONSTAT_DECODAGE)]
    assert interventions["mecanisme"] == MECANISME_DOUBLE
    assert interventions["cellules"] == 1
    assert interventions["reparables"] == 1
    assert interventions["reparees_presentes_ailleurs"] == 1

    clients = par_cle.loc[("clients", "nom", CONSTAT_DECODAGE)]
    assert clients["mecanisme"] == "octets UTF-8 dans un fichier déclaré cp1252"

    facture = par_cle.loc[("factures_entetes", "client", CONSTAT_DECODAGE)]
    assert facture["mecanisme"] == MECANISME_EXCEL
    perdu = par_cle.loc[("factures_entetes", "client", CONSTAT_REMPLACEMENT)]
    assert perdu["mecanisme"] == MECANISME_PERDU
    assert perdu["reparables"] == 0

    # Aucune valeur des données dans le résultat ni dans l'export.
    texte = texte_export_encodage(suspects, "2026-01")
    cellules = " ".join(suspects.astype(str).to_numpy().ravel())
    for valeur in ("Caf", "Bar", "FA1", "C2"):
        assert valeur not in texte
        assert valeur not in cellules


def test_lignage_ignore(perimetre):
    tables = charger_tout(perimetre)
    tables["interventions"]["champs_excedentaires"] = "CafÃ©"
    suspects = encodage_suspect(tables, perimetre.config)
    assert "champs_excedentaires" not in set(suspects["colonne"])


def test_export_refuse_une_colonne_inattendue():
    suspects = pd.DataFrame(columns=COLONNES_ENCODAGE + ["valeur"])
    with pytest.raises(ValueError, match="valeur"):
        texte_export_encodage(suspects, "2026-01")


def test_export_vide():
    vide = pd.DataFrame(columns=COLONNES_ENCODAGE)
    assert "Aucune cellule suspecte" in texte_export_encodage(vide, "2026-01")
