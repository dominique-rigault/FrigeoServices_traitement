"""Règles de nettoyage (étape 6).

Ce module ne contient rien de propre à un client. Il applique aux tables chargées
des règles de nettoyage explicites, dans un ordre fixé ici, sans jamais modifier les
tables reçues : `nettoyer` travaille sur une copie, et chaque ligne garde son
lignage. Chaque règle tire ses paramètres de ce qui existe déjà (règle générique,
dictionnaire, déclarations de doublons, décisions du métier) : aucun fichier de
configuration ne lui est propre.

La représentation de la source est conservée : une date en texte reste un texte,
un nombre natif reste un nombre, seule la valeur change. Les contrôles des étapes 3
à 5 s'appliquent donc sans changement aux tables nettoyées; la conversion des types
relève du chargement en base (voir `typage.lire`).

Une valeur que la règle ne sait pas corriger sans ambiguïté reste telle quelle : elle
reste une anomalie, et le bilan dit pourquoi elle n'a pas été corrigée. Rien n'est
deviné.

Règles, dans l'ordre (voir `catalogue_nettoyage`) :

- `encodage` : réparation des textes UTF-8 relus dans un encodage d'un octet
  (Windows-1252, ISO-8859-15 ou Latin-1), repérés comme à l'étape 3 par
  `controles.constats_encodage` (voir `reparer_encodage`);
- `remplacement` : une valeur invalidée par le métier dans la liste fermée de sa
  colonne et qui porte un remplacement au dictionnaire reçoit ce remplacement;
- `nature` : une valeur hors de la nature de date, d'heure ou de nombre de sa
  colonne est lue dans une forme élargie de la même famille, sans ambiguïté et
  sans perte, puis écrite dans la représentation de cette nature;
- `doublons` : les lignes en surnombre des doublons exacts sont retirées, la
  première occurrence de chaque groupe étant gardée (comme la vue « sans les
  doublons exacts en surnombre » des règles de gestion);
- `decision` : les décisions du métier prises dans le classeur d'arbitrage
  (`decisions.py`, data/config/decisions.yaml) : une cellule reçoit la valeur
  retenue par le métier, une ligne est retirée, à condition que la donnée n'ait
  pas changé depuis la décision.

Chaque règle s'applique aux valeurs laissées par les règles précédentes.

`nettoyer` rend les tables nettoyées, le journal des corrections (une ligne par
cellule modifiée, avec sa valeur avant et après) et un bilan par règle et par
colonne. `comparer_anomalies` compare, contrôle par contrôle, la table des
anomalies des tables brutes et celle des tables nettoyées. Rien n'est écrit sur
disque.
"""

from __future__ import annotations

import datetime as dt
import numbers
import re
from collections import Counter, namedtuple
from decimal import Decimal

import pandas as pd

from .confidentialite import charger_sensibilite, est_sensible, verifier_sensibilite
from .controles import (
    CARACTERE_REMPLACEMENT,
    COLONNES_LIGNAGE_ECART,
    ENCODAGES_SUSPECTS,
    ISSUE_A_ARBITRER,
    ISSUE_ANOMALIE,
    VALEUR_MASQUEE,
    _REPERTOIRE,
    _SEQUENCE_UTF8,
    _colonnes_de_donnees,
    _issue_element,
    _octets,
    _problemes_de_correspondance,
    _valeur_constatee,
    constats_encodage,
)
from .dictionnaire import (
    LISTE_FERMEE,
    _valeurs_renseignees,
    est_masquee,
    problemes_dictionnaire,
)
from .anomalies import _index_lignage
from .gestion import ISSUE_INFORMATION
from .anomalies import _repere as _repere_anomalie
from .doublons import (
    COMPARAISON_NORMALISEE,
    CONSTAT_EXACT,
    SEPARATEUR,
    _texte,
    charger_declarations_doublons,
    detecter_doublons,
)
from .profilage import _interpretations, signature
from .typage import NATURES_DATE, NATURES_HEURE, NATURES_LISIBLES, ecrire_date

REGLE_ENCODAGE = "encodage"
REGLE_REMPLACEMENT = "remplacement"
REGLE_NATURE = "nature"
REGLE_DOUBLONS = "doublons"
REGLE_DECISION = "decision"
REGLES_NETTOYAGE = (
    REGLE_ENCODAGE, REGLE_REMPLACEMENT, REGLE_NATURE, REGLE_DOUBLONS, REGLE_DECISION
)

ACTION_MODIFIEE = "valeur modifiée"
ACTION_RETIREE = "ligne retirée"
SOURCE_GENERIQUE = "règle générique"
SOURCE_DICTIONNAIRE = "dictionnaire"
SOURCE_DECISION = "décision du métier"

RAISON_REMPLACEMENT = "caractère de remplacement"
RAISON_DESACCORD = "encodages en désaccord"
MAX_PASSES = 5
RAISON_PASSES = f"séquence toujours présente après {MAX_PASSES} passes"
RAISONS_ENCODAGE = (RAISON_REMPLACEMENT, RAISON_DESACCORD, RAISON_PASSES)

RAISON_SANS_REMPLACEMENT = "valeur invalidée sans remplacement"
RAISON_HORS_LISTE = "valeur hors liste"
RAISON_NON_TEXTUELLE = "valeur non textuelle"
RAISONS_REMPLACEMENT = (RAISON_SANS_REMPLACEMENT, RAISON_HORS_LISTE, RAISON_NON_TEXTUELLE)

RAISON_DATE_IMPOSSIBLE = "date impossible"
RAISON_DATE_FUTURE = "année sur deux chiffres, date future"
RAISON_SANS_COUPURE = "année sur deux chiffres, date de coupure non fournie"
RAISON_HEURE = "date avec une heure"
RAISON_UNITE = "valeur avec une unité"
RAISON_SEPARATEUR = "séparateur ambigu"
RAISON_DECIMALES = "partie décimale non nulle"
RAISON_AUTRE_FAMILLE = "autre famille de nature"
RAISON_NON_RECONNUE = "forme non reconnue"
RAISONS_NATURE = (
    RAISON_DATE_IMPOSSIBLE,
    RAISON_DATE_FUTURE,
    RAISON_SANS_COUPURE,
    RAISON_HEURE,
    RAISON_UNITE,
    RAISON_SEPARATEUR,
    RAISON_DECIMALES,
    RAISON_AUTRE_FAMILLE,
    RAISON_NON_RECONNUE,
)

RAISON_LIGNAGE_AMBIGU = "lignage ambigu"
RAISONS_DOUBLONS = (RAISON_LIGNAGE_AMBIGU,)

RAISON_SOURCE_MODIFIEE = "source modifiée depuis la décision"
RAISON_INTROUVABLE = "ligne source introuvable"
RAISON_ILLISIBLE = "valeur retenue illisible dans la nature en vigueur"
RAISONS_DECISION = (RAISON_SOURCE_MODIFIEE, RAISON_INTROUVABLE, RAISON_ILLISIBLE)

COLONNE_PERIODE = "periode_export"
COLONNES_JOURNAL = (
    "regle_nettoyage",
    "table",
    *COLONNES_LIGNAGE_ECART,
    COLONNE_PERIODE,
    "cle",
    "colonne",
    "action",
    "source",
    "valeur_avant",
    "valeur_apres",
    "detail",
)
COLONNES_BILAN_NETTOYAGE = (
    "regle_nettoyage",
    "table",
    "colonne",
    "visees",
    "corrigees",
    "non_corrigees",
    "raisons",
)
COLONNES_CATALOGUE_NETTOYAGE = ("rang", "regle_nettoyage", "source", "corrige", "ne_corrige_jamais")

_CATALOGUE = {
    REGLE_ENCODAGE: (
        SOURCE_GENERIQUE,
        "toute cellule de texte signalée par la règle encodage de l'étape 3 : chaque "
        "séquence d'un texte UTF-8 relu en Windows-1252, ISO-8859-15 ou Latin-1 est "
        f"remplacée par son caractère, passe après passe, au plus {MAX_PASSES} passes",
        "une cellule qui contient le caractère de remplacement (information perdue); "
        "une portion de texte que deux encodages réparent en deux caractères "
        f"différents; une séquence encore présente après {MAX_PASSES} passes",
    ),
    REGLE_REMPLACEMENT: (
        SOURCE_DICTIONNAIRE,
        "toute cellule de texte dont la valeur, invalidée par le métier dans la liste "
        "fermée de sa colonne, porte un remplacement au dictionnaire : elle reçoit ce "
        "remplacement (valeur comparée telle quelle, comme au contrôle)",
        "une valeur hors liste ou à arbitrer; une valeur invalidée sans remplacement; "
        "une cellule qui n'est pas un texte",
    ),
    REGLE_NATURE: (
        SOURCE_GENERIQUE,
        "toute cellule hors de la nature de date, d'heure ou de nombre de sa colonne, "
        "lue dans une forme de la même famille et écrite dans la représentation de la "
        "nature : dates JJ/MM/AAAA, JJ.MM.AAAA, JJ-MM-AAAA, AAAA-MM-JJ, AAAAMMJJ, date "
        "native, et JJ/MM/AA (ou point, tiret) en 20AA si la date ne dépasse pas la "
        "date de coupure; nombres entiers, décimaux à virgule ou à point, espace "
        "séparateur de milliers, symbole € en fin de valeur",
        "une date impossible; une année sur deux chiffres qui donnerait une date "
        "postérieure à la date de coupure; une date avec une heure écrite dans une "
        "colonne de dates en texte; une valeur avec une unité (1h30, 45 min); un point "
        "suivi de trois chiffres (séparateur ambigu); une partie décimale non nulle "
        "vers un entier; une valeur d'une autre famille (nombre dans une colonne de "
        "dates); une heure hors de la forme HH:MM",
    ),
    REGLE_DOUBLONS: (
        SOURCE_GENERIQUE,
        "toute ligne en surnombre d'un groupe de doublons exacts (lignes identiques "
        "hors lignage, telles quelles ou après normalisation), cherchés sur les tables "
        "issues des règles précédentes : la ligne est retirée, la première occurrence "
        "du groupe est gardée",
        "une valeur en double (clé répétée sur des lignes différentes); des lignes "
        "identiques hors clé; une ligne dont le lignage désigne plusieurs lignes",
    ),
    REGLE_DECISION: (
        SOURCE_DECISION,
        "toute cellule que le métier a décidé de corriger, et toute ligne qu'il a "
        "décidé de retirer, dans le classeur d'arbitrage (data/config/decisions.yaml) : "
        "la cellule reçoit la valeur retenue, écrite dans la représentation de la "
        "nature de sa colonne, ou la ligne est retirée, si la donnée n'a pas changé "
        "depuis la décision (même empreinte); corrections d'abord, retraits ensuite",
        "une donnée modifiée depuis la décision (source corrigée ou réexportée); une "
        "ligne source introuvable; une valeur retenue illisible dans la nature en "
        "vigueur de sa colonne; un élément que le métier a décidé de garder",
    ),
}

Nettoyage = namedtuple("Nettoyage", ["tables", "journal", "bilan"])
Nettoyage.__doc__ = """Résultat de `nettoyer` : tables nettoyées, journal et bilan."""

Reparation = namedtuple("Reparation", ["texte", "raison", "passes", "encodages"])
Reparation.__doc__ = """Résultat de `reparer_encodage`.

`texte` est le texte réparé (le texte reçu s'il n'y avait rien à réparer), None si
la réparation est refusée; `raison` dit pourquoi elle l'est (None sinon);
`passes` est le nombre de passes qui ont modifié le texte; `encodages` les encodages
qui ont repéré au moins une séquence, dans l'ordre de `ENCODAGES_SUSPECTS`.
"""


def catalogue_nettoyage() -> pd.DataFrame:
    """Règles de nettoyage dans leur ordre d'application, avec leur source, ce
    qu'elles corrigent et ce qu'elles ne corrigent jamais."""
    return pd.DataFrame(
        [
            {
                "rang": rang,
                "regle_nettoyage": regle,
                "source": _CATALOGUE[regle][0],
                "corrige": _CATALOGUE[regle][1],
                "ne_corrige_jamais": _CATALOGUE[regle][2],
            }
            for rang, regle in enumerate(REGLES_NETTOYAGE, start=1)
        ],
        columns=list(COLONNES_CATALOGUE_NETTOYAGE),
    )


def _portions(texte: str, encodage: str) -> dict[tuple[int, int], str]:
    """Portions du texte à remplacer pour un encodage : {(début, fin): caractère}.

    Le texte est réécrit dans l'encodage comme pour le contrôle (`_octets`); ces
    encodages étant d'un octet, la position d'un octet est celle de son caractère.
    Seules comptent les séquences dont le caractère appartient au répertoire des
    encodages suspects, comme pour le contrôle.
    """
    portions = {}
    for trouve in _SEQUENCE_UTF8.finditer(_octets(texte, encodage)):
        caractere = trouve.group().decode("utf-8")
        if caractere in _REPERTOIRE:
            portions[(trouve.start(), trouve.end())] = caractere
    return portions


def _appliquer(texte: str, portions: dict[tuple[int, int], str]) -> str:
    morceaux, fin = [], 0
    for (debut, suite), caractere in sorted(portions.items()):
        morceaux.append(texte[fin:debut])
        morceaux.append(caractere)
        fin = suite
    morceaux.append(texte[fin:])
    return "".join(morceaux)


def _reunir(par_encodage: list[dict]) -> dict | None:
    """Réparations de tous les encodages, None si deux d'entre elles se contredisent
    (portions qui se chevauchent sans être la même portion réparée par le même
    caractère)."""
    reunies: dict[tuple[int, int], str] = {}
    for portions in par_encodage:
        for portion, caractere in portions.items():
            for autre, sien in reunies.items():
                chevauche = portion[0] < autre[1] and autre[0] < portion[1]
                if chevauche and (portion, caractere) != (autre, sien):
                    return None
            reunies[portion] = caractere
    return reunies


def reparer_encodage(texte: str) -> Reparation:
    """Répare un texte UTF-8 relu dans un encodage d'un octet.

    À chaque passe, chaque encodage de `ENCODAGES_SUSPECTS` donne les séquences
    qu'il repère (comme `controles.constats_encodage`), chacune remplacée par son
    caractère, le reste du texte étant gardé tel quel. Les réparations des
    encodages sont réunies : elles ne sont refusées que si une même portion de texte
    est réparée en deux caractères différents (`Ã€` donne `À` en Windows-1252 et
    `ä` en ISO-8859-15). Les passes se répètent tant qu'une séquence reste (texte
    mal décodé plusieurs fois), au plus `MAX_PASSES`.

    Réparation refusée, avec sa raison : texte qui contient le caractère de
    remplacement (non touché, l'information est perdue), réparations en désaccord,
    séquence encore présente après `MAX_PASSES` passes. Un texte sans séquence est
    rendu tel quel, avec 0 passe.
    """
    if CARACTERE_REMPLACEMENT in texte:
        return Reparation(None, RAISON_REMPLACEMENT, 0, ())
    reperent: set[str] = set()

    def encodages() -> tuple[str, ...]:
        return tuple(e for e in ENCODAGES_SUSPECTS if e in reperent)

    for passe in range(MAX_PASSES):
        par_encodage = {e: _portions(texte, e) for e in ENCODAGES_SUSPECTS}
        par_encodage = {e: p for e, p in par_encodage.items() if p}
        if not par_encodage:
            return Reparation(texte, None, passe, encodages())
        reperent.update(par_encodage)
        reunies = _reunir(list(par_encodage.values()))
        if reunies is None:
            return Reparation(None, RAISON_DESACCORD, passe + 1, encodages())
        texte = _appliquer(texte, reunies)
    if any(_portions(texte, e) for e in ENCODAGES_SUSPECTS):
        return Reparation(None, RAISON_PASSES, MAX_PASSES, encodages())
    return Reparation(texte, None, MAX_PASSES, encodages())


def _detail_encodage(reparation: Reparation) -> str:
    passes = "1 passe" if reparation.passes == 1 else f"{reparation.passes} passes"
    return f"repéré en {', '.join(reparation.encodages)}; {passes}"


def _encodage(serie: pd.Series, regles: dict, contexte: dict):
    """Règle `encodage` sur une colonne indexée par la position des lignes.

    Rend None si aucune cellule n'est visée, sinon (positions visées, {position:
    (valeur corrigée, détail)}, Counter des raisons). Les cellules visées sont
    celles que la règle `encodage` de l'étape 3 signale (séquence d'un mauvais
    décodage ou caractère de remplacement). `regles` (règles de la colonne au
    dictionnaire) et `contexte` (date de coupure, colonne masquée) ne servent pas
    à cette règle.
    """
    presentes = _valeurs_renseignees(serie)
    textes = presentes[[isinstance(v, str) for v in presentes]]
    suspects = {v for v in textes.unique() if constats_encodage(v)}
    if not suspects:
        return None
    visees = textes[textes.isin(suspects)]
    reparations = {v: reparer_encodage(v) for v in suspects}
    acceptees, raisons = {}, Counter()
    for position, valeur in visees.items():
        reparation = reparations[valeur]
        if reparation.texte is None:
            raisons[reparation.raison] += 1
        elif reparation.texte != valeur:
            acceptees[position] = (reparation.texte, _detail_encodage(reparation))
        else:
            # Hors caractère de remplacement, une cellule signalée a toujours une
            # séquence à réparer : ce cas ne se produit pas, il serait compté plutôt
            # que passé sous silence.
            raisons[RAISON_PASSES] += 1
    return list(visees.index), acceptees, raisons


def _remplacement(serie: pd.Series, regles: dict, contexte: dict):
    """Règle `remplacement` sur une colonne indexée par la position des lignes.

    Rendu comme `_encodage`. Les cellules visées sont celles que la règle
    `valeurs` de l'étape 3 met en anomalie (valeur invalide ou hors liste d'une
    liste fermée), la valeur étant comparée telle quelle, comme au contrôle. Une
    valeur invalide qui porte un remplacement est remplacée si la cellule est un
    texte.
    """
    regle = regles["valeurs"]
    if regle["regle"] != LISTE_FERMEE:
        return None
    presentes = _valeurs_renseignees(serie)
    if presentes.empty:
        return None
    connus = {element["valeur"]: element for element in regle["liste"]}
    textes = presentes.astype(str)
    issues = textes.map({t: _issue_element(connus.get(t)) for t in textes.unique()})
    visees = issues[issues.isin(("invalide", "hors liste"))]
    if visees.empty:
        return None
    acceptees, raisons = {}, Counter()
    for position, issue in visees.items():
        if issue == "hors liste":
            raisons[RAISON_HORS_LISTE] += 1
            continue
        element = connus[textes[position]]
        if element.get("remplacement") is None:
            raisons[RAISON_SANS_REMPLACEMENT] += 1
        elif not isinstance(presentes[position], str):
            raisons[RAISON_NON_TEXTUELLE] += 1
        else:
            acceptees[position] = (element["remplacement"], _detail_remplacement(element))
    return list(visees.index), acceptees, raisons


def _detail_remplacement(element: dict) -> str:
    """Date de la revue qui a invalidé la valeur (le dictionnaire validé exige
    `revu_le` pour une valeur invalide)."""
    return f"valeur invalidée le {str(element['revu_le'])[:10]}"


# --- Règle nature ---------------------------------------------------------------

# Espace ordinaire, insécable ou fine insécable.
_ESPACES = "[ " + chr(0xA0) + chr(0x202F) + "]"
_DATE_JJ_MM_AAAA = re.compile(r"(\d{2})([/.-])(\d{2})\2(\d{4})")
_DATE_JJ_MM_AA = re.compile(r"(\d{2})([/.-])(\d{2})\2(\d{2})")
_DATE_AAAA_MM_JJ = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_DATE_AAAAMMJJ = re.compile(r"(\d{4})(\d{2})(\d{2})")
_HEURE = re.compile(r"\d{2}:\d{2}")
_EURO = re.compile(f"(?P<corps>.*?)(?:{_ESPACES}?€)?")
_ENTIER = re.compile(r"(-?)(\d+)")
_VIRGULE = re.compile(r"(-?)(\d+),(\d+)")
_POINT = re.compile(r"(-?)(\d+)\.(\d+)")
_MILLIERS = re.compile(f"(-?)(\\d{{1,3}}(?:{_ESPACES}\\d{{3}})+)(?:,(\\d+))?")


class _Refus(str):
    """Raison d'un refus, distincte d'une valeur convertie en texte."""


def _famille(nature: str) -> str:
    if nature in NATURES_DATE:
        return "date"
    if nature in NATURES_HEURE:
        return "heure"
    return "nombre"


def _date_native(valeur) -> bool:
    return isinstance(valeur, (dt.date, pd.Timestamp))


def _nombre_natif(valeur) -> bool:
    return isinstance(valeur, numbers.Real) and not isinstance(valeur, bool)


def _lire_date(texte: str, date_coupure):
    """(date, siècle ajouté) ou raison du refus, None si la forme n'est pas une date."""
    for motif, ordre in (
        (_DATE_JJ_MM_AAAA, (4, 3, 1)),
        (_DATE_AAAA_MM_JJ, (1, 2, 3)),
        (_DATE_AAAAMMJJ, (1, 2, 3)),
    ):
        trouve = motif.fullmatch(texte)
        if trouve:
            annee, mois, jour = (int(trouve.group(i)) for i in ordre)
            try:
                return dt.datetime(annee, mois, jour), False
            except ValueError:
                return RAISON_DATE_IMPOSSIBLE
    trouve = _DATE_JJ_MM_AA.fullmatch(texte)
    if trouve:
        try:
            date = dt.datetime(2000 + int(trouve.group(4)), int(trouve.group(3)),
                               int(trouve.group(1)))
        except ValueError:
            return RAISON_DATE_IMPOSSIBLE
        if date_coupure is None:
            return RAISON_SANS_COUPURE
        if pd.Timestamp(date) > pd.Timestamp(date_coupure):
            return RAISON_DATE_FUTURE
        return date, True
    return None


def _lire_nombre(texte: str):
    """(signe, chiffres entiers, chiffres décimaux) ou raison du refus, None si la
    forme n'est pas un nombre. Le symbole € en fin de valeur est admis."""
    corps = _EURO.fullmatch(texte).group("corps")
    for motif in (_ENTIER, _VIRGULE, _POINT, _MILLIERS):
        trouve = motif.fullmatch(corps)
        if trouve:
            signe, entiers = trouve.group(1), re.sub(_ESPACES, "", trouve.group(2))
            decimales = trouve.group(3) if motif is not _ENTIER else None
            if motif is _POINT and len(decimales) == 3:
                return RAISON_SEPARATEUR
            return signe, entiers, decimales or ""
    return None


def _a_une_unite(texte: str) -> bool:
    return any(c.isdigit() for c in texte) and any(c.isalpha() for c in texte)


def _ecrire_nombre(signe: str, entiers: str, decimales: str, nature: str):
    """Valeur dans la représentation de la nature, ou `_Refus` avec sa raison.

    Un nombre en texte est réécrit à partir des chiffres lus, sans passer par un
    flottant; un entier sans partie décimale reçoit la décimale 0 dans une nature
    décimale.
    """
    if nature == "nombre natif":
        return float(Decimal(f"{signe}{entiers}.{decimales or '0'}"))
    if nature == "entier (texte)":
        if decimales.strip("0"):
            return _Refus(RAISON_DECIMALES)
        return f"{signe}{entiers}"
    separateur = "," if nature == "décimal virgule (texte)" else "."
    return f"{signe}{entiers}{separateur}{decimales or '0'}"


def _convertir(valeur, nature: str, date_coupure):
    """(valeur convertie, forme lue, siècle ajouté) ou raison du refus."""
    famille = _famille(nature)
    if isinstance(valeur, str):
        date = _lire_date(valeur, date_coupure)
        nombre = _lire_nombre(valeur)
    else:
        date = (pd.Timestamp(valeur).to_pydatetime(), False) if _date_native(valeur) else None
        nombre = _decomposer(valeur) if _nombre_natif(valeur) else None
    if famille == "date":
        if isinstance(date, str):
            return date
        if date is not None:
            instant, siecle = date
            if nature == "date native":
                return instant, siecle
            if instant != instant.replace(hour=0, minute=0, second=0, microsecond=0):
                return RAISON_HEURE
            return ecrire_date(instant, nature), siecle
        if nombre is not None or (isinstance(valeur, str) and _HEURE.fullmatch(valeur)):
            return RAISON_AUTRE_FAMILLE
        return RAISON_NON_RECONNUE
    if famille == "nombre":
        if isinstance(nombre, str):
            return nombre
        if nombre is not None:
            ecrit = _ecrire_nombre(*nombre, nature)
            return str(ecrit) if isinstance(ecrit, _Refus) else (ecrit, False)
        if date is not None:
            return RAISON_AUTRE_FAMILLE
        if isinstance(valeur, str) and _a_une_unite(valeur):
            return RAISON_UNITE
        return RAISON_NON_RECONNUE
    if date is not None or nombre is not None:
        return RAISON_AUTRE_FAMILLE
    return RAISON_NON_RECONNUE


def _decomposer(nombre) -> tuple[str, str, str]:
    """Signe, chiffres entiers et chiffres décimaux d'un nombre natif."""
    texte = format(Decimal(str(nombre)), "f")
    signe = "-" if texte.startswith("-") else ""
    entiers, _, decimales = texte.lstrip("-").partition(".")
    return signe, entiers, decimales


def _nature(serie: pd.Series, regles: dict, contexte: dict):
    """Règle `nature` sur une colonne indexée par la position des lignes.

    Rendu comme `_encodage`. Les cellules visées sont celles que la règle `nature`
    de l'étape 3 met hors nature, pour une nature de date, d'heure ou de nombre.
    Une valeur est lue dans une forme élargie de la même famille que la nature en
    vigueur (voir `catalogue_nettoyage`), puis écrite dans la représentation de
    cette nature.
    """
    nature = regles["nature"]["regle"]
    if nature not in NATURES_LISIBLES:
        return None
    presentes = _valeurs_renseignees(serie)
    if presentes.empty:
        return None
    conformes = _interpretations(presentes)[nature].index
    visees = presentes[~presentes.index.isin(conformes)]
    if visees.empty:
        return None
    acceptees, raisons = {}, Counter()
    for position, valeur in visees.items():
        resultat = _convertir(valeur, nature, contexte["date_coupure"])
        if isinstance(resultat, str):
            raisons[resultat] += 1
            continue
        convertie, siecle = resultat
        forme = "forme masquée" if contexte["masquee"] else f"forme lue {signature(valeur)}"
        acceptees[position] = (convertie, forme + (", siècle 20 ajouté" if siecle else ""))
    return list(visees.index), acceptees, raisons


_REGLES = {
    REGLE_ENCODAGE: (_encodage, SOURCE_GENERIQUE, RAISONS_ENCODAGE),
    REGLE_REMPLACEMENT: (_remplacement, SOURCE_DICTIONNAIRE, RAISONS_REMPLACEMENT),
    REGLE_NATURE: (_nature, SOURCE_GENERIQUE, RAISONS_NATURE),
}


def _numero(valeur) -> str:
    """Numéro de ligne écrit en entier (un numéro lu 2.0 vaut 2)."""
    texte = _texte(valeur)
    try:
        nombre = float(texte)
    except ValueError:
        return texte
    return str(int(nombre)) if nombre.is_integer() else texte


def _repere(ligne) -> tuple[str, str, str]:
    """Repère d'une ligne par son lignage, en textes comparables."""
    return tuple(
        _numero(ligne[c]) if c == "num_ligne_source" else _texte(ligne[c])
        for c in COLONNES_LIGNAGE_ECART
    )


def _doublons_en_surnombre(doublons: pd.DataFrame, table: str, donnees: pd.DataFrame):
    """Règle `doublons` sur une table : lignes en surnombre des doublons exacts.

    Rend None si la table n'a aucun doublon exact, sinon (nombre de lignes en
    surnombre, {position: détail}, Counter des raisons). Les lignes d'un groupe se
    suivent dans la table des doublons, dans l'ordre de la table : la première est
    gardée, les autres sont retirées. Une ligne est retrouvée par son lignage; un
    lignage qui désigne plusieurs lignes de la table n'est pas retiré.
    """
    exacts = doublons[(doublons["table"] == table) & (doublons["constat"] == CONSTAT_EXACT)]
    if exacts.empty:
        return None
    positions: dict[tuple, list[int]] = {}
    lignage = donnees.reindex(columns=list(COLONNES_LIGNAGE_ECART)).reset_index(drop=True)
    for position, ligne in lignage.iterrows():
        positions.setdefault(_repere(ligne), []).append(position)
    visees, retirees, raisons = 0, {}, Counter()
    for _, groupe in exacts.groupby("groupe", sort=False):
        premiere = groupe.iloc[0]
        for _, ligne in groupe.iloc[1:].iterrows():
            visees += 1
            trouvees = positions.get(_repere(ligne), [])
            if len(trouvees) != 1:
                raisons[RAISON_LIGNAGE_AMBIGU] += 1
                continue
            feuille = _texte(premiere["feuille_source"])
            ou = _texte(premiere["fichier_source"]) + (f", {feuille}" if feuille else "")
            detail = f"doublon exact de la ligne {_numero(premiere['num_ligne_source'])} ({ou})"
            if ligne["comparaison"] == COMPARAISON_NORMALISEE:
                detail += ", après normalisation"
            retirees[trouvees[0]] = detail
    return visees, retirees, raisons


def _detail_decision(identifiant: str, decision: dict) -> str:
    return (
        f"décision du {str(decision['decide_le'])[:10]}, classeur {decision['classeur']}, "
        f"anomalie {identifiant}"
    )


def _regle_decision(nettoyees: dict, decisions: dict, dictionnaire: dict, ordre_tables: list):
    """Règle `decision` : applique aux tables nettoyées (modifiées sur place) les
    décisions « corriger » puis « retirer » du métier.

    Rend (corrections, retraits, lignes du bilan) : une correction est (table,
    étiquette de la ligne, colonne, valeur avant, valeur après, détail), un retrait
    (table, étiquette, détail). Les décisions sont prises de la plus ancienne à la
    plus récente. Une décision ne s'applique que si sa ligne est retrouvée par son
    lignage et si l'empreinte calculée comme à l'export (`decisions.elements_a_arbitrer`)
    est la sienne : valeur de la cellule pour une correction, ligne entière hors
    lignage, après les corrections, pour un retrait. Une valeur retenue est écrite
    telle qu'enregistrée si la nature de la colonne n'a pas changé depuis la
    décision, sinon relue dans la nature en vigueur (`decisions.lire_valeur_retenue`).
    Une décision « garder » ne change rien.
    """
    from .decisions import (
        DECISION_CORRIGER,
        DECISION_RETIRER,
        _empreinte,
        _forme,
        lire_valeur_retenue,
    )

    ordonnees = sorted(decisions.items(), key=lambda e: (str(e[1]["decide_le"]), e[0]))
    comptes: dict[tuple, list] = {}

    def compter(table, colonne):
        return comptes.setdefault((table, colonne), [0, 0, Counter()])

    def situer(table, decision):
        """Position de la ligne dans la table nettoyée, None si introuvable."""
        donnees = nettoyees.get(table)
        if donnees is None:
            return None
        reperes = _index_lignage(donnees.reset_index(drop=True))
        return reperes.get(
            _repere_anomalie(
                decision["fichier_source"], decision["feuille_source"],
                decision["num_ligne_source"],
            )
        )

    corrections = []
    for identifiant, decision in ordonnees:
        if decision["decision"] != DECISION_CORRIGER:
            continue
        table, colonne = decision["table"], decision["champ"]
        compte = compter(table, colonne)
        compte[0] += 1
        position = situer(table, decision)
        donnees = nettoyees.get(table)
        if position is None or colonne not in _colonnes_de_donnees(donnees):
            compte[2][RAISON_INTROUVABLE] += 1
            continue
        rang = donnees.columns.get_loc(colonne)
        avant = donnees.iat[position, rang]
        if _empreinte([_forme(avant)]) != decision["empreinte"]:
            compte[2][RAISON_SOURCE_MODIFIEE] += 1
            continue
        valeur = decision["valeur_retenue"]
        nature = dictionnaire[table][colonne]["nature"]["regle"]
        if nature != decision["nature"]:
            valeur, raison = lire_valeur_retenue(valeur, nature)
            if raison is not None:
                compte[2][RAISON_ILLISIBLE] += 1
                continue
        nouvelle = donnees[colonne].copy()
        nouvelle.iloc[position] = valeur
        donnees.isetitem(rang, nouvelle)
        compte[1] += 1
        corrections.append(
            (table, donnees.index[position], colonne, avant, valeur,
             _detail_decision(identifiant, decision))
        )

    retraits, a_retirer = [], {}
    for identifiant, decision in ordonnees:
        if decision["decision"] != DECISION_RETIRER:
            continue
        table = decision["table"]
        compte = compter(table, None)
        compte[0] += 1
        position = situer(table, decision)
        if position is None:
            compte[2][RAISON_INTROUVABLE] += 1
            continue
        donnees = nettoyees[table]
        ligne = donnees.iloc[position]
        empreinte = _empreinte(
            f"{c}={_forme(ligne[c])}" for c in _colonnes_de_donnees(donnees)
        )
        if empreinte != decision["empreinte"]:
            compte[2][RAISON_SOURCE_MODIFIEE] += 1
            continue
        compte[1] += 1
        etiquette = donnees.index[position]
        # Deux décisions peuvent viser la même ligne (deux contrôles de doublons) :
        # elle n'est retirée, et inscrite au journal, qu'une fois.
        if etiquette not in a_retirer.setdefault(table, set()):
            a_retirer[table].add(etiquette)
            retraits.append((table, etiquette, _detail_decision(identifiant, decision)))
    for table, etiquettes in a_retirer.items():
        nettoyees[table] = nettoyees[table].drop(index=sorted(etiquettes))

    def rang_bilan(cle):
        table, colonne = cle
        if table not in nettoyees:
            return (len(ordre_tables), table, 0)
        colonnes = list(_colonnes_de_donnees(nettoyees[table]))
        # Une colonne inconnue, et les retraits (sans colonne), après les colonnes.
        rang_colonne = colonnes.index(colonne) if colonne in colonnes else len(colonnes)
        return (ordre_tables.index(table), "", rang_colonne)

    lignes = []
    for (table, colonne) in sorted(comptes, key=rang_bilan):
        visees, corrigees, raisons = comptes[(table, colonne)]
        lignes.append(
            {
                "regle_nettoyage": REGLE_DECISION,
                "table": table,
                "colonne": colonne,
                "visees": visees,
                "corrigees": corrigees,
                "non_corrigees": visees - corrigees,
                "raisons": _texte_raisons(raisons, RAISONS_DECISION),
            }
        )
    return corrections, retraits, lignes


def _texte_raisons(raisons: Counter, ordre) -> str | None:
    morceaux = [f"{raison} {raisons[raison]}" for raison in ordre if raisons[raison]]
    return "; ".join(morceaux) or None


def nettoyer(
    tables: dict[str, pd.DataFrame],
    dictionnaire: dict,
    sensibles: dict[str, frozenset[str]] | None = None,
    declarations: dict | None = None,
    date_coupure=None,
    decisions: dict | None = None,
) -> Nettoyage:
    """Applique les règles de nettoyage et rend les tables nettoyées, le journal des
    corrections et le bilan.

    `dictionnaire` est le dictionnaire enregistré : il doit décrire exactement les
    tables et colonnes chargées (sinon `ValueError`, comme pour les contrôles); il
    marque aussi des colonnes sensibles. `sensibles` (config/sensibilite.yaml par
    défaut) est vérifiée avant tout (`RuntimeError` si elle est incohérente).
    `declarations` (bloc `doublons` de config/controles.yaml par défaut) donne la clé
    de chaque table, reprise dans le journal. `date_coupure` (fin de la période
    extraite, `perimetre.date_coupure`) sert à la règle `nature` : une année écrite
    sur deux chiffres n'est complétée en 20AA que si la date obtenue ne la dépasse
    pas; sans elle, ces dates ne sont pas converties, et le bilan le dit.
    `decisions` (contenu rendu par `decisions.charger_decisions`, fichier
    data/config/decisions.yaml par défaut, aucune décision s'il est absent) sert à
    la règle `decision`.

    Tables nettoyées : copies des tables reçues, mêmes colonnes, mêmes types de
    colonnes, lignage compris; seules les cellules corrigées changent, et les lignes
    retirées comme doublons ou par décision disparaissent (les autres gardent leur
    index). Les
    tables reçues ne sont pas modifiées.

    Journal (`COLONNES_JOURNAL`) : une ligne par cellule modifiée ou par ligne
    retirée, dans l'ordre des règles, puis des tables, puis des lignes, puis des
    colonnes. `cle` est la clé
    déclarée de la ligne, lue dans la table reçue (vide sans clé déclarée, « masqué »
    si une colonne de la clé est sensible); `valeur_avant` et `valeur_apres` valent
    « masqué » pour une colonne sensible, la valeur brute restant retrouvable par le
    lignage; `valeur_avant` est la valeur laissée par les règles précédentes;
    `detail` précise la correction (pour l'encodage, les encodages qui ont repéré
    une séquence et le nombre de passes; pour un remplacement, la date de la revue
    qui a invalidé la valeur; pour la nature, la forme lue, « forme masquée » pour
    une colonne sensible, et l'ajout du siècle; pour une ligne retirée comme
    doublon, la ligne gardée du même groupe; pour une décision, sa date, son
    classeur et l'identifiant de l'anomalie). Une ligne retirée n'a ni colonne ni
    valeur.

    Bilan (`COLONNES_BILAN_NETTOYAGE`) : une ligne par règle et par colonne qui a au
    moins une cellule visée (par table, sans colonne, pour les doublons et les
    retraits décidés par le métier), avec les
    cellules (ou lignes) visées, corrigées, non corrigées, et le décompte des raisons
    de non-correction (textes séparés par « ; »).
    """
    if sensibles is None:
        sensibles = charger_sensibilite()
    problemes = verifier_sensibilite(tables, sensibles)
    if problemes:
        raise RuntimeError(
            "Classification de sensibilité incohérente\n  " + "\n  ".join(problemes)
        )
    problemes = problemes_dictionnaire(dictionnaire)
    if problemes:
        raise ValueError("Dictionnaire invalide\n  " + "\n  ".join(problemes))
    problemes = _problemes_de_correspondance(tables, dictionnaire)
    if problemes:
        raise ValueError(
            "Le dictionnaire ne décrit pas les données chargées : il est à régénérer "
            "(notebook 02c_dictionnaire)\n  " + "\n  ".join(problemes)
        )
    if declarations is None:
        declarations = charger_declarations_doublons()
    # Import local : decisions.py importe ce module.
    from .decisions import charger_decisions, problemes_decisions

    if decisions is None:
        decisions = charger_decisions()
    problemes = problemes_decisions(decisions)
    if problemes:
        raise ValueError("Décisions invalides\n  " + "\n  ".join(problemes))

    nettoyees = {table: donnees.copy() for table, donnees in tables.items()}
    brutes = {table: donnees.reset_index(drop=True) for table, donnees in tables.items()}
    cles = {}
    for table, donnees in brutes.items():
        cle = [c for c in declarations.get(table, {}).get("cle", []) if c in donnees.columns]
        cles[table] = (cle, any(est_sensible(sensibles, table, c) for c in cle))
    journal, bilan = [], []

    def ligne_du_journal(rang_regle, rang_table, table, position, **champs) -> dict:
        """Ligne du journal pour la ligne source de la table reçue à cette position."""
        ligne = brutes[table].iloc[position]
        cle, cle_masquee = cles[table]
        if not cle:
            texte_cle = None
        elif cle_masquee:
            texte_cle = VALEUR_MASQUEE
        else:
            texte_cle = SEPARATEUR.join(_texte(ligne[c]) for c in cle)
        colonnes = brutes[table].columns
        periode = _texte(ligne[COLONNE_PERIODE]) if COLONNE_PERIODE in colonnes else ""
        return {
            "regle_nettoyage": REGLES_NETTOYAGE[rang_regle],
            "table": table,
            **{c: (ligne[c] if c in colonnes else None) for c in COLONNES_LIGNAGE_ECART},
            COLONNE_PERIODE: periode or None,
            "cle": texte_cle,
            **champs,
            "_regle": rang_regle,
            "_table": rang_table,
            "_position": position,
        }

    for rang_regle, regle_nettoyage in enumerate(REGLES_NETTOYAGE):
        if regle_nettoyage == REGLE_DECISION:
            corrections, retraits, lignes_bilan = _regle_decision(
                nettoyees, decisions["decisions"], dictionnaire, list(tables)
            )
            bilan.extend(lignes_bilan)
            rangs_tables = {table: rang for rang, table in enumerate(tables)}
            positions_brutes = {
                table: {etiquette: i for i, etiquette in enumerate(donnees.index)}
                for table, donnees in tables.items()
            }
            for table, etiquette, colonne, avant, apres, detail in corrections:
                regles = dictionnaire[table][colonne]
                masquee = (
                    est_sensible(sensibles, table, colonne)
                    or est_masquee(regles["valeurs"])
                    or est_masquee(regles["format"])
                )
                avant = _valeur_constatee(avant)
                journal.append(
                    ligne_du_journal(
                        rang_regle,
                        rangs_tables[table],
                        table,
                        positions_brutes[table][etiquette],
                        colonne=colonne,
                        action=ACTION_MODIFIEE,
                        source=SOURCE_DECISION,
                        valeur_avant=VALEUR_MASQUEE if masquee else avant,
                        valeur_apres=VALEUR_MASQUEE if masquee else apres,
                        detail=detail,
                        _colonne=list(_colonnes_de_donnees(brutes[table])).index(colonne),
                    )
                )
            for table, etiquette, detail in retraits:
                journal.append(
                    ligne_du_journal(
                        rang_regle,
                        rangs_tables[table],
                        table,
                        positions_brutes[table][etiquette],
                        colonne=None,
                        action=ACTION_RETIREE,
                        source=SOURCE_DECISION,
                        valeur_avant=None,
                        valeur_apres=None,
                        detail=detail,
                        _colonne=len(brutes[table].columns),
                    )
                )
            continue
        if regle_nettoyage == REGLE_DOUBLONS:
            # Doublons cherchés une fois, sur toutes les tables nettoyées.
            doublons, _ = detecter_doublons(nettoyees, declarations, sensibles)
            for rang_table, table in enumerate(tables):
                resultat = _doublons_en_surnombre(doublons, table, nettoyees[table])
                if resultat is None:
                    continue
                visees, retirees, raisons = resultat
                bilan.append(
                    {
                        "regle_nettoyage": regle_nettoyage,
                        "table": table,
                        "colonne": None,
                        "visees": visees,
                        "corrigees": len(retirees),
                        "non_corrigees": visees - len(retirees),
                        "raisons": _texte_raisons(raisons, RAISONS_DOUBLONS),
                    }
                )
                for position, detail in sorted(retirees.items()):
                    journal.append(
                        ligne_du_journal(
                            rang_regle,
                            rang_table,
                            table,
                            position,
                            colonne=None,
                            action=ACTION_RETIREE,
                            source=SOURCE_GENERIQUE,
                            valeur_avant=None,
                            valeur_apres=None,
                            detail=detail,
                            _colonne=-1,
                        )
                    )
                donnees = nettoyees[table]
                nettoyees[table] = donnees.drop(index=donnees.index[sorted(retirees)])
            continue

        appliquer_regle, source, ordre_raisons = _REGLES[regle_nettoyage]
        for rang_table, table in enumerate(tables):
            for rang_colonne, colonne in enumerate(_colonnes_de_donnees(brutes[table])):
                regles = dictionnaire[table][colonne]
                masquee = (
                    est_sensible(sensibles, table, colonne)
                    or est_masquee(regles["valeurs"])
                    or est_masquee(regles["format"])
                )
                # La règle s'applique aux valeurs laissées par les règles précédentes.
                courante = nettoyees[table][colonne].reset_index(drop=True)
                contexte = {"date_coupure": date_coupure, "masquee": masquee}
                resultat = appliquer_regle(courante, regles, contexte)
                if resultat is None:
                    continue
                visees, acceptees, raisons = resultat
                bilan.append(
                    {
                        "regle_nettoyage": regle_nettoyage,
                        "table": table,
                        "colonne": colonne,
                        "visees": len(visees),
                        "corrigees": len(acceptees),
                        "non_corrigees": len(visees) - len(acceptees),
                        "raisons": _texte_raisons(raisons, ordre_raisons),
                    }
                )
                if not acceptees:
                    continue
                positions = sorted(acceptees)
                nouvelle = nettoyees[table][colonne].copy()
                for position in positions:
                    nouvelle.iloc[position] = acceptees[position][0]
                nettoyees[table].isetitem(nettoyees[table].columns.get_loc(colonne), nouvelle)
                for position in positions:
                    valeur_apres, detail = acceptees[position]
                    avant = _valeur_constatee(courante.iloc[position])
                    journal.append(
                        ligne_du_journal(
                            rang_regle,
                            rang_table,
                            table,
                            position,
                            colonne=colonne,
                            action=ACTION_MODIFIEE,
                            source=source,
                            valeur_avant=VALEUR_MASQUEE if masquee else avant,
                            valeur_apres=VALEUR_MASQUEE if masquee else valeur_apres,
                            detail=detail,
                            _colonne=rang_colonne,
                        )
                    )

    if journal:
        # Colonnes de type objet : une cellule vide reste None, quelle que soit la
        # version de pandas.
        journal = pd.DataFrame(journal, dtype=object).sort_values(
            ["_regle", "_table", "_position", "_colonne"], kind="stable"
        )
        journal = journal[list(COLONNES_JOURNAL)].reset_index(drop=True)
    else:
        journal = pd.DataFrame(columns=list(COLONNES_JOURNAL), dtype=object)
    bilan = pd.DataFrame(bilan, columns=list(COLONNES_BILAN_NETTOYAGE), dtype=object)
    bilan = bilan.astype({"visees": int, "corrigees": int, "non_corrigees": int})
    return Nettoyage(nettoyees, journal, bilan)


COLONNES_COMPARAISON = (
    "etape",
    "controle",
    "table",
    "champ",
    "anomalies_avant",
    "anomalies_apres",
    "a_arbitrer_avant",
    "a_arbitrer_apres",
    "informations_avant",
    "informations_apres",
    "resolues",
    "apparues",
    "issue_changee",
)
_NOMS_ISSUES = {
    ISSUE_ANOMALIE: "anomalies",
    ISSUE_A_ARBITRER: "a_arbitrer",
    ISSUE_INFORMATION: "informations",
}
_COLONNES_COMPAREES = ("id_anomalie", "etape", "controle", "table", "champ", "issue")


def comparer_anomalies(avant: pd.DataFrame, apres: pd.DataFrame) -> pd.DataFrame:
    """Compare, contrôle par contrôle, la table des anomalies avant et après nettoyage.

    `avant` et `apres` sont rendues par `anomalies.reunir_anomalies` (ou
    `qualifier`), l'une sur les tables brutes, l'autre sur les tables nettoyées.
    Rend une ligne par contrôle (étape, contrôle, table, champ) présent dans l'une
    ou l'autre, dans l'ordre de `avant` puis, pour les contrôles nouveaux, de
    `apres` (`COLONNES_COMPARAISON`) : les anomalies, écarts à arbitrer et
    informations avant et après, puis trois décomptes tirés des identifiants :
    `resolues` (identifiant présent avant, absent après), `apparues` (absent
    avant, présent après), `issue_changee` (même identifiant, autre issue).

    Une apparition n'est pas forcément un défaut : une valeur devenue lisible rend
    évaluable une règle qui ne l'était pas. Aucune valeur n'est rendue. Lève une
    ValueError pour une colonne absente, une issue inconnue ou un identifiant en
    double.
    """
    problemes = []
    for nom, table in (("avant", avant), ("après", apres)):
        manquantes = [c for c in _COLONNES_COMPAREES if c not in table.columns]
        if manquantes:
            problemes.append(f"table {nom} : colonnes absentes {', '.join(manquantes)}")
            continue
        inconnues = sorted(set(table["issue"]) - set(_NOMS_ISSUES), key=str)
        if inconnues:
            problemes.append(f"table {nom} : issues inconnues {', '.join(map(str, inconnues))}")
        if table["id_anomalie"].duplicated().any():
            problemes.append(f"table {nom} : identifiants en double")
    if problemes:
        raise ValueError("Tables des anomalies inattendues\n  " + "\n  ".join(problemes))

    issues_avant = dict(zip(avant["id_anomalie"], avant["issue"]))
    issues_apres = dict(zip(apres["id_anomalie"], apres["issue"]))
    comptes: dict[tuple, Counter] = {}

    def compter(ligne) -> Counter:
        champ = None if pd.isna(ligne.champ) else ligne.champ
        cle = (ligne.etape, ligne.controle, ligne.table, champ)
        return comptes.setdefault(cle, Counter())

    for ligne in avant.itertuples(index=False):
        compte = compter(ligne)
        compte[_NOMS_ISSUES[ligne.issue] + "_avant"] += 1
        if ligne.id_anomalie not in issues_apres:
            compte["resolues"] += 1
        elif issues_apres[ligne.id_anomalie] != ligne.issue:
            compte["issue_changee"] += 1
    for ligne in apres.itertuples(index=False):
        compte = compter(ligne)
        compte[_NOMS_ISSUES[ligne.issue] + "_apres"] += 1
        if ligne.id_anomalie not in issues_avant:
            compte["apparues"] += 1
    lignes = [
        {
            "etape": etape,
            "controle": controle,
            "table": table,
            "champ": champ,
            **{c: int(compte[c]) for c in COLONNES_COMPARAISON[4:]},
        }
        for (etape, controle, table, champ), compte in comptes.items()
    ]
    comparaison = pd.DataFrame(lignes, columns=list(COLONNES_COMPARAISON), dtype=object)
    return comparaison.astype({c: int for c in COLONNES_COMPARAISON[4:]})
