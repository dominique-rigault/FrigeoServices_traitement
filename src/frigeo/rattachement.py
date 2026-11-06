"""Rattachement des lignes aux référentiels (étape 7.3d).

Une ligne de fait (une intervention, une ligne de facture) cite un référentiel par une
clé écrite telle que saisie : le nom de l'intervenant, le code du client. Les règles de
gestion savent déjà rapprocher ces clés de leur référentiel, avec une comparaison
déclarée (telle quelle, après normalisation, mots dans le désordre) et, pour certaines,
une date qui doit tomber dans une période du référentiel. Ce module reprend ces règles
pour dire, ligne par ligne, quelle ligne du référentiel la ligne cite. Le modèle en
étoile s'en sert pour relier chaque fait au bon membre de dimension, sans réécrire en
SQL la comparaison des clés : aucune règle n'est écrite deux fois.

Règles reprises : celles de config/gestion.yaml de type existence_dans_reference ou
date_dans_periode_reference (`gestion.TYPES_AVEC_REFERENTIEL`). Deux règles de même
table, clé, référentiel, clé du référentiel et comparaison donnent un seul
rattachement; la variante avec date est gardée. Le filtre d'une règle n'est pas
appliqué : il dit quelles lignes contrôler, pas lesquelles rattacher.

Calcul, sur les tables nettoyées (le contenu du schéma propre) :

- la clé de chaque ligne, des deux côtés, est lue comme par la règle
  (`gestion._cles_comparees`); une clé vide ou absente du référentiel ne donne aucun
  rattachement (la ligne de fait ira vers le membre « non renseigné » ou
  « introuvable » de sa dimension);
- une seule ligne du référentiel porte la clé : c'est elle;
- plusieurs lignes la portent et la règle a une date : celle dont la période (début à
  fin, bornes incluses, fin vide ou absente ouverte) contient la date de la ligne, si
  elle est seule;
- sinon, la première dans l'ordre du lignage (fichier, feuille, numéro de ligne), comme
  les dimensions.

Rien n'est écrit ici : `rattacher` rend les lignes, désignées par leur lignage, et un
bilan par rattachement, en décomptes. Aucune valeur du client n'y figure.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .doublons import COMPARAISON_TELLE_QUELLE
from .gestion import (
    TYPES_AVEC_REFERENTIEL,
    _avec_defauts,
    _cles_comparees,
    _lire_dates,
)
from .typage import ETAT_LUE, ETAT_VIDE

TYPE_AVEC_DATE = "date_dans_periode_reference"

COLONNES_RATTACHEMENT = (
    "regle",
    "fichier_source",
    "feuille_source",
    "num_ligne_source",
    "fichier_reference",
    "feuille_reference",
    "num_ligne_reference",
    "candidates",
    "choix_par_date",
)
COLONNES_BILAN_RATTACHEMENT = (
    "regle",
    "table",
    "cle",
    "table_reference",
    "cle_reference",
    "comparaison",
    "date",
    "lignes",
    "cles_vides",
    "introuvables",
    "rattachees",
    "plusieurs_candidates",
    "choisies_par_date",
)


@dataclass(frozen=True)
class RegleRattachement:
    """Un rattachement : clé d'une table vers la clé d'un référentiel.

    `date`, `debut` et `fin` viennent d'une règle date_dans_periode_reference (`fin`
    peut manquer); `refs` donne les références des règles de gestion reprises.
    """

    table: str
    cle: tuple[str, ...]
    table_reference: str
    cle_reference: tuple[str, ...]
    comparaison: str = COMPARAISON_TELLE_QUELLE
    date: str | None = None
    debut: str | None = None
    fin: str | None = None
    refs: tuple[str, ...] = ()

    @property
    def identite(self) -> tuple:
        return (self.table, self.cle, self.table_reference, self.cle_reference,
                self.comparaison)

    @property
    def avec_date(self) -> bool:
        return self.date is not None

    def libelle(self) -> str:
        """« interventions.intervenant vers intervenants.nom, prenom »."""
        return (f"{self.table}.{', '.join(self.cle)} vers "
                f"{self.table_reference}.{', '.join(self.cle_reference)}")


def regles_rattachement(regles: list) -> list[RegleRattachement]:
    """Rattachements déduits des règles de gestion (déjà chargées et complétées), dans
    l'ordre de la première règle de chacun.

    Seules les règles des types `TYPES_AVEC_REFERENTIEL` comptent; la clé du
    référentiel reprend par défaut celle de la ligne. Deux règles de même identité
    (table, clé, référentiel, clé du référentiel, comparaison) n'en font qu'un : la
    première variante avec date est gardée, et les références des deux règles sont
    réunies.
    """
    rattachements: dict[tuple, RegleRattachement] = {}
    for instance in regles:
        if instance.get("type") not in TYPES_AVEC_REFERENTIEL:
            continue
        complete = _avec_defauts(instance)
        avec_date = instance["type"] == TYPE_AVEC_DATE
        regle = RegleRattachement(
            table=complete["table"],
            cle=tuple(complete["cle"]),
            table_reference=complete["table_reference"],
            cle_reference=tuple(complete["cle_reference"]),
            comparaison=complete.get("comparaison", COMPARAISON_TELLE_QUELLE),
            date=complete["date"] if avec_date else None,
            debut=complete["debut"] if avec_date else None,
            fin=complete.get("fin") if avec_date else None,
            refs=(str(complete.get("ref")),),
        )
        connue = rattachements.get(regle.identite)
        if connue is None:
            rattachements[regle.identite] = regle
            continue
        refs = connue.refs + tuple(r for r in regle.refs if r not in connue.refs)
        gardee = regle if regle.avec_date and not connue.avec_date else connue
        rattachements[regle.identite] = RegleRattachement(
            gardee.table, gardee.cle, gardee.table_reference, gardee.cle_reference,
            gardee.comparaison, gardee.date, gardee.debut, gardee.fin, refs,
        )
    return list(rattachements.values())


@dataclass
class Rattachements:
    """Résultat de `rattacher`.

    `regles` : les rattachements, numérotés par leur rang à partir de 1 (colonne
    `regle` des deux tables). `lignes` (`COLONNES_RATTACHEMENT`) : une ligne par ligne
    rattachée, la ligne source et la ligne du référentiel désignées par leur lignage,
    avec le nombre de lignes du référentiel qui portaient la clé et le choix par la
    date. `bilan` (`COLONNES_BILAN_RATTACHEMENT`) : décomptes par rattachement.
    """

    regles: list[RegleRattachement]
    lignes: pd.DataFrame
    bilan: pd.DataFrame

    def lignes_par_regle(self) -> dict[int, int]:
        """Nombre de lignes rattachées par rang de rattachement (zéro compris)."""
        comptes = self.lignes["regle"].value_counts()
        return {rang: int(comptes.get(rang, 0)) for rang in range(1, len(self.regles) + 1)}


def _feuille(valeur) -> str | None:
    """Feuille du lignage, None pour un fichier sans feuille (CSV)."""
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return None
    texte = str(valeur)
    return texte if texte.strip() else None


def _lignage(donnees: pd.DataFrame) -> list[tuple[str, str | None, int]]:
    """(fichier, feuille, numéro de ligne) de chaque ligne, dans l'ordre de la table."""
    return [
        (str(fichier), _feuille(feuille), int(numero))
        for fichier, feuille, numero in zip(
            donnees["fichier_source"],
            donnees.get("feuille_source", pd.Series([None] * len(donnees), index=donnees.index)),
            donnees["num_ligne_source"],
        )
    ]


def _ordre(lignage: tuple) -> tuple:
    fichier, feuille, numero = lignage
    return (fichier, feuille or "", numero)


def _problemes(regles: list[RegleRattachement], tables: dict, dictionnaire: dict) -> list[str]:
    """Tables, colonnes et natures manquantes, toutes listées."""
    problemes = []
    for rang, regle in enumerate(regles, start=1):
        cotes = (
            (regle.table, [*regle.cle, *([regle.date] if regle.date else [])]),
            (regle.table_reference,
             [*regle.cle_reference, *(c for c in (regle.debut, regle.fin) if c)]),
        )
        for table, colonnes in cotes:
            if table not in tables:
                problemes.append(f"rattachement {rang} ({regle.libelle()}) : table {table} absente")
                continue
            absentes = [
                c for c in [*colonnes, "fichier_source", "num_ligne_source"]
                if c not in tables[table].columns
            ]
            if absentes:
                problemes.append(
                    f"rattachement {rang} ({regle.libelle()}) : colonnes absentes de {table} "
                    + ", ".join(absentes)
                )
            sans_nature = [
                c for c in colonnes
                if c in (regle.date, regle.debut, regle.fin)
                and c not in dictionnaire.get(table, {})
            ]
            if sans_nature:
                problemes.append(
                    f"rattachement {rang} ({regle.libelle()}) : colonnes de {table} absentes du "
                    "dictionnaire " + ", ".join(sans_nature)
                )
    return problemes


def _nature(dictionnaire: dict, table: str, colonne: str | None) -> str | None:
    if colonne is None:
        return None
    return dictionnaire[table][colonne]["nature"]["regle"]


def _rattacher_une(rang: int, regle: RegleRattachement, tables: dict, dictionnaire: dict):
    donnees = tables[regle.table].reset_index(drop=True)
    reference = tables[regle.table_reference].reset_index(drop=True)
    lignage_source = _lignage(donnees)
    lignage_reference = _lignage(reference)

    cles = _cles_comparees(donnees, list(regle.cle), regle.comparaison)
    cles_reference = _cles_comparees(reference, list(regle.cle_reference), regle.comparaison)
    candidates: dict[str, list[int]] = {}
    for position in sorted(range(len(reference)), key=lambda p: _ordre(lignage_reference[p])):
        cle = cles_reference.iloc[position]
        if cle is not None:
            candidates.setdefault(cle, []).append(position)

    if regle.avec_date:
        dates, _ = _lire_dates(donnees, regle.date, _nature(dictionnaire, regle.table, regle.date))
        debuts, etats_debut = _lire_dates(
            reference, regle.debut, _nature(dictionnaire, regle.table_reference, regle.debut)
        )
        fins, etats_fin = _lire_dates(
            reference, regle.fin, _nature(dictionnaire, regle.table_reference, regle.fin)
        )

        def contient(position: int, date) -> bool:
            if etats_debut.iloc[position] != ETAT_LUE or debuts.iloc[position] > date:
                return False
            etat_fin = etats_fin.iloc[position]
            return etat_fin == ETAT_VIDE or (etat_fin == ETAT_LUE and date <= fins.iloc[position])

    lignes = []
    vides = introuvables = plusieurs = par_date = 0
    for position, cle in enumerate(cles):
        if cle is None:
            vides += 1
            continue
        liste = candidates.get(cle)
        if liste is None:
            introuvables += 1
            continue
        choisie, choix_par_date = liste[0], False
        if len(liste) > 1:
            plusieurs += 1
            if regle.avec_date and pd.notna(dates.iloc[position]):
                contenantes = [p for p in liste if contient(p, dates.iloc[position])]
                if len(contenantes) == 1:
                    choisie, choix_par_date = contenantes[0], True
                    par_date += 1
        source, cible = lignage_source[position], lignage_reference[choisie]
        lignes.append((rang, *source, *cible, len(liste), choix_par_date))
    bilan = {
        "regle": rang,
        "table": regle.table,
        "cle": ", ".join(regle.cle),
        "table_reference": regle.table_reference,
        "cle_reference": ", ".join(regle.cle_reference),
        "comparaison": regle.comparaison,
        "date": regle.date,
        "lignes": len(donnees),
        "cles_vides": vides,
        "introuvables": introuvables,
        "rattachees": len(lignes),
        "plusieurs_candidates": plusieurs,
        "choisies_par_date": par_date,
    }
    return lignes, bilan


def rattacher(
    tables: dict[str, pd.DataFrame],
    dictionnaire: dict,
    regles: list | None = None,
) -> Rattachements:
    """Rattache les lignes des tables à leurs référentiels (voir l'en-tête du module).

    `tables` : les tables nettoyées, avec leur lignage (fichier_source, feuille_source,
    num_ligne_source). `dictionnaire` : le dictionnaire enregistré, dont la nature en
    vigueur dit comment lire les dates. `regles` : les règles de gestion, celles de
    config/gestion.yaml par défaut (`gestion.charger_regles_gestion`).

    Une table, une colonne ou une nature manquante lève `ValueError`, tous les problèmes
    étant listés en une fois, sans valeur. Les arguments ne sont pas modifiés.
    """
    if regles is None:
        from .gestion import charger_regles_gestion

        regles = charger_regles_gestion()
    retenues = regles_rattachement(regles)
    problemes = _problemes(retenues, tables, dictionnaire)
    if problemes:
        raise ValueError("Rattachements impossibles\n  " + "\n  ".join(problemes))
    lignes, bilans = [], []
    for rang, regle in enumerate(retenues, start=1):
        trouvees, bilan = _rattacher_une(rang, regle, tables, dictionnaire)
        lignes += trouvees
        bilans.append(bilan)
    return Rattachements(
        retenues,
        pd.DataFrame(lignes, columns=list(COLONNES_RATTACHEMENT)),
        pd.DataFrame(bilans, columns=list(COLONNES_BILAN_RATTACHEMENT)),
    )
