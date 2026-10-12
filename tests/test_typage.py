"""Tests de la lecture typée (frigeo.typage)."""

import datetime as dt

import pandas as pd
import pytest

from frigeo.typage import ETAT_ILLISIBLE, ETAT_LUE, ETAT_VIDE, ecrire_date, lire


def _serie(valeurs, index=None):
    return pd.Series(valeurs, index=index, dtype=object)


def test_dates_en_texte_vides_et_illisibles():
    serie = _serie(["14/03/2025", "", "  ", None, "2025-03-14", "31/02/2025", "01/12/2026"])
    lecture = lire(serie, "date JJ/MM/AAAA")
    assert list(lecture.etats) == [
        ETAT_LUE,
        ETAT_VIDE,
        ETAT_VIDE,
        ETAT_VIDE,
        ETAT_ILLISIBLE,
        ETAT_ILLISIBLE,
        ETAT_LUE,
    ]
    assert lecture.valeurs.iloc[0] == pd.Timestamp(2025, 3, 14)
    assert lecture.valeurs.iloc[6] == pd.Timestamp(2026, 12, 1)
    assert lecture.valeurs.iloc[1:6].isna().all()
    assert str(lecture.valeurs.dtype) == "datetime64[ns]"


def test_date_compacte_et_date_iso():
    assert lire(_serie(["20250321", "2025032"]), "date AAAAMMJJ").valeurs.iloc[0] == (
        pd.Timestamp(2025, 3, 21)
    )
    lecture = lire(_serie(["2025-03-21", "21/03/2025"]), "date AAAA-MM-JJ")
    assert list(lecture.etats) == [ETAT_LUE, ETAT_ILLISIBLE]


def test_date_native_sans_lecture_tolerante_du_texte():
    serie = _serie([dt.datetime(2025, 3, 14), dt.date(2025, 3, 15), "16/03/2025", 45000])
    lecture = lire(serie, "date native")
    assert list(lecture.etats) == [ETAT_LUE, ETAT_LUE, ETAT_ILLISIBLE, ETAT_ILLISIBLE]
    assert list(lecture.valeurs.iloc[:2]) == [pd.Timestamp(2025, 3, 14), pd.Timestamp(2025, 3, 15)]


def test_heure_lue_comme_duree_depuis_minuit():
    lecture = lire(_serie(["08:45", "8:45", "25:00"]), "heure HH:MM")
    assert list(lecture.etats) == [ETAT_LUE, ETAT_ILLISIBLE, ETAT_ILLISIBLE]
    assert lecture.valeurs.iloc[0] == pd.Timedelta(hours=8, minutes=45)


def test_nombres_selon_leur_nature():
    lecture = lire(_serie(["18,4", "18.4", 18.4, "-2,50"]), "décimal virgule (texte)")
    assert list(lecture.etats) == [ETAT_LUE, ETAT_ILLISIBLE, ETAT_ILLISIBLE, ETAT_LUE]
    assert list(lecture.valeurs.dropna()) == [18.4, -2.5]
    lecture = lire(_serie([46.8, "46.80", 3, True]), "nombre natif")
    assert list(lecture.etats) == [ETAT_LUE, ETAT_ILLISIBLE, ETAT_LUE, ETAT_ILLISIBLE]
    lecture = lire(_serie(["95", "9,5"]), "entier (texte)")
    assert list(lecture.etats) == [ETAT_LUE, ETAT_ILLISIBLE]
    assert lecture.valeurs.iloc[0] == 95.0


def test_index_conserve_et_serie_intacte():
    serie = _serie(["14/03/2025", "x"], index=[10, 7])
    copie = serie.copy()
    lecture = lire(serie, "date JJ/MM/AAAA")
    assert list(lecture.valeurs.index) == [10, 7]
    assert list(lecture.etats.index) == [10, 7]
    assert lecture.etats.loc[7] == ETAT_ILLISIBLE
    pd.testing.assert_series_equal(serie, copie)


def test_colonne_vide():
    lecture = lire(_serie([None, ""]), "date JJ/MM/AAAA")
    assert list(lecture.etats) == [ETAT_VIDE, ETAT_VIDE]
    assert lecture.valeurs.isna().all()


@pytest.mark.parametrize("nature", ["texte", "à décider", "aucune"])
def test_nature_non_lisible_refusee(nature):
    with pytest.raises(ValueError, match="non lisible"):
        lire(_serie(["a"]), nature)


def test_ecriture_d_une_date_dans_la_forme_de_sa_nature():
    date = pd.Timestamp(2025, 3, 4)
    assert ecrire_date(date, "date JJ/MM/AAAA") == "04/03/2025"
    assert ecrire_date(date, "date AAAAMMJJ") == "20250304"
    assert ecrire_date(date, "date AAAA-MM-JJ") == "2025-03-04"
    assert ecrire_date(date, "date native") == "2025-03-04"
    assert ecrire_date(pd.Timestamp(2025, 3, 4, 10, 30), "date native") == "2025-03-04 10:30:00"
    with pytest.raises(ValueError):
        ecrire_date(date, "heure HH:MM")
