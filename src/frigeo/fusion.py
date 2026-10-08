"""Fusion d'un dictionnaire régénéré avec le dictionnaire en place (étape 2d).

À chaque nouveau mois, le dictionnaire est régénéré à partir des données. Les
décisions déjà prises par le métier ne doivent pas être perdues : la fusion garde
les règles et les valeurs revues, met à jour ce que la génération observe, et
rend un rapport de ce qui a changé. Ce module ne contient rien de propre à un
client et n'écrit aucun fichier.
"""

from __future__ import annotations

from copy import deepcopy

import pandas as pd

from .dictionnaire import LISTE_FERMEE, ORIGINE_AJOUT, REGLES, STATUT_INITIAL

A_REGARDER = "à regarder"
INFORMATION = "information"
COLONNES_RAPPORT = ("table", "colonne", "regle", "valeur", "evenement", "niveau")


def _revue(element: dict) -> bool:
    """Une règle ou une valeur est revue dès que son statut n'est plus « observé »."""
    return element["statut"] != STATUT_INITIAL


def _porte_decision(colonne: dict) -> bool:
    return any(
        _revue(element)
        for regle in colonne.values()
        for element in (regle, *regle.get("liste", ()))
    )


def _fusionner_regle(ancienne: dict, nouvelle: dict, noter) -> dict:
    """Met à jour ce que la génération observe, sans toucher à la décision.

    Une règle non revue suit la nouvelle proposition. Une règle revue garde sa
    règle en vigueur : une nouvelle proposition qui s'en écarte est signalée.
    """
    regle = deepcopy(ancienne)
    for champ in ("proposition", "motif", "a_arbitrer"):
        regle[champ] = deepcopy(nouvelle[champ])
    if not _revue(ancienne):
        regle["regle"] = nouvelle["proposition"]
    if nouvelle["proposition"] != ancienne["proposition"]:
        if _revue(ancienne) and nouvelle["proposition"] != ancienne["regle"]:
            noter("nouvelle proposition différente de la règle en vigueur", A_REGARDER)
        else:
            noter("proposition changée", INFORMATION)
    return regle


def _fusionner_liste(ancienne: dict, nouvelle: dict, regle_en_vigueur: str, noter) -> list:
    """Liste des valeurs après fusion : l'ordre de la génération, puis les valeurs conservées."""
    anciennes = {element["valeur"]: element for element in ancienne["liste"]}
    etait_proposee = ancienne["proposition"] == LISTE_FERMEE
    liste = []
    for observee in nouvelle["liste"]:
        valeur = observee["valeur"]
        connue = anciennes.pop(valeur, None)
        if connue is None:
            liste.append(deepcopy(observee))
            if etait_proposee:
                noter("valeur nouvelle", INFORMATION, valeur)
            continue
        element = deepcopy(connue)
        element["effectif"] = observee["effectif"]
        # Une valeur ajoutée par le métier le reste, même si elle apparaît dans les données.
        if connue["origine"] not in (ORIGINE_AJOUT, observee["origine"]):
            element["origine"] = observee["origine"]
            noter("origine changée", INFORMATION, valeur)
        liste.append(element)

    # Valeurs que la génération ne connaît pas.
    if nouvelle["proposition"] != LISTE_FERMEE:
        # Sans liste proposée, la génération ne compte plus les valeurs.
        garder_tout = regle_en_vigueur == LISTE_FERMEE
        conservees = 0
        for valeur, connue in anciennes.items():
            if garder_tout or _revue(connue):
                liste.append(deepcopy(connue))
                conservees += 1
            else:
                noter("valeur non revue supprimée", INFORMATION, valeur)
        if conservees and etait_proposee:
            noter(
                f"liste qui n'est plus proposée : {conservees} valeurs conservées, "
                "effectif non mis à jour",
                INFORMATION,
            )
        return liste
    for valeur, connue in anciennes.items():
        if not _revue(connue):
            noter("valeur non revue supprimée", INFORMATION, valeur)
            continue
        element = deepcopy(connue)
        if connue["effectif"] > 0 and connue["origine"] != ORIGINE_AJOUT:
            noter("valeur revue qui n'est plus observée", A_REGARDER, valeur)
        element["effectif"] = 0
        liste.append(element)
    return liste


def _fusionner_colonne(ancienne: dict, nouvelle: dict, noter) -> dict:
    colonne = {}
    for nom in REGLES:
        colonne[nom] = _fusionner_regle(
            ancienne[nom], nouvelle[nom], lambda *args, nom=nom: noter(nom, *args)
        )
    colonne["valeurs"]["liste"] = _fusionner_liste(
        ancienne["valeurs"],
        nouvelle["valeurs"],
        colonne["valeurs"]["regle"],
        lambda *args: noter("valeurs", *args),
    )
    return colonne


def fusionner(existant: dict, regenere: dict) -> tuple[dict, pd.DataFrame]:
    """Fusionne le dictionnaire régénéré avec le dictionnaire en place.

    `existant` et `regenere` sont les tables rendues par `charger_dictionnaire` et
    `generer_dictionnaire`; aucun des deux n'est modifié. Rend le dictionnaire
    fusionné et le rapport, une ligne par événement, ceux « à regarder » en premier
    (`regle` et `valeur` sont vides quand l'événement ne les concerne pas).

    Règle : la proposition, le motif et les écarts à arbitrer viennent de la
    génération; la règle en vigueur ne change que si la règle n'a pas été revue.
    Valeur : l'effectif et l'origine viennent de la génération; une valeur revue est
    conservée même si elle n'est plus observée, une valeur non revue qui n'est plus
    observée est supprimée. Statut, commentaire, remplacement et date de revue ne
    sont jamais modifiés. Une colonne absente de la régénération est conservée si
    elle porte une décision, supprimée sinon.
    """
    evenements = []

    def noteur(table, colonne):
        def noter(regle, evenement, niveau, valeur=""):
            evenements.append((table, colonne, regle, valeur, evenement, niveau))

        return noter

    fusion = {}
    for table, colonnes in regenere.items():
        anciennes = existant.get(table, {})
        fusion[table] = {}
        for colonne, nouvelle in colonnes.items():
            noter = noteur(table, colonne)
            if colonne in anciennes:
                fusion[table][colonne] = _fusionner_colonne(anciennes[colonne], nouvelle, noter)
            else:
                fusion[table][colonne] = deepcopy(nouvelle)
                noter("", "colonne nouvelle", INFORMATION)
    for table, colonnes in existant.items():
        for colonne, ancienne in colonnes.items():
            if colonne in regenere.get(table, {}):
                continue
            noter = noteur(table, colonne)
            if _porte_decision(ancienne):
                fusion.setdefault(table, {})[colonne] = deepcopy(ancienne)
                noter("", "colonne absente de la régénération, conservée avec ses décisions", A_REGARDER)
            else:
                noter("", "colonne absente de la régénération, supprimée", INFORMATION)

    rapport = pd.DataFrame(evenements, columns=list(COLONNES_RAPPORT))
    ordre = rapport["niveau"].map({A_REGARDER: 0, INFORMATION: 1})
    rapport = rapport.iloc[ordre.argsort(kind="stable")].reset_index(drop=True)
    return fusion, rapport
