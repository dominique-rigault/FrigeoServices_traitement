"""Formulaire des règles de contrôle par le métier (phase 5.1 du mode opératoire).

Ce module ne contient rien de propre à un client. Les règles que le dictionnaire ne
peut pas déduire des données (nombre de décimales, bornes, clé de Luhn) et les
déclarations de doublons sont écrites dans config/controles.yaml. Plutôt que de faire
écrire ce fichier à la main, le métier les revoit dans un classeur Excel :

- le classeur montre, à côté de propositions tirées des données (valeurs observées),
  les règles en vigueur lues dans config/controles.yaml, si bien qu'il donne en clair
  l'état effectif des règles;
- le métier choisit un statut par ligne, comme dans la revue du dictionnaire, et
  saisit au besoin ses propres valeurs;
- le classeur relu est contrôlé (`importer_formulaire`), puis réécrit
  config/controles.yaml (`ecrire_controles`), après une copie datée de l'ancien
  fichier.

Le fichier YAML ne garde pas de statut : une règle présente a été donnée par le
métier, elle sort au statut « documenté » avec ses valeurs. Une proposition refusée
(statut « invalide ») est retenue sous la clé `ecartees`, pour ne pas revenir à
chaque cycle; les commentaires du métier le sont sous la clé `commentaires`. Ces deux
clés sont sans effet sur les contrôles. Le fichier réécrit garde l'ordre du
dictionnaire; les commentaires écrits à la main dans le fichier ne sont pas gardés,
mais les motifs (expressions régulières) et les règles sur des colonnes que le
formulaire ne présente pas sont repris tels quels.

Le classeur porte des valeurs observées (minimum, maximum) : il est rangé hors du
dépôt, dans data/formulaires/. Les minimums et maximums d'une colonne sensible y sont
masqués, sans proposition de bornes.
"""

from __future__ import annotations

import copy
import hashlib
import unicodedata
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple

import pandas as pd
import yaml
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, Protection
from openpyxl.utils import get_column_letter, quote_sheetname

from . import dictionnaire as module_dictionnaire
from . import racine_projet
from .confidentialite import est_sensible
from .controles import (
    CLE_COMMENTAIRES,
    CLE_DOUBLONS,
    CLE_ECARTEES,
    CLE_REGLES_COMPLEMENTAIRES,
    CLES_FICHIER_CONTROLES,
    EXCLUSIONS,
    REGLES_COMPLEMENTAIRES,
    _cle_luhn_valide,
    _nombre,
    _parametre_en_texte,
    _probleme_parametre,
    _trop_de_decimales,
    chemin_regles_complementaires,
    problemes_regles_complementaires,
)
from .dictionnaire import STATUTS, _valeurs_renseignees, dossier_sauvegardes
from .doublons import problemes_declarations_doublons
from .revue import _ecrire_texte, _menu
from .typage import NATURES_NOMBRE

FEUILLE_MODE_EMPLOI = "mode_emploi"
FEUILLE_DECIMALES = "décimales"
FEUILLE_BORNES = "bornes"
FEUILLE_LUHN = "clé_luhn"
FEUILLE_DOUBLONS = "doublons"
FEUILLE_TABLES = "tables"
FEUILLE_MOTIFS = "motifs"
# Feuille technique, masquée : la liste des tables, pour le menu des lignes d'ajout.
FEUILLE_LISTES = "listes"

# Types de règle revus dans le formulaire (clés de config/controles.yaml), avec leur
# feuille. Le motif n'y est qu'affiché : une expression régulière n'est pas l'affaire
# du métier.
TYPES_FORMULAIRE = ("decimales", "bornes", "cle_luhn")
FEUILLES_TYPE = {
    "decimales": FEUILLE_DECIMALES,
    "bornes": FEUILLE_BORNES,
    "cle_luhn": FEUILLE_LUHN,
}
# Les déclarations de doublons : nom dans config/controles.yaml et nom affiché.
GROUPES_DOUBLONS = {"cle": "clé", "unique": "unique", "presume_unique": "présumé unique"}
OUI = "oui"
NON = "non"
AUCUNE = "aucune"
MASQUE = "masqué"
ORIGINE_EN_VIGUEUR = "en vigueur"
ORIGINE_PROPOSEE = "proposée"
ORIGINE_ECARTEE = "écartée"
STATUT_OBSERVE, STATUT_VALIDE, STATUT_INVALIDE, STATUT_DOCUMENTE = STATUTS
# Part minimale de clés de Luhn valides pour proposer la règle.
SEUIL_LUHN = 0.95
# Natures des colonnes où une clé candidate peut être proposée : un montant ou une
# date ne sont pas des identifiants, même sans répétition.
NATURES_CLE = ("texte", "entier (texte)")
LIGNES_AJOUT = 50
REPERE_EMPREINTE = "Empreinte de config/controles.yaml à l'export (repère technique)"

COLONNES_DECIMALES = (
    "table",
    "colonne",
    "nature",
    "valeurs",
    "observé",
    "proposition",
    "en_vigueur",
    "statut",
    "décimales",
    "commentaire",
)
COLONNES_BORNES = (
    "table",
    "colonne",
    "nature",
    "valeurs",
    "observé",
    "proposition",
    "en_vigueur",
    "statut",
    "min",
    "min_exclu",
    "max",
    "max_exclu",
    "commentaire",
    "proposition_min",
    "proposition_max",
)
COLONNES_LUHN = (
    "table",
    "colonne",
    "nature",
    "valeurs",
    "observé",
    "proposition",
    "en_vigueur",
    "statut",
    "commentaire",
)
COLONNES_DOUBLONS = ("table", "type", "colonnes", "origine", "observé", "statut", "commentaire")
COLONNES_TABLES = ("table", "lignes", "clé_en_vigueur", "identiques_hors_clé")
COLONNES_MOTIFS = ("table", "colonne", "motif")
COLONNES_TYPE = {
    "decimales": COLONNES_DECIMALES,
    "bornes": COLONNES_BORNES,
    "cle_luhn": COLONNES_LUHN,
}
MODIFIABLES = {
    "decimales": ("statut", "décimales", "commentaire"),
    "bornes": ("statut", "min", "min_exclu", "max", "max_exclu", "commentaire"),
    "cle_luhn": ("statut", "commentaire"),
}
MODIFIABLES_DOUBLONS = ("type", "statut", "commentaire")
SAISIE_AJOUT_DOUBLONS = ("table", "type", "colonnes", "statut", "commentaire")
# Colonnes techniques, masquées : la proposition des bornes en nombres, relue à
# l'import.
COLONNES_MASQUEES = ("proposition_min", "proposition_max")
LARGEURS = {
    "table": 22,
    "colonne": 26,
    "nature": 22,
    "valeurs": 10,
    "observé": 34,
    "proposition": 16,
    "en_vigueur": 16,
    "statut": 13,
    "décimales": 11,
    "min": 11,
    "min_exclu": 11,
    "max": 11,
    "max_exclu": 11,
    "commentaire": 50,
    "proposition_min": 8,
    "proposition_max": 8,
    "type": 16,
    "colonnes": 40,
    "origine": 12,
    "lignes": 10,
    "clé_en_vigueur": 34,
    "identiques_hors_clé": 20,
    "motif": 50,
}


def chemin_formulaire(periode_fin: str) -> Path:
    """Emplacement par défaut du formulaire : data/formulaires/, hors du dépôt."""
    return racine_projet() / "data" / "formulaires" / f"controles_{periode_fin}.xlsx"


def empreinte_controles(chemin: str | Path | None = None) -> str:
    """Empreinte du contenu de config/controles.yaml, « absent » sans fichier.

    Les fins de ligne sont ramenées à LF : une conversion par Git sous Windows ne
    change pas l'empreinte.
    """
    chemin = Path(chemin) if chemin is not None else chemin_regles_complementaires()
    if not chemin.is_file():
        return "absent"
    contenu = chemin.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(contenu).hexdigest()[:16]


# --- Observations ---------------------------------------------------------------


def _decimales(nombre) -> int:
    """Nombre de décimales significatives d'un nombre lu par `controles._nombre`."""
    if isinstance(nombre, Decimal):
        return max(0, -nombre.normalize().as_tuple().exponent)
    return next(d for d in range(16) if not _trop_de_decimales(nombre, d))


def _arrondi(nombre):
    """Nombre écrit dans config/controles.yaml : un entier, ou un décimal arrondi."""
    if isinstance(nombre, Decimal):
        nombre = float(nombre)
    if float(nombre).is_integer():
        return int(nombre)
    return round(float(nombre), 10)


def texte_nombre(nombre) -> str:
    """Nombre écrit à la française (virgule décimale), sans zéro inutile."""
    texte = format(Decimal(repr(_arrondi(nombre))).normalize(), "f")
    return texte.replace(".", ",")


def observer_nombres(serie: pd.Series) -> dict:
    """Valeurs numériques d'une colonne : nombre, minimum, maximum et décimales.

    Seules comptent les valeurs que lisent les contrôles (nombre natif, ou texte à
    virgule ou point décimal, sans séparateur de milliers) : les autres relèvent de
    la règle `nature`. Sans valeur lisible, minimum, maximum et décimales sont None.
    """
    nombres = [n for n in map(_nombre, _valeurs_renseignees(serie)) if n is not None]
    if not nombres:
        return {"valeurs": 0, "min": None, "max": None, "decimales": None}
    return {
        "valeurs": len(nombres),
        "min": min(nombres),
        "max": max(nombres),
        "decimales": max(_decimales(n) for n in nombres),
    }


def observer_luhn(serie: pd.Series) -> dict:
    """Valeurs faites de chiffres d'une colonne, et part de celles dont la clé de Luhn
    est valide (None sans valeur de chiffres)."""
    chiffres = [
        texte
        for texte in (str(v) for v in _valeurs_renseignees(serie))
        if texte.isascii() and texte.isdigit()
    ]
    if not chiffres:
        return {"valeurs": 0, "part_valide": None}
    valides = sum(_cle_luhn_valide(texte) for texte in chiffres)
    return {"valeurs": len(chiffres), "part_valide": valides / len(chiffres)}


def observer_groupe(donnees: pd.DataFrame, colonnes: list[str]) -> dict:
    """Lignes d'une table où le groupe de colonnes est entièrement renseigné, et lignes
    dont les valeurs du groupe se répètent (comparées telles quelles)."""
    renseignees = pd.Series(True, index=donnees.index)
    for colonne in colonnes:
        renseignees &= donnees.index.isin(_valeurs_renseignees(donnees[colonne]).index)
    sous_table = donnees.loc[renseignees, colonnes].astype(str)
    return {
        "lignes": len(donnees),
        "renseignees": len(sous_table),
        "repetees": int(sous_table.duplicated(keep=False).sum()),
    }


def _texte_groupe(observation: dict) -> str:
    texte = f"{observation['renseignees']} lignes renseignées sur {observation['lignes']}"
    if observation["repetees"]:
        return f"{texte}, {observation['repetees']} lignes répétées"
    return f"{texte}, aucune répétition"


# --- Contenu de config/controles.yaml -------------------------------------------


def _section(contenu: dict, cle: str) -> dict:
    valeur = contenu.get(cle)
    return valeur if isinstance(valeur, dict) else {}


def _ecartees(contenu: dict, nom: str) -> dict:
    """Propositions écartées pour un type de règle ou les doublons, par table."""
    return _section(_section(contenu, CLE_ECARTEES), nom)


def _commentaires(contenu: dict, nom: str) -> dict:
    """Commentaires du métier pour un type de règle ou les doublons, par table."""
    return _section(_section(contenu, CLE_COMMENTAIRES), nom)


def texte_groupe(colonnes: list[str]) -> str:
    """Colonnes d'un groupe de doublons, telles que le formulaire les écrit."""
    return ", ".join(colonnes)


def _groupes_en_vigueur(declaration: dict) -> list[tuple[str, list[str]]]:
    groupes = []
    if "cle" in declaration:
        groupes.append(("cle", list(declaration["cle"])))
    for nom in ("unique", "presume_unique"):
        groupes.extend((nom, list(groupe)) for groupe in declaration.get(nom, []))
    return groupes


# --- Lignes du formulaire -------------------------------------------------------


def _colonnes_de_nature(dictionnaire: dict, natures) -> list[tuple[str, str, str]]:
    """(table, colonne, nature en vigueur) des colonnes d'une des natures, dans
    l'ordre du dictionnaire."""
    return [
        (table, colonne, regles["nature"]["regle"])
        for table, colonnes in dictionnaire.items()
        for colonne, regles in colonnes.items()
        if regles["nature"]["regle"] in natures
    ]


def _statut_export(en_vigueur, ecartee: bool) -> str:
    if en_vigueur is not None:
        return STATUT_DOCUMENTE
    return STATUT_INVALIDE if ecartee else STATUT_OBSERVE


def lignes_decimales(tables: dict, dictionnaire: dict, contenu: dict) -> list[dict]:
    """Lignes de la feuille des décimales : une par colonne de nature numérique.

    La proposition est le plus grand nombre de décimales observé; « aucune » sans
    valeur lisible.
    """
    regles = _section(contenu, CLE_REGLES_COMPLEMENTAIRES)
    ecartees = _ecartees(contenu, "decimales")
    commentaires = _commentaires(contenu, "decimales")
    lignes = []
    for table, colonne, nature in _colonnes_de_nature(dictionnaire, NATURES_NOMBRE):
        observation = observer_nombres(tables[table][colonne])
        en_vigueur = regles.get(table, {}).get(colonne, {}).get("decimales")
        decimales = observation["decimales"]
        lignes.append(
            {
                "table": table,
                "colonne": colonne,
                "nature": nature,
                "valeurs": observation["valeurs"],
                "observé": decimales,
                "proposition": AUCUNE if decimales is None else decimales,
                "en_vigueur": en_vigueur,
                "statut": _statut_export(en_vigueur, colonne in ecartees.get(table, [])),
                "décimales": en_vigueur,
                "commentaire": commentaires.get(table, {}).get(colonne),
            }
        )
    return lignes


def lignes_bornes(
    tables: dict, dictionnaire: dict, contenu: dict, sensibles: dict
) -> list[dict]:
    """Lignes de la feuille des bornes : une par colonne de nature numérique.

    La proposition est l'intervalle observé, bornes incluses; « aucune » sans valeur
    lisible ou pour une colonne sensible, dont le minimum et le maximum observés
    sont masqués.
    """
    regles = _section(contenu, CLE_REGLES_COMPLEMENTAIRES)
    ecartees = _ecartees(contenu, "bornes")
    commentaires = _commentaires(contenu, "bornes")
    lignes = []
    for table, colonne, nature in _colonnes_de_nature(dictionnaire, NATURES_NOMBRE):
        observation = observer_nombres(tables[table][colonne])
        en_vigueur = regles.get(table, {}).get(colonne, {}).get("bornes")
        sensible = est_sensible(sensibles, table, colonne)
        if sensible and observation["valeurs"]:
            observe, proposition, mini, maxi = MASQUE, AUCUNE, None, None
        elif observation["valeurs"]:
            mini, maxi = _arrondi(observation["min"]), _arrondi(observation["max"])
            observe = f"de {texte_nombre(mini)} à {texte_nombre(maxi)}"
            proposition = f"{texte_nombre(mini)} à {texte_nombre(maxi)}"
        else:
            observe, proposition, mini, maxi = None, AUCUNE, None, None
        en_vigueur = en_vigueur if isinstance(en_vigueur, dict) else None
        ligne = {
            "table": table,
            "colonne": colonne,
            "nature": nature,
            "valeurs": observation["valeurs"],
            "observé": observe,
            "proposition": proposition,
            "en_vigueur": (
                None if en_vigueur is None else _parametre_en_texte("bornes", en_vigueur)
            ),
            "statut": _statut_export(en_vigueur, colonne in ecartees.get(table, [])),
            "min": None,
            "min_exclu": None,
            "max": None,
            "max_exclu": None,
            "commentaire": commentaires.get(table, {}).get(colonne),
            "proposition_min": mini,
            "proposition_max": maxi,
        }
        for borne, exclusion in EXCLUSIONS.items():
            if en_vigueur is not None and borne in en_vigueur:
                ligne[borne] = en_vigueur[borne]
                ligne[exclusion] = OUI if en_vigueur.get(exclusion) else NON
        lignes.append(ligne)
    return lignes


def lignes_luhn(tables: dict, dictionnaire: dict, contenu: dict) -> list[dict]:
    """Lignes de la feuille des clés de Luhn : une par colonne « entier (texte) ».

    La règle est proposée quand au moins `SEUIL_LUHN` des valeurs faites de chiffres
    ont une clé valide (un SIRET, par exemple).
    """
    regles = _section(contenu, CLE_REGLES_COMPLEMENTAIRES)
    ecartees = _ecartees(contenu, "cle_luhn")
    commentaires = _commentaires(contenu, "cle_luhn")
    lignes = []
    for table, colonne, nature in _colonnes_de_nature(dictionnaire, ("entier (texte)",)):
        observation = observer_luhn(tables[table][colonne])
        en_vigueur = OUI if regles.get(table, {}).get(colonne, {}).get("cle_luhn") else None
        part = observation["part_valide"]
        lignes.append(
            {
                "table": table,
                "colonne": colonne,
                "nature": nature,
                "valeurs": observation["valeurs"],
                "observé": (
                    None if part is None
                    else f"{texte_nombre(round(100 * part, 1))} % de clés valides"
                ),
                "proposition": OUI if part is not None and part >= SEUIL_LUHN else AUCUNE,
                "en_vigueur": en_vigueur,
                "statut": _statut_export(en_vigueur, colonne in ecartees.get(table, [])),
                "commentaire": commentaires.get(table, {}).get(colonne),
            }
        )
    return lignes


def _candidates(donnees: pd.DataFrame, dictionnaire_table: dict) -> list[str]:
    """Colonnes d'une table toujours renseignées et sans valeur répétée."""
    if len(donnees) < 2:
        return []
    candidates = []
    for colonne, regles in dictionnaire_table.items():
        if regles["nature"]["regle"] not in NATURES_CLE:
            continue
        observation = observer_groupe(donnees, [colonne])
        if observation["renseignees"] == len(donnees) and not observation["repetees"]:
            candidates.append(colonne)
    return candidates


def lignes_doublons(tables: dict, dictionnaire: dict, contenu: dict) -> list[dict]:
    """Lignes de la feuille des doublons : un groupe de colonnes par ligne.

    Les groupes en vigueur d'abord (statut « documenté »), puis les clés candidates
    (une colonne toujours renseignée, sans valeur répétée, de nature texte ou entier)
    qui ne sont pas déjà déclarées seules, au statut « observé », puis les groupes
    écartés (statut « invalide »). Une clé candidate est proposée comme clé si la
    table n'en a pas, comme unique sinon.
    """
    declarations = _section(contenu, CLE_DOUBLONS)
    ecartees = _ecartees(contenu, "doublons")
    commentaires = _commentaires(contenu, "doublons")
    lignes = []
    for table, donnees in tables.items():
        if table not in dictionnaire:
            continue
        en_vigueur = _groupes_en_vigueur(declarations.get(table, {}))
        refuses = [list(groupe) for groupe in ecartees.get(table, [])]
        connus = {frozenset(groupe) for _, groupe in en_vigueur} | {
            frozenset(groupe) for groupe in refuses
        }
        avec_cle = any(nom == "cle" for nom, _ in en_vigueur)
        proposes = [
            ("unique" if avec_cle else "cle", [colonne])
            for colonne in _candidates(donnees, dictionnaire[table])
            if frozenset([colonne]) not in connus
        ]
        for origine, statut, groupes in (
            (ORIGINE_EN_VIGUEUR, STATUT_DOCUMENTE, en_vigueur),
            (ORIGINE_PROPOSEE, STATUT_OBSERVE, proposes),
            (ORIGINE_ECARTEE, STATUT_INVALIDE, [("unique", groupe) for groupe in refuses]),
        ):
            for nom, groupe in groupes:
                presentes = [colonne for colonne in groupe if colonne in donnees.columns]
                observation = (
                    _texte_groupe(observer_groupe(donnees, groupe))
                    if len(presentes) == len(groupe)
                    else None
                )
                lignes.append(
                    {
                        "table": table,
                        "type": GROUPES_DOUBLONS[nom],
                        "colonnes": texte_groupe(groupe),
                        "origine": origine,
                        "observé": observation,
                        "statut": statut,
                        "commentaire": commentaires.get(table, {}).get(texte_groupe(groupe)),
                    }
                )
    return lignes


def lignes_tables(tables: dict, dictionnaire: dict, contenu: dict) -> list[dict]:
    """Lignes de la feuille des tables : faut-il chercher les lignes identiques hors
    de la clé (« non » quand deux enregistrements peuvent y être pareils) ?"""
    declarations = _section(contenu, CLE_DOUBLONS)
    return [
        {
            "table": table,
            "lignes": len(donnees),
            "clé_en_vigueur": texte_groupe(declarations.get(table, {}).get("cle", [])) or None,
            "identiques_hors_clé": (
                NON if declarations.get(table, {}).get("identique_hors_cle") is False else OUI
            ),
        }
        for table, donnees in tables.items()
        if table in dictionnaire
    ]


def lignes_motifs(contenu: dict) -> list[dict]:
    """Motifs en vigueur, affichés en lecture seule."""
    return [
        {"table": table, "colonne": colonne, "motif": regles["motif"]}
        for table, colonnes in _section(contenu, CLE_REGLES_COMPLEMENTAIRES).items()
        for colonne, regles in (colonnes or {}).items()
        if isinstance(regles, dict) and "motif" in regles
    ]


# --- Export ---------------------------------------------------------------------


def _a_traiter(lignes: list[dict]) -> int:
    return sum(ligne["statut"] == STATUT_OBSERVE for ligne in lignes)


def _mode_emploi(periode_fin: str, lignes: dict) -> list[str]:
    decimales, bornes, luhn = lignes["decimales"], lignes["bornes"], lignes["cle_luhn"]
    doublons = lignes["doublons"]
    return [
        "Formulaire des règles de contrôle",
        f"Période de fin : {periode_fin}. Formulaire généré le {date.today():%d/%m/%Y}.",
        "Ce formulaire donne les règles de contrôle que le dictionnaire des données ne "
        "peut pas déduire des fichiers : nombre de décimales, bornes, clé de contrôle "
        "de Luhn, et les colonnes qui ne doivent pas se répéter. Il montre les règles en "
        "vigueur (colonne en_vigueur, statut documenté) à côté de ce que l'outil observe "
        "dans les données (colonnes observé et proposition). Une fois revu, il réécrit "
        "le fichier des règles de contrôle.",
        "",
        "Ce qui reste à traiter",
        f"Feuille « {FEUILLE_DECIMALES} » : {_a_traiter(decimales)} lignes à « observé » "
        f"sur {len(decimales)}. Feuille « {FEUILLE_BORNES} » : {_a_traiter(bornes)} sur "
        f"{len(bornes)}. Feuille « {FEUILLE_LUHN} » : {_a_traiter(luhn)} sur {len(luhn)}. "
        f"Feuille « {FEUILLE_DOUBLONS} » : {_a_traiter(doublons)} sur {len(doublons)}.",
        "Une revue partielle est possible : une ligne laissée à « observé » est "
        "reprise telle quelle dans le formulaire suivant.",
        "",
        "Ce qui est attendu",
        "Pour chaque ligne, choisir un statut dans le menu déroulant et, si besoin, "
        "écrire un commentaire (il est conservé).",
        "observé : la ligne n'est pas revue; pas de règle.",
        "valide : la proposition devient la règle. Impossible si la proposition est "
        f"« {AUCUNE} ».",
        "documenté : vous donnez vous-même la règle, dans les colonnes à saisir de la "
        "ligne. Une règle en vigueur sort avec ce statut et ses valeurs : pour la "
        "modifier, changer les valeurs en gardant documenté.",
        "invalide : pas de règle sur cette colonne, et la proposition ne sera plus "
        "faite. Pour une règle en vigueur, invalide la retire.",
        "Remettre « observé » sur une règle en vigueur la retire aussi, mais la ligne "
        "sera de nouveau à traiter au formulaire suivant.",
        "Une valeur saisie sur une ligne qui n'est pas au statut documenté est ignorée "
        "(un avertissement le signale à l'import).",
        "",
        f"Feuille « {FEUILLE_DECIMALES} » : le nombre maximal de décimales d'un nombre",
        "Une ligne par colonne numérique, codes compris : pour un code ou un "
        "identifiant (SIRET, compte), choisir invalide. La proposition est le plus grand "
        "nombre de décimales observé. Colonne à saisir : décimales.",
        "",
        f"Feuille « {FEUILLE_BORNES} » : le minimum et le maximum admis",
        "La proposition est le plus petit et le plus grand nombre observés, bornes "
        "incluses. Attention : si les données contiennent une erreur (un taux de 80 au "
        "lieu de 0,8), elle fait partie de la proposition. Colonnes à saisir : min, max "
        "(l'un ou l'autre suffit), et pour chacun min_exclu ou max_exclu (oui si la "
        "borne elle-même est interdite : « plus de 0 » s'écrit min 0 et min_exclu oui). "
        f"Pour une colonne sensible, le minimum et le maximum observés sont « {MASQUE} » "
        "et rien n'est proposé : donner les bornes au statut documenté.",
        "",
        f"Feuille « {FEUILLE_LUHN} » : la clé de contrôle de Luhn",
        "Une ligne par colonne de chiffres. La règle est proposée quand au moins "
        f"{texte_nombre(100 * SEUIL_LUHN)} % des valeurs ont une clé valide, ce qui est "
        "le cas d'un SIRET ou d'un SIREN corrects.",
        "",
        f"Feuille « {FEUILLE_DOUBLONS} » : les colonnes qui ne doivent pas se répéter",
        "Une ligne par groupe de colonnes : clé (l'identifiant d'une ligne, une seule "
        "par table), unique (une répétition est une anomalie), présumé unique (une "
        "répétition est à arbitrer). Le type se change dans le menu de la colonne type. "
        "Les groupes en vigueur sont au statut documenté. L'outil propose les colonnes "
        "toujours renseignées et sans répétition (statut observé) : valide les retient "
        "avec le type affiché.",
        "Pour ajouter un groupe de plusieurs colonnes : sur une ligne vide en bas de la "
        "feuille, choisir la table et le type dans les menus, écrire les colonnes "
        "séparées par une virgule (par exemple « raison_sociale, cp ») et choisir le "
        "statut documenté.",
        "",
        f"Feuille « {FEUILLE_TABLES} » : les lignes identiques hors de la clé",
        "oui : deux lignes pareilles en tout sauf la clé sont signalées. non : elles "
        "sont normales dans cette table (deux enregistrements peuvent être pareils). Ne "
        "s'applique qu'à une table qui a une clé.",
        "",
        f"Feuille « {FEUILLE_MOTIFS} » : lecture seule",
        "Les motifs (expressions régulières) sont écrits par le consultant et repris "
        "tels quels.",
        "",
        "Règles à respecter pour que le formulaire puisse être réimporté",
        "Ne modifier que les cellules non verrouillées. Ne pas renommer, déplacer ni "
        "supprimer de feuilles, de colonnes ou de lignes. Avant l'import : enregistrer "
        "puis fermer le classeur dans Excel. Un formulaire ne s'applique qu'une fois : "
        "après son import, ou après une modification du fichier des règles, il est à "
        "réexporter.",
        REPERE_EMPREINTE,
    ]


def _remplir(feuille, colonnes, lignes, modifiables, lignes_ajout=0, saisie_ajout=()) -> None:
    """Écrit l'en-tête et les lignes, puis protège la feuille hors cellules modifiables."""
    for indice, nom in enumerate(colonnes, start=1):
        cellule = feuille.cell(row=1, column=indice, value=nom)
        cellule.font = Font(bold=True)
        lettre = cellule.column_letter
        feuille.column_dimensions[lettre].width = LARGEURS[nom]
        if nom in COLONNES_MASQUEES:
            feuille.column_dimensions[lettre].hidden = True
    for numero, ligne in enumerate(lignes, start=2):
        for indice, nom in enumerate(colonnes, start=1):
            cellule = feuille.cell(row=numero, column=indice)
            valeur = ligne.get(nom)
            if isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
                cellule.value = valeur
            else:
                _ecrire_texte(cellule, valeur)
            if nom in modifiables:
                cellule.protection = Protection(locked=False)
    fin = len(lignes) + 1
    for numero in range(fin + 1, fin + lignes_ajout + 1):
        for indice, nom in enumerate(colonnes, start=1):
            if nom in saisie_ajout:
                cellule = feuille.cell(row=numero, column=indice)
                cellule.number_format = "@"
                cellule.protection = Protection(locked=False)
    derniere = get_column_letter(len(colonnes))
    feuille.freeze_panes = "C2"
    feuille.auto_filter.ref = f"A1:{derniere}{max(fin + lignes_ajout, 2)}"
    feuille.protection.sheet = True
    feuille.protection.autoFilter = False
    feuille.protection.formatColumns = False


def _colonne(colonnes, nom) -> int:
    return colonnes.index(nom) + 1


def _ajouter_menu(feuille, menu, colonnes, nom, premiere, derniere) -> None:
    if derniere >= premiere:
        lettre = get_column_letter(_colonne(colonnes, nom))
        menu.add(f"{lettre}{premiere}:{lettre}{derniere}")


def exporter_formulaire(
    tables: dict,
    dictionnaire: dict,
    contenu: dict,
    sensibles: dict,
    periode_fin: str,
    chemin: str | Path | None = None,
    *,
    empreinte: str,
    ecraser: bool = False,
) -> Path:
    """Écrit le formulaire des règles de contrôle et rend son chemin.

    `contenu` est celui de config/controles.yaml (`controles.lire_fichier_controles`)
    et `empreinte` son empreinte (`empreinte_controles`) : elle est inscrite dans le
    formulaire, et l'import le refusera si le fichier a changé depuis. Sans
    `ecraser=True`, refuse de remplacer un formulaire existant : une revue y est
    peut-être en cours.
    """
    chemin = Path(chemin) if chemin is not None else chemin_formulaire(periode_fin)
    if chemin.exists() and not ecraser:
        raise FileExistsError(
            f"{chemin} existe déjà : export refusé (ecraser=True pour forcer)"
        )
    lignes = {
        "decimales": lignes_decimales(tables, dictionnaire, contenu),
        "bornes": lignes_bornes(tables, dictionnaire, contenu, sensibles),
        "cle_luhn": lignes_luhn(tables, dictionnaire, contenu),
        "doublons": lignes_doublons(tables, dictionnaire, contenu),
    }
    noms_tables = [table for table in tables if table in dictionnaire]

    classeur = Workbook()
    notice = classeur.active
    notice.title = FEUILLE_MODE_EMPLOI
    notice.column_dimensions["A"].width = 120
    rubriques = ("Ce qui", "Feuille", "Règles à", "Formulaire des")
    for numero, texte in enumerate(_mode_emploi(periode_fin, lignes), start=1):
        cellule = notice.cell(row=numero, column=1)
        _ecrire_texte(cellule, texte)
        cellule.alignment = Alignment(wrap_text=True, vertical="top")
        if texte == REPERE_EMPREINTE:
            _ecrire_texte(notice.cell(row=numero, column=2), empreinte)
        if texte.startswith(rubriques):
            cellule.font = Font(bold=True)
    notice.protection.sheet = True

    for nom in TYPES_FORMULAIRE:
        colonnes = COLONNES_TYPE[nom]
        feuille = classeur.create_sheet(FEUILLES_TYPE[nom])
        _remplir(feuille, colonnes, lignes[nom], MODIFIABLES[nom])
        derniere = len(lignes[nom]) + 1
        _ajouter_menu(feuille, _menu(feuille, STATUTS), colonnes, "statut", 2, derniere)
        if nom == "bornes":
            menu = _menu(feuille, (OUI, NON))
            for exclusion in EXCLUSIONS.values():
                _ajouter_menu(feuille, menu, colonnes, exclusion, 2, derniere)

    feuille = classeur.create_sheet(FEUILLE_DOUBLONS)
    doublons = lignes["doublons"]
    _remplir(
        feuille, COLONNES_DOUBLONS, doublons, MODIFIABLES_DOUBLONS, LIGNES_AJOUT,
        SAISIE_AJOUT_DOUBLONS,
    )
    derniere = len(doublons) + 1 + LIGNES_AJOUT
    _ajouter_menu(feuille, _menu(feuille, STATUTS), COLONNES_DOUBLONS, "statut", 2, derniere)
    _ajouter_menu(
        feuille, _menu(feuille, tuple(GROUPES_DOUBLONS.values())), COLONNES_DOUBLONS,
        "type", 2, derniere,
    )
    if noms_tables:
        plage = f"{quote_sheetname(FEUILLE_LISTES)}!$A$1:$A${len(noms_tables)}"
        _ajouter_menu(
            feuille, _menu(feuille, formule=plage), COLONNES_DOUBLONS, "table",
            len(doublons) + 2, derniere,
        )

    feuille = classeur.create_sheet(FEUILLE_TABLES)
    lignes_t = lignes_tables(tables, dictionnaire, contenu)
    _remplir(feuille, COLONNES_TABLES, lignes_t, ("identiques_hors_clé",))
    _ajouter_menu(
        feuille, _menu(feuille, (OUI, NON)), COLONNES_TABLES, "identiques_hors_clé", 2,
        len(lignes_t) + 1,
    )

    feuille = classeur.create_sheet(FEUILLE_MOTIFS)
    _remplir(feuille, COLONNES_MOTIFS, lignes_motifs(contenu), ())

    listes = classeur.create_sheet(FEUILLE_LISTES)
    for numero, table in enumerate(noms_tables, start=1):
        _ecrire_texte(listes.cell(row=numero, column=1), table)
    listes.protection.sheet = True
    listes.sheet_state = "hidden"

    chemin.parent.mkdir(parents=True, exist_ok=True)
    classeur.save(chemin)
    return chemin


# --- Import ---------------------------------------------------------------------

# Rapport des changements : une ligne par règle qui change, avec son état avant et
# après, en texte (« 2 », « 0 exclu à 1 », « clé », « écartée »; vide sans règle).
COLONNES_CHANGEMENTS = ("table", "colonne", "regle", "avant", "apres")
ETAT_ECARTEE = "écartée"
REGLE_DOUBLONS = "doublons"
REGLE_IDENTIQUES = "identique_hors_cle"
# Type d'un groupe de doublons : nom affiché, puis nom dans config/controles.yaml.
TYPES_DOUBLONS = {affiche: nom for nom, affiche in GROUPES_DOUBLONS.items()}
ORIGINES = (ORIGINE_EN_VIGUEUR, ORIGINE_PROPOSEE, ORIGINE_ECARTEE)
STATUTS_RETENUS = (STATUT_VALIDE, STATUT_DOCUMENTE)


class Formulaire(NamedTuple):
    """Règles lues dans un formulaire, contrôlées mais pas encore écrites.

    `contenu` est le nouveau contenu de config/controles.yaml, `changements` le
    rapport des règles qui changent (`COLONNES_CHANGEMENTS`).
    """

    contenu: dict
    changements: pd.DataFrame
    avertissements: list[str]


def _texte(valeur) -> str:
    """Texte d'une cellule, normalisé (NFC, espaces en bord ôtés), vide sans valeur."""
    if valeur is None:
        return ""
    return unicodedata.normalize("NFC", str(valeur)).strip()


def _vide(valeur) -> bool:
    return _texte(valeur) == ""


def _lire_feuille(classeur, nom: str, colonnes: tuple[str, ...]) -> list[tuple[int, dict]]:
    """Lignes non vides d'une feuille, avec leur numéro de ligne Excel.

    Lève une ValueError si la feuille manque ou si son en-tête n'est pas celui exporté.
    """
    if nom not in classeur.sheetnames:
        raise ValueError(
            f"feuille « {nom} » absente (feuille renommée, ou formulaire exporté par une "
            "version antérieure : à réexporter)"
        )
    lignes = classeur[nom].iter_rows(values_only=True)
    entete = tuple(next(lignes, ()))
    while entete and entete[-1] is None:
        entete = entete[:-1]
    if entete != colonnes:
        raise ValueError(
            f"feuille « {nom} » : en-tête modifié, attendu {', '.join(colonnes)} "
            "(formulaire exporté par une version antérieure : à réexporter)"
        )
    resultat = []
    for numero, valeurs in enumerate(lignes, start=2):
        valeurs = tuple(valeurs[: len(colonnes)]) + (None,) * (len(colonnes) - len(valeurs))
        if all(_vide(valeur) for valeur in valeurs):
            continue
        resultat.append((numero, dict(zip(colonnes, valeurs))))
    return resultat


def _lire_empreinte(classeur) -> str:
    """Empreinte de config/controles.yaml inscrite dans le formulaire à l'export."""
    if FEUILLE_MODE_EMPLOI not in classeur.sheetnames:
        raise ValueError(f"feuille « {FEUILLE_MODE_EMPLOI} » absente")
    for ligne in classeur[FEUILLE_MODE_EMPLOI].iter_rows(max_col=2, values_only=True):
        if ligne and ligne[0] == REPERE_EMPREINTE:
            empreinte = _texte(ligne[1] if len(ligne) > 1 else None)
            if empreinte:
                return empreinte
            break
    raise ValueError(
        f"feuille « {FEUILLE_MODE_EMPLOI} » : repère de l'empreinte absent ou modifié, "
        "formulaire à réexporter"
    )


def _nombre_saisi(valeur):
    """Nombre d'une cellule (natif, ou texte à virgule ou point décimal), écrit comme
    dans config/controles.yaml (entier si possible); None s'il n'y en a pas."""
    if isinstance(valeur, str):
        valeur = valeur.strip()
    nombre = _nombre(valeur)
    return None if nombre is None else _arrondi(nombre)


def _saisie(nom: str, ligne: dict) -> tuple[object, str | None]:
    """Paramètre donné dans les colonnes à saisir d'une ligne (None si rien n'y est
    écrit), et le problème de la saisie (None si elle est correcte)."""
    if nom == "decimales":
        if _vide(ligne["décimales"]):
            return None, None
        nombre = _nombre_saisi(ligne["décimales"])
        if not isinstance(nombre, int) or nombre < 0:
            return None, "décimales : un nombre entier positif ou nul est attendu"
        return nombre, None
    if nom == "bornes":
        parametre = {}
        for borne in EXCLUSIONS:
            if not _vide(ligne[borne]):
                nombre = _nombre_saisi(ligne[borne])
                if nombre is None:
                    return None, f"{borne} : un nombre est attendu"
                parametre[borne] = nombre
        for exclusion in EXCLUSIONS.values():
            choix = _texte(ligne[exclusion])
            if choix == OUI:
                parametre[exclusion] = True
            elif choix not in ("", NON):
                return None, f"{exclusion} : {OUI} ou {NON} est attendu"
        return parametre or None, None
    return None, None


def _sans_exclusion_fausse(parametre):
    """Paramètre comparable à une saisie : une exclusion à false équivaut à son absence."""
    if isinstance(parametre, dict):
        return {cle: valeur for cle, valeur in parametre.items() if valeur is not False}
    return parametre


def _proposition(nom: str, ligne: dict):
    """Règle proposée par l'outil sur une ligne, None si la proposition est « aucune »."""
    if _texte(ligne["proposition"]) in ("", AUCUNE):
        return None
    if nom == "decimales":
        nombre = _nombre_saisi(ligne["proposition"])
        return nombre if isinstance(nombre, int) and nombre >= 0 else None
    if nom == "bornes":
        mini = _nombre_saisi(ligne["proposition_min"])
        maxi = _nombre_saisi(ligne["proposition_max"])
        return None if mini is None or maxi is None else {"min": mini, "max": maxi}
    return True if _texte(ligne["proposition"]) == OUI else None


def _importer_type(
    nom: str, lignes: list[tuple[int, dict]], dictionnaire: dict, nouveau: dict
) -> tuple[list[str], list[str]]:
    """Applique les lignes d'une feuille de règles (décimales, bornes ou clé de Luhn)
    au nouveau contenu, et rend les problèmes et les avertissements."""
    feuille = FEUILLES_TYPE[nom]
    regles = nouveau.setdefault(CLE_REGLES_COMPLEMENTAIRES, {})
    ecartees = nouveau.setdefault(CLE_ECARTEES, {}).setdefault(nom, {})
    commentaires = nouveau.setdefault(CLE_COMMENTAIRES, {}).setdefault(nom, {})
    problemes, avertissements, vues = [], [], {}
    for numero, ligne in lignes:
        table, colonne = _texte(ligne["table"]), _texte(ligne["colonne"])
        ou = f"feuille « {feuille} », ligne {numero} ({table}.{colonne})"
        if colonne not in dictionnaire.get(table, {}):
            problemes.append(f"{ou} : colonne inconnue du dictionnaire, formulaire à réexporter")
            continue
        if (table, colonne) in vues:
            problemes.append(f"{ou} : colonne déjà présente ligne {vues[(table, colonne)]}")
            continue
        vues[(table, colonne)] = numero
        statut = _texte(ligne["statut"])
        if statut not in STATUTS:
            problemes.append(f"{ou} : statut {statut!r} inconnu (choisir dans le menu)")
            continue
        saisie, probleme = _saisie(nom, ligne)
        actuelle = regles.get(table, {}).get(colonne, {}).get(nom)
        if statut != STATUT_DOCUMENTE and (probleme or (
            saisie is not None and saisie != _sans_exclusion_fausse(actuelle)
        )):
            avertissements.append(
                f"{ou} : valeurs saisies ignorées (statut {statut}, seul le statut "
                f"{STATUT_DOCUMENTE} prend les valeurs saisies)"
            )
        parametre = None
        if statut == STATUT_DOCUMENTE:
            if probleme:
                problemes.append(f"{ou} : {probleme}")
                continue
            parametre = True if nom == "cle_luhn" else saisie
            if parametre is None:
                problemes.append(f"{ou} : statut {STATUT_DOCUMENTE} sans règle saisie")
                continue
        elif statut == STATUT_VALIDE:
            parametre = _proposition(nom, ligne)
            if parametre is None:
                problemes.append(
                    f"{ou} : statut {STATUT_VALIDE} impossible, aucune proposition (choisir "
                    f"{STATUT_DOCUMENTE} et donner la règle, ou {STATUT_INVALIDE})"
                )
                continue
        if parametre is not None:
            probleme = _probleme_parametre(nom, parametre)
            if probleme:
                problemes.append(f"{ou} : {probleme}")
                continue
        # Nouvel état de la ligne : la règle, le refus mémorisé, le commentaire.
        regles_colonne = regles.setdefault(table, {}).setdefault(colonne, {})
        if parametre is None:
            regles_colonne.pop(nom, None)
        else:
            regles_colonne[nom] = parametre
        refus = [c for c in ecartees.get(table, []) if c != colonne]
        if statut == STATUT_INVALIDE:
            refus.append(colonne)
        ecartees[table] = refus
        commentaire = _texte(ligne["commentaire"])
        if commentaire:
            commentaires.setdefault(table, {})[colonne] = commentaire
        else:
            commentaires.get(table, {}).pop(colonne, None)
    return problemes, avertissements


def _colonnes_groupe(texte: str) -> list[str]:
    return [colonne.strip() for colonne in texte.split(",")]


def _importer_doublons(
    lignes: list[tuple[int, dict]],
    lignes_tables: list[tuple[int, dict]],
    dictionnaire: dict,
    contenu: dict,
    nouveau: dict,
) -> list[str]:
    """Applique les feuilles des doublons et des tables au nouveau contenu, et rend
    les problèmes.

    Les déclarations d'une table du dictionnaire sont refaites d'après le
    formulaire; celles d'une table hors du dictionnaire restent telles quelles.
    """
    problemes = []
    declarations = _section(contenu, CLE_DOUBLONS)
    retenus = {table: [] for table in dictionnaire}
    refuses = {table: [] for table in dictionnaire}
    commentaires = {table: {} for table in dictionnaire}
    en_vigueur_vus = {table: set() for table in dictionnaire}
    for numero, ligne in lignes:
        ou = f"feuille « {FEUILLE_DOUBLONS} », ligne {numero}"
        table, origine = _texte(ligne["table"]), _texte(ligne["origine"])
        statut, type_affiche = _texte(ligne["statut"]), _texte(ligne["type"])
        if table not in dictionnaire:
            problemes.append(f"{ou} : table {table!r} inconnue du dictionnaire")
            continue
        colonnes = _colonnes_groupe(_texte(ligne["colonnes"]))
        ou = f"{ou} ({table}, {texte_groupe(colonnes)})"
        avant = len(problemes)
        if origine and origine not in ORIGINES:
            problemes.append(f"{ou} : origine {origine!r} modifiée, formulaire à réexporter")
        if type_affiche not in TYPES_DOUBLONS:
            problemes.append(f"{ou} : type {type_affiche!r} inconnu (choisir dans le menu)")
        if statut not in STATUTS:
            problemes.append(f"{ou} : statut {statut!r} inconnu (choisir dans le menu)")
        elif not origine and statut != STATUT_DOCUMENTE:
            problemes.append(
                f"{ou} : une ligne ajoutée prend le statut {STATUT_DOCUMENTE} (statut {statut})"
            )
        if "" in colonnes:
            problemes.append(
                f"{ou} : colonnes attendues, séparées par une virgule (par exemple « a, b »)"
            )
        else:
            inconnues = [c for c in colonnes if c not in dictionnaire[table]]
            if inconnues:
                problemes.append(f"{ou} : colonnes inconnues de la table ({', '.join(inconnues)})")
            if len(set(colonnes)) < len(colonnes):
                problemes.append(f"{ou} : une colonne est répétée dans le groupe")
        if len(problemes) > avant:
            continue
        if origine == ORIGINE_EN_VIGUEUR:
            en_vigueur_vus[table].add(frozenset(colonnes))
        if statut in STATUTS_RETENUS:
            retenus[table].append((TYPES_DOUBLONS[type_affiche], colonnes, numero))
        elif statut == STATUT_INVALIDE:
            refuses[table].append((colonnes, numero))
        commentaire = _texte(ligne["commentaire"])
        if commentaire:
            commentaires[table][texte_groupe(colonnes)] = commentaire

    # Un groupe en vigueur sans sa ligne serait retiré sans que le métier l'ait dit.
    for table in dictionnaire:
        for nom, groupe in _groupes_en_vigueur(declarations.get(table, {})):
            if frozenset(groupe) not in en_vigueur_vus[table]:
                problemes.append(
                    f"feuille « {FEUILLE_DOUBLONS} » : la ligne du groupe en vigueur "
                    f"{table}, {texte_groupe(groupe)} manque (ligne supprimée ?), formulaire "
                    "à réexporter"
                )

    identiques = {}
    for numero, ligne in lignes_tables:
        ou = f"feuille « {FEUILLE_TABLES} », ligne {numero}"
        table, choix = _texte(ligne["table"]), _texte(ligne["identiques_hors_clé"])
        if table not in dictionnaire:
            problemes.append(f"{ou} : table {table!r} inconnue du dictionnaire")
        elif choix not in (OUI, NON):
            problemes.append(f"{ou} ({table}) : {OUI} ou {NON} est attendu")
        else:
            identiques[table] = choix

    nouvelles = {}
    for table in dictionnaire:
        vus = {}
        for nom, groupe, numero in retenus[table]:
            vus.setdefault(frozenset(groupe), []).append(numero)
        for groupe, numero in refuses[table]:
            vus.setdefault(frozenset(groupe), []).append(numero)
        for groupe, numeros in vus.items():
            if len(numeros) > 1:
                problemes.append(
                    f"feuille « {FEUILLE_DOUBLONS} » : {table}, colonnes "
                    f"{', '.join(sorted(groupe))} présentes sur plusieurs lignes "
                    f"({', '.join(map(str, numeros))})"
                )
        cles = [(groupe, numero) for nom, groupe, numero in retenus[table] if nom == "cle"]
        if len(cles) > 1:
            problemes.append(
                f"feuille « {FEUILLE_DOUBLONS} » : {table}, une seule clé par table (lignes "
                f"{', '.join(str(numero) for _, numero in cles)})"
            )
        declaration = {}
        if cles:
            declaration["cle"] = cles[0][0]
        for nom in ("unique", "presume_unique"):
            groupes = [groupe for n, groupe, _ in retenus[table] if n == nom]
            if groupes:
                declaration[nom] = groupes
        ancienne = declarations.get(table, {})
        choix = identiques.get(
            table, NON if ancienne.get(REGLE_IDENTIQUES) is False else OUI
        )
        if choix == NON:
            if "cle" not in declaration:
                problemes.append(
                    f"feuille « {FEUILLE_TABLES} » ({table}) : {NON} sans clé déclarée "
                    f"(déclarer une clé, ou choisir {OUI})"
                )
            declaration[REGLE_IDENTIQUES] = False
        if declaration:
            nouvelles[table] = declaration
    for table, declaration in declarations.items():
        if table not in dictionnaire:
            nouvelles[table] = declaration
    nouveau[CLE_DOUBLONS] = nouvelles
    nouveau.setdefault(CLE_ECARTEES, {})[REGLE_DOUBLONS] = {
        **_ecartees(contenu, REGLE_DOUBLONS),
        **{table: [groupe for groupe, _ in refuses[table]] for table in dictionnaire},
    }
    nouveau.setdefault(CLE_COMMENTAIRES, {})[REGLE_DOUBLONS] = {
        **_commentaires(contenu, REGLE_DOUBLONS),
        **commentaires,
    }
    return problemes


def _rangs(dictionnaire: dict) -> tuple[dict, dict]:
    tables = {table: rang for rang, table in enumerate(dictionnaire)}
    colonnes = {
        (table, colonne): rang
        for table, cols in dictionnaire.items()
        for rang, colonne in enumerate(cols)
    }
    return tables, colonnes


def _trier(section: dict, ordre: dict) -> dict:
    """Clés connues dans l'ordre donné, puis les autres dans leur ordre."""
    connues = sorted((cle for cle in section if cle in ordre), key=ordre.get)
    return {cle: section[cle] for cle in connues + [c for c in section if c not in ordre]}


def _ordonner(contenu: dict, dictionnaire: dict) -> dict:
    """Contenu dans l'ordre du dictionnaire (tables puis colonnes), sans section,
    table ni colonne vide."""
    rang_tables, rang_colonnes = _rangs(dictionnaire)

    def colonnes_triees(table, section):
        ordre = {c: rang for (t, c), rang in rang_colonnes.items() if t == table}
        return _trier(section, ordre)

    ordre_types = {nom: rang for rang, nom in enumerate(REGLES_COMPLEMENTAIRES)}
    resultat = {}
    regles = {}
    complementaires = _trier(_section(contenu, CLE_REGLES_COMPLEMENTAIRES), rang_tables)
    for table, colonnes in complementaires.items():
        triees = {
            colonne: _trier(types, ordre_types)
            for colonne, types in colonnes_triees(table, colonnes or {}).items()
            if types
        }
        if triees:
            regles[table] = triees
    if regles:
        resultat[CLE_REGLES_COMPLEMENTAIRES] = regles
    doublons = _trier(_section(contenu, CLE_DOUBLONS), rang_tables)
    if doublons:
        resultat[CLE_DOUBLONS] = doublons
    ordre_sections = {nom: rang for rang, nom in enumerate(TYPES_FORMULAIRE + (REGLE_DOUBLONS,))}
    for cle in (CLE_ECARTEES, CLE_COMMENTAIRES):
        section = {}
        for nom, tables in _trier(_section(contenu, cle), ordre_sections).items():
            par_table = {}
            for table, valeur in _trier(tables or {}, rang_tables).items():
                if cle == CLE_ECARTEES and nom != REGLE_DOUBLONS:
                    ordre = {c: rang for (t, c), rang in rang_colonnes.items() if t == table}
                    valeur = sorted(valeur, key=lambda c: ordre.get(c, len(ordre)))
                elif cle == CLE_COMMENTAIRES and nom != REGLE_DOUBLONS:
                    valeur = colonnes_triees(table, valeur)
                if valeur:
                    par_table[table] = valeur
            if par_table:
                section[nom] = par_table
        if section:
            resultat[cle] = section
    return resultat


def _etats_regles(contenu: dict, nom: str) -> dict:
    """État de chaque règle d'un type, en texte, par (table, colonne)."""
    etats = {}
    for table, colonnes in _ecartees(contenu, nom).items():
        for colonne in colonnes:
            etats[(table, colonne)] = ETAT_ECARTEE
    for table, colonnes in _section(contenu, CLE_REGLES_COMPLEMENTAIRES).items():
        for colonne, types in (colonnes or {}).items():
            if isinstance(types, dict) and nom in types:
                etats[(table, colonne)] = _parametre_en_texte(nom, types[nom])
    return etats


def _etats_doublons(contenu: dict) -> dict:
    """État de chaque groupe de doublons (type affiché ou « écartée »), par (table,
    colonnes en texte); et choix des lignes identiques hors clé, par (table, None)."""
    etats = {}
    for table, groupes in _ecartees(contenu, REGLE_DOUBLONS).items():
        for groupe in groupes:
            etats[(table, texte_groupe(groupe), REGLE_DOUBLONS)] = ETAT_ECARTEE
    for table, declaration in _section(contenu, CLE_DOUBLONS).items():
        for nom, groupe in _groupes_en_vigueur(declaration):
            etats[(table, texte_groupe(groupe), REGLE_DOUBLONS)] = GROUPES_DOUBLONS[nom]
        if declaration.get(REGLE_IDENTIQUES) is False:
            etats[(table, None, REGLE_IDENTIQUES)] = NON
    return etats


def comparer_controles(avant: dict, apres: dict, dictionnaire: dict) -> pd.DataFrame:
    """Rapport des règles qui changent entre deux contenus de config/controles.yaml.

    Une ligne par règle (décimales, bornes, clé de Luhn), par groupe de doublons
    (colonnes séparées par une virgule) et par table dont la recherche des lignes
    identiques hors clé change, dans l'ordre du dictionnaire. Les motifs et les
    commentaires n'y figurent pas.
    """
    rang_tables, rang_colonnes = _rangs(dictionnaire)
    lignes = []
    for nom in TYPES_FORMULAIRE:
        etats_avant, etats_apres = _etats_regles(avant, nom), _etats_regles(apres, nom)
        for table, colonne in etats_avant.keys() | etats_apres.keys():
            ancien, nouveau = etats_avant.get((table, colonne)), etats_apres.get((table, colonne))
            if ancien != nouveau:
                lignes.append((table, colonne, nom, ancien, nouveau))
    etats_avant, etats_apres = _etats_doublons(avant), _etats_doublons(apres)
    for table, colonnes, nom in etats_avant.keys() | etats_apres.keys():
        cle = (table, colonnes, nom)
        defaut = OUI if nom == REGLE_IDENTIQUES else None
        ancien, nouveau = etats_avant.get(cle, defaut), etats_apres.get(cle, defaut)
        if ancien != nouveau:
            lignes.append((table, colonnes, nom, ancien, nouveau))
    ordre_regles = {nom: rang for rang, nom in enumerate(
        TYPES_FORMULAIRE + (REGLE_DOUBLONS, REGLE_IDENTIQUES)
    )}
    lignes.sort(key=lambda l: (
        rang_tables.get(l[0], len(rang_tables)),
        l[0],
        ordre_regles[l[2]],
        rang_colonnes.get((l[0], l[1]), len(rang_colonnes)),
        l[1] or "",
    ))
    return pd.DataFrame(lignes, columns=list(COLONNES_CHANGEMENTS))


def importer_formulaire(
    chemin: str | Path, dictionnaire: dict, contenu: dict, *, empreinte: str
) -> Formulaire:
    """Lit un formulaire revu par le métier et contrôle chaque ligne, sans rien écrire.

    `contenu` est le contenu actuel de config/controles.yaml
    (`controles.lire_fichier_controles`) et `empreinte` son empreinte
    (`empreinte_controles`) : un formulaire exporté avant une modification du
    fichier (dont l'application d'un autre formulaire) est refusé, il annulerait
    des décisions prises depuis.

    Statuts d'une ligne de règle : valide adopte la proposition (refusé si elle est
    « aucune »); documenté prend les valeurs saisies; invalide retire la règle et
    mémorise le refus sous `ecartees`; observé retire la règle sans mémoriser de
    refus. Une valeur saisie sur une ligne qui n'est pas documentée est ignorée,
    avec un avertissement. Les règles des colonnes que le formulaire ne présente
    pas, et les motifs, sont repris tels quels.

    Tous les problèmes bloquants sont listés en une fois dans une ValueError, avec
    la feuille et le numéro de ligne Excel. Les avertissements ne bloquent pas
    l'import.
    """
    chemin = Path(chemin)
    classeur = load_workbook(chemin, read_only=True, data_only=True)
    try:
        try:
            lignes = {
                nom: _lire_feuille(classeur, FEUILLES_TYPE[nom], COLONNES_TYPE[nom])
                for nom in TYPES_FORMULAIRE
            }
            lignes_d = _lire_feuille(classeur, FEUILLE_DOUBLONS, COLONNES_DOUBLONS)
            lignes_t = _lire_feuille(classeur, FEUILLE_TABLES, COLONNES_TABLES)
            repere = _lire_empreinte(classeur)
        except ValueError as erreur:
            raise ValueError(f"Formulaire invalide ({chemin})\n  {erreur}") from None
    finally:
        classeur.close()
    if repere != empreinte:
        raise ValueError(
            f"Formulaire périmé ({chemin}) : config/controles.yaml a changé depuis son "
            f"export (empreinte {repere} à l'export, {empreinte} aujourd'hui). Ce "
            "formulaire a déjà été appliqué, ou le fichier a été modifié depuis : à "
            "réexporter."
        )

    nouveau = copy.deepcopy(contenu)
    problemes, avertissements = [], []
    for nom in TYPES_FORMULAIRE:
        problemes_type, avertissements_type = _importer_type(
            nom, lignes[nom], dictionnaire, nouveau
        )
        problemes += problemes_type
        avertissements += avertissements_type
    problemes += _importer_doublons(lignes_d, lignes_t, dictionnaire, contenu, nouveau)
    nouveau = _ordonner(nouveau, dictionnaire)
    if not problemes:
        problemes = _problemes_contenu(nouveau)
    if problemes:
        raise ValueError(
            f"Formulaire invalide ({chemin}), {len(problemes)} problèmes\n  "
            + "\n  ".join(problemes)
        )
    return Formulaire(nouveau, comparer_controles(contenu, nouveau, dictionnaire), avertissements)


# --- Écriture de config/controles.yaml ------------------------------------------

ENTETE_CONTROLES = """\
# Règles de contrôle données par le métier, que le dictionnaire des données ne peut
# pas déduire des fichiers. Une forme fixe (code postal, numéro à longueur fixe) ne
# se déclare pas ici mais dans le classeur de revue du dictionnaire (règle format).
# Ce fichier est réécrit en entier par le formulaire des règles de contrôle (notebook
# 04), qui ne garde pas les commentaires ajoutés à la main. Les motifs s'écrivent à
# la main, le formulaire les reprend tels quels.
#
# Règles possibles pour une colonne
#   decimales  nombre maximal de décimales
#   bornes     minimum et maximum admis, bornes incluses (min, max ou les deux);
#              min_exclu: true ou max_exclu: true exclut la borne
#   motif      expression régulière que la valeur entière doit respecter
#   cle_luhn   clé de contrôle de Luhn valide (true)
"""
COMMENTAIRE_DOUBLONS = """\
# Doublons, déclarés d'après ce que dit le métier.
# cle = identifiant d'une ligne; unique = colonnes qui ne doivent pas se répéter;
# presume_unique = colonnes en principe uniques, une répétition est à arbitrer;
# identique_hors_cle false = deux lignes pareilles hors clé sont normales dans cette table.
"""
COMMENTAIRE_ECARTEES = """\
# Propositions du formulaire écartées par le métier, qui ne sont plus proposées
# (sans effet sur les contrôles).
"""
COMMENTAIRE_COMMENTAIRES = """\
# Commentaires du métier saisis dans le formulaire (sans effet sur les contrôles).
"""


def _yaml(valeur) -> str:
    """Valeur YAML sur une ligne : un scalaire, ou une liste ou un dictionnaire en ligne."""
    options = {"default_flow_style": True, "allow_unicode": True, "width": 10**9,
               "sort_keys": False}
    texte = yaml.safe_dump(valeur, **options)
    if "\n" in texte.removesuffix("\n...\n").removesuffix("\n") and isinstance(valeur, str):
        texte = yaml.safe_dump(valeur, default_style='"', **options)
    texte = texte.removesuffix("\n...\n").removesuffix("\n")
    if "\n" in texte:
        raise ValueError(f"valeur {valeur!r} : impossible de l'écrire sur une ligne")
    return texte


def texte_controles(contenu: dict) -> str:
    """Texte de config/controles.yaml pour un contenu, dans l'ordre de ses clés.

    Un en-tête de commentaires standard, puis les règles (une colonne par ligne,
    règles en ligne), les doublons, les propositions écartées et les commentaires
    du métier. La relecture du texte redonne exactement le contenu.
    """
    blocs = [ENTETE_CONTROLES]
    regles = _section(contenu, CLE_REGLES_COMPLEMENTAIRES)
    if regles:
        lignes = [f"{CLE_REGLES_COMPLEMENTAIRES}:"]
        for table, colonnes in regles.items():
            lignes.append(f"  {_yaml(table)}:")
            lignes += [f"    {_yaml(c)}: {_yaml(types)}" for c, types in colonnes.items()]
        blocs.append("\n".join(lignes) + "\n")
    doublons = _section(contenu, CLE_DOUBLONS)
    if doublons:
        lignes = [f"{CLE_DOUBLONS}:"]
        for table, declaration in doublons.items():
            lignes.append(f"  {_yaml(table)}:")
            for cle, valeur in declaration.items():
                if cle in ("unique", "presume_unique"):
                    lignes.append(f"    {cle}:")
                    lignes += [f"      - {_yaml(groupe)}" for groupe in valeur]
                else:
                    lignes.append(f"    {cle}: {_yaml(valeur)}")
        blocs.append("\n" + COMMENTAIRE_DOUBLONS + "\n".join(lignes) + "\n")
    for cle, commentaire in (
        (CLE_ECARTEES, COMMENTAIRE_ECARTEES), (CLE_COMMENTAIRES, COMMENTAIRE_COMMENTAIRES)
    ):
        section = _section(contenu, cle)
        if not section:
            continue
        lignes = [f"{cle}:"]
        for nom, tables in section.items():
            lignes.append(f"  {_yaml(nom)}:")
            for table, valeur in tables.items():
                if cle == CLE_ECARTEES and nom == REGLE_DOUBLONS:
                    lignes.append(f"    {_yaml(table)}:")
                    lignes += [f"      - {_yaml(groupe)}" for groupe in valeur]
                elif cle == CLE_ECARTEES:
                    lignes.append(f"    {_yaml(table)}: {_yaml(valeur)}")
                else:
                    lignes.append(f"    {_yaml(table)}:")
                    lignes += [f"      {_yaml(c)}: {_yaml(t)}" for c, t in valeur.items()]
        blocs.append("\n" + commentaire + "\n".join(lignes) + "\n")
    texte = "\n".join(blocs)
    if yaml.safe_load(texte) != {cle: valeur for cle, valeur in contenu.items() if valeur}:
        raise ValueError("relecture du fichier des contrôles écrit différente du contenu")
    return texte


def _problemes_contenu(contenu: dict) -> list[str]:
    """Problèmes de structure d'un contenu de config/controles.yaml."""
    problemes = [
        f"clé inconnue {cle!r} du fichier des contrôles"
        for cle in contenu
        if cle not in CLES_FICHIER_CONTROLES
    ]
    if CLE_REGLES_COMPLEMENTAIRES in contenu:
        problemes += [
            f"règles complémentaires, {probleme}"
            for probleme in problemes_regles_complementaires(contenu[CLE_REGLES_COMPLEMENTAIRES])
        ]
    if CLE_DOUBLONS in contenu:
        problemes += [
            f"doublons, {probleme}"
            for probleme in problemes_declarations_doublons(contenu[CLE_DOUBLONS])
        ]
    return problemes


class EcritureControles(NamedTuple):
    """Résultat de `ecrire_controles` : le fichier, sa copie datée (None s'il n'y
    avait pas de fichier ou si rien n'a changé), et s'il a été réécrit."""

    chemin: Path
    sauvegarde: Path | None
    ecrit: bool


def ecrire_controles(
    contenu: dict,
    chemin: str | Path | None = None,
    *,
    empreinte: str,
    dossier: str | Path | None = None,
) -> EcritureControles:
    """Réécrit config/controles.yaml avec le contenu donné (`Formulaire.contenu`).

    `empreinte` est celle du fichier lue avant l'import du formulaire : si le
    fichier a changé depuis, rien n'est écrit. L'ancien fichier est d'abord copié
    dans `dossier` (par défaut data/config/sauvegardes, hors du dépôt), sous le nom
    `controles_<AAAA-MM-JJ>_<HHMMSS>.yaml`; une copie déjà présente sous ce nom
    n'est jamais remplacée, et rien n'est alors écrit. Un contenu identique au
    fichier ne le réécrit pas. Le fichier est écrit en UTF-8 avec des fins de
    ligne LF.
    """
    chemin = Path(chemin) if chemin is not None else chemin_regles_complementaires()
    actuelle = empreinte_controles(chemin)
    if actuelle != empreinte:
        raise ValueError(
            f"{chemin} a changé depuis la lecture du formulaire (empreinte {empreinte}, "
            f"{actuelle} aujourd'hui) : écriture refusée, formulaire à réexporter"
        )
    problemes = _problemes_contenu(contenu)
    if problemes:
        raise ValueError(
            "Contenu du fichier des contrôles invalide\n  " + "\n  ".join(problemes)
        )
    texte = texte_controles(contenu)
    if chemin.is_file() and chemin.read_bytes().replace(b"\r\n", b"\n") == texte.encode():
        return EcritureControles(chemin, None, False)
    sauvegarde = None
    if chemin.is_file():
        dossier = Path(dossier) if dossier is not None else dossier_sauvegardes()
        instant = module_dictionnaire._maintenant()
        sauvegarde = dossier / f"{chemin.stem}_{instant:%Y-%m-%d_%H%M%S}{chemin.suffix}"
        dossier.mkdir(parents=True, exist_ok=True)
        try:
            with open(sauvegarde, "xb") as flux:
                flux.write(chemin.read_bytes())
        except FileExistsError:
            raise FileExistsError(
                f"{sauvegarde} existe déjà : écriture refusée, rien n'a été modifié "
                "(relancer dans une seconde)"
            ) from None
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "w", encoding="utf-8", newline="\n") as flux:
        flux.write(texte)
    return EcritureControles(chemin, sauvegarde, True)
