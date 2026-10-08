"""Génération du dictionnaire des données à partir des données observées.

Ce module ne contient rien de propre à un client. Tout ce qui est généré a le
statut « observé »; seul le métier peut en décider autrement, par la revue.

Chaque règle distingue la `proposition` (ce que la génération déduit des données)
de la `regle` en vigueur (ce que les contrôles appliqueront). Les deux sont égales
tant que la règle n'a pas été revue.
"""

from __future__ import annotations

import numbers
import os
import unicodedata
from copy import deepcopy
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from . import racine_projet
from .confidentialite import charger_sensibilite, est_sensible, verifier_sensibilite
from .profilage import COLONNES_LIGNAGE, _NATURES_TEXTE, profiler_colonne

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
    return {
        "liste_fermee": False,
        "motif": motif,
        "valeurs": [],
        "effectifs": [],
        "a_arbitrer": [],
    }


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

    Conditions, vérifiées dans cet ordre (la première qui échoue donne le motif) :
    colonne non sensible, au moins `effectif_min` valeurs renseignées, nature
    dominante « texte », au plus `max_valeurs` valeurs principales (une valeur est
    principale si elle pèse au moins `part_min` des valeurs renseignées), et
    valeurs principales couvrant au moins `couverture_min` des valeurs renseignées.

    Les valeurs non principales ne sont jamais déclarées valides : elles sont
    rendues dans `a_arbitrer` avec leur effectif. `effectifs` donne l'effectif des
    valeurs principales, dans le même ordre. Une colonne sensible n'expose
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

    nature = proposer_nature(serie)["regle"]
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
        "effectifs": [n for _, n in principales],
        "a_arbitrer": [{"valeur": v, "effectif": n} for v, n in autres],
    }

# Seuils du critère obligatoire, facultatif, presque toujours vide (validés le
# 07/10/2026, à confirmer sur le profil réel).
VIDES_MAX_OBLIGATOIRE = 0.02
VIDES_MIN_PRESQUE_VIDE = 0.98


def _regle(regle: str, motif: str, a_arbitrer: dict) -> dict:
    return {"regle": regle, "motif": motif, "a_arbitrer": a_arbitrer}


def proposer_obligatoire(
    serie: pd.Series,
    *,
    vides_max: float = VIDES_MAX_OBLIGATOIRE,
    presque_vide_min: float = VIDES_MIN_PRESQUE_VIDE,
    effectif_min: int = EFFECTIF_MIN,
) -> dict:
    """Propose le caractère obligatoire d'une colonne d'après sa part de vides.

    Les trois formes de vide (None ou NaN, chaîne vide, chaîne d'espaces) sont
    comptées ensemble. Règles rendues, dans cet ordre :
    « toujours vide » (100 % de vides), « obligatoire » si aucune valeur n'est vide,
    « à décider » sous `effectif_min` lignes dès qu'il y a un vide, puis
    « obligatoire » jusqu'à `vides_max` de vides inclus (les vides vont dans
    `a_arbitrer`), « presque toujours vide » à partir de `presque_vide_min` (les
    cellules renseignées vont dans `a_arbitrer`) et « facultatif » entre les deux.
    """
    total = len(serie)
    if total == 0:
        return _regle("à décider", "aucune ligne", {})
    renseignees = len(_valeurs_renseignees(serie))
    vides = total - renseignees
    part = vides / total

    if renseignees == 0:
        return _regle("toujours vide", "100 % de vides", {})
    if vides == 0:
        return _regle("obligatoire", "aucune valeur vide", {"vides": 0})
    if total < effectif_min:
        return _regle(
            "à décider",
            f"effectif insuffisant ({total} lignes, {effectif_min} requises)",
            {"vides": vides},
        )

    motif = f"{100 * part:.2f} % de vides"
    if part <= vides_max:
        return _regle("obligatoire", motif, {"vides": vides})
    if part >= presque_vide_min:
        return _regle(
            "presque toujours vide", motif, {"renseignees": renseignees}
        )
    return _regle("facultatif", motif, {})

def proposer_nature(
    serie: pd.Series,
    profil: dict | None = None,
    *,
    couverture_min: float = COUVERTURE_MIN,
    part_min: float = PART_MIN,
    effectif_min: int = EFFECTIF_MIN,
) -> dict:
    """Propose la nature d'une colonne d'après la nature dominante du profil.

    Règles rendues :
    la nature dominante si elle couvre au moins `couverture_min` des valeurs
    renseignées (les valeurs hors nature vont dans `a_arbitrer`), « à décider » entre
    `part_min` et `couverture_min`, et « texte » si aucune nature spécifique ne couvre
    `part_min` (les valeurs conformes à une nature sont alors des coïncidences).
    Sous `effectif_min` valeurs renseignées, « à décider » dès qu'une valeur est hors
    nature. `profil` évite de recalculer `profiler_colonne`.
    """
    if profil is None:
        profil = profiler_colonne(serie)
    nature = profil["nature_dominante"]
    if nature == "aucune valeur":
        return _regle("à décider", "aucune valeur renseignée", {})

    renseignees = (
        profil["nb_lignes"]
        - profil["nb_none_nan"]
        - profil["nb_chaine_vide"]
        - profil["nb_espaces_seuls"]
    )
    hors = profil["nb_hors_nature"]
    couverture = (renseignees - hors) / renseignees
    if nature != "texte" and couverture < part_min:
        nature, hors, couverture = "texte", 0, 1.0

    if hors == 0:
        return _regle(nature, "toutes les valeurs renseignées sont de cette nature", {"hors_nature": 0})

    detail = {"nature_dominante": nature, "hors_nature": hors}
    if renseignees < effectif_min:
        return _regle(
            "à décider",
            f"effectif insuffisant ({renseignees} valeurs renseignées, {effectif_min} requises)",
            detail,
        )
    if couverture >= couverture_min:
        return _regle(
            nature,
            f"{100 * couverture:.2f} % des valeurs renseignées",
            {"hors_nature": hors},
        )
    return _regle(
        "à décider",
        f"nature dominante {nature} sur {100 * couverture:.1f} % des valeurs "
        f"renseignées (minimum {100 * couverture_min:.0f} %)",
        detail,
    )


STATUT_INITIAL = "observé"
STATUTS = ("observé", "valide", "invalide", "documenté")
REGLES = ("obligatoire", "nature", "valeurs")

A_DECIDER = "à décider"
# Règle en vigueur d'une proposition écartée par le métier (statut « invalide ») :
# aucun contrôle de ce type ne portera sur la colonne.
REGLE_ECARTEE = "aucune"
# Règles que le métier peut donner lui-même, avec le statut « documenté ».
REGLES_RETENUES = {
    "obligatoire": ("obligatoire", "facultatif", "toujours vide"),
    "nature": ("texte", "nombre natif", "date native", *_NATURES_TEXTE),
}

# Règle `valeurs` : la colonne n'accepte qu'une liste fermée de valeurs, ou non.
LISTE_FERMEE = "liste fermée"
AUCUNE_LISTE = "aucune"

# Origine d'une valeur de la liste d'une colonne.
ORIGINE_LISTE = "liste proposée"
ORIGINE_A_ARBITRER = "à arbitrer"
ORIGINE_AJOUT = "ajoutée"
ORIGINES = (ORIGINE_LISTE, ORIGINE_A_ARBITRER, ORIGINE_AJOUT)


def _regle_observee(proposition: str, motif: str, a_arbitrer: dict) -> dict:
    """Règle proposée et pas encore revue : la règle en vigueur est la proposition."""
    return {
        "regle": proposition,
        "proposition": proposition,
        "statut": STATUT_INITIAL,
        "motif": motif,
        "a_arbitrer": a_arbitrer,
        "commentaire": "",
        "revu_le": None,
    }


def _valeur_observee(valeur: str, origine: str, effectif: int) -> dict:
    return {
        "valeur": valeur,
        "origine": origine,
        "effectif": effectif,
        "statut": STATUT_INITIAL,
        "commentaire": "",
        "revu_le": None,
        "remplacement": None,
    }


def generer_colonne(
    serie: pd.Series,
    table: str,
    colonne: str,
    sensibles: dict[str, frozenset[str]],
) -> dict:
    """Règles proposées pour une colonne, toutes au statut « observé ».

    Trois règles sont rendues : `obligatoire`, `nature` et `valeurs`. Chacune porte la
    proposition, la règle en vigueur (égale à la proposition), son statut, le motif
    de la proposition et les écarts à arbitrer. La règle `valeurs` vaut « liste
    fermée » ou « aucune » et porte en plus la `liste` des valeurs observées : les
    valeurs principales (origine « liste proposée ») puis les valeurs rares (origine
    « à arbitrer »), chacune avec son effectif et son propre statut. Une colonne
    sensible n'expose aucune valeur : sa liste est vide.
    """
    obligatoire = proposer_obligatoire(serie)
    nature = proposer_nature(serie)
    liste = proposer_liste(serie, table, colonne, sensibles)
    if liste["liste_fermee"]:
        valeurs = _regle_observee(
            LISTE_FERMEE, liste["motif"], {"valeurs": len(liste["a_arbitrer"])}
        )
        valeurs["liste"] = [
            _valeur_observee(valeur, ORIGINE_LISTE, effectif)
            for valeur, effectif in zip(liste["valeurs"], liste["effectifs"])
        ] + [
            _valeur_observee(element["valeur"], ORIGINE_A_ARBITRER, element["effectif"])
            for element in liste["a_arbitrer"]
        ]
    else:
        valeurs = _regle_observee(AUCUNE_LISTE, liste["motif"], {})
        valeurs["liste"] = []
    return {
        "obligatoire": _regle_observee(
            obligatoire["regle"], obligatoire["motif"], obligatoire["a_arbitrer"]
        ),
        "nature": _regle_observee(nature["regle"], nature["motif"], nature["a_arbitrer"]),
        "valeurs": valeurs,
    }


def generer_table(
    donnees: pd.DataFrame,
    nom_table: str,
    sensibles: dict[str, frozenset[str]],
) -> dict:
    """Règles proposées pour chaque colonne de données (colonnes de lignage exclues)."""
    return {
        colonne: generer_colonne(donnees[colonne], nom_table, colonne, sensibles)
        for colonne in donnees.columns
        if colonne not in COLONNES_LIGNAGE
    }


def generer_dictionnaire(
    tables: dict[str, pd.DataFrame],
    sensibles: dict[str, frozenset[str]] | None = None,
) -> dict:
    """Dictionnaire proposé pour l'ensemble des tables chargées.

    La classification de sensibilité (config/sensibilite.yaml par défaut) est toujours
    appliquée et vérifiée avant le calcul, comme dans `profiler_tout` avec masquage.
    """
    if sensibles is None:
        sensibles = charger_sensibilite()
    problemes = verifier_sensibilite(tables, sensibles)
    if problemes:
        raise RuntimeError(
            "Classification de sensibilité incohérente\n  " + "\n  ".join(problemes)
        )
    return {
        nom: generer_table(donnees, nom, sensibles) for nom, donnees in tables.items()
    }

def resumer_dictionnaire(dictionnaire: dict) -> pd.DataFrame:
    """Tableau de synthèse du dictionnaire, une ligne par colonne.

    Les colonnes `obligatoire`, `nature` et `liste_fermee` donnent la règle en
    vigueur. `nb_valeurs` est le nombre de valeurs de la liste proposée et
    `nb_a_arbitrer` le nombre de valeurs à arbitrer. Sans liste, `motif_liste` dit
    pourquoi aucune n'est proposée.
    """
    lignes = []
    for table, colonnes in dictionnaire.items():
        for colonne, regles in colonnes.items():
            valeurs = regles["valeurs"]
            origines = [element["origine"] for element in valeurs["liste"]]
            lignes.append(
                {
                    "table": table,
                    "colonne": colonne,
                    "obligatoire": regles["obligatoire"]["regle"],
                    "nature": regles["nature"]["regle"],
                    "liste_fermee": valeurs["regle"] == LISTE_FERMEE,
                    "nb_valeurs": origines.count(ORIGINE_LISTE),
                    "nb_a_arbitrer": origines.count(ORIGINE_A_ARBITRER),
                    "motif_liste": valeurs["motif"],
                }
            )
    return pd.DataFrame(lignes)


# Version de la structure du fichier : 2 depuis la refonte de l'étape 2d (règle en
# vigueur distincte de la proposition, liste unique de valeurs).
STRUCTURE = 2
CHAMPS_REGLE = (
    "regle",
    "proposition",
    "statut",
    "motif",
    "a_arbitrer",
    "commentaire",
    "revu_le",
)
CHAMPS_VALEUR = (
    "valeur",
    "origine",
    "effectif",
    "statut",
    "commentaire",
    "revu_le",
    "remplacement",
)
# Statuts admis sur une valeur observée : « documenté » est réservé aux ajouts.
STATUTS_VALEUR_OBSERVEE = ("observé", "valide", "invalide")
# Statuts d'une valeur qui peut servir de remplacement à une valeur invalide.
STATUTS_CIBLE = ("valide", "documenté")


def chemin_dictionnaire() -> Path:
    """Emplacement par défaut du dictionnaire : data/config/dictionnaire.yaml.

    Le dictionnaire contient des valeurs observées dans les données : il est rangé
    avec elles, hors du dépôt.
    """
    return racine_projet() / "data" / "config" / "dictionnaire.yaml"


def _natif(valeur):
    """Copie de `valeur` en types Python natifs, seuls acceptés par l'écriture YAML."""
    if isinstance(valeur, dict):
        return {cle: _natif(element) for cle, element in valeur.items()}
    if isinstance(valeur, (list, tuple)):
        return [_natif(element) for element in valeur]
    if valeur is None or isinstance(valeur, (str, bool)):
        return valeur
    if isinstance(valeur, numbers.Integral):
        return int(valeur)
    if isinstance(valeur, numbers.Real):
        return float(valeur)
    raise TypeError(f"Type non pris en charge dans le dictionnaire : {type(valeur).__name__}")


# Journal des revues, dans le bloc `meta` : une entrée par classeur appliqué.
CHAMPS_REVUE = (
    "date",
    "classeur",
    "regles_changees",
    "valeurs_changees",
    "valeurs_ajoutees",
    "commentaires_changes",
)


def _meta(periode_fin: str) -> dict:
    return {
        "structure": STRUCTURE,
        "periode_fin": periode_fin,
        "genere_le": date.today().isoformat(),
        "seuils": {
            "max_valeurs": MAX_VALEURS,
            "part_min": PART_MIN,
            "couverture_min": COUVERTURE_MIN,
            "effectif_min": EFFECTIF_MIN,
            "vides_max_obligatoire": VIDES_MAX_OBLIGATOIRE,
            "vides_min_presque_vide": VIDES_MIN_PRESQUE_VIDE,
        },
        "revues": [],
    }


def _decrire(valeur) -> str:
    return f"{valeur!r} (type {type(valeur).__name__})"


def _statut_normalise(statut):
    return unicodedata.normalize("NFC", statut) if isinstance(statut, str) else statut


def _est_date_iso(valeur) -> bool:
    """Vrai pour un texte 'AAAA-MM-JJ' qui désigne une date réelle."""
    try:
        return date.fromisoformat(valeur).isoformat() == valeur
    except (TypeError, ValueError):
        return False


def _problemes_journal(revues) -> list[str]:
    """Problèmes du journal des revues (clé `revues` du bloc `meta`)."""
    if not isinstance(revues, list):
        return ["journal des revues : une liste est attendue"]
    problemes = []
    for rang, entree in enumerate(revues, start=1):
        ou = f"journal des revues, entrée {rang}"
        if not isinstance(entree, dict) or set(entree) != set(CHAMPS_REVUE):
            problemes.append(f"{ou} : champs attendus {', '.join(CHAMPS_REVUE)}")
            continue
        if not _est_date_iso(entree["date"]):
            problemes.append(
                f"{ou} : date {_decrire(entree['date'])}, une date 'AAAA-MM-JJ' entre "
                "guillemets est attendue"
            )
        if not isinstance(entree["classeur"], str) or entree["classeur"].strip() == "":
            problemes.append(f"{ou} : nom de classeur {_decrire(entree['classeur'])}")
        for champ in CHAMPS_REVUE[2:]:
            nombre = entree[champ]
            if isinstance(nombre, bool) or not isinstance(nombre, int) or nombre < 0:
                problemes.append(
                    f"{ou} : {champ} {_decrire(nombre)}, un entier positif ou nul est attendu"
                )
    return problemes


def _problemes_decision(ou: str, element: dict) -> list[str]:
    """Problèmes de commentaire et de date de revue, communs aux règles et aux valeurs."""
    problemes = []
    if not isinstance(element["commentaire"], str):
        problemes.append(
            f"{ou} : commentaire {_decrire(element['commentaire'])}, un texte est attendu"
        )
    revu_le = element["revu_le"]
    if revu_le is None:
        if element["statut"] in STATUTS and element["statut"] != STATUT_INITIAL:
            problemes.append(
                f"{ou} : statut {element['statut']} sans date de revue (revu_le)"
            )
    elif not _est_date_iso(revu_le):
        problemes.append(
            f"{ou} : revu_le {_decrire(revu_le)}, une date 'AAAA-MM-JJ' entre "
            "guillemets est attendue"
        )
    return problemes


def _problemes_liste(ou: str, regle: dict) -> list[str]:
    """Problèmes de la règle `valeurs` et de sa liste de valeurs.

    Une valeur écrite à la main sans guillemets (No, 27, 2026-03-01) est lue par
    YAML comme un booléen, un nombre ou une date : elle est rejetée ici. Une même
    valeur ne figure qu'une fois dans la liste d'une colonne. Un remplacement n'est
    admis que sur une valeur invalide et vise une valeur valide ou documentée de la
    même liste.
    """
    problemes = []
    for champ in ("regle", "proposition"):
        if regle[champ] not in (LISTE_FERMEE, AUCUNE_LISTE):
            problemes.append(
                f"{ou}, règle valeurs : {champ} {_decrire(regle[champ])} au lieu de "
                f"« {LISTE_FERMEE} » ou « {AUCUNE_LISTE} »"
            )
    liste = regle["liste"]
    if not isinstance(liste, list):
        problemes.append(f"{ou}, liste de valeurs : une liste est attendue")
        return problemes
    if regle["regle"] == LISTE_FERMEE and not liste:
        problemes.append(f"{ou}, liste de valeurs : liste fermée sans aucune valeur")

    statuts = {}
    remplacements = []
    for element in liste:
        if not isinstance(element, dict) or set(element) != set(CHAMPS_VALEUR):
            problemes.append(
                f"{ou}, liste de valeurs : champs attendus {', '.join(CHAMPS_VALEUR)}"
            )
            continue
        valeur = element["valeur"]
        if not isinstance(valeur, str):
            problemes.append(
                f"{ou}, liste de valeurs : {_decrire(valeur)} n'est pas un texte, "
                "mettre la valeur entre guillemets"
            )
            continue
        if valeur.strip() == "":
            problemes.append(f"{ou}, liste de valeurs : valeur vide ou composée d'espaces")
            continue
        if valeur in statuts:
            problemes.append(
                f"{ou}, liste de valeurs : valeur {valeur!r} présente plusieurs fois"
            )
            continue
        ici = f"{ou}, valeur {valeur!r}"
        statut = element["statut"] = _statut_normalise(element["statut"])
        statuts[valeur] = statut
        origine = element["origine"]
        if origine not in ORIGINES:
            problemes.append(f"{ici} : origine inconnue {origine!r}")
        elif origine == ORIGINE_AJOUT and statut != "documenté":
            problemes.append(f"{ici} : une valeur ajoutée doit porter le statut documenté")
        elif origine != ORIGINE_AJOUT and statut not in STATUTS_VALEUR_OBSERVEE:
            problemes.append(
                f"{ici} : statut {statut!r} impossible sur une valeur observée "
                f"(attendu {', '.join(STATUTS_VALEUR_OBSERVEE)})"
            )
        effectif = element["effectif"]
        minimum = 1 if statut == STATUT_INITIAL else 0
        if isinstance(effectif, bool) or not isinstance(effectif, int) or effectif < minimum:
            problemes.append(
                f"{ici} : effectif {_decrire(effectif)}, un entier d'au moins "
                f"{minimum} est attendu"
            )
        problemes.extend(_problemes_decision(ici, element))
        if element["remplacement"] is not None:
            remplacements.append((ici, statut, element["remplacement"]))

    for ici, statut, cible in remplacements:
        if statut != "invalide":
            problemes.append(f"{ici} : remplacement réservé au statut invalide")
        elif not isinstance(cible, str) or statuts.get(cible) not in STATUTS_CIBLE:
            problemes.append(
                f"{ici} : remplacement {_decrire(cible)} absent des valeurs valides "
                "ou documentées de la colonne"
            )
    return problemes


def _probleme_regle_en_vigueur(nom: str, regle: dict) -> str | None:
    """Incohérence entre le statut d'une règle revue et sa règle en vigueur.

    Une proposition validée est une vraie règle, une proposition écartée ne laisse
    aucune règle, et une règle donnée par le métier fait partie de `REGLES_RETENUES`.
    """
    statut, en_vigueur = regle["statut"], regle["regle"]
    if statut == "invalide" and en_vigueur != REGLE_ECARTEE:
        return (
            f"au statut invalide, la règle ({en_vigueur!r}) doit être "
            f"« {REGLE_ECARTEE} »"
        )
    if statut == "valide" and en_vigueur in (A_DECIDER, REGLE_ECARTEE):
        return f"au statut valide, la règle ne peut pas être « {en_vigueur} »"
    if statut == "documenté":
        if nom not in REGLES_RETENUES:
            return f"statut documenté impossible sur la règle {nom}"
        if en_vigueur not in REGLES_RETENUES[nom]:
            return (
                f"au statut documenté, la règle ({en_vigueur!r}) doit être parmi "
                f"{', '.join(REGLES_RETENUES[nom])}"
            )
    return None


def _verifier_et_normaliser(contenu) -> list[str]:
    """Liste tous les problèmes de structure et normalise les statuts (NFC)."""
    if not isinstance(contenu, dict) or not isinstance(contenu.get("tables"), dict):
        return ["clé « tables » absente ou mal formée"]
    problemes = []
    for table, colonnes in contenu["tables"].items():
        if not isinstance(colonnes, dict):
            problemes.append(f"{table} : liste de colonnes mal formée")
            continue
        for colonne, regles in colonnes.items():
            ou = f"{table}.{colonne}"
            if not isinstance(regles, dict) or set(regles) != set(REGLES):
                problemes.append(f"{ou} : règles attendues {', '.join(REGLES)}")
                continue
            for nom in REGLES:
                regle = regles[nom]
                champs = CHAMPS_REGLE + (("liste",) if nom == "valeurs" else ())
                if not isinstance(regle, dict) or set(regle) != set(champs):
                    problemes.append(
                        f"{ou}, règle {nom} : champs attendus {', '.join(champs)}"
                    )
                    continue
                ici = f"{ou}, règle {nom}"
                statut = regle["statut"] = _statut_normalise(regle["statut"])
                if statut not in STATUTS:
                    problemes.append(f"{ici} : statut inconnu {statut!r}")
                elif statut == STATUT_INITIAL and regle["regle"] != regle["proposition"]:
                    problemes.append(
                        f"{ici} : au statut {STATUT_INITIAL}, la règle "
                        f"({regle['regle']!r}) doit être la proposition "
                        f"({regle['proposition']!r})"
                    )
                else:
                    probleme = _probleme_regle_en_vigueur(nom, regle)
                    if probleme:
                        problemes.append(f"{ici} : {probleme}")
                problemes.extend(_problemes_decision(ici, regle))
                if nom == "valeurs":
                    problemes.extend(_problemes_liste(ou, regle))
    return problemes


def problemes_dictionnaire(tables: dict) -> list[str]:
    """Problèmes de structure et de cohérence de tables déjà en mémoire.

    Mêmes contrôles qu'au chargement du fichier. `tables` n'est pas modifié.
    """
    return _verifier_et_normaliser({"tables": deepcopy(tables)})


def _lire_fichier(chemin: Path) -> dict:
    """Contenu du fichier, après contrôle de la version de la structure."""
    with open(chemin, encoding="utf-8") as flux:
        contenu = yaml.safe_load(flux)
    meta = contenu.get("meta") if isinstance(contenu, dict) else None
    structure = meta.get("structure") if isinstance(meta, dict) else None
    if structure != STRUCTURE:
        raise ValueError(
            f"Dictionnaire à une autre structure ({chemin}) : structure "
            f"{structure!r}, attendue {STRUCTURE}. Le fichier est à régénérer."
        )
    return contenu


def charger_dictionnaire(chemin: str | Path | None = None) -> dict:
    """Charge le dictionnaire et rend ses tables, après contrôle de la structure.

    Tous les problèmes sont listés en une fois. Un statut hors de `STATUTS` est rejeté.
    Un fichier écrit avant la refonte de la structure est refusé d'emblée.
    """
    chemin = Path(chemin) if chemin is not None else chemin_dictionnaire()
    contenu = _lire_fichier(chemin)
    problemes = _verifier_et_normaliser(contenu)
    if problemes:
        raise ValueError(f"Dictionnaire invalide ({chemin})\n  " + "\n  ".join(problemes))
    return contenu["tables"]


def charger_meta(chemin: str | Path | None = None) -> dict:
    """Rend le bloc `meta` du dictionnaire, dont le journal des revues.

    La clé `revues` est toujours présente : une liste vide si aucun classeur n'a
    encore été appliqué (y compris pour un fichier écrit avant ce journal).
    """
    chemin = Path(chemin) if chemin is not None else chemin_dictionnaire()
    meta = dict(_lire_fichier(chemin)["meta"])
    meta.setdefault("revues", [])
    problemes = _problemes_journal(meta["revues"])
    if problemes:
        raise ValueError(f"Dictionnaire invalide ({chemin})\n  " + "\n  ".join(problemes))
    return meta


def ecrire_dictionnaire(
    dictionnaire: dict,
    periode_fin: str,
    chemin: str | Path | None = None,
    *,
    ecraser: bool = False,
    revue: dict | None = None,
) -> Path:
    """Écrit le dictionnaire en YAML et vérifie l'écriture par une relecture.

    Sans `ecraser=True`, refuse de remplacer un fichier illisible ou qui porte au
    moins une décision de revue (règle ou valeur à un statut autre que « observé »). Le
    fichier n'est remplacé qu'une fois la relecture identique au dictionnaire fourni.

    Le journal des revues du fichier en place est toujours conservé. `revue` est
    l'entrée rendue par `appliquer_revue` : elle est ajoutée au journal, et le reste
    du bloc `meta` (période, date de génération, seuils) est alors repris du fichier
    en place, puisque l'application d'un classeur ne régénère rien.
    """
    chemin = Path(chemin) if chemin is not None else chemin_dictionnaire()
    tables = _natif(dictionnaire)

    if chemin.exists() and not ecraser:
        revues = sum(
            element["statut"] != STATUT_INITIAL
            for colonnes in charger_dictionnaire(chemin).values()
            for regles in colonnes.values()
            for regle in regles.values()
            for element in (regle, *regle.get("liste", ()))
        )
        if revues:
            raise FileExistsError(
                f"{chemin} porte {revues} décisions de revue : écriture refusée "
                "(ecraser=True pour forcer)"
            )

    en_place = None
    if chemin.exists():
        try:
            en_place = charger_meta(chemin)
        except (ValueError, yaml.YAMLError):
            # Fichier illisible, remplacé avec ecraser=True : son journal est perdu.
            en_place = None
    meta = _meta(periode_fin)
    if revue is not None:
        if en_place is None:
            raise ValueError(
                f"{chemin} : aucun dictionnaire lisible en place, une revue ne peut "
                "s'appliquer qu'à un dictionnaire existant"
            )
        if en_place.get("periode_fin") != periode_fin:
            raise ValueError(
                f"{chemin} : dictionnaire de la période {en_place.get('periode_fin')}, "
                f"revue appliquée pour la période {periode_fin}"
            )
        meta = en_place
    meta["revues"] = _natif(
        (en_place["revues"] if en_place else []) + ([revue] if revue is not None else [])
    )
    problemes = _problemes_journal(meta["revues"])
    if problemes:
        raise ValueError("Journal des revues invalide\n  " + "\n  ".join(problemes))

    chemin.parent.mkdir(parents=True, exist_ok=True)
    provisoire = chemin.with_name(chemin.name + ".tmp")
    try:
        with open(provisoire, "w", encoding="utf-8", newline="\n") as flux:
            yaml.safe_dump(
                {"meta": meta, "tables": tables},
                flux,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=1000,
            )
        if charger_dictionnaire(provisoire) != tables or charger_meta(provisoire) != meta:
            raise RuntimeError("La relecture du dictionnaire écrit diffère de l'original")
        os.replace(provisoire, chemin)
    finally:
        provisoire.unlink(missing_ok=True)
    return chemin