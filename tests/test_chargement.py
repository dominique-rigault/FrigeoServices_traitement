"""Tests du périmètre et du chargement sur un mini jeu de fichiers fictifs."""

import openpyxl
import pytest

from frigeo.chargement import (
    bilan_chargement,
    charger_table,
    charger_tout,
    lire_excel,
    lire_texte,
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
        "factures": {
            "emplacement": "raw",
            "motif": "factures_{p}.xlsx",
            "format": "excel",
            "ligne_entete": 1,
            "tables": {
                "factures_entetes": {"feuille": "Entetes"},
                "factures_lignes": {"feuille": "Lignes"},
            },
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

INTERVENTIONS_2025 = (
    "id;client;duree\n"
    "A1;Café;95\n"
    "A2;Bar;1h10\n"
    "A3;Z;10;extra\n"
    'A4;"multi\nligne";5\n'
    "A5;;7\n"
)
INTERVENTIONS_2026_01 = "id;client;duree\nB1;Brasserie;60\n"
CLIENTS = "code;nom\nC1;Café\nC2;CafÃ©\n"


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
    return CONFIG


@pytest.fixture
def data_dir(tmp_path):
    racine = tmp_path / "data"
    (racine / "raw").mkdir(parents=True)
    (racine / "referentiels").mkdir()
    raw = racine / "raw"
    (raw / "interventions_2025.csv").write_bytes(INTERVENTIONS_2025.encode("utf-8"))
    (raw / "interventions_2026-01.csv").write_bytes(INTERVENTIONS_2026_01.encode("utf-8"))
    (racine / "referentiels" / "clients.csv").write_bytes(CLIENTS.encode("cp1252"))
    ecrire_excel(
        raw / "factures_2025.xlsx",
        {
            "Entetes": [["num_facture", "total_ht"], ["FA1", 46.8], ["FA2", "46.80"]],
            "Lignes": [["num_facture", "num_ligne"], ["FA1", 1], ["FA2", 1]],
        },
    )
    ecrire_excel(
        raw / "factures_2026-01.xlsx",
        {
            "Entetes": [["num_facture", "total_ht"], ["FA3", None]],
            "Lignes": [["num_facture", "num_ligne"], ["FA3", 1]],
        },
    )
    return racine


@pytest.fixture
def perimetre(data_dir, config):
    return decouvrir(data_dir, "2026-01", config)


def test_perimetre_complet(perimetre):
    perimetre.verifier()
    assert not perimetre.manquants
    assert len(perimetre.fichiers) == 5


def test_fichier_manquant_arrete_le_traitement(data_dir, config):
    (data_dir / "raw" / "factures_2026-01.xlsx").unlink()
    p = decouvrir(data_dir, "2026-01", config)
    with pytest.raises(RuntimeError, match="factures_2026-01.xlsx"):
        p.verifier()


def test_fichier_en_double_arrete_le_traitement(data_dir, config):
    (data_dir / "raw" / "copie").mkdir()
    (data_dir / "raw" / "copie" / "interventions_2026-01.csv").write_bytes(
        INTERVENTIONS_2026_01.encode("utf-8")
    )
    p = decouvrir(data_dir, "2026-01", config)
    with pytest.raises(RuntimeError, match="plusieurs endroits"):
        p.verifier()


def test_fichiers_hors_perimetre_listes(data_dir, config):
    (data_dir / "raw" / "notes.txt").write_text("hors périmètre", encoding="utf-8")
    p = decouvrir(data_dir, "2026-01", config)
    assert [c.name for c in p.ignores] == ["notes.txt"]


def test_effectifs_par_table(perimetre):
    tables = charger_tout(perimetre)
    assert set(tables) == {"interventions", "factures_entetes", "factures_lignes", "clients"}
    assert len(tables["interventions"]) == 6
    assert len(tables["factures_entetes"]) == 3
    assert len(tables["factures_lignes"]) == 3
    assert len(tables["clients"]) == 2


def test_ordre_des_colonnes_et_lignage(perimetre):
    t = charger_table(perimetre, "interventions")
    assert list(t.columns) == [
        "fichier_source",
        "feuille_source",
        "num_ligne_source",
        "periode_export",
        "id",
        "client",
        "duree",
        "nb_champs_source",
        "champs_excedentaires",
        "date_chargement",
    ]
    assert t["periode_export"].tolist() == ["2025"] * 5 + ["2026-01"]
    assert t["fichier_source"].tolist()[0] == "interventions_2025.csv"
    assert t["fichier_source"].tolist()[-1] == "interventions_2026-01.csv"


def test_numeros_de_ligne_physiques(perimetre):
    t = charger_table(perimetre, "interventions")
    # A4 occupe les lignes 5 et 6 du fichier, A5 est donc en ligne 7
    assert t["num_ligne_source"].tolist() == [2, 3, 4, 5, 7, 2]


def test_champs_excedentaires(perimetre):
    t = charger_table(perimetre, "interventions")
    assert t["nb_champs_source"].tolist() == [3, 3, 4, 3, 3, 3]
    assert t["champs_excedentaires"].tolist()[2] == "extra"
    assert t["champs_excedentaires"].isna().sum() == 5


def test_valeurs_texte_brutes(perimetre):
    t = charger_table(perimetre, "interventions")
    assert t["duree"].tolist()[:2] == ["95", "1h10"]
    assert t["client"].tolist()[3] == "multi\nligne"
    assert t["client"].tolist()[4] == ""


def test_encodage_cp1252_et_double_encodage_conserves(perimetre):
    t = charger_table(perimetre, "clients")
    assert t["nom"].tolist() == ["Café", "CafÃ©"]


def test_mauvais_encodage_signale(data_dir, config):
    (data_dir / "raw" / "interventions_2026-01.csv").write_bytes(
        b"id;client;duree\nB1;Caf\xe9;5\n"
    )
    p = decouvrir(data_dir, "2026-01", config)
    with pytest.raises(RuntimeError, match="Encodage inattendu"):
        charger_table(p, "interventions")


def test_types_excel_conserves(perimetre):
    valeurs = charger_table(perimetre, "factures_entetes")["total_ht"].tolist()
    assert isinstance(valeurs[0], float)
    assert valeurs[1] == "46.80" and isinstance(valeurs[1], str)
    assert valeurs[2] is None


def test_feuille_source_renseignee_pour_excel_seulement(perimetre):
    entetes = charger_table(perimetre, "factures_entetes")
    interventions = charger_table(perimetre, "interventions")
    assert set(entetes["feuille_source"]) == {"Entetes"}
    assert interventions["feuille_source"].isna().all()


def test_ligne_entete_texte(tmp_path):
    chemin = tmp_path / "titre.csv"
    chemin.write_bytes("titre\n\nid;client\nA;B\n".encode("utf-8"))
    entete, lignes = lire_texte(chemin, "utf-8", ";", ligne_entete=3)
    assert entete == ["id", "client"]
    assert lignes == [(4, ["A", "B"])]


def test_ligne_entete_excel(tmp_path):
    chemin = tmp_path / "titre.xlsx"
    ecrire_excel(chemin, {"Feuille": [["Titre", None], ["id", "client"], ["A", "B"]]})
    entete, lignes = lire_excel(chemin, "Feuille", ligne_entete=2)
    assert entete == ["id", "client"]
    assert lignes == [(3, ["A", "B"])]


def test_bilan_chargement(perimetre):
    bilan = bilan_chargement(charger_tout(perimetre))
    assert bilan["lignes_chargees"].sum() == 6 + 3 + 3 + 2


def test_table_inconnue(perimetre):
    with pytest.raises(RuntimeError, match="absente de la configuration"):
        charger_table(perimetre, "inconnue")