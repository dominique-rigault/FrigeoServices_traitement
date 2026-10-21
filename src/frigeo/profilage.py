"""Profilage des tables chargées (étape 2).

Le profilage décrit ce qui est réellement présent dans chaque colonne, sans rien
corriger ni supposer : types Python, valeurs vides, valeurs distinctes, formats
observés (signatures), nature dominante et bornes. Le dictionnaire des données
(étape 2c) part de ce profil; les contrôles automatisés relèvent de l'étape 3.

Usage typique, après le chargement de l'étape 1 :

    profil = profiler_tout(tables, masquer_exemples=True)
    synthese_par_table(profil)
    points_a_regarder(profil, tables=tables)
    detail_signatures(tables[nom_table], colonne)

Les fonctions de synthèse (`synthese_par_table`, `points_a_regarder`,
`texte_export_profil`) ne nomment aucune table ni colonne : elles parcourent le
profil, quel que soit le client.
"""

from __future__ import annotations

import datetime as dt
import numbers
import re
from functools import lru_cache

import pandas as pd

from frigeo.confidentialite import (
    charger_sensibilite,
    est_sensible,
    masquer_mesures,
    verifier_sensibilite,
)

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
    donnees: pd.DataFrame,
    nom_table: str,
    par: str | None = None,
    masquer_exemples: bool = False,
    sensibles: dict[str, frozenset[str]] | None = None,
) -> pd.DataFrame:
    """Profil de toutes les colonnes de données d'une table (une ligne par colonne).

    Avec par="periode_export" ou par="fichier_source", le profil est établi
    séparément pour chaque exemplaire, ce qui révèle un format qui change d'un
    export à l'autre.

    Avec masquer_exemples=True, les colonnes classées sensibles (config/sensibilite.yaml
    par défaut) n'exposent plus leurs bornes. Le profil est calculé en entier puis
    filtré : seule la sortie change.
    """
    if masquer_exemples and sensibles is None:
        sensibles = charger_sensibilite()
    colonnes = [c for c in donnees.columns if c not in COLONNES_LIGNAGE]
    groupes = [(None, donnees)] if par is None else list(donnees.groupby(par, sort=True))
    lignes = []
    for cle, sous_table in groupes:
        for colonne in colonnes:
            ligne = {"table": nom_table}
            if par is not None:
                ligne[par] = cle
            ligne["colonne"] = colonne
            profil = profiler_colonne(sous_table[colonne])
            masquee = masquer_exemples and est_sensible(sensibles, nom_table, colonne)
            if masquee:
                profil = masquer_mesures(profil)
            ligne.update(profil)
            if masquer_exemples:
                ligne["masquee"] = masquee
            lignes.append(ligne)
    return pd.DataFrame(lignes)


def profiler_tout(
    tables: dict[str, pd.DataFrame],
    par: str | None = None,
    masquer_exemples: bool = False,
    sensibles: dict[str, frozenset[str]] | None = None,
) -> pd.DataFrame:
    """Profil de l'ensemble des tables chargées, empilé dans un seul tableau.

    Avec masquer_exemples=True, la classification est vérifiée avant le calcul :
    une colonne classée sensible mais introuvable (faute de frappe probable)
    arrête le traitement, car la vraie colonne serait alors exposée.
    """
    if masquer_exemples:
        if sensibles is None:
            sensibles = charger_sensibilite()
        problemes = verifier_sensibilite(tables, sensibles)
        if problemes:
            raise RuntimeError(
                "Classification de sensibilité incohérente\n  " + "\n  ".join(problemes)
            )
    return pd.concat(
        [
            profiler_table(
                donnees, nom, par=par, masquer_exemples=masquer_exemples, sensibles=sensibles
            )
            for nom, donnees in tables.items()
        ],
        ignore_index=True,
    )


def detail_signatures(
    donnees: pd.DataFrame,
    colonne: str,
    n: int = 10,
    masquer_exemples: bool = False,
    sensibles: dict[str, frozenset[str]] | None = None,
    nom_table: str | None = None,
) -> pd.DataFrame:
    """Formes observées dans une colonne, avec effectif, part et ligne d'exemple.

    La forme est distinguée du type Python : un montant lu comme texte et un
    montant lu comme nombre ont la même forme mais pas le même type. Chaque forme
    renvoie à une ligne source (fichier et numéro de ligne), pour aller voir la
    valeur dans le fichier brut.

    Avec masquer_exemples=True, la valeur d'exemple est retirée pour une colonne
    classée sensible. Le nom de la table est alors obligatoire.
    """
    masquee = False
    if masquer_exemples:
        if nom_table is None:
            raise ValueError("nom_table est obligatoire avec masquer_exemples=True")
        if sensibles is None:
            sensibles = charger_sensibilite()
        masquee = est_sensible(sensibles, nom_table, colonne)

    serie = donnees[colonne]
    masque = (serie.notna() & (serie.astype(str).str.strip() != "")).to_numpy()
    valeurs = serie[masque]
    colonnes_lignage = [c for c in ("fichier_source", "num_ligne_source") if c in donnees.columns]
    base = donnees.loc[masque, colonnes_lignage].copy()
    base["signature"] = [signature(v) for v in valeurs]
    base["type"] = [type(v).__name__ for v in valeurs]
    agregats = {"effectif": ("signature", "size")}
    if not masquee:
        base["valeur_exemple"] = valeurs.to_numpy()
        agregats["valeur_exemple"] = ("valeur_exemple", "first")
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


# Synthèse du profil, sans nom propre à un client.

POINT_HORS_NATURE = "valeurs hors de la nature dominante"
POINT_TYPES = "plusieurs types lus"
POINT_VIDES = "vides sous plusieurs formes"
POINT_ESPACES = "espaces en début ou fin de valeur"
POINT_TOUJOURS_VIDE = "colonne toujours vide"
POINT_CONSTANTE = "une seule valeur"
POINT_FORME = "forme numérique non reconnue"
POINT_FORME_ELARGIE = "forme élargie lue par le nettoyage"
POINT_EXPORT = "nature différente selon l'export"
POINTS = (
    POINT_FORME,
    POINT_EXPORT,
    POINT_HORS_NATURE,
    POINT_FORME_ELARGIE,
    POINT_TYPES,
    POINT_VIDES,
    POINT_ESPACES,
    POINT_TOUJOURS_VIDE,
    POINT_CONSTANTE,
)
# Forme faite de chiffres et de séparateurs, avec au besoin € en fin : date,
# heure ou nombre possible.
_FORME_NUMERIQUE = re.compile(r"[9 .,:/'\-\u00a0\u202f]*9[9 .,:/'\-\u00a0\u202f€]*")
FORMES_AFFICHEES = 3
# Familles de types Python : des types d'une même famille (int et float lus dans un
# classeur Excel) ne font pas un point « plusieurs types lus ».
_FAMILLES_TYPES = {
    "int": "nombre",
    "float": "nombre",
    "Decimal": "nombre",
    "datetime": "date",
    "date": "date",
    "Timestamp": "date",
    "time": "heure",
}
FORME_MASQUEE = "masquée"
COLONNES_POINTS = ["table", "colonne", "point", "cellules", "detail"]
COLONNES_EXPORT_PROFIL = [
    "table",
    "colonne",
    "nature_dominante",
    "pct_nature",
    "pct_vide",
    "nb_distincts",
    "nb_signatures",
    "signatures_top",
]


def _effectifs_familles(types_python) -> dict[str, int]:
    """Effectifs par famille de types, lus dans le champ `types_python`
    (« str (12), float (3) »); int et float forment une seule famille."""
    if not isinstance(types_python, str):
        return {}
    familles: dict[str, int] = {}
    for nom, n in re.findall(r"(\w+) \((\d+)\)", types_python):
        famille = _FAMILLES_TYPES.get(nom, nom)
        familles[famille] = familles.get(famille, 0) + int(n)
    return familles


def _entier(valeur) -> int:
    return 0 if valeur is None or pd.isna(valeur) else int(valeur)


def synthese_par_table(profil: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par table : lignes, colonnes, natures dominantes et décomptes de
    colonnes concernées par des vides, des valeurs hors nature ou des espaces."""
    lignes = []
    for table, groupe in profil.groupby("table", sort=False):
        natures = groupe["nature_dominante"].value_counts()
        lignes.append(
            {
                "table": table,
                "lignes": int(groupe["nb_lignes"].max()),
                "colonnes": len(groupe),
                "natures": ", ".join(f"{nature} ({n})" for nature, n in natures.items()),
                "colonnes_avec_vides": int((groupe["pct_vide"] > 0).sum()),
                "colonnes_toujours_vides": int(
                    (groupe["nature_dominante"] == "aucune valeur").sum()
                ),
                "colonnes_hors_nature": int(
                    (groupe["nb_hors_nature"].fillna(0) > 0).sum()
                ),
                "colonnes_espaces_bord": int(
                    (groupe["nb_espaces_bord"].fillna(0) > 0).sum()
                ),
            }
        )
    return pd.DataFrame(lignes)


def _motifs_reconnus(forme: str) -> bool:
    """Vrai si la forme correspond au motif d'une nature reconnue (le chiffre 9 de
    la forme se lit comme un chiffre dans les motifs)."""
    return any(re.fullmatch(motif, forme) for motif, _ in _NATURES_TEXTE.values())


def _lue_par_le_nettoyage(forme: str) -> bool:
    """Vrai si la règle `nature` du nettoyage sait lire la forme : date JJ.MM.AAAA,
    JJ-MM-AAAA ou JJ/MM/AA, heure HH:MM, nombre avec séparateur de milliers ou
    symbole €. Le chiffre 9 de la forme se lit comme un chiffre."""
    # Import local : le module de nettoyage importe lui-même ce module.
    from .nettoyage import (
        _DATE_AAAA_MM_JJ,
        _DATE_AAAAMMJJ,
        _DATE_JJ_MM_AA,
        _DATE_JJ_MM_AAAA,
        _HEURE,
        _lire_nombre,
    )

    motifs = (_DATE_JJ_MM_AAAA, _DATE_JJ_MM_AA, _DATE_AAAA_MM_JJ, _DATE_AAAAMMJJ, _HEURE)
    return any(m.fullmatch(forme) for m in motifs) or _lire_nombre(forme) is not None


def formes_non_reconnues(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Formes faites de chiffres et de séparateurs qu'aucune nature ne reconnaît.

    Seules les valeurs lues comme texte sont examinées (une date native d'Excel a
    une forme connue). Une ligne par table, colonne et sorte de forme : nombre
    de cellules et formes concernées, les plus fréquentes d'abord. `lue_par_nettoyage`
    est vrai pour les formes élargies que la règle `nature` du nettoyage sait lire
    (JJ.MM.AAAA, JJ/MM/AA, milliers séparés par une espace); les autres peuvent être
    une date, une heure ou un nombre que ni le profil ni le nettoyage ne savent lire
    (HH:MM:SS, MM/JJ/AAAA), ou un code formaté (téléphone).
    """
    lignes = []
    for table, donnees in tables.items():
        for colonne in donnees.columns:
            if colonne in COLONNES_LIGNAGE:
                continue
            serie = donnees[colonne]
            textes = serie[[isinstance(v, str) and v.strip() != "" for v in serie]]
            if textes.empty:
                continue
            formes = textes.map(signature).value_counts()
            retenues = [
                forme
                for forme in formes.index
                if _FORME_NUMERIQUE.fullmatch(forme) and not _motifs_reconnus(forme)
            ]
            for lue in (False, True):
                sorte = [f for f in retenues if _lue_par_le_nettoyage(f) is lue]
                if sorte:
                    lignes.append(
                        {
                            "table": table,
                            "colonne": colonne,
                            "lue_par_nettoyage": lue,
                            "cellules": int(formes[sorte].sum()),
                            "formes": [str(f) for f in sorte],
                        }
                    )
    return pd.DataFrame(
        lignes, columns=["table", "colonne", "lue_par_nettoyage", "cellules", "formes"]
    )


def natures_par_export(profil_par_export: pd.DataFrame) -> pd.DataFrame:
    """Colonnes dont la nature dominante change d'un export à l'autre.

    `profil_par_export` est le résultat de `profiler_tout(tables,
    par="periode_export")`. Les exports sans aucune valeur dans la colonne sont
    ignorés. Une ligne par table et colonne : nombre d'exports et détail des
    natures par période.
    """
    lignes = []
    presentes = profil_par_export[profil_par_export["nature_dominante"] != "aucune valeur"]
    for (table, colonne), groupe in presentes.groupby(["table", "colonne"], sort=False):
        if groupe["nature_dominante"].nunique() < 2:
            continue
        lignes.append(
            {
                "table": table,
                "colonne": colonne,
                "exports": len(groupe),
                "detail": "; ".join(
                    f"{periode} : {nature}"
                    for periode, nature in zip(
                        groupe["periode_export"], groupe["nature_dominante"]
                    )
                ),
            }
        )
    return pd.DataFrame(lignes, columns=["table", "colonne", "exports", "detail"])


def points_a_regarder(
    profil: pd.DataFrame,
    tables: dict[str, pd.DataFrame] | None = None,
    profil_par_export: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Points à regarder dans le profil, une ligne par colonne et par point.

    Les points sont classés dans l'ordre de `POINTS`, puis par table et colonne.
    `cellules` est le nombre de cellules concernées (vide pour une nature qui
    change d'un export à l'autre). `detail` ne porte que des formes, des types ou
    des natures, jamais de valeur. Les formes non reconnues demandent les tables,
    les natures par export le profil par période.
    """
    lignes = []

    def ajouter(table, colonne, point, cellules, detail=None):
        lignes.append(
            {
                "table": table,
                "colonne": colonne,
                "point": point,
                "cellules": cellules,
                "detail": detail,
            }
        )

    if tables is not None:
        for ligne in formes_non_reconnues(tables).itertuples(index=False):
            ajouter(
                ligne.table,
                ligne.colonne,
                POINT_FORME_ELARGIE if ligne.lue_par_nettoyage else POINT_FORME,
                ligne.cellules,
                " | ".join(ligne.formes[:FORMES_AFFICHEES]),
            )
    if profil_par_export is not None:
        for ligne in natures_par_export(profil_par_export).itertuples(index=False):
            ajouter(ligne.table, ligne.colonne, POINT_EXPORT, None, ligne.detail)

    for ligne in profil.itertuples(index=False):
        nature = ligne.nature_dominante
        vides = _entier(ligne.nb_none_nan) + _entier(ligne.nb_chaine_vide) + _entier(
            ligne.nb_espaces_seuls
        )
        if nature == "aucune valeur":
            ajouter(ligne.table, ligne.colonne, POINT_TOUJOURS_VIDE, _entier(ligne.nb_lignes))
            continue
        if nature != "texte" and _entier(ligne.nb_hors_nature) > 0:
            ajouter(
                ligne.table, ligne.colonne, POINT_HORS_NATURE, _entier(ligne.nb_hors_nature), nature
            )
        familles = _effectifs_familles(ligne.types_python)
        if len(familles) > 1:
            ajouter(
                ligne.table,
                ligne.colonne,
                POINT_TYPES,
                sum(familles.values()) - max(familles.values()),
                ligne.types_python,
            )
        formes_vides = [
            nom
            for nom, n in (
                ("absente", ligne.nb_none_nan),
                ("chaîne vide", ligne.nb_chaine_vide),
                ("espaces seuls", ligne.nb_espaces_seuls),
            )
            if _entier(n) > 0
        ]
        if len(formes_vides) > 1:
            ajouter(ligne.table, ligne.colonne, POINT_VIDES, vides, ", ".join(formes_vides))
        if _entier(ligne.nb_espaces_bord) > 0:
            ajouter(ligne.table, ligne.colonne, POINT_ESPACES, _entier(ligne.nb_espaces_bord))
        if _entier(ligne.nb_distincts) == 1 and _entier(ligne.nb_lignes) > 1:
            ajouter(ligne.table, ligne.colonne, POINT_CONSTANTE, _entier(ligne.nb_lignes) - vides)

    points = pd.DataFrame(lignes, columns=COLONNES_POINTS)
    points["cellules"] = points["cellules"].astype("Int64")
    rang = {point: i for i, point in enumerate(POINTS)}
    return (
        points.assign(_rang=points["point"].map(rang))
        .sort_values(["_rang", "table", "colonne"], kind="stable")
        .drop(columns="_rang")
        .reset_index(drop=True)
    )


def _masquees(profil: pd.DataFrame) -> set[tuple[str, str]]:
    if "masquee" not in profil.columns:
        raise ValueError(
            "Export refusé : le profil doit être calculé avec masquer_exemples=True"
        )
    return {
        (table, colonne)
        for table, colonne, masquee in zip(profil["table"], profil["colonne"], profil["masquee"])
        if masquee
    }


def _texte(valeur) -> str:
    """Texte d'une cellule de l'export : vide pour une valeur absente, entier sans
    décimale pour un décompte que pandas a rangé en flottant."""
    if valeur is None or (not isinstance(valeur, str) and pd.isna(valeur)):
        return ""
    if isinstance(valeur, float) and valeur.is_integer():
        return str(int(valeur))
    return str(valeur)


def texte_export_profil(
    profil: pd.DataFrame, points: pd.DataFrame, periode_fin: str
) -> str:
    """Texte à transmettre à l'assistant pour la synthèse du profilage.

    Il porte, par colonne, la nature dominante, les parts de la nature et des
    vides, le nombre de valeurs distinctes et de formes, et les formes principales;
    puis les points à regarder. Aucune borne (min, max) n'y figure, ni aucune
    valeur. Les formes d'une colonne sensible sont remplacées par « masquée ».
    Le profil doit avoir été calculé avec masquer_exemples=True.
    """
    masquees = _masquees(profil)
    autres = [c for c in points.columns if c not in COLONNES_POINTS]
    if autres:
        raise ValueError("Export refusé : colonnes inattendues " + ", ".join(map(str, autres)))
    synthese = synthese_par_table(profil)
    lignes = [
        f"Profil du périmètre jusqu'à {periode_fin}",
        f"{len(synthese)} tables, {len(profil)} colonnes",
        "",
        "Tables",
        (
            "table | lignes | colonnes | natures | avec vides | toujours vides "
            "| hors nature | espaces en bord"
        ),
    ]
    for t in synthese.itertuples(index=False):
        lignes.append(
            f"{t.table} | {t.lignes} | {t.colonnes} | {t.natures} | {t.colonnes_avec_vides} "
            f"| {t.colonnes_toujours_vides} | {t.colonnes_hors_nature} | {t.colonnes_espaces_bord}"
        )
    lignes += [
        "",
        "Colonnes",
        "table | colonne | nature | % nature | % vide | distincts | formes | formes principales",
    ]
    for c in profil.itertuples(index=False):
        formes = FORME_MASQUEE if (c.table, c.colonne) in masquees else _texte(c.signatures_top)
        lignes.append(
            " | ".join(
                [
                    c.table,
                    c.colonne,
                    _texte(c.nature_dominante),
                    _texte(c.pct_nature),
                    _texte(c.pct_vide),
                    _texte(c.nb_distincts),
                    _texte(c.nb_signatures),
                    formes,
                ]
            )
        )
    lignes += ["", "Points à regarder", "table | colonne | point | cellules | détail"]
    if points.empty:
        lignes.append("aucun")
    for p in points.itertuples(index=False):
        detail = _texte(p.detail)
        if p.point in (POINT_FORME, POINT_FORME_ELARGIE) and (p.table, p.colonne) in masquees:
            detail = FORME_MASQUEE
        lignes.append(
            " | ".join([p.table, p.colonne, p.point, _texte(p.cellules), detail])
        )
    return "\n".join(lignes)
