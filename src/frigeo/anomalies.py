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

La gravité et les indicateurs affectés sont des colonnes vides à ce stade (étape
5c). Rien n'est corrigé ni écrit : l'écriture sur disque relève de l'étape 5d.
"""

from __future__ import annotations

import hashlib

import pandas as pd

from .confidentialite import charger_sensibilite, est_sensible
from .controles import (
    COLONNES_BILAN,
    COLONNES_ECARTS,
    COLONNES_LIGNAGE_ECART,
    ISSUE_A_ARBITRER,
    ISSUE_ANOMALIE,
    VALEUR_MASQUEE,
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
    dont la clé porte la période). `gravite` et `indicateurs` sont vides.

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
    `indicateurs` sont vides.
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
