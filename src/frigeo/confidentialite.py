"""Classification des colonnes par sensibilité et masquage des exemples.

Un profil destiné à être partagé avec un assistant ne doit contenir, pour les
colonnes sensibles, que des formes, des effectifs et des types. Le masquage
porte sur la sortie et ne change rien au calcul du profil.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

# Mesures du profil qui exposent des valeurs réelles.
MESURES_A_MASQUER = ("min", "max")


def chemin_sensibilite() -> Path:
    """Chemin de config/sensibilite.yaml à la racine du projet."""
    from frigeo import racine_projet

    return racine_projet() / "config" / "sensibilite.yaml"


def charger_sensibilite(chemin: Path | None = None) -> dict[str, frozenset[str]]:
    """Lit la classification et renvoie, par table, l'ensemble des colonnes sensibles."""
    chemin = chemin or chemin_sensibilite()
    if not chemin.is_file():
        raise RuntimeError(f"Classification de sensibilité introuvable {chemin}")
    with open(chemin, encoding="utf-8") as fichier:
        brut = yaml.safe_load(fichier)
    if not isinstance(brut, dict) or not isinstance(brut.get("colonnes_sensibles"), dict):
        raise RuntimeError("La clé colonnes_sensibles est absente ou n'est pas un dictionnaire")
    resultat = {}
    for table, colonnes in brut["colonnes_sensibles"].items():
        if not isinstance(colonnes, list) or not all(isinstance(c, str) for c in colonnes):
            raise RuntimeError(f"Les colonnes sensibles de {table} doivent être une liste de textes")
        resultat[table] = frozenset(colonnes)
    return resultat


def verifier_sensibilite(
    tables: dict[str, pd.DataFrame], sensibles: dict[str, frozenset[str]]
) -> list[str]:
    """Liste les tables et colonnes classées sensibles mais absentes des données chargées."""
    problemes = []
    for table, colonnes in sensibles.items():
        if table not in tables:
            problemes.append(f"Table {table} classée sensible mais absente des données chargées")
            continue
        for colonne in sorted(colonnes - set(tables[table].columns)):
            problemes.append(
                f"Colonne {table}.{colonne} classée sensible mais absente de la table"
            )
    return problemes


def est_sensible(sensibles: dict[str, frozenset[str]], table: str, colonne: str) -> bool:
    return colonne in sensibles.get(table, ())


def masquer_mesures(profil: dict) -> dict:
    """Retire d'un profil de colonne les mesures qui exposent des valeurs réelles."""
    return {**profil, **{m: None for m in MESURES_A_MASQUER if m in profil}}