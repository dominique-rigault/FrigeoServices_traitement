"""Profilage des tables chargées (étape 2).

Le profilage décrit ce qui est réellement présent dans chaque colonne, sans rien
corriger ni supposer : types Python, valeurs vides, valeurs distinctes, formats
observés (signatures), nature dominante et bornes. La comparaison avec le
dictionnaire des données (chapitre 4) se fait à la lecture du profil; les
contrôles automatisés relèvent de l'étape 3.

Usage typique, après le chargement de l'étape 1 :

    profil = profiler_tout(tables)
    detail_signatures(tables["interventions"], "date_debut")
"""

from __future__ import annotations

import datetime as dt
import numbers
from functools import lru_cache

import pandas as pd

# Colonnes ajoutées par le chargement, exclues du profil des données.
COLONNES_LIGNAGE = (
    "fichier_source",
    "feuille_source",
    "num_ligne_source",
    "periode_export",
    "date_chargement",
    "nb_champs_source",
    "champs_excedentaires",
)

# Séquences typiques d'un texte UTF-8 relu avec un autre encodage.
MOTIF_ENCODAGE_SUSPECT = r"Ã|Â|â€|\ufffd"


def _vers_nombre(serie: pd.Series) -> pd.Series:
    return pd.to_numeric(serie, errors="coerce")


def _vers_nombre_virgule(serie: pd.Series) -> pd.Series:
    return pd.to_numeric(serie.str.replace(",", ".", regex=False), errors="coerce")


def _vers_date(format_date: str):
    def convertir(serie: pd.Series) -> pd.Series:
        return pd.to_datetime(serie, format=format_date, errors="coerce")

    return convertir


# Natures testées sur les valeurs de type texte : (motif complet, conversion).
# Une valeur ne compte dans une nature que si elle respecte le motif ET se
# convertit (31/02/2025 n'est pas une date). L'ordre départage les égalités :
# 20250321 est d'abord lu comme une date AAAAMMJJ.
_NATURES_TEXTE = {
    "date JJ/MM/AAAA": (r"\d{2}/\d{2}/\d{4}", _vers_date("%d/%m/%Y")),
    "date AAAAMMJJ": (r"\d{8}", _vers_date("%Y%m%d")),
    "date AAAA-MM-JJ": (r"\d{4}-\d{2}-\d{2}", _vers_date("%Y-%m-%d")),
    "heure HH:MM": (r"\d{2}:\d{2}", _vers_date("%H:%M")),
    "entier (texte)": (r"-?\d+", _vers_nombre),
    "décimal virgule (texte)": (r"-?\d+,\d+", _vers_nombre_virgule),
    "décimal point (texte)": (r"-?\d+\.\d+", _vers_nombre),
}

_NATURES_DATE = ("date JJ/MM/AAAA", "date AAAAMMJJ", "date AAAA-MM-JJ", "date native")


@lru_cache(maxsize=None)
def signature(valeur) -> str:
    """Forme d'une valeur : chiffre devient 9, majuscule A, minuscule a.

    Les autres caractères (séparateurs, espaces, accents isolés) sont conservés.
    INT-2025-004187 donne AAA-9999-999999.
    """
    sortie = []
    for caractere in str(valeur):
        if caractere.isdigit():
            sortie.append("9")
        elif caractere.isalpha():
            sortie.append("A" if caractere.isupper() else "a")
        else:
            sortie.append(caractere)
    return "".join(sortie)


def _est_texte(valeur) -> bool:
    return isinstance(valeur, str)


def _est_nombre_natif(valeur) -> bool:
    return isinstance(valeur, numbers.Real) and not isinstance(valeur, bool)


def _est_date_native(valeur) -> bool:
    return isinstance(valeur, dt.date)


def _interpretations(presentes: pd.Series) -> dict[str, pd.Series]:
    """Pour chaque nature, les valeurs présentes qui s'y conforment, converties."""
    resultat: dict[str, pd.Series] = {}

    dates = presentes[presentes.map(_est_date_native).astype(bool)]
    resultat["date native"] = pd.to_datetime(dates.astype(object)).dropna()

    nombres = presentes[presentes.map(_est_nombre_natif).astype(bool)]
    resultat["nombre natif"] = pd.to_numeric(nombres.astype(object)).dropna()

    textes = presentes[presentes.map(_est_texte).astype(bool)].astype(str)
    for nature, (motif, convertir) in _NATURES_TEXTE.items():
        if textes.empty:
            resultat[nature] = pd.Series(dtype="float64")
            continue
        conformes = textes[textes.str.fullmatch(motif)]
        resultat[nature] = convertir(conformes).dropna() if len(conformes) else conformes
    return resultat


def _formater_borne(valeur, nature: str) -> str:
    if nature in _NATURES_DATE:
        horodatage = pd.Timestamp(valeur)
        if horodatage.time() == dt.time(0, 0):
            return horodatage.strftime("%d/%m/%Y")
        return horodatage.strftime("%d/%m/%Y %H:%M")
    if nature == "heure HH:MM":
        return pd.Timestamp(valeur).strftime("%H:%M")
    return f"{valeur:.10g}"


def profiler_colonne(serie: pd.Series) -> dict:
    """Profil d'une colonne : vides, types, distincts, formats, nature, bornes.

    Trois formes de vide sont comptées à part : None ou NaN, chaîne vide, chaîne
    d'espaces. Les natures (dates, entiers, décimaux) sont celles réellement
    observées; la nature dominante est la plus fréquente parmi les valeurs
    présentes, les autres valeurs sont comptées hors nature.
    """
    total = len(serie)
    est_none = serie.isna().astype(bool)
    est_chaine_vide = serie.map(lambda v: isinstance(v, str) and v == "").astype(bool)
    est_espaces = serie.map(
        lambda v: isinstance(v, str) and v != "" and v.strip() == ""
    ).astype(bool)
    vides = est_none | est_chaine_vide | est_espaces
    presentes = serie[~vides]

    profil = {
        "nb_lignes": total,
        "nb_none_nan": int(est_none.sum()),
        "nb_chaine_vide": int(est_chaine_vide.sum()),
        "nb_espaces_seuls": int(est_espaces.sum()),
        "pct_vide": round(100 * int(vides.sum()) / total, 2) if total else None,
    }
    if presentes.empty:
        return {**profil, "nature_dominante": "aucune valeur"}

    types = presentes.map(lambda v: type(v).__name__).value_counts()
    textes = presentes[presentes.map(_est_texte).astype(bool)].astype(str)
    longueurs = presentes.map(lambda v: len(str(v)))

    comptes = presentes.value_counts()
    par_signature = (
        pd.DataFrame(
            {"signature": [signature(v) for v in comptes.index], "n": comptes.to_numpy()}
        )
        .groupby("signature")["n"]
        .sum()
        .sort_values(ascending=False, kind="stable")
    )

    interpretations = _interpretations(presentes)
    effectifs = {nature: len(valeurs) for nature, valeurs in interpretations.items()}
    nature, effectif = max(effectifs.items(), key=lambda element: element[1])
    if effectif == 0:
        nature = "texte"
        borne_min = borne_max = None
    else:
        valeurs = interpretations[nature]
        borne_min = _formater_borne(valeurs.min(), nature)
        borne_max = _formater_borne(valeurs.max(), nature)

    return {
        **profil,
        "nb_distincts": int(presentes.nunique()),
        "types_python": ", ".join(f"{nom} ({n})" for nom, n in types.items()),
        "nature_dominante": nature,
        "pct_nature": round(100 * effectif / len(presentes), 2) if effectif else None,
        "nb_hors_nature": len(presentes) - effectif if effectif else 0,
        "min": borne_min,
        "max": borne_max,
        "long_min": int(longueurs.min()),
        "long_max": int(longueurs.max()),
        "nb_signatures": len(par_signature),
        "signatures_top": " | ".join(
            f"{forme} ({n})" for forme, n in par_signature.head(3).items()
        ),
        "nb_espaces_bord": int((textes != textes.str.strip()).sum()),
        "nb_encodage_suspect": int(
            textes.str.contains(MOTIF_ENCODAGE_SUSPECT, regex=True).sum()
        ),
    }


def profiler_table(
    donnees: pd.DataFrame, nom_table: str, par: str | None = None
) -> pd.DataFrame:
    """Profil de toutes les colonnes de données d'une table (une ligne par colonne).

    Avec par="periode_export" ou par="fichier_source", le profil est établi
    séparément pour chaque exemplaire, ce qui révèle un format qui change d'un
    export à l'autre.
    """
    colonnes = [c for c in donnees.columns if c not in COLONNES_LIGNAGE]
    groupes = [(None, donnees)] if par is None else list(donnees.groupby(par, sort=True))
    lignes = []
    for cle, sous_table in groupes:
        for colonne in colonnes:
            ligne = {"table": nom_table}
            if par is not None:
                ligne[par] = cle
            ligne["colonne"] = colonne
            ligne.update(profiler_colonne(sous_table[colonne]))
            lignes.append(ligne)
    return pd.DataFrame(lignes)


def profiler_tout(tables: dict[str, pd.DataFrame], par: str | None = None) -> pd.DataFrame:
    """Profil de l'ensemble des tables chargées, empilé dans un seul tableau."""
    return pd.concat(
        [profiler_table(donnees, nom, par=par) for nom, donnees in tables.items()],
        ignore_index=True,
    )


def detail_signatures(donnees: pd.DataFrame, colonne: str, n: int = 10) -> pd.DataFrame:
    """Formes observées dans une colonne, avec effectif, part et ligne d'exemple.

    La forme est distinguée du type Python : un montant lu comme texte et un
    montant lu comme nombre ont la même forme mais pas le même type. Chaque forme
    renvoie à une ligne source (fichier et numéro de ligne), pour aller voir la
    valeur dans le fichier brut.
    """
    serie = donnees[colonne]
    masque = (serie.notna() & (serie.astype(str).str.strip() != "")).to_numpy()
    valeurs = serie[masque]
    colonnes_lignage = [c for c in ("fichier_source", "num_ligne_source") if c in donnees.columns]
    base = donnees.loc[masque, colonnes_lignage].copy()
    base["signature"] = [signature(v) for v in valeurs]
    base["type"] = [type(v).__name__ for v in valeurs]
    base["valeur_exemple"] = valeurs.to_numpy()

    agregats = {"effectif": ("signature", "size"), "valeur_exemple": ("valeur_exemple", "first")}
    for lignage in ("fichier_source", "num_ligne_source"):
        if lignage in base.columns:
            agregats[f"{lignage}_exemple"] = (lignage, "first")
    resume = (
        base.groupby(["signature", "type"], sort=False)
        .agg(**agregats)
        .sort_values("effectif", ascending=False, kind="stable")
    )
    resume["part_pct"] = (100 * resume["effectif"] / len(base)).round(2)
    return resume.head(n).reset_index()