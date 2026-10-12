"""Détection des doublons (étape 3).

Ce module ne contient rien de propre à un client. Ce que seul le métier sait est
déclaré à la main dans `config/controles.yaml`, sous la clé `doublons` (voir
`charger_declarations_doublons`) : la clé de chaque table, les colonnes dont les
valeurs doivent être uniques, et celles qui le sont en principe.

Trois constats, à la maille de la ligne :

- doublon exact : des lignes identiques sur toutes leurs colonnes, sans aucune
  déclaration; c'est une anomalie;
- valeur en double : une même valeur dans une colonne, ou une même combinaison
  dans un groupe de colonnes, déclarée unique, sur des lignes qui ne sont pas
  identiques. C'est une anomalie pour la clé et pour les colonnes `unique`, un
  écart à arbitrer pour les colonnes `presume_unique`;
- identique hors clé : des lignes identiques sur toutes les colonnes sauf la clé,
  avec des clés différentes (un enregistrement ressaisi sous un autre
  identifiant, ou deux enregistrements réellement pareils). L'outil ne sait pas
  les distinguer : c'est toujours un écart à arbitrer, et le métier peut écarter
  ce constat pour une table.

Les valeurs sont comparées après normalisation des textes (casse, accents, espaces
en bord et répétées). Un groupe dont les valeurs ne sont pas strictement égales
porte la mention « après normalisation ». Une valeur vide n'est jamais comparée.

Chaque groupe porte sa portée : « même fichier », ou « entre exports » quand ses
lignes viennent de fichiers sources différents.

Rien n'est corrigé, supprimé ni écrit : `detecter_doublons` rend la table des
doublons et un bilan.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pandas as pd

from .confidentialite import charger_sensibilite, est_sensible, verifier_sensibilite
from .controles import (
    CLE_DOUBLONS,
    COLONNES_LIGNAGE_ECART,
    ISSUE_A_ARBITRER,
    ISSUE_ANOMALIE,
    VALEUR_MASQUEE,
    _colonnes_de_donnees,
    lire_fichier_controles,
)

CONSTAT_EXACT = "doublon exact"
CONSTAT_VALEUR = "valeur en double"
CONSTAT_HORS_CLE = "identique hors clé"

PORTEE_MEME_FICHIER = "même fichier"
PORTEE_ENTRE_EXPORTS = "entre exports"

COMPARAISON_TELLE_QUELLE = "telle quelle"
COMPARAISON_NORMALISEE = "après normalisation"

# Texte de la colonne `colonnes` pour un doublon exact, et séparateur des valeurs
# d'un groupe de colonnes dans les colonnes `cle` et `valeur`.
TOUTES_COLONNES = "toutes"
SEPARATEUR = " | "

# Clés admises dans la déclaration d'une table.
CLES_DECLARATION = ("cle", "unique", "presume_unique", "identique_hors_cle")

COLONNES_DOUBLONS = (
    "table",
    *COLONNES_LIGNAGE_ECART,
    "constat",
    "colonnes",
    "issue",
    "portee",
    "comparaison",
    "groupe",
    "taille_groupe",
    "cle",
    "valeur",
)
COLONNES_BILAN_DOUBLONS = (
    "table",
    "constat",
    "colonnes",
    "issue",
    "comparees",
    "groupes",
    "lignes",
    "en_surnombre",
    "entre_exports",
    "apres_normalisation",
)
COLONNES_NON_CHERCHES = ("table", "constat", "raison")


def _probleme_groupe(groupe) -> str | None:
    """Problème d'un groupe de colonnes déclaré, None s'il est correct."""
    if (
        not isinstance(groupe, list)
        or not groupe
        or not all(isinstance(colonne, str) and colonne for colonne in groupe)
    ):
        return "une liste de noms de colonnes est attendue, par exemple [siret]"
    if len(set(groupe)) != len(groupe):
        return "une colonne est citée deux fois"
    return None


def problemes_declarations_doublons(declarations) -> list[str]:
    """Problèmes de structure des déclarations de doublons, tous listés en une fois."""
    if not isinstance(declarations, dict):
        return ["un dictionnaire de tables est attendu"]
    problemes = []
    for table, declaration in declarations.items():
        if not isinstance(declaration, dict) or not declaration:
            problemes.append(
                f"{table} : une déclaration est attendue (cle, unique, presume_unique)"
            )
            continue
        for cle in declaration:
            if cle not in CLES_DECLARATION:
                problemes.append(
                    f"{table} : clé inconnue {cle!r} (clés possibles : "
                    f"{', '.join(CLES_DECLARATION)})"
                )
        groupes = []
        if "cle" in declaration:
            probleme = _probleme_groupe(declaration["cle"])
            if probleme:
                problemes.append(f"{table}, cle : {probleme}")
            else:
                groupes.append(("cle", declaration["cle"]))
        for nom in ("unique", "presume_unique"):
            if nom not in declaration:
                continue
            liste = declaration[nom]
            if not isinstance(liste, list) or not liste:
                problemes.append(
                    f"{table}, {nom} : une liste de groupes de colonnes est attendue, "
                    "par exemple [[siret]]"
                )
                continue
            for groupe in liste:
                probleme = _probleme_groupe(groupe)
                if probleme:
                    problemes.append(f"{table}, {nom} : {probleme}")
                else:
                    groupes.append((nom, groupe))
        if not any(nom in declaration for nom in ("cle", "unique", "presume_unique")):
            problemes.append(f"{table} : rien n'est déclaré (cle, unique ou presume_unique)")
        vus = {}
        for nom, groupe in groupes:
            repere = frozenset(groupe)
            if repere in vus:
                problemes.append(
                    f"{table} : les colonnes {', '.join(groupe)} sont déclarées deux fois "
                    f"({vus[repere]} et {nom})"
                )
            vus.setdefault(repere, nom)
        if "identique_hors_cle" in declaration:
            if declaration["identique_hors_cle"] is not False:
                problemes.append(
                    f"{table}, identique_hors_cle : la valeur attendue est false (pour "
                    "garder ce constat, retirer la ligne)"
                )
            elif "cle" not in declaration:
                problemes.append(
                    f"{table}, identique_hors_cle : sans clé déclarée, il n'y a rien à écarter"
                )
    return problemes


def charger_declarations_doublons(chemin: str | Path | None = None) -> dict:
    """Déclarations de doublons de config/controles.yaml, par table.

    Le fichier est écrit à la main, d'après ce que dit le métier. Sous la clé
    `doublons`, chaque table porte :

    - `cle: [colonne, ...]` : l'identifiant d'une ligne, une ou plusieurs colonnes;
    - `unique: [[colonne, ...], ...]` : d'autres colonnes, ou groupes de colonnes,
      dont les valeurs ne doivent pas se répéter;
    - `presume_unique: [[colonne, ...], ...]` : des colonnes en principe uniques,
      dont une répétition est à arbitrer par le métier;
    - `identique_hors_cle: false` : pour ne pas chercher dans cette table les
      lignes identiques hors clé (deux enregistrements peuvent y être pareils).

    Un fichier absent, ou sans clé `doublons`, ne donne aucune déclaration : seuls
    les doublons exacts sont alors cherchés. Un fichier mal formé est refusé, tous
    les problèmes étant listés en une fois.
    """
    declarations = lire_fichier_controles(chemin).get(CLE_DOUBLONS)
    if declarations is None:
        return {}
    problemes = problemes_declarations_doublons(declarations)
    if problemes:
        raise ValueError("Déclarations de doublons invalides\n  " + "\n  ".join(problemes))
    return declarations


def _groupes_declares(declaration: dict) -> list[tuple[str, list[str]]]:
    """Groupes de colonnes déclarés uniques, avec l'issue d'une répétition."""
    groupes = []
    if "cle" in declaration:
        groupes.append((ISSUE_ANOMALIE, declaration["cle"]))
    groupes += [(ISSUE_ANOMALIE, groupe) for groupe in declaration.get("unique", [])]
    groupes += [(ISSUE_A_ARBITRER, groupe) for groupe in declaration.get("presume_unique", [])]
    return groupes


def _problemes_de_presence(tables: dict, declarations: dict) -> list[str]:
    """Tables et colonnes déclarées mais absentes des données chargées."""
    problemes = []
    for table, declaration in declarations.items():
        if table not in tables:
            problemes.append(f"table {table} absente des données chargées")
            continue
        presentes = _colonnes_de_donnees(tables[table])
        for _, groupe in _groupes_declares(declaration):
            for colonne in groupe:
                message = f"colonne {table}.{colonne} absente des données chargées"
                if colonne not in presentes and message not in problemes:
                    problemes.append(message)
    return problemes


def doublons_non_cherches(tables: dict[str, pd.DataFrame], declarations: dict) -> pd.DataFrame:
    """Constats qui ne sont pas cherchés dans une table, avec la raison.

    Une table sans clé déclarée n'a que le contrôle des doublons exacts et de ses
    éventuelles colonnes uniques : cela ne doit pas passer inaperçu.
    """
    lignes = []
    for table, donnees in tables.items():
        declaration = declarations.get(table, {})
        if "cle" not in declaration:
            raison = "aucune clé déclarée"
            lignes.append({"table": table, "constat": CONSTAT_VALEUR, "raison": raison})
        elif declaration.get("identique_hors_cle") is False:
            raison = "écarté par le métier"
        elif not [c for c in _colonnes_de_donnees(donnees) if c not in declaration["cle"]]:
            raison = "aucune colonne hors clé"
        else:
            continue
        lignes.append({"table": table, "constat": CONSTAT_HORS_CLE, "raison": raison})
    return pd.DataFrame(lignes, columns=list(COLONNES_NON_CHERCHES))


def _texte(valeur) -> str:
    """Texte de la valeur chargée, vide pour une cellule sans valeur."""
    if valeur is None or (not isinstance(valeur, str) and pd.isna(valeur)):
        return ""
    return str(valeur)


def normaliser(texte: str) -> str:
    """Texte sans accent, sans casse, sans espace en bord ni espace répétée."""
    decompose = unicodedata.normalize("NFKD", texte)
    sans_accent = "".join(c for c in decompose if not unicodedata.combining(c))
    return " ".join(sans_accent.casefold().split())


def _reperes(textes: pd.DataFrame, colonnes: list[str]) -> pd.Series:
    """Numéro commun aux lignes qui portent les mêmes textes dans ces colonnes."""
    return textes.groupby(colonnes, sort=False).ngroup()


def _groupes(reperes, retenues, differents, bruts, fichiers) -> pd.DataFrame:
    """Lignes en doublon parmi les lignes retenues, avec leur groupe.

    Un groupe réunit au moins deux lignes de même repère. Quand `differents` est
    donné, il doit en outre y prendre au moins deux valeurs.
    """
    lignes = pd.DataFrame({"repere": reperes, "brut": bruts, "fichier": fichiers})
    if differents is not None:
        lignes["different"] = differents
    lignes = lignes[retenues.to_numpy()]
    par_groupe = lignes.groupby("repere", sort=False)
    garder = par_groupe["repere"].transform("size") > 1
    if differents is not None:
        garder &= par_groupe["different"].transform("nunique") > 1
    lignes = lignes[garder.to_numpy()]
    par_groupe = lignes.groupby("repere", sort=False)
    return pd.DataFrame(
        {
            "groupe": par_groupe.ngroup() + 1,
            "taille_groupe": par_groupe["repere"].transform("size"),
            "entre_exports": par_groupe["fichier"].transform("nunique") > 1,
            "normalisee": par_groupe["brut"].transform("nunique") > 1,
        },
        index=lignes.index,
    )


def detecter_doublons(
    tables: dict[str, pd.DataFrame],
    declarations: dict | None = None,
    sensibles: dict[str, frozenset[str]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cherche les doublons et rend la table des doublons et le bilan.

    Les déclarations (config/controles.yaml par défaut, voir
    `charger_declarations_doublons`) disent, par table, la clé et les colonnes
    uniques ou en principe uniques. Une table sans déclaration n'a que le contrôle
    des doublons exacts (voir `doublons_non_cherches`). Une table ou une colonne
    déclarée mais inconnue des données arrête le traitement (faute de frappe
    probable).

    Table des doublons (`COLONNES_DOUBLONS`) : une ligne par ligne source et par
    groupe où elle figure, avec son lignage, le constat, les colonnes comparées,
    l'issue (« anomalie » ou « à arbitrer »), la portée du groupe, la comparaison
    (« telle quelle », ou « après normalisation » quand les valeurs du groupe ne
    sont pas strictement égales), le numéro du groupe dans son contrôle et sa
    taille. `cle` porte la clé de la ligne quand une clé est déclarée, `valeur` la
    valeur en double. L'une et l'autre sont remplacées par « masqué » dès qu'une
    de leurs colonnes est sensible : le lignage permet de retrouver la ligne. Une
    même ligne peut figurer sous plusieurs constats. Les lignes d'un même groupe se
    suivent.

    Bilan (`COLONNES_BILAN_DOUBLONS`) : une ligne par contrôle, avec le nombre de
    lignes comparées, de groupes, de lignes en doublon, de lignes en surnombre (les
    lignes des groupes moins une par groupe), de groupes entre exports et de
    groupes trouvés après normalisation.

    Ne sont pas comparées : pour un doublon exact, une ligne entièrement vide; pour
    une valeur en double, une ligne dont l'une des colonnes du groupe est vide;
    pour les lignes identiques hors clé, une ligne vide hors de sa clé.

    La classification de sensibilité (config/sensibilite.yaml par défaut) est
    vérifiée avant le calcul. Les arguments ne sont pas modifiés.
    """
    if sensibles is None:
        sensibles = charger_sensibilite()
    problemes = verifier_sensibilite(tables, sensibles)
    if problemes:
        raise RuntimeError(
            "Classification de sensibilité incohérente\n  " + "\n  ".join(problemes)
        )
    if declarations is None:
        declarations = charger_declarations_doublons()
    problemes = problemes_declarations_doublons(declarations)
    if not problemes:
        problemes = _problemes_de_presence(tables, declarations)
    if problemes:
        raise ValueError("Déclarations de doublons invalides\n  " + "\n  ".join(problemes))

    bilan, morceaux = [], []
    for table, origine in tables.items():
        donnees = origine.reset_index(drop=True)
        metier = _colonnes_de_donnees(donnees)
        if not metier:
            continue
        bruts = pd.DataFrame({c: donnees[c].map(_texte) for c in metier}, index=donnees.index)
        normes = pd.DataFrame(
            {c: bruts[c].map({t: normaliser(t) for t in bruts[c].unique()}) for c in metier},
            index=donnees.index,
        )
        renseignees = normes != ""
        fichiers = (
            donnees["fichier_source"].map(_texte)
            if "fichier_source" in donnees.columns
            else pd.Series("", index=donnees.index)
        )
        declaration = declarations.get(table, {})
        cle = declaration.get("cle", [])
        hors_cle = [c for c in metier if c not in cle]
        ligne_normee = _reperes(normes, metier)

        def masque(colonnes):
            return any(est_sensible(sensibles, table, c) for c in colonnes)

        def en_texte(colonnes):
            if masque(colonnes):
                return pd.Series(VALEUR_MASQUEE, index=donnees.index, dtype=object)
            return bruts[colonnes].agg(SEPARATEUR.join, axis=1).astype(object)

        cles = en_texte(cle) if cle else pd.Series(None, index=donnees.index, dtype=object)

        # Contrôles de la table : constat, colonnes affichées, issue, colonnes
        # comparées, lignes retenues, repère qui doit différer, valeur affichée.
        a_faire = [
            (
                CONSTAT_EXACT,
                TOUTES_COLONNES,
                ISSUE_ANOMALIE,
                metier,
                renseignees.any(axis=1),
                None,
                None,
            )
        ]
        for issue, groupe in _groupes_declares(declaration):
            a_faire.append(
                (
                    CONSTAT_VALEUR,
                    ", ".join(groupe),
                    issue,
                    groupe,
                    renseignees[groupe].all(axis=1),
                    ligne_normee,
                    en_texte(groupe),
                )
            )
        if cle and hors_cle and declaration.get("identique_hors_cle") is not False:
            a_faire.append(
                (
                    CONSTAT_HORS_CLE,
                    "toutes sauf " + ", ".join(cle),
                    ISSUE_A_ARBITRER,
                    hors_cle,
                    renseignees[hors_cle].any(axis=1),
                    _reperes(normes, cle),
                    None,
                )
            )

        for constat, affichees, issue, comparees, retenues, differents, valeurs in a_faire:
            groupes = _groupes(
                _reperes(normes, comparees),
                retenues,
                differents,
                _reperes(bruts, comparees),
                fichiers,
            )
            premiers = groupes.drop_duplicates("groupe")
            bilan.append(
                {
                    "table": table,
                    "constat": constat,
                    "colonnes": affichees,
                    "issue": issue,
                    "comparees": int(retenues.sum()),
                    "groupes": len(premiers),
                    "lignes": len(groupes),
                    "en_surnombre": len(groupes) - len(premiers),
                    "entre_exports": int(premiers["entre_exports"].sum()),
                    "apres_normalisation": int(premiers["normalisee"].sum()),
                }
            )
            if groupes.empty:
                continue
            groupes = groupes.sort_values("groupe", kind="stable")
            positions = groupes.index
            morceau = pd.DataFrame(
                {
                    "table": table,
                    "constat": constat,
                    "colonnes": affichees,
                    "issue": issue,
                    "portee": groupes["entre_exports"]
                    .map({True: PORTEE_ENTRE_EXPORTS, False: PORTEE_MEME_FICHIER})
                    .to_numpy(),
                    "comparaison": groupes["normalisee"]
                    .map({True: COMPARAISON_NORMALISEE, False: COMPARAISON_TELLE_QUELLE})
                    .to_numpy(),
                    "groupe": groupes["groupe"].to_numpy(),
                    "taille_groupe": groupes["taille_groupe"].to_numpy(),
                    "cle": cles.loc[positions].to_numpy(),
                    "valeur": None if valeurs is None else valeurs.loc[positions].to_numpy(),
                }
            )
            for lignage in COLONNES_LIGNAGE_ECART:
                morceau[lignage] = (
                    donnees[lignage].loc[positions].to_numpy()
                    if lignage in donnees.columns
                    else None
                )
            morceaux.append(morceau)

    if morceaux:
        doublons = pd.concat(morceaux, ignore_index=True)[list(COLONNES_DOUBLONS)]
    else:
        doublons = pd.DataFrame(columns=list(COLONNES_DOUBLONS))
    return doublons, pd.DataFrame(bilan, columns=list(COLONNES_BILAN_DOUBLONS))
