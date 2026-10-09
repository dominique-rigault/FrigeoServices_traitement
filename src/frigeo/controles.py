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

Rien n'est corrigé ni écrit : `controler` rend la table des écarts et un bilan.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

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


def _valeur_constatee(valeur) -> str | None:
    """Texte de la valeur constatée, None pour une cellule sans valeur."""
    if valeur is None or (not isinstance(valeur, str) and pd.isna(valeur)):
        return None
    return str(valeur)


def controler(
    tables: dict[str, pd.DataFrame],
    dictionnaire: dict,
    sensibles: dict[str, frozenset[str]] | None = None,
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
            for rang_regle, nom in enumerate(REGLES):
                regle = regles[nom]
                if regle["regle"] in REGLES_SANS_CONTROLE[nom]:
                    continue
                controlees, non_revues, ecarts = _controler_regle(
                    nom, regle, serie, presentes
                )
                commun = {
                    "table": table,
                    "colonne": colonne,
                    "regle": nom,
                    "regle_en_vigueur": regle["regle"],
                    "statut_regle": regle["statut"],
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
                    morceau["_regle"] = rang_regle
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
