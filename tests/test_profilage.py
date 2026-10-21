"""Tests du profilage sur des colonnes fictives aux défauts connus."""

import pandas as pd
import pytest

from frigeo.profilage import (
    FORME_MASQUEE,
    POINT_CONSTANTE,
    POINT_ESPACES,
    POINT_EXPORT,
    POINT_FORME,
    POINT_FORME_ELARGIE,
    POINT_HORS_NATURE,
    POINT_TOUJOURS_VIDE,
    POINT_TYPES,
    POINT_VIDES,
    detail_signatures,
    formes_non_reconnues,
    points_a_regarder,
    profiler_colonne,
    profiler_table,
    profiler_tout,
    signature,
    synthese_par_table,
    texte_export_profil,
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

def tables_fictives():
    """Deux tables aux défauts connus, sur deux exports pour la première."""
    mesures = pd.DataFrame(
        {
            "fichier_source": ["m_2025.csv"] * 3 + ["m_2026-01.csv"] * 2,
            "num_ligne_source": [2, 3, 4, 2, 3],
            "periode_export": ["2025"] * 3 + ["2026-01"] * 2,
            "jour": ["14/03/2025", "15/03/2025", "2025-03-16", "20260105", "20260106"],
            "heure": ["08:15:00", "09:30:00", "10:00:00", "11:00:00", ""],
            "montant": [12.5, "13,20", 14.0, 15.0, 16.0],
            "libelle": [" Alpha", "Beta", "Gamma", "Delta", "Epsilon"],
            "vide": [None, "", None, None, None],
            "statut": ["OK", "OK", "OK", "OK", "OK"],
        },
        dtype=object,
    )
    personnes = pd.DataFrame(
        {
            "fichier_source": ["p.csv"] * 2,
            "num_ligne_source": [2, 3],
            "periode_export": [None, None],
            "nom": ["Durand", "Martin"],
            "telephone": ["01 23 45 67 89", "09 87 65 43 21"],
        },
        dtype=object,
    )
    return {"mesures": mesures, "personnes": personnes}


SENSIBLES = {"personnes": frozenset({"nom", "telephone"})}


def test_synthese_par_table():
    profil = profiler_tout(tables_fictives())
    synthese = synthese_par_table(profil).set_index("table")
    assert synthese.loc["mesures", "lignes"] == 5
    assert synthese.loc["mesures", "colonnes"] == 6
    assert synthese.loc["mesures", "colonnes_toujours_vides"] == 1
    assert synthese.loc["mesures", "colonnes_espaces_bord"] == 1
    assert synthese.loc["personnes", "colonnes"] == 2


def test_formes_non_reconnues_ignore_les_natures_connues():
    formes = formes_non_reconnues(tables_fictives()).set_index(["table", "colonne"])
    assert formes.loc[("mesures", "heure"), "formes"] == ["99:99:99"]
    assert formes.loc[("mesures", "heure"), "cellules"] == 4
    assert not formes.loc[("mesures", "heure"), "lue_par_nettoyage"]
    assert formes.loc[("personnes", "telephone"), "formes"] == ["99 99 99 99 99"]
    # Dates, décimal à virgule et texte ne sont pas signalés.
    assert ("mesures", "jour") not in formes.index
    assert ("mesures", "montant") not in formes.index
    assert ("personnes", "nom") not in formes.index


def test_points_a_regarder():
    tables = tables_fictives()
    profil = profiler_tout(tables)
    par_export = profiler_tout(tables, par="periode_export")
    points = points_a_regarder(profil, tables=tables, profil_par_export=par_export)
    vus = set(zip(points["table"], points["colonne"], points["point"]))
    assert ("mesures", "heure", POINT_FORME) in vus
    assert ("mesures", "jour", POINT_EXPORT) in vus
    assert ("mesures", "jour", POINT_HORS_NATURE) in vus
    assert ("mesures", "montant", POINT_TYPES) in vus
    assert ("mesures", "vide", POINT_TOUJOURS_VIDE) in vus
    assert ("mesures", "libelle", POINT_ESPACES) in vus
    assert ("mesures", "statut", POINT_CONSTANTE) in vus
    assert POINT_VIDES not in set(points["point"])
    detail = points.set_index(["colonne", "point"]).loc[("jour", POINT_EXPORT), "detail"]
    assert detail == "2025\u00a0: date JJ/MM/AAAA; 2026-01\u00a0: date AAAAMMJJ"
    # Les formes non reconnues viennent en tête.
    assert points.loc[0, "point"] == POINT_FORME


def test_vides_sous_plusieurs_formes():
    donnees = pd.DataFrame({"x": ["a", "", None, "  "]}, dtype=object)
    points = points_a_regarder(profiler_table(donnees, "t"))
    ligne = points[points["point"] == POINT_VIDES].iloc[0]
    assert ligne["cellules"] == 3
    assert ligne["detail"] == "absente, chaîne vide, espaces seuls"


def test_export_sans_valeurs_et_formes_sensibles_masquees():
    tables = tables_fictives()
    profil = profiler_tout(tables, masquer_exemples=True, sensibles=SENSIBLES)
    points = points_a_regarder(profil, tables=tables)
    texte = texte_export_profil(profil, points, "2026-01")
    for valeur in ("Durand", "Martin", "Alpha", "13,20", "14/03/2025", "01 23"):
        assert valeur not in texte
    assert "99 99 99 99 99" not in texte
    assert FORME_MASQUEE in texte
    # Les formes d'une colonne non sensible sont transmises.
    assert "99:99:99" in texte


def test_export_refuse_un_profil_non_masque():
    profil = profiler_tout(tables_fictives())
    with pytest.raises(ValueError, match="masquer_exemples"):
        texte_export_profil(profil, points_a_regarder(profil), "2026-01")


def test_export_refuse_une_colonne_de_points_inattendue():
    profil = profiler_tout(tables_fictives(), masquer_exemples=True, sensibles=SENSIBLES)
    points = points_a_regarder(profil).assign(valeur="x")
    with pytest.raises(ValueError, match="valeur"):
        texte_export_profil(profil, points, "2026-01")


def test_formes_elargies_lues_par_le_nettoyage():
    donnees = pd.DataFrame(
        {
            "jour": ["14/03/2025", "14.03.2025", "14-03-25", "03/14/2025 08:00"],
            "montant": ["12,50", "1 234,50", "12,50 €", "1.234.567"],
        },
        dtype=object,
    )
    formes = formes_non_reconnues({"t": donnees})
    lues = formes[formes["lue_par_nettoyage"]].set_index("colonne")
    assert lues.loc["jour", "formes"] == ["99.99.9999", "99-99-99"]
    assert lues.loc["montant", "formes"] == ["9 999,99", "99,99 €"]
    autres = formes[~formes["lue_par_nettoyage"]].set_index("colonne")
    assert autres.loc["jour", "formes"] == ["99/99/9999 99:99"]
    assert autres.loc["montant", "formes"] == ["9.999.999"]
    points = points_a_regarder(profiler_table(donnees, "t"), tables={"t": donnees})
    assert set(points.loc[points["colonne"] == "jour", "point"]) >= {
        POINT_FORME,
        POINT_FORME_ELARGIE,
    }


def test_entiers_et_decimaux_natifs_ne_sont_pas_plusieurs_types():
    donnees = pd.DataFrame({"x": [1, 2.5, 3], "y": [1, 2.5, "3,5"]}, dtype=object)
    points = points_a_regarder(profiler_table(donnees, "t"))
    types = points[points["point"] == POINT_TYPES].set_index("colonne")
    assert "x" not in types.index
    assert types.loc["y", "cellules"] == 1


def test_export_ecrit_les_decomptes_en_entiers():
    tables = tables_fictives()
    profil = profiler_tout(tables, masquer_exemples=True, sensibles=SENSIBLES)
    texte = texte_export_profil(profil, points_a_regarder(profil), "2026-01")
    assert "mesures | statut | texte |  | 0 | 1 | 1 | AA (5)" in texte
