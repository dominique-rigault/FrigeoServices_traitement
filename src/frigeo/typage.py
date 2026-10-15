"""Lecture typée des valeurs chargées (étape 4).

Les données chargées restent telles qu'elles ont été lues dans les fichiers
sources : texte pour les fichiers CSV et le FEC, type de la cellule pour Excel.
Les règles de gestion ont pourtant besoin de comparer des dates, des heures et des
nombres. Ce module lit une colonne selon sa nature en vigueur dans le dictionnaire
(règle `nature`), sans rien modifier : la valeur typée est rendue à côté de la
valeur brute.

La reconnaissance est celle du profilage et du contrôle de nature de l'étape 3
(voir `profilage._interpretations`) : une valeur est lue si elle se conforme à la
nature de sa colonne, sinon elle est illisible. Une valeur illisible a déjà été
signalée par le contrôle de nature : pour une règle de gestion, elle est seulement
non évaluable. Aucune lecture tolérante n'est tentée (une date écrite en texte
dans une colonne de dates natives reste illisible), car ce serait une correction
implicite, que seule l'étape 6 peut apporter par une règle explicite.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .dictionnaire import _valeurs_renseignees
from .profilage import _interpretations

NATURES_DATE = ("date native", "date JJ/MM/AAAA", "date AAAAMMJJ", "date AAAA-MM-JJ")
NATURES_HEURE = ("heure HH:MM",)
NATURES_NOMBRE = (
    "nombre natif",
    "entier (texte)",
    "décimal virgule (texte)",
    "décimal point (texte)",
)
NATURES_LISIBLES = (*NATURES_DATE, *NATURES_HEURE, *NATURES_NOMBRE)

# État de chaque cellule après la lecture.
ETAT_LUE = "lue"
ETAT_VIDE = "vide"
ETAT_ILLISIBLE = "illisible"

# Écriture d'une date dans la forme de sa nature, pour proposer une valeur au
# métier dans la forme qu'il connaît.
_ECRITURE_DATE = {
    "date JJ/MM/AAAA": "%d/%m/%Y",
    "date AAAAMMJJ": "%Y%m%d",
    "date AAAA-MM-JJ": "%Y-%m-%d",
    "date native": "%Y-%m-%d",
}


@dataclass(frozen=True)
class Lecture:
    """Résultat de la lecture d'une colonne, aligné sur son index.

    `valeurs` : dates (datetime64), heures (durée depuis minuit, timedelta64) ou
    nombres (float64), NaT ou NaN pour une cellule vide ou illisible. `etats` :
    « lue », « vide » ou « illisible ».
    """

    valeurs: pd.Series
    etats: pd.Series


def lire(serie: pd.Series, nature: str) -> Lecture:
    """Lit une colonne selon sa nature, sans modifier la série reçue.

    `nature` est la règle `nature` en vigueur dans le dictionnaire, qui doit être
    une date, une heure ou un nombre (`NATURES_LISIBLES`). Une cellule vide (None,
    NaN, chaîne vide ou faite d'espaces) est « vide », une valeur qui ne se conforme
    pas à la nature est « illisible ».
    """
    if nature not in NATURES_LISIBLES:
        raise ValueError(
            f"Nature {nature!r} non lisible : une date, une heure ou un nombre est "
            f"attendu ({', '.join(NATURES_LISIBLES)})"
        )
    index = serie.index
    serie = serie.reset_index(drop=True)
    presentes = _valeurs_renseignees(serie)
    lues = _interpretations(presentes)[nature]

    if nature in NATURES_DATE:
        valeurs = pd.Series(pd.NaT, index=serie.index, dtype="datetime64[ns]")
        if len(lues):
            valeurs.loc[lues.index] = pd.to_datetime(lues).astype("datetime64[ns]")
    elif nature in NATURES_HEURE:
        valeurs = pd.Series(pd.NaT, index=serie.index, dtype="timedelta64[ns]")
        if len(lues):
            instants = pd.to_datetime(lues).astype("datetime64[ns]")
            valeurs.loc[lues.index] = instants - instants.dt.normalize()
    else:
        valeurs = pd.Series(float("nan"), index=serie.index, dtype="float64")
        if len(lues):
            valeurs.loc[lues.index] = pd.to_numeric(lues).astype("float64")

    etats = pd.Series(ETAT_VIDE, index=serie.index, dtype=object)
    etats.loc[presentes.index] = ETAT_ILLISIBLE
    etats.loc[lues.index] = ETAT_LUE
    return Lecture(valeurs.set_axis(index), etats.set_axis(index))


def ecrire_date(valeur, nature: str) -> str:
    """Texte d'une date dans la forme de sa nature (JJ/MM/AAAA, AAAAMMJJ, etc.).

    Une date native est écrite AAAA-MM-JJ, suivie de l'heure si elle n'est pas
    minuit.
    """
    if nature not in _ECRITURE_DATE:
        raise ValueError(f"Nature {nature!r} : une nature de date est attendue")
    instant = pd.Timestamp(valeur)
    if nature == "date native" and instant != instant.normalize():
        return instant.strftime("%Y-%m-%d %H:%M:%S")
    return instant.strftime(_ECRITURE_DATE[nature])
