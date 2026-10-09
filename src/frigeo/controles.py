"""Contrôles de format et de complétude à partir du dictionnaire (étape 3).

Ce module ne contient rien de propre à un client. Il applique aux données chargées
la règle en vigueur de chaque colonne (champ `regle` du dictionnaire enregistré),
jamais la proposition :

- `obligatoire` : une cellule vide est une anomalie quand la règle vaut
  « obligatoire », une cellule renseignée quand elle vaut « toujours vide »;
- `nature` : une valeur renseignée qui n'est pas de la nature attendue est une
  anomalie (aucun contrôle pour la nature « texte »);
- `valeurs` : pour une liste fermée, chaque valeur renseignée est comparée telle
  quelle à la liste de la colonne;
- `format` : pour des formes fermées, la forme de chaque valeur renseignée (voir
  `profilage.signature`) est comparée aux formes de la colonne.

Une règle « facultatif », « presque toujours vide », « à décider » ou « aucune » ne
donne aucun contrôle. Une cellule vide n'est jugée que par la règle `obligatoire`.

Pour une liste ou un format, trois issues sont possibles :

- admise : valeur ou forme au statut « valide » ou « documenté », ou d'origine
  « liste proposée » et pas encore revue (elle est alors comptée « non revue »);
- anomalie : valeur ou forme au statut « invalide », ou absente de la liste;
- à arbitrer : valeur ou forme connue du dictionnaire mais non décidée.

S'y ajoutent les règles complémentaires, que le dictionnaire ne peut pas déduire des
données et que le métier donne dans `config/controles.yaml` (voir
`charger_regles_complementaires`) : nombre de décimales, bornes, motif, clé de Luhn.
Une forme fixe (code postal, numéro à longueur fixe) n'en fait pas partie : elle
relève de la règle `format` du dictionnaire.

Rien n'est corrigé ni écrit : `controler` rend la table des écarts et un bilan.
"""

from __future__ import annotations

import numbers
import re
from decimal import Decimal
from pathlib import Path

import pandas as pd
import yaml

from . import racine_projet

from .confidentialite import charger_sensibilite, est_sensible, verifier_sensibilite
from .dictionnaire import (
    A_DECIDER,
    CLES_LISTE,
    FORMES_FERMEES,
    LISTE_FERMEE,
    ORIGINE_LISTE,
    REGLE_ECARTEE,
    REGLES,
    STATUT_INITIAL,
    STATUTS_CIBLE,
    _valeurs_renseignees,
    charger_dictionnaire,
    chemin_dictionnaire,
    est_masquee,
    problemes_dictionnaire,
)
from .profilage import COLONNES_LIGNAGE, _NATURES_TEXTE, _interpretations, signature

# Règles en vigueur qui donnent un contrôle, et celles qui n'en donnent aucun.
REGLES_CONTROLEES = {
    "obligatoire": ("obligatoire", "toujours vide"),
    "nature": ("nombre natif", "date native", *_NATURES_TEXTE),
    "valeurs": (LISTE_FERMEE,),
    "format": (FORMES_FERMEES,),
}
REGLES_SANS_CONTROLE = {
    "obligatoire": ("facultatif", "presque toujours vide", A_DECIDER, REGLE_ECARTEE),
    "nature": ("texte", A_DECIDER, REGLE_ECARTEE),
    "valeurs": (REGLE_ECARTEE,),
    "format": (REGLE_ECARTEE,),
}

# Issue d'un écart : une anomalie est certaine au regard de la règle en vigueur, un
# écart à arbitrer attend une décision du métier sur la valeur ou la forme.
ISSUE_ANOMALIE = "anomalie"
ISSUE_A_ARBITRER = "à arbitrer"

# Valeur constatée d'une colonne sensible : elle ne figure jamais dans la table des
# écarts, le lignage permet de la retrouver dans le fichier source.
VALEUR_MASQUEE = "masqué"

COLONNES_LIGNAGE_ECART = ("fichier_source", "feuille_source", "num_ligne_source")
COLONNES_ECARTS = (
    "table",
    *COLONNES_LIGNAGE_ECART,
    "colonne",
    "regle",
    "regle_en_vigueur",
    "statut_regle",
    "issue",
    "constat",
    "valeur",
)
COLONNES_SANS_CONTROLE = ("table", "colonne", "regle", "regle_en_vigueur", "statut_regle")
COLONNES_BILAN = (
    *COLONNES_SANS_CONTROLE,
    "controlees",
    "anomalies",
    "a_arbitrer",
    "non_revues",
)


# Règles complémentaires, données par le métier dans config/controles.yaml : le type
# de règle, puis le constat d'un écart. Leur statut est toujours « documenté ».
REGLES_COMPLEMENTAIRES = {
    "decimales": "trop de décimales",
    "bornes": "hors bornes",
    "motif": "hors motif",
    "cle_luhn": "clé invalide",
}
STATUT_COMPLEMENTAIRE = "documenté"
CLE_REGLES_COMPLEMENTAIRES = "regles"
# Tolérance relative pour les décimales d'un nombre natif, dont le calcul par le
# tableur laisse parfois une imprécision (181.45000000000002).
TOLERANCE_DECIMALES = 1e-9
_MOTIF_NOMBRE = re.compile(r"-?\d+(?:[.,]\d+)?")


def chemin_regles_complementaires() -> Path:
    """Emplacement par défaut des règles complémentaires : config/controles.yaml."""
    return racine_projet() / "config" / "controles.yaml"


def _est_nombre(valeur) -> bool:
    return isinstance(valeur, numbers.Real) and not isinstance(valeur, bool)


def _probleme_parametre(type_regle: str, parametre) -> str | None:
    """Problème du paramètre d'une règle complémentaire, None s'il est correct."""
    if type_regle == "decimales":
        if isinstance(parametre, bool) or not isinstance(parametre, int) or parametre < 0:
            return "un nombre entier de décimales, positif ou nul, est attendu"
    elif type_regle == "bornes":
        if (
            not isinstance(parametre, dict)
            or not parametre
            or set(parametre) - {"min", "max"}
            or not all(_est_nombre(borne) for borne in parametre.values())
        ):
            return "un minimum (min), un maximum (max) ou les deux sont attendus, en nombres"
        if len(parametre) == 2 and parametre["min"] > parametre["max"]:
            return "le minimum dépasse le maximum"
    elif type_regle == "motif":
        if not isinstance(parametre, str) or parametre == "":
            return "une expression régulière entre guillemets est attendue"
        try:
            re.compile(parametre)
        except re.error as erreur:
            return f"expression régulière invalide ({erreur})"
    elif parametre is not True:
        return "la valeur attendue est true (pour ne plus contrôler, retirer la ligne)"
    return None


def problemes_regles_complementaires(regles) -> list[str]:
    """Problèmes de structure des règles complémentaires, tous listés en une fois."""
    if not isinstance(regles, dict):
        return ["un dictionnaire de tables est attendu"]
    problemes = []
    for table, colonnes in regles.items():
        if not isinstance(colonnes, dict) or not colonnes:
            problemes.append(f"{table} : un dictionnaire de colonnes est attendu")
            continue
        for colonne, types in colonnes.items():
            ou = f"{table}.{colonne}"
            if not isinstance(types, dict) or not types:
                problemes.append(f"{ou} : au moins une règle est attendue")
                continue
            for type_regle, parametre in types.items():
                if type_regle not in REGLES_COMPLEMENTAIRES:
                    problemes.append(
                        f"{ou} : règle inconnue {type_regle!r} (règles possibles : "
                        f"{', '.join(REGLES_COMPLEMENTAIRES)})"
                    )
                    continue
                probleme = _probleme_parametre(type_regle, parametre)
                if probleme:
                    problemes.append(f"{ou}, règle {type_regle} : {probleme}")
    return problemes


def charger_regles_complementaires(chemin: str | Path | None = None) -> dict:
    """Règles complémentaires de config/controles.yaml, par table puis par colonne.

    Le fichier est écrit à la main, d'après ce que dit le métier. Sous la clé
    `regles`, chaque colonne porte une ou plusieurs règles :

    - `decimales: 2` : au plus deux décimales significatives;
    - `bornes: {min: 0, max: 15}` : valeur comprise entre les bornes, incluses (une
      seule borne est possible);
    - `motif: "..."` : la valeur entière correspond à l'expression régulière;
    - `cle_luhn: true` : la clé de contrôle de Luhn est valide.

    Un fichier absent ne donne aucune règle. Un fichier mal formé est refusé, tous
    les problèmes étant listés en une fois.
    """
    chemin = Path(chemin) if chemin is not None else chemin_regles_complementaires()
    if not chemin.is_file():
        return {}
    with open(chemin, encoding="utf-8") as flux:
        contenu = yaml.safe_load(flux)
    if not isinstance(contenu, dict) or set(contenu) != {CLE_REGLES_COMPLEMENTAIRES}:
        raise ValueError(
            f"Règles complémentaires invalides ({chemin}) : la seule clé attendue est "
            f"« {CLE_REGLES_COMPLEMENTAIRES} »"
        )
    regles = contenu[CLE_REGLES_COMPLEMENTAIRES]
    if regles is None:
        return {}
    problemes = problemes_regles_complementaires(regles)
    if problemes:
        raise ValueError(
            f"Règles complémentaires invalides ({chemin})\n  " + "\n  ".join(problemes)
        )
    return regles


def charger_dictionnaire_enregistre(chemin: str | Path | None = None) -> dict:
    """Tables du dictionnaire enregistré, avec un message clair s'il n'existe pas.

    Le dictionnaire est hors du dépôt : un clone neuf n'en a pas. Il est généré puis
    revu par le métier dans le notebook 02c_dictionnaire.
    """
    chemin = Path(chemin) if chemin is not None else chemin_dictionnaire()
    if not chemin.exists():
        raise FileNotFoundError(
            f"Dictionnaire introuvable ({chemin}) : les contrôles appliquent ses "
            "règles. Il est généré puis revu dans le notebook 02c_dictionnaire, à "
            "exécuter d'abord."
        )
    return charger_dictionnaire(chemin)


def _colonnes_de_donnees(donnees: pd.DataFrame) -> list[str]:
    return [colonne for colonne in donnees.columns if colonne not in COLONNES_LIGNAGE]


def _problemes_de_correspondance(tables: dict, dictionnaire: dict) -> list[str]:
    """Tables et colonnes présentes d'un seul côté, données ou dictionnaire."""
    problemes = []
    for table in tables:
        if table not in dictionnaire:
            problemes.append(f"table {table} absente du dictionnaire")
    for table, colonnes in dictionnaire.items():
        if table not in tables:
            problemes.append(f"table {table} absente des données chargées")
            continue
        presentes = _colonnes_de_donnees(tables[table])
        for colonne in presentes:
            if colonne not in colonnes:
                problemes.append(f"colonne {table}.{colonne} absente du dictionnaire")
        for colonne in colonnes:
            if colonne not in presentes:
                problemes.append(f"colonne {table}.{colonne} absente des données chargées")
    return problemes


def _problemes_de_regles(dictionnaire: dict) -> list[str]:
    """Règles en vigueur que les contrôles ne connaissent pas."""
    problemes = []
    for table, colonnes in dictionnaire.items():
        for colonne, regles in colonnes.items():
            for nom in REGLES:
                en_vigueur = regles[nom]["regle"]
                if en_vigueur not in (*REGLES_CONTROLEES[nom], *REGLES_SANS_CONTROLE[nom]):
                    problemes.append(
                        f"{table}.{colonne}, règle {nom} : règle en vigueur "
                        f"{en_vigueur!r} inconnue des contrôles"
                    )
    return problemes


def regles_sans_controle(dictionnaire: dict) -> pd.DataFrame:
    """Règles du dictionnaire qui ne donnent aucun contrôle, une ligne par règle.

    Les règles « à décider » s'y trouvent : tant que le métier n'a pas tranché, la
    colonne n'est pas contrôlée sur ce point, ce qui ne doit pas passer inaperçu.
    """
    lignes = [
        {
            "table": table,
            "colonne": colonne,
            "regle": nom,
            "regle_en_vigueur": regles[nom]["regle"],
            "statut_regle": regles[nom]["statut"],
        }
        for table, colonnes in dictionnaire.items()
        for colonne, regles in colonnes.items()
        for nom in REGLES
        if regles[nom]["regle"] in REGLES_SANS_CONTROLE[nom]
    ]
    return pd.DataFrame(lignes, columns=list(COLONNES_SANS_CONTROLE))


def _issue_element(element: dict | None) -> str | None:
    """Issue d'une valeur ou d'une forme d'après son élément dans le dictionnaire.

    Rend « invalide », « hors liste » ou « à arbitrer » pour un écart, « non revue »
    pour un élément admis mais pas encore revu, None pour un élément admis.
    """
    if element is None:
        return "hors liste"
    if element["statut"] in STATUTS_CIBLE:
        return None
    if element["statut"] != STATUT_INITIAL:
        return "invalide"
    return "non revue" if element["origine"] == ORIGINE_LISTE else "à arbitrer"


def _controler_regle(nom: str, regle: dict, serie: pd.Series, presentes: pd.Series):
    """Contrôle d'une règle sur une colonne dont l'index est la position des lignes.

    Rend le nombre de cellules contrôlées, le nombre de cellules admises mais non
    revues, et les écarts : une liste de (positions, constat, issue).
    """
    en_vigueur = regle["regle"]
    if nom == "obligatoire":
        if en_vigueur == "obligatoire":
            ecarts = [(serie.index.difference(presentes.index), "vide", ISSUE_ANOMALIE)]
        else:
            ecarts = [(presentes.index, "renseignée", ISSUE_ANOMALIE)]
        return len(serie), 0, ecarts
    if presentes.empty:
        return 0, 0, []
    if nom == "nature":
        conformes = _interpretations(presentes)[en_vigueur].index
        hors_nature = presentes.index.difference(conformes)
        return len(presentes), 0, [(hors_nature, "hors nature", ISSUE_ANOMALIE)]

    mot = CLES_LISTE[nom]
    connus = {element[mot]: element for element in regle["liste"]}
    textes = presentes.astype(str)
    if nom == "format":
        textes = textes.map({texte: signature(texte) for texte in textes.unique()})
    issues = textes.map(
        {repere: _issue_element(connus.get(repere)) for repere in textes.unique()}
    )
    ecarts = [
        (issues.index[(issues == "invalide").to_numpy()], f"{mot} invalide", ISSUE_ANOMALIE),
        (
            issues.index[(issues == "hors liste").to_numpy()],
            f"{mot} hors liste",
            ISSUE_ANOMALIE,
        ),
        (
            issues.index[(issues == "à arbitrer").to_numpy()],
            f"{mot} à arbitrer",
            ISSUE_A_ARBITRER,
        ),
    ]
    return len(presentes), int((issues == "non revue").sum()), ecarts


def _nombre(valeur):
    """Nombre porté par une valeur native ou par un texte, None s'il n'y en a pas.

    Un texte est lu avec une virgule ou un point décimal, sans séparateur de milliers.
    """
    if _est_nombre(valeur):
        return valeur
    if isinstance(valeur, str) and _MOTIF_NOMBRE.fullmatch(valeur):
        return Decimal(valeur.replace(",", "."))
    return None


def _trop_de_decimales(nombre, maximum: int) -> bool:
    if isinstance(nombre, Decimal):
        return max(0, -nombre.normalize().as_tuple().exponent) > maximum
    ecart = abs(nombre - round(nombre, maximum))
    return bool(ecart > TOLERANCE_DECIMALES * max(1, abs(nombre)))


def _cle_luhn_valide(chiffres: str) -> bool:
    total = 0
    for rang, chiffre in enumerate(reversed(chiffres)):
        produit = int(chiffre) * (2 if rang % 2 else 1)
        total += produit - 9 if produit > 9 else produit
    return total % 10 == 0


def _verdict_complementaire(type_regle: str, parametre, valeur) -> bool | None:
    """Vrai si la valeur est en écart, faux sinon, None si elle n'est pas évaluable.

    Pour les décimales et les bornes, une valeur qui n'est pas un nombre n'est pas
    évaluable : c'est la règle `nature` qui la signale. La clé de Luhn ne se calcule
    que sur une valeur faite de chiffres.
    """
    if type_regle in ("decimales", "bornes"):
        nombre = _nombre(valeur)
        if nombre is None:
            return None
        if type_regle == "decimales":
            return _trop_de_decimales(nombre, parametre)
        return bool(
            ("min" in parametre and nombre < parametre["min"])
            or ("max" in parametre and nombre > parametre["max"])
        )
    texte = str(valeur)
    if type_regle == "motif":
        return re.fullmatch(parametre, texte) is None
    if not (texte.isascii() and texte.isdigit()):
        return None
    return not _cle_luhn_valide(texte)


def _parametre_en_texte(type_regle: str, parametre) -> str:
    """Texte du paramètre d'une règle complémentaire, pour la table des écarts."""
    if type_regle == "bornes":
        if len(parametre) == 2:
            return f"{parametre['min']} à {parametre['max']}"
        borne, valeur = next(iter(parametre.items()))
        return f"{borne} {valeur}"
    return "oui" if type_regle == "cle_luhn" else str(parametre)


def _controler_complementaire(type_regle: str, parametre, presentes: pd.Series):
    """Contrôle d'une règle complémentaire, rendu comme `_controler_regle`."""
    verdicts = [_verdict_complementaire(type_regle, parametre, v) for v in presentes]
    en_ecart = presentes.index[[verdict is True for verdict in verdicts]]
    evaluables = sum(verdict is not None for verdict in verdicts)
    return evaluables, 0, [(en_ecart, REGLES_COMPLEMENTAIRES[type_regle], ISSUE_ANOMALIE)]


def _problemes_de_complementaires(tables: dict, complementaires: dict) -> list[str]:
    """Tables et colonnes des règles complémentaires absentes des données chargées."""
    problemes = []
    for table, colonnes in complementaires.items():
        if table not in tables:
            problemes.append(f"table {table} absente des données chargées")
            continue
        presentes = _colonnes_de_donnees(tables[table])
        for colonne in colonnes:
            if colonne not in presentes:
                problemes.append(f"colonne {table}.{colonne} absente des données chargées")
    return problemes


def _valeur_constatee(valeur) -> str | None:
    """Texte de la valeur constatée, None pour une cellule sans valeur."""
    if valeur is None or (not isinstance(valeur, str) and pd.isna(valeur)):
        return None
    return str(valeur)


def controler(
    tables: dict[str, pd.DataFrame],
    dictionnaire: dict,
    sensibles: dict[str, frozenset[str]] | None = None,
    complementaires: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Applique les règles en vigueur du dictionnaire et rend les écarts et le bilan.

    `dictionnaire` est le dictionnaire enregistré (voir
    `charger_dictionnaire_enregistre`). Il doit décrire exactement les tables et les
    colonnes chargées : sinon rien n'est contrôlé et tous les écarts de structure
    sont listés, le dictionnaire étant à régénérer.

    Table des écarts (`COLONNES_ECARTS`) : une ligne par cellule et par règle en
    écart, avec le lignage de la ligne source, la règle en vigueur, son statut (un
    écart à une règle au statut « observé » reste à confirmer par le métier),
    l'issue (« anomalie » ou « à arbitrer »), le constat et la valeur constatée. Les
    lignes d'une même cellule se suivent : la table est triée par table, fichier,
    feuille, numéro de ligne, puis colonne et règle. La valeur constatée est le
    texte de la valeur chargée; pour une colonne sensible elle est remplacée par
    « masqué ». Les cellules admises n'y figurent pas.

    Bilan (`COLONNES_BILAN`) : une ligne par règle contrôlée, avec les nombres de
    cellules contrôlées, d'anomalies, d'écarts à arbitrer et de cellules admises mais
    non revues. Les règles sans contrôle sont rendues par `regles_sans_controle`.

    Règles complémentaires (config/controles.yaml par défaut, voir
    `charger_regles_complementaires`) : elles sont contrôlées après les quatre règles
    du dictionnaire, dans l'ordre décimales, bornes, motif, clé de Luhn. La colonne
    `regle` porte leur type, `regle_en_vigueur` leur paramètre et `statut_regle` vaut
    « documenté », puisque c'est le métier qui les donne. Seules les valeurs
    évaluables sont comptées comme contrôlées. Une table ou une colonne inconnue des
    données arrête le traitement (faute de frappe probable).

    La classification de sensibilité (config/sensibilite.yaml par défaut) est
    vérifiée avant le calcul. Une colonne est aussi tenue pour sensible quand le
    dictionnaire la marque comme telle. Les arguments ne sont pas modifiés.
    """
    if sensibles is None:
        sensibles = charger_sensibilite()
    problemes = verifier_sensibilite(tables, sensibles)
    if problemes:
        raise RuntimeError(
            "Classification de sensibilité incohérente\n  " + "\n  ".join(problemes)
        )
    if complementaires is None:
        complementaires = charger_regles_complementaires()
    problemes = problemes_regles_complementaires(complementaires)
    if not problemes:
        problemes = _problemes_de_complementaires(tables, complementaires)
    if problemes:
        raise ValueError("Règles complémentaires invalides\n  " + "\n  ".join(problemes))
    problemes = problemes_dictionnaire(dictionnaire)
    if problemes:
        raise ValueError("Dictionnaire invalide\n  " + "\n  ".join(problemes))
    problemes = _problemes_de_correspondance(tables, dictionnaire)
    if problemes:
        raise ValueError(
            "Le dictionnaire ne décrit pas les données chargées : il est à régénérer "
            "(notebook 02c_dictionnaire)\n  " + "\n  ".join(problemes)
        )
    problemes = _problemes_de_regles(dictionnaire)
    if problemes:
        raise ValueError("Règles inconnues des contrôles\n  " + "\n  ".join(problemes))

    rang_regles = {nom: rang for rang, nom in enumerate((*REGLES, *REGLES_COMPLEMENTAIRES))}
    bilan, morceaux = [], []
    for rang_table, (table, colonnes) in enumerate(dictionnaire.items()):
        donnees = tables[table].reset_index(drop=True)
        rang_colonnes = {colonne: rang for rang, colonne in enumerate(donnees.columns)}
        for colonne, regles in colonnes.items():
            serie = donnees[colonne]
            presentes = _valeurs_renseignees(serie)
            masquee = (
                est_sensible(sensibles, table, colonne)
                or est_masquee(regles["valeurs"])
                or est_masquee(regles["format"])
            )
            a_faire = [
                (
                    nom,
                    regles[nom]["regle"],
                    regles[nom]["statut"],
                    _controler_regle(nom, regles[nom], serie, presentes),
                )
                for nom in REGLES
                if regles[nom]["regle"] not in REGLES_SANS_CONTROLE[nom]
            ]
            en_plus = complementaires.get(table, {}).get(colonne, {})
            a_faire += [
                (
                    type_regle,
                    _parametre_en_texte(type_regle, en_plus[type_regle]),
                    STATUT_COMPLEMENTAIRE,
                    _controler_complementaire(type_regle, en_plus[type_regle], presentes),
                )
                for type_regle in REGLES_COMPLEMENTAIRES
                if type_regle in en_plus
            ]
            for nom, en_vigueur, statut, (controlees, non_revues, ecarts) in a_faire:
                commun = {
                    "table": table,
                    "colonne": colonne,
                    "regle": nom,
                    "regle_en_vigueur": en_vigueur,
                    "statut_regle": statut,
                }
                comptes = {ISSUE_ANOMALIE: 0, ISSUE_A_ARBITRER: 0}
                for positions, constat, issue in ecarts:
                    if len(positions) == 0:
                        continue
                    comptes[issue] += len(positions)
                    valeurs = (
                        [VALEUR_MASQUEE] * len(positions)
                        if masquee
                        else [_valeur_constatee(v) for v in serie.loc[positions]]
                    )
                    morceau = pd.DataFrame(
                        {
                            "_position": positions,
                            **commun,
                            "issue": issue,
                            "constat": constat,
                            "valeur": pd.Series(valeurs, dtype=object).to_numpy(),
                        }
                    )
                    for lignage in COLONNES_LIGNAGE_ECART:
                        morceau[lignage] = (
                            donnees[lignage].loc[positions].to_numpy()
                            if lignage in donnees.columns
                            else None
                        )
                    morceau["_table"] = rang_table
                    morceau["_colonne"] = rang_colonnes[colonne]
                    morceau["_regle"] = rang_regles[nom]
                    morceaux.append(morceau)
                bilan.append(
                    {
                        **commun,
                        "controlees": controlees,
                        "anomalies": comptes[ISSUE_ANOMALIE],
                        "a_arbitrer": comptes[ISSUE_A_ARBITRER],
                        "non_revues": non_revues,
                    }
                )

    if morceaux:
        ecarts = pd.concat(morceaux, ignore_index=True).sort_values(
            ["_table", *COLONNES_LIGNAGE_ECART, "_position", "_colonne", "_regle"],
            kind="stable",
            na_position="first",
        )
        ecarts = ecarts[list(COLONNES_ECARTS)].reset_index(drop=True)
    else:
        ecarts = pd.DataFrame(columns=list(COLONNES_ECARTS))
    return ecarts, pd.DataFrame(bilan, columns=list(COLONNES_BILAN))
