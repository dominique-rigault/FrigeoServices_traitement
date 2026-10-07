"""Génération du dictionnaire des données à partir des données observées.

Ce module ne contient rien de propre à un client. Tout ce qui est généré a le
statut « observé »; seul le métier peut le faire passer à « validé ».
"""

from __future__ import annotations

import numbers
import os
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from . import racine_projet
from .confidentialite import charger_sensibilite, est_sensible, verifier_sensibilite
from .profilage import COLONNES_LIGNAGE, profiler_colonne

# Seuils par défaut du critère de liste fermée (validés le 05/10/2026, à
# confirmer sur le profil réel).
MAX_VALEURS = 12
PART_MIN = 0.005
COUVERTURE_MIN = 0.95
EFFECTIF_MIN = 200


def _valeurs_renseignees(serie: pd.Series) -> pd.Series:
    """Valeurs présentes, hors None, NaN, chaîne vide et chaîne d'espaces."""
    est_none = serie.isna().astype(bool)
    est_texte_vide = serie.map(
        lambda v: isinstance(v, str) and v.strip() == ""
    ).astype(bool)
    return serie[~(est_none | est_texte_vide)]


def _refus(motif: str) -> dict:
    return {"liste_fermee": False, "motif": motif, "valeurs": [], "a_arbitrer": []}


def proposer_liste(
    serie: pd.Series,
    table: str | None = None,
    colonne: str | None = None,
    sensibles: dict[str, frozenset[str]] | None = None,
    *,
    max_valeurs: int = MAX_VALEURS,
    part_min: float = PART_MIN,
    couverture_min: float = COUVERTURE_MIN,
    effectif_min: int = EFFECTIF_MIN,
) -> dict:
    """Décide si une colonne est proposée avec une liste de valeurs fermée.

    Conditions, vérifiées dans cet ordre (la première qui échoue donne le motif) :
    colonne non sensible, au moins `effectif_min` valeurs renseignées, nature
    dominante « texte », au plus `max_valeurs` valeurs principales (une valeur est
    principale si elle pèse au moins `part_min` des valeurs renseignées), et
    valeurs principales couvrant au moins `couverture_min` des valeurs renseignées.

    Les valeurs non principales ne sont jamais déclarées valides : elles sont
    rendues dans `a_arbitrer` avec leur effectif. Une colonne sensible n'expose
    aucune valeur. Les valeurs sont comparées telles quelles (« Gisors » et
    « Gisors  » sont deux valeurs), converties en texte.
    """
    if sensibles is not None and est_sensible(sensibles, table, colonne):
        return _refus("colonne sensible")

    presentes = _valeurs_renseignees(serie)
    total = len(presentes)
    if total == 0:
        return _refus("aucune valeur renseignée")
    if total < effectif_min:
        return _refus(
            f"effectif insuffisant ({total} valeurs renseignées, {effectif_min} requises)"
        )

    nature = proposer_nature(serie)["regle"]
    if nature != "texte":
        return _refus(f"nature dominante {nature}")

    comptes = sorted(
        presentes.astype(str).value_counts().items(),
        key=lambda element: (-element[1], element[0]),
    )
    seuil = part_min * total
    principales = [(v, n) for v, n in comptes if n >= seuil]
    autres = [(v, n) for v, n in comptes if n < seuil]

    if len(principales) > max_valeurs:
        return _refus(
            f"{len(principales)} valeurs principales (maximum {max_valeurs})"
        )
    couverture = sum(n for _, n in principales) / total
    if couverture < couverture_min:
        return _refus(
            f"valeurs principales couvrant {100 * couverture:.1f} % des valeurs "
            f"renseignées (minimum {100 * couverture_min:.0f} %)"
        )

    return {
        "liste_fermee": True,
        "motif": (
            f"{len(principales)} valeurs principales couvrant "
            f"{100 * couverture:.1f} % des valeurs renseignées"
        ),
        "valeurs": [v for v, _ in principales],
        "a_arbitrer": [{"valeur": v, "effectif": n} for v, n in autres],
    }

# Seuils du critère obligatoire, facultatif, presque toujours vide (validés le
# 07/10/2026, à confirmer sur le profil réel).
VIDES_MAX_OBLIGATOIRE = 0.02
VIDES_MIN_PRESQUE_VIDE = 0.98


def _regle(regle: str, motif: str, a_arbitrer: dict) -> dict:
    return {"regle": regle, "motif": motif, "a_arbitrer": a_arbitrer}


def proposer_obligatoire(
    serie: pd.Series,
    *,
    vides_max: float = VIDES_MAX_OBLIGATOIRE,
    presque_vide_min: float = VIDES_MIN_PRESQUE_VIDE,
    effectif_min: int = EFFECTIF_MIN,
) -> dict:
    """Propose le caractère obligatoire d'une colonne d'après sa part de vides.

    Les trois formes de vide (None ou NaN, chaîne vide, chaîne d'espaces) sont
    comptées ensemble. Règles rendues, dans cet ordre :
    « toujours vide » (100 % de vides), « obligatoire » si aucune valeur n'est vide,
    « à décider » sous `effectif_min` lignes dès qu'il y a un vide, puis
    « obligatoire » jusqu'à `vides_max` de vides inclus (les vides vont dans
    `a_arbitrer`), « presque toujours vide » à partir de `presque_vide_min` (les
    cellules renseignées vont dans `a_arbitrer`) et « facultatif » entre les deux.
    """
    total = len(serie)
    if total == 0:
        return _regle("à décider", "aucune ligne", {})
    renseignees = len(_valeurs_renseignees(serie))
    vides = total - renseignees
    part = vides / total

    if renseignees == 0:
        return _regle("toujours vide", "100 % de vides", {})
    if vides == 0:
        return _regle("obligatoire", "aucune valeur vide", {"vides": 0})
    if total < effectif_min:
        return _regle(
            "à décider",
            f"effectif insuffisant ({total} lignes, {effectif_min} requises)",
            {"vides": vides},
        )

    motif = f"{100 * part:.2f} % de vides"
    if part <= vides_max:
        return _regle("obligatoire", motif, {"vides": vides})
    if part >= presque_vide_min:
        return _regle(
            "presque toujours vide", motif, {"renseignees": renseignees}
        )
    return _regle("facultatif", motif, {})

def proposer_nature(
    serie: pd.Series,
    profil: dict | None = None,
    *,
    couverture_min: float = COUVERTURE_MIN,
    part_min: float = PART_MIN,
    effectif_min: int = EFFECTIF_MIN,
) -> dict:
    """Propose la nature d'une colonne d'après la nature dominante du profil.

    Règles rendues :
    la nature dominante si elle couvre au moins `couverture_min` des valeurs
    renseignées (les valeurs hors nature vont dans `a_arbitrer`), « à décider » entre
    `part_min` et `couverture_min`, et « texte » si aucune nature spécifique ne couvre
    `part_min` (les valeurs conformes à une nature sont alors des coïncidences).
    Sous `effectif_min` valeurs renseignées, « à décider » dès qu'une valeur est hors
    nature. `profil` évite de recalculer `profiler_colonne`.
    """
    if profil is None:
        profil = profiler_colonne(serie)
    nature = profil["nature_dominante"]
    if nature == "aucune valeur":
        return _regle("à décider", "aucune valeur renseignée", {})

    renseignees = (
        profil["nb_lignes"]
        - profil["nb_none_nan"]
        - profil["nb_chaine_vide"]
        - profil["nb_espaces_seuls"]
    )
    hors = profil["nb_hors_nature"]
    couverture = (renseignees - hors) / renseignees
    if nature != "texte" and couverture < part_min:
        nature, hors, couverture = "texte", 0, 1.0

    if hors == 0:
        return _regle(nature, "toutes les valeurs renseignées sont de cette nature", {"hors_nature": 0})

    detail = {"nature_dominante": nature, "hors_nature": hors}
    if renseignees < effectif_min:
        return _regle(
            "à décider",
            f"effectif insuffisant ({renseignees} valeurs renseignées, {effectif_min} requises)",
            detail,
        )
    if couverture >= couverture_min:
        return _regle(
            nature,
            f"{100 * couverture:.2f} % des valeurs renseignées",
            {"hors_nature": hors},
        )
    return _regle(
        "à décider",
        f"nature dominante {nature} sur {100 * couverture:.1f} % des valeurs "
        f"renseignées (minimum {100 * couverture_min:.0f} %)",
        detail,
    )


STATUT_INITIAL = "observé"


def _regle_observee(regle, motif: str, a_arbitrer) -> dict:
    return {
        "regle": regle,
        "statut": STATUT_INITIAL,
        "motif": motif,
        "a_arbitrer": a_arbitrer,
    }


def generer_colonne(
    serie: pd.Series,
    table: str,
    colonne: str,
    sensibles: dict[str, frozenset[str]],
) -> dict:
    """Règles proposées pour une colonne, toutes au statut « observe ».

    Trois règles sont rendues : `obligatoire`, `nature` et `valeurs`. Chacune porte son
    statut, le motif de la proposition et les écarts à arbitrer. Une colonne sensible
    n'expose aucune valeur : sa règle `valeurs` est « aucune ».
    """
    obligatoire = proposer_obligatoire(serie)
    nature = proposer_nature(serie)
    liste = proposer_liste(serie, table, colonne, sensibles)
    if liste["liste_fermee"]:
        valeurs = _regle_observee(liste["valeurs"], liste["motif"], liste["a_arbitrer"])
    else:
        valeurs = _regle_observee("aucune", liste["motif"], [])
    return {
        "obligatoire": _regle_observee(
            obligatoire["regle"], obligatoire["motif"], obligatoire["a_arbitrer"]
        ),
        "nature": _regle_observee(nature["regle"], nature["motif"], nature["a_arbitrer"]),
        "valeurs": valeurs,
    }


def generer_table(
    donnees: pd.DataFrame,
    nom_table: str,
    sensibles: dict[str, frozenset[str]],
) -> dict:
    """Règles proposées pour chaque colonne de données (colonnes de lignage exclues)."""
    return {
        colonne: generer_colonne(donnees[colonne], nom_table, colonne, sensibles)
        for colonne in donnees.columns
        if colonne not in COLONNES_LIGNAGE
    }


def generer_dictionnaire(
    tables: dict[str, pd.DataFrame],
    sensibles: dict[str, frozenset[str]] | None = None,
) -> dict:
    """Dictionnaire proposé pour l'ensemble des tables chargées.

    La classification de sensibilité (config/sensibilite.yaml par défaut) est toujours
    appliquée et vérifiée avant le calcul, comme dans `profiler_tout` avec masquage.
    """
    if sensibles is None:
        sensibles = charger_sensibilite()
    problemes = verifier_sensibilite(tables, sensibles)
    if problemes:
        raise RuntimeError(
            "Classification de sensibilité incohérente\n  " + "\n  ".join(problemes)
        )
    return {
        nom: generer_table(donnees, nom, sensibles) for nom, donnees in tables.items()
    }

def resumer_dictionnaire(dictionnaire: dict) -> pd.DataFrame:
    """Tableau de synthèse du dictionnaire, une ligne par colonne.

    Pour une colonne avec liste fermée, `nb_valeurs` est le nombre de valeurs proposées
    et `nb_a_arbitrer` le nombre de valeurs à arbitrer. Sans liste, `motif_liste` dit
    pourquoi aucune n'est proposée.
    """
    lignes = []
    for table, colonnes in dictionnaire.items():
        for colonne, regles in colonnes.items():
            valeurs = regles["valeurs"]
            fermee = isinstance(valeurs["regle"], list)
            lignes.append(
                {
                    "table": table,
                    "colonne": colonne,
                    "obligatoire": regles["obligatoire"]["regle"],
                    "nature": regles["nature"]["regle"],
                    "liste_fermee": fermee,
                    "nb_valeurs": len(valeurs["regle"]) if fermee else 0,
                    "nb_a_arbitrer": len(valeurs["a_arbitrer"]),
                    "motif_liste": valeurs["motif"],
                }
            )
    return pd.DataFrame(lignes)



STATUTS = ("observé", "valide", "invalide", "documenté")
REGLES = ("obligatoire", "nature", "valeurs")
CHAMPS_REGLE = ("regle", "statut", "motif", "a_arbitrer")


def chemin_dictionnaire() -> Path:
    """Emplacement par défaut du dictionnaire : data/config/dictionnaire.yaml.

    Le dictionnaire contient des valeurs observées dans les données : il est rangé
    avec elles, hors du dépôt.
    """
    return racine_projet() / "data" / "config" / "dictionnaire.yaml"


def _natif(valeur):
    """Copie de `valeur` en types Python natifs, seuls acceptés par l'écriture YAML."""
    if isinstance(valeur, dict):
        return {cle: _natif(element) for cle, element in valeur.items()}
    if isinstance(valeur, (list, tuple)):
        return [_natif(element) for element in valeur]
    if valeur is None or isinstance(valeur, (str, bool)):
        return valeur
    if isinstance(valeur, numbers.Integral):
        return int(valeur)
    if isinstance(valeur, numbers.Real):
        return float(valeur)
    raise TypeError(f"Type non pris en charge dans le dictionnaire : {type(valeur).__name__}")


def _meta(periode_fin: str) -> dict:
    return {
        "periode_fin": periode_fin,
        "genere_le": date.today().isoformat(),
        "seuils": {
            "max_valeurs": MAX_VALEURS,
            "part_min": PART_MIN,
            "couverture_min": COUVERTURE_MIN,
            "effectif_min": EFFECTIF_MIN,
            "vides_max_obligatoire": VIDES_MAX_OBLIGATOIRE,
            "vides_min_presque_vide": VIDES_MIN_PRESQUE_VIDE,
        },
    }


def _verifier_et_normaliser(contenu) -> list[str]:
    """Liste tous les problèmes de structure et normalise les statuts (NFC)."""
    if not isinstance(contenu, dict) or not isinstance(contenu.get("tables"), dict):
        return ["clé « tables » absente ou mal formée"]
    problemes = []
    for table, colonnes in contenu["tables"].items():
        if not isinstance(colonnes, dict):
            problemes.append(f"{table} : liste de colonnes mal formée")
            continue
        for colonne, regles in colonnes.items():
            ou = f"{table}.{colonne}"
            if not isinstance(regles, dict) or set(regles) != set(REGLES):
                problemes.append(f"{ou} : règles attendues {', '.join(REGLES)}")
                continue
            for nom in REGLES:
                regle = regles[nom]
                if not isinstance(regle, dict) or set(regle) != set(CHAMPS_REGLE):
                    problemes.append(
                        f"{ou}, règle {nom} : champs attendus {', '.join(CHAMPS_REGLE)}"
                    )
                    continue
                statut = regle["statut"]
                if isinstance(statut, str):
                    statut = unicodedata.normalize("NFC", statut)
                if statut not in STATUTS:
                    problemes.append(f"{ou}, règle {nom} : statut inconnu {statut!r}")
                else:
                    regle["statut"] = statut
    return problemes


def charger_dictionnaire(chemin: str | Path | None = None) -> dict:
    """Charge le dictionnaire et rend ses tables, après contrôle de la structure.

    Tous les problèmes sont listés en une fois. Un statut hors de `STATUTS` est rejeté.
    """
    chemin = Path(chemin) if chemin is not None else chemin_dictionnaire()
    with open(chemin, encoding="utf-8") as flux:
        contenu = yaml.safe_load(flux)
    problemes = _verifier_et_normaliser(contenu)
    if problemes:
        raise ValueError(f"Dictionnaire invalide ({chemin})\n  " + "\n  ".join(problemes))
    return contenu["tables"]


def ecrire_dictionnaire(
    dictionnaire: dict,
    periode_fin: str,
    chemin: str | Path | None = None,
    *,
    ecraser: bool = False,
) -> Path:
    """Écrit le dictionnaire en YAML et vérifie l'écriture par une relecture.

    Sans `ecraser=True`, refuse de remplacer un fichier illisible ou qui porte au
    moins un statut autre que « observé » (travail de revue à ne pas perdre). Le
    fichier n'est remplacé qu'une fois la relecture identique au dictionnaire fourni.
    """
    chemin = Path(chemin) if chemin is not None else chemin_dictionnaire()
    tables = _natif(dictionnaire)

    if chemin.exists() and not ecraser:
        revues = sum(
            regle["statut"] != STATUT_INITIAL
            for colonnes in charger_dictionnaire(chemin).values()
            for regles in colonnes.values()
            for regle in regles.values()
        )
        if revues:
            raise FileExistsError(
                f"{chemin} porte {revues} règles déjà revues : écriture refusée "
                "(ecraser=True pour forcer)"
            )

    chemin.parent.mkdir(parents=True, exist_ok=True)
    provisoire = chemin.with_name(chemin.name + ".tmp")
    try:
        with open(provisoire, "w", encoding="utf-8", newline="\n") as flux:
            yaml.safe_dump(
                {"meta": _meta(periode_fin), "tables": tables},
                flux,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=1000,
            )
        if charger_dictionnaire(provisoire) != tables:
            raise RuntimeError("La relecture du dictionnaire écrit diffère de l'original")
        os.replace(provisoire, chemin)
    finally:
        provisoire.unlink(missing_ok=True)
    return chemin