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

Un type peut rapprocher la table de la règle d'une autre table, sa table liée (par
exemple les en-têtes de factures et leurs lignes) : la vue s'applique aux deux
tables, le filtre à la seule table de la règle, et les écarts sont portés par les
lignes de la table de la règle. Les types qui confrontent une table à un
référentiel (existence d'une clé, date dans une période, année déclarée) suivent le
même mécanisme, le référentiel étant la table liée. Un type peut aussi avoir
plusieurs tables liées (par exemple une intervention, les lignes de facture qui la
portent et les en-têtes de ces factures, ou les pièces posées et les pièces facturées).

Un filtre, comme les conditions d'un type, compare la valeur d'une colonne à une
liste de valeurs ou à une expression régulière. Les pratiques que le métier tient
pour normales se déclarent, pour les types qui l'admettent, comme des exceptions
(paramètre `exceptions`) : un écart qui remplit toutes les conditions d'une
exception prend l'issue « information ». Un type peut enfin avoir besoin de la date
de coupure des données (fin de la période extraite), passée à `controler_gestion`.

Un type peut enfin comparer des totaux par période d'export (par exemple le chiffre
d'affaires des factures et celui du FEC) : un tel écart n'appartient à aucune ligne
source, il est rendu sans lignage, la clé donnant la période.

Rien n'est corrigé ni écrit : `controler_gestion` rend la table des écarts et un
bilan.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass, field
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
    COMPARAISON_NORMALISEE,
    COMPARAISON_TELLE_QUELLE,
    CONSTAT_EXACT,
    SEPARATEUR,
    _texte,
    charger_declarations_doublons,
    detecter_doublons,
    normaliser,
)
from .typage import (
    ETAT_ILLISIBLE,
    ETAT_LUE,
    ETAT_VIDE,
    NATURES_DATE,
    NATURES_HEURE,
    NATURES_NOMBRE,
    ecrire_date,
    lire,
)

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
# Clés d'une condition (filtre, conditions et exceptions d'un type) : la colonne, et
# soit la liste des valeurs admises, soit un motif (expression régulière qui couvre la
# valeur entière).
CLES_CONDITION = ("colonne", "valeurs", "motif")
CLES_TEST_CONDITION = ("valeurs", "motif")
# Clés d'une exception (pratique normale) : son libellé et ses conditions.
CLES_EXCEPTION = ("libelle", "conditions")
PREFIXE_PRATIQUE = "pratique normale : "
# Date de coupure des données, transmise au type qui la demande (TypeRegle.contexte).
CONTEXTE_DATE_COUPURE = "date_coupure"
# Vue de la table de la règle avant le filtre (sans les doublons exacts en surnombre
# selon la vue du type), pour juger qu'une clé est répétée dans toute la table.
CONTEXTE_VUE_COMPLETE = "vue_complete"
# Nom de la table de la règle, pour un type qui le cite dans ses valeurs affichées.
CONTEXTE_TABLE = "table"

VUE_TOUTES = "toutes les lignes"
VUE_SANS_SURNOMBRE = "sans les doublons exacts en surnombre"

# Genre d'un paramètre, qui dit comment il est vérifié.
GENRE_COLONNE_DATE = "colonne de date"
GENRE_COLONNE_HEURE = "colonne d'heure"
GENRE_COLONNE_NOMBRE = "colonne de nombre"
GENRE_COLONNE = "colonne"
GENRES_COLONNE = (GENRE_COLONNE_DATE, GENRE_COLONNE_HEURE, GENRE_COLONNE_NOMBRE, GENRE_COLONNE)
GENRE_NOMBRE = "nombre"
GENRE_PLAGES = "plages"
GENRE_MOTIF_NUMERO = "motif de numéro"
GENRE_COMPARAISON = "comparaison"
GENRE_HORAIRES = "horaires"
GENRE_FERIES = "jours fériés"
GENRE_VALEURS = "liste de valeurs"
GENRE_COLONNES = "liste de colonnes"
GENRE_TERMES = "termes"
GENRE_TABLE = "table"
GENRE_BOOLEEN = "true ou false"
# Colonnes de la table liée (nommée par un paramètre de genre « table »), avec le
# genre de colonne qui dit leur nature attendue.
GENRE_COLONNE_LIEE = "colonne de la table liée"
GENRE_COLONNE_NOMBRE_LIEE = "colonne de nombre de la table liée"
GENRE_COLONNE_DATE_LIEE = "colonne de date de la table liée"
GENRE_COLONNE_HEURE_LIEE = "colonne d'heure de la table liée"
GENRES_COLONNE_LIEE = {
    GENRE_COLONNE_LIEE: GENRE_COLONNE,
    GENRE_COLONNE_NOMBRE_LIEE: GENRE_COLONNE_NOMBRE,
    GENRE_COLONNE_DATE_LIEE: GENRE_COLONNE_DATE,
    GENRE_COLONNE_HEURE_LIEE: GENRE_COLONNE_HEURE,
}
# Liste de colonnes de la table liée.
GENRE_COLONNES_LIEES = "liste de colonnes de la table liée"
# Colonnes de même nom dans la table de la règle et dans la table liée.
GENRE_COLONNES_COMMUNES = "colonnes des deux tables"
# Liste de conditions {colonne, valeurs ou motif}, toutes vraies, sur la table de la
# règle ou sur la table liée que désigne TypeRegle.rattachements.
GENRE_CONDITIONS = "liste de conditions"
# Exceptions (pratiques normales) : liste de {libelle, conditions}; une colonne écrite
# « table.colonne » est celle d'une table liée de la règle.
GENRE_EXCEPTIONS = "exceptions"
# Liste d'au moins une colonne de nombre de la table de la règle.
GENRE_COLONNES_NOMBRE = "liste de colonnes de nombre"
# Facteurs d'un produit : liste de colonnes de nombre, chacune écrite seule ou en
# dictionnaire {colonne, coefficient, constante, vide} (voir `_facteur`).
GENRE_FACTEURS = "facteurs"
# Sens d'un arrondi à un pas (voir `ARRONDIS`).
GENRE_ARRONDI = "arrondi"
# Montants comparés aux lignes liées : liste de {colonne, conditions, termes} (voir
# `CLES_MONTANT`).
GENRE_MONTANTS = "montants"
# Termes portés par les colonnes de nombre de la table liée (colonne vers coefficient).
GENRE_TERMES_LIES = "termes de la table liée"
# Natures en vigueur admises pour une colonne, selon le genre du paramètre.
_NATURES_ATTENDUES = {
    GENRE_COLONNE_DATE: (NATURES_DATE, "une date est attendue"),
    GENRE_COLONNE_HEURE: (NATURES_HEURE, "une heure est attendue"),
    GENRE_COLONNE_NOMBRE: (NATURES_NOMBRE, "un nombre est attendu"),
}
# Comparaison des valeurs d'une colonne de regroupement ou d'une clé : telle quelle,
# après normalisation (voir doublons.normaliser), ou mots dans le désordre (après
# normalisation, les mots étant triés, pour rapprocher « NOM Prénom » de « Prénom NOM »).
COMPARAISON_MOTS = "mots dans le désordre"
COMPARAISONS = (COMPARAISON_TELLE_QUELLE, COMPARAISON_NORMALISEE, COMPARAISON_MOTS)
# Arrondi d'une valeur à un pas : au multiple supérieur, inférieur ou le plus proche
# (à égale distance, le multiple supérieur).
ARRONDI_SUPERIEUR = "supérieur"
ARRONDI_INFERIEUR = "inférieur"
ARRONDI_PROCHE = "au plus proche"
ARRONDIS = (ARRONDI_SUPERIEUR, ARRONDI_INFERIEUR, ARRONDI_PROCHE)
# Clés d'un facteur écrit en dictionnaire.
CLES_FACTEUR = ("colonne", "coefficient", "constante", "vide")
# Clés d'un montant : la colonne de la table de la règle, les conditions (facultatives)
# que remplissent les lignes liées retenues, et les termes (colonne de la table liée
# vers coefficient) dont la somme fait la valeur de chaque ligne liée.
CLES_MONTANT = ("colonne", "conditions", "termes")
# Horaires : créneaux de chaque jour de la semaine, et d'un jour férié. Un jour
# absent n'a aucun créneau. Un créneau va de debut (inclus) à fin (exclue).
JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
JOUR_FERIE = "ferie"
CLES_HORAIRES = (*JOURS, JOUR_FERIE)
CLES_CRENEAU = ("debut", "fin")
_MOTIF_HEURE = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]|24:00")
_MOTIF_JOUR = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# Bornes d'une plage, incluses.
CLES_BORNES = ("min", "max")
# Groupes nommés réservés d'un motif de numéro : le numéro (obligatoire) et
# l'année (facultative, comparée à l'année de la date par la règle chronologique).
# Les autres groupes nommés définissent la série.
GROUPE_NUMERO = "numero"
GROUPE_ANNEE = "annee"
_CHIFFRES = re.compile(r"[0-9]+")

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
    "avertissements",
)
COLONNES_CATALOGUE = ("type", "description", "parametres", "vue", "issue")


@dataclass(frozen=True)
class Constats:
    """Résultat d'un type sur sa vue, indexé par la position des lignes.

    `evaluables` : vrai pour une ligne que le type a pu juger. `ecarts` : une ligne
    par écart, avec les colonnes `constat` et `proposition` (None quand l'outil ne
    propose rien), indexée par la position de la ligne en écart; une même ligne peut
    porter plusieurs écarts. Une colonne `valeur`, facultative, remplace la valeur
    affichée par défaut (les valeurs des colonnes de la règle) quand elle n'est pas
    vide. L'issue n'est pas donnée par le type : c'est celle de la règle, ou à
    défaut celle du type. `avertissements` : messages sur la règle elle-même (par
    exemple une configuration incomplète pour une année des données), affichés au
    bilan. `hors_champ`, facultatif : vrai pour une ligne que le type laisse hors de
    son champ (par exemple une clé facultative vide); elle est comptée avec les
    lignes hors du filtre, et non parmi les lignes non évaluables. Une colonne
    `issue`, facultative, donne l'issue d'un écart quand elle n'est pas vide (par
    exemple « information » pour une pratique normale déclarée en exception).
    `ecarts_periodes`, facultatif : écarts qui n'appartiennent à aucune ligne source
    (par exemple un total de période), une ligne par écart, avec les colonnes
    `constat`, `cle` (par exemple la période) et `valeur`, et une colonne `issue`
    facultative; ils sont rendus sans lignage, après les écarts des lignes de la règle.
    """

    evaluables: pd.Series
    ecarts: pd.DataFrame
    avertissements: tuple = ()
    hors_champ: pd.Series | None = None
    ecarts_periodes: pd.DataFrame | None = None


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
    n'en déclare pas. `table_liee` : nom du paramètre qui désigne la table liée,
    pour un type qui rapproche deux tables; `controler` reçoit alors aussi la table
    liée (`Liee`), prise selon la même vue. `defauts` : paramètre facultatif vers le
    paramètre dont il reprend la valeur quand il manque (par exemple la clé du
    référentiel, qui reprend par défaut les noms de colonnes de la clé).

    `tables_liees` : noms des paramètres qui désignent les tables liées, pour un type
    qui en rapproche plusieurs; `controler` reçoit alors un dictionnaire (paramètre
    vers `Liee`) au lieu d'une seule `Liee`. `rattachements` : paramètre de colonnes
    vers le paramètre de la table liée à laquelle ces colonnes appartiennent (par
    défaut `table_liee`). `contexte` : informations sur les données que le type
    demande, transmises dans ses paramètres (`CONTEXTE_DATE_COUPURE`,
    `CONTEXTE_VUE_COMPLETE`, `CONTEXTE_TABLE`). `prerequis_liees(donnees)` rend le
    problème qui empêche d'appliquer le type à une table liée, None s'il n'y en a pas.
    """

    description: str
    parametres: dict
    vue: str
    controler: Callable
    prerequis: Callable | None = None
    facultatifs: tuple = ()
    verifier: Callable | None = None
    issue: str = ISSUE_ANOMALIE
    table_liee: str | None = None
    defauts: dict = field(default_factory=dict)
    tables_liees: tuple = ()
    rattachements: dict = field(default_factory=dict)
    contexte: tuple = ()
    prerequis_liees: Callable | None = None

    def parametres_tables(self) -> tuple:
        """Paramètres qui désignent les tables liées, dans leur ordre."""
        if self.tables_liees:
            return self.tables_liees
        return (self.table_liee,) if self.table_liee else ()


@dataclass(frozen=True)
class Liee:
    """Table liée d'une règle : son nom, sa vue (index = position des lignes dans la
    table) et la nature en vigueur des colonnes citées par la règle."""

    table: str
    donnees: pd.DataFrame
    natures: dict


def _ecarts(
    constats: pd.Series,
    propositions: pd.Series | None = None,
    valeurs: pd.Series | None = None,
    issues: pd.Series | None = None,
) -> pd.DataFrame:
    """Écarts d'un type : une ligne par constat renseigné, indexée par la position."""
    garde = constats.notna()
    ecarts = pd.DataFrame(
        {"constat": constats[garde].astype(object), "proposition": None},
        index=constats.index[garde],
        columns=["constat", "proposition"],
    )
    if propositions is not None:
        ecarts["proposition"] = propositions[garde].astype(object)
    if valeurs is not None:
        ecarts["valeur"] = valeurs[garde].astype(object)
    if issues is not None:
        ecarts["issue"] = issues[garde].astype(object)
    return ecarts


def _renseignee(valeur) -> bool:
    return valeur is not None and not (isinstance(valeur, float) and math.isnan(valeur))


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


CONSTAT_NUMEROS_MANQUANTS = "numéros manquants avant celui-ci"
CONSTAT_DATE_AVANT_PRECEDENT = "date antérieure à celle du numéro précédent"
CONSTAT_ANNEE_DU_NUMERO = "année du numéro différente de l'année de la date"


def _numeros(donnees: pd.DataFrame, colonne: str, motif: str) -> dict:
    """Série, numéro et correspondance de chaque ligne dont la valeur suit le motif.

    Le motif doit couvrir la valeur entière, et son groupe `numero` n'être fait que
    de chiffres; les autres groupes nommés, dans leur ordre, forment la série. Une
    ligne vide ou qui ne suit pas le motif est absente du résultat. Les lignes sont
    rendues dans l'ordre de la vue.
    """
    expression = re.compile(motif)
    noms = [nom for nom in expression.groupindex if nom != GROUPE_NUMERO]
    lues = {}
    for position, valeur in donnees[colonne].items():
        texte = _valeur_constatee(valeur)
        trouve = None if texte is None else expression.fullmatch(texte)
        if trouve is None or not _CHIFFRES.fullmatch(trouve.group(GROUPE_NUMERO) or ""):
            continue
        serie = tuple(trouve.group(nom) for nom in noms)
        lues[position] = (serie, int(trouve.group(GROUPE_NUMERO)), trouve)
    return lues


def _ecrire_numero(trouve: re.Match, numero: int) -> str:
    """Valeur de la ligne où le numéro est remplacé par un autre, à la même largeur."""
    debut, fin = trouve.span(GROUPE_NUMERO)
    return trouve.string[:debut] + str(numero).zfill(fin - debut) + trouve.string[fin:]


def _numeros_manquants(trouve: re.Match, premier: int, dernier: int) -> str:
    """Plage des numéros manquants : « INT-2025-000004 à INT-2025-000006 (3 numéros) »."""
    nombre = dernier - premier + 1
    if nombre == 1:
        return f"{_ecrire_numero(trouve, premier)} (1 numéro)"
    return (
        f"{_ecrire_numero(trouve, premier)} à {_ecrire_numero(trouve, dernier)} "
        f"({nombre} numéros)"
    )


def _numerotation_continue(donnees, parametres, natures) -> Constats:
    """Numéros de chaque série sans trou.

    Un trou est porté par la première ligne (dans l'ordre de la vue) du numéro qui le
    suit; la valeur affichée donne la plage des numéros manquants. Avec `debut`, les
    numéros manquants entre `debut` et le premier numéro observé forment aussi un
    trou. Un numéro répété ne crée pas de trou (les valeurs en double relèvent des
    doublons). Les derniers numéros d'une série, s'ils manquent, ne se voient pas.
    """
    lues = _numeros(donnees, parametres["colonne"], parametres["motif"])
    evaluables = pd.Series(donnees.index.isin(list(lues)), index=donnees.index, dtype=bool)
    par_serie = {}
    for position, (serie, numero, trouve) in lues.items():
        par_serie.setdefault(serie, {}).setdefault(numero, (position, trouve))
    constats = pd.Series(None, index=donnees.index, dtype=object)
    valeurs = pd.Series(None, index=donnees.index, dtype=object)
    debut = parametres.get("debut")
    for numeros in par_serie.values():
        precedent = None if debut is None else int(debut) - 1
        for numero in sorted(numeros):
            if precedent is not None and numero > precedent + 1:
                position, trouve = numeros[numero]
                constats.loc[position] = CONSTAT_NUMEROS_MANQUANTS
                valeurs.loc[position] = _numeros_manquants(trouve, precedent + 1, numero - 1)
            precedent = numero
    return Constats(evaluables, _ecarts(constats, valeurs=valeurs))


def _numerotation_chronologique(donnees, parametres, natures) -> Constats:
    """Numéros de chaque série croissants avec la date.

    Une ligne est évaluable si sa valeur suit le motif et si sa date est lisible
    (et, quand le motif a un groupe `annee`, si l'année n'est faite que de
    chiffres). Chaque ligne évaluable est comparée au numéro précédent de sa série
    qui a une date lisible, représenté par sa première ligne dans l'ordre de la vue;
    une date antérieure est un écart, porté par la ligne au numéro le plus grand, et
    la valeur affichée donne les deux dates. Quand le motif a un groupe `annee`, une
    année différente de celle de la date est un autre écart.
    """
    colonne, colonne_date = parametres["colonne"], parametres["date"]
    lues = _numeros(donnees, colonne, parametres["motif"])
    avec_annee = GROUPE_ANNEE in re.compile(parametres["motif"]).groupindex
    dates = lire(donnees[colonne_date], natures[colonne_date]).valeurs
    textes_dates = donnees[colonne_date].map(_valeur_constatee)
    evaluables = pd.Series(False, index=donnees.index, dtype=bool)
    representants = {}
    for position, (serie, numero, trouve) in lues.items():
        if pd.isna(dates.loc[position]):
            continue
        if avec_annee and not _CHIFFRES.fullmatch(trouve.group(GROUPE_ANNEE) or ""):
            continue
        evaluables.loc[position] = True
        representants.setdefault(serie, {}).setdefault(numero, position)
    precedents = {}
    for serie, numeros in representants.items():
        ordonnes = sorted(numeros)
        precedents[serie] = dict(zip(ordonnes[1:], ordonnes[:-1]))

    ruptures = pd.Series(None, index=donnees.index, dtype=object)
    valeurs = pd.Series(None, index=donnees.index, dtype=object)
    annees = pd.Series(None, index=donnees.index, dtype=object)
    for position in evaluables.index[evaluables.to_numpy()]:
        serie, numero, trouve = lues[position]
        date = dates.loc[position]
        precedent = precedents[serie].get(numero)
        if precedent is not None:
            ligne_precedente = representants[serie][precedent]
            if date < dates.loc[ligne_precedente]:
                ruptures.loc[position] = CONSTAT_DATE_AVANT_PRECEDENT
                valeurs.loc[position] = (
                    f"{textes_dates.loc[position]} (numéro précédent "
                    f"{lues[ligne_precedente][2].string} : {textes_dates.loc[ligne_precedente]})"
                )
        if avec_annee and int(trouve.group(GROUPE_ANNEE)) != date.year:
            annees.loc[position] = CONSTAT_ANNEE_DU_NUMERO
    ecarts = pd.concat([_ecarts(ruptures, valeurs=valeurs), _ecarts(annees)])
    return Constats(evaluables, ecarts)


CONSTAT_CHEVAUCHEMENT = "chevauche une ligne précédente du même groupe"
CONSTAT_BATTEMENT = "écart inférieur au battement avec la ligne précédente"


def _comparable(texte: str, comparaison: str) -> str:
    """Texte sous la forme où il est comparé (voir `COMPARAISONS`)."""
    if comparaison == COMPARAISON_TELLE_QUELLE:
        return texte
    normalise = normaliser(texte)
    if comparaison == COMPARAISON_MOTS:
        return " ".join(sorted(normalise.split()))
    return normalise


def _groupe_lu(valeur, comparaison: str) -> str | None:
    """Valeur d'une colonne de regroupement, None si elle est vide."""
    texte = _valeur_constatee(valeur)
    if texte is None or not texte.strip():
        return None
    return _comparable(texte, comparaison)


def _ecrire_creneau(debut: pd.Timestamp, fin: pd.Timestamp) -> str:
    """Créneau écrit « 14/03/2025 10:00 à 11:35 » (date de fin donnée si elle change)."""
    texte = f"{debut:%d/%m/%Y %H:%M} à "
    if fin.normalize() == debut.normalize():
        return texte + f"{fin:%H:%M}"
    return texte + f"{fin:%d/%m/%Y %H:%M}"


def _reperer_ligne(donnees: pd.DataFrame, position) -> str:
    """Lignage d'une ligne écrit « fichier, feuille, ligne n »."""
    morceaux = []
    for colonne in COLONNES_LIGNAGE_ECART:
        if colonne not in donnees.columns:
            continue
        texte = _valeur_constatee(donnees.at[position, colonne])
        if texte:
            morceaux.append(f"ligne {texte}" if colonne == "num_ligne_source" else texte)
    return ", ".join(morceaux)


def _intervalles_sans_chevauchement(donnees, parametres, natures) -> Constats:
    """Intervalles d'un même groupe sans chevauchement, séparés d'au moins le battement.

    Un intervalle commence à la date (et à l'heure, si elle est déclarée) et dure
    `duree` minutes. Dans chaque groupe, les intervalles sont pris par début
    croissant; chacun est comparé à l'intervalle précédent qui finit le plus tard
    (une longue ligne peut en contenir une courte). Un début avant cette fin est un
    chevauchement; un début avant cette fin plus le battement est un écart trop
    court. L'écart est porté par la ligne qui commence le plus tard; la valeur
    affichée donne les deux créneaux et le lignage de l'autre ligne. Un groupe vide,
    une date, une heure ou une durée vide ou illisible, ou une durée négative,
    rendent la ligne non évaluable.
    """
    colonne_date, colonne_duree = parametres["date"], parametres["duree"]
    dates = lire(donnees[colonne_date], natures[colonne_date]).valeurs
    if "heure" in parametres:
        heures = lire(donnees[parametres["heure"]], natures[parametres["heure"]]).valeurs
    else:
        heures = pd.Series(pd.Timedelta(0), index=donnees.index, dtype="timedelta64[ns]")
    durees = lire(donnees[colonne_duree], natures[colonne_duree]).valeurs
    comparaison = parametres.get("comparaison", COMPARAISON_TELLE_QUELLE)
    groupes = donnees[parametres["groupe"]].map(lambda valeur: _groupe_lu(valeur, comparaison))
    debuts = dates + heures
    fins = debuts + pd.to_timedelta(durees, unit="min")
    evaluables = (groupes.notna() & debuts.notna() & (durees >= 0)).astype(bool)
    battement = pd.Timedelta(minutes=parametres.get("battement", 0))

    ordre = pd.DataFrame(
        {"groupe": groupes, "debut": debuts, "fin": fins, "position": donnees.index},
        index=donnees.index,
    )[evaluables.to_numpy()]
    ordre = ordre.sort_values(["groupe", "debut", "fin", "position"], kind="stable")
    constats = pd.Series(None, index=donnees.index, dtype=object)
    valeurs = pd.Series(None, index=donnees.index, dtype=object)
    precedents = {}
    for groupe, debut, fin, position in ordre.itertuples(index=False):
        avant = precedents.get(groupe)
        if avant is not None:
            fin_avant, position_avant = avant
            constat = None
            if debut < fin_avant:
                constat = CONSTAT_CHEVAUCHEMENT
            elif debut < fin_avant + battement:
                constat = CONSTAT_BATTEMENT
            if constat is not None:
                constats.loc[position] = constat
                valeurs.loc[position] = (
                    f"{_ecrire_creneau(debut, fin)}, après "
                    f"{_ecrire_creneau(debuts.loc[position_avant], fin_avant)} "
                    f"({_reperer_ligne(donnees, position_avant)})"
                )
        if avant is None or fin > avant[0]:
            precedents[groupe] = (fin, position)
    return Constats(evaluables, _ecarts(constats, valeurs=valeurs))


CONSTAT_HORS_HORAIRES = "hors horaires sans valeur admise"
NOM_FERIE = "férié"


def _minutes(texte) -> int | None:
    """Minutes depuis minuit d'une heure « HH:MM » (24:00 admis), None si illisible."""
    if not isinstance(texte, str) or not _MOTIF_HEURE.fullmatch(texte):
        return None
    heures, minutes = texte.split(":")
    return int(heures) * 60 + int(minutes)


def _annee_feries(cle) -> int | None:
    """Année d'une clé de feries (nombre ou texte de quatre chiffres), None sinon."""
    if isinstance(cle, int) and not isinstance(cle, bool):
        return cle if 1 <= cle <= 9999 else None
    if isinstance(cle, str) and _MOTIF_ANNEE.fullmatch(cle):
        return int(cle)
    return None


def _jour_ferie(valeur) -> dt.date | None:
    """Date d'un jour férié (date lue par YAML ou texte AAAA-MM-JJ), None sinon."""
    if isinstance(valeur, dt.datetime):
        return None
    if isinstance(valeur, dt.date):
        return valeur
    if isinstance(valeur, str) and _MOTIF_JOUR.fullmatch(valeur):
        try:
            return dt.date.fromisoformat(valeur)
        except ValueError:
            return None
    return None


def _pluriel(nombre: int, singulier: str, pluriel: str) -> str:
    return f"{nombre} {singulier if nombre <= 1 else pluriel}"


def _lire_horaires(parametres: dict) -> tuple[dict, dict]:
    """Jours fériés (année vers ensemble de dates) et créneaux (jour vers liste de
    couples début, fin en minutes) des paramètres horaires et feries."""
    feries = {
        _annee_feries(cle): {pd.Timestamp(_jour_ferie(valeur)) for valeur in jours}
        for cle, jours in parametres["feries"].items()
    }
    creneaux = {
        jour: [(_minutes(creneau["debut"]), _minutes(creneau["fin"])) for creneau in liste]
        for jour, liste in parametres["horaires"].items()
    }
    return feries, creneaux


def _situer(date, heure, feries: dict, creneaux: dict):
    """Situation d'une date et d'une heure face aux horaires : None si la date ou l'heure
    manque, ou si l'année n'a pas de jours fériés déclarés; sinon le jour écrit
    (« samedi 08/03/2025 13:00 », « férié 01/05/2025 10:00 ») et vrai si l'heure tombe
    dans un créneau de ce jour (début inclus, fin exclue)."""
    if pd.isna(date) or pd.isna(heure) or date.year not in feries:
        return None
    ferie = date.normalize() in feries[date.year]
    jour = JOUR_FERIE if ferie else JOURS[date.dayofweek]
    minutes = int(heure.total_seconds() // 60)
    dans = any(debut <= minutes < fin for debut, fin in creneaux.get(jour, []))
    texte = (
        f"{NOM_FERIE if ferie else jour} {date:%d/%m/%Y} "
        f"{minutes // 60:02d}:{minutes % 60:02d}"
    )
    return texte, dans


def _avertissements_feries(dates: pd.Series, feries: dict, minimum) -> list[str]:
    """Avertissements, pour chaque année des dates lues : année absente des jours
    fériés déclarés (avec son nombre de lignes), année sans jour férié, ou avec moins
    de jours que le minimum."""
    avertissements = []
    for annee, nombre in dates.dropna().dt.year.value_counts().sort_index().items():
        annee = int(annee)
        if annee not in feries:
            avertissements.append(
                f"année {annee} absente des jours fériés déclarés : "
                + _pluriel(int(nombre), "ligne non évaluable", "lignes non évaluables")
            )
        elif not feries[annee]:
            avertissements.append(f"année {annee} : aucun jour férié déclaré")
        elif minimum is not None and len(feries[annee]) < minimum:
            avertissements.append(
                f"année {annee} : "
                + _pluriel(len(feries[annee]), "jour férié déclaré", "jours fériés déclarés")
                + f", moins que feries_minimum ({minimum:g})"
            )
    return avertissements


def _hors_horaires_selon_valeur(donnees, parametres, natures) -> Constats:
    """Ligne hors horaires portant l'une des valeurs admises dans sa colonne.

    Le jour de la ligne est un jour férié s'il figure dans `feries`, sinon son jour
    de la semaine; l'heure est comparée aux créneaux de ce jour (début inclus, fin
    exclue). Une ligne hors de tout créneau doit porter, dans `colonne`, l'une des
    `valeurs` (comparées telles quelles; une liste vide n'en admet aucune). Une date
    ou une heure vide ou illisible, une année sans jours fériés déclarés, ou une
    valeur vide pour une ligne hors horaires, rendent la ligne non évaluable.

    Avertissements, pour chaque année des dates lues : année absente de `feries`,
    année déclarée sans jour férié, ou avec moins de `feries_minimum` jours.
    """
    colonne_date, colonne_heure = parametres["date"], parametres["heure"]
    dates = lire(donnees[colonne_date], natures[colonne_date]).valeurs
    heures = lire(donnees[colonne_heure], natures[colonne_heure]).valeurs
    feries, creneaux = _lire_horaires(parametres)
    admises = set(parametres["valeurs"])
    textes = donnees[parametres["colonne"]].map(_valeur_constatee)

    evaluables = pd.Series(False, index=donnees.index, dtype=bool)
    constats = pd.Series(None, index=donnees.index, dtype=object)
    valeurs = pd.Series(None, index=donnees.index, dtype=object)
    for position in donnees.index:
        situation = _situer(dates.loc[position], heures.loc[position], feries, creneaux)
        if situation is None:
            continue
        moment, dans = situation
        if dans:
            evaluables.loc[position] = True
            continue
        texte = textes.loc[position]
        if texte is None or not texte.strip():
            continue
        evaluables.loc[position] = True
        if texte in admises:
            continue
        constats.loc[position] = CONSTAT_HORS_HORAIRES
        valeurs.loc[position] = f"{moment}{SEPARATEUR}{texte}"
    avertissements = _avertissements_feries(dates, feries, parametres.get("feries_minimum"))
    return Constats(evaluables, _ecarts(constats, valeurs=valeurs), tuple(avertissements))


# Les calculs sont arrondis avant d'être comparés à leur tolérance, pour qu'une
# erreur de calcul en virgule flottante ne crée pas un écart.
_DECIMALES_CALCUL = 9
CONSTAT_ECART_CALCUL = "écart au calcul supérieur à la tolérance"
CONSTAT_TOTAL_DIFFERENT = "total différent de la somme des lignes liées"
CONSTAT_SANS_LIGNE = "aucune ligne liée"
CONSTAT_DESEQUILIBRE = "groupe non équilibré"


def _ecrire_nombre(valeur: float) -> str:
    """Nombre écrit avec une virgule décimale, sans zéro inutile (« 36,3 », « -0,05 »)."""
    texte = f"{round(valeur, _DECIMALES_CALCUL):.{_DECIMALES_CALCUL}f}".rstrip("0").rstrip(".")
    return ("0" if texte == "-0" else texte).replace(".", ",")


def _cles_lues(donnees: pd.DataFrame, colonnes: list[str]) -> pd.Series:
    """Clé de chaque ligne (textes de ses colonnes), None si l'une d'elles est vide."""

    def cle(ligne):
        textes = tuple(_valeur_constatee(valeur) for valeur in ligne)
        return None if any(t is None or not t.strip() for t in textes) else textes

    return pd.Series(
        [cle(ligne) for ligne in donnees[colonnes].itertuples(index=False)],
        index=donnees.index,
        dtype=object,
    )


def _egalite_calculee(donnees, parametres, natures) -> Constats:
    """Valeur d'une colonne égale à un calcul sur la même ligne, à la tolérance près.

    Le calcul est la somme des colonnes de `termes`, chacune multipliée par son
    coefficient. Un écart (valeur moins calcul) dont la valeur absolue dépasse la
    tolérance est un écart; la valeur affichée donne la valeur, le calcul et
    l'écart. Une valeur vide ou illisible, dans la cible ou dans un terme, rend la
    ligne non évaluable.
    """
    cible = parametres["cible"]
    valeurs = lire(donnees[cible], natures[cible]).valeurs
    calcul = pd.Series(0.0, index=donnees.index)
    for colonne, coefficient in parametres["termes"].items():
        calcul = calcul + coefficient * lire(donnees[colonne], natures[colonne]).valeurs
    evaluables = (valeurs.notna() & calcul.notna()).astype(bool)
    differences = (valeurs - calcul).round(_DECIMALES_CALCUL)
    en_ecart = evaluables & (differences.abs() > parametres.get("tolerance", 0))
    constats = pd.Series(None, index=donnees.index, dtype=object)
    affichees = pd.Series(None, index=donnees.index, dtype=object)
    for position in donnees.index[en_ecart.to_numpy(dtype=bool)]:
        constats.loc[position] = CONSTAT_ECART_CALCUL
        affichees.loc[position] = (
            f"{_ecrire_nombre(valeurs.loc[position])} pour un calcul de "
            f"{_ecrire_nombre(calcul.loc[position])} (écart "
            f"{_ecrire_nombre(differences.loc[position])})"
        )
    return Constats(evaluables, _ecarts(constats, valeurs=affichees))


def _total_des_lignes(donnees, parametres, natures, liee: Liee) -> Constats:
    """Total de chaque ligne égal à la somme des lignes liées de même clé.

    Les lignes liées sont celles de la table liée qui ont la même clé (comparée
    telle quelle; une ligne liée à clé vide n'est rattachée à rien). Une ligne sans
    aucune ligne liée est un écart. Une clé vide ou répétée dans la table, un total
    vide ou illisible, ou un montant vide ou illisible parmi les lignes liées,
    rendent la ligne non évaluable. Un écart dont la valeur absolue dépasse la
    tolérance est un écart; la valeur affichée donne le total, la somme, le nombre
    de lignes liées et l'écart.
    """
    cle, colonne = parametres["cle"], parametres["colonne"]
    colonne_lignes = parametres["colonne_lignes"]
    totaux = lire(donnees[colonne], natures[colonne]).valeurs
    cles = _cles_lues(donnees, cle)
    montants = lire(liee.donnees[colonne_lignes], liee.natures[colonne_lignes]).valeurs
    sommes, nombres, illisibles = {}, {}, set()
    for cle_ligne, montant in zip(_cles_lues(liee.donnees, cle), montants):
        if cle_ligne is None:
            continue
        nombres[cle_ligne] = nombres.get(cle_ligne, 0) + 1
        if pd.isna(montant):
            illisibles.add(cle_ligne)
        else:
            sommes[cle_ligne] = sommes.get(cle_ligne, 0.0) + montant
    repetees = cles.notna() & cles.duplicated(keep=False)
    tolerance = parametres.get("tolerance", 0)

    evaluables = pd.Series(False, index=donnees.index, dtype=bool)
    constats = pd.Series(None, index=donnees.index, dtype=object)
    affichees = pd.Series(None, index=donnees.index, dtype=object)
    for position, cle_ligne, total, repetee in zip(donnees.index, cles, totaux, repetees):
        if cle_ligne is None or repetee:
            continue
        if cle_ligne not in nombres:
            evaluables.loc[position] = True
            constats.loc[position] = CONSTAT_SANS_LIGNE
            continue
        if pd.isna(total) or cle_ligne in illisibles:
            continue
        evaluables.loc[position] = True
        somme = sommes[cle_ligne]
        difference = round(total - somme, _DECIMALES_CALCUL)
        if abs(difference) > tolerance:
            constats.loc[position] = CONSTAT_TOTAL_DIFFERENT
            affichees.loc[position] = (
                f"{_ecrire_nombre(total)} pour une somme de {_ecrire_nombre(somme)} sur "
                + _pluriel(nombres[cle_ligne], "ligne liée", "lignes liées")
                + f" (écart {_ecrire_nombre(difference)})"
            )
    return Constats(evaluables, _ecarts(constats, valeurs=affichees))


def _equilibre_par_groupe(donnees, parametres, natures) -> Constats:
    """Somme de debit égale à la somme de credit dans chaque groupe de lignes.

    Un groupe réunit les lignes de même valeur dans les colonnes de `groupe`
    (comparées telles quelles). Chaque ligne d'un groupe dont l'écart (débit moins
    crédit) dépasse la tolérance en valeur absolue est un écart; la valeur affichée
    donne le groupe, ses totaux, l'écart et son nombre de lignes. Une ligne à
    groupe vide est non évaluable; un débit ou un crédit vide ou illisible rend
    toutes les lignes de son groupe non évaluables.
    """
    colonne_debit, colonne_credit = parametres["debit"], parametres["credit"]
    debits = lire(donnees[colonne_debit], natures[colonne_debit]).valeurs
    credits = lire(donnees[colonne_credit], natures[colonne_credit]).valeurs
    cles = _cles_lues(donnees, parametres["groupe"])
    groupes = {}
    for cle_ligne, debit, credit in zip(cles, debits, credits):
        if cle_ligne is None:
            continue
        groupe = groupes.setdefault(cle_ligne, {"debit": 0.0, "credit": 0.0, "lignes": 0,
                                                 "lisible": True})
        groupe["lignes"] += 1
        if pd.isna(debit) or pd.isna(credit):
            groupe["lisible"] = False
        else:
            groupe["debit"] += debit
            groupe["credit"] += credit
    tolerance = parametres.get("tolerance", 0)

    evaluables = pd.Series(False, index=donnees.index, dtype=bool)
    constats = pd.Series(None, index=donnees.index, dtype=object)
    affichees = pd.Series(None, index=donnees.index, dtype=object)
    for position, cle_ligne in zip(donnees.index, cles):
        if cle_ligne is None or not groupes[cle_ligne]["lisible"]:
            continue
        evaluables.loc[position] = True
        groupe = groupes[cle_ligne]
        difference = round(groupe["debit"] - groupe["credit"], _DECIMALES_CALCUL)
        if abs(difference) > tolerance:
            constats.loc[position] = CONSTAT_DESEQUILIBRE
            affichees.loc[position] = (
                f"{SEPARATEUR.join(cle_ligne)} : débit {_ecrire_nombre(groupe['debit'])}, "
                f"crédit {_ecrire_nombre(groupe['credit'])} (écart "
                f"{_ecrire_nombre(difference)}, "
                + _pluriel(groupe["lignes"], "ligne", "lignes")
                + ")"
            )
    return Constats(evaluables, _ecarts(constats, valeurs=affichees))


CONSTAT_ABSENTE = "absente de la table de référence"
CONSTAT_HORS_PERIODES = "date hors des périodes de la table de référence"
CONSTAT_PERIODE_NON_COUVERTE = "début de période non couvert par un palier"
CONSTAT_ANNEE_ABSENTE = "année absente de la table de référence"
# Raisons pour lesquelles une ligne d'un référentiel est inutilisable, dans l'ordre
# où elles sont cherchées (une ligne n'est comptée que sous la première).
RAISONS_PERIODE = ("clé vide", "début vide", "début illisible", "fin illisible",
                   "début après fin")
RAISONS_PALIER = ("clé vide", "date vide", "date illisible")
RAISONS_ANNEE = ("année vide", "année illisible")


def _cles_comparees(
    donnees: pd.DataFrame, colonnes: list[str], comparaison: str = COMPARAISON_TELLE_QUELLE
) -> pd.Series:
    """Clé de chaque ligne : textes de ses colonnes reliés par une espace, sous la forme
    où ils sont comparés; None si l'une des colonnes est vide ou faite d'espaces."""

    def cle(ligne):
        textes = [_valeur_constatee(valeur) for valeur in ligne]
        if any(texte is None or not texte.strip() for texte in textes):
            return None
        return _comparable(" ".join(textes), comparaison)

    return pd.Series(
        [cle(ligne) for ligne in donnees[colonnes].itertuples(index=False)],
        index=donnees.index,
        dtype=object,
    )


def _hors_champ_cle(cles: pd.Series, parametres: dict) -> pd.Series:
    """Lignes à clé vide, hors champ quand la clé est déclarée facultative."""
    if parametres.get("cle_facultative"):
        return cles.isna().astype(bool)
    return pd.Series(False, index=cles.index, dtype=bool)


def _jour(date: pd.Timestamp) -> str:
    return f"{date:%d/%m/%Y}"


def _inutilisables(table: str, raisons: dict) -> list[str]:
    """Avertissement sur les lignes inutilisables d'un référentiel, par raison."""
    total = sum(raisons.values())
    if not total:
        return []
    detail = ", ".join(f"{raison} {nombre}" for raison, nombre in raisons.items() if nombre)
    return [
        _pluriel(
            total,
            f"ligne de la table {table} inutilisable",
            f"lignes de la table {table} inutilisables",
        )
        + f" : {detail}"
    ]


def _lire_dates(donnees: pd.DataFrame, colonne: str | None, nature: str | None):
    """Dates lues (ramenées à minuit) et états d'une colonne; sans colonne, des dates
    vides."""
    if colonne is None:
        return (
            pd.Series(pd.NaT, index=donnees.index, dtype="datetime64[ns]"),
            pd.Series(ETAT_VIDE, index=donnees.index, dtype=object),
        )
    lecture = lire(donnees[colonne], nature)
    return lecture.valeurs.dt.normalize(), lecture.etats


def _existence_dans_reference(donnees, parametres, natures, liee: Liee) -> Constats:
    """Clé de chaque ligne présente dans la table de référence.

    Les clés sont comparées selon `comparaison`. Une clé vide rend la ligne non
    évaluable, ou hors champ si la clé est facultative.
    """
    comparaison = parametres.get("comparaison", COMPARAISON_TELLE_QUELLE)
    cles = _cles_comparees(donnees, parametres["cle"], comparaison)
    connues = set(_cles_comparees(liee.donnees, parametres["cle_reference"], comparaison).dropna())
    constats = cles.map(lambda cle: None if cle is None or cle in connues else CONSTAT_ABSENTE)
    return Constats(
        cles.notna().astype(bool),
        _ecarts(constats.astype(object)),
        hors_champ=_hors_champ_cle(cles, parametres),
    )


def _ecrire_periodes(periodes: list) -> str:
    """Périodes écrites « périodes du 01/01/2018 au 31/12/2023 et depuis le 01/05/2024 »."""
    textes = [
        f"depuis le {_jour(debut)}" if pd.isna(fin) else f"du {_jour(debut)} au {_jour(fin)}"
        for debut, fin in sorted(periodes, key=lambda periode: periode[0])
    ]
    return ("période " if len(textes) == 1 else "périodes ") + " et ".join(textes)


def _date_dans_periode_reference(donnees, parametres, natures, liee: Liee) -> Constats:
    """Date de chaque ligne dans l'une des périodes de sa clé dans la table de référence.

    Une clé peut avoir plusieurs périodes (lignes du référentiel); une période va de
    `debut` à `fin`, bornes incluses, et une fin vide (ou l'absence de `fin`) la laisse
    ouverte. Une ligne du référentiel au début vide ou illisible, à la fin illisible,
    ou au début postérieur à la fin, est inutilisable (avertissement au bilan). Une clé
    absente du référentiel est un écart; une date hors des périodes utilisables est un
    autre écart, sauf si la clé a une période inutilisable (ligne non évaluable). Une
    clé vide rend la ligne non évaluable, ou hors champ si la clé est facultative; une
    date vide ou illisible la rend non évaluable.
    """
    comparaison = parametres.get("comparaison", COMPARAISON_TELLE_QUELLE)
    cles = _cles_comparees(donnees, parametres["cle"], comparaison)
    colonne_date = parametres["date"]
    dates, _ = _lire_dates(donnees, colonne_date, natures[colonne_date])
    reference = _cles_comparees(liee.donnees, parametres["cle_reference"], comparaison)
    debut, fin = parametres["debut"], parametres.get("fin")
    debuts, etats_debut = _lire_dates(liee.donnees, debut, liee.natures[debut])
    fins, etats_fin = _lire_dates(liee.donnees, fin, liee.natures.get(fin))
    raisons = dict.fromkeys(RAISONS_PERIODE, 0)
    periodes, inutilisables = {}, set()
    for position, cle in reference.items():
        raison = None
        if cle is None:
            raison = "clé vide"
        elif etats_debut.loc[position] == ETAT_VIDE:
            raison = "début vide"
        elif etats_debut.loc[position] == ETAT_ILLISIBLE:
            raison = "début illisible"
        elif etats_fin.loc[position] == ETAT_ILLISIBLE:
            raison = "fin illisible"
        elif pd.notna(fins.loc[position]) and debuts.loc[position] > fins.loc[position]:
            raison = "début après fin"
        if raison is not None:
            raisons[raison] += 1
            if cle is not None:
                inutilisables.add(cle)
            continue
        periodes.setdefault(cle, []).append((debuts.loc[position], fins.loc[position]))

    evaluables = pd.Series(False, index=donnees.index, dtype=bool)
    constats = pd.Series(None, index=donnees.index, dtype=object)
    affichees = pd.Series(None, index=donnees.index, dtype=object)
    for position, cle, date in zip(donnees.index, cles, dates):
        if cle is None or pd.isna(date):
            continue
        if cle not in periodes and cle not in inutilisables:
            evaluables.loc[position] = True
            constats.loc[position] = CONSTAT_ABSENTE
            continue
        liste = periodes.get(cle, [])
        if any(debut <= date and (pd.isna(fin) or date <= fin) for debut, fin in liste):
            evaluables.loc[position] = True
            continue
        if cle in inutilisables:
            continue
        evaluables.loc[position] = True
        constats.loc[position] = CONSTAT_HORS_PERIODES
        affichees.loc[position] = f"{_jour(date)} ({_ecrire_periodes(liste)})"
    return Constats(
        evaluables,
        _ecarts(constats, valeurs=affichees),
        tuple(_inutilisables(liee.table, raisons)),
        hors_champ=_hors_champ_cle(cles, parametres),
    )


def _periodes_couvertes_par_paliers(donnees, parametres, natures, liee: Liee) -> Constats:
    """Début de chaque période couvert par un palier de même clé.

    Un palier (ligne de la table liée, par exemple une rémunération) vaut de sa date
    jusqu'au palier suivant de la même clé; seul le début d'une période peut donc
    être découvert. Une période est couverte si un palier de sa clé est daté au plus
    tard à son début et après la fin de la période précédente de la même clé (un
    palier d'une période antérieure ne couvre pas la suivante). La valeur affichée
    donne le début de la période et la date du premier palier qui le suit.

    Non évaluable : clé vide, début vide ou illisible, autre période de la même clé
    au début vide ou illisible, période précédente à la fin illisible, ou palier de
    la clé à la date vide ou illisible quand aucun palier lisible ne couvre la
    période. Les paliers inutilisables sont signalés au bilan.
    """
    cles = _cles_comparees(donnees, parametres["cle"])
    debut, fin = parametres["debut"], parametres.get("fin")
    debuts, etats_debut = _lire_dates(donnees, debut, natures[debut])
    fins, etats_fin = _lire_dates(donnees, fin, natures.get(fin))
    colonne_palier = parametres["date_palier"]
    dates_paliers, etats_paliers = _lire_dates(
        liee.donnees, colonne_palier, liee.natures[colonne_palier]
    )
    raisons = dict.fromkeys(RAISONS_PALIER, 0)
    paliers, illisibles = {}, set()
    for position, cle in _cles_comparees(liee.donnees, parametres["cle_paliers"]).items():
        if cle is None:
            raisons["clé vide"] += 1
        elif etats_paliers.loc[position] == ETAT_LUE:
            paliers.setdefault(cle, []).append(dates_paliers.loc[position])
        else:
            raisons["date vide" if etats_paliers.loc[position] == ETAT_VIDE
                    else "date illisible"] += 1
            illisibles.add(cle)
    par_cle = {}
    for position, cle in cles.items():
        if cle is not None:
            par_cle.setdefault(cle, []).append(position)

    evaluables = pd.Series(False, index=donnees.index, dtype=bool)
    constats = pd.Series(None, index=donnees.index, dtype=object)
    affichees = pd.Series(None, index=donnees.index, dtype=object)
    for position, cle in cles.items():
        if cle is None or etats_debut.loc[position] != ETAT_LUE:
            continue
        depart = debuts.loc[position]
        autres = [p for p in par_cle[cle] if p != position]
        if any(etats_debut.loc[p] != ETAT_LUE for p in autres):
            continue
        precedentes = [p for p in autres if debuts.loc[p] < depart]
        borne = pd.NaT
        if precedentes:
            precedente = max(precedentes, key=lambda p: debuts.loc[p])
            if etats_fin.loc[precedente] == ETAT_ILLISIBLE:
                continue
            borne = fins.loc[precedente]
        dates = paliers.get(cle, [])
        if any(date <= depart and (pd.isna(borne) or date > borne) for date in dates):
            evaluables.loc[position] = True
            continue
        if cle in illisibles:
            continue
        evaluables.loc[position] = True
        constats.loc[position] = CONSTAT_PERIODE_NON_COUVERTE
        suivants = [date for date in dates if date > depart]
        affichees.loc[position] = f"période du {_jour(depart)}, " + (
            f"premier palier le {_jour(min(suivants))}" if suivants else "aucun palier ensuite"
        )
    return Constats(
        evaluables,
        _ecarts(constats, valeurs=affichees),
        tuple(_inutilisables(liee.table, raisons)),
    )


def _annee_dans_reference(donnees, parametres, natures, liee: Liee) -> Constats:
    """Année de la date de chaque ligne déclarée dans la table de référence.

    Une date vide ou illisible rend la ligne non évaluable. Les années absentes sont
    aussi signalées au bilan, avec leur nombre de lignes, ainsi que les lignes du
    référentiel dont l'année est vide, illisible ou n'est pas un entier.
    """
    colonne = parametres["date"]
    dates, _ = _lire_dates(donnees, colonne, natures[colonne])
    colonne_annee = parametres["colonne_annee"]
    lecture = lire(liee.donnees[colonne_annee], liee.natures[colonne_annee])
    raisons = dict.fromkeys(RAISONS_ANNEE, 0)
    connues = set()
    for valeur, etat in zip(lecture.valeurs, lecture.etats):
        if etat == ETAT_VIDE:
            raisons["année vide"] += 1
        elif etat == ETAT_ILLISIBLE or not float(valeur).is_integer():
            raisons["année illisible"] += 1
        else:
            connues.add(int(valeur))
    constats = pd.Series(None, index=donnees.index, dtype=object)
    affichees = pd.Series(None, index=donnees.index, dtype=object)
    absentes = {}
    for position, date in dates.items():
        if pd.isna(date) or date.year in connues:
            continue
        constats.loc[position] = CONSTAT_ANNEE_ABSENTE
        affichees.loc[position] = (
            f"{_valeur_constatee(donnees.at[position, colonne])} (année {date.year})"
        )
        absentes[date.year] = absentes.get(date.year, 0) + 1
    avertissements = _inutilisables(liee.table, raisons) + [
        f"année {annee} absente de {liee.table}.{colonne_annee} : "
        + _pluriel(nombre, "ligne", "lignes")
        for annee, nombre in sorted(absentes.items())
    ]
    return Constats(
        dates.notna().astype(bool), _ecarts(constats, valeurs=affichees), tuple(avertissements)
    )


CONSTAT_SANS_DOCUMENT = "aucun document rattaché"
CONSTAT_DELAI_NON_ECHU = "aucun document rattaché, délai non échu à la date de coupure"
CONSTAT_PLUSIEURS_DOCUMENTS = "rattachée à plusieurs documents"
CONSTAT_HORS_DELAI = "document hors du délai"
CONSTAT_NON_CONFORME = "référence non conforme"
CONSTAT_VALEURS_DIFFERENTES = "valeurs différentes entre les deux références"
CONSTAT_LIGNES_INATTENDUES = "lignes liées alors qu'aucune n'est attendue"


def _index_unique(cles: pd.Series) -> tuple[dict, set]:
    """Position de chaque clé présente une seule fois, et ensemble des clés répétées
    (les clés vides sont ignorées)."""
    comptes = cles.dropna().value_counts()
    repetees = set(comptes.index[comptes > 1])
    index = {
        cle: position
        for position, cle in cles.items()
        if cle is not None and cle not in repetees
    }
    return index, repetees


def _pratique(exceptions, donnees: pd.DataFrame, position, cibles: dict) -> str | None:
    """Libellé de la première exception dont toutes les conditions sont remplies.

    Une colonne sans préfixe est lue sur la ligne de la règle; une colonne « t.c » sur
    les lignes de la table liée t que donne `cibles` (table vers vue et positions),
    qui doivent toutes remplir la condition (et être au moins une).
    """
    for exception in exceptions or []:
        remplie = True
        for condition in exception["conditions"]:
            table, colonne = _colonne_qualifiee(condition["colonne"], None, cibles)
            if table is None:
                textes = [_texte_lu(donnees.at[position, colonne])]
            else:
                vue, positions = cibles[table]
                textes = [_texte_lu(vue.at[p, colonne]) for p in positions]
            if not textes or not all(_condition_vraie(texte, condition) for texte in textes):
                remplie = False
                break
        if remplie:
            return exception["libelle"]
    return None


def _rattachement_unique_dans_delai(donnees, parametres, natures, liees) -> Constats:
    """Chaque ligne est rattachée à un document et un seul, daté dans le délai.

    Les lignes de table_lignes (celles qui remplissent filtre_lignes) de même clé
    désignent les documents (colonnes de document), retrouvés dans table_documents.
    Aucun document est un écart, qui devient une information quand le délai n'est pas
    échu à la date de coupure (date de la ligne plus delai_max après la coupure).
    Plusieurs documents sont un écart. Un seul document daté hors de delai_min à
    delai_max jours après la date de la ligne est un écart.

    Non évaluable : clé vide ou répétée (dans toute la table, filtre compris, car les
    lignes liées désignent la clé et non l'une de ses lignes), date vide ou illisible,
    ligne liée sans document, document absent de table_documents ou de clé répétée,
    date du document vide ou illisible.
    """
    lignes, documents = liees["table_lignes"], liees["table_documents"]
    cles = _cles_comparees(donnees, parametres["cle"])
    _, repetees = _index_unique(
        _cles_comparees(parametres[CONTEXTE_VUE_COMPLETE], parametres["cle"])
    )
    colonne_date = parametres["date"]
    dates, etats = _lire_dates(donnees, colonne_date, natures[colonne_date])
    vue_lignes = lignes.donnees[_dans_le_champ(lignes.donnees, parametres.get("filtre_lignes"))]
    rattaches = {}
    for cle, document in zip(
        _cles_comparees(vue_lignes, parametres["cle_lignes"]),
        _cles_comparees(vue_lignes, parametres["document"]),
    ):
        if cle is not None:
            rattaches.setdefault(cle, set()).add(document)
    index_documents, documents_repetes = _index_unique(
        _cles_comparees(documents.donnees, parametres["cle_documents"])
    )
    colonne_document = parametres["date_document"]
    dates_documents, etats_documents = _lire_dates(
        documents.donnees, colonne_document, documents.natures[colonne_document]
    )
    mini, maxi = parametres["delai_min"], parametres["delai_max"]
    coupure = pd.Timestamp(parametres[CONTEXTE_DATE_COUPURE]).normalize()

    evaluables = pd.Series(False, index=donnees.index, dtype=bool)
    constats = pd.Series(None, index=donnees.index, dtype=object)
    affichees = pd.Series(None, index=donnees.index, dtype=object)
    issues = pd.Series(None, index=donnees.index, dtype=object)
    for position, cle in cles.items():
        if cle is None or cle in repetees or etats.loc[position] != ETAT_LUE:
            continue
        date = dates.loc[position]
        rattaches_ligne = rattaches.get(cle, set())
        if None in rattaches_ligne:
            continue
        if not rattaches_ligne:
            evaluables.loc[position] = True
            limite = date + pd.Timedelta(days=maxi)
            if limite > coupure:
                constats.loc[position] = CONSTAT_DELAI_NON_ECHU
                issues.loc[position] = ISSUE_INFORMATION
                affichees.loc[position] = (
                    f"{_jour(date)} (délai jusqu'au {_jour(limite)}, coupure au "
                    f"{_jour(coupure)})"
                )
            else:
                constats.loc[position] = CONSTAT_SANS_DOCUMENT
            continue
        if len(rattaches_ligne) > 1:
            evaluables.loc[position] = True
            constats.loc[position] = CONSTAT_PLUSIEURS_DOCUMENTS
            affichees.loc[position] = (
                f"{_jour(date)}, {len(rattaches_ligne)} documents : "
                + SEPARATEUR.join(sorted(rattaches_ligne))
            )
            continue
        (document,) = rattaches_ligne
        if document in documents_repetes or document not in index_documents:
            continue
        rang = index_documents[document]
        if etats_documents.loc[rang] != ETAT_LUE:
            continue
        evaluables.loc[position] = True
        date_document = dates_documents.loc[rang]
        delai = (date_document - date).days
        if not mini <= delai <= maxi:
            constats.loc[position] = CONSTAT_HORS_DELAI
            affichees.loc[position] = (
                f"{_jour(date)}, document {document} du {_jour(date_document)} (écart de "
                + _pluriel(delai, "jour", "jours")
                + ")"
            )
    return Constats(evaluables, _ecarts(constats, valeurs=affichees, issues=issues))


def _reference_conforme(donnees, parametres, natures, liee: Liee) -> Constats:
    """La ligne de référence de chaque ligne remplit les conditions attendues.

    La référence est la ligne de table_reference de même clé. Un écart qui remplit
    une exception devient une information, son constat nommant la pratique.

    Non évaluable : clé vide (hors champ si cle_facultative vaut true), référence
    absente (l'existence relève de existence_dans_reference) ou de clé répétée,
    valeur vide d'une colonne des conditions dans la référence.
    """
    cles = _cles_comparees(donnees, parametres["cle"])
    index, repetees = _index_unique(_cles_comparees(liee.donnees, parametres["cle_reference"]))
    attendu = parametres["attendu"]
    exceptions = parametres.get("exceptions")

    evaluables = pd.Series(False, index=donnees.index, dtype=bool)
    constats = pd.Series(None, index=donnees.index, dtype=object)
    affichees = pd.Series(None, index=donnees.index, dtype=object)
    issues = pd.Series(None, index=donnees.index, dtype=object)
    for position, cle in cles.items():
        if cle is None or cle in repetees or cle not in index:
            continue
        reference = index[cle]
        textes = [_texte_lu(liee.donnees.at[reference, c["colonne"]]) for c in attendu]
        if any(texte is None for texte in textes):
            continue
        evaluables.loc[position] = True
        echecs = [
            f"{liee.table}.{condition['colonne']} = {texte}"
            for condition, texte in zip(attendu, textes)
            if not _condition_vraie(texte, condition)
        ]
        if not echecs:
            continue
        affichees.loc[position] = ", ".join(echecs)
        libelle = _pratique(
            exceptions, donnees, position, {liee.table: (liee.donnees, [reference])}
        )
        if libelle is None:
            constats.loc[position] = CONSTAT_NON_CONFORME
        else:
            constats.loc[position] = PREFIXE_PRATIQUE + libelle
            issues.loc[position] = ISSUE_INFORMATION
    return Constats(
        evaluables,
        _ecarts(constats, valeurs=affichees, issues=issues),
        hors_champ=_hors_champ_cle(cles, parametres),
    )


def _concordance_entre_references(donnees, parametres, natures, liees) -> Constats:
    """Les deux références d'une ligne portent la même valeur.

    Pour chacune des deux tables liées (a et b), la référence est la ligne de même
    clé; colonne_a de la référence a doit égaler colonne_b de la référence b, selon
    la comparaison (telle quelle par défaut).

    Non évaluable : clé vide, référence absente ou de clé répétée, valeur vide.
    """
    comparaison = parametres.get("comparaison", COMPARAISON_TELLE_QUELLE)
    lues = []
    for suffixe in ("a", "b"):
        liee = liees[f"table_{suffixe}"]
        cles = _cles_comparees(donnees, parametres[f"cle_{suffixe}"])
        index, repetees = _index_unique(
            _cles_comparees(liee.donnees, parametres[f"cle_reference_{suffixe}"])
        )
        colonne = parametres[f"colonne_{suffixe}"]
        valeurs = pd.Series(None, index=donnees.index, dtype=object)
        for position, cle in cles.items():
            if cle is not None and cle not in repetees and cle in index:
                valeurs.loc[position] = _texte_lu(liee.donnees.at[index[cle], colonne])
        lues.append((f"{liee.table}.{colonne}", valeurs))
    (nom_a, valeurs_a), (nom_b, valeurs_b) = lues
    evaluables = (valeurs_a.notna() & valeurs_b.notna()).astype(bool)
    constats = pd.Series(None, index=donnees.index, dtype=object)
    affichees = pd.Series(None, index=donnees.index, dtype=object)
    for position in donnees.index[evaluables]:
        a, b = valeurs_a.loc[position], valeurs_b.loc[position]
        if _comparable(a, comparaison) != _comparable(b, comparaison):
            constats.loc[position] = CONSTAT_VALEURS_DIFFERENTES
            affichees.loc[position] = f"{a} ({nom_a}) | {b} ({nom_b})"
    return Constats(evaluables, _ecarts(constats, valeurs=affichees))


def _sans_ligne_liee(donnees, parametres, natures, liee: Liee) -> Constats:
    """Aucune ligne de table_lignes (celles qui remplissent filtre_lignes) ne porte la
    clé de la ligne.

    Un écart qui remplit une exception devient une information; une condition sur
    une colonne « table_lignes.c » doit être remplie par toutes les lignes liées.

    Non évaluable : clé vide ou répétée (dans toute la table, filtre compris).
    """
    cles = _cles_comparees(donnees, parametres["cle"])
    _, repetees = _index_unique(
        _cles_comparees(parametres[CONTEXTE_VUE_COMPLETE], parametres["cle"])
    )
    vue_lignes = liee.donnees[_dans_le_champ(liee.donnees, parametres.get("filtre_lignes"))]
    par_cle = {}
    for position, cle in _cles_comparees(vue_lignes, parametres["cle_lignes"]).items():
        if cle is not None:
            par_cle.setdefault(cle, []).append(position)
    exceptions = parametres.get("exceptions")

    evaluables = pd.Series(False, index=donnees.index, dtype=bool)
    constats = pd.Series(None, index=donnees.index, dtype=object)
    affichees = pd.Series(None, index=donnees.index, dtype=object)
    issues = pd.Series(None, index=donnees.index, dtype=object)
    for position, cle in cles.items():
        if cle is None or cle in repetees:
            continue
        evaluables.loc[position] = True
        positions = par_cle.get(cle, [])
        if not positions:
            continue
        affichees.loc[position] = _pluriel(
            len(positions), f"ligne liée dans {liee.table}", f"lignes liées dans {liee.table}"
        )
        libelle = _pratique(exceptions, donnees, position, {liee.table: (vue_lignes, positions)})
        if libelle is None:
            constats.loc[position] = CONSTAT_LIGNES_INATTENDUES
        else:
            constats.loc[position] = PREFIXE_PRATIQUE + libelle
            issues.loc[position] = ISSUE_INFORMATION
    return Constats(evaluables, _ecarts(constats, valeurs=affichees, issues=issues))


CONSTAT_AUCUNE_LIGNE_CONFORME = "aucune ligne liée ne remplit les conditions attendues"
CONSTAT_NON_CONFORME_DANS_HORAIRES = "non conforme dans les horaires"
CONSTAT_NON_CONFORME_HORS_HORAIRES = "non conforme hors horaires"
CONSTAT_QUANTITES_DIFFERENTES = "quantités différentes entre les deux tables liées"


def _ligne_liee_attendue(donnees, parametres, natures, liee: Liee) -> Constats:
    """Au moins une ligne de table_lignes (parmi celles qui remplissent filtre_lignes)
    de même clé remplit toutes les conditions de attendu.

    Une ligne sans aucune ligne liée retenue est hors champ (l'absence de lignes liées
    relève d'une autre règle, par exemple sans_ligne_liee ou un rattachement). La
    valeur affichée donne, pour chaque colonne de attendu, les valeurs des lignes
    liées. Un écart qui remplit une exception devient une information; une condition
    sur une colonne « table_lignes.c » doit être remplie par toutes les lignes liées.

    Non évaluable : clé vide ou répétée (dans toute la table, filtre compris), ou,
    quand aucune ligne liée ne remplit les conditions, valeur vide d'une colonne de
    attendu dans l'une d'elles (elle aurait pu les remplir).
    """
    cles = _cles_comparees(donnees, parametres["cle"])
    _, repetees = _index_unique(
        _cles_comparees(parametres[CONTEXTE_VUE_COMPLETE], parametres["cle"])
    )
    vue_lignes = liee.donnees[_dans_le_champ(liee.donnees, parametres.get("filtre_lignes"))]
    par_cle = {}
    for position, cle in _cles_comparees(vue_lignes, parametres["cle_lignes"]).items():
        if cle is not None:
            par_cle.setdefault(cle, []).append(position)
    attendu = parametres["attendu"]
    exceptions = parametres.get("exceptions")

    evaluables = pd.Series(False, index=donnees.index, dtype=bool)
    hors_champ = pd.Series(False, index=donnees.index, dtype=bool)
    constats = pd.Series(None, index=donnees.index, dtype=object)
    affichees = pd.Series(None, index=donnees.index, dtype=object)
    issues = pd.Series(None, index=donnees.index, dtype=object)
    for position, cle in cles.items():
        if cle is None or cle in repetees:
            continue
        positions = par_cle.get(cle, [])
        if not positions:
            hors_champ.loc[position] = True
            continue
        textes = [
            [_texte_lu(vue_lignes.at[p, condition["colonne"]]) for condition in attendu]
            for p in positions
        ]
        if any(
            all(_condition_vraie(texte, condition) for texte, condition in zip(ligne, attendu))
            for ligne in textes
        ):
            evaluables.loc[position] = True
            continue
        if any(texte is None for ligne in textes for texte in ligne):
            continue
        evaluables.loc[position] = True
        affichees.loc[position] = "; ".join(
            f"{liee.table}.{condition['colonne']} = "
            + ", ".join(sorted({ligne[rang] for ligne in textes}))
            for rang, condition in enumerate(attendu)
        )
        libelle = _pratique(exceptions, donnees, position, {liee.table: (vue_lignes, positions)})
        if libelle is None:
            constats.loc[position] = CONSTAT_AUCUNE_LIGNE_CONFORME
        else:
            constats.loc[position] = PREFIXE_PRATIQUE + libelle
            issues.loc[position] = ISSUE_INFORMATION
    return Constats(
        evaluables,
        _ecarts(constats, valeurs=affichees, issues=issues),
        hors_champ=hors_champ,
    )


def _conforme_selon_horaires(donnees, parametres, natures, liee: Liee) -> Constats:
    """Chaque ligne remplit les conditions de dans_horaires ou de hors_horaires, selon
    la date et l'heure de sa référence face aux horaires.

    La référence est la ligne de table_reference de même clé; sa date et son heure
    sont situées comme pour hors_horaires_selon_valeur (jour férié de feries, sinon
    jour de la semaine; créneaux de ce jour, début inclus, fin exclue). Une liste de
    conditions absente n'impose rien. Les conditions portent sur la ligne elle-même.
    La valeur affichée donne les conditions en échec et le moment de la référence.

    Non évaluable : clé vide, référence absente ou de clé répétée, date ou heure vide
    ou illisible, année sans jours fériés déclarés, valeur vide d'une colonne des
    conditions à remplir. Avertissements comme pour hors_horaires_selon_valeur, sur
    les dates des références des lignes.
    """
    cles = _cles_comparees(donnees, parametres["cle"])
    index, repetees = _index_unique(_cles_comparees(liee.donnees, parametres["cle_reference"]))
    colonne_date, colonne_heure = parametres["date"], parametres["heure"]
    dates = lire(liee.donnees[colonne_date], liee.natures[colonne_date]).valeurs
    heures = lire(liee.donnees[colonne_heure], liee.natures[colonne_heure]).valeurs
    feries, creneaux = _lire_horaires(parametres)

    evaluables = pd.Series(False, index=donnees.index, dtype=bool)
    constats = pd.Series(None, index=donnees.index, dtype=object)
    affichees = pd.Series(None, index=donnees.index, dtype=object)
    dates_lignes = pd.Series(pd.NaT, index=donnees.index, dtype="datetime64[ns]")
    for position, cle in cles.items():
        if cle is None or cle in repetees or cle not in index:
            continue
        reference = index[cle]
        dates_lignes.loc[position] = dates.loc[reference]
        situation = _situer(dates.loc[reference], heures.loc[reference], feries, creneaux)
        if situation is None:
            continue
        moment, dans = situation
        conditions = parametres.get("dans_horaires" if dans else "hors_horaires") or []
        textes = [_texte_lu(donnees.at[position, c["colonne"]]) for c in conditions]
        if any(texte is None for texte in textes):
            continue
        evaluables.loc[position] = True
        echecs = [
            f"{condition['colonne']} = {texte}"
            for condition, texte in zip(conditions, textes)
            if not _condition_vraie(texte, condition)
        ]
        if echecs:
            constats.loc[position] = (
                CONSTAT_NON_CONFORME_DANS_HORAIRES if dans else CONSTAT_NON_CONFORME_HORS_HORAIRES
            )
            affichees.loc[position] = f"{', '.join(echecs)}{SEPARATEUR}{moment}"
    avertissements = _avertissements_feries(
        dates_lignes, feries, parametres.get("feries_minimum")
    )
    return Constats(evaluables, _ecarts(constats, valeurs=affichees), tuple(avertissements))


def _quantites_concordantes(donnees, parametres, natures, liees) -> Constats:
    """Les quantités des lignes liées de table_a et de table_b concordent, détail par
    détail (par exemple les pièces posées sur une intervention et les pièces facturées).

    Pour chaque table liée, les lignes de même clé qui remplissent son filtre sont
    regroupées par valeur de la colonne de détail (comparée telle quelle), et leurs
    quantités additionnées; un détail absent d'une table y vaut 0. Un écart entre les
    deux sommes d'un même détail au-delà de la tolérance est un écart, un seul par
    ligne; la valeur affichée donne chaque détail en écart et ses deux sommes.

    Hors champ, si hors_champ_sans_b vaut true : ligne sans aucune ligne dans table_b
    (avant filtre_b). Non évaluable : clé vide ou répétée (dans toute la table, filtre
    compris), ligne liée retenue au détail vide ou à la quantité vide ou illisible.
    """
    cles = _cles_comparees(donnees, parametres["cle"])
    _, repetees = _index_unique(
        _cles_comparees(parametres[CONTEXTE_VUE_COMPLETE], parametres["cle"])
    )
    sommes, illisibles, noms = [], [], []
    presentes_b = set()
    for suffixe in ("a", "b"):
        liee = liees[f"table_{suffixe}"]
        if suffixe == "b":
            presentes_b = set(_cles_comparees(liee.donnees, parametres["cle_b"]).dropna())
        vue = liee.donnees[_dans_le_champ(liee.donnees, parametres.get(f"filtre_{suffixe}"))]
        colonne_quantite = parametres[f"quantite_{suffixe}"]
        quantites = lire(vue[colonne_quantite], liee.natures[colonne_quantite]).valeurs
        details = [_texte_lu(valeur) for valeur in vue[parametres[f"detail_{suffixe}"]]]
        par_cle, mauvaises = {}, set()
        for cle, detail, quantite in zip(
            _cles_comparees(vue, parametres[f"cle_{suffixe}"]), details, quantites
        ):
            if cle is None:
                continue
            if detail is None or pd.isna(quantite):
                mauvaises.add(cle)
                continue
            par_detail = par_cle.setdefault(cle, {})
            par_detail[detail] = par_detail.get(detail, 0.0) + quantite
        sommes.append(par_cle)
        illisibles.append(mauvaises)
        noms.append(liee.table)
    tolerance = parametres.get("tolerance", 0)
    sans_b = parametres.get("hors_champ_sans_b", False)

    evaluables = pd.Series(False, index=donnees.index, dtype=bool)
    hors_champ = pd.Series(False, index=donnees.index, dtype=bool)
    constats = pd.Series(None, index=donnees.index, dtype=object)
    affichees = pd.Series(None, index=donnees.index, dtype=object)
    for position, cle in cles.items():
        if cle is None or cle in repetees:
            continue
        if sans_b and cle not in presentes_b:
            hors_champ.loc[position] = True
            continue
        if cle in illisibles[0] or cle in illisibles[1]:
            continue
        evaluables.loc[position] = True
        a, b = sommes[0].get(cle, {}), sommes[1].get(cle, {})
        en_ecart = [
            detail
            for detail in sorted(set(a) | set(b))
            if abs(round(a.get(detail, 0.0) - b.get(detail, 0.0), _DECIMALES_CALCUL))
            > tolerance
        ]
        if en_ecart:
            constats.loc[position] = CONSTAT_QUANTITES_DIFFERENTES
            affichees.loc[position] = "; ".join(
                f"{detail} : {_ecrire_nombre(a.get(detail, 0.0))} dans {noms[0]}, "
                f"{_ecrire_nombre(b.get(detail, 0.0))} dans {noms[1]}"
                for detail in en_ecart
            )
    return Constats(evaluables, _ecarts(constats, valeurs=affichees), hors_champ=hors_champ)


CONSTAT_SOMME_DIFFERENTE = "somme des lignes liées différente de la valeur attendue"
CONSTAT_PLUSIEURS_NON_NULLES = "plusieurs valeurs non nulles"
CONSTAT_AUCUNE_NON_NULLE = "aucune valeur non nulle"


def _facteur(element) -> dict:
    """Facteur complet : colonne, coefficient (1 par défaut), constante (0 par défaut) et
    valeur d'une cellule vide (None par défaut : la ligne est non évaluable)."""
    if isinstance(element, str):
        element = {"colonne": element}
    return {
        "colonne": element["colonne"],
        "coefficient": element.get("coefficient", 1),
        "constante": element.get("constante", 0),
        "vide": element.get("vide"),
    }


def _produit_calcule(donnees, parametres, natures) -> Constats:
    """Valeur d'une colonne égale, à la tolérance près, au produit de facteurs lus sur la
    même ligne.

    Chaque facteur vaut constante + coefficient × valeur de sa colonne; une cellule
    vide prend la valeur `vide` du facteur quand elle est déclarée. Par exemple un
    montant égal à quantite × prix × (1 - 0,01 × remise), la remise vide valant 0. Un
    écart (valeur moins produit) dont la valeur absolue dépasse la tolérance est un
    écart; la valeur affichée donne la valeur, le calcul et l'écart, comme pour
    egalite_calculee. Une cible vide ou illisible, un facteur illisible, ou un facteur
    vide sans valeur `vide`, rendent la ligne non évaluable.
    """
    cible = parametres["cible"]
    valeurs = lire(donnees[cible], natures[cible]).valeurs
    calcul = pd.Series(1.0, index=donnees.index)
    for element in parametres["facteurs"]:
        facteur = _facteur(element)
        lecture = lire(donnees[facteur["colonne"]], natures[facteur["colonne"]])
        lues = lecture.valeurs
        if facteur["vide"] is not None:
            lues = lues.where((lecture.etats != ETAT_VIDE).to_numpy(), float(facteur["vide"]))
        calcul = calcul * (facteur["constante"] + facteur["coefficient"] * lues)
    evaluables = (valeurs.notna() & calcul.notna()).astype(bool)
    differences = (valeurs - calcul).round(_DECIMALES_CALCUL)
    en_ecart = evaluables & (differences.abs() > parametres.get("tolerance", 0))
    constats = pd.Series(None, index=donnees.index, dtype=object)
    affichees = pd.Series(None, index=donnees.index, dtype=object)
    for position in donnees.index[en_ecart.to_numpy(dtype=bool)]:
        constats.loc[position] = CONSTAT_ECART_CALCUL
        affichees.loc[position] = (
            f"{_ecrire_nombre(valeurs.loc[position])} pour un calcul de "
            f"{_ecrire_nombre(calcul.loc[position])} (écart "
            f"{_ecrire_nombre(differences.loc[position])})"
        )
    return Constats(evaluables, _ecarts(constats, valeurs=affichees))


def _arrondir(valeur: float, pas: float, sens: str) -> float:
    """Valeur arrondie à un multiple du pas, dans le sens demandé (voir `ARRONDIS`).

    Le quotient est d'abord arrondi à 9 décimales, pour qu'une erreur de calcul en
    virgule flottante ne fasse pas passer au multiple suivant (75 / 60 / 0,25 vaut 5).
    """
    quotient = round(valeur / pas, _DECIMALES_CALCUL)
    if sens == ARRONDI_INFERIEUR:
        multiple = math.floor(quotient)
    elif sens == ARRONDI_PROCHE:
        multiple = math.floor(quotient + 0.5)
    else:
        multiple = math.ceil(quotient)
    return round(multiple * pas, _DECIMALES_CALCUL)


def _somme_liee_arrondie(donnees, parametres, natures, liee: Liee) -> Constats:
    """Somme de colonne_lignes sur les lignes liées égale à la valeur de colonne divisée
    par diviseur, arrondie au pas dans le sens de arrondi, et au moins égale à minimum.

    Par exemple la main d'oeuvre facturée (somme des quantités des lignes de main
    d'oeuvre) égale à la durée en minutes divisée par 60, arrondie au quart d'heure
    supérieur, avec un minimum d'une demi-heure. Les lignes liées sont celles de
    table_lignes de même clé qui remplissent filtre_lignes. Un écart au-delà de la
    tolérance est un écart; la valeur affichée donne la somme, le nombre de lignes
    liées, la valeur attendue et la valeur de colonne.

    Hors champ : ligne sans aucune ligne liée retenue (par exemple une intervention
    facturée au forfait). Non évaluable : clé vide ou répétée (dans toute la table,
    filtre compris), valeur de colonne vide ou illisible, quantité vide ou illisible
    parmi les lignes liées retenues.
    """
    cles = _cles_comparees(donnees, parametres["cle"])
    _, repetees = _index_unique(
        _cles_comparees(parametres[CONTEXTE_VUE_COMPLETE], parametres["cle"])
    )
    colonne = parametres["colonne"]
    valeurs = lire(donnees[colonne], natures[colonne]).valeurs
    vue_lignes = liee.donnees[_dans_le_champ(liee.donnees, parametres.get("filtre_lignes"))]
    colonne_lignes = parametres["colonne_lignes"]
    quantites = lire(vue_lignes[colonne_lignes], liee.natures[colonne_lignes]).valeurs
    sommes, nombres, illisibles = {}, {}, set()
    for cle, quantite in zip(_cles_comparees(vue_lignes, parametres["cle_lignes"]), quantites):
        if cle is None:
            continue
        nombres[cle] = nombres.get(cle, 0) + 1
        if pd.isna(quantite):
            illisibles.add(cle)
        else:
            sommes[cle] = sommes.get(cle, 0.0) + quantite
    diviseur = parametres.get("diviseur", 1)
    pas = parametres["pas"]
    sens = parametres.get("arrondi", ARRONDI_SUPERIEUR)
    minimum = parametres.get("minimum")
    tolerance = parametres.get("tolerance", 0)

    evaluables = pd.Series(False, index=donnees.index, dtype=bool)
    hors_champ = pd.Series(False, index=donnees.index, dtype=bool)
    constats = pd.Series(None, index=donnees.index, dtype=object)
    affichees = pd.Series(None, index=donnees.index, dtype=object)
    for position, cle in cles.items():
        if cle is None or cle in repetees:
            continue
        if cle not in nombres:
            hors_champ.loc[position] = True
            continue
        valeur = valeurs.loc[position]
        if pd.isna(valeur) or cle in illisibles:
            continue
        evaluables.loc[position] = True
        attendu = _arrondir(round(valeur / diviseur, _DECIMALES_CALCUL), pas, sens)
        if minimum is not None:
            attendu = max(attendu, minimum)
        somme = round(sommes.get(cle, 0.0), _DECIMALES_CALCUL)
        if abs(round(somme - attendu, _DECIMALES_CALCUL)) > tolerance:
            constats.loc[position] = CONSTAT_SOMME_DIFFERENTE
            affichees.loc[position] = (
                f"{_ecrire_nombre(somme)} sur "
                + _pluriel(nombres[cle], "ligne liée", "lignes liées")
                + f" pour {_ecrire_nombre(attendu)} attendu ({colonne} "
                f"{_ecrire_nombre(valeur)})"
            )
    return Constats(evaluables, _ecarts(constats, valeurs=affichees), hors_champ=hors_champ)


def _au_plus_une_non_nulle(donnees, parametres, natures) -> Constats:
    """Au plus une des colonnes porte une valeur non nulle sur chaque ligne (par exemple
    le débit ou le crédit d'une ligne d'écriture); si au_moins_une vaut true, au moins
    une aussi.

    Une valeur est nulle après arrondi à 9 décimales. Une valeur vide ou illisible
    rend la ligne non évaluable (une cellule vide n'est pas lue comme un zéro).
    """
    colonnes = parametres["colonnes"]
    lues = [lire(donnees[colonne], natures[colonne]) for colonne in colonnes]
    evaluables = pd.Series(True, index=donnees.index, dtype=bool)
    non_nulles = pd.Series(0, index=donnees.index, dtype="int64")
    for lecture in lues:
        evaluables &= (lecture.etats == ETAT_LUE).to_numpy()
        non_nulles += (lecture.valeurs.round(_DECIMALES_CALCUL).fillna(0) != 0).astype("int64")
    constats = pd.Series(None, index=donnees.index, dtype=object)
    constats[(evaluables & (non_nulles > 1)).to_numpy(dtype=bool)] = CONSTAT_PLUSIEURS_NON_NULLES
    if parametres.get("au_moins_une", False):
        constats[(evaluables & (non_nulles == 0)).to_numpy(dtype=bool)] = (
            CONSTAT_AUCUNE_NON_NULLE
        )
    return Constats(evaluables, _ecarts(constats))


CONSTAT_DATE_DIFFERENTE = "date différente de celle des lignes liées"
CONSTAT_PLUSIEURS_GROUPES = "lignes liées réparties en plusieurs groupes"
CONSTAT_SOMMES_DIFFERENTES = "sommes des lignes liées différentes des montants"


def _sommes_liees_concordantes(donnees, parametres, natures, liee: Liee) -> Constats:
    """Chaque ligne (par exemple une facture) a des lignes liées (par exemple les lignes
    de son écriture comptable) de même date, réunies en un seul groupe, dont les sommes
    égalent ses montants.

    Les lignes liées sont celles de table_lignes de même clé qui remplissent
    filtre_lignes. Pour chaque montant, les lignes liées qui remplissent ses conditions
    sont retenues, chacune valant la somme de ses termes (colonne multipliée par son
    coefficient, par exemple Debit 1 et Credit -1); la somme des lignes retenues doit
    égaler la valeur de la colonne du montant à la tolérance près (une somme sans ligne
    retenue vaut 0). Si date et date_lignes sont déclarées, chaque ligne liée a la date
    de la ligne. Si groupe_lignes est déclaré, les lignes liées ont toutes la même valeur
    de groupe (par exemple une seule écriture).

    Écarts : aucune ligne liée; date différente; plusieurs groupes; sommes différentes
    (un seul écart par ligne, la valeur affichée donnant chaque montant en écart).

    Non évaluable : clé vide ou répétée (dans toute la table, filtre compris); et, pour
    une ligne qui a des lignes liées, date vide ou illisible d'un côté ou de l'autre,
    groupe vide, montant vide ou illisible, terme vide ou illisible d'une ligne
    retenue, ou valeur vide d'une colonne de conditions dans une ligne liée (elle aurait
    pu porter le montant).
    """
    cles = _cles_comparees(donnees, parametres["cle"])
    _, repetees = _index_unique(
        _cles_comparees(parametres[CONTEXTE_VUE_COMPLETE], parametres["cle"])
    )
    vue_lignes = liee.donnees[_dans_le_champ(liee.donnees, parametres.get("filtre_lignes"))]
    par_cle = {}
    for position, cle in _cles_comparees(vue_lignes, parametres["cle_lignes"]).items():
        if cle is not None:
            par_cle.setdefault(cle, []).append(position)

    colonne_date, colonne_date_lignes = parametres.get("date"), parametres.get("date_lignes")
    avec_date = colonne_date is not None and colonne_date_lignes is not None
    if avec_date:
        dates, etats_dates = _lire_dates(donnees, colonne_date, natures[colonne_date])
        dates_lignes, etats_lignes = _lire_dates(
            vue_lignes, colonne_date_lignes, liee.natures[colonne_date_lignes]
        )
    groupes = None
    if "groupe_lignes" in parametres:
        groupes = _cles_comparees(vue_lignes, parametres["groupe_lignes"])

    montants = []
    for montant in parametres["montants"]:
        colonne = montant["colonne"]
        conditions = montant.get("conditions") or []
        retenues = _dans_le_champ(vue_lignes, conditions)
        conditions_vides = pd.Series(False, index=vue_lignes.index, dtype=bool)
        for condition in conditions:
            conditions_vides |= vue_lignes[condition["colonne"]].map(_texte_lu).isna().to_numpy()
        valeurs_lignes = pd.Series(0.0, index=vue_lignes.index)
        for terme, coefficient in montant["termes"].items():
            valeurs_lignes = valeurs_lignes + coefficient * lire(
                vue_lignes[terme], liee.natures[terme]
            ).valeurs
        montants.append(
            {
                "colonne": colonne,
                "valeurs": lire(donnees[colonne], natures[colonne]).valeurs,
                "retenues": retenues,
                "conditions_vides": conditions_vides,
                "valeurs_lignes": valeurs_lignes,
            }
        )
    tolerance = parametres.get("tolerance", 0)

    evaluables = pd.Series(False, index=donnees.index, dtype=bool)
    constats = pd.Series(None, index=donnees.index, dtype=object)
    morceaux = []
    for position, cle in cles.items():
        if cle is None or cle in repetees:
            continue
        positions = par_cle.get(cle, [])
        if not positions:
            evaluables.loc[position] = True
            constats.loc[position] = CONSTAT_SANS_LIGNE
            continue
        if avec_date and (
            etats_dates.loc[position] != ETAT_LUE
            or any(etats_lignes.loc[p] != ETAT_LUE for p in positions)
        ):
            continue
        if groupes is not None and any(groupes.loc[p] is None for p in positions):
            continue
        lisible = True
        sommes = []
        for montant in montants:
            valeur = montant["valeurs"].loc[position]
            retenues = [p for p in positions if montant["retenues"].loc[p]]
            if (
                pd.isna(valeur)
                or any(montant["conditions_vides"].loc[p] for p in positions)
                or any(pd.isna(montant["valeurs_lignes"].loc[p]) for p in retenues)
            ):
                lisible = False
                break
            somme = round(
                sum(montant["valeurs_lignes"].loc[p] for p in retenues), _DECIMALES_CALCUL
            )
            sommes.append((montant["colonne"], valeur, somme, len(retenues)))
        if not lisible:
            continue
        evaluables.loc[position] = True
        ecarts_ligne = []
        if groupes is not None:
            distincts = sorted({groupes.loc[p] for p in positions})
            if len(distincts) > 1:
                ecarts_ligne.append(
                    (
                        CONSTAT_PLUSIEURS_GROUPES,
                        f"{len(distincts)} groupes : " + SEPARATEUR.join(distincts),
                    )
                )
        if avec_date:
            date = dates.loc[position]
            autres = sorted({dates_lignes.loc[p] for p in positions} - {date})
            if autres:
                ecarts_ligne.append(
                    (
                        CONSTAT_DATE_DIFFERENTE,
                        f"{_jour(date)} (lignes liées : "
                        + ", ".join(_jour(jour) for jour in autres)
                        + ")",
                    )
                )
        en_ecart = [
            f"{colonne} {_ecrire_nombre(valeur)} pour une somme de {_ecrire_nombre(somme)} sur "
            + _pluriel(nombre, "ligne liée", "lignes liées")
            + f" (écart {_ecrire_nombre(round(valeur - somme, _DECIMALES_CALCUL))})"
            for colonne, valeur, somme, nombre in sommes
            if abs(round(valeur - somme, _DECIMALES_CALCUL)) > tolerance
        ]
        if en_ecart:
            ecarts_ligne.append((CONSTAT_SOMMES_DIFFERENTES, "; ".join(en_ecart)))
        for constat, affichee in ecarts_ligne:
            morceaux.append((position, constat, affichee))
    ecarts = _ecarts(constats)
    if morceaux:
        supplementaires = pd.DataFrame(
            {
                "constat": [constat for _, constat, _ in morceaux],
                "proposition": None,
                "valeur": [affichee for _, _, affichee in morceaux],
            },
            index=pd.Index([position for position, _, _ in morceaux]),
        )
        ecarts = pd.concat([ecarts, supplementaires])
    return Constats(evaluables, ecarts)


CONSTAT_TOTAL_PERIODE = "total différent de celui de la table liée"


def _totaux_par_periode(donnees, parametres, natures, liee: Liee) -> Constats:
    """Par période d'export (periode_export), et par valeur de detail si detail et
    detail_lignes sont déclarés, le total de la table de la règle égale celui de la
    table liée (par exemple le total HT des factures et le solde des comptes de
    produits du FEC).

    Chaque ligne vaut la somme de ses termes (colonne multipliée par son coefficient);
    les lignes de la table liée sont celles qui remplissent filtre_lignes. Les totaux
    sont des sommes exactes (`math.fsum`); un groupe présent d'un seul côté vaut 0 de
    l'autre côté. L'écart, signé et arrondi à 9 décimales, est comparé à la tolérance.

    Écart, sans ligne source : un par groupe dont les totaux diffèrent, la clé donnant
    la période (et la valeur de détail), la valeur donnant les deux totaux, leurs
    nombres de lignes et l'écart.

    Non évaluable (lignes de la table de la règle du groupe) : un terme vide ou
    illisible, d'un côté ou de l'autre, rend son groupe non évaluable; une valeur de
    détail vide rend sa période non évaluable; une ligne sans période lisible rend
    tous les groupes non évaluables. Chaque cause donne un avertissement.
    """
    vue_lignes = liee.donnees[_dans_le_champ(liee.donnees, parametres.get("filtre_lignes"))]
    noms = (parametres[CONTEXTE_TABLE], liee.table)
    cotes = (
        (donnees, parametres["termes"], parametres.get("detail"), natures),
        (vue_lignes, parametres["termes_lignes"], parametres.get("detail_lignes"),
         liee.natures),
    )
    sans_periode = [0, 0]
    details_vides = {}
    groupes = {}
    for cote, (vue, termes, colonne_detail, natures_vue) in enumerate(cotes):
        valeurs = pd.Series(0.0, index=vue.index)
        for colonne, coefficient in termes.items():
            valeurs = valeurs + coefficient * lire(vue[colonne], natures_vue[colonne]).valeurs
        if colonne_detail is None:
            details = [""] * len(vue)
        else:
            details = [_texte_lu(valeur) for valeur in vue[colonne_detail]]
        for position, valeur, periode, detail in zip(
            vue.index, valeurs, vue[COLONNE_PERIODE], details
        ):
            if _bornes_periode(periode) is None:
                sans_periode[cote] += 1
                continue
            if detail is None:
                details_vides.setdefault((periode, cote), []).append(position)
                continue
            groupe = groupes.setdefault(
                (periode, detail),
                {"positions": [], "valeurs": ([], []), "illisibles": [0, 0]},
            )
            if cote == 0:
                groupe["positions"].append(position)
            if pd.isna(valeur):
                groupe["illisibles"][cote] += 1
            else:
                groupe["valeurs"][cote].append(float(valeur))

    avertissements = []
    for cote, nombre in enumerate(sans_periode):
        if nombre:
            avertissements.append(
                _pluriel(nombre, "ligne", "lignes")
                + f" sans période d'export lisible dans {noms[cote]} : aucun total évaluable"
            )
    for (periode, cote), positions in sorted(details_vides.items()):
        colonne_detail = cotes[cote][2]
        avertissements.append(
            f"période {periode} : "
            + _pluriel(len(positions), "ligne", "lignes")
            + f" au détail vide dans {noms[cote]} ({colonne_detail})"
        )
    bloquees = {periode for periode, _ in details_vides}
    evaluables = pd.Series(False, index=donnees.index, dtype=bool)
    lignes_ecarts = []
    tolerance = parametres.get("tolerance", 0)
    for (periode, detail), groupe in sorted(groupes.items()):
        cle = periode if detail == "" else f"{periode}{SEPARATEUR}{detail}"
        for cote, nombre in enumerate(groupe["illisibles"]):
            if nombre:
                avertissements.append(
                    f"période {cle} : "
                    + _pluriel(nombre, "montant vide ou illisible", "montants vides ou illisibles")
                    + f" dans {noms[cote]}"
                )
        if any(sans_periode) or periode in bloquees or any(groupe["illisibles"]):
            continue
        evaluables.loc[groupe["positions"]] = True
        totaux = [round(math.fsum(groupe["valeurs"][cote]), _DECIMALES_CALCUL) for cote in (0, 1)]
        ecart = round(totaux[0] - totaux[1], _DECIMALES_CALCUL)
        if abs(ecart) > tolerance:
            lignes_ecarts.append(
                {
                    "constat": CONSTAT_TOTAL_PERIODE,
                    "cle": cle,
                    "valeur": " pour ".join(
                        f"{noms[cote]} {_ecrire_nombre(totaux[cote])} sur "
                        + _pluriel(len(groupe["valeurs"][cote]), "ligne", "lignes")
                        for cote in (0, 1)
                    )
                    + f" (écart {_ecrire_nombre(ecart)})",
                }
            )
    constats = pd.Series(None, index=donnees.index, dtype=object)
    return Constats(
        evaluables,
        _ecarts(constats),
        tuple(avertissements),
        ecarts_periodes=pd.DataFrame(lignes_ecarts, columns=["constat", "cle", "valeur"]),
    )


def _verifier_totaux(parametres: dict) -> list[str]:
    problemes = _verifier_tolerance(parametres)
    if ("detail" in parametres) != ("detail_lignes" in parametres):
        problemes.append("detail et detail_lignes : les deux sont attendues, ou aucune")
    return problemes


def _verifier_sommes_liees(parametres: dict) -> list[str]:
    problemes = _verifier_tolerance(parametres)
    if ("date" in parametres) != ("date_lignes" in parametres):
        problemes.append("date et date_lignes : les deux sont attendues, ou aucune")
    return problemes


def _verifier_conforme_horaires(parametres: dict) -> list[str]:
    problemes = _entier_positif(parametres, "feries_minimum")
    if "dans_horaires" not in parametres and "hors_horaires" not in parametres:
        problemes.append("dans_horaires ou hors_horaires attendu")
    return problemes


def _verifier_tolerance(parametres: dict) -> list[str]:
    if parametres.get("tolerance", 0) < 0:
        return ["tolerance : un nombre positif ou nul est attendu"]
    return []


def _entier_positif(parametres: dict, nom: str) -> list[str]:
    valeur = parametres.get(nom)
    if valeur is not None and (valeur < 0 or not float(valeur).is_integer()):
        return [f"{nom} : un entier positif ou nul est attendu"]
    return []


def _verifier_debut(parametres: dict) -> list[str]:
    return _entier_positif(parametres, "debut")


def _verifier_intervalles(parametres: dict) -> list[str]:
    if parametres.get("battement", 0) < 0:
        return ["battement : un nombre positif ou nul est attendu"]
    return []


def _verifier_horaires(parametres: dict) -> list[str]:
    return _entier_positif(parametres, "feries_minimum")


def _verifier_delai(parametres: dict) -> list[str]:
    problemes = [
        f"{nom} : un nombre entier de jours est attendu"
        for nom in ("delai_min", "delai_max")
        if not float(parametres[nom]).is_integer()
    ]
    if not problemes and parametres["delai_min"] > parametres["delai_max"]:
        problemes.append(
            f"delai_min ({parametres['delai_min']}) supérieur à delai_max "
            f"({parametres['delai_max']})"
        )
    return problemes


def _verifier_somme_arrondie(parametres: dict) -> list[str]:
    problemes = _verifier_tolerance(parametres)
    for nom in ("diviseur", "pas"):
        if nom in parametres and parametres[nom] <= 0:
            problemes.append(f"{nom} : un nombre strictement positif est attendu")
    return problemes


def _verifier_plusieurs_colonnes(parametres: dict) -> list[str]:
    if len(parametres["colonnes"]) < 2:
        return ["colonnes : au moins deux colonnes sont attendues"]
    return []


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
    "numerotation_continue": TypeRegle(
        description=(
            "Les numéros d'une même série se suivent sans trou. motif est une "
            "expression régulière qui couvre la valeur entière, avec un groupe nommé "
            "numero (des chiffres); les autres groupes nommés définissent la série "
            "(par exemple (?P<annee>...) pour une série par année). Un trou est porté "
            "par la ligne du numéro qui le suit; avec debut, les numéros manquants "
            "avant le premier numéro observé forment aussi un trou."
        ),
        parametres={
            "colonne": GENRE_COLONNE,
            "motif": GENRE_MOTIF_NUMERO,
            "debut": GENRE_NOMBRE,
        },
        vue=VUE_SANS_SURNOMBRE,
        controler=_numerotation_continue,
        facultatifs=("debut",),
        verifier=_verifier_debut,
    ),
    "numerotation_chronologique": TypeRegle(
        description=(
            "Dans une même série (voir numerotation_continue), un numéro n'a pas une "
            "date antérieure à celle du numéro précédent; si le motif a un groupe "
            "nommé annee, l'année du numéro est celle de la date."
        ),
        parametres={
            "colonne": GENRE_COLONNE,
            "motif": GENRE_MOTIF_NUMERO,
            "date": GENRE_COLONNE_DATE,
        },
        vue=VUE_SANS_SURNOMBRE,
        controler=_numerotation_chronologique,
        issue=ISSUE_A_ARBITRER,
    ),
    "intervalles_sans_chevauchement": TypeRegle(
        description=(
            "Dans un même groupe (par exemple un intervenant), deux lignes ne se "
            "chevauchent pas et sont séparées d'au moins battement minutes. Une ligne "
            "commence à date (et heure) et dure duree minutes; comparaison vaut telle "
            "quelle (par défaut), après normalisation (sans accent, casse ni espace "
            "en trop) ou mots dans le désordre (après normalisation, mots triés)."
        ),
        parametres={
            "groupe": GENRE_COLONNE,
            "date": GENRE_COLONNE_DATE,
            "heure": GENRE_COLONNE_HEURE,
            "duree": GENRE_COLONNE_NOMBRE,
            "battement": GENRE_NOMBRE,
            "comparaison": GENRE_COMPARAISON,
        },
        vue=VUE_SANS_SURNOMBRE,
        controler=_intervalles_sans_chevauchement,
        facultatifs=("heure", "battement", "comparaison"),
        verifier=_verifier_intervalles,
    ),
    "hors_horaires_selon_valeur": TypeRegle(
        description=(
            "Une ligne dont la date et l'heure tombent hors des créneaux de horaires "
            "(par jour de la semaine, et ferie pour un jour férié de feries) porte dans "
            "colonne l'une des valeurs. feries donne les jours fériés par année; une "
            "année des données absente de feries, ou avec moins de feries_minimum "
            "jours, est signalée au bilan."
        ),
        parametres={
            "date": GENRE_COLONNE_DATE,
            "heure": GENRE_COLONNE_HEURE,
            "horaires": GENRE_HORAIRES,
            "feries": GENRE_FERIES,
            "feries_minimum": GENRE_NOMBRE,
            "colonne": GENRE_COLONNE,
            "valeurs": GENRE_VALEURS,
        },
        vue=VUE_TOUTES,
        controler=_hors_horaires_selon_valeur,
        facultatifs=("feries_minimum",),
        verifier=_verifier_horaires,
    ),
    "egalite_calculee": TypeRegle(
        description=(
            "La valeur de cible égale, à tolerance près (0 par défaut), la somme des "
            "colonnes de termes multipliées chacune par son coefficient; par exemple "
            "total_ttc égale total_ht + total_tva avec termes {total_ht: 1, "
            "total_tva: 1}."
        ),
        parametres={
            "cible": GENRE_COLONNE_NOMBRE,
            "termes": GENRE_TERMES,
            "tolerance": GENRE_NOMBRE,
        },
        vue=VUE_TOUTES,
        controler=_egalite_calculee,
        facultatifs=("tolerance",),
        verifier=_verifier_tolerance,
    ),
    "total_des_lignes": TypeRegle(
        description=(
            "La valeur de colonne égale, à tolerance près (0 par défaut), la somme de "
            "colonne_lignes sur les lignes de table_lignes de même clé (cle, colonnes de "
            "même nom dans les deux tables). Une ligne sans aucune ligne liée est un "
            "écart; une clé répétée, ou un montant illisible parmi les lignes liées, "
            "rend la ligne non évaluable."
        ),
        parametres={
            "cle": GENRE_COLONNES_COMMUNES,
            "colonne": GENRE_COLONNE_NOMBRE,
            "table_lignes": GENRE_TABLE,
            "colonne_lignes": GENRE_COLONNE_NOMBRE_LIEE,
            "tolerance": GENRE_NOMBRE,
        },
        vue=VUE_SANS_SURNOMBRE,
        controler=_total_des_lignes,
        facultatifs=("tolerance",),
        verifier=_verifier_tolerance,
        table_liee="table_lignes",
    ),
    "equilibre_par_groupe": TypeRegle(
        description=(
            "Dans chaque groupe de lignes de même valeur de groupe (une ou plusieurs "
            "colonnes), la somme de debit égale la somme de credit, à tolerance près (0 "
            "par défaut). Chaque ligne d'un groupe non équilibré est un écart; un "
            "montant vide ou illisible rend tout son groupe non évaluable."
        ),
        parametres={
            "groupe": GENRE_COLONNES,
            "debit": GENRE_COLONNE_NOMBRE,
            "credit": GENRE_COLONNE_NOMBRE,
            "tolerance": GENRE_NOMBRE,
        },
        vue=VUE_SANS_SURNOMBRE,
        controler=_equilibre_par_groupe,
        facultatifs=("tolerance",),
        verifier=_verifier_tolerance,
    ),
    "existence_dans_reference": TypeRegle(
        description=(
            "La clé de chaque ligne (cle, une ou plusieurs colonnes, textes reliés par "
            "une espace) existe dans table_reference, sous les colonnes de "
            "cle_reference (par défaut celles de cle). comparaison vaut telle quelle "
            "(par défaut), après normalisation ou mots dans le désordre. Une clé vide "
            "rend la ligne non évaluable, ou hors champ si cle_facultative vaut true."
        ),
        parametres={
            "cle": GENRE_COLONNES,
            "table_reference": GENRE_TABLE,
            "cle_reference": GENRE_COLONNES_LIEES,
            "comparaison": GENRE_COMPARAISON,
            "cle_facultative": GENRE_BOOLEEN,
        },
        vue=VUE_TOUTES,
        controler=_existence_dans_reference,
        facultatifs=("cle_reference", "comparaison", "cle_facultative"),
        table_liee="table_reference",
        defauts={"cle_reference": "cle"},
    ),
    "date_dans_periode_reference": TypeRegle(
        description=(
            "La date de chaque ligne tombe dans l'une des périodes (debut à fin, "
            "incluses; fin vide ou absente : période ouverte) que table_reference donne "
            "pour sa clé (voir existence_dans_reference). Une clé absente du référentiel "
            "est un écart; une ligne du référentiel inutilisable (début vide ou "
            "illisible, fin illisible, début après fin) est signalée au bilan et rend "
            "non évaluables les dates hors des autres périodes de sa clé."
        ),
        parametres={
            "cle": GENRE_COLONNES,
            "date": GENRE_COLONNE_DATE,
            "table_reference": GENRE_TABLE,
            "cle_reference": GENRE_COLONNES_LIEES,
            "debut": GENRE_COLONNE_DATE_LIEE,
            "fin": GENRE_COLONNE_DATE_LIEE,
            "comparaison": GENRE_COMPARAISON,
            "cle_facultative": GENRE_BOOLEEN,
        },
        vue=VUE_TOUTES,
        controler=_date_dans_periode_reference,
        facultatifs=("cle_reference", "fin", "comparaison", "cle_facultative"),
        table_liee="table_reference",
        defauts={"cle_reference": "cle"},
    ),
    "periodes_couvertes_par_paliers": TypeRegle(
        description=(
            "Chaque période (debut à fin) est couverte dès son début par un palier de "
            "table_paliers de même clé (cle_paliers, par défaut les colonnes de cle), "
            "daté au plus tard au début de la période et après la fin de la période "
            "précédente de la même clé; un palier vaut jusqu'au palier suivant. Par "
            "exemple des périodes d'emploi couvertes par des rémunérations."
        ),
        parametres={
            "cle": GENRE_COLONNES,
            "debut": GENRE_COLONNE_DATE,
            "fin": GENRE_COLONNE_DATE,
            "table_paliers": GENRE_TABLE,
            "cle_paliers": GENRE_COLONNES_LIEES,
            "date_palier": GENRE_COLONNE_DATE_LIEE,
        },
        vue=VUE_SANS_SURNOMBRE,
        controler=_periodes_couvertes_par_paliers,
        facultatifs=("fin", "cle_paliers"),
        table_liee="table_paliers",
        defauts={"cle_paliers": "cle"},
    ),
    "annee_dans_reference": TypeRegle(
        description=(
            "L'année de la date de chaque ligne figure dans la colonne colonne_annee de "
            "table_reference (par exemple des paramètres annuels); chaque année absente "
            "est aussi signalée au bilan."
        ),
        parametres={
            "date": GENRE_COLONNE_DATE,
            "table_reference": GENRE_TABLE,
            "colonne_annee": GENRE_COLONNE_NOMBRE_LIEE,
        },
        vue=VUE_TOUTES,
        controler=_annee_dans_reference,
        table_liee="table_reference",
    ),
    "rattachement_unique_dans_delai": TypeRegle(
        description=(
            "Chaque ligne est rattachée à un document et un seul (par exemple une "
            "intervention à une facture) : les lignes de table_lignes de même clé "
            "(cle_lignes, par défaut les colonnes de cle), parmi celles qui remplissent "
            "filtre_lignes, désignent le document (colonnes de document), retrouvé dans "
            "table_documents (cle_documents, par défaut les colonnes de document). Le "
            "document est daté de delai_min à delai_max jours après la date de la ligne. "
            "Une ligne sans document dont le délai n'est pas échu à la date de coupure "
            "des données est une information."
        ),
        parametres={
            "cle": GENRE_COLONNES,
            "date": GENRE_COLONNE_DATE,
            "table_lignes": GENRE_TABLE,
            "cle_lignes": GENRE_COLONNES_LIEES,
            "document": GENRE_COLONNES_LIEES,
            "filtre_lignes": GENRE_CONDITIONS,
            "table_documents": GENRE_TABLE,
            "cle_documents": GENRE_COLONNES_LIEES,
            "date_document": GENRE_COLONNE_DATE_LIEE,
            "delai_min": GENRE_NOMBRE,
            "delai_max": GENRE_NOMBRE,
        },
        vue=VUE_SANS_SURNOMBRE,
        controler=_rattachement_unique_dans_delai,
        facultatifs=("cle_lignes", "filtre_lignes", "cle_documents"),
        verifier=_verifier_delai,
        defauts={"cle_lignes": "cle", "cle_documents": "document"},
        tables_liees=("table_lignes", "table_documents"),
        rattachements={
            "cle_lignes": "table_lignes",
            "document": "table_lignes",
            "filtre_lignes": "table_lignes",
            "cle_documents": "table_documents",
            "date_document": "table_documents",
        },
        contexte=(CONTEXTE_DATE_COUPURE, CONTEXTE_VUE_COMPLETE),
    ),
    "reference_conforme": TypeRegle(
        description=(
            "La ligne de table_reference de même clé (cle_reference, par défaut les "
            "colonnes de cle) remplit toutes les conditions de attendu (colonne et "
            "valeurs ou motif). Un écart qui remplit une exception (libelle et "
            "conditions, une colonne de la référence s'écrivant table.colonne) est une "
            "information. Une référence absente ou une valeur vide rend la ligne non "
            "évaluable; une clé vide aussi, ou la met hors champ si cle_facultative vaut "
            "true."
        ),
        parametres={
            "cle": GENRE_COLONNES,
            "table_reference": GENRE_TABLE,
            "cle_reference": GENRE_COLONNES_LIEES,
            "attendu": GENRE_CONDITIONS,
            "exceptions": GENRE_EXCEPTIONS,
            "cle_facultative": GENRE_BOOLEEN,
        },
        vue=VUE_SANS_SURNOMBRE,
        controler=_reference_conforme,
        facultatifs=("cle_reference", "exceptions", "cle_facultative"),
        table_liee="table_reference",
        defauts={"cle_reference": "cle"},
        rattachements={"attendu": "table_reference"},
    ),
    "concordance_entre_references": TypeRegle(
        description=(
            "Une ligne a deux références, dans table_a (clé cle_a, sous les colonnes de "
            "cle_reference_a, par défaut celles de cle_a) et dans table_b (de même) : "
            "colonne_a de la première égale colonne_b de la seconde (par exemple le "
            "client d'une intervention et celui de la facture d'une même ligne). "
            "comparaison vaut telle quelle (par défaut), après normalisation ou mots dans "
            "le désordre."
        ),
        parametres={
            "cle_a": GENRE_COLONNES,
            "table_a": GENRE_TABLE,
            "cle_reference_a": GENRE_COLONNES_LIEES,
            "colonne_a": GENRE_COLONNE_LIEE,
            "cle_b": GENRE_COLONNES,
            "table_b": GENRE_TABLE,
            "cle_reference_b": GENRE_COLONNES_LIEES,
            "colonne_b": GENRE_COLONNE_LIEE,
            "comparaison": GENRE_COMPARAISON,
        },
        vue=VUE_SANS_SURNOMBRE,
        controler=_concordance_entre_references,
        facultatifs=("cle_reference_a", "cle_reference_b", "comparaison"),
        defauts={"cle_reference_a": "cle_a", "cle_reference_b": "cle_b"},
        tables_liees=("table_a", "table_b"),
        rattachements={
            "cle_reference_a": "table_a",
            "colonne_a": "table_a",
            "cle_reference_b": "table_b",
            "colonne_b": "table_b",
        },
    ),
    "sans_ligne_liee": TypeRegle(
        description=(
            "Aucune ligne de table_lignes (parmi celles qui remplissent filtre_lignes) ne "
            "porte la clé de la ligne (cle_lignes, par défaut les colonnes de cle); par "
            "exemple une intervention annulée n'est pas facturée. Un écart qui remplit une "
            "exception (une condition sur table_lignes.colonne devant être remplie par "
            "toutes les lignes liées) est une information."
        ),
        parametres={
            "cle": GENRE_COLONNES,
            "table_lignes": GENRE_TABLE,
            "cle_lignes": GENRE_COLONNES_LIEES,
            "filtre_lignes": GENRE_CONDITIONS,
            "exceptions": GENRE_EXCEPTIONS,
        },
        vue=VUE_SANS_SURNOMBRE,
        controler=_sans_ligne_liee,
        facultatifs=("cle_lignes", "filtre_lignes", "exceptions"),
        table_liee="table_lignes",
        defauts={"cle_lignes": "cle"},
        rattachements={"filtre_lignes": "table_lignes"},
        contexte=(CONTEXTE_VUE_COMPLETE,),
    ),
    "ligne_liee_attendue": TypeRegle(
        description=(
            "Parmi les lignes de table_lignes de même clé (cle_lignes, par défaut les "
            "colonnes de cle) qui remplissent filtre_lignes, au moins une remplit toutes "
            "les conditions de attendu; par exemple une intervention de contrôle facturée "
            "avec un forfait de contrôle. Une ligne sans aucune ligne liée est hors champ. "
            "Un écart qui remplit une exception (une condition sur table_lignes.colonne "
            "devant être remplie par toutes les lignes liées) est une information."
        ),
        parametres={
            "cle": GENRE_COLONNES,
            "table_lignes": GENRE_TABLE,
            "cle_lignes": GENRE_COLONNES_LIEES,
            "filtre_lignes": GENRE_CONDITIONS,
            "attendu": GENRE_CONDITIONS,
            "exceptions": GENRE_EXCEPTIONS,
        },
        vue=VUE_SANS_SURNOMBRE,
        controler=_ligne_liee_attendue,
        facultatifs=("cle_lignes", "filtre_lignes", "exceptions"),
        table_liee="table_lignes",
        defauts={"cle_lignes": "cle"},
        rattachements={"filtre_lignes": "table_lignes", "attendu": "table_lignes"},
        contexte=(CONTEXTE_VUE_COMPLETE,),
    ),
    "conforme_selon_horaires": TypeRegle(
        description=(
            "Selon que la date et l'heure de la ligne de table_reference de même clé "
            "(cle_reference, par défaut les colonnes de cle) tombent dans les créneaux de "
            "horaires ou non (voir hors_horaires_selon_valeur pour horaires, feries et "
            "feries_minimum), la ligne remplit les conditions de dans_horaires ou de "
            "hors_horaires (l'une des deux au moins est déclarée); par exemple une main "
            "d'oeuvre facturée au tarif majoré hors des horaires ouvrés."
        ),
        parametres={
            "cle": GENRE_COLONNES,
            "table_reference": GENRE_TABLE,
            "cle_reference": GENRE_COLONNES_LIEES,
            "date": GENRE_COLONNE_DATE_LIEE,
            "heure": GENRE_COLONNE_HEURE_LIEE,
            "horaires": GENRE_HORAIRES,
            "feries": GENRE_FERIES,
            "feries_minimum": GENRE_NOMBRE,
            "dans_horaires": GENRE_CONDITIONS,
            "hors_horaires": GENRE_CONDITIONS,
        },
        vue=VUE_SANS_SURNOMBRE,
        controler=_conforme_selon_horaires,
        facultatifs=("cle_reference", "feries_minimum", "dans_horaires", "hors_horaires"),
        verifier=_verifier_conforme_horaires,
        table_liee="table_reference",
        defauts={"cle_reference": "cle"},
    ),
    "quantites_concordantes": TypeRegle(
        description=(
            "Les lignes de table_a et de table_b de même clé (cle_a et cle_b, par défaut "
            "les colonnes de cle), parmi celles qui remplissent filtre_a et filtre_b, ont "
            "pour chaque valeur de detail_a et detail_b la même somme de quantite_a et "
            "quantite_b, à tolerance près (0 par défaut); par exemple les pièces posées sur "
            "une intervention et les pièces facturées. Si hors_champ_sans_b vaut true, une "
            "ligne sans aucune ligne dans table_b est hors champ."
        ),
        parametres={
            "cle": GENRE_COLONNES,
            "table_a": GENRE_TABLE,
            "cle_a": GENRE_COLONNES_LIEES,
            "filtre_a": GENRE_CONDITIONS,
            "detail_a": GENRE_COLONNE_LIEE,
            "quantite_a": GENRE_COLONNE_NOMBRE_LIEE,
            "table_b": GENRE_TABLE,
            "cle_b": GENRE_COLONNES_LIEES,
            "filtre_b": GENRE_CONDITIONS,
            "detail_b": GENRE_COLONNE_LIEE,
            "quantite_b": GENRE_COLONNE_NOMBRE_LIEE,
            "tolerance": GENRE_NOMBRE,
            "hors_champ_sans_b": GENRE_BOOLEEN,
        },
        vue=VUE_SANS_SURNOMBRE,
        controler=_quantites_concordantes,
        facultatifs=("cle_a", "filtre_a", "cle_b", "filtre_b", "tolerance",
                     "hors_champ_sans_b"),
        verifier=_verifier_tolerance,
        defauts={"cle_a": "cle", "cle_b": "cle"},
        tables_liees=("table_a", "table_b"),
        rattachements={
            "cle_a": "table_a",
            "filtre_a": "table_a",
            "detail_a": "table_a",
            "quantite_a": "table_a",
            "cle_b": "table_b",
            "filtre_b": "table_b",
            "detail_b": "table_b",
            "quantite_b": "table_b",
        },
        contexte=(CONTEXTE_VUE_COMPLETE,),
    ),
    "produit_calcule": TypeRegle(
        description=(
            "La valeur de cible égale, à tolerance près (0 par défaut), le produit des "
            "facteurs lus sur la même ligne. Un facteur est une colonne, ou un dictionnaire "
            "{colonne, coefficient, constante, vide} qui vaut constante + coefficient × "
            "colonne (coefficient 1 et constante 0 par défaut), vide donnant la valeur d'une "
            "cellule vide (sans vide, la ligne est non évaluable); par exemple montant_ht "
            "égale quantite × pu_ht × (1 - 0,01 × remise_pct)."
        ),
        parametres={
            "cible": GENRE_COLONNE_NOMBRE,
            "facteurs": GENRE_FACTEURS,
            "tolerance": GENRE_NOMBRE,
        },
        vue=VUE_TOUTES,
        controler=_produit_calcule,
        facultatifs=("tolerance",),
        verifier=_verifier_tolerance,
    ),
    "somme_liee_arrondie": TypeRegle(
        description=(
            "La somme de colonne_lignes sur les lignes de table_lignes de même clé "
            "(cle_lignes, par défaut les colonnes de cle) qui remplissent filtre_lignes "
            "égale, à tolerance près (0 par défaut), la valeur de colonne divisée par "
            "diviseur (1 par défaut), arrondie au multiple de pas (arrondi vaut supérieur par "
            "défaut, inférieur ou au plus proche), et au moins égale à minimum; par exemple "
            "la main d'oeuvre facturée au quart d'heure supérieur d'une durée en minutes, "
            "avec un minimum d'une demi-heure. Une ligne sans aucune ligne liée retenue est "
            "hors champ."
        ),
        parametres={
            "cle": GENRE_COLONNES,
            "colonne": GENRE_COLONNE_NOMBRE,
            "diviseur": GENRE_NOMBRE,
            "pas": GENRE_NOMBRE,
            "arrondi": GENRE_ARRONDI,
            "minimum": GENRE_NOMBRE,
            "table_lignes": GENRE_TABLE,
            "cle_lignes": GENRE_COLONNES_LIEES,
            "filtre_lignes": GENRE_CONDITIONS,
            "colonne_lignes": GENRE_COLONNE_NOMBRE_LIEE,
            "tolerance": GENRE_NOMBRE,
        },
        vue=VUE_SANS_SURNOMBRE,
        controler=_somme_liee_arrondie,
        facultatifs=("diviseur", "arrondi", "minimum", "cle_lignes", "filtre_lignes",
                     "tolerance"),
        verifier=_verifier_somme_arrondie,
        table_liee="table_lignes",
        defauts={"cle_lignes": "cle"},
        rattachements={"filtre_lignes": "table_lignes"},
        contexte=(CONTEXTE_VUE_COMPLETE,),
    ),
    "au_plus_une_non_nulle": TypeRegle(
        description=(
            "Sur chaque ligne, au plus une des colonnes (au moins deux colonnes de nombre) "
            "porte une valeur non nulle, et au moins une si au_moins_une vaut true (false "
            "par défaut); par exemple le débit et le crédit d'une ligne d'écriture, l'un "
            "des deux à zéro. Une valeur vide ou illisible rend la ligne non évaluable."
        ),
        parametres={
            "colonnes": GENRE_COLONNES_NOMBRE,
            "au_moins_une": GENRE_BOOLEEN,
        },
        vue=VUE_TOUTES,
        controler=_au_plus_une_non_nulle,
        facultatifs=("au_moins_une",),
        verifier=_verifier_plusieurs_colonnes,
    ),
    "sommes_liees_concordantes": TypeRegle(
        description=(
            "Chaque ligne a des lignes liées dans table_lignes (même clé, cle_lignes par "
            "défaut les colonnes de cle, parmi celles qui remplissent filtre_lignes), par "
            "exemple une facture et les lignes de son écriture comptable. Pour chaque "
            "élément de montants (colonne, conditions facultatives et termes), la somme des "
            "lignes liées qui remplissent les conditions, chacune valant la somme de ses "
            "termes (colonne de la table liée vers coefficient), égale la valeur de colonne à "
            "tolerance près (0 par défaut). Si date et date_lignes sont déclarées, les lignes "
            "liées ont la date de la ligne; si groupe_lignes est déclaré, elles forment un "
            "seul groupe. Une ligne sans aucune ligne liée est un écart."
        ),
        parametres={
            "cle": GENRE_COLONNES,
            "table_lignes": GENRE_TABLE,
            "cle_lignes": GENRE_COLONNES_LIEES,
            "filtre_lignes": GENRE_CONDITIONS,
            "date": GENRE_COLONNE_DATE,
            "date_lignes": GENRE_COLONNE_DATE_LIEE,
            "groupe_lignes": GENRE_COLONNES_LIEES,
            "montants": GENRE_MONTANTS,
            "tolerance": GENRE_NOMBRE,
        },
        vue=VUE_SANS_SURNOMBRE,
        controler=_sommes_liees_concordantes,
        facultatifs=("cle_lignes", "filtre_lignes", "date", "date_lignes", "groupe_lignes",
                     "tolerance"),
        verifier=_verifier_sommes_liees,
        table_liee="table_lignes",
        defauts={"cle_lignes": "cle"},
        rattachements={"filtre_lignes": "table_lignes"},
        contexte=(CONTEXTE_VUE_COMPLETE,),
    ),
    "totaux_par_periode": TypeRegle(
        description=(
            "Par période d'export (periode_export), et par valeur de detail face à "
            "detail_lignes si les deux sont déclarées, la somme des lignes de la table "
            "(chacune valant la somme de ses termes, colonne vers coefficient) égale la "
            "somme des lignes de table_lignes qui remplissent filtre_lignes (chacune valant "
            "la somme de termes_lignes), à tolerance près (0 par défaut); par exemple le "
            "total HT des factures et le solde des comptes de produits du FEC. Un écart est "
            "rendu par période, sans ligne source. Un montant vide ou illisible rend sa "
            "période non évaluable."
        ),
        parametres={
            "termes": GENRE_TERMES,
            "detail": GENRE_COLONNE,
            "table_lignes": GENRE_TABLE,
            "filtre_lignes": GENRE_CONDITIONS,
            "termes_lignes": GENRE_TERMES_LIES,
            "detail_lignes": GENRE_COLONNE_LIEE,
            "tolerance": GENRE_NOMBRE,
        },
        vue=VUE_SANS_SURNOMBRE,
        controler=_totaux_par_periode,
        prerequis=_prerequis_export,
        facultatifs=("detail", "filtre_lignes", "detail_lignes", "tolerance"),
        verifier=_verifier_totaux,
        table_liee="table_lignes",
        rattachements={"filtre_lignes": "table_lignes"},
        contexte=(CONTEXTE_TABLE,),
        prerequis_liees=_prerequis_export,
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


def _avec_defauts(instance: dict) -> dict:
    """Instance complétée des paramètres facultatifs qui reprennent par défaut la valeur
    d'un autre paramètre (voir `TypeRegle.defauts`)."""
    complete = dict(instance)
    for parametre, source in TYPES[instance["type"]].defauts.items():
        if parametre not in complete and source in complete:
            complete[parametre] = complete[source]
    return complete


def _tables_liees(instance: dict) -> dict:
    """Tables liées d'une instance : paramètre vers nom de table, dans l'ordre du type."""
    type_regle = TYPES[instance["type"]]
    return {
        parametre: instance[parametre]
        for parametre in type_regle.parametres_tables()
        if parametre in instance
    }


def _colonne_qualifiee(colonne: str, table: str, liees) -> tuple[str, str]:
    """Table et colonne d'une colonne de condition d'exception : « t.c » désigne la
    colonne c de la table liée t, une colonne sans préfixe celle de la table de la
    règle."""
    prefixe, point, reste = colonne.partition(".")
    if point and prefixe in liees:
        return prefixe, reste
    return table, colonne


def _references(instance: dict) -> list[tuple[str, str, str, str]]:
    """Colonnes citées par une instance : (paramètre, table, colonne, genre de colonne).

    Dans l'ordre des paramètres de son type. Le genre de colonne dit la nature
    attendue (`GENRE_COLONNE` : aucune). Une colonne de la table liée est rattachée
    à la table que nomme le paramètre `table_liee` du type, ou celui que donne
    `TypeRegle.rattachements` pour ce paramètre. Les colonnes des conditions et des
    exceptions sont citées sans nature attendue.
    """
    instance = _avec_defauts(instance)
    type_regle = TYPES[instance["type"]]
    table = instance["table"]
    liees = set(_tables_liees(instance).values())

    def table_liee(parametre):
        source = type_regle.rattachements.get(parametre, type_regle.table_liee)
        return instance.get(source) if source else None

    references = []
    for parametre, genre in type_regle.parametres.items():
        if parametre not in instance:
            continue
        valeur = instance[parametre]
        if genre in GENRES_COLONNE:
            references.append((parametre, table, valeur, genre))
        elif genre == GENRE_COLONNES:
            references.extend((parametre, table, colonne, GENRE_COLONNE) for colonne in valeur)
        elif genre == GENRE_COLONNES_NOMBRE:
            references.extend(
                (parametre, table, colonne, GENRE_COLONNE_NOMBRE) for colonne in valeur
            )
        elif genre == GENRE_FACTEURS:
            references.extend(
                (parametre, table, _facteur(element)["colonne"], GENRE_COLONNE_NOMBRE)
                for element in valeur
            )
        elif genre == GENRE_TERMES:
            references.extend(
                (parametre, table, colonne, GENRE_COLONNE_NOMBRE) for colonne in valeur
            )
        elif genre == GENRE_TERMES_LIES:
            references.extend(
                (parametre, table_liee(parametre), colonne, GENRE_COLONNE_NOMBRE)
                for colonne in valeur
            )
        elif genre == GENRE_MONTANTS:
            # Une colonne citée par plusieurs montants n'est rapportée qu'une fois.
            citees = []
            for montant in valeur:
                citees.append((parametre, table, montant["colonne"], GENRE_COLONNE_NOMBRE))
                citees.extend(
                    (parametre, table_liee(parametre), condition["colonne"], GENRE_COLONNE)
                    for condition in montant.get("conditions") or []
                )
                citees.extend(
                    (parametre, table_liee(parametre), colonne, GENRE_COLONNE_NOMBRE)
                    for colonne in montant["termes"]
                )
            references.extend(dict.fromkeys(citees))
        elif genre == GENRE_COLONNES_LIEES:
            references.extend(
                (parametre, table_liee(parametre), colonne, GENRE_COLONNE) for colonne in valeur
            )
        elif genre == GENRE_COLONNES_COMMUNES:
            for nom_table in (table, table_liee(parametre)):
                references.extend(
                    (parametre, nom_table, colonne, GENRE_COLONNE) for colonne in valeur
                )
        elif genre in GENRES_COLONNE_LIEE:
            references.append(
                (parametre, table_liee(parametre), valeur, GENRES_COLONNE_LIEE[genre])
            )
        elif genre == GENRE_CONDITIONS:
            nom_table = table_liee(parametre) if parametre in type_regle.rattachements else table
            references.extend(
                (parametre, nom_table, condition["colonne"], GENRE_COLONNE) for condition in valeur
            )
        elif genre == GENRE_EXCEPTIONS:
            for exception in valeur:
                for condition in exception["conditions"]:
                    references.append(
                        (parametre, *_colonne_qualifiee(condition["colonne"], table, liees),
                         GENRE_COLONNE)
                    )
    return references


def _colonnes_instance(instance: dict, table: str | None = None) -> list[str]:
    """Colonnes citées par une instance dans une table (la sienne par défaut).

    Dans l'ordre des paramètres de son type, chaque colonne une seule fois.
    """
    table = instance["table"] if table is None else table
    colonnes = []
    for _, nom_table, colonne, _ in _references(instance):
        if nom_table == table and colonne not in colonnes:
            colonnes.append(colonne)
    return colonnes


def _problemes_parametre(genre: str, valeur) -> list[str]:
    """Problèmes d'un paramètre selon son genre."""
    if genre in GENRES_COLONNE:
        return [] if _texte_attendu(valeur) else [f"un nom de colonne est attendu ({genre})"]
    if genre == GENRE_NOMBRE:
        return [] if _est_nombre(valeur) else ["un nombre est attendu"]
    if genre == GENRE_MOTIF_NUMERO:
        if not _texte_attendu(valeur):
            return ["une expression régulière est attendue"]
        try:
            expression = re.compile(valeur)
        except re.error as erreur:
            return [f"expression régulière invalide ({erreur})"]
        if GROUPE_NUMERO not in expression.groupindex:
            return [
                f"groupe nommé {GROUPE_NUMERO} attendu, par exemple "
                f"(?P<{GROUPE_NUMERO}>\\d{{6}})"
            ]
        return []
    if genre == GENRE_COMPARAISON:
        if valeur in COMPARAISONS:
            return []
        return [
            f"comparaison inconnue {valeur!r} (comparaisons possibles : "
            f"{', '.join(COMPARAISONS)})"
        ]
    if genre == GENRE_VALEURS:
        if not isinstance(valeur, list):
            return ["une liste de valeurs est attendue (liste vide [] pour n'en admettre aucune)"]
        return [
            f"{element!r} n'est pas un texte (mettre un nombre entre guillemets)"
            for element in valeur
            if not _texte_attendu(element)
        ]
    if genre == GENRE_BOOLEEN:
        return [] if isinstance(valeur, bool) else ["true ou false est attendu"]
    if genre == GENRE_FACTEURS:
        return _problemes_facteurs(valeur)
    if genre == GENRE_ARRONDI:
        if valeur in ARRONDIS:
            return []
        return [f"arrondi inconnu {valeur!r} (arrondis possibles : {', '.join(ARRONDIS)})"]
    if genre in (GENRE_COLONNES, GENRE_COLONNES_NOMBRE, GENRE_COLONNES_COMMUNES,
                 GENRE_COLONNES_LIEES):
        if not isinstance(valeur, list) or not valeur:
            return [f"une liste non vide de noms de colonnes est attendue ({genre})"]
        problemes = [
            f"{element!r} n'est pas un nom de colonne"
            for element in valeur
            if not _texte_attendu(element)
        ]
        if not problemes and len(set(valeur)) < len(valeur):
            problemes.append("colonne citée deux fois")
        return problemes
    if genre == GENRE_TABLE:
        return [] if _texte_attendu(valeur) else ["un nom de table est attendu"]
    if genre in GENRES_COLONNE_LIEE:
        return [] if _texte_attendu(valeur) else [f"un nom de colonne est attendu ({genre})"]
    if genre in (GENRE_TERMES, GENRE_TERMES_LIES):
        return _problemes_termes(valeur)
    if genre == GENRE_MONTANTS:
        return _problemes_montants(valeur)
    if genre == GENRE_CONDITIONS:
        return _problemes_conditions(valeur)
    if genre == GENRE_EXCEPTIONS:
        return _problemes_exceptions(valeur)
    if genre == GENRE_HORAIRES:
        return _problemes_horaires(valeur)
    if genre == GENRE_FERIES:
        return _problemes_feries(valeur)
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


def _problemes_termes(termes) -> list[str]:
    """Problèmes des termes : dictionnaire non vide, colonne vers coefficient."""
    if not isinstance(termes, dict) or not termes:
        return [
            "un dictionnaire non vide est attendu (colonne vers coefficient, par "
            "exemple {total_ht: 1, total_tva: 1})"
        ]
    problemes = []
    for colonne, coefficient in termes.items():
        if not _texte_attendu(colonne):
            problemes.append(f"{colonne!r} n'est pas un nom de colonne")
        elif not _est_nombre(coefficient):
            problemes.append(f"{colonne} : un nombre est attendu comme coefficient")
    return problemes


def _problemes_montants(montants) -> list[str]:
    """Problèmes des montants : liste de {colonne, conditions, termes}, conditions
    facultatives."""
    if not isinstance(montants, list) or not montants:
        return [
            "une liste non vide de montants est attendue (chaque montant commence par un "
            "tiret, avec les clés colonne, termes et, si besoin, conditions)"
        ]
    problemes = []
    for rang, montant in enumerate(montants, start=1):
        nom = f"montant n° {rang}"
        if not isinstance(montant, dict):
            problemes.append(
                f"{nom} : un dictionnaire est attendu (clés {', '.join(CLES_MONTANT)})"
            )
            continue
        inconnues = [str(cle) for cle in montant if cle not in CLES_MONTANT]
        if inconnues:
            problemes.append(
                f"{nom} : clé inconnue {', '.join(inconnues)} (clés possibles : "
                f"{', '.join(CLES_MONTANT)})"
            )
        manquantes = [cle for cle in ("colonne", "termes") if cle not in montant]
        if manquantes:
            problemes.append(f"{nom} : clé manquante ({', '.join(manquantes)})")
        if "colonne" in montant and not _texte_attendu(montant["colonne"]):
            problemes.append(f"{nom}, colonne : un nom de colonne est attendu")
        if "termes" in montant:
            problemes.extend(
                f"{nom}, termes : {probleme}" for probleme in _problemes_termes(montant["termes"])
            )
        if "conditions" in montant:
            problemes.extend(
                f"{nom}, {probleme}" if probleme.startswith("condition")
                else f"{nom}, conditions : {probleme}"
                for probleme in _problemes_conditions(montant["conditions"])
            )
    return problemes


def _problemes_facteurs(facteurs) -> list[str]:
    """Problèmes des facteurs : liste de colonnes, chacune écrite seule ou en
    dictionnaire {colonne, coefficient, constante, vide}."""
    if not isinstance(facteurs, list) or not facteurs:
        return [
            "une liste non vide de facteurs est attendue (chaque facteur commence par un "
            "tiret : une colonne, ou un dictionnaire de clés colonne, coefficient, "
            "constante et vide)"
        ]
    problemes = []
    for rang, element in enumerate(facteurs, start=1):
        nom = f"facteur n° {rang}"
        if isinstance(element, str):
            if not _texte_attendu(element):
                problemes.append(f"{nom} : un nom de colonne est attendu")
            continue
        if not isinstance(element, dict):
            problemes.append(
                f"{nom} : un nom de colonne ou un dictionnaire (clés {', '.join(CLES_FACTEUR)}) "
                "est attendu"
            )
            continue
        inconnues = [str(cle) for cle in element if cle not in CLES_FACTEUR]
        if inconnues:
            problemes.append(
                f"{nom} : clé inconnue {', '.join(inconnues)} (clés possibles : "
                f"{', '.join(CLES_FACTEUR)})"
            )
        if "colonne" not in element:
            problemes.append(f"{nom} : clé manquante (colonne)")
        elif not _texte_attendu(element["colonne"]):
            problemes.append(f"{nom}, colonne : un nom de colonne est attendu")
        problemes.extend(
            f"{nom}, {cle} : un nombre est attendu"
            for cle in CLES_FACTEUR[1:]
            if cle in element and not _est_nombre(element[cle])
        )
    return problemes


def _problemes_horaires(horaires) -> list[str]:
    """Problèmes des horaires : jour vers liste de créneaux {debut, fin}."""
    jours_possibles = f"jours possibles : {', '.join(CLES_HORAIRES)}"
    if not isinstance(horaires, dict) or not horaires:
        return [f"un dictionnaire non vide est attendu (jour vers créneaux, {jours_possibles})"]
    problemes = []
    for jour, creneaux in horaires.items():
        if jour not in CLES_HORAIRES:
            problemes.append(f"jour inconnu {jour!r} ({jours_possibles})")
            continue
        if not isinstance(creneaux, list):
            problemes.append(
                f"{jour} : une liste de créneaux est attendue (chaque créneau commence par "
                "un tiret, liste vide [] pour aucun)"
            )
            continue
        for rang, creneau in enumerate(creneaux, start=1):
            nom = f"{jour}, créneau n° {rang}"
            if not isinstance(creneau, dict) or set(creneau) != set(CLES_CRENEAU):
                problemes.append(f"{nom} : clés debut et fin attendues")
                continue
            bornes = [_minutes(creneau[cle]) for cle in CLES_CRENEAU]
            problemes.extend(
                f"{nom}, {cle} : une heure HH:MM entre guillemets est attendue "
                "(par exemple '07:30')"
                for cle, minutes in zip(CLES_CRENEAU, bornes)
                if minutes is None
            )
            if None not in bornes and bornes[0] >= bornes[1]:
                problemes.append(
                    f"{nom} : debut ({creneau['debut']}) n'est pas avant fin ({creneau['fin']})"
                )
    return problemes


def _problemes_feries(feries) -> list[str]:
    """Problèmes des jours fériés : année vers liste de dates AAAA-MM-JJ de cette année."""
    if not isinstance(feries, dict) or not feries:
        return ["un dictionnaire non vide est attendu (année vers liste de dates AAAA-MM-JJ)"]
    problemes, annees = [], set()
    for cle, jours in feries.items():
        annee = _annee_feries(cle)
        if annee is None:
            problemes.append(f"année {cle!r} : une année AAAA est attendue")
            continue
        if annee in annees:
            problemes.append(f"année {annee} déclarée deux fois")
            continue
        annees.add(annee)
        if not isinstance(jours, list):
            problemes.append(
                f"année {annee} : une liste de dates est attendue (liste vide [] pour aucune)"
            )
            continue
        vus = set()
        for valeur in jours:
            jour = _jour_ferie(valeur)
            if jour is None:
                problemes.append(f"année {annee} : {valeur!r} n'est pas une date AAAA-MM-JJ")
            elif jour.year != annee:
                problemes.append(f"année {annee} : {jour.isoformat()} n'est pas de cette année")
            elif jour in vus:
                problemes.append(f"année {annee} : {jour.isoformat()} déclaré deux fois")
            vus.add(jour)
    return problemes


def _problemes_conditions(conditions) -> list[str]:
    """Problèmes d'une liste de conditions {colonne, valeurs} ou {colonne, motif}."""
    if not isinstance(conditions, list) or not conditions:
        return ["une liste de conditions est attendue (chaque condition commence par un tiret)"]
    problemes = []
    for rang, condition in enumerate(conditions, start=1):
        nom = f"condition n° {rang}"
        if not isinstance(condition, dict):
            problemes.append(
                f"{nom} : un dictionnaire est attendu (clés colonne et valeurs ou motif)"
            )
            continue
        inconnues = [str(cle) for cle in condition if cle not in CLES_CONDITION]
        if inconnues:
            problemes.append(
                f"{nom} : clé inconnue {', '.join(inconnues)} (clés possibles : "
                f"{', '.join(CLES_CONDITION)})"
            )
        if "colonne" not in condition:
            problemes.append(f"{nom} : clé manquante (colonne)")
        tests = [cle for cle in CLES_TEST_CONDITION if cle in condition]
        if not tests:
            problemes.append(f"{nom} : clé manquante (valeurs ou motif)")
        elif len(tests) > 1:
            problemes.append(f"{nom} : valeurs ou motif attendu, pas les deux")
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
        if "motif" in condition:
            motif = condition["motif"]
            if not _texte_attendu(motif):
                problemes.append(
                    f"{nom}, motif : une expression régulière est attendue (entre "
                    "guillemets simples, par exemple 'FA-.*')"
                )
            else:
                try:
                    re.compile(motif)
                except re.error as erreur:
                    problemes.append(f"{nom}, motif : expression régulière invalide ({erreur})")
    return problemes


def _problemes_filtre(filtre) -> list[str]:
    """Problèmes d'un filtre : liste de conditions (voir `_problemes_conditions`)."""
    return _problemes_conditions(filtre)


def _problemes_exceptions(exceptions) -> list[str]:
    """Problèmes des exceptions : liste de {libelle, conditions}."""
    if not isinstance(exceptions, list) or not exceptions:
        return [
            "une liste d'exceptions est attendue (chaque exception commence par un tiret, "
            "avec les clés libelle et conditions)"
        ]
    problemes = []
    for rang, exception in enumerate(exceptions, start=1):
        nom = f"exception n° {rang}"
        if not isinstance(exception, dict):
            problemes.append(f"{nom} : un dictionnaire est attendu (clés libelle et conditions)")
            continue
        inconnues = [str(cle) for cle in exception if cle not in CLES_EXCEPTION]
        if inconnues:
            problemes.append(
                f"{nom} : clé inconnue {', '.join(inconnues)} (clés possibles : "
                f"{', '.join(CLES_EXCEPTION)})"
            )
        manquantes = [cle for cle in CLES_EXCEPTION if cle not in exception]
        if manquantes:
            problemes.append(f"{nom} : clé manquante ({', '.join(manquantes)})")
        if "libelle" in exception and not _texte_attendu(exception["libelle"]):
            problemes.append(f"{nom}, libelle : un texte non vide est attendu")
        if "conditions" in exception:
            problemes.extend(
                f"{nom}, {probleme}" if probleme.startswith("condition")
                else f"{nom}, conditions : {probleme}"
                for probleme in _problemes_conditions(exception["conditions"])
            )
    return problemes


def _problemes_prefixes(instance: dict) -> list[str]:
    """Colonnes d'exception écrites « t.c » dont t n'est pas une table liée de la règle."""
    type_regle = TYPES[instance["type"]]
    liees = list(_tables_liees(instance).values())
    problemes = []
    for parametre, genre in type_regle.parametres.items():
        if genre != GENRE_EXCEPTIONS or parametre not in instance:
            continue
        for rang, exception in enumerate(instance[parametre], start=1):
            for numero, condition in enumerate(exception["conditions"], start=1):
                prefixe, point, _ = condition["colonne"].partition(".")
                if point and prefixe not in liees:
                    problemes.append(
                        f"{parametre}, exception n° {rang}, condition n° {numero} : "
                        f"{prefixe} n'est pas une table liée de la règle (tables liées : "
                        f"{', '.join(liees)}); une colonne de la table de la règle "
                        "s'écrit sans préfixe"
                    )
    return problemes


def _figer(valeur):
    """Valeur d'un paramètre sous une forme comparable et hachable."""
    if isinstance(valeur, dict):
        return tuple(sorted((str(cle), _figer(v)) for cle, v in valeur.items()))
    if isinstance(valeur, list):
        return tuple(_figer(v) for v in valeur)
    return valeur


def _parametre_compare(genre: str, valeur):
    """Valeur d'un paramètre sous la forme où deux règles sont comparées : les facteurs
    d'un produit sous leur forme complète, dans un ordre fixe (un produit ne dépend pas
    de l'ordre de ses facteurs)."""
    if genre == GENRE_FACTEURS:
        return sorted((_figer(_facteur(element)) for element in valeur), key=repr)
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
        if len(problemes) == avant_parametres:
            problemes.extend(f"{nom}, {probleme}" for probleme in _problemes_prefixes(instance))
        if type_regle.verifier is not None and len(problemes) == avant_parametres:
            complete = _avec_defauts(instance)
            parametres = {p: complete[p] for p in type_regle.parametres if p in complete}
            problemes.extend(f"{nom} : {probleme}" for probleme in type_regle.verifier(parametres))
        if len(problemes) > deja:
            continue
        complete = _avec_defauts(instance)
        repere = (
            instance["type"],
            instance["table"],
            _figer(
                {
                    p: _parametre_compare(genre, complete[p])
                    for p, genre in type_regle.parametres.items()
                    if p in complete
                }
            ),
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
        absentes = set()
        for parametre, nom_table, colonne, genre in _references(instance):
            if nom_table not in tables:
                if nom_table not in absentes:
                    parametre_table = next(
                        p for p, t in _tables_liees(instance).items() if t == nom_table
                    )
                    problemes.append(
                        f"{nom}, {parametre_table} : table {nom_table} absente des "
                        "données chargées"
                    )
                    absentes.add(nom_table)
                continue
            if colonne not in _colonnes_de_donnees(tables[nom_table]):
                problemes.append(
                    f"{nom}, {parametre} : colonne {nom_table}.{colonne} absente des données "
                    "chargées"
                )
                continue
            regles_colonne = dictionnaire.get(nom_table, {}).get(colonne)
            if regles_colonne is None:
                problemes.append(
                    f"{nom}, {parametre} : colonne {nom_table}.{colonne} absente du "
                    "dictionnaire, à régénérer (notebook 02c_dictionnaire)"
                )
                continue
            nature = regles_colonne["nature"]["regle"]
            if genre in _NATURES_ATTENDUES:
                admises, attendu = _NATURES_ATTENDUES[genre]
                if nature not in admises:
                    problemes.append(
                        f"{nom}, {parametre} : la nature en vigueur de {nom_table}.{colonne} "
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
        if type_regle.prerequis_liees is not None:
            for parametre_table, nom_liee in _tables_liees(instance).items():
                if nom_liee in tables:
                    probleme = type_regle.prerequis_liees(tables[nom_liee])
                    if probleme:
                        problemes.append(
                            f"{nom}, {parametre_table} : table {nom_liee}, {probleme}"
                        )
    return problemes


def _dans_le_champ(donnees: pd.DataFrame, filtre) -> pd.Series:
    """Vrai pour une ligne qui remplit toutes les conditions du filtre.

    La valeur de la ligne est comparée telle quelle aux valeurs de la condition, ou à
    son motif (qui doit couvrir la valeur entière); une cellule vide ou faite
    d'espaces ne remplit aucune condition.
    """
    champ = pd.Series(True, index=donnees.index, dtype=bool)
    for condition in filtre or []:
        champ &= donnees[condition["colonne"]].map(
            lambda valeur, condition=condition: _condition_vraie(_texte_lu(valeur), condition)
        ).astype(bool)
    return champ


def _texte_lu(valeur) -> str | None:
    """Texte d'une cellule, None si elle est vide ou faite d'espaces."""
    texte = _valeur_constatee(valeur)
    return texte if texte is not None and texte.strip() else None


def _condition_vraie(texte: str | None, condition: dict) -> bool:
    """Vrai si le texte remplit la condition (valeurs, ou motif sur la valeur entière)."""
    if texte is None:
        return False
    if "valeurs" in condition:
        return texte in condition["valeurs"]
    return re.fullmatch(condition["motif"], texte) is not None


def _ecrire_condition(condition: dict) -> str:
    if "valeurs" in condition:
        return f"{condition['colonne']} = {' ou '.join(condition['valeurs'])}"
    return f"{condition['colonne']} suit le motif {condition['motif']}"


def _texte_filtre(filtre) -> str | None:
    """Filtre écrit pour le bilan : « statut = Réalisée ou Annulée et ... »."""
    if not filtre:
        return None
    return " et ".join(_ecrire_condition(condition) for condition in filtre)


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
    date_coupure: dt.date | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Applique les règles de gestion et rend les écarts et le bilan.

    `dictionnaire` est le dictionnaire enregistré : la nature en vigueur de chaque
    colonne dit comment la lire (voir `typage.lire`). `regles` vient de
    config/gestion.yaml par défaut (voir `charger_regles_gestion`). `declarations`
    (déclarations de doublons de config/controles.yaml par défaut) donne la clé de
    chaque table, affichée dans la colonne `cle`. `doublons` est la table rendue par
    `doublons.detecter_doublons`; elle n'est utile qu'aux types qui travaillent sans
    les doublons exacts en surnombre, et elle est calculée si elle manque.
    `date_coupure` est la fin de la période extraite (`Perimetre.date_coupure`),
    demandée par les types qui en ont besoin (par exemple pour un délai non échu).

    Avant tout contrôle, sont vérifiés, chacun avec la liste complète des
    problèmes : la classification de sensibilité (`RuntimeError`), la structure des
    règles, puis les tables, les colonnes et leur nature dans les données et le
    dictionnaire (`ValueError`).

    Les lignes en surnombre sont écartées d'abord (selon la vue du type), puis les
    lignes qui ne remplissent pas le filtre de la règle (hors champ), auxquelles
    s'ajoutent les lignes que le type laisse hors champ (par exemple une clé
    facultative vide). Pour un type
    qui rapproche plusieurs tables, chaque table liée est prise selon la même vue,
    sans filtre; ses colonnes sont écrites « table.colonne » dans la colonne
    `colonnes`.

    Table des écarts (`COLONNES_ECARTS_GESTION`) : une ligne par ligne source et
    par constat, avec le lignage, la référence, le type et le libellé de la règle,
    l'issue (celle que donne le type pour cet écart, par exemple « information »
    pour une pratique normale, sinon celle de la règle, sinon celle du type), le
    constat, les colonnes en
    cause, la clé de la ligne, la valeur constatée (ou celle que donne le type, par
    exemple la plage des numéros manquants) et la correction proposée par l'outil,
    le cas échéant. Clé, valeur et proposition valent « masqué » dès
    qu'une de leurs colonnes est sensible. Les écarts suivent l'ordre des règles,
    puis celui des lignes sources.

    Bilan (`COLONNES_BILAN_GESTION`) : une ligne par règle, avec son filtre et les
    nombres de lignes de la table, de lignes écartées comme doublons exacts en
    surnombre, de lignes hors champ, de lignes non évaluables et contrôlées (ces
    quatre nombres font le total), d'anomalies, d'écarts à arbitrer et
    d'informations, et les avertissements de la règle (par exemple une année des
    données sans jours fériés déclarés), séparés par « ; », None s'il n'y en a pas.
    Les arguments ne sont pas modifiés.
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
    if not problemes and date_coupure is None:
        problemes = [
            f"{_nommer(rang, instance)} : la date de coupure des données est attendue "
            "(argument date_coupure, perimetre.date_coupure dans le notebook)"
            for rang, instance in enumerate(regles, start=1)
            if CONTEXTE_DATE_COUPURE in TYPES[instance["type"]].contexte
        ]
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
        vue_complete = vue
        dans_champ = _dans_le_champ(vue, filtre)
        hors_champ = int((~dans_champ).sum())
        vue = vue[dans_champ]
        complete = _avec_defauts(instance)
        parametres = {p: complete[p] for p in type_regle.parametres if p in complete}
        contexte = {
            CONTEXTE_DATE_COUPURE: date_coupure,
            CONTEXTE_VUE_COMPLETE: vue_complete,
            CONTEXTE_TABLE: table,
        }
        for nom_contexte in type_regle.contexte:
            parametres[nom_contexte] = contexte[nom_contexte]
        liees = {}
        for parametre_table, nom_liee in _tables_liees(instance).items():
            colonnes_liees = _colonnes_instance(instance, nom_liee)
            donnees_liees = tables[nom_liee].reset_index(drop=True)
            if type_regle.vue == VUE_SANS_SURNOMBRE:
                donnees_liees = donnees_liees.drop(
                    index=_positions_en_surnombre(doublons, nom_liee, donnees_liees)
                )
            liees[parametre_table] = Liee(
                nom_liee,
                donnees_liees,
                {c: dictionnaire[nom_liee][c]["nature"]["regle"] for c in colonnes_liees},
            )
        if type_regle.tables_liees:
            constats = type_regle.controler(vue, parametres, natures, liees)
        elif liees:
            constats = type_regle.controler(vue, parametres, natures, *liees.values())
        else:
            constats = type_regle.controler(vue, parametres, natures)
        colonnes_liees = {}
        for liee in liees.values():
            colonnes_liees.setdefault(liee.table, list(liee.natures))
        texte_colonnes = ", ".join(
            [
                *colonnes,
                *(
                    f"{nom_liee}.{colonne}"
                    for nom_liee, noms in colonnes_liees.items()
                    for colonne in noms
                ),
            ]
        )
        ecarts = constats.ecarts
        issues = pd.Series(issue, index=ecarts.index, dtype=object)
        if "issue" in ecarts.columns:
            issues = ecarts["issue"].where(ecarts["issue"].notna(), issue).astype(object)
        periodes = constats.ecarts_periodes
        if periodes is None:
            periodes = pd.DataFrame(columns=["constat", "cle", "valeur"])
        issues_periodes = pd.Series(issue, index=periodes.index, dtype=object)
        if "issue" in periodes.columns:
            issues_periodes = (
                periodes["issue"].where(periodes["issue"].notna(), issue).astype(object)
            )
        toutes_issues = pd.concat([issues, issues_periodes], ignore_index=True)
        hors_type = constats.hors_champ
        if hors_type is None:
            hors_type = pd.Series(False, index=constats.evaluables.index, dtype=bool)
        commun = {
            "ref": instance["ref"],
            "type": instance["type"],
            "libelle": instance["libelle"],
            "table": table,
        }
        bilan.append(
            {
                **commun,
                "colonnes": texte_colonnes,
                "vue": type_regle.vue,
                "filtre": _texte_filtre(filtre),
                "lignes": len(donnees),
                "ecartees_doublons": len(ecartees),
                "hors_champ": hors_champ + int(hors_type.sum()),
                "non_evaluables": int((~constats.evaluables & ~hors_type).sum()),
                "controlees": int(constats.evaluables.sum()),
                "anomalies": int((toutes_issues == ISSUE_ANOMALIE).sum()),
                "a_arbitrer": int((toutes_issues == ISSUE_A_ARBITRER).sum()),
                "informations": int((toutes_issues == ISSUE_INFORMATION).sum()),
                "avertissements": "; ".join(constats.avertissements) or None,
            }
        )
        sensible = _sensible(sensibles, table, regles_colonnes, colonnes) or any(
            _sensible(sensibles, nom_liee, dictionnaire[nom_liee], noms)
            for nom_liee, noms in colonnes_liees.items()
        )
        if not periodes.empty:
            masquer = [VALEUR_MASQUEE] * len(periodes)
            morceau_periodes = pd.DataFrame(
                {
                    "_position": range(len(periodes)),
                    **commun,
                    "issue": issues_periodes.to_numpy(),
                    "constat": periodes["constat"].to_numpy(),
                    "colonnes": texte_colonnes,
                    "cle": pd.Series(
                        masquer if sensible else list(periodes["cle"]), dtype=object
                    ).to_numpy(),
                    "valeur": pd.Series(
                        masquer if sensible else list(periodes["valeur"]), dtype=object
                    ).to_numpy(),
                    "proposition": None,
                }
            )
            for lignage in COLONNES_LIGNAGE_ECART:
                morceau_periodes[lignage] = None
            morceau_periodes["_regle"] = rang
            morceau_periodes["_sans_ligne"] = 1
            morceaux.append(morceau_periodes)
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
        if sensible:
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
            if "valeur" in ecarts.columns:
                valeurs = [
                    donnee if _renseignee(donnee) else valeur
                    for valeur, donnee in zip(valeurs, ecarts["valeur"])
                ]
            propositions = list(ecarts["proposition"])
        morceau = pd.DataFrame(
            {
                "_position": positions,
                **commun,
                "issue": issues.to_numpy(),
                "constat": ecarts["constat"].to_numpy(),
                "colonnes": texte_colonnes,
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
        morceau["_sans_ligne"] = 0
        morceaux.append(morceau)

    if morceaux:
        ecarts = pd.concat(morceaux, ignore_index=True).sort_values(
            ["_regle", "_sans_ligne", *COLONNES_LIGNAGE_ECART, "_position"],
            kind="stable",
            na_position="first",
        )
        ecarts = ecarts[list(COLONNES_ECARTS_GESTION)].reset_index(drop=True)
    else:
        ecarts = pd.DataFrame(columns=list(COLONNES_ECARTS_GESTION))
    return ecarts, pd.DataFrame(bilan, columns=list(COLONNES_BILAN_GESTION))
