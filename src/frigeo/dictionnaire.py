"""Génération du dictionnaire des données à partir des données observées.

Ce module ne contient rien de propre à un client. Tout ce qui est généré a le
statut « observé »; seul le métier peut le faire passer à « validé ».
"""

from __future__ import annotations

import pandas as pd

from .confidentialite import est_sensible
from .profilage import profiler_colonne

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

    nature = profiler_colonne(serie)["nature_dominante"]
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