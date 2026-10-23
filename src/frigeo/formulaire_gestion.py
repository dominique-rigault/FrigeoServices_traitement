"""Formulaire des règles de gestion par le métier (phase 6.1 du mode opératoire).

Ce module ne contient rien de propre à un client. Les règles de gestion sont écrites
dans config/gestion.yaml. Plutôt que de faire écrire ce fichier à la main, le métier
les revoit dans un classeur Excel, sur le modèle du formulaire des règles de
contrôle (`frigeo.formulaire_controles`) :

- les familles de règles qui tiennent sur une ligne ont leur feuille, où les règles
  en vigueur (statut « documenté ») voisinent avec des propositions tirées des
  données (statut « observé »);
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

import datetime as dt
import hashlib
from datetime import date
from pathlib import Path

import pandas as pd
import yaml
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, Protection
from openpyxl.utils import get_column_letter

from .dictionnaire import STATUTS
from .formulaire_controles import texte_nombre
from .formulaires import dossier_formulaires
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
    COLONNE_PERIODE,
    ISSUES,
    TYPES,
    _annee_feries,
    _bornes_periode,
    _ecrire_condition,
    _jour_ferie,
    _prerequis_export,
    _problemes_feries,
    _texte_filtre,
    chemin_regles_gestion,
    completer_jours_feries,
    problemes_regles_gestion,
)
from .revue import _ecrire_texte, _feuille_listes, _menu, _menus_d_ajout
from .typage import NATURES_DATE, lire

FEUILLE_MODE_EMPLOI = "mode_emploi"
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
# Part minimale des lignes qui suivent une règle pour la proposer.
SEUIL_PROPOSITION = 0.95
LIGNES_AJOUT = 50
REPERE_EMPREINTE = "Empreinte de config/gestion.yaml à l'export (repère technique)"

# Familles de règles qui ont leur feuille : nom sous la clé `ecartees`, type du
# catalogue et référence donnée à une proposition.
FAMILLE_PERIODES = "periodes_export"
TYPE_PERIODES = "date_dans_periode_export"
REF_PERIODES = "decoupage"
FAMILLE_FERIES = CLE_JOURS_FERIES
FAMILLES_ECARTEES = (FAMILLE_PERIODES, FAMILLE_FERIES)
# Clés d'une règle demandée en texte libre, avec leur colonne dans le classeur.
COLONNES_DEMANDE = {
    "regle": "règle",
    "tables": "tables",
    "colonnes": "colonnes",
    "tolerance": "tolérance_ou_délai",
    "issue": "issue_souhaitée",
    "commentaire": "commentaire",
}

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
# Colonnes techniques, masquées : le rang de la règle dans config/gestion.yaml (sous
# la clé regles, ou sous la clé retirees pour une règle retirée), relu à l'import.
COLONNES_MASQUEES = ("rang",)
FORMAT_DATE = "DD/MM/YYYY"
LARGEURS = {
    "table": 22,
    "colonne": 22,
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
            elif famille == FAMILLE_PERIODES:
                if not isinstance(valeur, list) or not all(
                    isinstance(element, dict)
                    and set(element) == {"table", "colonne"}
                    and all(isinstance(v, str) and v for v in element.values())
                    for element in valeur
                ):
                    problemes.append(
                        f"{nom} : une liste de {{table, colonne}} (textes) est attendue"
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
    ("", "") sans filtre, None si le filtre a plusieurs conditions ou un motif."""
    filtre = instance.get(CLE_FILTRE)
    if not filtre:
        return "", ""
    if len(filtre) == 1 and "valeurs" in filtre[0]:
        return filtre[0]["colonne"], ", ".join(str(v) for v in filtre[0]["valeurs"])
    return None


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
    proposition = OUI if lues and dans / lues >= SEUIL_PROPOSITION else AUCUNE
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
    tombent dans la période de leur export), puis les règles retirées et les
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


def lignes_autres(contenu: dict, familles=(_en_periode,)) -> list[dict]:
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
        f"Feuille « {FEUILLE_PERIODES} » : {_a_traiter(periodes)} lignes à « observé » sur "
        f"{len(periodes)}. Feuille « {FEUILLE_FERIES} » : {_a_traiter(feries)} sur "
        f"{len(feries)}. Feuille « {FEUILLE_AUTRES} » : {len(autres)} règles. Feuille "
        f"« {FEUILLE_NOUVELLES} » : {len(nouvelles)} règles demandées.",
        "Une revue partielle est possible : une ligne laissée à « observé » est reprise "
        "telle quelle dans le formulaire suivant.",
        "",
        "Ce qui est attendu",
        "Pour chaque ligne, choisir un statut dans le menu déroulant et, si besoin, écrire "
        "un commentaire (il est conservé).",
        "observé : la ligne n'est pas revue; pas de règle.",
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
        "Les colonnes qui désignent la règle (table, colonne, filtre) ne se modifient pas : "
        "pour changer l'une d'elles, mettre invalide sur la ligne et ajouter une ligne en "
        "bas de la feuille.",
        "",
        f"Feuille « {FEUILLE_PERIODES} » : la date d'une ligne tombe dans la période de son "
        "export",
        "Une ligne par colonne de date d'un fichier exporté chaque mois ou chaque année. "
        "La règle est proposée quand au moins "
        f"{_pourcentage(SEUIL_PROPOSITION)} % des dates observées tombent dans la période "
        "de leur export. Pour ajouter une règle : sur une ligne vide en bas de la feuille, "
        "choisir la table et la colonne dans les menus, et le statut documenté. Le filtre, "
        "facultatif, limite la règle aux lignes dont filtre_colonne vaut l'une des "
        "filtre_valeurs (séparées par une virgule).",
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


def exporter_formulaire_gestion(
    tables: dict,
    dictionnaire: dict,
    contenu: dict,
    periode_fin: str,
    chemin: str | Path | None = None,
    *,
    empreinte: str,
    ecraser: bool = False,
) -> Path:
    """Écrit le formulaire des règles de gestion et rend son chemin.

    `contenu` est celui de config/gestion.yaml (`gestion.lire_fichier_gestion`) et
    `empreinte` son empreinte (`empreinte_gestion`) : elle est inscrite dans le
    formulaire, et l'import le refusera si le fichier a changé depuis. Un contenu
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
