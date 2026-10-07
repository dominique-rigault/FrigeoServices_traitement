"""Génération du dictionnaire des données à partir des données observées.

Ce module ne contient rien de propre à un client. Tout ce qui est généré a le
statut « observé »; seul le métier peut le faire passer à « validé ».
"""

from __future__ import annotations

import pandas as pd

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