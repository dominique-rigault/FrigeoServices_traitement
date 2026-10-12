"""Contrôles des règles de gestion et rapprochements entre sources (étape 4).

Ce module ne contient rien de propre à un client. Il offre un catalogue de types
de règles génériques (`TYPES`, décrit par `catalogue_types`). Les règles d'un
client sont des instances de ces types, écrites à la main dans
`config/gestion.yaml` (voir `charger_regles_gestion`) : référence, libellé, type,
table et paramètres du type. Une règle qui n'entre dans aucun type donne lieu à un
nouveau type générique, testé et réutilisable, jamais à une fonction propre au
client.

Les écarts sont rendus à la maille de la ligne, avec le lignage de la ligne
source. Trois issues sont possibles :

- anomalie : la ligne contredit la règle;
- à arbitrer : la ligne contredit la règle, mais le métier doit dire s'il s'agit
  d'une erreur (et la corriger) ou d'un cas légitime;
- information : un cas que le métier tient pour normal, affiché sans être compté
  comme anomalie.

Chaque type a une issue par défaut; une règle peut en déclarer une autre (clé
`issue`). Une règle peut aussi se limiter aux lignes qui remplissent un filtre
(clé `filtre`) : les autres lignes sont hors champ, non contrôlées, et comptées au
bilan.

Une valeur vide ou illisible dans sa nature (voir `typage.lire`) rend la ligne non
évaluable : elle est comptée au bilan, sans écart, car le contrôle de nature de
l'étape 3 la signale déjà.

Chaque type déclare la vue sur laquelle il travaille : toutes les lignes, pour un
type qui juge chaque ligne seule (une copie est une ligne source avec son propre
lignage), ou les lignes sans les doublons exacts en surnombre, pour un type qui
compare, cumule ou rapproche des lignes (la première ligne de chaque groupe de
doublons exacts est gardée).

Rien n'est corrigé ni écrit : `controler_gestion` rend la table des écarts et un
bilan.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd
import yaml

from . import racine_projet

from .confidentialite import charger_sensibilite, est_sensible, verifier_sensibilite
from .controles import (
    COLONNES_LIGNAGE_ECART,
    ISSUE_A_ARBITRER,
    ISSUE_ANOMALIE,
    VALEUR_MASQUEE,
    _colonnes_de_donnees,
    _valeur_constatee,
)
from .dictionnaire import est_masquee
from .doublons import (
    CONSTAT_EXACT,
    SEPARATEUR,
    _texte,
    charger_declarations_doublons,
    detecter_doublons,
)
from .typage import NATURES_DATE, NATURES_NOMBRE, ecrire_date, lire

ISSUE_INFORMATION = "information"
ISSUES = (ISSUE_ANOMALIE, ISSUE_A_ARBITRER, ISSUE_INFORMATION)

CLE_REGLES_GESTION = "regles"
CLES_FICHIER_GESTION = (CLE_REGLES_GESTION,)
# Clés communes à toutes les instances, en plus des paramètres de leur type.
CLES_COMMUNES = ("ref", "libelle", "type", "table")
# Clés communes facultatives : filtre des lignes contrôlées et issue des écarts.
CLE_FILTRE = "filtre"
CLE_ISSUE = "issue"
CLES_FACULTATIVES = (CLE_FILTRE, CLE_ISSUE)
# Clés d'une condition du filtre.
CLES_CONDITION = ("colonne", "valeurs")

VUE_TOUTES = "toutes les lignes"
VUE_SANS_SURNOMBRE = "sans les doublons exacts en surnombre"

# Genre d'un paramètre, qui dit comment il est vérifié.
GENRE_COLONNE_DATE = "colonne de date"
GENRE_COLONNE_NOMBRE = "colonne de nombre"
GENRE_COLONNE = "colonne"
GENRES_COLONNE = (GENRE_COLONNE_DATE, GENRE_COLONNE_NOMBRE, GENRE_COLONNE)
GENRE_NOMBRE = "nombre"
GENRE_PLAGES = "plages"
# Natures en vigueur admises pour une colonne, selon le genre du paramètre.
_NATURES_ATTENDUES = {
    GENRE_COLONNE_DATE: (NATURES_DATE, "une date est attendue"),
    GENRE_COLONNE_NOMBRE: (NATURES_NOMBRE, "un nombre est attendu"),
}
# Bornes d'une plage, incluses.
CLES_BORNES = ("min", "max")

# Repère de la période d'un export, ajouté par le chargement : AAAA pour un export
# annuel, AAAA-MM pour un export mensuel.
COLONNE_PERIODE = "periode_export"
_MOTIF_ANNEE = re.compile(r"\d{4}")
_MOTIF_MOIS = re.compile(r"(\d{4})-(\d{2})")

COLONNES_ECARTS_GESTION = (
    "table",
    *COLONNES_LIGNAGE_ECART,
    "ref",
    "type",
    "libelle",
    "issue",
    "constat",
    "colonnes",
    "cle",
    "valeur",
    "proposition",
)
COLONNES_BILAN_GESTION = (
    "ref",
    "type",
    "libelle",
    "table",
    "colonnes",
    "vue",
    "filtre",
    "lignes",
    "ecartees_doublons",
    "hors_champ",
    "non_evaluables",
    "controlees",
    "anomalies",
    "a_arbitrer",
    "informations",
)
COLONNES_CATALOGUE = ("type", "description", "parametres", "vue", "issue")


@dataclass(frozen=True)
class Constats:
    """Résultat d'un type sur sa vue, indexé par la position des lignes.

    `evaluables` : vrai pour une ligne que le type a pu juger. `ecarts` : une ligne
    par écart, avec les colonnes `constat` et `proposition` (None quand l'outil ne
    propose rien), indexée par la position de la ligne en écart. L'issue n'est pas
    donnée par le type : c'est celle de la règle, ou à défaut celle du type.
    """

    evaluables: pd.Series
    ecarts: pd.DataFrame


@dataclass(frozen=True)
class TypeRegle:
    """Type de règle du catalogue.

    `parametres` : nom et genre de chaque paramètre; ceux de `facultatifs` peuvent
    manquer. `controler(donnees, parametres, natures)` reçoit la vue de la table
    (index = position des lignes dans la table), les paramètres présents de
    l'instance et la nature en vigueur de ses colonnes; il rend des `Constats`.
    `prerequis(donnees)` rend le problème qui empêche d'appliquer le type à une
    table, None s'il n'y en a pas. `verifier(parametres)` rend les problèmes
    propres au type (par exemple un minimum supérieur au maximum), une fois chaque
    paramètre vérifié selon son genre. `issue` : issue des écarts quand la règle
    n'en déclare pas.
    """

    description: str
    parametres: dict
    vue: str
    controler: Callable
    prerequis: Callable | None = None
    facultatifs: tuple = ()
    verifier: Callable | None = None
    issue: str = ISSUE_ANOMALIE


def _ecarts(constats: pd.Series, propositions: pd.Series | None = None) -> pd.DataFrame:
    """Écarts d'un type : une ligne par constat renseigné, indexée par la position."""
    garde = constats.notna()
    ecarts = pd.DataFrame(
        {"constat": constats[garde].astype(object), "proposition": None},
        index=constats.index[garde],
        columns=["constat", "proposition"],
    )
    if propositions is not None:
        ecarts["proposition"] = propositions[garde].astype(object)
    return ecarts


def _est_nombre(valeur) -> bool:
    return (
        isinstance(valeur, (int, float))
        and not isinstance(valeur, bool)
        and math.isfinite(valeur)
    )


def _bornes_periode(valeur):
    """Début et fin (exclue) de la période d'un export, None si elle est illisible."""
    if not isinstance(valeur, str):
        return None
    if _MOTIF_ANNEE.fullmatch(valeur):
        debut = pd.Timestamp(int(valeur), 1, 1)
        return debut, debut + pd.DateOffset(years=1)
    trouve = _MOTIF_MOIS.fullmatch(valeur)
    if trouve and 1 <= int(trouve.group(2)) <= 12:
        debut = pd.Timestamp(int(trouve.group(1)), int(trouve.group(2)), 1)
        return debut, debut + pd.DateOffset(months=1)
    return None


def _prerequis_export(donnees: pd.DataFrame) -> str | None:
    if COLONNE_PERIODE not in donnees.columns or not any(
        _bornes_periode(valeur) for valeur in donnees[COLONNE_PERIODE].unique()
    ):
        return (
            "la table n'est pas un export périodique (aucune période d'export "
            "lisible dans periode_export)"
        )
    return None


CONSTAT_DATE_ANTERIEURE = "date antérieure à la période de l'export"
CONSTAT_DATE_POSTERIEURE = "date postérieure à la période de l'export"


def _date_dans_periode_export(donnees, parametres, natures) -> Constats:
    """Date de référence de chaque ligne dans la période de son export.

    La correction proposée remplace l'année par celle de l'export, quand la date
    obtenue tombe dans la période.
    """
    colonne = parametres["colonne"]
    nature = natures[colonne]
    dates = lire(donnees[colonne], nature).valeurs
    bornes = [_bornes_periode(valeur) for valeur in donnees[COLONNE_PERIODE]]
    evaluables = dates.notna() & pd.Series(
        [periode is not None for periode in bornes], index=donnees.index, dtype=bool
    )
    constats = pd.Series(None, index=donnees.index, dtype=object)
    propositions = pd.Series(None, index=donnees.index, dtype=object)
    for position, date, periode in zip(donnees.index, dates, bornes):
        if pd.isna(date) or periode is None:
            continue
        debut, fin = periode
        if debut <= date < fin:
            continue
        constats.loc[position] = (
            CONSTAT_DATE_ANTERIEURE if date < debut else CONSTAT_DATE_POSTERIEURE
        )
        try:
            corrigee = date.replace(year=debut.year)
        except ValueError:
            corrigee = None
        if corrigee is not None and debut <= corrigee < fin:
            propositions.loc[position] = ecrire_date(corrigee, nature)
    return Constats(evaluables, _ecarts(constats, propositions))


CONSTAT_INFERIEURE = "inférieure au minimum"
CONSTAT_SUPERIEURE = "supérieure au maximum"
CONSTAT_RAPPORT_INFERIEUR = "rapport inférieur au minimum"
CONSTAT_RAPPORT_SUPERIEUR = "rapport supérieur au maximum"
CONSTAT_RAPPORT_NON_CALCULABLE = "rapport non calculable (dénominateur nul)"
# Le rapport est arrondi avant d'être comparé à ses bornes, pour qu'une erreur de
# calcul en virgule flottante ne fasse pas sortir de la plage une valeur égale à
# une borne.
_DECIMALES_RAPPORT = 9


def _comparer(valeurs, mini, maxi, sous: str, dessus: str) -> pd.Series:
    """Constat de chaque valeur face à ses bornes incluses, None dans la plage.

    `mini` et `maxi` sont un nombre, une série alignée sur les valeurs (NaN pour
    une ligne sans cette borne) ou None. Une valeur NaN n'a pas de constat.
    """
    constats = pd.Series(None, index=valeurs.index, dtype=object)
    if mini is not None:
        constats[(valeurs < mini).to_numpy(dtype=bool)] = sous
    if maxi is not None:
        constats[(valeurs > maxi).to_numpy(dtype=bool)] = dessus
    return constats


def _plage(donnees, parametres, natures) -> Constats:
    """Valeur d'une colonne de nombres entre un minimum et un maximum inclus."""
    colonne = parametres["colonne"]
    valeurs = lire(donnees[colonne], natures[colonne]).valeurs
    constats = _comparer(
        valeurs,
        parametres.get("min"),
        parametres.get("max"),
        CONSTAT_INFERIEURE,
        CONSTAT_SUPERIEURE,
    )
    return Constats(valeurs.notna(), _ecarts(constats))


def _plage_selon_valeur(donnees, parametres, natures) -> Constats:
    """Valeur d'une colonne de nombres dans la plage choisie par une autre colonne.

    La valeur de la colonne `selon` est comparée telle quelle aux valeurs de
    `plages`; une ligne dont la valeur n'a pas de plage déclarée est non évaluable.
    """
    colonne, plages = parametres["colonne"], parametres["plages"]
    valeurs = lire(donnees[colonne], natures[colonne]).valeurs
    choix = donnees[parametres["selon"]].map(_valeur_constatee)
    avec_plage = choix.map(lambda valeur: valeur in plages).astype(bool)

    def borne(nom):
        return choix.map(
            lambda valeur: plages[valeur].get(nom) if valeur in plages else None
        ).astype(float)

    constats = _comparer(
        valeurs, borne("min"), borne("max"), CONSTAT_INFERIEURE, CONSTAT_SUPERIEURE
    )
    return Constats(valeurs.notna() & avec_plage, _ecarts(constats))


def _rapport_dans_plage(donnees, parametres, natures) -> Constats:
    """Rapport numérateur × facteur / dénominateur entre un minimum et un maximum.

    Un dénominateur nul est un écart (rapport non calculable), pas une ligne non
    évaluable.
    """
    numerateur, denominateur = parametres["numerateur"], parametres["denominateur"]
    haut = lire(donnees[numerateur], natures[numerateur]).valeurs
    bas = lire(donnees[denominateur], natures[denominateur]).valeurs
    evaluables = haut.notna() & bas.notna()
    rapport = (haut * parametres.get("facteur", 1) / bas.where(bas != 0)).round(
        _DECIMALES_RAPPORT
    )
    constats = _comparer(
        rapport,
        parametres.get("min"),
        parametres.get("max"),
        CONSTAT_RAPPORT_INFERIEUR,
        CONSTAT_RAPPORT_SUPERIEUR,
    )
    constats[(evaluables & (bas == 0)).to_numpy(dtype=bool)] = CONSTAT_RAPPORT_NON_CALCULABLE
    return Constats(evaluables, _ecarts(constats))


def _problemes_bornes(bornes: dict) -> list[str]:
    """Problèmes d'une plage : au moins une borne, des nombres, min au plus max."""
    presentes = [cle for cle in CLES_BORNES if cle in bornes]
    if not presentes:
        return ["min ou max attendu"]
    problemes = [
        f"{cle} : un nombre est attendu" for cle in presentes if not _est_nombre(bornes[cle])
    ]
    if not problemes and len(presentes) == 2 and bornes["min"] > bornes["max"]:
        problemes.append(f"min ({bornes['min']}) supérieur à max ({bornes['max']})")
    return problemes


def _verifier_rapport(parametres: dict) -> list[str]:
    problemes = _problemes_bornes(parametres)
    if parametres.get("facteur") == 0:
        problemes.append("facteur : un nombre non nul est attendu")
    return problemes


TYPES = {
    "date_dans_periode_export": TypeRegle(
        description=(
            "La date de référence de chaque ligne tombe dans la période de son "
            "export (année ou mois, lue dans periode_export)."
        ),
        parametres={"colonne": GENRE_COLONNE_DATE},
        vue=VUE_TOUTES,
        controler=_date_dans_periode_export,
        prerequis=_prerequis_export,
        issue=ISSUE_A_ARBITRER,
    ),
    "plage": TypeRegle(
        description=(
            "La valeur de la colonne est comprise entre min et max (inclus); l'une "
            "des deux bornes peut manquer."
        ),
        parametres={"colonne": GENRE_COLONNE_NOMBRE, "min": GENRE_NOMBRE, "max": GENRE_NOMBRE},
        vue=VUE_TOUTES,
        controler=_plage,
        facultatifs=("min", "max"),
        verifier=_problemes_bornes,
    ),
    "plage_selon_valeur": TypeRegle(
        description=(
            "La valeur de la colonne est comprise dans la plage {min, max} que "
            "plages associe à la valeur de la colonne selon; une ligne dont la "
            "valeur de selon n'a pas de plage est non évaluable."
        ),
        parametres={
            "colonne": GENRE_COLONNE_NOMBRE,
            "selon": GENRE_COLONNE,
            "plages": GENRE_PLAGES,
        },
        vue=VUE_TOUTES,
        controler=_plage_selon_valeur,
    ),
    "rapport_dans_plage": TypeRegle(
        description=(
            "Le rapport numerateur × facteur / denominateur est compris entre min et "
            "max (inclus); facteur vaut 1 par défaut; un dénominateur nul est un "
            "écart."
        ),
        parametres={
            "numerateur": GENRE_COLONNE_NOMBRE,
            "denominateur": GENRE_COLONNE_NOMBRE,
            "facteur": GENRE_NOMBRE,
            "min": GENRE_NOMBRE,
            "max": GENRE_NOMBRE,
        },
        vue=VUE_TOUTES,
        controler=_rapport_dans_plage,
        facultatifs=("facteur", "min", "max"),
        verifier=_verifier_rapport,
    ),
}


def catalogue_types() -> pd.DataFrame:
    """Types de règles disponibles, avec leurs paramètres, leur vue et leur issue."""
    return pd.DataFrame(
        [
            {
                "type": nom,
                "description": type_regle.description,
                "parametres": ", ".join(
                    f"{parametre} ({genre}"
                    + (", facultatif" if parametre in type_regle.facultatifs else "")
                    + ")"
                    for parametre, genre in type_regle.parametres.items()
                ),
                "vue": type_regle.vue,
                "issue": type_regle.issue,
            }
            for nom, type_regle in TYPES.items()
        ],
        columns=list(COLONNES_CATALOGUE),
    )


def chemin_regles_gestion() -> Path:
    """Emplacement par défaut des règles de gestion : config/gestion.yaml."""
    return racine_projet() / "config" / "gestion.yaml"


def _nommer(rang: int, instance) -> str:
    ref = instance.get("ref") if isinstance(instance, dict) else None
    return f"règle n° {rang}" + (f" ({ref})" if isinstance(ref, str) and ref else "")


def _texte_attendu(valeur) -> bool:
    return isinstance(valeur, str) and valeur.strip() != ""


def _colonnes_instance(instance: dict) -> list[str]:
    """Colonnes citées par une instance, dans l'ordre des paramètres de son type."""
    return [
        instance[parametre]
        for parametre, genre in TYPES[instance["type"]].parametres.items()
        if genre in GENRES_COLONNE and parametre in instance
    ]


def _problemes_parametre(genre: str, valeur) -> list[str]:
    """Problèmes d'un paramètre selon son genre."""
    if genre in GENRES_COLONNE:
        return [] if _texte_attendu(valeur) else [f"un nom de colonne est attendu ({genre})"]
    if genre == GENRE_NOMBRE:
        return [] if _est_nombre(valeur) else ["un nombre est attendu"]
    if not isinstance(valeur, dict) or not valeur:
        return ["un dictionnaire non vide est attendu (valeur vers min et max)"]
    problemes = []
    for cle, bornes in valeur.items():
        if not _texte_attendu(cle):
            problemes.append(
                f"valeur {cle!r} : un texte est attendu (mettre un nombre entre guillemets)"
            )
            continue
        if not isinstance(bornes, dict):
            problemes.append(f"valeur {cle!r} : un dictionnaire min et max est attendu")
            continue
        inconnues = [str(nom) for nom in bornes if nom not in CLES_BORNES]
        if inconnues:
            problemes.append(
                f"valeur {cle!r} : clé inconnue {', '.join(inconnues)} (clés possibles : "
                f"{', '.join(CLES_BORNES)})"
            )
            continue
        problemes.extend(f"valeur {cle!r} : {probleme}" for probleme in _problemes_bornes(bornes))
    return problemes


def _problemes_filtre(filtre) -> list[str]:
    """Problèmes d'un filtre : liste de conditions {colonne, valeurs}."""
    if not isinstance(filtre, list) or not filtre:
        return ["une liste de conditions est attendue (chaque condition commence par un tiret)"]
    problemes = []
    for rang, condition in enumerate(filtre, start=1):
        nom = f"condition n° {rang}"
        if not isinstance(condition, dict):
            problemes.append(f"{nom} : un dictionnaire est attendu (clés colonne et valeurs)")
            continue
        inconnues = [str(cle) for cle in condition if cle not in CLES_CONDITION]
        if inconnues:
            problemes.append(
                f"{nom} : clé inconnue {', '.join(inconnues)} (clés possibles : "
                f"{', '.join(CLES_CONDITION)})"
            )
        manquantes = [cle for cle in CLES_CONDITION if cle not in condition]
        if manquantes:
            problemes.append(f"{nom} : clé manquante ({', '.join(manquantes)})")
        if "colonne" in condition and not _texte_attendu(condition["colonne"]):
            problemes.append(f"{nom}, colonne : un nom de colonne est attendu")
        if "valeurs" in condition:
            valeurs = condition["valeurs"]
            if not isinstance(valeurs, list) or not valeurs:
                problemes.append(f"{nom}, valeurs : une liste non vide est attendue")
            else:
                problemes.extend(
                    f"{nom}, valeurs : {valeur!r} n'est pas un texte (mettre un nombre "
                    "entre guillemets)"
                    for valeur in valeurs
                    if not _texte_attendu(valeur)
                )
    return problemes


def _figer(valeur):
    """Valeur d'un paramètre sous une forme comparable et hachable."""
    if isinstance(valeur, dict):
        return tuple(sorted((str(cle), _figer(v)) for cle, v in valeur.items()))
    if isinstance(valeur, list):
        return tuple(_figer(v) for v in valeur)
    return valeur


def problemes_regles_gestion(regles) -> list[str]:
    """Problèmes de structure des règles de gestion, tous listés en une fois."""
    if not isinstance(regles, list):
        return ["une liste de règles est attendue (chaque règle commence par un tiret)"]
    problemes, vues = [], {}
    for rang, instance in enumerate(regles, start=1):
        nom = _nommer(rang, instance)
        if not isinstance(instance, dict):
            problemes.append(f"{nom} : un dictionnaire de clés est attendu")
            continue
        deja = len(problemes)
        manquantes = [cle for cle in CLES_COMMUNES if cle not in instance]
        if manquantes:
            problemes.append(f"{nom} : clé manquante ({', '.join(manquantes)})")
        for cle in CLES_COMMUNES:
            if cle in instance and not _texte_attendu(instance[cle]):
                problemes.append(f"{nom}, {cle} : un texte non vide est attendu")
        if CLE_ISSUE in instance and instance[CLE_ISSUE] not in ISSUES:
            problemes.append(
                f"{nom}, issue : issue inconnue {instance[CLE_ISSUE]!r} (issues possibles : "
                f"{', '.join(ISSUES)})"
            )
        if CLE_FILTRE in instance:
            problemes.extend(
                f"{nom}, filtre, {probleme}"
                if probleme.startswith("condition")
                else f"{nom}, filtre : {probleme}"
                for probleme in _problemes_filtre(instance[CLE_FILTRE])
            )
        type_regle = None
        if _texte_attendu(instance.get("type")):
            type_regle = TYPES.get(instance["type"])
        if type_regle is None:
            if _texte_attendu(instance.get("type")):
                problemes.append(
                    f"{nom} : type inconnu {instance['type']!r} (types possibles : "
                    f"{', '.join(TYPES)})"
                )
            continue
        attendues = (*CLES_COMMUNES, *CLES_FACULTATIVES, *type_regle.parametres)
        inconnues = [str(cle) for cle in instance if cle not in attendues]
        if inconnues:
            problemes.append(
                f"{nom} : clé inconnue {', '.join(inconnues)} (clés possibles pour le "
                f"type {instance['type']} : {', '.join(attendues)})"
            )
        avant_parametres = len(problemes)
        absents = [
            parametre
            for parametre in type_regle.parametres
            if parametre not in instance and parametre not in type_regle.facultatifs
        ]
        if absents:
            problemes.append(f"{nom} : paramètre manquant ({', '.join(absents)})")
        for parametre, genre in type_regle.parametres.items():
            if parametre in instance:
                problemes.extend(
                    f"{nom}, {parametre} : {probleme}"
                    for probleme in _problemes_parametre(genre, instance[parametre])
                )
        if type_regle.verifier is not None and len(problemes) == avant_parametres:
            parametres = {p: instance[p] for p in type_regle.parametres if p in instance}
            problemes.extend(f"{nom} : {probleme}" for probleme in type_regle.verifier(parametres))
        if len(problemes) > deja:
            continue
        repere = (
            instance["type"],
            instance["table"],
            _figer({p: instance[p] for p in type_regle.parametres if p in instance}),
            _figer(instance.get(CLE_FILTRE)),
        )
        if repere in vues:
            problemes.append(
                f"{nom} : règle en double (même type, même table, mêmes paramètres et "
                f"même filtre que la {vues[repere]})"
            )
        else:
            vues[repere] = nom
    return problemes


def charger_regles_gestion(chemin: str | Path | None = None) -> list:
    """Règles de gestion de config/gestion.yaml, dans l'ordre du fichier.

    Le fichier est écrit à la main, d'après ce que dit le métier. Sous la clé
    `regles`, chaque règle est une instance d'un type du catalogue, avec un filtre
    et une issue facultatifs :

        regles:
          - ref: R22
            libelle: Distance imputée de 2 à 120 km
            type: plage
            table: interventions
            colonne: distance_km
            min: 2
            max: 120
            filtre:
              - colonne: statut
                valeurs: [Réalisée]
            issue: anomalie

    Un fichier absent, ou sans clé `regles`, ne donne aucune règle. Un fichier mal
    formé est refusé, tous les problèmes étant listés en une fois.
    """
    chemin = Path(chemin) if chemin is not None else chemin_regles_gestion()
    if not chemin.is_file():
        return []
    with open(chemin, encoding="utf-8") as flux:
        contenu = yaml.safe_load(flux)
    if contenu is None:
        return []
    attendue = " et ".join(f"« {cle} »" for cle in CLES_FICHIER_GESTION)
    if not isinstance(contenu, dict):
        raise ValueError(
            f"Fichier des règles de gestion invalide ({chemin}) : la seule clé "
            f"attendue est {attendue}"
        )
    inconnues = [str(cle) for cle in contenu if cle not in CLES_FICHIER_GESTION]
    if inconnues:
        raise ValueError(
            f"Fichier des règles de gestion invalide ({chemin}) : la seule clé "
            f"attendue est {attendue} (clé inconnue : {', '.join(inconnues)})"
        )
    regles = contenu.get(CLE_REGLES_GESTION)
    if regles is None:
        return []
    problemes = problemes_regles_gestion(regles)
    if problemes:
        raise ValueError(
            f"Règles de gestion invalides ({chemin})\n  " + "\n  ".join(problemes)
        )
    return regles


def _problemes_de_donnees(regles: list, tables: dict, dictionnaire: dict) -> list[str]:
    """Tables, colonnes et natures des règles confrontées aux données et au dictionnaire."""
    problemes = []
    for rang, instance in enumerate(regles, start=1):
        nom = _nommer(rang, instance)
        table = instance["table"]
        if table not in tables:
            problemes.append(f"{nom} : table {table} absente des données chargées")
            continue
        donnees = tables[table]
        presentes = _colonnes_de_donnees(donnees)
        type_regle = TYPES[instance["type"]]
        for parametre, genre in type_regle.parametres.items():
            if genre not in GENRES_COLONNE or parametre not in instance:
                continue
            colonne = instance[parametre]
            if colonne not in presentes:
                problemes.append(
                    f"{nom}, {parametre} : colonne {table}.{colonne} absente des données "
                    "chargées"
                )
                continue
            regles_colonne = dictionnaire.get(table, {}).get(colonne)
            if regles_colonne is None:
                problemes.append(
                    f"{nom}, {parametre} : colonne {table}.{colonne} absente du "
                    "dictionnaire, à régénérer (notebook 02c_dictionnaire)"
                )
                continue
            nature = regles_colonne["nature"]["regle"]
            if genre in _NATURES_ATTENDUES:
                admises, attendu = _NATURES_ATTENDUES[genre]
                if nature not in admises:
                    problemes.append(
                        f"{nom}, {parametre} : la nature en vigueur de {table}.{colonne} "
                        f"est {nature!r}, {attendu} (à trancher dans la revue du "
                        "dictionnaire, notebook 02c_dictionnaire)"
                    )
        for condition in instance.get(CLE_FILTRE) or []:
            if condition["colonne"] not in presentes:
                problemes.append(
                    f"{nom}, filtre : colonne {table}.{condition['colonne']} absente des "
                    "données chargées"
                )
        if type_regle.prerequis is not None:
            probleme = type_regle.prerequis(donnees)
            if probleme:
                problemes.append(f"{nom} : table {table}, {probleme}")
    return problemes


def _dans_le_champ(donnees: pd.DataFrame, filtre) -> pd.Series:
    """Vrai pour une ligne qui remplit toutes les conditions du filtre.

    La valeur de la ligne est comparée telle quelle aux valeurs de la condition;
    une cellule vide ne remplit aucune condition.
    """
    champ = pd.Series(True, index=donnees.index, dtype=bool)
    for condition in filtre or []:
        valeurs = set(condition["valeurs"])
        champ &= donnees[condition["colonne"]].map(
            lambda valeur: _valeur_constatee(valeur) in valeurs
        ).astype(bool)
    return champ


def _texte_filtre(filtre) -> str | None:
    """Filtre écrit pour le bilan : « statut = Réalisée ou Annulée et ... »."""
    if not filtre:
        return None
    return " et ".join(
        f"{condition['colonne']} = {' ou '.join(condition['valeurs'])}" for condition in filtre
    )


def _cle_ligne(donnees: pd.DataFrame) -> tuple:
    return tuple(
        tuple(_texte(valeur) for valeur in ligne)
        for ligne in donnees.reindex(columns=list(COLONNES_LIGNAGE_ECART)).itertuples(
            index=False
        )
    )


def _positions_en_surnombre(doublons: pd.DataFrame, table: str, donnees: pd.DataFrame):
    """Positions des lignes en surnombre d'une table : doublons exacts sauf le premier.

    Les lignes d'un groupe se suivent dans la table des doublons, dans l'ordre de la
    table : la première de chaque groupe est gardée.
    """
    exacts = doublons[(doublons["table"] == table) & (doublons["constat"] == CONSTAT_EXACT)]
    surnombre = exacts[exacts.duplicated("groupe", keep="first")]
    if surnombre.empty:
        return pd.Index([])
    reperes = set(_cle_ligne(surnombre))
    cles = _cle_ligne(donnees)
    return donnees.index[[cle in reperes for cle in cles]]


def _sensible(sensibles, table: str, regles_colonnes: dict, colonnes: list[str]) -> bool:
    """Vrai si l'une des colonnes est sensible, ou marquée comme telle au dictionnaire."""
    return any(
        est_sensible(sensibles, table, colonne)
        or any(
            est_masquee(regles_colonnes[colonne][nom])
            for nom in ("valeurs", "format")
            if colonne in regles_colonnes and nom in regles_colonnes[colonne]
        )
        for colonne in colonnes
    )


def controler_gestion(
    tables: dict[str, pd.DataFrame],
    dictionnaire: dict,
    regles: list | None = None,
    declarations: dict | None = None,
    doublons: pd.DataFrame | None = None,
    sensibles: dict[str, frozenset[str]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Applique les règles de gestion et rend les écarts et le bilan.

    `dictionnaire` est le dictionnaire enregistré : la nature en vigueur de chaque
    colonne dit comment la lire (voir `typage.lire`). `regles` vient de
    config/gestion.yaml par défaut (voir `charger_regles_gestion`). `declarations`
    (déclarations de doublons de config/controles.yaml par défaut) donne la clé de
    chaque table, affichée dans la colonne `cle`. `doublons` est la table rendue par
    `doublons.detecter_doublons`; elle n'est utile qu'aux types qui travaillent sans
    les doublons exacts en surnombre, et elle est calculée si elle manque.

    Avant tout contrôle, sont vérifiés, chacun avec la liste complète des
    problèmes : la classification de sensibilité (`RuntimeError`), la structure des
    règles, puis les tables, les colonnes et leur nature dans les données et le
    dictionnaire (`ValueError`).

    Les lignes en surnombre sont écartées d'abord (selon la vue du type), puis les
    lignes qui ne remplissent pas le filtre de la règle (hors champ).

    Table des écarts (`COLONNES_ECARTS_GESTION`) : une ligne par ligne source et
    par constat, avec le lignage, la référence, le type et le libellé de la règle,
    l'issue (celle de la règle, sinon celle du type), le constat, les colonnes en
    cause, la clé de la ligne, la valeur constatée et la correction proposée par
    l'outil, le cas échéant. Clé, valeur et proposition valent « masqué » dès
    qu'une de leurs colonnes est sensible. Les écarts suivent l'ordre des règles,
    puis celui des lignes sources.

    Bilan (`COLONNES_BILAN_GESTION`) : une ligne par règle, avec son filtre et les
    nombres de lignes de la table, de lignes écartées comme doublons exacts en
    surnombre, de lignes hors champ, de lignes non évaluables et contrôlées (ces
    quatre nombres font le total), d'anomalies, d'écarts à arbitrer et
    d'informations. Les arguments ne sont pas modifiés.
    """
    if sensibles is None:
        sensibles = charger_sensibilite()
    problemes = verifier_sensibilite(tables, sensibles)
    if problemes:
        raise RuntimeError(
            "Classification de sensibilité incohérente\n  " + "\n  ".join(problemes)
        )
    if regles is None:
        regles = charger_regles_gestion()
    problemes = problemes_regles_gestion(regles)
    if not problemes:
        problemes = _problemes_de_donnees(regles, tables, dictionnaire)
    if problemes:
        raise ValueError("Règles de gestion invalides\n  " + "\n  ".join(problemes))
    if declarations is None:
        declarations = charger_declarations_doublons()
    if doublons is None and any(TYPES[r["type"]].vue == VUE_SANS_SURNOMBRE for r in regles):
        doublons, _ = detecter_doublons(tables, declarations, sensibles)

    bilan, morceaux = [], []
    for rang, instance in enumerate(regles):
        table = instance["table"]
        type_regle = TYPES[instance["type"]]
        donnees = tables[table].reset_index(drop=True)
        colonnes = _colonnes_instance(instance)
        regles_colonnes = dictionnaire[table]
        natures = {c: regles_colonnes[c]["nature"]["regle"] for c in colonnes}
        filtre = instance.get(CLE_FILTRE)
        issue = instance.get(CLE_ISSUE, type_regle.issue)

        ecartees = pd.Index([])
        if type_regle.vue == VUE_SANS_SURNOMBRE:
            ecartees = _positions_en_surnombre(doublons, table, donnees)
        vue = donnees.drop(index=ecartees)
        dans_champ = _dans_le_champ(vue, filtre)
        hors_champ = int((~dans_champ).sum())
        vue = vue[dans_champ]
        parametres = {p: instance[p] for p in type_regle.parametres if p in instance}
        constats = type_regle.controler(vue, parametres, natures)
        ecarts = constats.ecarts
        commun = {
            "ref": instance["ref"],
            "type": instance["type"],
            "libelle": instance["libelle"],
            "table": table,
        }
        nombre = len(ecarts)
        bilan.append(
            {
                **commun,
                "colonnes": ", ".join(colonnes),
                "vue": type_regle.vue,
                "filtre": _texte_filtre(filtre),
                "lignes": len(donnees),
                "ecartees_doublons": len(ecartees),
                "hors_champ": hors_champ,
                "non_evaluables": int((~constats.evaluables).sum()),
                "controlees": int(constats.evaluables.sum()),
                "anomalies": nombre if issue == ISSUE_ANOMALIE else 0,
                "a_arbitrer": nombre if issue == ISSUE_A_ARBITRER else 0,
                "informations": nombre if issue == ISSUE_INFORMATION else 0,
            }
        )
        if ecarts.empty:
            continue

        positions = ecarts.index
        cle = declarations.get(table, {}).get("cle", [])
        if not cle:
            cles = [None] * len(positions)
        elif _sensible(sensibles, table, regles_colonnes, cle):
            cles = [VALEUR_MASQUEE] * len(positions)
        else:
            cles = [
                SEPARATEUR.join(_texte(v) for v in ligne)
                for ligne in donnees.loc[positions, cle].itertuples(index=False)
            ]
        if _sensible(sensibles, table, regles_colonnes, colonnes):
            valeurs = [VALEUR_MASQUEE] * len(positions)
            propositions = [
                None if proposition is None else VALEUR_MASQUEE
                for proposition in ecarts["proposition"]
            ]
        else:
            valeurs = [
                None
                if all(_valeur_constatee(v) is None for v in ligne)
                else SEPARATEUR.join(_valeur_constatee(v) or "" for v in ligne)
                for ligne in donnees.loc[positions, colonnes].itertuples(index=False)
            ]
            propositions = list(ecarts["proposition"])
        morceau = pd.DataFrame(
            {
                "_position": positions,
                **commun,
                "issue": issue,
                "constat": ecarts["constat"].to_numpy(),
                "colonnes": ", ".join(colonnes),
                "cle": pd.Series(cles, dtype=object).to_numpy(),
                "valeur": pd.Series(valeurs, dtype=object).to_numpy(),
                "proposition": pd.Series(propositions, dtype=object).to_numpy(),
            }
        )
        for lignage in COLONNES_LIGNAGE_ECART:
            morceau[lignage] = (
                donnees[lignage].loc[positions].to_numpy()
                if lignage in donnees.columns
                else None
            )
        morceau["_regle"] = rang
        morceaux.append(morceau)

    if morceaux:
        ecarts = pd.concat(morceaux, ignore_index=True).sort_values(
            ["_regle", *COLONNES_LIGNAGE_ECART, "_position"],
            kind="stable",
            na_position="first",
        )
        ecarts = ecarts[list(COLONNES_ECARTS_GESTION)].reset_index(drop=True)
    else:
        ecarts = pd.DataFrame(columns=list(COLONNES_ECARTS_GESTION))
    return ecarts, pd.DataFrame(bilan, columns=list(COLONNES_BILAN_GESTION))
