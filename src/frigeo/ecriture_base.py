"""Écriture des données dans la base (étape 7.2c).

Une exécution du traitement écrit en base les tables chargées (schéma chargement,
valeurs telles que livrées, en texte) et les tables nettoyées (schéma propre,
valeurs typées), avec leur lignage, et les inscrit dans le schéma qualite
(execution, journal_chargement, correspondance_colonne). Les autres tables de
qualite (anomalies, bilans, journal du nettoyage, décisions) s'ajoutent dans la
même transaction par le paramètre `completer`, avec `CompleterQualite` (7.2d), ainsi
que les tables de référence issues de la configuration (7.3a) : jours fériés de
config/gestion.yaml et valeurs admises des listes fermées du dictionnaire. Si un
pack déclare la procédure dw.reconstruire, elle est appelée en dernier, dans la même
transaction (7.3b) : propre et dw ne peuvent pas être désaccordés. Avant lui, le
rattachement des lignes à leurs référentiels (7.3d, module `rattachement`) est écrit
dans qualite.regle_rattachement et qualite.rattachement, pour que dw relie chaque
fait au bon membre de dimension.

Cycle d'une exécution :

1. l'exécution est inscrite « en cours » dans qualite.execution, et validée à part;
2. les valeurs sont préparées en Python, sans toucher la base : un garde-fou
   (texte de plus de 4 000 caractères, date avec une heure, nombre de plus de
   8 décimales ou trop grand) arrête l'écriture, tous les problèmes étant listés en
   une fois, sans aucune valeur;
3. une seule transaction supprime les tables générées, supprime les exécutions
   précédentes de la même période de fin (y compris celles qui ont échoué), recrée
   les tables, inscrit les fichiers chargés et la correspondance des colonnes,
   insère les données, écrit les autres tables de qualite, reconstruit dw si un
   pack le prévoit, puis passe l'exécution à « réussie »;
4. en cas d'erreur, la transaction est annulée (l'exécution précédente et ses
   tables restent intactes) et l'exécution passe à « échouée », avec le message.

Valeurs de chargement. Un texte est gardé tel quel, chaîne vide comprise; une
cellule absente devient NULL. Une valeur native d'Excel s'écrit sous une forme fixe
(`texte_livre`) : entier 123, nombre 12.5 (point décimal, jamais d'exposant), date
2025-03-14 suivie de l'heure si elle n'est pas minuit.

Valeurs de propre. Une cellule vide au sens du traitement (absente, chaîne vide ou
faite d'espaces) devient NULL, y compris en texte. Les dates, heures et entiers
sont lus par `typage.lire`, la reconnaissance des contrôles; les décimaux sont
convertis par Decimal à partir du texte (12,5) ou de l'écriture la plus courte du
nombre Excel, jamais par un flottant. Une valeur illisible devient NULL, et le
nombre de ces cellules est rendu par colonne.

Transmission. Les valeurs, exactes en Python, sont transmises au serveur sous
leur écriture ISO (2025-03-14, 08:30:00, 12.5), que SQL Server convertit sans
ambiguïté dans le type de la colonne, par lots de `TAILLE_LOT` lignes et avec la
taille réelle des textes de chaque lot : sans cela, le pilote réserverait 8 Ko par
cellule nvarchar(4000).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Callable

import pandas as pd

from .perimetre import tables_du_flux
from .structure_base import (
    FAMILLE_DATE,
    FAMILLE_DECIMAL,
    FAMILLE_ENTIER,
    FAMILLE_HEURE,
    REQUETE_TABLES_EXISTANTES,
    SCHEMA_CHARGEMENT,
    SCHEMA_PROPRE,
    TableBase,
    charger_structure,
    colonnes_techniques,
    ddl_structure,
    ddl_suppression,
    lignes_correspondance,
)
from .typage import ETAT_ILLISIBLE, ETAT_LUE, lire

LONGUEUR_MAX_TEXTE = 4000
DECIMALES_MAX = 8
CHIFFRES_ENTIERS_MAX = 20  # decimal(28, 8)
ENTIER_MAX = 2**63 - 1  # bigint
TAILLE_LOT = 5000
LONGUEUR_MAX_DETAIL = 4000

STATUT_EN_COURS = "en cours"
STATUT_REUSSIE = "réussie"
STATUT_ECHOUEE = "échouée"

# Tables de qualite rattachées à une exécution, dans l'ordre où leurs lignes sont
# supprimées : d'abord celles qui pointent vers journal_chargement.
TABLES_FILLES_EXECUTION = (
    "rattachement",
    "regle_rattachement",
    "anomalie",
    "non_evaluable",
    "journal_nettoyage",
    "bilan_controle",
    "bilan_nettoyage",
    "correspondance_cle",
    "decision",
    "jour_ferie",
    "valeur_liste",
    "correspondance_colonne",
    "journal_chargement",
)

PROBLEME_LONGUEUR = f"texte de plus de {LONGUEUR_MAX_TEXTE} caractères"
PROBLEME_HEURE = "date avec une heure autre que minuit"
PROBLEME_DECIMALES = f"nombre de plus de {DECIMALES_MAX} décimales"
PROBLEME_GRAND = "nombre trop grand pour la colonne"


class ErreurEcriture(Exception):
    """Écriture en base impossible; le message ne porte aucune valeur du client."""


# --- Valeurs -----------------------------------------------------------------------


def _absente(valeur) -> bool:
    if valeur is None or valeur is pd.NaT:
        return True
    return isinstance(valeur, float) and math.isnan(valeur)


def longueur_sql(texte: str) -> int:
    """Longueur d'un texte comptée comme nvarchar (unités UTF-16) : un caractère hors
    du plan de base, un émoji par exemple, en compte deux."""
    return len(texte.encode("utf-16-le")) // 2


def _decimal_en_texte(nombre: Decimal) -> str:
    texte = format(nombre, "f")
    if "." in texte:
        texte = texte.rstrip("0").rstrip(".")
    return "0" if texte in ("-0", "") else texte


def texte_livre(valeur) -> str | None:
    """Écriture en texte d'une valeur telle que livrée, pour le schéma chargement.

    Un texte est rendu tel quel, chaîne vide comprise; une valeur absente (None,
    NaN, NaT) donne None. Entier : 123; nombre : écriture la plus courte, point
    décimal, sans exposant (12.5, 0.00001, 12 pour 12.0); date : 2025-03-14, suivie
    de l'heure si elle n'est pas minuit; heure : 08:30:00. Tout autre type est écrit
    par str().
    """
    if _absente(valeur):
        return None
    if isinstance(valeur, str):
        return valeur
    if isinstance(valeur, bool):
        return str(valeur)
    if isinstance(valeur, int):
        return str(valeur)
    if isinstance(valeur, float):
        if math.isinf(valeur):
            return str(valeur)
        return _decimal_en_texte(Decimal(repr(valeur)))
    if isinstance(valeur, dt.datetime):
        if valeur.time() == dt.time(0):
            return valeur.strftime("%Y-%m-%d")
        return valeur.isoformat(sep=" ")
    if isinstance(valeur, (dt.date, dt.time)):
        return valeur.isoformat()
    return str(valeur)


def _decimal(valeur) -> Decimal:
    """Valeur exacte d'un nombre lu : texte (virgule ou point) ou nombre Excel."""
    if isinstance(valeur, str):
        return Decimal(valeur.strip().replace(",", "."))
    if isinstance(valeur, int):
        return Decimal(valeur)
    return Decimal(repr(float(valeur)))


def _probleme_decimal(nombre: Decimal) -> str | None:
    signe, chiffres, exposant = nombre.normalize().as_tuple()
    if not isinstance(exposant, int):
        return PROBLEME_GRAND
    if -exposant > DECIMALES_MAX:
        return PROBLEME_DECIMALES
    if len(chiffres) + exposant > CHIFFRES_ENTIERS_MAX:
        return PROBLEME_GRAND
    return None


@dataclass
class Colonne:
    """Valeurs d'une colonne prêtes à transmettre, et ce qu'en dit la préparation."""

    valeurs: list
    illisibles: int = 0
    problemes: dict[str, int] = field(default_factory=dict)
    positions_illisibles: list[int] = field(default_factory=list)

    def compter(self, probleme: str) -> None:
        self.problemes[probleme] = self.problemes.get(probleme, 0) + 1


def valeurs_chargement(serie: pd.Series) -> Colonne:
    """Valeurs d'une colonne de chargement : texte tel que livré."""
    colonne = Colonne([texte_livre(v) for v in serie])
    for texte in colonne.valeurs:
        if texte is not None and longueur_sql(texte) > LONGUEUR_MAX_TEXTE:
            colonne.compter(PROBLEME_LONGUEUR)
    return colonne


def _vide(valeur) -> bool:
    return _absente(valeur) or (isinstance(valeur, str) and valeur.strip() == "")


def valeurs_propre(serie: pd.Series, famille: str, nature: str) -> Colonne:
    """Valeurs d'une colonne de propre, dans l'écriture ISO de leur type.

    Une cellule vide donne None. Une valeur illisible dans la nature de la colonne
    donne None et est comptée. Un garde-fou déclenché est compté dans `problemes`.
    """
    serie = serie.reset_index(drop=True)
    if famille not in (FAMILLE_DATE, FAMILLE_HEURE, FAMILLE_ENTIER, FAMILLE_DECIMAL):
        colonne = Colonne([None if _vide(v) else texte_livre(v) for v in serie])
        for texte in colonne.valeurs:
            if texte is not None and longueur_sql(texte) > LONGUEUR_MAX_TEXTE:
                colonne.compter(PROBLEME_LONGUEUR)
        return colonne

    lecture = lire(serie, nature)
    lues = lecture.etats == ETAT_LUE
    positions = [int(p) for p in lecture.etats.index[lecture.etats == ETAT_ILLISIBLE]]
    colonne = Colonne([None] * len(serie), illisibles=len(positions), positions_illisibles=positions)
    for position in lues[lues].index:
        if famille == FAMILLE_DATE:
            instant = pd.Timestamp(lecture.valeurs.iloc[position])
            if instant != instant.normalize():
                colonne.compter(PROBLEME_HEURE)
                continue
            colonne.valeurs[position] = instant.date().isoformat()
        elif famille == FAMILLE_HEURE:
            secondes = int(pd.Timedelta(lecture.valeurs.iloc[position]).total_seconds())
            colonne.valeurs[position] = dt.time(
                secondes // 3600, secondes % 3600 // 60, secondes % 60
            ).isoformat()
        elif famille == FAMILLE_ENTIER:
            entier = int(str(serie.iloc[position]).strip())
            if abs(entier) > ENTIER_MAX:
                colonne.compter(PROBLEME_GRAND)
                continue
            colonne.valeurs[position] = str(entier)
        else:
            try:
                nombre = _decimal(serie.iloc[position])
            except InvalidOperation:
                colonne.illisibles += 1
                colonne.positions_illisibles.append(int(position))
                continue
            probleme = _probleme_decimal(nombre)
            if probleme:
                colonne.compter(probleme)
                continue
            colonne.valeurs[position] = _decimal_en_texte(nombre)
    return colonne


# --- Fichiers chargés --------------------------------------------------------------


def empreinte_fichier(chemin: str | Path) -> str:
    """Empreinte SHA-256 des octets du fichier, tels quels."""
    calcul = hashlib.sha256()
    with open(chemin, "rb") as flux:
        for bloc in iter(lambda: flux.read(1 << 20), b""):
            calcul.update(bloc)
    return calcul.hexdigest()


def _feuille(valeur) -> str | None:
    return None if _vide(valeur) else str(valeur)


COLONNES_JOURNAL_CHARGEMENT = (
    "fichier_source",
    "feuille_source",
    "periode_export",
    "empreinte_sha256",
    "nb_lignes",
)


def lignes_journal_chargement(perimetre, tables: dict[str, pd.DataFrame]) -> list[dict]:
    """Une ligne par fichier et par feuille du périmètre qui donne une table.

    Un classeur à deux feuilles donne deux lignes, de même empreinte. `nb_lignes`
    est le nombre de lignes chargées depuis ce fichier et cette feuille (0 si le
    fichier n'en a donné aucune).
    """
    comptes: dict[tuple, int] = {}
    for donnees in tables.values():
        if donnees.empty:
            continue
        cles = zip(donnees["fichier_source"], donnees["feuille_source"].map(_feuille))
        for cle in cles:
            comptes[cle] = comptes.get(cle, 0) + 1
    lignes = []
    for fichier in perimetre.fichiers:
        empreinte = empreinte_fichier(fichier["chemin"])
        flux = perimetre.config["flux"][fichier["flux"]]
        feuilles = []
        for nom_table, options in tables_du_flux(flux).items():
            if nom_table in tables and options.get("feuille") not in feuilles:
                feuilles.append(options.get("feuille"))
        for feuille in feuilles:
            lignes.append(
                {
                    "fichier_source": fichier["fichier"],
                    "feuille_source": feuille,
                    "periode_export": fichier["periode"],
                    "empreinte_sha256": empreinte,
                    "nb_lignes": comptes.get((fichier["fichier"], feuille), 0),
                }
            )
    return lignes


# --- Préparation -------------------------------------------------------------------


@dataclass
class TablePreparee:
    """Lignes d'une table prêtes à insérer dans un schéma, sans id_chargement."""

    table: TableBase
    schema: str
    colonnes: list[str]
    lignage: list[tuple]  # (fichier_source, feuille_source) de chaque ligne
    lignes: list[list]


COLONNES_CELLULES_ILLISIBLES = (
    "table", "colonne", "fichier_source", "feuille_source", "num_ligne_source",
)


@dataclass
class Preparation:
    tables: list[TablePreparee]
    journal: list[dict]
    illisibles: pd.DataFrame  # table, colonne, cellules
    # Une ligne par cellule illisible de propre : table, colonne, lignage.
    cellules_illisibles: pd.DataFrame


def _lignage(donnees: pd.DataFrame, schema: str) -> tuple[list[tuple], list[list]]:
    n = len(donnees)
    fichiers = [str(v) for v in donnees["fichier_source"]]
    feuilles = [_feuille(v) for v in donnees.get("feuille_source", pd.Series([None] * n))]
    periodes = [None if _absente(v) else str(v) for v in donnees.get("periode_export", pd.Series([None] * n))]
    numeros = [int(v) for v in donnees["num_ligne_source"]]
    colonnes = [periodes, fichiers, feuilles, numeros]
    if schema == SCHEMA_CHARGEMENT:
        nb_champs = donnees.get("nb_champs_source", pd.Series([None] * n))
        colonnes.append([None if _absente(v) else int(v) for v in nb_champs])
        colonnes.append(
            valeurs_chargement(donnees.get("champs_excedentaires", pd.Series([None] * n))).valeurs
        )
    return list(zip(fichiers, feuilles)), colonnes


def preparer(
    perimetre,
    tables: dict[str, pd.DataFrame],
    tables_nettoyees: dict[str, pd.DataFrame],
    structure: dict[str, TableBase],
) -> Preparation:
    """Valeurs de toutes les tables, sans toucher la base.

    Les tables de la structure doivent toutes être présentes, chargées et nettoyées.
    Un garde-fou déclenché lève `ErreurEcriture`, qui liste tous les problèmes par
    table, colonne et nombre de cellules, sans aucune valeur.
    """
    problemes, illisibles, cellules, preparees = [], [], [], []
    manquantes = [
        f"{nom} ({etat})"
        for nom in structure
        for etat, source in (("chargée", tables), ("nettoyée", tables_nettoyees))
        if nom not in source
    ]
    if manquantes:
        raise ErreurEcriture("Tables absentes des données : " + ", ".join(manquantes))
    for schema, source in ((SCHEMA_CHARGEMENT, tables), (SCHEMA_PROPRE, tables_nettoyees)):
        for nom, table in structure.items():
            donnees = source[nom]
            absentes = [c.source for c in table.colonnes if c.source not in donnees.columns]
            if absentes:
                problemes.append(f"{schema}.{table.nom} : colonnes absentes {', '.join(absentes)}")
                continue
            lignage, colonnes = _lignage(donnees, schema)
            for c in table.colonnes:
                if schema == SCHEMA_CHARGEMENT:
                    resultat = valeurs_chargement(donnees[c.source])
                else:
                    resultat = valeurs_propre(donnees[c.source], c.famille, c.nature)
                    if resultat.illisibles:
                        illisibles.append(
                            {"table": nom, "colonne": c.source, "cellules": resultat.illisibles}
                        )
                        numeros = colonnes[3]
                        cellules += [
                            {"table": nom, "colonne": c.source, "fichier_source": lignage[p][0],
                             "feuille_source": lignage[p][1], "num_ligne_source": numeros[p]}
                            for p in resultat.positions_illisibles
                        ]
                for probleme, nombre in resultat.problemes.items():
                    problemes.append(
                        f"{schema}.{table.nom}.{c.nom} ({nom}.{c.source}) : {nombre} cellule(s), "
                        f"{probleme}"
                    )
                colonnes.append(resultat.valeurs)
            noms = [t.nom for t in colonnes_techniques(schema) if not t.identite]
            noms.remove("id_chargement")
            noms += [c.nom for c in table.colonnes]
            preparees.append(
                TablePreparee(table, schema, noms, lignage, [list(l) for l in zip(*colonnes)])
            )
    if problemes:
        raise ErreurEcriture(
            "Écriture en base arrêtée par les garde-fous\n  " + "\n  ".join(problemes)
        )
    journal = lignes_journal_chargement(perimetre, tables)
    connus = {(l["fichier_source"], l["feuille_source"]) for l in journal}
    hors_journal = sorted(
        {f"{p.schema}.{p.table.nom}" for p in preparees for cle in p.lignage if cle not in connus}
    )
    if hors_journal:
        raise ErreurEcriture(
            "Lignes dont le fichier n'est pas dans le périmètre : " + ", ".join(hors_journal)
        )
    return Preparation(
        preparees,
        journal,
        pd.DataFrame(illisibles, columns=["table", "colonne", "cellules"]),
        pd.DataFrame(cellules, columns=list(COLONNES_CELLULES_ILLISIBLES)),
    )


# --- Base --------------------------------------------------------------------------

_VALEUR_TRONQUEE = re.compile(r"(Truncated value|Valeur tronquée)\s*:.*", re.IGNORECASE | re.DOTALL)


def message_sans_valeur(erreur: Exception) -> str:
    """Message d'une erreur, sans la valeur tronquée que cite SQL Server."""
    return _VALEUR_TRONQUEE.sub(r"\1 : (masquée)", str(erreur))[:LONGUEUR_MAX_DETAIL]


def _tailles(lot: list[list], types: list[str]) -> list:
    import pyodbc

    tailles = []
    for position, type_sql in enumerate(types):
        if type_sql == "int":
            tailles.append((pyodbc.SQL_INTEGER, 0, 0))
        else:
            longueur = max(
                (longueur_sql(l[position]) for l in lot if l[position] is not None), default=1
            )
            tailles.append((pyodbc.SQL_WVARCHAR, max(1, longueur), 0))
    return tailles


def _inserer(curseur, preparee: TablePreparee, ids: dict[tuple, int]) -> int:
    colonnes = ["id_chargement", *preparee.colonnes]
    types_techniques = {t.nom: t.type_sql for t in colonnes_techniques(preparee.schema)}
    types = ["int" if types_techniques.get(c) == "int" else "texte" for c in colonnes]
    lignes = [[ids[cle], *ligne] for cle, ligne in zip(preparee.lignage, preparee.lignes)]
    instruction = (
        f"INSERT INTO {preparee.schema}.{preparee.table.nom} ({', '.join(colonnes)}) "
        f"VALUES ({', '.join('?' * len(colonnes))})"
    )
    try:
        for debut in range(0, len(lignes), TAILLE_LOT):
            lot = lignes[debut:debut + TAILLE_LOT]
            curseur.setinputsizes(_tailles(lot, types))
            curseur.executemany(instruction, lot)
    finally:
        # Les tailles déclarées resteraient appliquées aux instructions suivantes.
        curseur.setinputsizes(None)
    return len(lignes)


def _inscrire_execution(moteur, periode_fin: str, version: str | None) -> int:
    with moteur.begin() as conn:
        curseur = conn.connection.cursor()
        try:
            curseur.execute(
                "INSERT INTO qualite.execution (periode_fin, version_traitement) "
                "OUTPUT INSERTED.id_execution VALUES (?, ?)",
                periode_fin, version,
            )
            return int(curseur.fetchone()[0])
        finally:
            curseur.close()


def _marquer_echec(moteur, id_execution: int, message: str) -> None:
    with moteur.begin() as conn:
        curseur = conn.connection.cursor()
        try:
            curseur.execute(
                "UPDATE qualite.execution SET statut = ?, fin = SYSUTCDATETIME(), detail = ? "
                "WHERE id_execution = ?",
                STATUT_ECHOUEE, message[:LONGUEUR_MAX_DETAIL], id_execution,
            )
        finally:
            curseur.close()


def _supprimer_precedentes(curseur, periode_fin: str, id_execution: int) -> None:
    precedentes = (
        "SELECT id_execution FROM qualite.execution WHERE periode_fin = ? AND id_execution <> ?"
    )
    for table in TABLES_FILLES_EXECUTION:
        curseur.execute(
            f"DELETE FROM qualite.{table} WHERE id_execution IN ({precedentes})",
            periode_fin, id_execution,
        )
    curseur.execute(
        "DELETE FROM qualite.execution WHERE periode_fin = ? AND id_execution <> ?",
        periode_fin, id_execution,
    )


def _inscrire_fichiers(curseur, id_execution: int, journal: list[dict]) -> dict[tuple, int]:
    ids = {}
    for ligne in journal:
        curseur.execute(
            "INSERT INTO qualite.journal_chargement (id_execution, "
            + ", ".join(COLONNES_JOURNAL_CHARGEMENT)
            + ") OUTPUT INSERTED.id_chargement VALUES (?, ?, ?, ?, ?, ?)",
            id_execution, *(ligne[c] for c in COLONNES_JOURNAL_CHARGEMENT),
        )
        ids[(ligne["fichier_source"], ligne["feuille_source"])] = int(curseur.fetchone()[0])
    return ids


def _inscrire_correspondance(curseur, id_execution: int, structure) -> None:
    lignes = lignes_correspondance(structure)
    if not lignes:
        return
    colonnes = list(lignes[0])
    curseur.executemany(
        f"INSERT INTO qualite.correspondance_colonne (id_execution, {', '.join(colonnes)}) "
        f"VALUES ({', '.join('?' * (len(colonnes) + 1))})",
        [[id_execution, *(l[c] for c in colonnes)] for l in lignes],
    )


@dataclass
class Ecriture:
    """Résultat d'une écriture réussie."""

    id_execution: int
    lignes: pd.DataFrame  # table, chargement, propre
    illisibles: pd.DataFrame  # table, colonne, cellules
    fichiers: int
    preparation: Preparation | None = None  # valeurs écrites, pour verifier_base
    # Journal de la reconstruction de dw (ordre, étape, lignes), None sans pack qui
    # déclare dw.reconstruire.
    journal_dw: list[tuple[int, str, int]] | None = None


def ecrire_base(
    moteur,
    periode_fin: str,
    perimetre,
    tables: dict[str, pd.DataFrame],
    tables_nettoyees: dict[str, pd.DataFrame],
    structure: dict[str, TableBase] | None = None,
    version: str | None = None,
    completer: Callable | None = None,
) -> Ecriture:
    """Écrit une exécution complète en base (voir le cycle en tête du module).

    `completer(curseur, id_execution, ids_chargement)` écrit, dans la même
    transaction, les autres tables de qualite; `ids_chargement` associe
    (fichier_source, feuille_source) à son id_chargement. `version` vaut par défaut
    la version du traitement lue dans Git. Après `completer`, la procédure
    dw.reconstruire est appelée si un pack la déclare : une erreur de sa part (contrat
    d'entrée non respecté) fait échouer toute l'exécution.
    """
    from .base import reconstruire_dw, version_traitement

    structure = structure or charger_structure()
    version = version if version is not None else version_traitement()
    id_execution = _inscrire_execution(moteur, periode_fin, version)
    try:
        preparation = preparer(perimetre, tables, tables_nettoyees, structure)
        comptes: dict[str, dict[str, int]] = {}
        journal_dw = None
        with moteur.begin() as conn:
            curseur = conn.connection.cursor()
            curseur.fast_executemany = True
            try:
                existantes = [tuple(l) for l in curseur.execute(REQUETE_TABLES_EXISTANTES).fetchall()]
                for instruction in ddl_suppression(existantes):
                    curseur.execute(instruction)
                _supprimer_precedentes(curseur, periode_fin, id_execution)
                for instruction in ddl_structure(structure):
                    curseur.execute(instruction)
                ids = _inscrire_fichiers(curseur, id_execution, preparation.journal)
                _inscrire_correspondance(curseur, id_execution, structure)
                for preparee in preparation.tables:
                    nombre = _inserer(curseur, preparee, ids)
                    comptes.setdefault(preparee.table.source, {})[preparee.schema] = nombre
                if completer is not None:
                    completer(curseur, id_execution, ids)
                journal_dw = reconstruire_dw(curseur, id_execution)
                curseur.execute(
                    "UPDATE qualite.execution SET statut = ?, fin = SYSUTCDATETIME() "
                    "WHERE id_execution = ?",
                    STATUT_REUSSIE, id_execution,
                )
            finally:
                curseur.close()
    except Exception as erreur:
        message = message_sans_valeur(erreur)
        _marquer_echec(moteur, id_execution, message)
        if isinstance(erreur, ErreurEcriture):
            raise
        raise ErreurEcriture(f"Écriture en base échouée (exécution {id_execution}) : {message}") from None
    lignes = pd.DataFrame(
        [
            {"table": nom, SCHEMA_CHARGEMENT: n.get(SCHEMA_CHARGEMENT, 0), SCHEMA_PROPRE: n.get(SCHEMA_PROPRE, 0)}
            for nom, n in comptes.items()
        ],
        columns=["table", SCHEMA_CHARGEMENT, SCHEMA_PROPRE],
    )
    return Ecriture(
        id_execution, lignes, preparation.illisibles, len(preparation.journal), preparation,
        journal_dw,
    )


# --- Tables de qualite (7.2d) -------------------------------------------------------

ETAT_BRUT = "brut"
ETAT_NETTOYE = "nettoyé"

# Colonnes des fichiers du traitement renommées en base (« table » est réservé en T-SQL).
RENOMMAGES = {"table": "table_source"}
# Clé provisoire d'une ligne : (fichier_source, feuille_source) de sa ligne source,
# remplacée à l'insertion par id_chargement.
CLE_LIGNAGE = "__lignage"
# Clé provisoire de la ligne du référentiel d'un rattachement, remplacée à l'insertion
# par id_chargement_reference.
CLE_LIGNAGE_REFERENCE = "__lignage_reference"
# Clé provisoire vers la colonne d'id_chargement qui la remplace, dans cet ordre.
CLES_LIGNAGE = {CLE_LIGNAGE: "id_chargement", CLE_LIGNAGE_REFERENCE: "id_chargement_reference"}

REQUETE_COLONNES_QUALITE = (
    "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, NUMERIC_SCALE "
    "FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = N'qualite'"
)
TYPES_ENTIERS = ("int", "bigint", "smallint", "tinyint")


@dataclass
class SortiesQualite:
    """Sorties du traitement à écrire dans qualite, telles que les produit le
    notebook 07 (mêmes tables que les fichiers CSV de data/anomalies et
    data/nettoyage)."""

    anomalies_brutes: pd.DataFrame
    bilan_brut: pd.DataFrame
    non_evaluables_brutes: pd.DataFrame
    anomalies_nettoyees: pd.DataFrame
    bilan_nettoye: pd.DataFrame
    non_evaluables_nettoyees: pd.DataFrame
    journal_nettoyage: pd.DataFrame
    bilan_nettoyage: pd.DataFrame
    decisions: dict
    dictionnaire: dict
    cle_empreinte: str
    # Jours fériés de config/gestion.yaml (`gestion.charger_jours_feries`).
    jours_feries: dict = field(default_factory=dict)
    # Rattachement des lignes aux référentiels (`rattachement.rattacher`), None s'il
    # n'est pas calculé : aucune ligne dans les deux tables du rattachement.
    rattachements: object = None
    # Codes en doublon regroupés sous un code principal (`nettoyage.nettoyer`,
    # membre correspondances), None : aucune ligne dans qualite.correspondance_cle.
    correspondances: pd.DataFrame | None = None


def _cle_lignage(enregistrement: dict, fichier: str = "fichier_source",
                 feuille: str = "feuille_source") -> tuple | None:
    valeur = enregistrement.get(fichier)
    if _vide(valeur):
        return None
    return (str(valeur), _feuille(enregistrement.get(feuille)))


def _lignes(donnees: pd.DataFrame, communs: dict, lignage: bool = True) -> list[dict]:
    lignes = []
    for enregistrement in donnees.to_dict("records"):
        ligne = dict(communs)
        for colonne, valeur in enregistrement.items():
            ligne[RENOMMAGES.get(colonne, colonne)] = valeur
        if lignage:
            ligne[CLE_LIGNAGE] = _cle_lignage(enregistrement)
        lignes.append(ligne)
    return lignes


def champ_sensible(sensibles: dict, dictionnaire: dict, table, champ) -> bool:
    """Vrai pour une colonne classée sensible ou masquée par le dictionnaire, comme
    dans la cellule # COLONNES SENSIBLES du notebook 07."""
    from .confidentialite import est_sensible
    from .dictionnaire import est_masquee

    if _vide(table) or _vide(champ):
        return False
    if est_sensible(sensibles, table, champ):
        return True
    regles = dictionnaire.get(table, {}).get(champ)
    return bool(regles) and (est_masquee(regles["valeurs"]) or est_masquee(regles["format"]))


def lignes_decisions(decisions: dict, dictionnaire: dict, sensibles: dict, cle: str) -> list[dict]:
    """Lignes de qualite.decision, sans id_execution, telles qu'enregistrées.

    Sur un champ sensible, valeur_retenue reste vide et son empreinte (clé du
    journal du nettoyage) est écrite dans empreinte_valeur_retenue.
    """
    from .decisions import CHAMPS_DECISION
    from .nettoyage import empreinte_valeur

    lignes = []
    for identifiant, decision in (decisions.get("decisions") or {}).items():
        ligne = {"id_decision": identifiant}
        for champ in CHAMPS_DECISION:
            ligne[RENOMMAGES.get(champ, champ)] = decision.get(champ)
        retenue = ligne["valeur_retenue"]
        ligne["empreinte_valeur_retenue"] = None
        if champ_sensible(sensibles, dictionnaire, decision.get("table"), decision.get("champ")):
            ligne["valeur_retenue"] = None
            if not _absente(retenue):
                ligne["empreinte_valeur_retenue"] = empreinte_valeur(retenue, cle)
        lignes.append(ligne)
    return lignes


def _sensibles(sensibles: dict | None) -> dict:
    """Colonnes sensibles données, ou celles de config/sensibilite.yaml."""
    from .confidentialite import charger_sensibilite

    return charger_sensibilite() if sensibles is None else sensibles


def lignes_jours_feries(jours_feries: dict) -> list[dict]:
    """Lignes de qualite.jour_ferie, sans id_execution : une par jour férié déclaré,
    dans l'ordre des années puis des jours. Une année déclarée sans jour férié donne
    une ligne sans jour, pour qu'elle reste distincte d'une année non déclarée."""
    lignes = []
    for annee, jours in jours_feries.items():
        if not jours:
            lignes.append({"annee": annee, "jour": None})
        lignes += [{"annee": annee, "jour": jour} for jour in jours]
    return lignes


def lignes_valeurs_liste(dictionnaire: dict, sensibles: dict) -> list[dict]:
    """Lignes de qualite.valeur_liste, sans id_execution : une par valeur admise de
    chaque colonne dont la règle `valeurs` en vigueur est une liste fermée.

    Une valeur est admise quand le contrôle de la liste ne la signale pas : valide,
    documentée, ou proposée par la génération et pas encore revue (statut observé).
    Les valeurs invalides, à arbitrer ou écartées ne sont pas reprises. Le rang suit
    l'ordre de la liste du dictionnaire, à partir de 1, parmi les valeurs admises. Une
    colonne sensible (`champ_sensible`) n'est pas reprise.
    """
    from .controles import _issue_element
    from .dictionnaire import LISTE_FERMEE

    lignes = []
    for table, colonnes in dictionnaire.items():
        for colonne, regles in colonnes.items():
            valeurs = regles["valeurs"]
            if valeurs["regle"] != LISTE_FERMEE or champ_sensible(
                sensibles, dictionnaire, table, colonne
            ):
                continue
            admises = [
                element for element in valeurs["liste"]
                if _issue_element(element) in (None, "non revue")
            ]
            lignes += [
                {"table_source": table, "colonne_source": colonne, "rang": rang,
                 "valeur": element["valeur"], "statut": element["statut"]}
                for rang, element in enumerate(admises, start=1)
            ]
    return lignes


def lignes_regles_rattachement(rattachements) -> list[dict]:
    """Lignes de qualite.regle_rattachement, sans id_execution : une par rattachement,
    numéroté par son rang (id_regle), colonnes reliées par « , »."""
    if rattachements is None:
        return []
    return [
        {"id_regle": rang, "table_source": r.table, "cle": ", ".join(r.cle),
         "table_reference": r.table_reference, "cle_reference": ", ".join(r.cle_reference),
         "comparaison": r.comparaison, "colonne_date": r.date, "debut": r.debut,
         "fin": r.fin, "refs": ", ".join(r.refs)}
        for rang, r in enumerate(rattachements.regles, start=1)
    ]


def lignes_rattachement(rattachements) -> list[dict]:
    """Lignes de qualite.rattachement, sans id_execution : une par ligne rattachée, la
    ligne source et celle du référentiel portant chacune sa clé de lignage
    (`CLE_LIGNAGE`, `CLE_LIGNAGE_REFERENCE`), remplacée à l'insertion par leur
    id_chargement."""
    if rattachements is None:
        return []
    return [
        {"id_regle": int(l["regle"]),
         "num_ligne_source": int(l["num_ligne_source"]),
         CLE_LIGNAGE: _cle_lignage(l),
         "num_ligne_reference": int(l["num_ligne_reference"]),
         CLE_LIGNAGE_REFERENCE: _cle_lignage(l, "fichier_reference", "feuille_reference"),
         "candidates": int(l["candidates"]),
         "choix_par_date": bool(l["choix_par_date"])}
        for l in rattachements.lignes.to_dict("records")
    ]


def lignes_correspondances(correspondances: pd.DataFrame | None) -> list[dict]:
    """Lignes de qualite.correspondance_cle, sans id_execution : une par code en
    doublon regroupé sous son code principal."""
    if correspondances is None:
        return []
    return [
        {"table_source": c["table"], "colonne_cle": c["colonne"],
         "code_doublon": c["code_doublon"], "code_principal": c["code_principal"],
         "id_decision": c["id_decision"]}
        for c in correspondances.to_dict("records")
    ]


def lignes_qualite(sorties: SortiesQualite, sensibles: dict | None = None) -> dict[str, list[dict]]:
    """Lignes de chaque table de qualite, sans id_execution, valeurs telles que dans
    les fichiers du traitement (une valeur masquée reste « masqué »).

    Chaque ligne au grain d'une ligne source porte sa clé de lignage (`CLE_LIGNAGE`),
    remplacée par id_chargement à l'insertion; une ligne de rattachement porte en plus
    celle de la ligne du référentiel (`CLE_LIGNAGE_REFERENCE`). Les tables suivent
    l'ordre d'insertion : une règle de rattachement avant ses lignes, une décision
    avant les correspondances de codes qui la citent.
    """
    sensibles = _sensibles(sensibles)
    brut, nettoye = {"etat": ETAT_BRUT}, {"etat": ETAT_NETTOYE}
    return {
        "anomalie": _lignes(sorties.anomalies_brutes, brut)
        + _lignes(sorties.anomalies_nettoyees, nettoye),
        "non_evaluable": _lignes(sorties.non_evaluables_brutes, brut)
        + _lignes(sorties.non_evaluables_nettoyees, nettoye),
        "bilan_controle": _lignes(sorties.bilan_brut, brut, lignage=False)
        + _lignes(sorties.bilan_nettoye, nettoye, lignage=False),
        "journal_nettoyage": _lignes(sorties.journal_nettoyage, {}),
        "bilan_nettoyage": _lignes(sorties.bilan_nettoyage, {}, lignage=False),
        "decision": lignes_decisions(
            sorties.decisions, sorties.dictionnaire, sensibles, sorties.cle_empreinte
        ),
        "jour_ferie": lignes_jours_feries(sorties.jours_feries),
        "valeur_liste": lignes_valeurs_liste(sorties.dictionnaire, sensibles),
        "regle_rattachement": lignes_regles_rattachement(sorties.rattachements),
        "rattachement": lignes_rattachement(sorties.rattachements),
        "correspondance_cle": lignes_correspondances(sorties.correspondances),
    }


def problemes_sorties(
    sorties: SortiesQualite,
    periode_fin: str,
    sensibles: dict | None = None,
    declarations: dict | None = None,
) -> list[str]:
    """Les refus de l'écriture des fichiers CSV, appliqués aux sorties avant leur
    écriture en base : colonnes attendues, table qualifiée, valeur ou clé sensible
    non masquée, empreintes du journal, fichier des décisions."""
    from .anomalies import _problemes_ecriture, _problemes_non_evaluables
    from .decisions import problemes_decisions
    from .nettoyage import (
        COLONNES_BILAN_NETTOYAGE,
        COLONNES_JOURNAL,
        empreintes_incoherentes,
        journal_non_masque,
    )

    problemes = []
    for etat, anomalies, bilan, non_evaluables, nettoyees in (
        (ETAT_BRUT, sorties.anomalies_brutes, sorties.bilan_brut, sorties.non_evaluables_brutes, False),
        (ETAT_NETTOYE, sorties.anomalies_nettoyees, sorties.bilan_nettoye,
         sorties.non_evaluables_nettoyees, True),
    ):
        trouves = _problemes_ecriture(anomalies, bilan, periode_fin, sensibles, declarations, nettoyees)
        if not trouves:
            trouves = _problemes_non_evaluables(non_evaluables, bilan, sensibles, declarations)
        problemes += [f"anomalies, état {etat} : {p}" for p in trouves]
    for nom, donnees, attendues in (
        ("journal du nettoyage", sorties.journal_nettoyage, COLONNES_JOURNAL),
        ("bilan du nettoyage", sorties.bilan_nettoyage, COLONNES_BILAN_NETTOYAGE),
    ):
        if list(donnees.columns) != list(attendues):
            problemes.append(f"{nom} : colonnes attendues, dans cet ordre, {', '.join(attendues)}")
    if list(sorties.journal_nettoyage.columns) == list(COLONNES_JOURNAL):
        fautives = journal_non_masque(sorties.journal_nettoyage, sensibles, declarations)
        if not fautives.empty:
            problemes.append(
                f"journal du nettoyage : {len(fautives)} lignes dont une valeur ou la clé "
                "d'une colonne sensible n'est pas masquée"
            )
        if not empreintes_incoherentes(sorties.journal_nettoyage).empty:
            problemes.append("journal du nettoyage : empreintes qui ne suivent pas le masquage")
    problemes += [f"décisions : {p}" for p in problemes_decisions(sorties.decisions)]
    problemes += _problemes_correspondances(sorties.correspondances, sorties.decisions)
    return problemes


def _problemes_correspondances(correspondances, decisions: dict) -> list[str]:
    """Colonnes des correspondances de codes, et décision citée présente dans le
    fichier des décisions."""
    from .nettoyage import COLONNES_CORRESPONDANCES

    if correspondances is None:
        return []
    if list(correspondances.columns) != list(COLONNES_CORRESPONDANCES):
        return [
            "correspondances des codes : colonnes attendues, dans cet ordre, "
            + ", ".join(COLONNES_CORRESPONDANCES)
        ]
    connues = set((decisions or {}).get("decisions") or {})
    absentes = sorted({str(i) for i in correspondances["id_decision"] if i not in connues})
    if absentes:
        return [
            "correspondances des codes : décisions absentes du fichier des décisions "
            f"({', '.join(absentes)})"
        ]
    return []


def valeur_sql(valeur, type_sql: str, echelle=None):
    """Valeur transmise pour une colonne de qualite, selon son type en base.

    Entier : int (None si vide; un numéro lu 2.0 vaut 2); décimal : texte arrondi à
    l'échelle de la colonne, comme le taux des fichiers; bit : 0 ou 1; tout autre
    type : texte tel que dans les fichiers (`texte_livre`).
    """
    from .anomalies import _numero

    if type_sql in TYPES_ENTIERS:
        return _numero(valeur)
    if type_sql in ("decimal", "numeric"):
        if _vide(valeur):
            return None
        return f"{float(valeur):.{int(echelle or 0)}f}"
    if type_sql == "bit":
        return None if _absente(valeur) else int(bool(valeur))
    return texte_livre(valeur)


def convertir_lignes(
    table: str,
    lignes: list[dict],
    colonnes_base: dict[str, tuple],
    ids_chargement: dict[tuple, int],
    communs: dict,
) -> tuple[list[str], list[list], list[str]]:
    """Colonnes, valeurs et problèmes d'une table de qualite avant insertion.

    `colonnes_base` donne, par colonne de la table en base, (type, longueur maximale
    en caractères, échelle). Problèmes, sans aucune valeur : colonne inconnue de la
    table, texte plus long que sa colonne, fichier source (ou fichier du référentiel)
    absent du journal des chargements. Chaque clé provisoire de lignage
    (`CLES_LIGNAGE`) présente dans une ligne devient sa colonne d'id_chargement, en
    fin de ligne, dans l'ordre de `CLES_LIGNAGE`.
    """
    problemes: list[str] = []
    if not lignes:
        return [], [], problemes
    # Colonnes de toutes les lignes, dans l'ordre de leur première apparition : les
    # anomalies brutes n'ont pas la colonne decision_metier des anomalies nettoyées.
    noms = list(communs)
    for ligne in lignes:
        noms += [c for c in ligne if c not in CLES_LIGNAGE and c not in noms]
    cles_presentes = [c for c in CLES_LIGNAGE if any(c in ligne for ligne in lignes)]
    noms += [CLES_LIGNAGE[c] for c in cles_presentes]
    inconnues = [c for c in noms if c not in colonnes_base]
    if inconnues:
        return noms, [], [f"qualite.{table} : colonnes inconnues en base {', '.join(inconnues)}"]
    trop_longues: dict[str, int] = {}
    hors_journal = 0
    valeurs = []
    for ligne in lignes:
        complete = {**communs, **ligne}
        absente = False
        for cle_provisoire in cles_presentes:
            if cle_provisoire not in ligne:
                continue
            cle = ligne[cle_provisoire]
            absente = absente or (cle is not None and cle not in ids_chargement)
            complete[CLES_LIGNAGE[cle_provisoire]] = (
                None if cle is None else ids_chargement.get(cle)
            )
        hors_journal += absente
        rangee = []
        for nom in noms:
            type_sql, longueur, echelle = colonnes_base[nom]
            valeur = valeur_sql(complete.get(nom), type_sql, echelle)
            if isinstance(valeur, str) and longueur and longueur > 0 and longueur_sql(valeur) > longueur:
                trop_longues[nom] = trop_longues.get(nom, 0) + 1
            rangee.append(valeur)
        valeurs.append(rangee)
    for nom, nombre in trop_longues.items():
        longueur = colonnes_base[nom][1]
        problemes.append(
            f"qualite.{table}.{nom} : {nombre} valeur(s) de plus de {longueur} caractères"
        )
    if hors_journal:
        problemes.append(
            f"qualite.{table} : {hors_journal} ligne(s) dont le fichier source n'est pas "
            "dans le journal des chargements"
        )
    return noms, valeurs, problemes


def _inserer_qualite(curseur, table: str, noms: list[str], valeurs: list[list], colonnes_base) -> None:
    import pyodbc

    instruction = (
        f"INSERT INTO qualite.{table} ({', '.join(noms)}) VALUES ({', '.join('?' * len(noms))})"
    )
    try:
        for debut in range(0, len(valeurs), TAILLE_LOT):
            lot = valeurs[debut:debut + TAILLE_LOT]
            tailles = []
            for position, nom in enumerate(noms):
                type_sql = colonnes_base[nom][0]
                if type_sql == "bigint":
                    tailles.append((pyodbc.SQL_BIGINT, 0, 0))
                elif type_sql in TYPES_ENTIERS or type_sql == "bit":
                    tailles.append((pyodbc.SQL_INTEGER, 0, 0))
                else:
                    longueur = max(
                        (longueur_sql(l[position]) for l in lot if l[position] is not None),
                        default=1,
                    )
                    tailles.append((pyodbc.SQL_WVARCHAR, max(1, longueur), 0))
            curseur.setinputsizes(tailles)
            curseur.executemany(instruction, lot)
    finally:
        curseur.setinputsizes(None)


class CompleterQualite:
    """Fonction `completer` de `ecrire_base` qui écrit les sorties dans qualite.

    Les refus (`problemes_sorties`, longueurs, lignage) sont tous listés dans une
    seule `ErreurEcriture`, avant la première insertion : la transaction est annulée
    et l'exécution inscrite « échouée ». Après l'écriture, `comptes` donne le nombre
    de lignes écrites par table.
    """

    def __init__(self, sorties: SortiesQualite, periode_fin: str,
                 sensibles: dict | None = None, declarations: dict | None = None):
        self.sorties = sorties
        self.periode_fin = periode_fin
        self.sensibles = sensibles
        self.declarations = declarations
        self.comptes: dict[str, int] = {}

    def __call__(self, curseur, id_execution: int, ids_chargement: dict[tuple, int]) -> None:
        problemes = problemes_sorties(self.sorties, self.periode_fin, self.sensibles, self.declarations)
        if problemes:
            raise ErreurEcriture(
                "Écriture de qualite refusée\n  " + "\n  ".join(problemes)
            )
        colonnes_base: dict[str, dict[str, tuple]] = {}
        for table, colonne, type_sql, longueur, echelle in curseur.execute(
            REQUETE_COLONNES_QUALITE
        ).fetchall():
            colonnes_base.setdefault(table, {})[colonne] = (type_sql, longueur, echelle)
        preparees = []
        for table, lignes in lignes_qualite(self.sorties, self.sensibles).items():
            noms, valeurs, trouves = convertir_lignes(
                table, lignes, colonnes_base.get(table, {}), ids_chargement,
                {"id_execution": id_execution},
            )
            problemes += trouves
            preparees.append((table, noms, valeurs))
        if problemes:
            raise ErreurEcriture("Écriture de qualite refusée\n  " + "\n  ".join(problemes))
        for table, noms, valeurs in preparees:
            if valeurs:
                _inserer_qualite(curseur, table, noms, valeurs, colonnes_base[table])
            self.comptes[table] = len(valeurs)


# --- Vérification de bout en bout (7.2e) --------------------------------------------

COLONNES_VERIFICATION = ["famille", "controle", "attendu", "obtenu", "conforme"]
FAMILLE_EXECUTION = "exécution"
FAMILLE_ILLISIBLES = "illisibles"
FAMILLE_QUALITE = "qualite"
FAMILLE_DW = "dw"
CONTRAT_RESPECTE = "respecté"
CONTRAT_NON_RESPECTE = "non respecté"
VALEUR_MASQUEE = "masqué"
TABLES_AVEC_ETAT = ("anomalie", "non_evaluable", "bilan_controle")
TABLES_AVEC_LIGNAGE = ("anomalie", "non_evaluable", "journal_nettoyage")


def attendus_table(preparee: TablePreparee) -> list[tuple[str, str, object, bool]]:
    """Agrégats attendus d'une table préparée : (libellé, expression SQL, valeur
    attendue, valeur à masquer).

    Pour toute table : nombre de lignes, puis nombre de cellules renseignées de chaque
    colonne de données. En propre, en plus : somme exacte d'une colonne entière ou
    décimale, plus petite et plus grande valeur d'une date ou d'une heure (écriture ISO).
    Les agrégats d'une colonne sensible, hors décomptes, sont à masquer à l'affichage.
    """
    nom = f"{preparee.schema}.{preparee.table.nom}"
    attendus = [(f"{nom} : lignes", "COUNT(*)", len(preparee.lignes), False)]
    debut = len(preparee.colonnes) - len(preparee.table.colonnes)
    for rang, colonne in enumerate(preparee.table.colonnes):
        valeurs = [l[debut + rang] for l in preparee.lignes if l[debut + rang] is not None]
        libelle = f"{nom}.{colonne.nom}"
        attendus.append((f"{libelle} : cellules renseignées", f"COUNT({colonne.nom})", len(valeurs), False))
        if preparee.schema != SCHEMA_PROPRE:
            continue
        if colonne.famille in (FAMILLE_ENTIER, FAMILLE_DECIMAL):
            with localcontext() as contexte:
                contexte.prec = 60
                somme = sum((Decimal(v) for v in valeurs), Decimal(0)) if valeurs else None
            attendus.append((f"{libelle} : somme", f"SUM({colonne.nom})", somme, colonne.sensible))
        elif colonne.famille in (FAMILLE_DATE, FAMILLE_HEURE):
            attendus.append((f"{libelle} : minimum", f"MIN({colonne.nom})",
                             min(valeurs) if valeurs else None, colonne.sensible))
            attendus.append((f"{libelle} : maximum", f"MAX({colonne.nom})",
                             max(valeurs) if valeurs else None, colonne.sensible))
    return attendus


def valeur_lue(valeur):
    """Valeur rendue par le serveur, sous la forme des valeurs attendues : nombre en
    Decimal, date ou heure en écriture ISO."""
    if valeur is None or isinstance(valeur, bool):
        return valeur
    if isinstance(valeur, (dt.date, dt.time)):
        return valeur.isoformat()
    if isinstance(valeur, (int, float, Decimal)):
        return Decimal(str(valeur))
    return valeur


def _affiche(valeur):
    if isinstance(valeur, Decimal):
        return _decimal_en_texte(valeur)
    return valeur


def conformite(attendu, obtenu) -> bool:
    """Égalité d'un agrégat attendu et lu : un entier attendu est comparé en Decimal."""
    if isinstance(attendu, int) and not isinstance(attendu, bool) and isinstance(obtenu, Decimal):
        attendu = Decimal(attendu)
    return attendu == obtenu


def verifier_base(moteur, ecriture: Ecriture, periode_fin: str,
                  sorties: SortiesQualite | None = None,
                  sensibles: dict | None = None) -> pd.DataFrame:
    """Relit la base après une écriture et compare avec ce que Python a préparé.

    Une ligne par contrôle (`COLONNES_VERIFICATION`), en décomptes et agrégats
    seulement, ceux d'une colonne sensible étant affichés « masqué » : exécution
    unique de la période, au statut réussie; lignes et cellules renseignées de chaque
    table de chargement et de propre, sommes, minimums et maximums de propre;
    cellules illisibles de propre rattachées à une anomalie après nettoyage (même
    ligne source, même champ); avec `sorties`, lignes de chaque table de qualite par
    état (jours fériés, valeurs des listes fermées, rattachements et
    correspondances des codes en doublon compris, `sensibles` étant celui de
    l'écriture), id_chargement renseigné pour toute ligne qui a un fichier source,
    et, par rattachement, lignes rattachées, choisies parmi plusieurs candidates et
    choisies par la date;
    pour dw, procédure de reconstruction présente si et seulement si l'écriture l'a
    appelée, et, si elle l'a été, journal de la reconstruction identique à celui de
    l'écriture et contrat d'entrée respecté par propre et par les rattachements de
    l'exécution; pour chaque fait déclaré par le pack, autant de lignes que dans propre
    et, avec `sorties`, membres -1 et -2 (ou liens non renseignés et introuvables, ou
    numéros renseignés) égaux aux clés vides, introuvables (ou lignes rattachées) du
    bilan des rattachements (`controles_faits`); pour chaque table dont le pack regroupe
    les codes en doublon, aucun membre pour un code en doublon et, avec `sorties`, les
    codes en doublon comptés sur les membres principaux (`controles_regroupements`).
    """
    from sqlalchemy import text

    from .anomalies import _colonnes_du_champ

    controles = []

    def ajouter(famille, controle, attendu, obtenu, masque=False):
        conforme = conformite(attendu, obtenu)
        if masque:
            attendu = obtenu = VALEUR_MASQUEE
        controles.append(
            {"famille": famille, "controle": controle, "attendu": _affiche(attendu),
             "obtenu": _affiche(obtenu), "conforme": conforme}
        )

    preparation = ecriture.preparation
    execution = {"e": ecriture.id_execution}
    with moteur.connect() as conn:
        executions = conn.execute(
            text("SELECT id_execution, statut FROM qualite.execution WHERE periode_fin = :p"),
            {"p": periode_fin},
        ).all()
        ajouter(FAMILLE_EXECUTION, f"exécutions de la période {periode_fin}", 1, len(executions))
        ajouter(FAMILLE_EXECUTION, "exécution écrite, au statut réussie",
                f"{ecriture.id_execution} {STATUT_REUSSIE}",
                ", ".join(f"{i} {s}" for i, s in executions) or None)

        for preparee in preparation.tables:
            attendus = attendus_table(preparee)
            ligne = conn.execute(
                text(f"SELECT {', '.join(a[1] for a in attendus)} "
                     f"FROM {preparee.schema}.{preparee.table.nom}")
            ).one()
            for (libelle, _, attendu, masque), obtenu in zip(attendus, ligne):
                ajouter(preparee.schema, libelle, attendu, valeur_lue(obtenu), masque)

        connues = set()
        for table, champ, fichier, feuille, numero in conn.execute(
            text("SELECT table_source, champ, fichier_source, feuille_source, num_ligne_source "
                 "FROM qualite.anomalie WHERE id_execution = :e AND etat = N'nettoyé'"),
            execution,
        ).all():
            for autre, colonne in _colonnes_du_champ(table, champ):
                connues.add((autre, colonne, fichier, _feuille(feuille), numero))
        cellules = preparation.cellules_illisibles
        rattachees = sum(
            1 for c in cellules.itertuples(index=False)
            if (c.table, c.colonne, c.fichier_source, c.feuille_source, c.num_ligne_source) in connues
        )
        ajouter(FAMILLE_ILLISIBLES, "cellules illisibles de propre rattachées à une anomalie "
                "après nettoyage", len(cellules), rattachees)

        if sorties is not None:
            attendus_qualite = {
                ("anomalie", ETAT_BRUT): len(sorties.anomalies_brutes),
                ("anomalie", ETAT_NETTOYE): len(sorties.anomalies_nettoyees),
                ("non_evaluable", ETAT_BRUT): len(sorties.non_evaluables_brutes),
                ("non_evaluable", ETAT_NETTOYE): len(sorties.non_evaluables_nettoyees),
                ("bilan_controle", ETAT_BRUT): len(sorties.bilan_brut),
                ("bilan_controle", ETAT_NETTOYE): len(sorties.bilan_nettoye),
                ("journal_nettoyage", None): len(sorties.journal_nettoyage),
                ("bilan_nettoyage", None): len(sorties.bilan_nettoyage),
                ("decision", None): len(sorties.decisions.get("decisions") or {}),
                ("jour_ferie", None): len(lignes_jours_feries(sorties.jours_feries)),
                ("valeur_liste", None): len(lignes_valeurs_liste(
                    sorties.dictionnaire, _sensibles(sensibles)
                )),
                ("regle_rattachement", None): len(lignes_regles_rattachement(
                    sorties.rattachements
                )),
                ("rattachement", None): len(lignes_rattachement(sorties.rattachements)),
                ("correspondance_cle", None): len(lignes_correspondances(
                    sorties.correspondances
                )),
            }
            for (table, etat), attendu in attendus_qualite.items():
                filtre = " AND etat = :etat" if etat else ""
                obtenu = conn.execute(
                    text(f"SELECT COUNT(*) FROM qualite.{table} WHERE id_execution = :e{filtre}"),
                    {**execution, **({"etat": etat} if etat else {})},
                ).scalar()
                libelle = f"qualite.{table}" + (f", état {etat}" if etat else "") + " : lignes"
                ajouter(FAMILLE_QUALITE, libelle, attendu, obtenu)
            for table in TABLES_AVEC_LIGNAGE:
                obtenu = conn.execute(
                    text(f"SELECT COUNT(*) FROM qualite.{table} WHERE id_execution = :e "
                         "AND fichier_source IS NOT NULL AND fichier_source <> N'' "
                         "AND id_chargement IS NULL"),
                    execution,
                ).scalar()
                ajouter(FAMILLE_QUALITE, f"qualite.{table} : lignes avec un fichier source "
                        "sans id_chargement", 0, obtenu)
            if sorties.rattachements is not None:
                _verifier_rattachements(conn, ecriture.id_execution, sorties.rattachements,
                                        ajouter)
        _verifier_dw(conn, ecriture, ajouter,
                     None if sorties is None else sorties.rattachements,
                     None if sorties is None else sorties.correspondances)
    return pd.DataFrame(controles, columns=COLONNES_VERIFICATION)


def _verifier_rattachements(conn, id_execution: int, rattachements, ajouter) -> None:
    """Lignes de qualite.rattachement par rattachement, et parmi elles celles choisies
    entre plusieurs lignes du référentiel, puis par la date, comparées au calcul."""
    from sqlalchemy import text

    lues = {
        int(regle): (int(lignes), int(plusieurs), int(par_date))
        for regle, lignes, plusieurs, par_date in conn.execute(
            text("SELECT id_regle, COUNT(*), "
                 "SUM(CASE WHEN candidates > 1 THEN 1 ELSE 0 END), "
                 "SUM(CAST(choix_par_date AS int)) "
                 "FROM qualite.rattachement WHERE id_execution = :e GROUP BY id_regle"),
            {"e": id_execution},
        ).all()
    }
    bilan = rattachements.bilan.set_index("regle")
    for rang, regle in enumerate(rattachements.regles, start=1):
        attendu = (int(bilan.loc[rang, "rattachees"]), int(bilan.loc[rang, "plusieurs_candidates"]),
                   int(bilan.loc[rang, "choisies_par_date"]))
        ajouter(FAMILLE_QUALITE,
                f"qualite.rattachement {rang} ({regle.libelle()}) : lignes, parmi plusieurs "
                "candidates, choisies par la date",
                " / ".join(map(str, attendu)), " / ".join(map(str, lues.get(rang, (0, 0, 0)))))


# Formes du contrôle d'un rattachement sur un fait (dw.contrat_rattachement.forme).
FORME_MEMBRE = "membre"
FORME_LIEN = "lien"
FORME_NUMERO = "numero"
LIEN_NON_RENSEIGNE = "non renseignée"
LIEN_INTROUVABLE = "introuvable"
_NOM_DW = re.compile(r"[a-z_][a-z0-9_]*")
REQUETE_FAITS_SOURCES = "SELECT table_fait, table_source FROM dw.source_fait ORDER BY table_fait"
REQUETE_CONTRATS_FAITS = (
    "SELECT table_source, cle, table_reference, table_fait, colonne_fait, forme "
    "FROM dw.contrat_rattachement WHERE table_fait IS NOT NULL ORDER BY id_contrat"
)
REQUETE_REGROUPEMENTS = (
    "SELECT table_source, table_dimension, colonne_code FROM dw.regroupement_codes "
    "ORDER BY table_source"
)


@dataclass(frozen=True)
class ControleFait:
    """Un contrôle d'un fait de dw : libellé, valeur attendue (calculée en Python) et
    requête qui rend la valeur obtenue en une ligne, une colonne par nombre (None si
    le contrôle est impossible, `probleme` disant pourquoi)."""

    libelle: str
    attendu: object
    requete: str | None
    probleme: str | None = None


def _nom_dw(nom) -> bool:
    return isinstance(nom, str) and _NOM_DW.fullmatch(nom) is not None


def controles_faits(sources: list[tuple], contrats: list[tuple], lignes: pd.DataFrame,
                    bilan: pd.DataFrame | None) -> list[ControleFait]:
    """Contrôles des faits déclarés par le pack, sans valeur du client.

    `sources` : (fait, table du dictionnaire) de dw.source_fait; chaque fait doit avoir
    autant de lignes que Python en a écrit dans propre pour sa table (`lignes`, colonnes
    table et propre de `Ecriture.lignes`). `contrats` : (table, clé, référentiel, fait,
    colonne, forme) de dw.contrat_rattachement; avec le bilan des rattachements
    (`rattachement.Rattachements.bilan`, le premier rattachement de même table, clé et
    référentiel faisant foi, comme dw.regle_rattachement), la colonne du fait doit
    compter :

    - forme membre : autant de -1 que de clés vides et de -2 que de clés introuvables;
    - forme lien : autant de « non renseignée » et d'« introuvable »;
    - forme numero : autant de valeurs renseignées que de lignes rattachées.

    Sans bilan, seuls les nombres de lignes sont contrôlés. Un nom de fait ou de colonne
    qui n'est pas un identifiant simple, un fait sans table dans propre ou un
    rattachement absent du bilan rendent un contrôle impossible (`probleme`).
    """
    controles = []
    propre = {str(t): int(n) for t, n in zip(lignes["table"], lignes[SCHEMA_PROPRE])}
    for fait, table in sources:
        libelle = f"dw.{fait} : une ligne par ligne de propre.{table}"
        if not _nom_dw(fait):
            controles.append(ControleFait(libelle, None, None, "nom de fait invalide"))
        elif table not in propre:
            controles.append(ControleFait(libelle, None, None, "table absente de l'écriture"))
        else:
            controles.append(
                ControleFait(libelle, propre[table], f"SELECT COUNT(*) FROM dw.{fait}")
            )
    if bilan is None:
        return controles
    premiers: dict[tuple, dict] = {}
    for ligne in bilan.to_dict("records"):
        premiers.setdefault((ligne["table"], ligne["cle"], ligne["table_reference"]), ligne)
    for table, cle, reference, fait, colonne, forme in contrats:
        libelle = f"dw.{fait}.{colonne} ({forme}) : rattachement {table}.{cle} vers {reference}"
        ligne = premiers.get((table, cle, reference))
        if not (_nom_dw(fait) and _nom_dw(colonne)):
            controles.append(ControleFait(libelle, None, None, "nom de fait ou de colonne invalide"))
        elif ligne is None:
            controles.append(ControleFait(libelle, None, None, "rattachement absent du bilan"))
        elif forme == FORME_MEMBRE:
            controles.append(ControleFait(
                libelle + ", membres -1 / -2",
                f"{int(ligne['cles_vides'])} / {int(ligne['introuvables'])}",
                f"SELECT SUM(CASE WHEN {colonne} = -1 THEN 1 ELSE 0 END), "
                f"SUM(CASE WHEN {colonne} = -2 THEN 1 ELSE 0 END) FROM dw.{fait}",
            ))
        elif forme == FORME_LIEN:
            controles.append(ControleFait(
                libelle + f", {LIEN_NON_RENSEIGNE} / {LIEN_INTROUVABLE}",
                f"{int(ligne['cles_vides'])} / {int(ligne['introuvables'])}",
                f"SELECT SUM(CASE WHEN {colonne} = N'{LIEN_NON_RENSEIGNE}' THEN 1 ELSE 0 END), "
                f"SUM(CASE WHEN {colonne} = N'{LIEN_INTROUVABLE}' THEN 1 ELSE 0 END) "
                f"FROM dw.{fait}",
            ))
        elif forme == FORME_NUMERO:
            controles.append(ControleFait(
                libelle + ", renseignés",
                int(ligne["rattachees"]),
                f"SELECT COUNT({colonne}) FROM dw.{fait}",
            ))
        else:
            controles.append(ControleFait(libelle, None, None, "forme inconnue"))
    return controles


def controles_regroupements(regroupements: list[tuple], correspondances: pd.DataFrame | None,
                            id_execution: int) -> list[ControleFait]:
    """Contrôles des codes en doublon regroupés par le pack, sans valeur du client.

    `regroupements` : (table du dictionnaire, dimension, colonne du code) de
    dw.regroupement_codes. Pour chacun, aucun membre de la dimension n'a pour code un
    code en doublon de la table dans qualite.correspondance_cle; avec `correspondances`
    (`nettoyage.nettoyer`), la somme de codes_en_doublon des membres est le nombre de
    codes en doublon de la table, ce qui suppose que chaque code principal a son
    membre. Les faits qui citent un code en doublon sont couverts par les membres -1
    et -2 de `controles_faits` : un code en doublon sans membre y serait introuvable.
    """
    controles = []
    for table, dimension, colonne in regroupements:
        libelle = f"dw.{dimension} : codes en doublon de {table}"
        if not (_nom_dw(table) and _nom_dw(dimension) and _nom_dw(colonne)):
            controles.append(ControleFait(libelle, None, None,
                                          "nom de table, de dimension ou de colonne invalide"))
            continue
        controles.append(ControleFait(
            libelle + ", aucun n'a de membre",
            0,
            f"SELECT COUNT(*) FROM dw.{dimension} AS d "
            f"JOIN qualite.correspondance_cle AS c ON c.code_doublon = d.{colonne} "
            f"WHERE c.id_execution = {int(id_execution)} AND c.table_source = N'{table}'",
        ))
        if correspondances is not None:
            controles.append(ControleFait(
                libelle + ", comptés sur les membres principaux (codes_en_doublon)",
                int((correspondances["table"] == table).sum()),
                f"SELECT COALESCE(SUM(codes_en_doublon), 0) FROM dw.{dimension}",
            ))
    return controles


def _obtenu(rangee: tuple):
    """Valeur obtenue d'un contrôle de fait : un nombre, ou « n / m »."""
    nombres = [0 if v is None else int(v) for v in rangee]
    return nombres[0] if len(nombres) == 1 else " / ".join(map(str, nombres))


def _journal_en_texte(journal) -> str | None:
    return "; ".join(f"{ordre}. {etape} {lignes}" for ordre, etape, lignes in journal) or None


def _verifier_dw(conn, ecriture: Ecriture, ajouter, rattachements=None,
                 correspondances=None) -> None:
    """Contrôles de la famille dw de `verifier_base`, sur la connexion ouverte, puis
    ceux des faits déclarés par le pack (`controles_faits`) et des codes en doublon
    qu'il regroupe (`controles_regroupements`)."""
    import pyodbc

    from .base import procedure_reconstruction_presente

    curseur = conn.connection.cursor()
    try:
        presente = procedure_reconstruction_presente(curseur)
        appelee = ecriture.journal_dw is not None
        ajouter(FAMILLE_DW, "procédure dw.reconstruire présente si l'écriture l'a appelée",
                appelee, presente)
        if not appelee or not presente:
            return
        curseur.execute(
            "SELECT ordre, etape, lignes FROM dw.journal_reconstruction "
            "WHERE id_execution = ? ORDER BY ordre",
            ecriture.id_execution,
        )
        lu = [(int(o), e, int(l)) for o, e, l in curseur.fetchall()]
        ajouter(FAMILLE_DW, f"dw.journal_reconstruction de l'exécution {ecriture.id_execution}",
                _journal_en_texte(ecriture.journal_dw), _journal_en_texte(lu))
        try:
            curseur.execute("EXEC dw.verifier_contrat ?", ecriture.id_execution)
            while curseur.nextset():
                pass
            contrat = CONTRAT_RESPECTE
        except pyodbc.Error:
            contrat = CONTRAT_NON_RESPECTE
        ajouter(FAMILLE_DW, "contrat d'entrée du pack respecté par propre et les rattachements",
                CONTRAT_RESPECTE, contrat)
        curseur.execute(REQUETE_FAITS_SOURCES)
        sources = [tuple(r) for r in curseur.fetchall()]
        curseur.execute(REQUETE_CONTRATS_FAITS)
        contrats = [tuple(r) for r in curseur.fetchall()]
        bilan = None if rattachements is None else rattachements.bilan
        curseur.execute(REQUETE_REGROUPEMENTS)
        regroupements = [tuple(r) for r in curseur.fetchall()]
        for controle in controles_faits(sources, contrats, ecriture.lignes, bilan) + \
                controles_regroupements(regroupements, correspondances, ecriture.id_execution):
            if controle.requete is None:
                ajouter(FAMILLE_DW, controle.libelle, controle.probleme, None)
                continue
            curseur.execute(controle.requete)
            ajouter(FAMILLE_DW, controle.libelle, controle.attendu, _obtenu(tuple(curseur.fetchone())))
    finally:
        curseur.close()
