"""Tests du profilage sur des colonnes fictives aux défauts connus."""

import pandas as pd
import pytest

from frigeo.profilage import (
    detail_signatures,
    profiler_colonne,
    profiler_table,
    signature,
)


def colonne(valeurs):
    return pd.Series(valeurs, dtype=object)


def donnees_fictives():
    return pd.DataFrame(
        {
            "fichier_source": ["a.csv", "a.csv", "b.csv"],
            "num_ligne_source": [2, 3, 2],
            "periode_export": ["2025", "2025", "2026-01"],
            "x": ["1", "2", "3"],
        },
        dtype=object,
    )


def test_trois_formes_de_vide():
    p = profiler_colonne(colonne(["a", "", "  ", None, "b"]))
    assert p["nb_lignes"] == 5
    assert p["nb_none_nan"] == 1
    assert p["nb_chaine_vide"] == 1
    assert p["nb_espaces_seuls"] == 1
    assert p["pct_vide"] == 60.0
    assert p["nb_distincts"] == 2


def test_dates_melangees_et_date_impossible():
    p = profiler_colonne(
        colonne(["14/03/2025", "15/03/2025", "2025-03-14", "31/02/2025"])
    )
    assert p["nature_dominante"] == "date JJ/MM/AAAA"
    assert p["pct_nature"] == 50.0
    assert p["nb_hors_nature"] == 2
    assert p["min"] == "14/03/2025"
    assert p["max"] == "15/03/2025"
    assert p["nb_signatures"] == 2


def test_montant_texte_dans_une_colonne_numerique():
    p = profiler_colonne(colonne([46.8, "46.80", 31.85]))
    assert p["nature_dominante"] == "nombre natif"
    assert p["nb_hors_nature"] == 1
    assert p["min"] == "31.85"
    assert p["max"] == "46.8"
    assert "float (2)" in p["types_python"]
    assert "str (1)" in p["types_python"]


def test_espaces_en_bord_et_encodage_suspect():
    p = profiler_colonne(colonne([" Café", "Café", "CafÃ©"]))
    assert p["nb_espaces_bord"] == 1
    assert p["nb_encodage_suspect"] == 1
    assert p["nature_dominante"] == "texte"


def test_colonne_sans_valeur():
    p = profiler_colonne(colonne(["", None]))
    assert p["nature_dominante"] == "aucune valeur"
    assert p["pct_vide"] == 100.0
    assert "min" not in p


def test_date_compacte_lue_comme_date_avant_entier():
    p = profiler_colonne(colonne(["20250321"]))
    assert p["nature_dominante"] == "date AAAAMMJJ"
    assert p["min"] == "21/03/2025"


@pytest.mark.parametrize(
    "valeur, attendu",
    [
        ("INT-2025-004187", "AAA-9999-999999"),
        ("Évreux", "Aaaaaa"),
        ("46.80", "99.99"),
    ],
)
def test_signature(valeur, attendu):
    assert signature(valeur) == attendu


def test_profil_exclut_les_colonnes_de_lignage():
    profil = profiler_table(donnees_fictives(), "t")
    assert profil["colonne"].tolist() == ["x"]
    assert profil["table"].tolist() == ["t"]
    assert profil.loc[0, "nb_lignes"] == 3


def test_profil_par_exemplaire():
    profil = profiler_table(donnees_fictives(), "t", par="periode_export")
    assert profil["periode_export"].tolist() == ["2025", "2026-01"]
    assert profil["nb_lignes"].tolist() == [2, 1]


def test_detail_signatures_distingue_forme_et_type():
    donnees = pd.DataFrame(
        {
            "fichier_source": ["a.xlsx"] * 4,
            "num_ligne_source": [2, 3, 4, 5],
            "montant": [46.75, "46.80", "46.80", None],
        },
        dtype=object,
    )
    d = detail_signatures(donnees, "montant")
    assert d["signature"].tolist() == ["99.99", "99.99"]
    assert d["type"].tolist() == ["str", "float"]
    assert d["effectif"].tolist() == [2, 1]
    assert d["part_pct"].tolist() == [66.67, 33.33]
    assert d.loc[0, "valeur_exemple"] == "46.80"
    assert d.loc[0, "fichier_source_exemple"] == "a.xlsx"
    assert d.loc[0, "num_ligne_source_exemple"] == 3