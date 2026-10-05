"""Tests de la classification des colonnes sensibles et du masquage."""

import pandas as pd
import pytest

from frigeo.chargement import liste_tables
from frigeo.confidentialite import (
    charger_sensibilite,
    est_sensible,
    masquer_mesures,
    verifier_sensibilite,
)
from frigeo.perimetre import charger_configuration
from frigeo.profilage import detail_signatures, profiler_table, profiler_tout

SENSIBLES = {"t": frozenset({"salaire"})}


def donnees():
    return pd.DataFrame(
        {
            "fichier_source": ["a.csv", "a.csv"],
            "num_ligne_source": [2, 3],
            "periode_export": ["2025", "2025"],
            "salaire": ["2460", "2500"],
            "age": ["30", "40"],
        },
        dtype=object,
    )


def test_classification_reelle_coherente_avec_les_sources():
    sensibles = charger_sensibilite()
    tables = set(liste_tables(charger_configuration()))
    assert sensibles
    assert set(sensibles) <= tables


def test_lecture_de_la_classification(tmp_path):
    chemin = tmp_path / "sensibilite.yaml"
    chemin.write_text(
        "colonnes_sensibles:\n  clients: [nom, siret]\n  fec: [CompAuxLib]\n",
        encoding="utf-8",
    )
    assert charger_sensibilite(chemin) == {
        "clients": frozenset({"nom", "siret"}),
        "fec": frozenset({"CompAuxLib"}),
    }


def test_classification_introuvable(tmp_path):
    with pytest.raises(RuntimeError, match="introuvable"):
        charger_sensibilite(tmp_path / "absent.yaml")


def test_classification_sans_la_cle_attendue(tmp_path):
    chemin = tmp_path / "sensibilite.yaml"
    chemin.write_text("autre: 1\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="colonnes_sensibles"):
        charger_sensibilite(chemin)


def test_classification_avec_colonnes_qui_ne_sont_pas_une_liste(tmp_path):
    chemin = tmp_path / "sensibilite.yaml"
    chemin.write_text("colonnes_sensibles:\n  t: nom\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="liste de textes"):
        charger_sensibilite(chemin)


def test_est_sensible():
    assert est_sensible(SENSIBLES, "t", "salaire")
    assert not est_sensible(SENSIBLES, "t", "age")
    assert not est_sensible(SENSIBLES, "autre", "salaire")


def test_masquer_mesures_conserve_le_reste():
    profil = {"nb_lignes": 3, "min": "1", "max": "2", "nb_distincts": 2}
    masque = masquer_mesures(profil)
    assert masque["min"] is None and masque["max"] is None
    assert masque["nb_lignes"] == 3 and masque["nb_distincts"] == 2
    assert profil["min"] == "1"


def test_masquer_mesures_sans_bornes():
    profil = {"nb_lignes": 2, "nature_dominante": "aucune valeur"}
    assert masquer_mesures(profil) == profil


def test_verifier_sensibilite_signale_colonne_et_table_inconnues():
    sensibles = {
        "t": frozenset({"salaire", "absente"}),
        "inconnue": frozenset({"x"}),
    }
    problemes = verifier_sensibilite({"t": donnees()}, sensibles)
    assert len(problemes) == 2
    assert any("t.absente" in p for p in problemes)
    assert any("Table inconnue" in p for p in problemes)


def test_profil_masque_la_colonne_sensible_seulement():
    profil = profiler_table(donnees(), "t", masquer_exemples=True, sensibles=SENSIBLES)
    assert profil["colonne"].tolist() == ["salaire", "age"]
    assert profil["masquee"].tolist() == [True, False]
    assert pd.isna(profil.loc[0, "min"]) and pd.isna(profil.loc[0, "max"])
    assert profil.loc[1, "min"] == "30" and profil.loc[1, "max"] == "40"
    assert profil.loc[0, "nb_distincts"] == 2
    assert profil.loc[0, "nature_dominante"] == "entier (texte)"


def test_profil_sans_masquage_garde_les_bornes():
    profil = profiler_table(donnees(), "t")
    assert "masquee" not in profil.columns
    assert profil.loc[0, "min"] == "2460"
    assert profil.loc[0, "max"] == "2500"


def test_profil_complet_arrete_sur_classification_incoherente():
    with pytest.raises(RuntimeError, match="incohérente"):
        profiler_tout(
            {"t": donnees()},
            masquer_exemples=True,
            sensibles={"t": frozenset({"salare"})},
        )


def test_profil_complet_masque():
    profil = profiler_tout({"t": donnees()}, masquer_exemples=True, sensibles=SENSIBLES)
    assert int(profil["masquee"].sum()) == 1


def test_detail_signatures_sans_valeur_exemple_si_sensible():
    d = detail_signatures(
        donnees(), "salaire", masquer_exemples=True, sensibles=SENSIBLES, nom_table="t"
    )
    assert "valeur_exemple" not in d.columns
    assert d.loc[0, "fichier_source_exemple"] == "a.csv"
    assert d.loc[0, "num_ligne_source_exemple"] == 2
    autre = detail_signatures(
        donnees(), "age", masquer_exemples=True, sensibles=SENSIBLES, nom_table="t"
    )
    assert autre.loc[0, "valeur_exemple"] == "30"


def test_detail_signatures_exige_le_nom_de_table_avec_masquage():
    with pytest.raises(ValueError, match="nom_table"):
        detail_signatures(donnees(), "salaire", masquer_exemples=True, sensibles=SENSIBLES)