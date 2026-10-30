"""Formulaire des règles de gestion par le métier (phase 6.1 du mode opératoire).

Ce module ne contient rien de propre à un client. Les règles de gestion sont écrites
dans config/gestion.yaml. Plutôt que de faire écrire ce fichier à la main, le métier
les revoit dans un classeur Excel, sur le modèle du formulaire des règles de
contrôle (`frigeo.formulaire_controles`) :

- les familles de règles qui tiennent sur une ligne (références, renseignement selon
  une autre colonne, période d'export) ont leur feuille, où les règles en vigueur
  (statut « documenté ») voisinent avec des propositions tirées des données (statut
  « observé »);
- les autres règles sont affichées en clair dans la feuille des autres règles, où le
  métier peut seulement les retirer, changer leur libellé et leur issue, ou les
  commenter;
- les jours fériés, partagés par les règles d'horaires, ont leur feuille, avec les
  jours fériés calculés pour la France en proposition;
- le métier décrit en texte libre les règles qu'il veut en plus, que le consultant
  traduira en règles du catalogue.

Le fichier YAML ne garde pas de statut : une règle présente a été donnée par le
métier. Une proposition refusée est retenue sous la clé `ecartees`, une règle
retirée sous la clé `retirees` (en entier, pour pouvoir la rétablir) et les règles
demandées sous la clé `demandes`; ces clés sont sans effet sur les contrôles.

Le classeur porte des valeurs du client (valeurs des listes, dates) : il est rangé
hors du dépôt, dans data/formulaires/.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import NamedTuple

import pandas as pd
import yaml
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, Protection
from openpyxl.utils import get_column_letter, quote_sheetname

from . import dictionnaire as module_dictionnaire
from .dictionnaire import LISTE_FERMEE, STATUTS, dossier_sauvegardes
from .doublons import COMPARAISON_TELLE_QUELLE
from .formulaire_controles import (
    NATURES_CLE,
    ApplicationFormulaire,
    Formulaire,
    _lire_feuille,
    _texte,
    _yaml,
    texte_nombre,
)
from .formulaires import dossier_formulaires, ecrire_et_archiver
from .gestion import (
    CLE_COMMENTAIRE,
    CLE_DEMANDES,
    CLE_ECARTEES,
    CLE_FILTRE,
    CLE_ISSUE,
    CLE_JOURS_FERIES,
    CLE_REGLES_GESTION,
    CLE_RETIREES,
    CLES_COMMUNES,
    CLES_FICHIER_GESTION,
    COLONNE_PERIODE,
    COMPARAISONS,
    GENRE_HORAIRES,
    ISSUES,
    TYPES,
    _annee_feries,
    _bornes_periode,
    _cles_comparees,
    _dans_le_champ,
    _ecrire_condition,
    _jour_ferie,
    _prerequis_export,
    _problemes_feries,
    _texte_filtre,
    _texte_lu,
    chemin_regles_gestion,
    completer_jours_feries,
    problemes_regles_gestion,
)
from .revue import FEUILLE_LISTES, _ecrire_texte, _feuille_listes, _menu, _menus_d_ajout
from .typage import NATURES_DATE, lire

FEUILLE_MODE_EMPLOI = "mode_emploi"
FEUILLE_REFERENCES = "références"
FEUILLE_RENSEIGNEMENT = "renseignement"
FEUILLE_PERIODES = "périodes_export"
FEUILLE_FERIES = "jours_fériés"
FEUILLE_AUTRES = "autres_règles"
FEUILLE_NOUVELLES = "nouvelles_règles"

OUI = "oui"
NON = "non"
AUCUNE = "aucune"
ORIGINE_EN_VIGUEUR = "en vigueur"
ORIGINE_PROPOSEE = "proposée"
ORIGINE_ECARTEE = "écartée"
ORIGINE_RETIREE = "retirée"
STATUT_OBSERVE, STATUT_VALIDE, STATUT_INVALIDE, STATUT_DOCUMENTE = STATUTS
# Part minimale des lignes qui suivent une règle pour la proposer, comptée avec une
# ligne contraire de plus (voir `_seuil_atteint`).
SEUIL_PROPOSITION = 0.95
# Références : nombre minimal de valeurs distinctes trouvées pour une proposition.
MIN_DISTINCTES = 2
# Renseignement : nombre maximal de valeurs de la liste fermée de la colonne selon.
MAX_VALEURS_SELON = 12
LIGNES_AJOUT = 50
REPERE_EMPREINTE = "Empreinte de config/gestion.yaml à l'export (repère technique)"

# Familles de règles qui ont leur feuille : nom sous la clé `ecartees`, type du
# catalogue et référence donnée à une proposition.
FAMILLE_REFERENCES = "references"
TYPE_REFERENCES = "existence_dans_reference"
REF_REFERENCES = "existence"
FAMILLE_RENSEIGNEMENT = "renseignement"
TYPE_RENSEIGNEMENT = "renseignee_selon_valeur"
REF_RENSEIGNEMENT = "renseignement"
FAMILLE_PERIODES = "periodes_export"
TYPE_PERIODES = "date_dans_periode_export"
REF_PERIODES = "decoupage"
FAMILLE_FERIES = CLE_JOURS_FERIES
FAMILLES_ECARTEES = (FAMILLE_REFERENCES, FAMILLE_RENSEIGNEMENT, FAMILLE_PERIODES, FAMILLE_FERIES)
# Clés d'une proposition écartée, par famille (liste de dictionnaires de textes);
# les jours fériés écartés suivent la forme de la clé jours_feries.
CLES_PROPOSITION_ECARTEE = {
    FAMILLE_REFERENCES: ("table", "colonne", "table_reference", "colonne_reference"),
    FAMILLE_RENSEIGNEMENT: ("table", "colonne", "selon"),
    FAMILLE_PERIODES: ("table", "colonne"),
}
# Clés d'une règle demandée en texte libre, avec leur colonne dans le classeur.
COLONNES_DEMANDE = {
    "regle": "règle",
    "tables": "tables",
    "colonnes": "colonnes",
    "tolerance": "tolérance_ou_délai",
    "issue": "issue_souhaitée",
    "commentaire": "commentaire",
}

COLONNES_REFERENCES = (
    "table",
    "colonne",
    "table_reference",
    "colonne_reference",
    "observé",
    "proposition",
    "origine",
    "statut",
    "ref",
    "libellé",
    "issue",
    "clé_facultative",
    "comparaison",
    "filtre_colonne",
    "filtre_valeurs",
    "commentaire",
    "rang",
    "proposition_clé_facultative",
)
MODIFIABLES_REFERENCES = (
    "statut", "ref", "libellé", "issue", "clé_facultative", "comparaison", "commentaire",
)
SAISIE_AJOUT_REFERENCES = (
    "table", "colonne", "table_reference", "colonne_reference", "statut", "ref", "libellé",
    "issue", "clé_facultative", "comparaison", "filtre_colonne", "filtre_valeurs",
    "commentaire",
)
COLONNES_RENSEIGNEMENT = (
    "table",
    "colonne",
    "selon",
    "observé",
    "proposition",
    "origine",
    "statut",
    "ref",
    "libellé",
    "issue",
    "valeurs",
    "vide_sinon",
    "filtre_colonne",
    "filtre_valeurs",
    "commentaire",
    "rang",
    "proposition_valeurs",
    "proposition_vide_sinon",
)
MODIFIABLES_RENSEIGNEMENT = (
    "statut", "ref", "libellé", "issue", "valeurs", "vide_sinon", "commentaire",
)
SAISIE_AJOUT_RENSEIGNEMENT = (
    "table", "colonne", "selon", "statut", "ref", "libellé", "issue", "valeurs", "vide_sinon",
    "filtre_colonne", "filtre_valeurs", "commentaire",
)
COLONNES_PERIODES = (
    "table",
    "colonne",
    "nature",
    "dates",
    "observé",
    "proposition",
    "origine",
    "statut",
    "ref",
    "libellé",
    "issue",
    "filtre_colonne",
    "filtre_valeurs",
    "commentaire",
    "rang",
)
MODIFIABLES_PERIODES = ("statut", "ref", "libellé", "issue", "commentaire")
SAISIE_AJOUT_PERIODES = (
    "table", "colonne", "statut", "ref", "libellé", "issue", "filtre_colonne",
    "filtre_valeurs", "commentaire",
)
COLONNES_FERIES = ("année", "date", "jour", "fête", "origine", "statut")
MODIFIABLES_FERIES = ("statut",)
SAISIE_AJOUT_FERIES = ("date", "statut")
COLONNES_AUTRES = (
    "ref",
    "libellé",
    "type",
    "table",
    "paramètres",
    "filtre",
    "issue",
    "origine",
    "statut",
    "commentaire",
    "rang",
)
MODIFIABLES_AUTRES = ("libellé", "issue", "statut", "commentaire")
COLONNES_NOUVELLES = tuple(COLONNES_DEMANDE.values())
# Colonnes techniques, masquées, relues à l'import : le rang de la règle dans
# config/gestion.yaml (sous la clé regles, ou sous la clé retirees pour une règle
# retirée), et les paramètres proposés, que le statut valide adopte.
COLONNES_MASQUEES = (
    "rang", "proposition_clé_facultative", "proposition_valeurs", "proposition_vide_sinon",
)
FORMAT_DATE = "DD/MM/YYYY"
LARGEURS = {
    "table": 22,
    "colonne": 22,
    "table_reference": 22,
    "colonne_reference": 22,
    "selon": 18,
    "clé_facultative": 10,
    "comparaison": 20,
    "valeurs": 24,
    "vide_sinon": 10,
    "proposition_clé_facultative": 10,
    "proposition_valeurs": 10,
    "proposition_vide_sinon": 10,
    "nature": 18,
    "dates": 9,
    "observé": 40,
    "proposition": 12,
    "origine": 12,
    "statut": 13,
    "ref": 14,
    "libellé": 50,
    "issue": 13,
    "filtre_colonne": 16,
    "filtre_valeurs": 22,
    "commentaire": 50,
    "rang": 6,
    "année": 8,
    "date": 12,
    "jour": 10,
    "fête": 24,
    "type": 28,
    "paramètres": 80,
    "filtre": 36,
    "règle": 70,
    "tables": 30,
    "colonnes": 30,
    "tolérance_ou_délai": 24,
    "issue_souhaitée": 16,
}
JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def chemin_formulaire_gestion(periode_fin: str) -> Path:
    """Emplacement par défaut du formulaire : data/formulaires/, hors du dépôt."""
    return dossier_formulaires() / f"gestion_{periode_fin}.xlsx"


def empreinte_gestion(chemin: str | Path | None = None) -> str:
    """Empreinte du contenu de config/gestion.yaml, « absent » sans fichier.

    Les fins de ligne sont ramenées à LF : une conversion par Git sous Windows ne
    change pas l'empreinte.
    """
    chemin = Path(chemin) if chemin is not None else chemin_regles_gestion()
    if not chemin.is_file():
        return "absent"
    contenu = chemin.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(contenu).hexdigest()[:16]


# --- Jours fériés ---------------------------------------------------------------


def _paques(annee: int) -> date:
    """Dimanche de Pâques du calendrier grégorien (algorithme de Meeus)."""
    a, b, c = annee % 19, annee // 100, annee % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    j = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * j) // 451
    mois = (h + j - 7 * m + 114) // 31
    jour = (h + j - 7 * m + 114) % 31 + 1
    return date(annee, mois, jour)


def feries_france(annee: int) -> dict[date, str]:
    """Jours fériés légaux de la France métropolitaine pour une année, avec leur nom,
    dans l'ordre des dates (sans les jours propres à l'Alsace et à la Moselle)."""
    paques = _paques(annee)
    jours = {
        date(annee, 1, 1): "Jour de l'an",
        paques + dt.timedelta(days=1): "Lundi de Pâques",
        date(annee, 5, 1): "Fête du travail",
        date(annee, 5, 8): "Victoire 1945",
        paques + dt.timedelta(days=39): "Ascension",
        paques + dt.timedelta(days=50): "Lundi de Pentecôte",
        date(annee, 7, 14): "Fête nationale",
        date(annee, 8, 15): "Assomption",
        date(annee, 11, 1): "Toussaint",
        date(annee, 11, 11): "Armistice 1918",
        date(annee, 12, 25): "Noël",
    }
    return dict(sorted(jours.items()))


# --- Contenu de config/gestion.yaml ---------------------------------------------


def _ecartees(contenu: dict, famille: str):
    ecartees = contenu.get(CLE_ECARTEES)
    return ecartees.get(famille) if isinstance(ecartees, dict) else None


def _jours_declares(feries) -> dict[int, list[date]]:
    """Jours fériés d'un dictionnaire année vers dates, lus en dates, par année."""
    if not isinstance(feries, dict):
        return {}
    jours = {}
    for cle, valeurs in feries.items():
        annee = _annee_feries(cle)
        if annee is not None and isinstance(valeurs, list):
            lus = [_jour_ferie(valeur) for valeur in valeurs]
            jours[annee] = [jour for jour in lus if jour is not None]
    return jours


def problemes_contenu_formulaire(contenu: dict) -> list[str]:
    """Problèmes des clés que tient le formulaire dans config/gestion.yaml (règles,
    jours fériés, propositions écartées, règles retirées, règles demandées), tous
    listés en une fois."""
    problemes = []
    jours_feries = contenu.get(CLE_JOURS_FERIES)
    if CLE_JOURS_FERIES in contenu:
        problemes.extend(
            f"{CLE_JOURS_FERIES} : {probleme}" for probleme in _problemes_feries(jours_feries)
        )
        if problemes:
            jours_feries = None
    for cle in (CLE_REGLES_GESTION, CLE_RETIREES):
        if cle in contenu:
            regles = completer_jours_feries(contenu[cle], jours_feries)
            problemes.extend(f"{cle}, {probleme}" for probleme in problemes_regles_gestion(regles))
    ecartees = contenu.get(CLE_ECARTEES)
    if CLE_ECARTEES in contenu:
        if not isinstance(ecartees, dict):
            problemes.append(f"{CLE_ECARTEES} : un dictionnaire par famille est attendu")
            ecartees = {}
        for famille, valeur in ecartees.items():
            nom = f"{CLE_ECARTEES}, {famille}"
            if famille == FAMILLE_FERIES:
                problemes.extend(f"{nom} : {probleme}" for probleme in _problemes_feries(valeur))
            elif famille in CLES_PROPOSITION_ECARTEE:
                cles = CLES_PROPOSITION_ECARTEE[famille]
                if not isinstance(valeur, list) or not all(
                    isinstance(element, dict)
                    and set(element) == set(cles)
                    and all(isinstance(v, str) and v for v in element.values())
                    for element in valeur
                ):
                    problemes.append(
                        f"{nom} : une liste de {{{', '.join(cles)}}} (textes) est attendue"
                    )
            else:
                problemes.append(
                    f"{CLE_ECARTEES} : famille inconnue {famille!r} (familles possibles : "
                    f"{', '.join(FAMILLES_ECARTEES)})"
                )
    if CLE_DEMANDES in contenu:
        demandes = contenu[CLE_DEMANDES]
        if not isinstance(demandes, list):
            problemes.append(f"{CLE_DEMANDES} : une liste est attendue")
            demandes = []
        for rang, demande in enumerate(demandes, start=1):
            nom = f"{CLE_DEMANDES}, demande n° {rang}"
            if not isinstance(demande, dict):
                problemes.append(f"{nom} : un dictionnaire de clés est attendu")
                continue
            inconnues = [str(cle) for cle in demande if cle not in COLONNES_DEMANDE]
            if inconnues:
                problemes.append(
                    f"{nom} : clé inconnue {', '.join(inconnues)} (clés possibles : "
                    f"{', '.join(COLONNES_DEMANDE)})"
                )
            if not isinstance(demande.get("regle"), str) or not demande["regle"].strip():
                problemes.append(f"{nom}, regle : un texte non vide est attendu")
            if any(not isinstance(v, str) for c, v in demande.items() if c in COLONNES_DEMANDE):
                problemes.append(f"{nom} : des textes sont attendus")
    return problemes


# --- Lignes du formulaire -------------------------------------------------------


def _est_condition(valeur) -> bool:
    return (
        isinstance(valeur, dict)
        and "colonne" in valeur
        and len(set(valeur) & {"valeurs", "motif"}) == 1
        and set(valeur) <= {"colonne", "valeurs", "motif"}
    )


def _texte_valeur(valeur) -> str:
    """Valeur d'un paramètre écrite en clair."""
    if isinstance(valeur, bool):
        return "true" if valeur else "false"
    if isinstance(valeur, (date, dt.datetime)):
        return valeur.isoformat()
    if isinstance(valeur, list) and valeur and all(_est_condition(v) for v in valeur):
        return " et ".join(_ecrire_condition(condition) for condition in valeur)
    if isinstance(valeur, list) and valeur and all(
        isinstance(v, dict) and set(v) == {"libelle", "conditions"}
        and all(_est_condition(c) for c in v["conditions"])
        for v in valeur
    ):
        return "; ".join(
            f"« {v['libelle']} » si "
            + " et ".join(_ecrire_condition(c) for c in v["conditions"])
            for v in valeur
        )
    if isinstance(valeur, list) and all(
        isinstance(v, (str, int, float)) and not isinstance(v, bool) for v in valeur
    ):
        return ", ".join(str(v) for v in valeur)
    if isinstance(valeur, (list, dict)):
        texte = yaml.safe_dump(
            valeur, default_flow_style=True, allow_unicode=True, sort_keys=False, width=10**6
        )
        return texte.strip()
    return str(valeur)


def texte_parametres(instance: dict) -> str:
    """Paramètres d'une règle écrits en clair, dans l'ordre de son type
    (« cle = id_intervention; delai_max = 30 »), hors filtre, issue et commentaire."""
    type_regle = TYPES.get(instance.get("type"))
    noms = list(type_regle.parametres) if type_regle is not None else []
    noms += [
        cle for cle in instance
        if cle not in noms
        and cle not in (*CLES_COMMUNES, CLE_FILTRE, CLE_ISSUE, CLE_COMMENTAIRE)
    ]
    return "; ".join(
        f"{nom} = {_texte_valeur(instance[nom])}" for nom in noms if nom in instance
    )


def _issue(instance: dict) -> str:
    """Issue effective d'une règle : la sienne, sinon celle de son type."""
    if CLE_ISSUE in instance:
        return instance[CLE_ISSUE]
    return TYPES[instance["type"]].issue


def _filtre_simple(instance: dict) -> tuple[str, str] | None:
    """Colonne et valeurs (« a, b ») du filtre d'une règle qui tient sur une ligne :
    ("", "") sans filtre, None si le filtre a plusieurs conditions, un motif, ou une
    valeur qui contient une virgule (elle serait coupée en deux à l'import)."""
    filtre = instance.get(CLE_FILTRE)
    if not filtre:
        return "", ""
    if (
        len(filtre) == 1
        and "valeurs" in filtre[0]
        and not any("," in str(v) for v in filtre[0]["valeurs"])
    ):
        return filtre[0]["colonne"], ", ".join(str(v) for v in filtre[0]["valeurs"])
    return None


def _seuil_atteint(favorables: int, total: int) -> bool:
    """Vrai si au moins `SEUIL_PROPOSITION` des lignes suivent la règle, en comptant une
    ligne contraire de plus : une proposition ne repose pas sur une poignée de lignes
    (à 95 %, il en faut au moins 19, toutes conformes)."""
    return total > 0 and favorables / (total + 1) >= SEUIL_PROPOSITION


def lignes_minimales() -> int:
    """Nombre minimal de lignes, toutes conformes, pour atteindre le seuil."""
    lignes = 1
    while not _seuil_atteint(lignes, lignes):
        lignes += 1
    return lignes


def _en_periode(instance: dict) -> bool:
    """Vrai pour une règle de la famille des périodes d'export qui tient sur une ligne."""
    return instance.get("type") == TYPE_PERIODES and _filtre_simple(instance) is not None


def observer_periodes(donnees: pd.DataFrame, colonne: str, nature: str) -> dict:
    """Dates lues d'une colonne d'un export, et celles qui tombent dans la période de
    leur export (une ligne sans période lisible n'est pas comptée)."""
    dates = lire(donnees[colonne], nature).valeurs
    lues = dans = 0
    for jour, periode in zip(dates, donnees[COLONNE_PERIODE]):
        bornes = _bornes_periode(periode)
        if pd.isna(jour) or bornes is None:
            continue
        lues += 1
        dans += bornes[0] <= jour < bornes[1]
    return {"dates": lues, "dans": dans}


def _pourcentage(part: float) -> str:
    return texte_nombre(round(100 * part, 1))


def _ligne_periode(table, colonne, nature, observation) -> dict:
    lues, dans = observation["dates"], observation["dans"]
    if lues:
        observe = (
            f"{dans} sur {lues} dans la période de l'export ({_pourcentage(dans / lues)} %)"
        )
    else:
        observe = None
    proposition = OUI if _seuil_atteint(dans, lues) else AUCUNE
    return {
        "table": table,
        "colonne": colonne,
        "nature": nature,
        "dates": lues,
        "observé": observe,
        "proposition": proposition,
    }


def _ligne_regle_periode(base: dict, instance: dict, rang: int, origine: str) -> dict:
    filtre_colonne, filtre_valeurs = _filtre_simple(instance)
    return {
        **base,
        "origine": origine,
        "statut": STATUT_DOCUMENTE if origine == ORIGINE_EN_VIGUEUR else STATUT_INVALIDE,
        "ref": instance["ref"],
        "libellé": instance["libelle"],
        "issue": _issue(instance),
        "filtre_colonne": filtre_colonne or None,
        "filtre_valeurs": filtre_valeurs or None,
        "commentaire": instance.get(CLE_COMMENTAIRE),
        "rang": rang,
    }


def lignes_periodes(tables: dict, dictionnaire: dict, contenu: dict) -> list[dict]:
    """Lignes de la feuille des périodes d'export : une par colonne de date d'une table
    d'export, et une par règle de la famille.

    Par table, dans l'ordre du dictionnaire : les règles en vigueur (documenté), les
    propositions (observé, « oui » quand au moins `SEUIL_PROPOSITION` des dates
    tombent dans la période de leur export, seuil compté avec une date hors période de
    plus), puis les règles retirées et les
    propositions écartées (invalide). Une colonne qui a une règle de la famille, en
    vigueur ou retirée (y compris une règle à filtre complexe, affichée dans la
    feuille des autres règles), ou une proposition écartée, n'a pas de proposition.
    """
    ecartees = {
        (element["table"], element["colonne"])
        for element in _ecartees(contenu, FAMILLE_PERIODES) or []
    }
    colonnes = [
        (table, colonne, regles_colonne["nature"]["regle"])
        for table, colonnes_table in dictionnaire.items()
        if table in tables and _prerequis_export(tables[table]) is None
        for colonne, regles_colonne in colonnes_table.items()
        if regles_colonne["nature"]["regle"] in NATURES_DATE
    ]
    vigueur, retirees = (
        [(r, rang) for rang, r in enumerate(contenu.get(cle) or []) if _en_periode(r)]
        for cle in (CLE_REGLES_GESTION, CLE_RETIREES)
    )
    # Une colonne qui a déjà une règle de la famille, même trop complexe pour cette
    # feuille, n'a pas de proposition.
    connues = ecartees | {
        (r["table"], r["colonne"])
        for cle in (CLE_REGLES_GESTION, CLE_RETIREES)
        for r in contenu.get(cle) or []
        if r.get("type") == TYPE_PERIODES
    }
    observations = {}

    def base(table, colonne):
        if (table, colonne) not in observations:
            nature = dictionnaire.get(table, {}).get(colonne, {}).get("nature", {}).get("regle")
            if (
                table in tables
                and _prerequis_export(tables[table]) is None
                and colonne in tables[table].columns
                and nature in NATURES_DATE
            ):
                observation = observer_periodes(tables[table], colonne, nature)
            else:
                observation = {"dates": 0, "dans": 0}
            ligne = _ligne_periode(table, colonne, nature, observation)
            if not observation["dates"]:
                ligne["dates"] = None
            observations[(table, colonne)] = ligne
        return dict(observations[(table, colonne)])

    ordre = list(dictionnaire)
    noms = sorted(
        {table for table, _, _ in colonnes}
        | {r["table"] for r, _ in vigueur + retirees}
        | {table for table, _ in ecartees},
        key=lambda t: (ordre.index(t) if t in ordre else len(ordre), t),
    )
    lignes = []
    for table in noms:
        for instance, rang in vigueur:
            if instance["table"] == table:
                lignes.append(_ligne_regle_periode(
                    base(table, instance["colonne"]), instance, rang, ORIGINE_EN_VIGUEUR
                ))
        for nom_table, colonne, _ in colonnes:
            if nom_table == table and (table, colonne) not in connues:
                lignes.append({
                    **base(table, colonne),
                    "origine": ORIGINE_PROPOSEE,
                    "statut": STATUT_OBSERVE,
                    "ref": REF_PERIODES,
                    "libellé": f"{colonne} dans la période de l'export",
                    "issue": TYPES[TYPE_PERIODES].issue,
                })
        for instance, rang in retirees:
            if instance["table"] == table:
                lignes.append(_ligne_regle_periode(
                    base(table, instance["colonne"]), instance, rang, ORIGINE_RETIREE
                ))
        for nom_table, colonne in sorted(ecartees):
            if nom_table == table:
                lignes.append({
                    **base(table, colonne),
                    "origine": ORIGINE_ECARTEE,
                    "statut": STATUT_INVALIDE,
                    "ref": REF_PERIODES,
                    "libellé": f"{colonne} dans la période de l'export",
                    "issue": TYPES[TYPE_PERIODES].issue,
                })
    return lignes


# --- Références : valeur connue d'une colonne de référence ------------------------


def _en_reference(instance: dict) -> bool:
    """Vrai pour une règle de la famille des références qui tient sur une ligne."""
    return instance.get("type") == TYPE_REFERENCES and _filtre_simple(instance) is not None


def _champs_regle(instance: dict, rang: int, origine: str) -> dict:
    """Colonnes communes de la ligne d'une règle en vigueur ou retirée."""
    filtre_colonne, filtre_valeurs = _filtre_simple(instance)
    return {
        "origine": origine,
        "statut": STATUT_DOCUMENTE if origine == ORIGINE_EN_VIGUEUR else STATUT_INVALIDE,
        "ref": instance["ref"],
        "libellé": instance["libelle"],
        "issue": _issue(instance),
        "filtre_colonne": filtre_colonne or None,
        "filtre_valeurs": filtre_valeurs or None,
        "commentaire": instance.get(CLE_COMMENTAIRE),
        "rang": rang,
    }


def _par_table(dictionnaire: dict, groupes: list[list[dict]]) -> list[dict]:
    """Lignes de plusieurs groupes, rangées par table (ordre du dictionnaire, puis tables
    inconnues par nom), et dans chaque table groupe après groupe."""
    ordre = list(dictionnaire)
    noms = sorted(
        {ligne["table"] for groupe in groupes for ligne in groupe},
        key=lambda t: (ordre.index(t) if t in ordre else len(ordre), t),
    )
    return [ligne for t in noms for groupe in groupes for ligne in groupe if ligne["table"] == t]


def _ecartees_famille(contenu: dict, famille: str) -> list[tuple]:
    """Propositions écartées d'une famille, en tuples dans l'ordre de leurs clés."""
    return [
        tuple(element[cle] for cle in CLES_PROPOSITION_ECARTEE[famille])
        for element in _ecartees(contenu, famille) or []
    ]


def cibles_references(dictionnaire: dict, declarations: dict | None) -> list[tuple[str, str]]:
    """Colonnes vers lesquelles une référence peut être proposée : la clé ou une colonne
    unique, d'une seule colonne, déclarées dans config/controles.yaml (doublons), de
    nature texte ou entier (texte), dans l'ordre du dictionnaire."""
    cibles = []
    for table, colonnes in dictionnaire.items():
        declaration = (declarations or {}).get(table) or {}
        groupes = [declaration.get("cle") or []] + list(declaration.get("unique") or [])
        for groupe in groupes:
            if (
                len(groupe) == 1
                and groupe[0] in colonnes
                and colonnes[groupe[0]]["nature"]["regle"] in NATURES_CLE
                and (table, groupe[0]) not in cibles
            ):
                cibles.append((table, groupe[0]))
    return cibles


def _compter_reference(cles: pd.Series, connues: set) -> dict:
    renseignees = cles.dropna()
    effectifs = renseignees.value_counts()
    trouvees = effectifs[effectifs.index.isin(list(connues))]
    return {
        "renseignees": len(renseignees),
        "trouvees": int(trouvees.sum()),
        "distinctes": len(trouvees),
        "vides": int(cles.isna().sum()),
    }


def observer_reference(
    donnees: pd.DataFrame,
    colonnes: list[str],
    reference: pd.DataFrame,
    colonnes_reference: list[str],
    comparaison: str = COMPARAISON_TELLE_QUELLE,
) -> dict:
    """Clés d'une table retrouvées dans une table de référence, comparées comme le fait
    le type existence_dans_reference : lignes à clé renseignée, lignes trouvées, valeurs
    distinctes trouvées et lignes à clé vide."""
    cles = _cles_comparees(donnees, list(colonnes), comparaison)
    connues = set(_cles_comparees(reference, list(colonnes_reference), comparaison).dropna())
    return _compter_reference(cles, connues)


def _colonnes_observation_reference(observation: dict | None) -> dict:
    """Colonnes observé, proposition et proposition_clé_facultative d'une ligne."""
    if observation is None:
        return {"observé": None, "proposition": AUCUNE, "proposition_clé_facultative": None}
    renseignees, trouvees = observation["renseignees"], observation["trouvees"]
    if renseignees:
        observe = (
            f"{renseignees} lignes renseignées, {trouvees} trouvées "
            f"({_pourcentage(trouvees / renseignees)} %)"
        )
    else:
        observe = "aucune ligne renseignée"
    if observation["vides"]:
        observe += f", {observation['vides']} vides"
    proposee = (
        _seuil_atteint(trouvees, renseignees) and observation["distinctes"] >= MIN_DISTINCTES
    )
    return {
        "observé": observe,
        "proposition": OUI if proposee else AUCUNE,
        "proposition_clé_facultative": OUI if observation["vides"] else NON,
    }


def _base_reference(tables, table, colonnes, table_ref, colonnes_ref, comparaison, filtre):
    observation = None
    utiles = [(table, c) for c in colonnes] + [(table_ref, c) for c in colonnes_ref]
    utiles += [(table, condition["colonne"]) for condition in filtre or []]
    if all(t in tables and c in tables[t].columns for t, c in utiles):
        donnees = tables[table]
        if filtre:
            donnees = donnees[_dans_le_champ(donnees, filtre)]
        observation = observer_reference(
            donnees, colonnes, tables[table_ref], colonnes_ref, comparaison
        )
    return {
        "table": table,
        "colonne": ", ".join(colonnes),
        "table_reference": table_ref,
        "colonne_reference": ", ".join(colonnes_ref),
        **_colonnes_observation_reference(observation),
    }


def _ligne_regle_reference(tables, instance, rang, origine) -> dict:
    colonnes_ref = instance.get("cle_reference") or instance["cle"]
    comparaison = instance.get("comparaison", COMPARAISON_TELLE_QUELLE)
    base = _base_reference(
        tables, instance["table"], instance["cle"], instance["table_reference"], colonnes_ref,
        comparaison, instance.get(CLE_FILTRE),
    )
    return {
        **base,
        **_champs_regle(instance, rang, origine),
        "clé_facultative": OUI if instance.get("cle_facultative") else NON,
        "comparaison": comparaison,
    }


def _ligne_proposition_reference(base: dict, origine: str) -> dict:
    return {
        **base,
        "origine": origine,
        "statut": STATUT_OBSERVE if origine == ORIGINE_PROPOSEE else STATUT_INVALIDE,
        "ref": REF_REFERENCES,
        "libellé": (
            f"{base['table']}.{base['colonne']} connue de "
            f"{base['table_reference']}.{base['colonne_reference']}"
        ),
        "issue": TYPES[TYPE_REFERENCES].issue,
        "clé_facultative": base["proposition_clé_facultative"] or NON,
        "comparaison": COMPARAISON_TELLE_QUELLE,
    }


def lignes_references(
    tables: dict, dictionnaire: dict, contenu: dict, declarations: dict | None
) -> list[dict]:
    """Lignes de la feuille des références : les règles de la famille et les
    propositions.

    Une colonne A est proposée vers une colonne B, clé ou unique d'une seule colonne
    (`cibles_references`), de même nature, distincte de A (une table peut se viser
    elle-même), quand au moins `SEUIL_PROPOSITION` des lignes à A renseignée sont
    trouvées dans B (seuil compté avec une ligne contraire de plus) et qu'au moins
    `MIN_DISTINCTES` valeurs distinctes y sont trouvées; la clé facultative est proposée
    si A a des vides. Aucune proposition quand une règle en vigueur ou retirée, ou une
    proposition écartée, relie déjà A à B, quel que soit son filtre. Par table A, dans
    l'ordre du dictionnaire : règles en vigueur (documenté), propositions (observé),
    règles retirées, puis propositions écartées (invalide).
    """
    ecartees = _ecartees_famille(contenu, FAMILLE_REFERENCES)
    vigueur, retirees = (
        [(r, rang) for rang, r in enumerate(contenu.get(cle) or []) if _en_reference(r)]
        for cle in (CLE_REGLES_GESTION, CLE_RETIREES)
    )
    connues = {(t, (c,), tr, (cr,)) for t, c, tr, cr in ecartees} | {
        (r["table"], tuple(r["cle"]), r["table_reference"],
         tuple(r.get("cle_reference") or r["cle"]))
        for cle in (CLE_REGLES_GESTION, CLE_RETIREES)
        for r in contenu.get(cle) or []
        if r.get("type") == TYPE_REFERENCES
    }
    cache = {}

    def cles(table, colonne):
        if (table, colonne) not in cache:
            cache[(table, colonne)] = _cles_comparees(tables[table], [colonne])
        return cache[(table, colonne)]

    cibles = [
        (t, c) for t, c in cibles_references(dictionnaire, declarations)
        if t in tables and c in tables[t].columns
    ]
    propositions = []
    for rang_cible, (table_b, colonne_b) in enumerate(cibles):
        nature_b = dictionnaire[table_b][colonne_b]["nature"]["regle"]
        connues_b = set(cles(table_b, colonne_b).dropna())
        for table_a, colonnes_a in dictionnaire.items():
            if table_a not in tables:
                continue
            for rang_a, (colonne_a, regles_a) in enumerate(colonnes_a.items()):
                if (
                    (table_a, colonne_a) == (table_b, colonne_b)
                    or regles_a["nature"]["regle"] != nature_b
                    or colonne_a not in tables[table_a].columns
                    or (table_a, (colonne_a,), table_b, (colonne_b,)) in connues
                ):
                    continue
                observation = _compter_reference(cles(table_a, colonne_a), connues_b)
                base = {
                    "table": table_a,
                    "colonne": colonne_a,
                    "table_reference": table_b,
                    "colonne_reference": colonne_b,
                    **_colonnes_observation_reference(observation),
                }
                if base["proposition"] == OUI:
                    propositions.append(((rang_a, rang_cible), base))
    propositions = [
        _ligne_proposition_reference(base, ORIGINE_PROPOSEE)
        for _, base in sorted(propositions, key=lambda element: element[0])
    ]
    lignes_ecartees = [
        _ligne_proposition_reference(
            _base_reference(tables, t, [c], tr, [cr], COMPARAISON_TELLE_QUELLE, None),
            ORIGINE_ECARTEE,
        )
        for t, c, tr, cr in ecartees
    ]
    return _par_table(dictionnaire, [
        [_ligne_regle_reference(tables, r, rang, ORIGINE_EN_VIGUEUR) for r, rang in vigueur],
        propositions,
        [_ligne_regle_reference(tables, r, rang, ORIGINE_RETIREE) for r, rang in retirees],
        lignes_ecartees,
    ])


# --- Renseignement : colonne renseignée selon la valeur d'une autre --------------


def _en_renseignement(instance: dict) -> bool:
    """Vrai pour une règle de la famille du renseignement qui tient sur une ligne (pas
    de valeur qui contient une virgule, elle serait coupée en deux à l'import)."""
    return (
        instance.get("type") == TYPE_RENSEIGNEMENT
        and _filtre_simple(instance) is not None
        and not any("," in str(v) for v in instance.get("valeurs") or [])
    )


def _liste_en_vigueur(dictionnaire: dict, table: str, colonne: str) -> list[str] | None:
    """Valeurs (textes) de la liste fermée en vigueur d'une colonne, hors valeurs
    invalidées, dans l'ordre du dictionnaire; None sans liste fermée en vigueur."""
    regle = dictionnaire.get(table, {}).get(colonne, {}).get("valeurs") or {}
    if regle.get("regle") != LISTE_FERMEE:
        return None
    return [
        str(element["valeur"]) for element in regle.get("liste") or []
        if element.get("statut") != STATUT_INVALIDE
    ]


def _liste_selon(dictionnaire: dict, table: str, selon: str, sensibles: dict) -> list[str] | None:
    """Liste en vigueur d'une colonne qui peut servir de colonne selon à une
    proposition : liste fermée d'au plus `MAX_VALEURS_SELON` valeurs, colonne non
    sensible (ses valeurs entreraient dans config/gestion.yaml, versionné); None sinon."""
    liste = _liste_en_vigueur(dictionnaire, table, selon)
    if liste is None or len(liste) > MAX_VALEURS_SELON or selon in sensibles.get(table, ()):
        return None
    return liste


def _compter_renseignement(choix: list, remplies: list) -> dict:
    lignes, renseignees, vides = Counter(), Counter(), 0
    for valeur, remplie in zip(choix, remplies):
        if valeur is None:
            vides += 1
        else:
            lignes[valeur] += 1
            renseignees[valeur] += remplie
    return {"lignes": lignes, "renseignees": renseignees, "selon_vide": vides}


def observer_renseignement(donnees: pd.DataFrame, colonne: str, selon: str) -> dict:
    """Par valeur de la colonne selon (texte lu, comparé tel quel comme dans la règle) :
    lignes, et lignes où la colonne est renseignée (une cellule faite d'espaces compte
    comme vide); et nombre de lignes où selon est vide."""
    return _compter_renseignement(
        [_texte_lu(valeur) for valeur in donnees[selon]],
        [_texte_lu(valeur) is not None for valeur in donnees[colonne]],
    )


def proposer_renseignement(observation: dict, liste: list[str]) -> tuple[list[str], bool] | None:
    """Valeurs retenues (dans l'ordre de la liste) et vide_sinon proposés, None sans
    proposition.

    Seules comptent les lignes dont selon porte une valeur de la liste en vigueur (les
    autres sont déjà des anomalies de format). Une valeur est retenue quand la colonne
    est renseignée sur au moins `SEUIL_PROPOSITION` de ses lignes, seuil compté avec
    une ligne contraire de plus. Pas de proposition sans valeur retenue, ni quand
    toutes les valeurs observées atteignent le seuil compté simplement : la colonne
    est alors renseignée quelle que soit la valeur, ce que dit la règle obligatoire du
    dictionnaire. vide_sinon est proposé quand la colonne est vide sur au moins
    `SEUIL_PROPOSITION` des autres lignes (avec une ligne contraire de plus).
    """
    lignes = {v: observation["lignes"][v] for v in liste if observation["lignes"][v]}
    renseignees = {v: observation["renseignees"][v] for v in lignes}
    retenues = [v for v in lignes if _seuil_atteint(renseignees[v], lignes[v])]
    if not retenues or all(
        renseignees[v] / lignes[v] >= SEUIL_PROPOSITION for v in lignes
    ):
        return None
    autres = sum(lignes[v] for v in lignes if v not in retenues)
    vides_autres = autres - sum(renseignees[v] for v in lignes if v not in retenues)
    return retenues, _seuil_atteint(vides_autres, autres)


def _texte_renseignement(observation: dict, valeurs: list[str]) -> str:
    """Observé d'une ligne : « Avoir 11 sur 11 renseignées; autres valeurs 0 sur 8596
    renseignées »."""
    lignes, renseignees = observation["lignes"], observation["renseignees"]
    parties = [f"{v} {renseignees[v]} sur {lignes[v]} renseignées" for v in valeurs]
    autres = [v for v in lignes if v not in valeurs]
    parties.append(
        f"autres valeurs {sum(renseignees[v] for v in autres)} sur "
        f"{sum(lignes[v] for v in autres)} renseignées"
    )
    if observation["selon_vide"]:
        parties.append(f"selon vide sur {observation['selon_vide']} lignes")
    return "; ".join(parties)


def _libelle_renseignement(colonne, selon, valeurs, vide_sinon) -> str:
    if not valeurs:
        return f"{colonne} renseignée selon {selon}"
    libelle = f"{colonne} renseignée si {selon} vaut {' ou '.join(valeurs)}"
    return libelle + (", vide sinon" if vide_sinon else "")


def _base_renseignement(tables, dictionnaire, sensibles, table, colonne, selon, filtre,
                        valeurs=None):
    """Colonnes observées d'une ligne, et la proposition (None sans proposition);
    `valeurs` (règle) ou, à défaut, les valeurs proposées détaillent l'observé."""
    base = {
        "table": table,
        "colonne": colonne,
        "selon": selon,
        "observé": None,
        "proposition": AUCUNE,
        "proposition_valeurs": None,
        "proposition_vide_sinon": None,
    }
    utiles = [colonne, selon] + [condition["colonne"] for condition in filtre or []]
    if table not in tables or any(c not in tables[table].columns for c in utiles):
        return base, None
    donnees = tables[table]
    if filtre:
        donnees = donnees[_dans_le_champ(donnees, filtre)]
    observation = observer_renseignement(donnees, colonne, selon)
    liste = _liste_selon(dictionnaire, table, selon, sensibles)
    proposition = proposer_renseignement(observation, liste) if liste is not None else None
    if proposition is not None:
        retenues, vide_sinon = proposition
        base["proposition"] = ", ".join(retenues) + ("; vide sinon" if vide_sinon else "")
        base["proposition_valeurs"] = ", ".join(retenues)
        base["proposition_vide_sinon"] = OUI if vide_sinon else NON
    if valeurs is None:
        valeurs = proposition[0] if proposition is not None else []
    base["observé"] = _texte_renseignement(observation, valeurs)
    return base, proposition


def _ligne_regle_renseignement(tables, dictionnaire, sensibles, instance, rang, origine):
    valeurs = [str(v) for v in instance["valeurs"]]
    base, _ = _base_renseignement(
        tables, dictionnaire, sensibles, instance["table"], instance["colonne"], instance["selon"],
        instance.get(CLE_FILTRE), valeurs,
    )
    return {
        **base,
        **_champs_regle(instance, rang, origine),
        "valeurs": ", ".join(valeurs),
        "vide_sinon": OUI if instance.get("vide_sinon") else NON,
    }


def _ligne_proposition_renseignement(base: dict, proposition, origine: str) -> dict:
    valeurs, vide_sinon = proposition if proposition is not None else ([], False)
    return {
        **base,
        "origine": origine,
        "statut": STATUT_OBSERVE if origine == ORIGINE_PROPOSEE else STATUT_INVALIDE,
        "ref": REF_RENSEIGNEMENT,
        "libellé": _libelle_renseignement(base["colonne"], base["selon"], valeurs, vide_sinon),
        "issue": TYPES[TYPE_RENSEIGNEMENT].issue,
        "valeurs": base["proposition_valeurs"],
        "vide_sinon": base["proposition_vide_sinon"],
    }


def lignes_renseignement(
    tables: dict, dictionnaire: dict, contenu: dict, sensibles: dict | None = None
) -> list[dict]:
    """Lignes de la feuille du renseignement : les règles de la famille et les
    propositions.

    Une colonne C est proposée selon une colonne S de la même table quand S a une liste
    fermée en vigueur d'au plus `MAX_VALEURS_SELON` valeurs, que C a des cellules vides
    et des cellules renseignées, et que `proposer_renseignement` retient des valeurs.
    S ne doit pas être une colonne sensible : ses valeurs entreraient dans
    config/gestion.yaml, versionné. Aucune proposition quand une règle en vigueur ou
    retirée, ou une proposition écartée, porte déjà sur C selon S, quel que soit son
    filtre. Les valeurs de S figurent dans le classeur (fichier du client). Par table,
    dans l'ordre du dictionnaire : règles en vigueur (documenté), propositions
    (observé), règles retirées, puis propositions écartées (invalide).
    """
    sensibles = sensibles or {}
    ecartees = _ecartees_famille(contenu, FAMILLE_RENSEIGNEMENT)
    vigueur, retirees = (
        [(r, rang) for rang, r in enumerate(contenu.get(cle) or []) if _en_renseignement(r)]
        for cle in (CLE_REGLES_GESTION, CLE_RETIREES)
    )
    connues = set(ecartees) | {
        (r["table"], r["colonne"], r["selon"])
        for cle in (CLE_REGLES_GESTION, CLE_RETIREES)
        for r in contenu.get(cle) or []
        if r.get("type") == TYPE_RENSEIGNEMENT
    }
    propositions = []
    for table, colonnes in dictionnaire.items():
        if table not in tables:
            continue
        donnees = tables[table]
        presentes = [c for c in colonnes if c in donnees.columns]
        listes = {s: _liste_selon(dictionnaire, table, s, sensibles) for s in presentes}
        if all(liste is None for liste in listes.values()):
            continue
        remplies = {
            c: [_texte_lu(valeur) is not None for valeur in donnees[c]] for c in presentes
        }
        for rang_s, selon in enumerate(presentes):
            liste = listes[selon]
            if liste is None:
                continue
            textes = [_texte_lu(valeur) for valeur in donnees[selon]]
            for rang_c, colonne in enumerate(presentes):
                # Une colonne sans vide, ou sans valeur, n'aurait pas de proposition :
                # elle est écartée d'emblée.
                if (
                    colonne == selon
                    or all(remplies[colonne])
                    or not any(remplies[colonne])
                    or (table, colonne, selon) in connues
                ):
                    continue
                observation = _compter_renseignement(textes, remplies[colonne])
                proposition = proposer_renseignement(observation, liste)
                if proposition is None:
                    continue
                retenues, vide_sinon = proposition
                base = {
                    "table": table,
                    "colonne": colonne,
                    "selon": selon,
                    "observé": _texte_renseignement(observation, retenues),
                    "proposition": ", ".join(retenues) + ("; vide sinon" if vide_sinon else ""),
                    "proposition_valeurs": ", ".join(retenues),
                    "proposition_vide_sinon": OUI if vide_sinon else NON,
                }
                propositions.append(((rang_c, rang_s), base, proposition))
    propositions = [
        _ligne_proposition_renseignement(base, proposition, ORIGINE_PROPOSEE)
        for _, base, proposition in sorted(propositions, key=lambda element: element[0])
    ]
    lignes_ecartees = [
        _ligne_proposition_renseignement(
            *_base_renseignement(tables, dictionnaire, sensibles, t, c, s, None),
            ORIGINE_ECARTEE,
        )
        for t, c, s in ecartees
    ]
    return _par_table(dictionnaire, [
        [_ligne_regle_renseignement(tables, dictionnaire, sensibles, r, rang,
                                    ORIGINE_EN_VIGUEUR) for r, rang in vigueur],
        propositions,
        [_ligne_regle_renseignement(tables, dictionnaire, sensibles, r, rang, ORIGINE_RETIREE)
         for r, rang in retirees],
        lignes_ecartees,
    ])


def annees_des_exports(tables: dict) -> list[int]:
    """Années des périodes d'export des tables (colonne periode_export lisible)."""
    annees = set()
    for donnees in tables.values():
        if COLONNE_PERIODE not in donnees.columns:
            continue
        for periode in donnees[COLONNE_PERIODE].unique():
            bornes = _bornes_periode(periode)
            if bornes is not None:
                annees.add(bornes[0].year)
    return sorted(annees)


def lignes_feries(tables: dict, contenu: dict) -> list[dict]:
    """Lignes de la feuille des jours fériés : une par date, pour chaque année déclarée
    dans config/gestion.yaml ou présente dans les périodes d'export.

    Une date déclarée sort au statut documenté, une date calculée pour la France et
    non déclarée au statut observé, une date écartée au statut invalide. La colonne
    fête nomme les jours calculés; elle reste vide pour un jour propre à l'entreprise.
    """
    declares = _jours_declares(contenu.get(CLE_JOURS_FERIES))
    ecartes = _jours_declares(_ecartees(contenu, FAMILLE_FERIES))
    annees = sorted(set(declares) | set(ecartes) | set(annees_des_exports(tables)))
    lignes = []
    for annee in annees:
        calcules = feries_france(annee)
        jours = set(declares.get(annee, [])) | set(calcules) | set(ecartes.get(annee, []))
        for jour in sorted(jours):
            if jour in declares.get(annee, []):
                origine, statut = ORIGINE_EN_VIGUEUR, STATUT_DOCUMENTE
            elif jour in ecartes.get(annee, []):
                origine, statut = ORIGINE_ECARTEE, STATUT_INVALIDE
            else:
                origine, statut = ORIGINE_PROPOSEE, STATUT_OBSERVE
            lignes.append({
                "année": annee,
                "date": jour,
                "jour": JOURS[jour.weekday()],
                "fête": calcules.get(jour),
                "origine": origine,
                "statut": statut,
            })
    return lignes


def lignes_autres(
    contenu: dict, familles=(_en_reference, _en_renseignement, _en_periode)
) -> list[dict]:
    """Lignes de la feuille des autres règles : les règles qui n'ont pas leur feuille,
    en vigueur (documenté) puis retirées (invalide), dans l'ordre du fichier, avec
    leurs paramètres et leur filtre écrits en clair."""
    lignes = []
    for cle, origine, statut in (
        (CLE_REGLES_GESTION, ORIGINE_EN_VIGUEUR, STATUT_DOCUMENTE),
        (CLE_RETIREES, ORIGINE_RETIREE, STATUT_INVALIDE),
    ):
        for rang, instance in enumerate(contenu.get(cle) or []):
            if any(famille(instance) for famille in familles):
                continue
            lignes.append({
                "ref": instance["ref"],
                "libellé": instance["libelle"],
                "type": instance["type"],
                "table": instance["table"],
                "paramètres": texte_parametres(instance),
                "filtre": _texte_filtre(instance.get(CLE_FILTRE)),
                "issue": _issue(instance),
                "origine": origine,
                "statut": statut,
                "commentaire": instance.get(CLE_COMMENTAIRE),
                "rang": rang,
            })
    return lignes


def lignes_nouvelles(contenu: dict) -> list[dict]:
    """Lignes de la feuille des nouvelles règles : les règles demandées en texte libre
    (clé `demandes`), que le consultant traduira en règles du catalogue."""
    return [
        {COLONNES_DEMANDE[cle]: demande.get(cle) for cle in COLONNES_DEMANDE}
        for demande in contenu.get(CLE_DEMANDES) or []
    ]


# --- Classeur -------------------------------------------------------------------


def _a_traiter(lignes: list[dict]) -> int:
    return sum(ligne["statut"] == STATUT_OBSERVE for ligne in lignes)


def _mode_emploi(periode_fin: str, lignes: dict) -> list[str]:
    references, renseignement = lignes["references"], lignes["renseignement"]
    periodes, feries = lignes["periodes"], lignes["feries"]
    autres, nouvelles = lignes["autres"], lignes["nouvelles"]
    issues = ", ".join(ISSUES)
    return [
        "Formulaire des règles de gestion",
        f"Période de fin : {periode_fin}. Formulaire généré le {date.today():%d/%m/%Y}.",
        "Ce formulaire donne les règles de gestion de l'entreprise : ce que les données "
        "doivent respecter d'une ligne à l'autre ou d'un fichier à l'autre. Il montre les "
        "règles en vigueur (statut documenté) à côté de ce que l'outil observe dans les "
        "données (colonnes observé et proposition). Une fois revu, il réécrit le fichier "
        "des règles de gestion.",
        "",
        "Ce qui reste à traiter",
        f"Feuille « {FEUILLE_REFERENCES} » : {_a_traiter(references)} lignes à « observé » "
        f"sur {len(references)}. Feuille « {FEUILLE_RENSEIGNEMENT} » : "
        f"{_a_traiter(renseignement)} sur {len(renseignement)}. Feuille "
        f"« {FEUILLE_PERIODES} » : {_a_traiter(periodes)} sur "
        f"{len(periodes)}. Feuille « {FEUILLE_FERIES} » : {_a_traiter(feries)} sur "
        f"{len(feries)}. Feuille « {FEUILLE_AUTRES} » : {len(autres)} règles. Feuille "
        f"« {FEUILLE_NOUVELLES} » : {len(nouvelles)} règles demandées.",
        "Une revue partielle est possible : une ligne laissée à « observé » est reprise "
        "telle quelle dans le formulaire suivant.",
        "",
        "Ce qui est attendu",
        "Pour chaque ligne, choisir un statut dans le menu déroulant et, si besoin, écrire "
        "un commentaire (il est conservé).",
        "observé : la ligne n'est pas revue; pas de règle. Sur une règle en vigueur ou "
        "retirée, observé la supprime sans la garder.",
        f"valide : la proposition devient la règle. Impossible si la proposition est "
        f"« {AUCUNE} ».",
        "documenté : la règle est retenue telle que la ligne la décrit. Une règle en "
        "vigueur sort avec ce statut : pour la modifier, changer les cellules modifiables "
        "en gardant documenté.",
        "invalide : pas de règle, et la proposition ne sera plus faite. Pour une règle en "
        "vigueur, invalide la retire; elle reste affichée (origine « retirée ») et "
        "documenté la rétablit.",
        "La colonne origine dit d'où vient la ligne : en vigueur, proposée, écartée ou "
        "retirée.",
        f"L'issue d'un écart se choisit dans le menu : {issues}. « anomalie » pour une "
        "erreur, « à arbitrer » quand le métier doit dire s'il s'agit d'une erreur, "
        "« information » pour un cas normal qu'on veut voir.",
        "Les colonnes qui désignent la règle (table, colonnes, table de référence, filtre) "
        "ne se modifient pas : pour changer l'une d'elles, mettre invalide sur la ligne et "
        "ajouter une ligne en bas de la feuille. Le filtre, facultatif, limite la règle aux "
        "lignes dont filtre_colonne vaut l'une des filtre_valeurs (séparées par une "
        "virgule).",
        f"Une proposition demande qu'au moins {_pourcentage(SEUIL_PROPOSITION)} % des "
        "lignes observées suivent la règle, en comptant une ligne contraire de plus : elle "
        f"ne repose jamais sur moins de {lignes_minimales()} lignes. Une règle utile mais "
        "trop rare pour être proposée s'ajoute en bas de la feuille.",
        "",
        f"Feuille « {FEUILLE_REFERENCES} » : chaque valeur d'une colonne existe dans une "
        "colonne de référence",
        "Par exemple, le client d'une facture existe dans le fichier des clients. Une "
        "colonne est proposée vers la clé ou une colonne unique d'une table (déclarées dans "
        "les règles de contrôle), de même nature, quand au moins "
        f"{_pourcentage(SEUIL_PROPOSITION)} % de ses valeurs y sont trouvées, avec au moins "
        f"{MIN_DISTINCTES} valeurs différentes. clé_facultative à « {OUI} » : une ligne sans "
        "valeur n'est pas contrôlée (sinon, elle ne peut pas être évaluée). comparaison : "
        f"{', '.join(COMPARAISONS)} (sans accents, majuscules ni espaces en trop). Pour une "
        "clé de plusieurs colonnes, ajouter une ligne en bas de la feuille et écrire les "
        "colonnes séparées par une virgule (« a, b »), dans le même ordre dans colonne et "
        "colonne_reference.",
        "",
        f"Feuille « {FEUILLE_RENSEIGNEMENT} » : une colonne est renseignée selon la valeur "
        "d'une autre",
        "Par exemple, la facture d'origine est renseignée pour un avoir et vide pour une "
        "facture. La colonne selon a une liste fermée de valeurs au dictionnaire, de "
        f"{MAX_VALEURS_SELON} valeurs au plus. Une colonne est proposée quand elle est "
        f"renseignée sur au moins {_pourcentage(SEUIL_PROPOSITION)} % des lignes de "
        "certaines valeurs (colonne valeurs, séparées par une virgule) sans l'être pour "
        f"toutes. vide_sinon à « {OUI} » : la colonne doit être vide sur les autres lignes; "
        "il est proposé quand elle l'est sur au moins "
        f"{_pourcentage(SEUIL_PROPOSITION)} % d'entre elles.",
        "",
        f"Feuille « {FEUILLE_PERIODES} » : la date d'une ligne tombe dans la période de son "
        "export",
        "Une ligne par colonne de date d'un fichier exporté chaque mois ou chaque année. "
        "La règle est proposée quand au moins "
        f"{_pourcentage(SEUIL_PROPOSITION)} % des dates observées tombent dans la période "
        "de leur export.",
        "Pour ajouter une règle dans l'une de ces trois feuilles : sur une ligne vide en "
        "bas de la feuille, choisir la table et les colonnes dans les menus, remplir les "
        "autres cellules, et choisir le statut documenté. ref et libellé laissés vides "
        "prennent ceux d'une proposition.",
        "",
        f"Feuille « {FEUILLE_FERIES} » : les jours fériés, communs à toutes les règles "
        "d'horaires",
        "Une ligne par date, pour chaque année déclarée ou présente dans les données. Les "
        "jours fériés légaux de la France sont proposés (statut observé) quand ils ne sont "
        "pas déclarés : valide les retient. Pour un jour propre à l'entreprise (pont, "
        "fermeture, jour férié local), écrire la date sur une ligne vide en bas de la "
        "feuille et choisir documenté.",
        "",
        f"Feuille « {FEUILLE_AUTRES} » : les autres règles, écrites par le consultant",
        "Leurs paramètres sont en lecture seule. On peut changer le libellé, l'issue et le "
        "commentaire, ou retirer la règle (invalide). Pour changer un paramètre, le "
        "demander dans la feuille des nouvelles règles ou au consultant.",
        "",
        f"Feuille « {FEUILLE_NOUVELLES} » : les règles que vous voulez en plus",
        "Décrire chaque règle en clair, une par ligne : ce qui doit être vrai, les tables "
        "et colonnes concernées, la tolérance ou le délai admis, l'issue souhaitée. Le "
        "consultant la traduit en règle; elle reste dans cette feuille jusque-là. Effacer "
        "la ligne d'une règle qui n'est plus voulue.",
        "",
        "Règles à respecter pour que le formulaire puisse être réimporté",
        "Ne modifier que les cellules non verrouillées. Ne pas renommer, déplacer ni "
        "supprimer de feuilles, de colonnes ou de lignes. Avant l'import : enregistrer puis "
        "fermer le classeur dans Excel. Un formulaire ne s'applique qu'une fois : après son "
        "import, ou après une modification du fichier des règles, il est à réexporter.",
        REPERE_EMPREINTE,
    ]


def _remplir(feuille, colonnes, lignes, modifiables, lignes_ajout=0, saisie_ajout=()) -> None:
    """Écrit l'en-tête et les lignes, puis protège la feuille hors cellules modifiables.

    Une date est écrite comme une date (format JJ/MM/AAAA), un nombre comme un nombre,
    le reste comme du texte.
    """
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
            if isinstance(valeur, date):
                cellule.value = valeur
                cellule.number_format = FORMAT_DATE
            elif isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
                cellule.value = valeur
            else:
                _ecrire_texte(cellule, valeur)
            if nom in modifiables:
                cellule.protection = Protection(locked=False)
            if nom in ("libellé", "paramètres", "règle", "commentaire"):
                cellule.alignment = Alignment(wrap_text=True, vertical="top")
    fin = len(lignes) + 1
    for numero in range(fin + 1, fin + lignes_ajout + 1):
        for indice, nom in enumerate(colonnes, start=1):
            if nom in saisie_ajout:
                cellule = feuille.cell(row=numero, column=indice)
                cellule.number_format = FORMAT_DATE if nom == "date" else "@"
                cellule.protection = Protection(locked=False)
    derniere = get_column_letter(len(colonnes))
    feuille.freeze_panes = "C2"
    feuille.auto_filter.ref = f"A1:{derniere}{max(fin + lignes_ajout, 2)}"
    feuille.protection.sheet = True
    feuille.protection.autoFilter = False
    feuille.protection.formatColumns = False


def _ajouter_menu(menu, colonnes, nom, premiere, derniere) -> None:
    if derniere >= premiere:
        lettre = get_column_letter(colonnes.index(nom) + 1)
        menu.add(f"{lettre}{premiere}:{lettre}{derniere}")


def _menus_table(feuille, colonnes, nb_tables, premiere, derniere, nom_table, noms,
                 souples=()) -> None:
    """Menus d'une table et de ses colonnes sur les lignes d'ajout (voir
    `revue._menus_d_ajout`) : le menu d'une colonne de `noms` ne propose que les
    colonnes de la table choisie sur la ligne. Une colonne de `souples` admet aussi une
    saisie hors du menu, après un avertissement (clé de plusieurs colonnes « a, b »)."""
    if not nb_tables or derniere < premiere:
        return
    nom = quote_sheetname(FEUILLE_LISTES)
    tables = f"{nom}!$A$1:${get_column_letter(nb_tables)}$1"
    col_table = get_column_letter(colonnes.index(nom_table) + 1)
    _menu(feuille, formule=tables).add(f"{col_table}{premiere}:{col_table}{derniere}")
    # La référence à la table est relative à la ligne : elle suit chaque ligne d'ajout.
    rang = f"MATCH(${col_table}{premiere},{nom}!$1:$1,0)-1"
    choix = f"OFFSET({nom}!$A$1,1,{rang},COUNTA(OFFSET({nom}!$A:$A,0,{rang}))-1,1)"
    for nom_colonne in noms:
        lettre = get_column_letter(colonnes.index(nom_colonne) + 1)
        menu = _menu(feuille, formule=choix)
        if nom_colonne in souples:
            menu.errorStyle = "warning"
            menu.error = "Colonne hors du menu : vérifier les noms (clé « a, b » admise)."
        menu.add(f"{lettre}{premiere}:{lettre}{derniere}")


def exporter_formulaire_gestion(
    tables: dict,
    dictionnaire: dict,
    contenu: dict,
    declarations: dict | None,
    sensibles: dict | None,
    periode_fin: str,
    chemin: str | Path | None = None,
    *,
    empreinte: str,
    ecraser: bool = False,
) -> Path:
    """Écrit le formulaire des règles de gestion et rend son chemin.

    `contenu` est celui de config/gestion.yaml (`gestion.lire_fichier_gestion`) et
    `empreinte` son empreinte (`empreinte_gestion`) : elle est inscrite dans le
    formulaire, et l'import le refusera si le fichier a changé depuis.
    `declarations` sont les déclarations de doublons de config/controles.yaml
    (`doublons.charger_declarations_doublons`), dont les clés et colonnes uniques
    servent de cibles aux références proposées; `sensibles` les colonnes sensibles
    (`confidentialite.charger_sensibilite`), qui ne servent pas de colonne selon à une
    proposition de renseignement. Un contenu
    mal formé est refusé (`ValueError`, tous les problèmes listés). Sans
    `ecraser=True`, refuse de remplacer un formulaire existant : une revue y est
    peut-être en cours.
    """
    chemin = Path(chemin) if chemin is not None else chemin_formulaire_gestion(periode_fin)
    if chemin.exists() and not ecraser:
        raise FileExistsError(f"{chemin} existe déjà : export refusé (ecraser=True pour forcer)")
    problemes = problemes_contenu_formulaire(contenu)
    if problemes:
        raise ValueError(
            "Fichier des règles de gestion invalide\n  " + "\n  ".join(problemes)
        )
    lignes = {
        "references": lignes_references(tables, dictionnaire, contenu, declarations),
        "renseignement": lignes_renseignement(tables, dictionnaire, contenu, sensibles),
        "periodes": lignes_periodes(tables, dictionnaire, contenu),
        "feries": lignes_feries(tables, contenu),
        "autres": lignes_autres(contenu),
        "nouvelles": lignes_nouvelles(contenu),
    }

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

    nb_tables = len(dictionnaire)
    feuille = classeur.create_sheet(FEUILLE_REFERENCES)
    references = lignes["references"]
    _remplir(feuille, COLONNES_REFERENCES, references, MODIFIABLES_REFERENCES, LIGNES_AJOUT,
             SAISIE_AJOUT_REFERENCES)
    derniere = len(references) + 1 + LIGNES_AJOUT
    colonnes = COLONNES_REFERENCES
    _ajouter_menu(_menu(feuille, STATUTS), colonnes, "statut", 2, derniere)
    _ajouter_menu(_menu(feuille, ISSUES), colonnes, "issue", 2, derniere)
    _ajouter_menu(_menu(feuille, (OUI, NON)), colonnes, "clé_facultative", 2, derniere)
    _ajouter_menu(_menu(feuille, COMPARAISONS), colonnes, "comparaison", 2, derniere)
    premiere = len(references) + 2
    _menus_table(feuille, colonnes, nb_tables, premiere, derniere, "table", ("colonne",),
                 souples=("colonne",))
    _menus_table(feuille, colonnes, nb_tables, premiere, derniere, "table_reference",
                 ("colonne_reference",), souples=("colonne_reference",))

    feuille = classeur.create_sheet(FEUILLE_RENSEIGNEMENT)
    renseignement = lignes["renseignement"]
    colonnes = COLONNES_RENSEIGNEMENT
    _remplir(feuille, colonnes, renseignement, MODIFIABLES_RENSEIGNEMENT, LIGNES_AJOUT,
             SAISIE_AJOUT_RENSEIGNEMENT)
    derniere = len(renseignement) + 1 + LIGNES_AJOUT
    _ajouter_menu(_menu(feuille, STATUTS), colonnes, "statut", 2, derniere)
    _ajouter_menu(_menu(feuille, ISSUES), colonnes, "issue", 2, derniere)
    _ajouter_menu(_menu(feuille, (OUI, NON)), colonnes, "vide_sinon", 2, derniere)
    _menus_table(feuille, colonnes, nb_tables, len(renseignement) + 2, derniere, "table",
                 ("colonne", "selon"))

    feuille = classeur.create_sheet(FEUILLE_PERIODES)
    periodes = lignes["periodes"]
    _remplir(feuille, COLONNES_PERIODES, periodes, MODIFIABLES_PERIODES, LIGNES_AJOUT,
             SAISIE_AJOUT_PERIODES)
    derniere = len(periodes) + 1 + LIGNES_AJOUT
    _ajouter_menu(_menu(feuille, STATUTS), COLONNES_PERIODES, "statut", 2, derniere)
    _ajouter_menu(_menu(feuille, ISSUES), COLONNES_PERIODES, "issue", 2, derniere)
    _menus_d_ajout(feuille, COLONNES_PERIODES, len(dictionnaire), len(periodes) + 2, derniere)

    feuille = classeur.create_sheet(FEUILLE_FERIES)
    feries = lignes["feries"]
    _remplir(feuille, COLONNES_FERIES, feries, MODIFIABLES_FERIES, LIGNES_AJOUT,
             SAISIE_AJOUT_FERIES)
    derniere = len(feries) + 1 + LIGNES_AJOUT
    _ajouter_menu(_menu(feuille, STATUTS), COLONNES_FERIES, "statut", 2, derniere)

    feuille = classeur.create_sheet(FEUILLE_AUTRES)
    autres = lignes["autres"]
    _remplir(feuille, COLONNES_AUTRES, autres, MODIFIABLES_AUTRES)
    _ajouter_menu(_menu(feuille, STATUTS), COLONNES_AUTRES, "statut", 2, len(autres) + 1)
    _ajouter_menu(_menu(feuille, ISSUES), COLONNES_AUTRES, "issue", 2, len(autres) + 1)

    feuille = classeur.create_sheet(FEUILLE_NOUVELLES)
    nouvelles = lignes["nouvelles"]
    _remplir(feuille, COLONNES_NOUVELLES, nouvelles, COLONNES_NOUVELLES, LIGNES_AJOUT,
             COLONNES_NOUVELLES)
    _ajouter_menu(_menu(feuille, ISSUES), COLONNES_NOUVELLES, "issue_souhaitée", 2,
                  len(nouvelles) + 1 + LIGNES_AJOUT)

    _feuille_listes(classeur, dictionnaire)

    chemin.parent.mkdir(parents=True, exist_ok=True)
    classeur.save(chemin)
    return chemin


# --- Import du formulaire ---------------------------------------------------------

COLONNES_CHANGEMENTS_GESTION = (
    "feuille", "ref", "table", "colonnes", "changement", "avant", "apres",
)
CHANGEMENT_AJOUTEE = "ajoutée"
CHANGEMENT_MODIFIEE = "modifiée"
CHANGEMENT_RETIREE = "retirée"
CHANGEMENT_RETABLIE = "rétablie"
CHANGEMENT_SUPPRIMEE = "supprimée"
CHANGEMENT_ECARTEE = "écartée"
CHANGEMENT_REPROPOSEE = "reproposée"
CHANGEMENT_DECLAREE = "déclarée"
CHANGEMENT_DEMANDEE = "demandée"
ORIGINES = (ORIGINE_EN_VIGUEUR, ORIGINE_PROPOSEE, ORIGINE_ECARTEE, ORIGINE_RETIREE)
ABSENT = "absent"


class _Famille(NamedTuple):
    """Ce qui distingue les trois familles en lignes à l'import."""

    nom: str
    feuille: str
    colonnes: tuple[str, ...]
    type: str
    ref: str
    en_famille: object


FAMILLES = (
    _Famille(FAMILLE_REFERENCES, FEUILLE_REFERENCES, COLONNES_REFERENCES, TYPE_REFERENCES,
             REF_REFERENCES, _en_reference),
    _Famille(FAMILLE_RENSEIGNEMENT, FEUILLE_RENSEIGNEMENT, COLONNES_RENSEIGNEMENT,
             TYPE_RENSEIGNEMENT, REF_RENSEIGNEMENT, _en_renseignement),
    _Famille(FAMILLE_PERIODES, FEUILLE_PERIODES, COLONNES_PERIODES, TYPE_PERIODES,
             REF_PERIODES, _en_periode),
)


def _texte_cellule(valeur) -> str:
    """Texte d'une cellule (un nombre entier saisi dans Excel s'écrit sans « .0 »)."""
    if isinstance(valeur, float) and valeur.is_integer():
        valeur = int(valeur)
    return _texte(valeur)


def _decouper(texte: str) -> list[str]:
    """Valeurs d'une cellule « a, b », dans l'ordre, sans valeur vide."""
    return [morceau.strip() for morceau in texte.split(",") if morceau.strip()]


def _commentaire_saisi(valeur) -> str | None:
    """Commentaire d'une cellule (retours à la ligne d'Excel ramenés à « \\n »), None
    s'il est vide."""
    texte = _texte_cellule(valeur).replace("\r\n", "\n").replace("\r", "\n")
    return texte or None


def _commentaire_regle(instance: dict) -> str | None:
    commentaire = instance.get(CLE_COMMENTAIRE)
    return _commentaire_saisi(commentaire) if commentaire is not None else None


def _oui_non(valeur, nom: str) -> tuple[bool | None, str | None]:
    """Choix oui ou non d'une cellule (vide vaut non), et le problème de la saisie."""
    texte = _texte_cellule(valeur)
    if texte in ("", NON):
        return False, None
    if texte == OUI:
        return True, None
    return None, f"{nom} : {OUI}, {NON} ou vide est attendu"


def _filtre_ligne(ligne: dict) -> tuple[str, str]:
    return _texte_cellule(ligne["filtre_colonne"]), _texte_cellule(ligne["filtre_valeurs"])


def _filtre_regle(instance: dict) -> tuple[str, str]:
    return _filtre_simple(instance) or ("", "")


def _identite_ligne(famille: _Famille, ligne: dict) -> tuple:
    """Colonnes qui désignent la règle d'une ligne (lecture seule), en textes."""
    if famille.nom == FAMILLE_REFERENCES:
        noms = ("table", "colonne", "table_reference", "colonne_reference")
    elif famille.nom == FAMILLE_RENSEIGNEMENT:
        noms = ("table", "colonne", "selon")
    else:
        noms = ("table", "colonne")
    return tuple(_texte_cellule(ligne[nom]) for nom in noms) + _filtre_ligne(ligne)


def _identite_regle(famille: _Famille, instance: dict) -> tuple:
    if famille.nom == FAMILLE_REFERENCES:
        cle = instance["cle"]
        valeurs = (instance["table"], ", ".join(cle), instance["table_reference"],
                   ", ".join(instance.get("cle_reference") or cle))
    elif famille.nom == FAMILLE_RENSEIGNEMENT:
        valeurs = (instance["table"], instance["colonne"], instance["selon"])
    else:
        valeurs = (instance["table"], instance["colonne"])
    return tuple(_texte(v) for v in valeurs) + _filtre_regle(instance)


def _designation(famille: _Famille, identite: tuple) -> str:
    """Colonnes d'une règle de famille, pour le rapport des changements."""
    if famille.nom == FAMILLE_REFERENCES:
        texte = f"{identite[1]} vers {identite[2]}.{identite[3]}"
    elif famille.nom == FAMILLE_RENSEIGNEMENT:
        texte = f"{identite[1]} selon {identite[2]}"
    else:
        texte = identite[1]
    filtre_colonne, filtre_valeurs = identite[-2:]
    if filtre_colonne:
        texte += f" (si {filtre_colonne} = {filtre_valeurs})"
    return texte


def _parametres_defaut(famille: _Famille) -> dict:
    if famille.nom == FAMILLE_REFERENCES:
        return {"cle_facultative": False, "comparaison": COMPARAISON_TELLE_QUELLE}
    if famille.nom == FAMILLE_RENSEIGNEMENT:
        return {"valeurs": [], "vide_sinon": False}
    return {}


def _parametres_regle(famille: _Famille, instance: dict) -> dict:
    """Paramètres modifiables d'une règle, sous la forme comparée aux saisies."""
    if famille.nom == FAMILLE_REFERENCES:
        return {
            "cle_facultative": bool(instance.get("cle_facultative")),
            "comparaison": instance.get("comparaison", COMPARAISON_TELLE_QUELLE),
        }
    if famille.nom == FAMILLE_RENSEIGNEMENT:
        return {
            "valeurs": [str(v) for v in instance["valeurs"]],
            "vide_sinon": bool(instance.get("vide_sinon")),
        }
    return {}


def _parametres_saisis(famille: _Famille, ligne: dict) -> tuple[dict | None, list[str]]:
    """Paramètres écrits dans les cellules modifiables d'une ligne, et les problèmes."""
    if famille.nom == FAMILLE_REFERENCES:
        facultative, probleme = _oui_non(ligne["clé_facultative"], "clé_facultative")
        problemes = [probleme] if probleme else []
        comparaison = _texte_cellule(ligne["comparaison"]) or COMPARAISON_TELLE_QUELLE
        if comparaison not in COMPARAISONS:
            problemes.append(
                f"comparaison : {', '.join(COMPARAISONS)} ou vide est attendu"
            )
        if problemes:
            return None, problemes
        return {"cle_facultative": facultative, "comparaison": comparaison}, []
    if famille.nom == FAMILLE_RENSEIGNEMENT:
        vide_sinon, probleme = _oui_non(ligne["vide_sinon"], "vide_sinon")
        if probleme:
            return None, [probleme]
        return {"valeurs": _decouper(_texte_cellule(ligne["valeurs"])),
                "vide_sinon": vide_sinon}, []
    return {}, []


def _parametres_proposes(famille: _Famille, ligne: dict, base: dict) -> dict | None:
    """Paramètres de la proposition d'une ligne (colonnes masquées), complétés par
    `base`; None si la proposition est « aucune »."""
    if _texte_cellule(ligne["proposition"]) in ("", AUCUNE):
        return None
    parametres = dict(base)
    if famille.nom == FAMILLE_REFERENCES:
        parametres["cle_facultative"] = (
            _texte_cellule(ligne["proposition_clé_facultative"]) == OUI
        )
    elif famille.nom == FAMILLE_RENSEIGNEMENT:
        valeurs = _decouper(_texte_cellule(ligne["proposition_valeurs"]))
        if not valeurs:
            return None
        parametres["valeurs"] = valeurs
        parametres["vide_sinon"] = _texte_cellule(ligne["proposition_vide_sinon"]) == OUI
    return parametres


def _exportes(famille: _Famille, ligne: dict, instance: dict | None) -> dict:
    """Paramètres tels que l'export les a écrits dans les cellules modifiables."""
    if instance is not None:
        return _parametres_regle(famille, instance)
    parametres = _parametres_defaut(famille)
    if famille.nom == FAMILLE_REFERENCES:
        parametres["cle_facultative"] = (
            _texte_cellule(ligne["proposition_clé_facultative"]) == OUI
        )
    elif famille.nom == FAMILLE_RENSEIGNEMENT:
        parametres["valeurs"] = _decouper(_texte_cellule(ligne["proposition_valeurs"]))
        parametres["vide_sinon"] = _texte_cellule(ligne["proposition_vide_sinon"]) == OUI
    return parametres


def _avec_cle(instance: dict, cle: str, valeur, apres: str | None = None) -> dict:
    """Copie d'une règle où `cle` vaut `valeur` : à sa place si elle y est, sinon
    après la clé `apres` (à la fin si `apres` est absente)."""
    if cle in instance:
        return {**instance, cle: valeur}
    nouvelle = {}
    for nom, existante in instance.items():
        nouvelle[nom] = existante
        if nom == apres:
            nouvelle[cle] = valeur
    nouvelle.setdefault(cle, valeur)
    return nouvelle


def _sans_cle(instance: dict, cle: str) -> dict:
    return {nom: valeur for nom, valeur in instance.items() if nom != cle}


def _appliquer_parametres(famille: _Famille, instance: dict, parametres: dict) -> dict:
    """Règle dont les paramètres modifiables prennent les valeurs données; un booléen
    faux ou une comparaison telle quelle s'écrivent par l'absence de la clé."""
    if parametres == _parametres_regle(famille, instance):
        return instance
    if famille.nom == FAMILLE_REFERENCES:
        if parametres["comparaison"] == COMPARAISON_TELLE_QUELLE:
            instance = _sans_cle(instance, "comparaison")
        else:
            apres = "cle_reference" if "cle_reference" in instance else "table_reference"
            instance = _avec_cle(instance, "comparaison", parametres["comparaison"], apres)
        if parametres["cle_facultative"]:
            instance = _avec_cle(instance, "cle_facultative", True,
                                 "comparaison" if "comparaison" in instance else None)
        else:
            instance = _sans_cle(instance, "cle_facultative")
    elif famille.nom == FAMILLE_RENSEIGNEMENT:
        if [str(v) for v in instance["valeurs"]] != parametres["valeurs"]:
            instance = {**instance, "valeurs": list(parametres["valeurs"])}
        if parametres["vide_sinon"]:
            instance = _avec_cle(instance, "vide_sinon", True, "valeurs")
        else:
            instance = _sans_cle(instance, "vide_sinon")
    return instance


def _maj_descriptif(instance: dict, ref, libelle, issue, commentaire) -> dict:
    """Règle dont la référence, le libellé, l'issue et le commentaire prennent les
    valeurs saisies (None pour la référence ou le libellé : inchangés; issue None :
    celle du type)."""
    if ref is not None and ref != instance["ref"]:
        instance = {**instance, "ref": ref}
    if libelle is not None and libelle != instance["libelle"]:
        instance = {**instance, "libelle": libelle}
    defaut = TYPES[instance["type"]].issue
    if (issue or defaut) != _issue(instance):
        if (issue or defaut) == defaut:
            instance = _sans_cle(instance, CLE_ISSUE)
        else:
            instance = _avec_cle(instance, CLE_ISSUE, issue)
    if commentaire != _commentaire_regle(instance):
        if commentaire is None:
            instance = _sans_cle(instance, CLE_COMMENTAIRE)
        else:
            instance = _avec_cle(instance, CLE_COMMENTAIRE, commentaire, "libelle")
    return instance


def _filtre_saisi(table: str, colonne: str, valeurs: str, dictionnaire: dict, lieu: str,
                  problemes: list, avertissements: list) -> list | None:
    """Filtre d'une ligne d'ajout (une condition sur des valeurs), None sans filtre."""
    if not colonne and not valeurs:
        return None
    if not colonne or not valeurs:
        problemes.append(f"{lieu} : filtre_colonne et filtre_valeurs vont ensemble")
        return None
    if colonne not in dictionnaire.get(table, {}):
        problemes.append(f"{lieu} : colonne de filtre {colonne!r} inconnue de la table {table}")
        return None
    choix = _decouper(valeurs)
    liste = _liste_en_vigueur(dictionnaire, table, colonne)
    if liste is not None:
        hors = [v for v in choix if v not in liste]
        if hors:
            avertissements.append(
                f"{lieu} : valeur de filtre hors de la liste en vigueur de {colonne} "
                f"({', '.join(hors)})"
            )
    return [{"colonne": colonne, "valeurs": choix}]


def _colonnes_connues(dictionnaire: dict, table: str, colonnes: list[str], nom: str,
                      lieu: str, problemes: list) -> bool:
    if table not in dictionnaire:
        problemes.append(f"{lieu} : table {table!r} inconnue du dictionnaire")
        return False
    if not colonnes:
        problemes.append(f"{lieu} : {nom} à remplir")
        return False
    inconnues = [c for c in colonnes if c not in dictionnaire[table]]
    if inconnues:
        problemes.append(
            f"{lieu} : {nom}, colonne inconnue de la table {table} ({', '.join(inconnues)})"
        )
        return False
    return True


def _libelle_defaut(famille: _Famille, identite: tuple, parametres: dict) -> str:
    if famille.nom == FAMILLE_REFERENCES:
        return f"{identite[0]}.{identite[1]} connue de {identite[2]}.{identite[3]}"
    if famille.nom == FAMILLE_RENSEIGNEMENT:
        return _libelle_renseignement(identite[1], identite[2], parametres["valeurs"],
                                      parametres["vide_sinon"])
    return f"{identite[1]} dans la période de l'export"


def _nouvelle_regle(famille: _Famille, identite: tuple, parametres: dict, filtre,
                    ref: str, libelle: str, issue, commentaire) -> dict:
    """Règle d'une famille construite d'après une ligne, clés dans l'ordre du type."""
    instance = {"ref": ref, "libelle": libelle}
    if commentaire is not None:
        instance[CLE_COMMENTAIRE] = commentaire
    instance.update({"type": famille.type, "table": identite[0]})
    if famille.nom == FAMILLE_REFERENCES:
        cle, cle_reference = _decouper(identite[1]), _decouper(identite[3])
        instance.update({"cle": cle, "table_reference": identite[2]})
        if cle_reference != cle:
            instance["cle_reference"] = cle_reference
        if parametres["comparaison"] != COMPARAISON_TELLE_QUELLE:
            instance["comparaison"] = parametres["comparaison"]
        if parametres["cle_facultative"]:
            instance["cle_facultative"] = True
    elif famille.nom == FAMILLE_RENSEIGNEMENT:
        instance.update({"colonne": identite[1], "selon": identite[2],
                         "valeurs": list(parametres["valeurs"])})
        if parametres["vide_sinon"]:
            instance["vide_sinon"] = True
    else:
        instance["colonne"] = identite[1]
    if filtre:
        instance[CLE_FILTRE] = filtre
    if issue is not None and issue != TYPES[famille.type].issue:
        instance[CLE_ISSUE] = issue
    return instance


def _texte_regle(instance: dict) -> str:
    """Règle en clair pour le rapport : paramètres, filtre et issue."""
    parties = [texte_parametres(instance)]
    filtre = _texte_filtre(instance.get(CLE_FILTRE))
    if filtre:
        parties.append(f"filtre = {filtre}")
    parties.append(f"issue = {_issue(instance)}")
    return "; ".join(partie for partie in parties if partie)


def _difference(avant: dict, apres: dict) -> tuple[str, str]:
    """Clés qui changent entre deux versions d'une règle, en clair."""
    noms = [cle for cle in avant if avant.get(cle, ABSENT) != apres.get(cle, ABSENT)]
    noms += [cle for cle in apres if cle not in avant]

    def ecrire(instance):
        return "; ".join(
            f"{nom} = {_texte_valeur(instance[nom])}" if nom in instance else f"{nom} {ABSENT}"
            for nom in noms
        )

    return ecrire(avant), ecrire(apres)


class _Etat:
    """Décisions lues dans le classeur, appliquées ensuite au contenu."""

    def __init__(self, contenu: dict):
        self.regles = list(contenu.get(CLE_REGLES_GESTION) or [])
        self.retirees = list(contenu.get(CLE_RETIREES) or [])
        # Sort des règles désignées par une ligne : rang vers (action, règle).
        self.sort_regles: dict[int, tuple[str, dict | None]] = {}
        self.sort_retirees: dict[int, tuple[str, dict | None]] = {}
        self.insertions: list[dict] = []
        ecartees = contenu.get(CLE_ECARTEES) or {}
        self.ecartees = {
            famille.nom: list(ecartees.get(famille.nom) or []) for famille in FAMILLES
        }
        self.ecartees_retirees: dict[str, set[int]] = {f.nom: set() for f in FAMILLES}
        self.ecartees_ajoutees: dict[str, list[dict]] = {f.nom: [] for f in FAMILLES}
        self.ecartees_vues: dict[str, set[int]] = {f.nom: set() for f in FAMILLES}
        self.changements: list[tuple] = []

    def noter(self, feuille, ref, table, colonnes, changement, avant="", apres=""):
        self.changements.append((feuille, ref, table, colonnes, changement, avant, apres))


def _lire_rang(ligne: dict, origine: str, etat: _Etat, lieu: str,
               problemes: list) -> tuple[list | None, int | None]:
    """Liste (règles ou règles retirées) et rang désignés par la colonne masquée."""
    source, deja = (
        (etat.regles, etat.sort_regles) if origine == ORIGINE_EN_VIGUEUR
        else (etat.retirees, etat.sort_retirees)
    )
    valeur = ligne["rang"]
    if isinstance(valeur, float) and valeur.is_integer():
        valeur = int(valeur)
    if isinstance(valeur, str) and valeur.strip().isdigit():
        valeur = int(valeur.strip())
    if isinstance(valeur, bool) or not isinstance(valeur, int) or not 0 <= valeur < len(source):
        problemes.append(f"{lieu} : colonne masquée rang illisible, formulaire à réexporter")
        return None, None
    if valeur in deja:
        problemes.append(
            f"{lieu} : règle déjà désignée par une autre ligne (ligne recopiée), formulaire à "
            "réexporter"
        )
        return None, None
    return source, valeur


def _desaccord(lieu: str, rang: int, origine: str) -> str:
    cle = CLE_REGLES_GESTION if origine == ORIGINE_EN_VIGUEUR else CLE_RETIREES
    return (
        f"{lieu} : la ligne ne correspond plus à la règle n° {rang + 1} de la clé {cle} "
        "(ligne déplacée ou recopiée), formulaire à réexporter"
    )


def _issue_saisie(ligne: dict, lieu: str, problemes: list) -> tuple[str | None, bool]:
    """Issue saisie (None : celle du type) et vrai si la saisie est lisible."""
    issue = _texte_cellule(ligne["issue"])
    if issue and issue not in ISSUES:
        problemes.append(f"{lieu} : issue inconnue {issue!r} (issues possibles : "
                         f"{', '.join(ISSUES)})")
        return None, False
    return issue or None, True


def _verifier_valeurs(famille: _Famille, identite: tuple, parametres: dict,
                      dictionnaire: dict, lieu: str, problemes: list,
                      avertissements: list) -> None:
    """Contrôle des valeurs d'une règle de renseignement nouvelle ou modifiée."""
    if famille.nom != FAMILLE_RENSEIGNEMENT:
        return
    valeurs = parametres["valeurs"]
    if not valeurs:
        problemes.append(f"{lieu} : valeurs à remplir (séparées par une virgule)")
        return
    liste = _liste_en_vigueur(dictionnaire, identite[0], identite[2])
    if liste is None:
        avertissements.append(
            f"{lieu} : {identite[2]} n'a pas de liste fermée en vigueur, valeurs non vérifiées"
        )
        return
    hors = [v for v in valeurs if v not in liste]
    if hors:
        problemes.append(
            f"{lieu} : valeurs hors de la liste en vigueur de {identite[2]} "
            f"({', '.join(hors)})"
        )


def _identite_ajout(famille: _Famille, ligne: dict, dictionnaire: dict, lieu: str,
                    problemes: list) -> tuple | None:
    """Colonnes qui désignent la règle d'une ligne d'ajout, contrôlées contre le
    dictionnaire (None si elles ne conviennent pas)."""
    identite = _identite_ligne(famille, ligne)
    table = identite[0]
    if not table:
        problemes.append(f"{lieu} : table à remplir")
        return None
    if famille.nom == FAMILLE_REFERENCES:
        cle = _decouper(identite[1])
        cle_reference = _decouper(identite[3]) or cle
        if not _colonnes_connues(dictionnaire, table, cle, "colonne", lieu, problemes):
            return None
        if not identite[2]:
            problemes.append(f"{lieu} : table_reference à remplir")
            return None
        if not _colonnes_connues(dictionnaire, identite[2], cle_reference,
                                 "colonne_reference", lieu, problemes):
            return None
        if len(cle) != len(cle_reference):
            problemes.append(
                f"{lieu} : colonne et colonne_reference n'ont pas le même nombre de colonnes"
            )
            return None
        return (table, ", ".join(cle), identite[2], ", ".join(cle_reference)) + identite[4:]
    if famille.nom == FAMILLE_RENSEIGNEMENT:
        if not _colonnes_connues(dictionnaire, table, [c for c in identite[1:3] if c] or [],
                                 "colonne et selon", lieu, problemes):
            return None
        if not identite[1] or not identite[2]:
            problemes.append(f"{lieu} : colonne et selon à remplir")
            return None
        return identite
    if not _colonnes_connues(dictionnaire, table, [identite[1]] if identite[1] else [],
                             "colonne", lieu, problemes):
        return None
    nature = dictionnaire[table][identite[1]]["nature"]["regle"]
    if nature not in NATURES_DATE:
        problemes.append(
            f"{lieu} : {identite[1]} n'est pas une colonne de date (nature {nature})"
        )
        return None
    return identite


def _importer_famille(famille: _Famille, lignes: list[tuple[int, dict]], dictionnaire: dict,
                      etat: _Etat, problemes: list, avertissements: list) -> None:
    """Applique à `etat` les lignes de la feuille d'une famille (voir
    `importer_formulaire_gestion`)."""
    cles_ecartees = CLES_PROPOSITION_ECARTEE[famille.nom]
    for numero, ligne in lignes:
        lieu = f"feuille « {famille.feuille} », ligne {numero}"
        origine, statut = _texte_cellule(ligne["origine"]), _texte_cellule(ligne["statut"])
        if origine and origine not in ORIGINES:
            problemes.append(f"{lieu} : origine {origine!r} inconnue, formulaire à réexporter")
            continue
        if statut not in STATUTS:
            problemes.append(
                f"{lieu} : statut {'absent' if not statut else repr(statut)} (statuts "
                f"possibles : {', '.join(STATUTS)})"
            )
            continue
        nombre = len(problemes)
        issue, lisible = _issue_saisie(ligne, lieu, problemes)
        ref, libelle = _texte_cellule(ligne["ref"]), _texte_cellule(ligne["libellé"])
        commentaire = _commentaire_saisi(ligne["commentaire"])

        if not origine:
            # Ligne d'ajout.
            if statut != STATUT_DOCUMENTE:
                problemes.append(f"{lieu} : une ligne ajoutée doit être au statut documenté")
                continue
            identite = _identite_ajout(famille, ligne, dictionnaire, lieu, problemes)
            saisis, erreurs = _parametres_saisis(famille, ligne)
            problemes.extend(f"{lieu} : {erreur}" for erreur in erreurs)
            if identite is None or saisis is None or not lisible:
                continue
            filtre = _filtre_saisi(identite[0], *identite[-2:], dictionnaire, lieu, problemes,
                                   avertissements)
            _verifier_valeurs(famille, identite, saisis, dictionnaire, lieu, problemes,
                              avertissements)
            if len(problemes) > nombre:
                continue
            instance = _nouvelle_regle(
                famille, identite, saisis, filtre, ref or famille.ref,
                libelle or _libelle_defaut(famille, identite, saisis), issue, commentaire,
            )
            etat.insertions.append(instance)
            etat.noter(famille.feuille, instance["ref"], identite[0],
                       _designation(famille, identite), CHANGEMENT_AJOUTEE,
                       apres=_texte_regle(instance))
            continue

        identite = _identite_ligne(famille, ligne)
        instance, source, rang = None, None, None
        if origine in (ORIGINE_EN_VIGUEUR, ORIGINE_RETIREE):
            source, rang = _lire_rang(ligne, origine, etat, lieu, problemes)
            if source is None:
                continue
            instance = source[rang]
            if (
                not isinstance(instance, dict)
                or instance.get("type") != famille.type
                or not famille.en_famille(instance)
                or _identite_regle(famille, instance) != identite
            ):
                problemes.append(_desaccord(lieu, rang, origine))
                continue
        rang_ecartee = None
        if origine == ORIGINE_ECARTEE:
            element = {cle: _texte_cellule(ligne[nom]) for cle, nom in zip(
                cles_ecartees, ("table", "colonne", famille.colonnes[2], famille.colonnes[3])
            )}
            trouves = [i for i, e in enumerate(etat.ecartees[famille.nom]) if e == element]
            if not trouves:
                problemes.append(
                    f"{lieu} : proposition écartée absente de config/gestion.yaml, formulaire à "
                    "réexporter"
                )
                continue
            rang_ecartee = trouves[0]
            if rang_ecartee in etat.ecartees_vues[famille.nom]:
                problemes.append(f"{lieu} : proposition écartée désignée deux fois")
                continue
            etat.ecartees_vues[famille.nom].add(rang_ecartee)

        exportes = _exportes(famille, ligne, instance)
        saisis, erreurs = _parametres_saisis(famille, ligne)
        base = (
            _parametres_regle(famille, instance) if instance is not None
            else _parametres_defaut(famille)
        )
        proposes = _parametres_proposes(famille, ligne, base)
        if statut == STATUT_DOCUMENTE:
            problemes.extend(f"{lieu} : {erreur}" for erreur in erreurs)
            parametres = saisis
        elif statut == STATUT_VALIDE:
            if proposes is None:
                problemes.append(f"{lieu} : valide impossible, la proposition est « {AUCUNE} »")
                continue
            parametres = proposes
            if saisis != proposes:
                avertissements.append(
                    f"{lieu} : valeurs saisies ignorées, valide adopte la proposition"
                )
        else:
            parametres = None
            if saisis != exportes:
                avertissements.append(f"{lieu} : valeurs saisies ignorées (statut {statut})")
        if len(problemes) > nombre or not lisible:
            continue
        retenue = statut in (STATUT_DOCUMENTE, STATUT_VALIDE)
        if instance is not None and retenue and (not ref or not libelle):
            problemes.append(f"{lieu} : ref et libellé à remplir")
            continue
        if retenue and parametres != base:
            _verifier_valeurs(famille, identite, parametres, dictionnaire, lieu, problemes,
                              avertissements)
            if len(problemes) > nombre:
                continue
        designation = _designation(famille, identite)

        if instance is not None:
            ancienne = instance
            if retenue or statut == STATUT_INVALIDE:
                if retenue:
                    instance = _appliquer_parametres(famille, instance, parametres)
                instance = _maj_descriptif(instance, ref or None, libelle or None, issue,
                                           commentaire)
            if origine == ORIGINE_EN_VIGUEUR:
                if retenue:
                    etat.sort_regles[rang] = ("garder", instance)
                    if instance != ancienne:
                        etat.noter(famille.feuille, instance["ref"], identite[0], designation,
                                   CHANGEMENT_MODIFIEE, *_difference(ancienne, instance))
                elif statut == STATUT_INVALIDE:
                    etat.sort_regles[rang] = ("retirer", instance)
                    etat.noter(famille.feuille, instance["ref"], identite[0], designation,
                               CHANGEMENT_RETIREE, avant=_texte_regle(ancienne))
                else:
                    etat.sort_regles[rang] = ("supprimer", None)
                    avertissements.append(
                        f"{lieu} : règle en vigueur remise à observé, supprimée sans être "
                        "gardée parmi les règles retirées"
                    )
                    etat.noter(famille.feuille, ancienne["ref"], identite[0], designation,
                               CHANGEMENT_SUPPRIMEE, avant=_texte_regle(ancienne))
            else:
                if retenue:
                    etat.sort_retirees[rang] = ("retablir", None)
                    etat.insertions.append(instance)
                    etat.noter(famille.feuille, instance["ref"], identite[0], designation,
                               CHANGEMENT_RETABLIE, apres=_texte_regle(instance))
                elif statut == STATUT_INVALIDE:
                    etat.sort_retirees[rang] = ("garder", instance)
                else:
                    etat.sort_retirees[rang] = ("supprimer", None)
                    avertissements.append(
                        f"{lieu} : règle retirée remise à observé, oubliée (elle ne pourra "
                        "plus être rétablie)"
                    )
                    etat.noter(famille.feuille, ancienne["ref"], identite[0], designation,
                               CHANGEMENT_SUPPRIMEE, avant=_texte_regle(ancienne))
            continue

        # Proposition, ou proposition écartée.
        if retenue:
            nouvelle = _nouvelle_regle(
                famille, identite, parametres, None, ref or famille.ref,
                libelle or _libelle_defaut(famille, identite, parametres), issue, commentaire,
            )
            etat.insertions.append(nouvelle)
            etat.noter(famille.feuille, nouvelle["ref"], identite[0], designation,
                       CHANGEMENT_AJOUTEE, apres=_texte_regle(nouvelle))
            if rang_ecartee is not None:
                etat.ecartees_retirees[famille.nom].add(rang_ecartee)
            continue
        if commentaire is not None:
            avertissements.append(f"{lieu} : commentaire non conservé (aucune règle)")
        if origine == ORIGINE_PROPOSEE and statut == STATUT_INVALIDE:
            etat.ecartees_ajoutees[famille.nom].append({
                cle: _texte_cellule(ligne[nom]) for cle, nom in zip(
                    cles_ecartees, ("table", "colonne", famille.colonnes[2],
                                    famille.colonnes[3])
                )
            })
            etat.noter(famille.feuille, "", identite[0], designation, CHANGEMENT_ECARTEE)
        elif origine == ORIGINE_ECARTEE and statut == STATUT_OBSERVE:
            etat.ecartees_retirees[famille.nom].add(rang_ecartee)
            etat.noter(famille.feuille, "", identite[0], designation, CHANGEMENT_REPROPOSEE)


def _importer_autres(lignes: list[tuple[int, dict]], etat: _Etat, problemes: list,
                     avertissements: list) -> None:
    """Applique à `etat` les lignes de la feuille des autres règles."""
    for numero, ligne in lignes:
        lieu = f"feuille « {FEUILLE_AUTRES} », ligne {numero}"
        origine, statut = _texte_cellule(ligne["origine"]), _texte_cellule(ligne["statut"])
        if origine not in (ORIGINE_EN_VIGUEUR, ORIGINE_RETIREE):
            problemes.append(
                f"{lieu} : origine {origine!r} inattendue (pas de ligne d'ajout dans cette "
                "feuille), formulaire à réexporter"
            )
            continue
        if statut not in (STATUT_DOCUMENTE, STATUT_INVALIDE):
            problemes.append(
                f"{lieu} : statut {'absent' if not statut else repr(statut)}, documenté ou "
                "invalide est attendu (pas de proposition dans cette feuille)"
            )
            continue
        nombre = len(problemes)
        source, rang = _lire_rang(ligne, origine, etat, lieu, problemes)
        if source is None:
            continue
        instance = source[rang]
        identite = tuple(_texte_cellule(ligne[nom]) for nom in ("type", "table", "paramètres",
                                                                 "filtre"))
        if (
            not isinstance(instance, dict)
            or any(famille.en_famille(instance) for famille in FAMILLES)
            or identite != (
                _texte(instance.get("type")), _texte(instance.get("table")),
                _texte(texte_parametres(instance)),
                _texte(_texte_filtre(instance.get(CLE_FILTRE))),
            )
        ):
            problemes.append(_desaccord(lieu, rang, origine))
            continue
        issue, lisible = _issue_saisie(ligne, lieu, problemes)
        libelle = _texte_cellule(ligne["libellé"])
        if not libelle:
            problemes.append(f"{lieu} : libellé à remplir")
        if len(problemes) > nombre or not lisible:
            continue
        ancienne = instance
        instance = _maj_descriptif(instance, None, libelle, issue,
                                   _commentaire_saisi(ligne["commentaire"]))
        colonnes = texte_parametres(ancienne)
        if origine == ORIGINE_EN_VIGUEUR and statut == STATUT_DOCUMENTE:
            etat.sort_regles[rang] = ("garder", instance)
            if instance != ancienne:
                etat.noter(FEUILLE_AUTRES, instance["ref"], instance["table"], colonnes,
                           CHANGEMENT_MODIFIEE, *_difference(ancienne, instance))
        elif origine == ORIGINE_EN_VIGUEUR:
            etat.sort_regles[rang] = ("retirer", instance)
            etat.noter(FEUILLE_AUTRES, instance["ref"], instance["table"], colonnes,
                       CHANGEMENT_RETIREE, avant=_texte_regle(ancienne))
        elif statut == STATUT_DOCUMENTE:
            etat.sort_retirees[rang] = ("retablir", None)
            etat.insertions.append(instance)
            etat.noter(FEUILLE_AUTRES, instance["ref"], instance["table"], colonnes,
                       CHANGEMENT_RETABLIE, apres=_texte_regle(instance))
        else:
            etat.sort_retirees[rang] = ("garder", instance)


def _date_saisie(valeur) -> date | None:
    """Date d'une cellule : date d'Excel, ou texte JJ/MM/AAAA ou AAAA-MM-JJ."""
    if isinstance(valeur, dt.datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    texte = _texte_cellule(valeur)
    for forme in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(texte, forme).date()
        except ValueError:
            continue
    return None


def _jours_par_annee(jours: set[date]) -> dict[int, set[date]]:
    annees: dict[int, set[date]] = {}
    for jour in jours:
        annees.setdefault(jour.year, set()).add(jour)
    return annees


def _ecrire_jours(original, jours: set[date]) -> dict:
    """Jours fériés (année vers liste) d'après les dates retenues; une année dont les
    dates ne changent pas garde sa liste telle quelle, une année déclarée sans date
    retenue garde une liste vide."""
    original = original if isinstance(original, dict) else {}
    par_annee = _jours_par_annee(jours)
    anciens = _jours_declares(original)
    resultat = {}
    for cle in original:
        annee = _annee_feries(cle)
        if annee is None:
            continue
        if set(anciens.get(annee, [])) == par_annee.get(annee, set()):
            resultat[cle] = original[cle]
        else:
            resultat[cle] = [jour.isoformat() for jour in sorted(par_annee.get(annee, set()))]
    for annee in sorted(set(par_annee) - set(anciens)):
        resultat[annee] = [jour.isoformat() for jour in sorted(par_annee[annee])]
    return resultat


def _importer_feries(lignes: list[tuple[int, dict]], contenu: dict, etat: _Etat,
                     problemes: list, avertissements: list) -> tuple[dict, dict]:
    """Jours fériés déclarés et écartés après la revue de leur feuille."""
    declares = {j for jours in _jours_declares(contenu.get(CLE_JOURS_FERIES)).values()
                for j in jours}
    ecartes = {j for jours in _jours_declares(_ecartees(contenu, FAMILLE_FERIES)).values()
               for j in jours}
    nouveaux_declares, nouveaux_ecartes, vus = set(declares), set(ecartes), set()
    for numero, ligne in lignes:
        lieu = f"feuille « {FEUILLE_FERIES} », ligne {numero}"
        origine, statut = _texte_cellule(ligne["origine"]), _texte_cellule(ligne["statut"])
        jour = _date_saisie(ligne["date"])
        if jour is None:
            problemes.append(f"{lieu} : date illisible (JJ/MM/AAAA attendu)")
            continue
        if origine and origine not in (ORIGINE_EN_VIGUEUR, ORIGINE_PROPOSEE, ORIGINE_ECARTEE):
            problemes.append(f"{lieu} : origine {origine!r} inconnue, formulaire à réexporter")
            continue
        if statut not in STATUTS:
            problemes.append(
                f"{lieu} : statut {'absent' if not statut else repr(statut)} (statuts "
                f"possibles : {', '.join(STATUTS)})"
            )
            continue
        if not origine and statut != STATUT_DOCUMENTE:
            problemes.append(f"{lieu} : une date ajoutée doit être au statut documenté")
            continue
        if jour in vus:
            problemes.append(f"{lieu} : date {jour:%d/%m/%Y} déjà présente dans la feuille")
            continue
        vus.add(jour)
        nouveaux_declares.discard(jour)
        nouveaux_ecartes.discard(jour)
        if statut in (STATUT_DOCUMENTE, STATUT_VALIDE):
            nouveaux_declares.add(jour)
        elif statut == STATUT_INVALIDE:
            nouveaux_ecartes.add(jour)
    absents = (declares | ecartes) - vus
    if absents:
        avertissements.append(
            f"feuille « {FEUILLE_FERIES} » : {len(absents)} dates de config/gestion.yaml "
            "absentes du formulaire, laissées telles quelles"
        )

    def etat_jour(jour, dans_declares, dans_ecartes):
        return "déclarée" if jour in dans_declares else "écartée" if jour in dans_ecartes else ""

    for jour in sorted(declares | ecartes | nouveaux_declares | nouveaux_ecartes):
        avant = etat_jour(jour, declares, ecartes)
        apres = etat_jour(jour, nouveaux_declares, nouveaux_ecartes)
        if avant == apres:
            continue
        if apres == "déclarée":
            changement = CHANGEMENT_DECLAREE
        elif apres == "écartée":
            changement = CHANGEMENT_ECARTEE
        elif avant == "déclarée":
            changement = CHANGEMENT_RETIREE
        else:
            changement = CHANGEMENT_REPROPOSEE
        etat.noter(FEUILLE_FERIES, "", "", jour.isoformat(), changement, avant, apres)
    if nouveaux_declares == declares:
        jours_feries = contenu.get(CLE_JOURS_FERIES)
    else:
        jours_feries = _ecrire_jours(contenu.get(CLE_JOURS_FERIES), nouveaux_declares)
    if nouveaux_ecartes == ecartes:
        jours_ecartes = _ecartees(contenu, FAMILLE_FERIES)
    else:
        jours_ecartes = {
            cle: liste for cle, liste in _ecrire_jours(
                _ecartees(contenu, FAMILLE_FERIES), nouveaux_ecartes
            ).items() if liste
        }
    return jours_feries, jours_ecartes


def _demande_normalisee(demande: dict) -> dict:
    return {
        cle: _texte_cellule(valeur) for cle, valeur in demande.items()
        if _texte_cellule(valeur)
    }


def _importer_nouvelles(lignes: list[tuple[int, dict]], contenu: dict, etat: _Etat,
                        problemes: list) -> list:
    """Règles demandées en texte libre, d'après la feuille des nouvelles règles."""
    demandes = []
    for numero, ligne in lignes:
        demande = {
            cle: _commentaire_saisi(ligne[nom]) for cle, nom in COLONNES_DEMANDE.items()
        }
        demande = {cle: valeur for cle, valeur in demande.items() if valeur is not None}
        if "regle" not in demande:
            problemes.append(
                f"feuille « {FEUILLE_NOUVELLES} », ligne {numero} : colonne "
                f"{COLONNES_DEMANDE['regle']} à remplir"
            )
            continue
        demandes.append(demande)
    anciennes = list(contenu.get(CLE_DEMANDES) or [])
    normalisees = [_demande_normalisee(d) for d in anciennes if isinstance(d, dict)]
    if normalisees == [_demande_normalisee(d) for d in demandes]:
        return anciennes
    restantes = list(normalisees)
    for demande in demandes:
        if _demande_normalisee(demande) in restantes:
            restantes.remove(_demande_normalisee(demande))
        else:
            etat.noter(FEUILLE_NOUVELLES, "", demande.get("tables", ""),
                       demande.get("colonnes", ""), CHANGEMENT_DEMANDEE,
                       apres=demande["regle"])
    for demande in restantes:
        etat.noter(FEUILLE_NOUVELLES, "", demande.get("tables", ""),
                   demande.get("colonnes", ""), CHANGEMENT_RETIREE, avant=demande["regle"])
    return demandes


def _regles_apres(etat: _Etat, avertissements: list) -> tuple[list, list]:
    """Règles et règles retirées après la revue : les règles gardent l'ordre du
    fichier; une règle nouvelle ou rétablie se place après la dernière règle du même
    type (à la fin s'il n'y en a pas); une règle retirée s'ajoute à la fin des règles
    retirées."""
    absentes = (len(etat.regles) - len(etat.sort_regles)
                + len(etat.retirees) - len(etat.sort_retirees))
    if absentes:
        avertissements.append(
            f"{absentes} règles de config/gestion.yaml absentes du formulaire, laissées "
            "telles quelles"
        )
    regles, retirees_nouvelles = [], []
    for rang, instance in enumerate(etat.regles):
        action, modifiee = etat.sort_regles.get(rang, ("garder", instance))
        if action == "garder":
            regles.append(modifiee)
        elif action == "retirer":
            retirees_nouvelles.append(modifiee)
    for instance in etat.insertions:
        rangs = [i for i, r in enumerate(regles)
                 if isinstance(r, dict) and r.get("type") == instance["type"]]
        regles.insert(rangs[-1] + 1 if rangs else len(regles), instance)
    retirees = []
    for rang, instance in enumerate(etat.retirees):
        action, modifiee = etat.sort_retirees.get(rang, ("garder", instance))
        if action == "garder":
            retirees.append(modifiee)
    return regles, retirees + retirees_nouvelles


def _lire_empreinte_gestion(classeur) -> str:
    """Empreinte de config/gestion.yaml inscrite dans le formulaire à l'export."""
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


def _remplacer(contenu: dict, cle: str, valeur) -> None:
    """Met `valeur` sous `cle`, ou retire la clé si la valeur est vide (une clé déjà
    présente avec une valeur vide est gardée telle quelle)."""
    if valeur:
        contenu[cle] = valeur
    elif cle in contenu and contenu[cle]:
        del contenu[cle]


def importer_formulaire_gestion(
    chemin: str | Path, dictionnaire: dict, contenu: dict, *, empreinte: str
) -> Formulaire:
    """Lit un formulaire des règles de gestion revu par le métier et contrôle chaque
    ligne, sans rien écrire.

    `contenu` est le contenu actuel de config/gestion.yaml
    (`gestion.lire_fichier_gestion`) et `empreinte` son empreinte (`empreinte_gestion`) :
    un formulaire exporté avant une modification du fichier est refusé.

    Feuilles des familles, selon l'origine de la ligne. Règle en vigueur : documenté la
    garde avec les modifications saisies, valide adopte la proposition, invalide la
    passe sous `retirees` (en entier), observé la supprime sans la garder. Proposition :
    documenté ou valide en fait une règle (valeurs saisies, ou proposition adoptée),
    invalide la mémorise sous `ecartees`. Proposition écartée : documenté ou valide en
    fait une règle, observé la retire de `ecartees`. Règle retirée : documenté ou valide
    la rétablit, observé l'oublie. valide est refusé quand la proposition est
    « aucune »; une valeur saisie qui ne sert pas est ignorée, avec un avertissement.
    Une ligne ajoutée en bas d'une feuille doit être au statut documenté; sa référence
    et son libellé laissés vides prennent ceux d'une proposition.

    Feuille des autres règles : documenté garde ou rétablit la règle (libellé, issue et
    commentaire modifiables), invalide la retire ou la laisse retirée. Feuille des jours
    fériés : documenté ou valide déclare la date, invalide l'écarte, observé ne la
    déclare ni ne l'écarte. Feuille des nouvelles règles : ses lignes remplacent les
    règles demandées.

    Les règles gardent l'ordre du fichier; une règle nouvelle ou rétablie se place après
    la dernière règle en vigueur du même type. Tous les problèmes bloquants sont listés
    en une fois dans une ValueError, avec la feuille et le numéro de ligne Excel. Rend
    le nouveau contenu, le rapport des changements (`COLONNES_CHANGEMENTS_GESTION`) et
    les avertissements.
    """
    chemin = Path(chemin)
    classeur = load_workbook(chemin, read_only=True, data_only=True)
    try:
        try:
            lignes = {
                famille.nom: _lire_feuille(classeur, famille.feuille, famille.colonnes)
                for famille in FAMILLES
            }
            lignes_feries = _lire_feuille(classeur, FEUILLE_FERIES, COLONNES_FERIES)
            lignes_autres_regles = _lire_feuille(classeur, FEUILLE_AUTRES, COLONNES_AUTRES)
            lignes_demandes = _lire_feuille(classeur, FEUILLE_NOUVELLES, COLONNES_NOUVELLES)
            repere = _lire_empreinte_gestion(classeur)
        except ValueError as erreur:
            raise ValueError(f"Formulaire invalide ({chemin})\n  {erreur}") from None
    finally:
        classeur.close()
    if repere != empreinte:
        raise ValueError(
            f"Formulaire périmé ({chemin}) : config/gestion.yaml a changé depuis son export "
            f"(empreinte {repere} à l'export, {empreinte} aujourd'hui). Ce formulaire a "
            "déjà été appliqué, ou le fichier a été modifié depuis : à réexporter."
        )
    problemes = problemes_contenu_formulaire(contenu)
    if problemes:
        raise ValueError(
            "Fichier des règles de gestion invalide\n  " + "\n  ".join(problemes)
        )

    etat = _Etat(contenu)
    problemes, avertissements = [], []
    for famille in FAMILLES:
        _importer_famille(famille, lignes[famille.nom], dictionnaire, etat, problemes,
                          avertissements)
    _importer_autres(lignes_autres_regles, etat, problemes, avertissements)
    jours_feries, jours_ecartes = _importer_feries(lignes_feries, contenu, etat, problemes,
                                                   avertissements)
    demandes = _importer_nouvelles(lignes_demandes, contenu, etat, problemes)
    if problemes:
        raise ValueError(
            f"Formulaire invalide ({chemin}), {len(problemes)} problèmes\n  "
            + "\n  ".join(problemes)
        )
    regles, retirees = _regles_apres(etat, avertissements)

    nouveau = copy.deepcopy(contenu)
    _remplacer(nouveau, CLE_JOURS_FERIES, jours_feries)
    _remplacer(nouveau, CLE_REGLES_GESTION, regles)
    _remplacer(nouveau, CLE_RETIREES, retirees)
    ecartees = dict(nouveau.get(CLE_ECARTEES) or {})
    for famille in FAMILLES:
        elements = [
            e for i, e in enumerate(etat.ecartees[famille.nom])
            if i not in etat.ecartees_retirees[famille.nom]
        ] + etat.ecartees_ajoutees[famille.nom]
        if elements != etat.ecartees[famille.nom]:
            _remplacer(ecartees, famille.nom, elements)
    _remplacer(ecartees, FAMILLE_FERIES, jours_ecartes)
    _remplacer(nouveau, CLE_ECARTEES, ecartees)
    _remplacer(nouveau, CLE_DEMANDES, demandes)
    problemes = problemes_contenu_formulaire(nouveau)
    if problemes:
        raise ValueError(
            f"Formulaire invalide ({chemin}), {len(problemes)} problèmes après la revue\n  "
            + "\n  ".join(problemes)
        )
    changements = pd.DataFrame(etat.changements, columns=list(COLONNES_CHANGEMENTS_GESTION))
    return Formulaire(nouveau, changements, avertissements)


# --- Écriture de config/gestion.yaml ----------------------------------------------

ENTETE_GESTION = """\
# Règles de gestion propres au client, données par le métier.
# Chaque règle est une instance d'un type du catalogue (voir frigeo.gestion.catalogue_types),
# avec ref (référence de la règle), libelle (texte affiché), type, table, les paramètres du
# type, et en option filtre, issue et commentaire. Une règle qui n'entre dans aucun type
# demande un nouveau type générique dans src/.
# Ce fichier est réécrit en entier par le formulaire des règles de gestion (notebook 05),
# qui ne garde pas les lignes de commentaire écrites à la main; le commentaire d'une règle
# s'écrit sous sa clé commentaire.
"""
COMMENTAIRE_JOURS_FERIES = """\
# Jours fériés, repris par chaque règle d'horaires qui n'en déclare pas (clé feries).
"""
COMMENTAIRE_RETIREES = """\
# Règles retirées par le métier, gardées en entier pour pouvoir les rétablir
# (sans effet sur les contrôles).
"""
COMMENTAIRE_ECARTEES_GESTION = """\
# Propositions du formulaire écartées par le métier, qui ne sont plus proposées
# (sans effet sur les contrôles).
"""
COMMENTAIRE_DEMANDES = """\
# Règles demandées par le métier en texte libre, que le consultant traduira en règles
# du catalogue (sans effet sur les contrôles).
"""
# Nombre de dates par ligne dans les listes de jours fériés.
DATES_PAR_LIGNE = 6
# Colonne vers laquelle un commentaire de règle est replié.
LARGEUR_COMMENTAIRE = 84
_MOTIF_HEURE_TEXTE = re.compile(r"\d{1,2}:\d{2}")


def _scalaire(valeur, cle=None) -> str:
    """Valeur simple écrite en YAML, utilisable dans une liste ou un dictionnaire en
    ligne; un motif et une heure sont écrits entre apostrophes."""
    if isinstance(valeur, str) and (cle == "motif" or _MOTIF_HEURE_TEXTE.fullmatch(valeur)):
        return "'" + valeur.replace("'", "''") + "'"
    texte = yaml.safe_dump(
        [valeur], default_flow_style=True, allow_unicode=True, width=10**9
    ).strip()
    if "\n" in texte:
        texte = "[" + json.dumps(valeur, ensure_ascii=False) + "]"
    return texte[1:-1]


def _est_scalaire(valeur) -> bool:
    return not isinstance(valeur, (list, dict))


def _en_ligne(valeur, creneaux: bool = False) -> bool:
    """Vrai si la valeur s'écrit sur une ligne : valeur simple, liste ou dictionnaire
    de valeurs simples, et dans des horaires, liste de créneaux."""
    if _est_scalaire(valeur):
        return True
    elements = valeur.values() if isinstance(valeur, dict) else valeur
    if all(_est_scalaire(e) for e in elements):
        return True
    return creneaux and isinstance(valeur, list) and all(
        isinstance(e, dict) and all(_est_scalaire(v) for v in e.values()) for e in valeur
    )


def _flux(valeur, cle=None) -> str:
    """Valeur écrite en ligne (listes et dictionnaires entre crochets ou accolades)."""
    if isinstance(valeur, list):
        return "[" + ", ".join(_flux(v, cle) for v in valeur) + "]"
    if isinstance(valeur, dict):
        return "{" + ", ".join(
            f"{_scalaire(k)}: {_flux(v, k)}" for k, v in valeur.items()
        ) + "}"
    return _scalaire(valeur, cle)


def _scalaire_bloc(valeur, cle, retrait: int) -> str:
    """Valeur simple d'une clé écrite en bloc (hors d'une liste en ligne) : un motif et
    une heure entre apostrophes, un texte sur plusieurs lignes entre guillemets avec
    « \n », un commentaire replié vers la centième colonne."""
    if isinstance(valeur, str) and (cle == "motif" or _MOTIF_HEURE_TEXTE.fullmatch(valeur)):
        return _scalaire(valeur, cle)
    if cle == CLE_COMMENTAIRE and isinstance(valeur, str) and "\n" not in valeur:
        largeur = max(40, LARGEUR_COMMENTAIRE - retrait - len(str(cle)) - 2)
        texte = yaml.safe_dump(valeur, allow_unicode=True, width=largeur)
        texte = texte.removesuffix("\n...\n").removesuffix("\n")
        return texte.replace("\n  ", "\n" + " " * (retrait + 2))
    return _yaml(valeur)


def _lignes_valeur(cle, valeur, retrait: int, creneaux: bool = False) -> list[str]:
    """Lignes d'une clé et de sa valeur, en bloc quand elle ne tient pas en ligne."""
    marge = " " * retrait
    if _est_scalaire(valeur):
        return [f"{marge}{_scalaire(cle)}: {_scalaire_bloc(valeur, cle, retrait)}"]
    if _en_ligne(valeur, creneaux):
        return [f"{marge}{_scalaire(cle)}: {_flux(valeur, cle)}"]
    lignes = [f"{marge}{_scalaire(cle)}:"]
    if isinstance(valeur, dict):
        for nom, element in valeur.items():
            lignes += _lignes_valeur(nom, element, retrait + 2, creneaux)
    else:
        for element in valeur:
            lignes += _lignes_element(element, retrait + 2)
    return lignes


def _lignes_element(element, retrait: int, creneaux: bool = False) -> list[str]:
    """Lignes d'un élément de liste (« - ... ») : une condition (colonne et valeurs ou
    motif) ou un dictionnaire qui ne tient pas en ligne s'écrit une clé par ligne."""
    marge = " " * retrait
    if isinstance(element, dict) and element and (
        not _en_ligne(element) or _est_condition(element)
    ):
        lignes = []
        for nom, valeur in element.items():
            lignes += _lignes_valeur(nom, valeur, retrait + 2, creneaux)
        return [f"{marge}- {lignes[0][retrait + 2:]}"] + lignes[1:]
    return [f"{marge}- {_flux(element)}"]


def _lignes_regle(instance: dict) -> list[str]:
    """Lignes d'une règle : une clé par ligne, ses valeurs en ligne quand elles le
    permettent (créneaux des horaires compris)."""
    type_regle = TYPES.get(instance.get("type"))
    genres = type_regle.parametres if type_regle is not None else {}
    lignes = []
    for nom, valeur in instance.items():
        lignes += _lignes_valeur(nom, valeur, 4, genres.get(nom) == GENRE_HORAIRES)
    return [f"  - {lignes[0][4:]}"] + lignes[1:]


def _lignes_regles(regles: list) -> list[str]:
    """Lignes d'une liste de règles, une ligne vide avant chaque changement de
    référence."""
    lignes, precedente = [], None
    for instance in regles:
        if precedente is not None and instance.get("ref") != precedente:
            lignes.append("")
        lignes += _lignes_regle(instance)
        precedente = instance.get("ref")
    return lignes


def _lignes_jours(jours: dict, retrait: int) -> list[str]:
    """Lignes de jours fériés (année vers liste), quelques dates par ligne."""
    lignes = []
    for annee, liste in jours.items():
        debut = f"{' ' * retrait}{_scalaire(annee)}: ["
        textes = [_scalaire(jour) for jour in liste]
        paquets = [textes[i:i + DATES_PAR_LIGNE] for i in range(0, len(textes),
                                                               DATES_PAR_LIGNE)] or [[]]
        for rang, paquet in enumerate(paquets):
            marge = debut if rang == 0 else " " * len(debut)
            fin = "]" if rang == len(paquets) - 1 else ","
            lignes.append(marge + ", ".join(paquet) + fin)
    return lignes


def texte_gestion(contenu: dict) -> str:
    """Texte de config/gestion.yaml pour un contenu.

    Un en-tête de commentaires standard, puis les jours fériés, les règles (une clé par
    ligne, une ligne vide quand la référence change), les règles retirées, les
    propositions écartées et les règles demandées. La relecture du texte redonne
    exactement le contenu.
    """
    blocs = [ENTETE_GESTION]
    jours_feries = contenu.get(CLE_JOURS_FERIES)
    if jours_feries:
        blocs.append(COMMENTAIRE_JOURS_FERIES + f"{CLE_JOURS_FERIES}:\n"
                     + "\n".join(_lignes_jours(jours_feries, 2)) + "\n")
    for cle, commentaire in ((CLE_REGLES_GESTION, ""), (CLE_RETIREES, COMMENTAIRE_RETIREES)):
        regles = contenu.get(cle)
        if regles:
            blocs.append(commentaire + f"{cle}:\n" + "\n".join(_lignes_regles(regles)) + "\n")
    ecartees = contenu.get(CLE_ECARTEES)
    if ecartees:
        lignes = [f"{CLE_ECARTEES}:"]
        for famille, valeur in ecartees.items():
            lignes.append(f"  {_scalaire(famille)}:")
            if famille == FAMILLE_FERIES:
                lignes += _lignes_jours(valeur, 4)
            else:
                lignes += [f"    - {_flux(element)}" for element in valeur]
        blocs.append(COMMENTAIRE_ECARTEES_GESTION + "\n".join(lignes) + "\n")
    demandes = contenu.get(CLE_DEMANDES)
    if demandes:
        lignes = [f"{CLE_DEMANDES}:"]
        for demande in demandes:
            sous = []
            for nom, valeur in demande.items():
                sous += _lignes_valeur(nom, valeur, 4)
            lignes += [f"  - {sous[0][4:]}"] + sous[1:]
        blocs.append(COMMENTAIRE_DEMANDES + "\n".join(lignes) + "\n")
    texte = "\n".join(blocs)
    attendu = {cle: valeur for cle, valeur in contenu.items() if valeur}
    if (yaml.safe_load(texte) or {}) != attendu:
        raise ValueError("relecture du fichier des règles de gestion écrit différente du contenu")
    return texte


def _problemes_fichier_gestion(contenu: dict) -> list[str]:
    """Problèmes d'un contenu de config/gestion.yaml : clés, puis contenu des clés."""
    problemes = [
        f"clé inconnue {cle!r} du fichier des règles de gestion"
        for cle in contenu
        if cle not in CLES_FICHIER_GESTION
    ]
    return problemes + problemes_contenu_formulaire(contenu)


class EcritureGestion(NamedTuple):
    """Résultat de `ecrire_gestion` : le fichier, sa copie datée (None s'il n'y avait
    pas de fichier ou si rien n'a changé), et s'il a été réécrit."""

    chemin: Path
    sauvegarde: Path | None
    ecrit: bool


def ecrire_gestion(
    contenu: dict,
    chemin: str | Path | None = None,
    *,
    empreinte: str,
    dossier: str | Path | None = None,
) -> EcritureGestion:
    """Réécrit config/gestion.yaml avec le contenu donné (`Formulaire.contenu`).

    `empreinte` est celle du fichier lue avant l'import du formulaire : si le fichier a
    changé depuis, rien n'est écrit. L'ancien fichier est d'abord copié dans `dossier`
    (par défaut data/config/sauvegardes, hors du dépôt), sous le nom
    `gestion_<AAAA-MM-JJ>_<HHMMSS>.yaml`; une copie déjà présente sous ce nom n'est
    jamais remplacée, et rien n'est alors écrit. Un contenu identique au fichier ne le
    réécrit pas. Le fichier est écrit en UTF-8 avec des fins de ligne LF.
    """
    chemin = Path(chemin) if chemin is not None else chemin_regles_gestion()
    actuelle = empreinte_gestion(chemin)
    if actuelle != empreinte:
        raise ValueError(
            f"{chemin} a changé depuis la lecture du formulaire (empreinte {empreinte}, "
            f"{actuelle} aujourd'hui) : écriture refusée, formulaire à réexporter"
        )
    problemes = _problemes_fichier_gestion(contenu)
    if problemes:
        raise ValueError(
            "Contenu du fichier des règles de gestion invalide\n  " + "\n  ".join(problemes)
        )
    texte = texte_gestion(contenu)
    if chemin.is_file() and chemin.read_bytes().replace(b"\r\n", b"\n") == texte.encode():
        return EcritureGestion(chemin, None, False)
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
    return EcritureGestion(chemin, sauvegarde, True)


def appliquer_formulaire_gestion(
    formulaire: Formulaire,
    chemin_formulaire: str | Path,
    contenu: dict,
    *,
    empreinte: str,
    chemin: str | Path | None = None,
    dossier: str | Path | None = None,
    dossier_archive: str | Path | None = None,
) -> ApplicationFormulaire:
    """Écrit les règles d'un formulaire importé, puis met le formulaire de côté.

    `contenu` et `empreinte` sont ceux de config/gestion.yaml lus avant l'import. Si
    le contenu du formulaire est celui du fichier (formulaire pas encore rempli), rien
    n'est fait : le formulaire reste en place. Sinon, le formulaire est d'abord archivé
    dans data/formulaires/appliques (un classeur ouvert dans Excel arrête tout, sans
    rien modifier), puis le fichier est réécrit après sa copie datée
    (`ecrire_gestion`); si l'écriture échoue, le formulaire est remis à sa place.
    """
    if formulaire.contenu == contenu:
        return ApplicationFormulaire(False, None, None)
    ecriture, archive = ecrire_et_archiver(
        chemin_formulaire,
        lambda: ecrire_gestion(formulaire.contenu, chemin, empreinte=empreinte, dossier=dossier),
        dossier_archive,
    )
    return ApplicationFormulaire(ecriture.ecrit, ecriture.sauvegarde, archive)
