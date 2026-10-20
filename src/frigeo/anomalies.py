"""Table des anomalies (étape 5).

Ce module ne contient rien de propre à un client. Il réunit, dans un format commun,
les trois tables rendues par les contrôles :

- les écarts de format et de complétude (`controles.controler`), à la maille de la
  cellule;
- les doublons (`doublons.detecter_doublons`), à la maille de la ligne;
- les écarts de gestion (`gestion.controler_gestion`), à la maille de la ligne, ou
  de la période pour un total (ces écarts n'ont pas de lignage).

Chaque ligne garde la maille de sa source : une même ligne source peut donc porter
plusieurs anomalies. Les trois issues sont gardées (anomalie, à arbitrer,
information); seules les anomalies sont comptées comme telles au bilan.

`reunir_anomalies` ajoute aux écarts de format la clé métier de leur ligne (clé
déclarée dans le bloc `doublons` de config/controles.yaml), ajoute à toutes les
lignes la période de l'export de leur ligne source, et donne à chacune un
identifiant stable (`id_anomalie`), empreinte de son contrôle et de sa ligne
source. `bilan_controles` rend une ligne par contrôle, avec les nombres de lignes
contrôlées, d'anomalies, d'écarts à arbitrer et d'informations, le taux
d'anomalies et le nombre de lignes sources distinctes en anomalie.

`reunir_anomalies` et `bilan_controles` laissent vides la gravité et les
indicateurs affectés; `qualifier` les renseigne d'après config/anomalies.yaml
(`charger_qualification`) : indicateurs alimentés par chaque colonne, exceptions
par contrôle. Rien n'est corrigé.

`ecrire_anomalies` écrit la table qualifiée et son bilan en CSV dans
data/anomalies/ (`anomalies_AAAA-MM.csv`, `bilan_AAAA-MM.csv`), après avoir vérifié
qu'aucune valeur sensible n'y est visible; c'est la seule fonction du module qui
écrit sur disque.
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
from pathlib import Path

import pandas as pd
import yaml

from . import racine_projet

from .confidentialite import charger_sensibilite, est_sensible
from .controles import (
    COLONNES_BILAN,
    COLONNES_ECARTS,
    COLONNES_LIGNAGE_ECART,
    ISSUE_A_ARBITRER,
    ISSUE_ANOMALIE,
    VALEUR_MASQUEE,
    _colonnes_de_donnees,
)
from .doublons import (
    COLONNES_BILAN_DOUBLONS,
    COLONNES_DOUBLONS,
    CONSTAT_EXACT,
    CONSTAT_HORS_CLE,
    SEPARATEUR,
    TOUTES_COLONNES,
    _texte,
    charger_declarations_doublons,
)
from .gestion import COLONNES_BILAN_GESTION, COLONNES_ECARTS_GESTION, ISSUE_INFORMATION

# Famille du contrôle, dans l'ordre de la table et du bilan.
ETAPE_FORMAT = "format"
ETAPE_DOUBLONS = "doublons"
ETAPE_GESTION = "gestion"
ETAPES = (ETAPE_FORMAT, ETAPE_DOUBLONS, ETAPE_GESTION)

# Règle violée par un doublon, selon la déclaration du métier.
REGLE_LIGNES_DIFFERENTES = "lignes toutes différentes"
REGLE_CLE_UNIQUE = "clé unique"
REGLE_VALEURS_UNIQUES = "valeurs uniques"
REGLE_PRESUME_UNIQUE = "valeurs en principe uniques"
REGLE_HORS_CLE = "lignes différentes hors clé"

COLONNE_PERIODE = "periode_export"
LONGUEUR_IDENTIFIANT = 12

COLONNES_ANOMALIES = (
    "id_anomalie",
    "etape",
    "controle",
    "table",
    *COLONNES_LIGNAGE_ECART,
    COLONNE_PERIODE,
    "cle",
    "champ",
    "valeur",
    "regle",
    "constat",
    "issue",
    "statut_regle",
    "detail",
    "proposition",
    "gravite",
    "indicateurs",
)
# Table des anomalies des tables nettoyées (étape 6), avec la décision du métier
# (voir `decisions.ajouter_decisions`).
COLONNE_DECISION_METIER = "decision_metier"
COLONNES_ANOMALIES_NETTOYEES = (*COLONNES_ANOMALIES, COLONNE_DECISION_METIER)
COLONNES_BILAN_ANOMALIES = (
    "etape",
    "controle",
    "table",
    "champ",
    "regle",
    "controlees",
    "anomalies",
    "a_arbitrer",
    "informations",
    "taux",
    "lignes_distinctes",
    "gravite",
    "indicateurs",
)


def _verifier_colonnes(nom: str, donnees: pd.DataFrame, attendues) -> list[str]:
    manquantes = [c for c in attendues if c not in donnees.columns]
    if manquantes:
        return [f"{nom} : colonnes absentes {', '.join(manquantes)}"]
    return []


def _controle_format(table, colonne, regle) -> str:
    return f"{table}.{colonne} {regle}"


def _controle_doublons(table, constat, colonnes) -> str:
    return f"{table} {constat} ({colonnes})"


def _controle_gestion(ref, libelle) -> str:
    return f"{ref} {libelle}"


def _regle_format(regle, en_vigueur) -> str:
    return f"{regle} = {en_vigueur}"


def _regle_doublon(table, constat, colonnes, issue, declarations) -> str:
    """Règle violée par un doublon, d'après le constat et la déclaration."""
    if constat == CONSTAT_EXACT:
        return REGLE_LIGNES_DIFFERENTES
    if constat == CONSTAT_HORS_CLE:
        return REGLE_HORS_CLE
    cle = declarations.get(table, {}).get("cle", [])
    if cle and colonnes == ", ".join(cle):
        return REGLE_CLE_UNIQUE
    return REGLE_VALEURS_UNIQUES if issue == ISSUE_ANOMALIE else REGLE_PRESUME_UNIQUE


def _numero(valeur) -> int | None:
    """Numéro de ligne entier, None sans numéro (un numéro lu 2.0 vaut 2)."""
    texte = _texte(valeur)
    if texte == "":
        return None
    try:
        nombre = float(texte)
    except ValueError:
        return None
    return int(nombre) if nombre.is_integer() else None


def _repere(fichier, feuille, ligne) -> tuple[str, str, str]:
    """Repère d'une ligne source par son lignage, en textes comparables."""
    numero = _numero(ligne)
    return (_texte(fichier), _texte(feuille), "" if numero is None else str(numero))


def _index_lignage(donnees: pd.DataFrame) -> dict[tuple, int]:
    """Position de chaque ligne par son lignage (repères ambigus exclus)."""
    if not all(c in donnees.columns for c in COLONNES_LIGNAGE_ECART):
        return {}
    reperes = [
        _repere(*ligne)
        for ligne in donnees[list(COLONNES_LIGNAGE_ECART)].itertuples(index=False)
    ]
    vus: dict[tuple, int] = {}
    doubles = set()
    for position, repere in enumerate(reperes):
        if repere in vus:
            doubles.add(repere)
        vus[repere] = position
    return {r: p for r, p in vus.items() if r not in doubles and r[2] != ""}


def _empreinte(*parties) -> str:
    texte = "\x1f".join(_texte(p) for p in parties)
    return hashlib.sha1(texte.encode("utf-8")).hexdigest()[:LONGUEUR_IDENTIFIANT]


def reunir_anomalies(
    tables: dict[str, pd.DataFrame],
    ecarts: pd.DataFrame,
    doublons: pd.DataFrame,
    ecarts_gestion: pd.DataFrame,
    bilan: pd.DataFrame,
    bilan_doublons: pd.DataFrame,
    bilan_gestion: pd.DataFrame,
    declarations: dict | None = None,
    sensibles: dict[str, frozenset[str]] | None = None,
) -> pd.DataFrame:
    """Réunit les écarts des trois contrôles dans la table des anomalies.

    `ecarts` et `bilan` viennent de `controles.controler`, `doublons` et
    `bilan_doublons` de `doublons.detecter_doublons`, `ecarts_gestion` et
    `bilan_gestion` de `gestion.controler_gestion`; les bilans donnent l'ordre des
    contrôles. `declarations` (config/controles.yaml par défaut) donne la clé de
    chaque table, `sensibles` (config/sensibilite.yaml par défaut) les colonnes
    dont la clé est masquée.

    Table des anomalies (`COLONNES_ANOMALIES`) : une ligne par écart de chaque
    source, à sa maille. `controle` nomme le contrôle, comme au bilan
    (« table.colonne règle » pour le format, « table constat (colonnes) » pour les
    doublons, « référence libellé » pour la gestion). `champ` porte la ou les
    colonnes du contrôle, `regle` la règle violée en clair, `statut_regle` le
    statut de la règle du dictionnaire (format seulement), `detail` la portée, la
    comparaison et le groupe d'un doublon, `proposition` la correction proposée
    par un contrôle de gestion. La clé d'un écart de format est retrouvée par le
    lignage, d'après la clé déclarée de sa table (vide sans clé déclarée,
    « masqué » si une colonne de la clé est sensible). `periode_export` est celle
    de la ligne source, vide pour un écart sans lignage (un total par période,
    dont la clé porte la période). `gravite` et `indicateurs` sont vides (voir
    `qualifier`).

    `id_anomalie` est une empreinte de l'étape, du contrôle, de la table, du
    lignage, du champ et du constat (et de la clé pour un écart sans lignage) :
    elle ne change pas d'une exécution à l'autre tant que la ligne source garde
    son lignage. Deux lignes de même empreinte arrêtent le traitement.

    Ordre : par étape, puis par contrôle dans l'ordre de son bilan, puis dans
    l'ordre de la table source (lignage; lignes d'un groupe de doublons à la suite;
    écarts sans lignage à la fin de leur règle). Les arguments ne sont pas modifiés.
    """
    if declarations is None:
        declarations = charger_declarations_doublons()
    if sensibles is None:
        sensibles = charger_sensibilite()
    problemes = (
        _verifier_colonnes("table des écarts", ecarts, COLONNES_ECARTS)
        + _verifier_colonnes("table des doublons", doublons, COLONNES_DOUBLONS)
        + _verifier_colonnes("table des écarts de gestion", ecarts_gestion, COLONNES_ECARTS_GESTION)
        + _verifier_colonnes("bilan des écarts", bilan, COLONNES_BILAN)
        + _verifier_colonnes("bilan des doublons", bilan_doublons, COLONNES_BILAN_DOUBLONS)
        + _verifier_colonnes("bilan de gestion", bilan_gestion, COLONNES_BILAN_GESTION)
    )
    if problemes:
        raise ValueError("Tables des contrôles inattendues\n  " + "\n  ".join(problemes))
    rangs = _rangs_controles(bilan, bilan_doublons, bilan_gestion)

    index = {}
    cles_tables = {}
    for table, donnees in tables.items():
        donnees = donnees.reset_index(drop=True)
        index[table] = (_index_lignage(donnees), donnees)
        cle = declarations.get(table, {}).get("cle", [])
        if not cle or any(c not in donnees.columns for c in cle):
            cles_tables[table] = None
        elif any(est_sensible(sensibles, table, c) for c in cle):
            cles_tables[table] = VALEUR_MASQUEE
        else:
            cles_tables[table] = cle

    def situer(ligne):
        """Position de la ligne source dans sa table, None si elle est introuvable."""
        repere = _repere(ligne.fichier_source, ligne.feuille_source, ligne.num_ligne_source)
        reperes, _ = index.get(ligne.table, ({}, None))
        return reperes.get(repere)

    def periode(table, position):
        if position is None:
            return None
        donnees = index[table][1]
        if COLONNE_PERIODE not in donnees.columns:
            return None
        valeur = _texte(donnees.at[position, COLONNE_PERIODE])
        return valeur or None

    def cle_format(table, position):
        cle = cles_tables.get(table)
        if cle is None or position is None:
            return None
        if cle == VALEUR_MASQUEE:
            return VALEUR_MASQUEE
        donnees = index[table][1]
        return SEPARATEUR.join(_texte(donnees.at[position, c]) for c in cle)

    lignes = []
    for ligne in ecarts.itertuples(index=False):
        position = situer(ligne)
        lignes.append(
            {
                "etape": ETAPE_FORMAT,
                "controle": _controle_format(ligne.table, ligne.colonne, ligne.regle),
                "table": ligne.table,
                "fichier_source": ligne.fichier_source,
                "feuille_source": ligne.feuille_source,
                "num_ligne_source": ligne.num_ligne_source,
                COLONNE_PERIODE: periode(ligne.table, position),
                "cle": cle_format(ligne.table, position),
                "champ": ligne.colonne,
                "valeur": ligne.valeur,
                "regle": _regle_format(ligne.regle, ligne.regle_en_vigueur),
                "constat": ligne.constat,
                "issue": ligne.issue,
                "statut_regle": ligne.statut_regle,
                "detail": None,
                "proposition": None,
            }
        )
    for ligne in doublons.itertuples(index=False):
        position = situer(ligne)
        lignes.append(
            {
                "etape": ETAPE_DOUBLONS,
                "controle": _controle_doublons(ligne.table, ligne.constat, ligne.colonnes),
                "table": ligne.table,
                "fichier_source": ligne.fichier_source,
                "feuille_source": ligne.feuille_source,
                "num_ligne_source": ligne.num_ligne_source,
                COLONNE_PERIODE: periode(ligne.table, position),
                "cle": ligne.cle,
                "champ": ligne.colonnes,
                "valeur": ligne.valeur,
                "regle": _regle_doublon(
                    ligne.table, ligne.constat, ligne.colonnes, ligne.issue, declarations
                ),
                "constat": ligne.constat,
                "issue": ligne.issue,
                "statut_regle": None,
                "detail": f"{ligne.portee}, {ligne.comparaison}, groupe {ligne.groupe} "
                f"de {ligne.taille_groupe} lignes",
                "proposition": None,
            }
        )
    for ligne in ecarts_gestion.itertuples(index=False):
        position = situer(ligne)
        lignes.append(
            {
                "etape": ETAPE_GESTION,
                "controle": _controle_gestion(ligne.ref, ligne.libelle),
                "table": ligne.table,
                "fichier_source": ligne.fichier_source,
                "feuille_source": ligne.feuille_source,
                "num_ligne_source": ligne.num_ligne_source,
                COLONNE_PERIODE: periode(ligne.table, position),
                "cle": ligne.cle,
                "champ": ligne.colonnes,
                "valeur": ligne.valeur,
                "regle": ligne.type,
                "constat": ligne.constat,
                "issue": ligne.issue,
                "statut_regle": None,
                "detail": None,
                "proposition": ligne.proposition,
            }
        )

    sans_calcul = ("id_anomalie", "gravite", "indicateurs")
    entetes = [c for c in COLONNES_ANOMALIES if c not in sans_calcul]
    anomalies = pd.DataFrame(lignes, columns=entetes)
    inconnus = sorted(
        {
            f"{etape} : {controle}"
            for etape, controle in zip(anomalies["etape"], anomalies["controle"])
            if (etape, controle) not in rangs
        }
    )
    if inconnus:
        raise ValueError(
            "Écarts dont le contrôle est absent de son bilan\n  " + "\n  ".join(inconnus)
        )

    anomalies["num_ligne_source"] = pd.array(
        [_numero(n) for n in anomalies["num_ligne_source"]], dtype="Int64"
    )
    sans_ligne = anomalies["num_ligne_source"].isna()
    anomalies["id_anomalie"] = [
        _empreinte(
            ligne.etape,
            ligne.controle,
            ligne.table,
            ligne.fichier_source,
            ligne.feuille_source,
            ligne.num_ligne_source,
            ligne.champ,
            ligne.constat,
            ligne.cle if vide else "",
        )
        for ligne, vide in zip(anomalies.itertuples(index=False), sans_ligne)
    ]
    doubles = anomalies[anomalies["id_anomalie"].duplicated(keep=False)]
    if not doubles.empty:
        exemples = [
            f"{ligne.controle}, {_texte(ligne.fichier_source)} ligne "
            f"{_texte(ligne.num_ligne_source)}, {ligne.constat}"
            for ligne in doubles.head(5).itertuples(index=False)
        ]
        raise ValueError(
            f"{len(doubles)} lignes partagent leur identifiant (lignage absent ou en "
            "double, ou deux règles de même référence et de même libellé)\n  "
            + "\n  ".join(exemples)
        )
    anomalies["gravite"] = None
    anomalies["indicateurs"] = None
    anomalies["_rang"] = [
        rangs[(etape, controle)]
        for etape, controle in zip(anomalies["etape"], anomalies["controle"])
    ]
    anomalies = anomalies.sort_values("_rang", kind="stable")
    return anomalies[list(COLONNES_ANOMALIES)].reset_index(drop=True)


def _lignes_bilan(bilan, bilan_doublons, bilan_gestion, declarations) -> list[dict]:
    """Lignes du bilan par contrôle, sans les décomptes tirés des anomalies."""
    lignes = []
    for ligne in bilan.itertuples(index=False):
        lignes.append(
            {
                "etape": ETAPE_FORMAT,
                "controle": _controle_format(ligne.table, ligne.colonne, ligne.regle),
                "table": ligne.table,
                "champ": ligne.colonne,
                "regle": _regle_format(ligne.regle, ligne.regle_en_vigueur),
                "controlees": ligne.controlees,
            }
        )
    for ligne in bilan_doublons.itertuples(index=False):
        lignes.append(
            {
                "etape": ETAPE_DOUBLONS,
                "controle": _controle_doublons(ligne.table, ligne.constat, ligne.colonnes),
                "table": ligne.table,
                "champ": ligne.colonnes,
                "regle": _regle_doublon(
                    ligne.table, ligne.constat, ligne.colonnes, ligne.issue, declarations
                ),
                "controlees": ligne.comparees,
            }
        )
    for ligne in bilan_gestion.itertuples(index=False):
        lignes.append(
            {
                "etape": ETAPE_GESTION,
                "controle": _controle_gestion(ligne.ref, ligne.libelle),
                "table": ligne.table,
                "champ": ligne.colonnes,
                "regle": ligne.type,
                "controlees": ligne.controlees,
            }
        )
    return lignes


def _rangs_controles(bilan, bilan_doublons, bilan_gestion) -> dict[tuple, int]:
    """Rang de chaque contrôle dans l'ordre des bilans; un nom en double arrête."""
    noms = (
        [(ETAPE_FORMAT, _controle_format(t, c, r))
         for t, c, r in zip(bilan["table"], bilan["colonne"], bilan["regle"])]
        + [(ETAPE_DOUBLONS, _controle_doublons(t, c, k))
           for t, c, k in zip(bilan_doublons["table"], bilan_doublons["constat"],
                              bilan_doublons["colonnes"])]
        + [(ETAPE_GESTION, _controle_gestion(r, l))
           for r, l in zip(bilan_gestion["ref"], bilan_gestion["libelle"])]
    )
    doubles = sorted({f"{e} : {n}" for e, n in noms if noms.count((e, n)) > 1})
    if doubles:
        raise ValueError(
            "Contrôles de même nom (pour la gestion, donner un libellé différent à "
            "chaque règle d'une même référence)\n  " + "\n  ".join(doubles)
        )
    return {nom: rang for rang, nom in enumerate(noms)}


def bilan_controles(
    bilan: pd.DataFrame,
    bilan_doublons: pd.DataFrame,
    bilan_gestion: pd.DataFrame,
    anomalies: pd.DataFrame,
    declarations: dict | None = None,
) -> pd.DataFrame:
    """Bilan par contrôle des trois étapes, dans l'ordre de leurs bilans.

    `controlees` vient du bilan de chaque source (cellules pour le format, lignes
    comparées pour les doublons, lignes contrôlées pour la gestion). Les nombres
    d'anomalies, d'écarts à arbitrer et d'informations sont comptés dans la table
    des anomalies (`reunir_anomalies`); `lignes_distinctes` est le nombre de lignes
    sources qui portent au moins une anomalie pour ce contrôle. `taux` est le
    rapport des anomalies aux lignes contrôlées; il est vide quand rien n'est
    contrôlé, ou quand un écart du contrôle n'a pas de lignage (un total par
    période se compte en périodes, ses lignes contrôlées en lignes). `gravite` et
    `indicateurs` sont vides (voir `qualifier`).
    """
    if declarations is None:
        declarations = charger_declarations_doublons()
    _rangs_controles(bilan, bilan_doublons, bilan_gestion)
    lignes = _lignes_bilan(bilan, bilan_doublons, bilan_gestion, declarations)
    entetes = ["etape", "controle", "table", "champ", "regle", "controlees"]
    resultat = pd.DataFrame(lignes, columns=entetes)
    issues = anomalies.assign(
        _anomalie=anomalies["issue"] == ISSUE_ANOMALIE,
        _arbitrer=anomalies["issue"] == ISSUE_A_ARBITRER,
        _information=anomalies["issue"] == ISSUE_INFORMATION,
        _sans_ligne=anomalies["num_ligne_source"].map(_texte) == "",
    ).groupby(["etape", "controle"], sort=False)
    comptes = pd.DataFrame(
        {
            "anomalies": issues["_anomalie"].sum(),
            "a_arbitrer": issues["_arbitrer"].sum(),
            "informations": issues["_information"].sum(),
            "_sans_ligne": issues["_sans_ligne"].any(),
        }
    )
    en_anomalie = anomalies[
        (anomalies["issue"] == ISSUE_ANOMALIE) & (anomalies["num_ligne_source"].map(_texte) != "")
    ]
    distinctes = (
        en_anomalie.assign(
            _repere=[
                _repere(f, s, n)
                for f, s, n in zip(
                    en_anomalie["fichier_source"],
                    en_anomalie["feuille_source"],
                    en_anomalie["num_ligne_source"],
                )
            ]
        )
        .groupby(["etape", "controle"], sort=False)["_repere"]
        .nunique()
    )
    cles = list(zip(resultat["etape"], resultat["controle"]))
    for colonne in ("anomalies", "a_arbitrer", "informations"):
        resultat[colonne] = [int(comptes[colonne].get(c, 0)) for c in cles]
    resultat["lignes_distinctes"] = [int(distinctes.get(c, 0)) for c in cles]
    sans_ligne = [bool(comptes["_sans_ligne"].get(c, False)) for c in cles]
    resultat["taux"] = pd.Series([
        None if vide or not controlees else anomalies_controle / controlees
        for vide, controlees, anomalies_controle in zip(
            sans_ligne, resultat["controlees"], resultat["anomalies"]
        )
    ], dtype=object)
    resultat["controlees"] = resultat["controlees"].astype(int)
    resultat["gravite"] = None
    resultat["indicateurs"] = None
    return resultat[list(COLONNES_BILAN_ANOMALIES)]


def _colonnes_du_champ(table: str, champ) -> list[tuple[str, str]]:
    """Colonnes citées par un champ (« a, t.b »), avec leur table."""
    texte = _texte(champ)
    if not texte or texte == TOUTES_COLONNES or texte.startswith(TOUTES_COLONNES + " "):
        return []
    colonnes = []
    for morceau in texte.split(", "):
        if "." in morceau:
            autre, colonne = morceau.split(".", 1)
            colonnes.append((autre, colonne))
        else:
            colonnes.append((table, morceau))
    return colonnes


def anomalies_non_masquees(
    anomalies: pd.DataFrame,
    sensibles: dict[str, frozenset[str]] | None = None,
    declarations: dict | None = None,
) -> pd.DataFrame:
    """Lignes dont la valeur ou la clé vient d'une colonne sensible sans être masquée.

    La valeur est jugée d'après les colonnes du champ, la clé d'après la clé
    déclarée de la table. Une table vide est attendue.
    """
    if sensibles is None:
        sensibles = charger_sensibilite()
    if declarations is None:
        declarations = charger_declarations_doublons()

    def visible(texte) -> bool:
        return _texte(texte) not in ("", VALEUR_MASQUEE)

    fautives = []
    for position, ligne in enumerate(anomalies.itertuples(index=False)):
        valeur_sensible = any(
            est_sensible(sensibles, t, c) for t, c in _colonnes_du_champ(ligne.table, ligne.champ)
        )
        cle = declarations.get(ligne.table, {}).get("cle", [])
        cle_sensible = any(est_sensible(sensibles, ligne.table, c) for c in cle)
        if (valeur_sensible and (visible(ligne.valeur) or visible(ligne.proposition))) or (
            cle_sensible and visible(ligne.cle)
        ):
            fautives.append(position)
    return anomalies.iloc[fautives]


# Gravité et indicateurs affectés (étape 5c), déclarés dans config/anomalies.yaml.
CLE_INDICATEURS = "indicateurs"
CLE_COLONNES = "colonnes"
CLE_EXCEPTIONS = "exceptions"
CLES_FICHIER_QUALIFICATION = (CLE_INDICATEURS, CLE_COLONNES, CLE_EXCEPTIONS)
CLE_DEPEND_DE = "depend_de"
CLES_INDICATEUR = (CLE_DEPEND_DE,)
CLES_EXCEPTION = ("controle", "motif", "etape", "gravite", "indicateurs")
GRAVITE_BLOQUANTE = "bloquante"
GRAVITE_MAJEURE = "majeure"
GRAVITE_MINEURE = "mineure"
GRAVITES = (GRAVITE_BLOQUANTE, GRAVITE_MAJEURE, GRAVITE_MINEURE)
SEPARATEUR_INDICATEURS = ", "
COLONNES_NON_QUALIFIES = ("etape", "controle", "table", "champ", "colonnes_non_declarees")
COLONNES_NON_DECLAREES = ("table", "colonne")


def chemin_qualification() -> Path:
    """Emplacement par défaut de la gravité et des indicateurs : config/anomalies.yaml."""
    return racine_projet() / "config" / "anomalies.yaml"


def charger_qualification(chemin: str | Path | None = None) -> dict:
    """Gravité et indicateurs affectés, lus dans config/anomalies.yaml.

    Le fichier est écrit à la main, d'après ce que dit le métier, sous trois clés
    facultatives :

        indicateurs:
          CA: {}
          coût salarial: {}
          marge: {depend_de: [CA, coût salarial]}
        colonnes:
          interventions:
            duree_min: [coût salarial]
            commentaire: []
        exceptions:
          - motif: '.* encodage'
            gravite: mineure
          - controle: R06 Écriture équilibrée
            gravite: bloquante

    `indicateurs` est le catalogue des indicateurs, dans l'ordre d'affichage; un
    indicateur peut dépendre d'autres indicateurs (`depend_de`), qu'une anomalie
    affecte alors avec eux. `colonnes` donne, par table puis par colonne, les
    indicateurs qu'alimente la colonne (`[]` pour aucun, ce qui est une déclaration
    et non un oubli). `exceptions` ajuste les contrôles que désigne leur nom exact
    (`controle`) ou une expression régulière sur ce nom (`motif`), éventuellement
    restreints à une étape (`etape`) : une `gravite`, des `indicateurs` qui
    remplacent ceux des colonnes, ou les deux.

    Un fichier absent ou vide ne déclare rien (tous les contrôles seront non
    qualifiés). Un fichier mal formé est refusé, tous les problèmes étant listés en
    une fois; la présence des tables et des colonnes dans les données est vérifiée
    par `qualifier`.
    """
    chemin = Path(chemin) if chemin is not None else chemin_qualification()
    if not chemin.is_file():
        return {}
    with open(chemin, encoding="utf-8") as flux:
        contenu = yaml.safe_load(flux)
    if contenu is None:
        return {}
    attendues = ", ".join(f"« {cle} »" for cle in CLES_FICHIER_QUALIFICATION)
    if not isinstance(contenu, dict):
        raise ValueError(
            f"Fichier de gravité et d'indicateurs invalide ({chemin}) : les seules clés "
            f"attendues sont {attendues}"
        )
    problemes = problemes_qualification(contenu)
    if problemes:
        raise ValueError(
            f"Fichier de gravité et d'indicateurs invalide ({chemin})\n  "
            + "\n  ".join(problemes)
        )
    return contenu


def _bloc(qualification: dict, cle: str, vide):
    """Contenu d'une clé du fichier, `vide` si elle manque ou n'a pas de valeur."""
    valeur = qualification.get(cle)
    return vide if valeur is None else valeur


def _nom_attendu(valeur) -> bool:
    return isinstance(valeur, str) and valeur.strip() != ""


def _problemes_liste_indicateurs(valeur, catalogue, ou: str) -> list[str]:
    """Problèmes d'une liste d'indicateurs (liste de noms du catalogue, sans répétition)."""
    if not isinstance(valeur, list):
        return [f"{ou} : une liste d'indicateurs est attendue ([] pour aucun)"]
    problemes = []
    for nom in valeur:
        if not _nom_attendu(nom):
            problemes.append(f"{ou} : nom d'indicateur attendu ({nom!r})")
        elif nom not in catalogue:
            problemes.append(f"{ou} : indicateur inconnu {nom} (absent du catalogue)")
    noms = [n for n in valeur if isinstance(n, str)]
    repetes = sorted({n for n in noms if noms.count(n) > 1})
    if repetes:
        problemes.append(f"{ou} : indicateur répété {', '.join(repetes)}")
    return problemes


def _cycles(dependances: dict[str, list[str]]) -> list[str]:
    """Indicateurs pris dans une dépendance circulaire."""
    en_cycle = []
    for depart in dependances:
        a_voir = list(dependances.get(depart, []))
        vus = set()
        while a_voir:
            nom = a_voir.pop()
            if nom == depart:
                en_cycle.append(depart)
                break
            if nom in vus:
                continue
            vus.add(nom)
            a_voir.extend(dependances.get(nom, []))
    return en_cycle


def problemes_qualification(qualification, tables: dict | None = None) -> list[str]:
    """Problèmes du contenu de config/anomalies.yaml, tous listés.

    Avec `tables`, vérifie aussi que chaque table et chaque colonne déclarée existe
    dans les données (une colonne de lignage n'est pas une colonne de données).
    """
    if not isinstance(qualification, dict):
        return ["un dictionnaire est attendu, de clés " + ", ".join(CLES_FICHIER_QUALIFICATION)]
    problemes = []
    inconnues = [str(cle) for cle in qualification if cle not in CLES_FICHIER_QUALIFICATION]
    if inconnues:
        problemes.append(
            f"clé inconnue {', '.join(inconnues)} (clés attendues "
            f"{', '.join(CLES_FICHIER_QUALIFICATION)})"
        )

    catalogue = _bloc(qualification, CLE_INDICATEURS, {})
    dependances = {}
    if not isinstance(catalogue, dict):
        problemes.append(f"{CLE_INDICATEURS} : un dictionnaire nom d'indicateur vers "
                         "ses précisions est attendu")
        catalogue = {}
    for nom, precisions in catalogue.items():
        ou = f"{CLE_INDICATEURS}, {nom}"
        if not _nom_attendu(nom):
            problemes.append(f"{CLE_INDICATEURS} : nom d'indicateur attendu ({nom!r})")
            continue
        if precisions is None:
            continue
        if not isinstance(precisions, dict):
            problemes.append(f"{ou} : un dictionnaire est attendu ({{}} sans précision)")
            continue
        inconnues = [str(c) for c in precisions if c not in CLES_INDICATEUR]
        if inconnues:
            problemes.append(
                f"{ou} : clé inconnue {', '.join(inconnues)} (clé possible {CLE_DEPEND_DE})"
            )
        if CLE_DEPEND_DE in precisions:
            liste = precisions[CLE_DEPEND_DE]
            problemes += _problemes_liste_indicateurs(liste, catalogue, f"{ou}, {CLE_DEPEND_DE}")
            if isinstance(liste, list):
                dependances[nom] = [n for n in liste if isinstance(n, str) and n in catalogue]
    cycles = _cycles(dependances)
    if cycles:
        problemes.append(f"{CLE_INDICATEURS} : dépendance circulaire ({', '.join(cycles)})")

    colonnes = _bloc(qualification, CLE_COLONNES, {})
    if not isinstance(colonnes, dict):
        problemes.append(f"{CLE_COLONNES} : un dictionnaire table vers colonnes est attendu")
        colonnes = {}
    for table, par_colonne in colonnes.items():
        if not isinstance(par_colonne, dict):
            problemes.append(
                f"{CLE_COLONNES}, {table} : un dictionnaire colonne vers indicateurs est attendu"
            )
            continue
        if tables is not None and table not in tables:
            problemes.append(f"{CLE_COLONNES} : table {table} absente des données chargées")
        presentes = (
            _colonnes_de_donnees(tables[table])
            if tables is not None and table in tables
            else None
        )
        for colonne, indicateurs in par_colonne.items():
            ou = f"{CLE_COLONNES}, {table}.{colonne}"
            problemes += _problemes_liste_indicateurs(indicateurs, catalogue, ou)
            if presentes is not None and colonne not in presentes:
                problemes.append(
                    f"{CLE_COLONNES} : colonne {table}.{colonne} absente des données chargées"
                )

    exceptions = _bloc(qualification, CLE_EXCEPTIONS, [])
    if not isinstance(exceptions, list):
        problemes.append(f"{CLE_EXCEPTIONS} : une liste est attendue")
        exceptions = []
    for rang, exception in enumerate(exceptions, start=1):
        ou = f"{CLE_EXCEPTIONS}, exception n° {rang}"
        if not isinstance(exception, dict):
            problemes.append(f"{ou} : un dictionnaire est attendu")
            continue
        inconnues = [str(c) for c in exception if c not in CLES_EXCEPTION]
        if inconnues:
            problemes.append(
                f"{ou} : clé inconnue {', '.join(inconnues)} (clés possibles "
                f"{', '.join(CLES_EXCEPTION)})"
            )
        designations = [c for c in ("controle", "motif") if c in exception]
        if len(designations) != 1:
            problemes.append(f"{ou} : une clé controle ou une clé motif est attendue, pas les deux")
        if "controle" in exception and not _nom_attendu(exception["controle"]):
            problemes.append(f"{ou} : nom de contrôle attendu")
        if "motif" in exception:
            motif = exception["motif"]
            if not _nom_attendu(motif):
                problemes.append(f"{ou} : expression régulière attendue")
            else:
                try:
                    re.compile(motif)
                except re.error as erreur:
                    problemes.append(f"{ou} : expression régulière invalide ({erreur})")
        if "etape" in exception and exception["etape"] not in ETAPES:
            problemes.append(
                f"{ou} : étape inconnue {exception['etape']!r} (étapes possibles "
                f"{', '.join(ETAPES)})"
            )
        if "gravite" not in exception and "indicateurs" not in exception:
            problemes.append(f"{ou} : une gravite ou des indicateurs sont attendus")
        if "gravite" in exception and exception["gravite"] not in GRAVITES:
            problemes.append(
                f"{ou} : gravité inconnue {exception['gravite']!r} (gravités possibles "
                f"{', '.join(GRAVITES)})"
            )
        if "indicateurs" in exception:
            problemes += _problemes_liste_indicateurs(exception["indicateurs"], catalogue, ou)
    return problemes


def _designe(exception: dict, etape: str, controle: str) -> bool:
    """Vrai si l'exception désigne ce contrôle."""
    if "etape" in exception and exception["etape"] != etape:
        return False
    if "controle" in exception:
        return exception["controle"] == controle
    return re.fullmatch(exception["motif"], controle) is not None


def _affectes(base, catalogue: dict) -> list[str]:
    """Indicateurs affectés : ceux de la base et ceux qui en dépendent, dans l'ordre
    du catalogue."""
    affectes = set(base)
    change = True
    while change:
        change = False
        for nom, precisions in catalogue.items():
            depend = (precisions or {}).get(CLE_DEPEND_DE) or []
            if nom not in affectes and any(d in affectes for d in depend):
                affectes.add(nom)
                change = True
    return [nom for nom in catalogue if nom in affectes]


def _colonnes_du_controle(etape, table, champ, tables) -> list[tuple[str, str]] | None:
    """Colonnes dont un contrôle tire ses indicateurs.

    Un doublon compte deux fois dans tous les agrégats de sa table : un contrôle de
    doublons a les colonnes de toute sa table (None si la table est absente des
    données). Les autres contrôles ont les colonnes de leur champ.
    """
    if etape == ETAPE_DOUBLONS:
        if table not in tables:
            return None
        return [(table, colonne) for colonne in _colonnes_de_donnees(tables[table])]
    return _colonnes_du_champ(table, champ)


def qualifier(
    anomalies: pd.DataFrame,
    bilan: pd.DataFrame,
    qualification: dict,
    tables: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Renseigne la gravité et les indicateurs affectés de chaque contrôle.

    `anomalies` vient de `reunir_anomalies`, `bilan` de `bilan_controles`,
    `qualification` de `charger_qualification`. Rend `(anomalies, bilan,
    non_qualifies)`, les arguments n'étant pas modifiés.

    Les indicateurs d'un contrôle sont ceux des colonnes de son champ (« t.c » pour
    une colonne d'une table liée), ou de toutes les colonnes de sa table pour un
    contrôle de doublons, complétés des indicateurs qui en dépendent, dans l'ordre
    du catalogue et reliés par « , ». Une exception qui donne des indicateurs les
    remplace. La gravité est celle d'une exception, sinon « majeure » si le contrôle
    affecte au moins un indicateur, « mineure » sinon.

    Un contrôle est qualifié si une exception lui donne ses indicateurs ou si toutes
    ses colonnes sont déclarées; sinon sa gravité et ses indicateurs restent vides,
    et il figure dans `non_qualifies` (`COLONNES_NON_QUALIFIES`) avec ses colonnes
    non déclarées. Dans la table des anomalies, chaque ligne reçoit la gravité et
    les indicateurs de son contrôle, sauf les informations, qui ne sont pas des
    anomalies (gravité et indicateurs vides).

    Refuse (`ValueError`, tous les problèmes listés) : un fichier mal formé, une
    table ou une colonne déclarée absente des données, deux exceptions qui donnent
    à un même contrôle des gravités ou des indicateurs différents, une ligne de la
    table des anomalies dont le contrôle est absent du bilan.
    """
    problemes = (
        _verifier_colonnes("table des anomalies", anomalies, COLONNES_ANOMALIES)
        + _verifier_colonnes("bilan par contrôle", bilan, COLONNES_BILAN_ANOMALIES)
    )
    if problemes:
        raise ValueError("Tables inattendues\n  " + "\n  ".join(problemes))
    problemes = problemes_qualification(qualification, tables)
    if problemes:
        raise ValueError(
            "Fichier de gravité et d'indicateurs invalide\n  " + "\n  ".join(problemes)
        )
    catalogue = _bloc(qualification, CLE_INDICATEURS, {})
    declarees = _bloc(qualification, CLE_COLONNES, {})
    exceptions = _bloc(qualification, CLE_EXCEPTIONS, [])

    resultats = {}
    non_qualifies = []
    conflits = []
    for ligne in bilan.itertuples(index=False):
        designantes = [e for e in exceptions if _designe(e, ligne.etape, ligne.controle)]
        gravites = {e["gravite"] for e in designantes if "gravite" in e}
        listes = {
            tuple(_affectes(e["indicateurs"], catalogue))
            for e in designantes
            if "indicateurs" in e
        }
        if len(gravites) > 1:
            conflits.append(
                f"{ligne.etape} : {ligne.controle}, gravités différentes "
                f"({', '.join(sorted(gravites))})"
            )
        if len(listes) > 1:
            textes = [SEPARATEUR_INDICATEURS.join(liste) or "aucun" for liste in sorted(listes)]
            conflits.append(
                f"{ligne.etape} : {ligne.controle}, indicateurs différents "
                f"({'; '.join(textes)})"
            )
        if listes:
            indicateurs = list(next(iter(listes)))
        else:
            colonnes = _colonnes_du_controle(ligne.etape, ligne.table, ligne.champ, tables)
            if colonnes is None:
                manquantes = [f"table {ligne.table} absente des données"]
            else:
                manquantes = [
                    f"{t}.{c}" for t, c in colonnes if c not in (declarees.get(t) or {})
                ]
            if manquantes:
                non_qualifies.append(
                    {
                        "etape": ligne.etape,
                        "controle": ligne.controle,
                        "table": ligne.table,
                        "champ": ligne.champ,
                        "colonnes_non_declarees": SEPARATEUR_INDICATEURS.join(manquantes),
                    }
                )
                resultats[(ligne.etape, ligne.controle)] = (None, None)
                continue
            base = [nom for t, c in colonnes for nom in declarees[t][c]]
            indicateurs = _affectes(base, catalogue)
        if gravites:
            gravite = next(iter(gravites))
        else:
            gravite = GRAVITE_MAJEURE if indicateurs else GRAVITE_MINEURE
        texte = SEPARATEUR_INDICATEURS.join(indicateurs) or None
        resultats[(ligne.etape, ligne.controle)] = (gravite, texte)
    if conflits:
        raise ValueError(
            "Exceptions contradictoires sur un même contrôle\n  " + "\n  ".join(conflits)
        )

    inconnus = sorted(
        {
            f"{etape} : {controle}"
            for etape, controle in zip(anomalies["etape"], anomalies["controle"])
            if (etape, controle) not in resultats
        }
    )
    if inconnus:
        raise ValueError(
            "Lignes de la table des anomalies dont le contrôle est absent du bilan\n  "
            + "\n  ".join(inconnus)
        )

    bilan = bilan.copy()
    cles = list(zip(bilan["etape"], bilan["controle"]))
    bilan["gravite"] = pd.Series([resultats[c][0] for c in cles], index=bilan.index, dtype=object)
    bilan["indicateurs"] = pd.Series(
        [resultats[c][1] for c in cles], index=bilan.index, dtype=object
    )
    anomalies = anomalies.copy()
    valeurs = [
        (None, None) if issue == ISSUE_INFORMATION else resultats[(etape, controle)]
        for etape, controle, issue in zip(
            anomalies["etape"], anomalies["controle"], anomalies["issue"]
        )
    ]
    anomalies["gravite"] = pd.Series([v[0] for v in valeurs], index=anomalies.index, dtype=object)
    anomalies["indicateurs"] = pd.Series(
        [v[1] for v in valeurs], index=anomalies.index, dtype=object
    )
    return anomalies, bilan, pd.DataFrame(non_qualifies, columns=list(COLONNES_NON_QUALIFIES))


def colonnes_non_declarees(tables: dict[str, pd.DataFrame], qualification: dict) -> pd.DataFrame:
    """Colonnes des données absentes du bloc `colonnes` (`COLONNES_NON_DECLAREES`).

    Dans l'ordre des tables et de leurs colonnes, sans les colonnes de lignage :
    c'est la liste à compléter pour qualifier tous les contrôles.
    """
    declarees = _bloc(qualification, CLE_COLONNES, {})
    if not isinstance(declarees, dict):
        declarees = {}
    lignes = [
        {"table": table, "colonne": colonne}
        for table, donnees in tables.items()
        for colonne in _colonnes_de_donnees(donnees)
        if not isinstance(declarees.get(table), dict) or colonne not in declarees[table]
    ]
    return pd.DataFrame(lignes, columns=list(COLONNES_NON_DECLAREES))


def avertissements_qualification(bilan: pd.DataFrame, qualification: dict) -> list[str]:
    """Déclarations sans effet : exception qui ne désigne aucun contrôle du bilan,
    indicateur du catalogue qu'aucune colonne ni aucune exception n'affecte.

    Ce ne sont pas des erreurs (certains contrôles n'existent que selon les données),
    mais elles peuvent cacher une faute de frappe.
    """
    catalogue = _bloc(qualification, CLE_INDICATEURS, {})
    declarees = _bloc(qualification, CLE_COLONNES, {})
    exceptions = _bloc(qualification, CLE_EXCEPTIONS, [])
    messages = []
    controles = list(zip(bilan["etape"], bilan["controle"]))
    for rang, exception in enumerate(exceptions, start=1):
        if not any(_designe(exception, etape, controle) for etape, controle in controles):
            designation = exception.get("controle", exception.get("motif"))
            messages.append(f"exception n° {rang} ({designation}) : aucun contrôle désigné")
    utilises = set()
    for par_colonne in declarees.values():
        for indicateurs in (par_colonne or {}).values():
            utilises.update(indicateurs or [])
    for exception in exceptions:
        utilises.update(exception.get("indicateurs") or [])
    utilises = set(_affectes(utilises, catalogue))
    for nom in catalogue:
        if nom not in utilises:
            messages.append(f"indicateur {nom} : affecté par aucune colonne ni exception")
    return messages


# Écriture de la table des anomalies et du bilan par contrôle (étape 5d).
SEPARATEUR_CSV = ";"
SEPARATEUR_DECIMAL_CSV = ","
DECIMALES_TAUX = 4
ENCODAGE_CSV = "utf-8-sig"
FIN_DE_LIGNE_CSV = "\r\n"
PREFIXE_FICHIER_ANOMALIES = "anomalies_"
PREFIXE_FICHIER_BILAN = "bilan_"
PREFIXE_FICHIER_ANOMALIES_NETTOYEES = "anomalies_nettoyees_"
PREFIXE_FICHIER_BILAN_NETTOYEES = "bilan_nettoyees_"
SUFFIXE_PROVISOIRE = ".tmp"
_MOTIF_PERIODE_FIN = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
_COLONNES_ENTIERES_BILAN = (
    "controlees",
    "anomalies",
    "a_arbitrer",
    "informations",
    "lignes_distinctes",
)


def dossier_anomalies() -> Path:
    """Emplacement par défaut des fichiers écrits : data/anomalies/, hors du dépôt."""
    return racine_projet() / "data" / "anomalies"


def chemins_anomalies(
    periode_fin: str, dossier: str | Path | None = None, nettoyees: bool = False
) -> tuple[Path, Path]:
    """Chemins de la table des anomalies et du bilan d'une période (AAAA-MM).

    Avec `nettoyees=True`, ceux de la table des anomalies des tables nettoyées
    (étape 6) : `anomalies_nettoyees_AAAA-MM.csv` et `bilan_nettoyees_AAAA-MM.csv`.
    """
    dossier = dossier_anomalies() if dossier is None else Path(dossier)
    if nettoyees:
        prefixes = (PREFIXE_FICHIER_ANOMALIES_NETTOYEES, PREFIXE_FICHIER_BILAN_NETTOYEES)
    else:
        prefixes = (PREFIXE_FICHIER_ANOMALIES, PREFIXE_FICHIER_BILAN)
    return tuple(dossier / f"{prefixe}{periode_fin}.csv" for prefixe in prefixes)


def _problemes_ecriture(
    anomalies, bilan, periode_fin, sensibles, declarations, nettoyees=False
) -> list[str]:
    """Tous les problèmes qui empêchent d'écrire la table et le bilan."""
    if not isinstance(periode_fin, str) or not _MOTIF_PERIODE_FIN.fullmatch(periode_fin):
        return [f"période {periode_fin!r} : forme AAAA-MM attendue (par exemple 2026-03)"]
    problemes = []
    for nom, donnees, attendues in (
        (
            "table des anomalies",
            anomalies,
            COLONNES_ANOMALIES_NETTOYEES if nettoyees else COLONNES_ANOMALIES,
        ),
        ("bilan par contrôle", bilan, COLONNES_BILAN_ANOMALIES),
    ):
        if list(donnees.columns) != list(attendues):
            problemes.append(
                f"{nom} : colonnes attendues, dans cet ordre, {', '.join(attendues)}"
            )
    if problemes:
        return problemes

    identifiants = anomalies["id_anomalie"].map(_texte)
    vides = int((identifiants == "").sum())
    if vides:
        problemes.append(f"{vides} lignes sans identifiant (id_anomalie)")
    repetes = sorted(set(identifiants[identifiants.duplicated() & (identifiants != "")]))
    if repetes:
        problemes.append(
            f"{len(repetes)} identifiants en double ({', '.join(repetes[:5])}"
            + (", ..." if len(repetes) > 5 else "")
            + ")"
        )

    au_bilan = {
        (etape, controle): (_texte(gravite), _texte(indicateurs))
        for etape, controle, gravite, indicateurs in zip(
            bilan["etape"], bilan["controle"], bilan["gravite"], bilan["indicateurs"]
        )
    }
    absents = set()
    discordants = set()
    for etape, controle, issue, gravite, indicateurs in zip(
        anomalies["etape"],
        anomalies["controle"],
        anomalies["issue"],
        anomalies["gravite"],
        anomalies["indicateurs"],
    ):
        if (etape, controle) not in au_bilan:
            absents.add(f"{etape} : {controle}")
        elif issue != ISSUE_INFORMATION and au_bilan[(etape, controle)] != (
            _texte(gravite),
            _texte(indicateurs),
        ):
            discordants.add(f"{etape} : {controle}")
    if absents:
        problemes.append(
            "contrôles de la table des anomalies absents du bilan : " + ", ".join(sorted(absents))
        )

    a_qualifier = bool((anomalies["issue"] != ISSUE_INFORMATION).any())
    if a_qualifier and (bilan["gravite"].map(_texte) == "").all():
        problemes.append(
            "aucune gravité au bilan : appeler qualifier (cellule GRAVITE ET INDICATEURS) "
            "avant l'écriture"
        )
    elif discordants:
        problemes.append(
            "gravité ou indicateurs différents entre la table des anomalies et le bilan "
            "(les deux doivent venir du même appel à qualifier) : "
            + ", ".join(sorted(discordants))
        )

    fautives = anomalies_non_masquees(anomalies, sensibles, declarations)
    if not fautives.empty:
        controles = sorted(set(fautives["controle"]))
        problemes.append(
            f"{len(fautives)} lignes dont la valeur ou la clé d'une colonne sensible n'est "
            f"pas masquée (contrôles : {', '.join(controles)})"
        )
    return problemes


def _table_ecrite(anomalies: pd.DataFrame) -> pd.DataFrame:
    """Table des anomalies telle qu'écrite : numéro de ligne entier, sans `2.0`."""
    sortie = anomalies.copy()
    sortie["num_ligne_source"] = pd.array(
        [_numero(v) for v in sortie["num_ligne_source"]], dtype="Int64"
    )
    return sortie


def _bilan_ecrit(bilan: pd.DataFrame) -> pd.DataFrame:
    """Bilan tel qu'écrit : décomptes entiers, taux à 4 décimales et virgule décimale."""
    sortie = bilan.copy()
    for colonne in _COLONNES_ENTIERES_BILAN:
        sortie[colonne] = pd.array([_numero(v) for v in sortie[colonne]], dtype="Int64")

    def taux(valeur):
        if valeur is None or pd.isna(valeur):
            return None
        texte = f"{float(valeur):.{DECIMALES_TAUX}f}"
        return texte.replace(".", SEPARATEUR_DECIMAL_CSV)

    sortie["taux"] = pd.Series([taux(v) for v in sortie["taux"]], index=sortie.index, dtype=object)
    return sortie


def _ecrire_csv(donnees: pd.DataFrame, chemin: Path) -> None:
    donnees.to_csv(
        chemin,
        sep=SEPARATEUR_CSV,
        index=False,
        encoding=ENCODAGE_CSV,
        lineterminator=FIN_DE_LIGNE_CSV,
        quoting=csv.QUOTE_MINIMAL,
    )
    relu = pd.read_csv(
        chemin,
        sep=SEPARATEUR_CSV,
        encoding=ENCODAGE_CSV,
        dtype=str,
        keep_default_na=False,
    )
    if list(relu.columns) != list(donnees.columns) or len(relu) != len(donnees):
        raise RuntimeError(f"La relecture de {chemin.name} diffère de la table écrite")


def _ecrire_fichiers(sorties: list[tuple[pd.DataFrame, Path]]) -> None:
    """Écrit des tables en CSV, tout ou rien.

    Chaque table est écrite et relue dans un fichier provisoire, puis les fichiers
    provisoires remplacent les anciens. Si l'un des anciens fichiers est ouvert
    (dans Excel), `PermissionError` dit lequel fermer, et les anciens fichiers
    restent intacts.
    """
    chemins = [chemin for _, chemin in sorties]
    provisoires = [c.with_name(c.name + SUFFIXE_PROVISOIRE) for c in chemins]
    chemins[0].parent.mkdir(parents=True, exist_ok=True)
    try:
        for (donnees, _), provisoire in zip(sorties, provisoires):
            _ecrire_csv(donnees, provisoire)
        ouverts = [c for c in chemins if _verrouille(c)]
        if ouverts:
            raise PermissionError(
                "Fichier ouvert, sans doute dans Excel : le fermer, puis relancer l'écriture. "
                "Rien n'a été modifié.\n  " + "\n  ".join(str(c) for c in ouverts)
            )
        for rang, (provisoire, chemin) in enumerate(zip(provisoires, chemins)):
            try:
                os.replace(provisoire, chemin)
            except PermissionError as erreur:
                deja = (
                    f" {chemins[0].name} a déjà été remplacé, {chemin.name} ne l'a pas été : "
                    "relancer l'écriture une fois le fichier fermé."
                    if rang
                    else " Rien n'a été modifié."
                )
                raise PermissionError(
                    f"Fichier ouvert, sans doute dans Excel : {chemin}.{deja}"
                ) from erreur
    finally:
        for provisoire in provisoires:
            provisoire.unlink(missing_ok=True)


def _verrouille(chemin: Path) -> bool:
    """Vrai si un fichier existant ne peut pas être ouvert en écriture (ouvert dans Excel)."""
    if not chemin.exists():
        return False
    try:
        with open(chemin, "r+b"):
            pass
    except PermissionError:
        return True
    return False


def ecrire_anomalies(
    anomalies: pd.DataFrame,
    bilan: pd.DataFrame,
    periode_fin: str,
    dossier: str | Path | None = None,
    sensibles: dict[str, frozenset[str]] | None = None,
    declarations: dict | None = None,
    *,
    nettoyees: bool = False,
) -> tuple[Path, Path]:
    """Écrit la table des anomalies et le bilan par contrôle en CSV.

    `anomalies` et `bilan` viennent de `qualifier`. Les fichiers sont
    `anomalies_AAAA-MM.csv` et `bilan_AAAA-MM.csv`, dans `dossier`
    (par défaut data/anomalies/, créé s'il manque), réécrits à chaque exécution,
    sans copie de sauvegarde (ils se régénèrent à partir des données et de la
    configuration). Rend les deux chemins.

    Format : UTF-8 avec BOM, séparateur « ; », fins de ligne CRLF, valeurs écrites
    telles quelles (entre guillemets si elles contiennent le séparateur, des
    guillemets ou un retour à la ligne), cellule vide pour une valeur absente,
    numéro de ligne entier; au bilan, taux à 4 décimales avec une virgule.

    Refuse (`ValueError`, tous les problèmes listés, sans créer ni toucher aucun
    fichier) : une période qui n'est pas de la forme AAAA-MM, des colonnes autres
    que `COLONNES_ANOMALIES` et `COLONNES_BILAN_ANOMALIES` (dans cet ordre), un
    identifiant vide ou en double, un contrôle absent du bilan, une table qui n'est
    pas passée par `qualifier` (aucune gravité au bilan alors qu'il y a des
    anomalies ou des écarts à arbitrer) ou dont la gravité diffère de celle du
    bilan, une valeur ou une clé d'une colonne sensible non masquée
    (`anomalies_non_masquees`).

    Écriture tout ou rien : les deux fichiers sont écrits et relus en provisoire,
    puis remplacent les anciens. Si l'un des anciens fichiers est ouvert (dans
    Excel), `PermissionError` dit lequel fermer, et les deux anciens fichiers
    restent intacts.

    Avec `nettoyees=True` (étape 6), la table est celle des tables nettoyées, avec
    la colonne `decision_metier` en dernier (`COLONNES_ANOMALIES_NETTOYEES`), et les
    fichiers sont `anomalies_nettoyees_AAAA-MM.csv` et `bilan_nettoyees_AAAA-MM.csv`,
    à côté de ceux des données brutes.
    """
    problemes = _problemes_ecriture(
        anomalies, bilan, periode_fin, sensibles, declarations, nettoyees
    )
    if problemes:
        raise ValueError("Écriture refusée\n  " + "\n  ".join(problemes))

    chemins = chemins_anomalies(periode_fin, dossier, nettoyees)
    _ecrire_fichiers(
        [(_table_ecrite(anomalies), chemins[0]), (_bilan_ecrit(bilan), chemins[1])]
    )
    return chemins
