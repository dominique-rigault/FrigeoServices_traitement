"""Tests de la lecture et de la validation de la configuration des sources."""

import copy

import pytest

from frigeo.chargement import liste_tables
from frigeo.perimetre import (
    charger_configuration,
    noms_attendus,
    periodes,
    verifier_configuration,
)


@pytest.fixture
def config():
    return charger_configuration()


def test_treize_tables_distinctes(config):
    tables = liste_tables(config)
    assert len(tables) == 13
    assert len(set(tables)) == 13


def test_periodes_jusqu_a_mars(config):
    assert periodes("2026-03", config) == ["2025", "2026-01", "2026-02", "2026-03"]


def test_periodes_a_cheval_sur_deux_annees(config):
    resultat = periodes("2027-02", config)
    assert resultat[0] == "2025"
    assert len(resultat) == 15
    assert "2026-12" in resultat
    assert resultat[-1] == "2027-02"


@pytest.mark.parametrize("valeur", ["2026-13", "2026-3", "mars 2026", "2025-12"])
def test_periode_fin_invalide(config, valeur):
    with pytest.raises(ValueError):
        periodes(valeur, config)


def test_noms_attendus_fec_annuel_et_mensuel(config):
    assert noms_attendus(config, "2025")["fec"] == "999000001FEC20251231.txt"
    assert noms_attendus(config, "2026-04")["fec"] == "FEC_extraction_2026-04.txt"


def test_noms_attendus_flux_periodiques_seulement(config):
    noms = noms_attendus(config, "2026-04")
    assert set(noms) == {
        "interventions",
        "pieces_interventions",
        "factures",
        "achats",
        "fec",
    }
    assert noms["interventions"] == "interventions_2026-04.csv"
    assert noms["factures"] == "factures_2026-04.xlsx"


def test_configuration_valide_acceptee(config):
    verifier_configuration(config)


def test_cinq_erreurs_signalees_en_une_fois(config):
    c = copy.deepcopy(config)
    c["periodes"]["premier_mois"] = 2026
    c["flux"]["fec"]["encodage"] = ""
    c["flux"]["clients"]["tables"] = ["interventions"]
    c["flux"]["factures"]["tables"]["factures_lignes"] = {}
    del c["flux"]["achats"]["ligne_entete"]
    with pytest.raises(RuntimeError) as erreur:
        verifier_configuration(c)
    message = str(erreur.value)
    for attendu in (
        "periodes.premier_mois",
        "factures_lignes doit indiquer sa feuille",
        "achats ligne_entete",
        "fec encodage est obligatoire",
        "Table interventions déclarée",
    ):
        assert attendu in message


def test_motif_sans_marqueur_de_periode_refuse(config):
    c = copy.deepcopy(config)
    c["flux"]["interventions"]["motif"] = "interventions.csv"
    with pytest.raises(RuntimeError, match="doit contenir"):
        verifier_configuration(c)


def test_flux_sans_motif_ni_fichier_refuse(config):
    c = copy.deepcopy(config)
    del c["flux"]["clients"]["fichier"]
    with pytest.raises(RuntimeError, match="soit motif, soit fichier"):
        verifier_configuration(c)


def test_configuration_non_dictionnaire_refusee():
    with pytest.raises(RuntimeError):
        verifier_configuration(["pas", "un", "dictionnaire"])