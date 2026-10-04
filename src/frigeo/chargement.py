"""Chargement des fichiers bruts sans modification, avec lignage.

Chaque ligne chargée conserve
- fichier_source, le nom du fichier d'origine
- feuille_source, le nom de la feuille pour un fichier Excel
- num_ligne_source, le numéro de ligne physique, l'en-tête étant la ligne 1
- periode_export, la période du fichier
- date_chargement, l'horodatage du chargement

Les valeurs des fichiers texte sont conservées telles quelles, sous forme de texte.
Les valeurs des fichiers Excel conservent le type lu dans la cellule.
"""

from __future__ import annotations

import csv
from pathlib import Path

import openpyxl
import pandas as pd

from frigeo.perimetre import Perimetre

# Encodage et séparateur déclarés dans le dossier de données
FORMATS_TEXTE = {
    "interventions": ("utf-8", ";"),
    "pieces_interventions": ("utf-8", ";"),
    "fec": ("iso-8859-15", "\t"),
    "clients": ("cp1252", ";"),
    "fournisseurs": ("utf-8", ";"),
}

# Table, avec le flux d'origine et le nom de la feuille Excel
FEUILLES_EXCEL = {
    "factures_entetes": ("factures", "Entetes"),
    "factures_lignes": ("factures", "Lignes"),
    "achats_entetes": ("achats", "Entetes"),
    "achats_lignes": ("achats", "Lignes"),
    "intervenants": ("intervenants", "Intervenants"),
    "remunerations": ("intervenants", "Remunerations"),
    "catalogue_pieces": ("catalogue_pieces", "Catalogue"),
    "parametres_couts": ("parametres_couts", "Parametres"),
}

TABLES = [*FORMATS_TEXTE, *FEUILLES_EXCEL]


def lire_texte(chemin: Path, encodage: str, sep: str):
    """Renvoie l'en-tête et la liste des (numéro de ligne physique, valeurs)."""
    try:
        with open(chemin, encoding=encodage, newline="") as fichier:
            lecteur = csv.reader(fichier, delimiter=sep)
            entete = next(lecteur, None)
            if entete is None:
                raise RuntimeError(f"Fichier vide {chemin.name}")
            precedent = lecteur.line_num
            lignes = []
            for valeurs in lecteur:
                lignes.append((precedent + 1, valeurs))
                precedent = lecteur.line_num
    except UnicodeDecodeError as erreur:
        raise RuntimeError(
            f"Encodage inattendu pour {chemin.name}, attendu {encodage}, octet {erreur.start}"
        ) from erreur
    return entete, lignes


def lire_excel(chemin: Path, feuille: str):
    """Renvoie l'en-tête et la liste des (numéro de ligne, valeurs) d'une feuille."""
    classeur = openpyxl.load_workbook(chemin, read_only=True, data_only=True)
    try:
        if feuille not in classeur.sheetnames:
            raise RuntimeError(f"Feuille {feuille} absente de {chemin.name}")
        rangees = list(classeur[feuille].iter_rows(values_only=True))
    finally:
        classeur.close()
    if not rangees:
        raise RuntimeError(f"Feuille {feuille} vide dans {chemin.name}")
    entete = [None if c is None else str(c) for c in rangees[0]]
    lignes = [
        (numero, list(valeurs)) for numero, valeurs in enumerate(rangees[1:], start=2)
    ]
    return entete, lignes


def _assembler(entete, lignes, fichier, feuille=None, sep=None) -> pd.DataFrame:
    n = len(entete)
    donnees = [v[:n] + [None] * (n - len(v)) for _, v in lignes]
    table = pd.DataFrame(donnees, columns=entete, dtype=object)
    if sep is not None:
        table["nb_champs_source"] = [len(v) for _, v in lignes]
        table["champs_excedentaires"] = [
            sep.join(v[n:]) if len(v) > n else None for _, v in lignes
        ]
    table.insert(0, "periode_export", fichier["periode"])
    table.insert(0, "num_ligne_source", [numero for numero, _ in lignes])
    table.insert(0, "feuille_source", feuille)
    table.insert(0, "fichier_source", fichier["fichier"])
    return table


def charger_table(perimetre: Perimetre, table: str, date_chargement=None) -> pd.DataFrame:
    """Charge et assemble tous les exemplaires d'une table du périmètre."""
    date_chargement = date_chargement or pd.Timestamp.now().floor("s")
    morceaux = []
    if table in FORMATS_TEXTE:
        encodage, sep = FORMATS_TEXTE[table]
        for f in (f for f in perimetre.fichiers if f["flux"] == table):
            entete, lignes = lire_texte(f["chemin"], encodage, sep)
            morceaux.append(_assembler(entete, lignes, f, sep=sep))
    else:
        flux, feuille = FEUILLES_EXCEL[table]
        for f in (f for f in perimetre.fichiers if f["flux"] == flux):
            entete, lignes = lire_excel(f["chemin"], feuille)
            morceaux.append(_assembler(entete, lignes, f, feuille=feuille))
    resultat = pd.concat(morceaux, ignore_index=True)
    resultat["date_chargement"] = date_chargement
    return resultat


def charger_tout(perimetre: Perimetre) -> dict[str, pd.DataFrame]:
    """Charge toutes les tables avec le même horodatage."""
    horodatage = pd.Timestamp.now().floor("s")
    return {t: charger_table(perimetre, t, horodatage) for t in TABLES}


def bilan_chargement(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Nombre de lignes chargées par table, fichier et feuille."""
    lignes = []
    for table, donnees in tables.items():
        comptes = donnees.groupby(
            ["fichier_source", "feuille_source"], dropna=False
        ).size()
        for (fichier, feuille), nombre in comptes.items():
            lignes.append(
                {
                    "table": table,
                    "fichier_source": fichier,
                    "feuille_source": feuille if isinstance(feuille, str) else None,
                    "lignes_chargees": int(nombre),
                }
            )
    return pd.DataFrame(lignes)