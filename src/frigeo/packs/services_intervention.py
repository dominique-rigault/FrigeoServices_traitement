"""Vérification des calculs du pack services_intervention (étape 7.4).

Les calculs du pack (sql/packs/services_intervention/004_calculs.sql) sont refaits
ici en Python, à partir des valeurs écrites dans propre (la préparation de
l'écriture) et des rattachements des lignes à leurs référentiels, puis comparés à
dw ligne par ligne. Les paramètres de calcul (catégorie et article d'un chantier,
type de pièce d'une facture) sont lus dans dw.parametre_calcul : ce sont des
entrées du calcul, pas des résultats.

Chantiers (`chantiers_attendus`) : les interventions de la catégorie de chantier
reliées à des lignes de facture de l'article de chantier d'un même en-tête de type
facture forment un chantier si elles sont au moins deux; une intervention reliée à
plusieurs en-têtes suit le premier dans l'ordre du lignage de l'en-tête. Les jours
sont rangés par date de début, heure de début, puis lignage (vides d'abord). Chaque
intervention d'un chantier reçoit l'intervention du premier jour, son rang et le
nombre de jours; une autre intervention est son propre chantier, d'un jour.

Date du stock initial : la valeur de dw.parametre_calcul doit être celle de la règle
de stock de config/gestion.yaml (type solde_jamais_negatif, clé date_initial),
la même date étant déclarée aux deux endroits.

Aucune valeur du client n'est affichée : seulement des décomptes et des dates de
paramètres.
"""

from __future__ import annotations

from typing import Callable

import pandas as pd

from ..structure_base import SCHEMA_PROPRE

Lignage = tuple[str, "str | None", int]

TYPE_STOCK = "solde_jamais_negatif"

REQUETE_PARAMETRES = "SELECT cle, valeur FROM dw.parametre_calcul ORDER BY cle"
REQUETE_CHANTIERS = (
    "SELECT f.fichier_source, f.feuille_source, f.num_ligne_source, "
    "c.fichier_source, c.feuille_source, c.num_ligne_source, "
    "f.jour_chantier, f.nb_jours_chantier "
    "FROM dw.fait_intervention AS f "
    "JOIN dw.fait_intervention AS c ON c.id_fait_intervention = f.id_chantier"
)


# --- Lecture de la préparation et des rattachements ------------------------------


def _feuille(valeur) -> str | None:
    """Feuille du lignage, None pour un fichier sans feuille."""
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return None
    texte = str(valeur)
    return texte if texte.strip() else None


def lignage(fichier, feuille, numero) -> Lignage:
    return (str(fichier), _feuille(feuille), int(numero))


def table_propre(preparation, source: str) -> dict[Lignage, dict]:
    """Lignes écrites dans propre pour la table `source` du dictionnaire, par
    lignage, chaque ligne donnant ses valeurs par nom de colonne en base."""
    for preparee in preparation.tables:
        if preparee.schema == SCHEMA_PROPRE and preparee.table.source == source:
            colonnes = preparee.colonnes
            rangs = [colonnes.index(c) for c in ("fichier_source", "feuille_source",
                                                 "num_ligne_source")]
            return {
                lignage(*(ligne[r] for r in rangs)): dict(zip(colonnes, ligne))
                for ligne in preparee.lignes
            }
    raise KeyError(f"table {source} absente de la préparation")


def liens(rattachements, table: str, cle: str, reference: str) -> dict[Lignage, Lignage]:
    """Ligne du référentiel que cite chaque ligne de `table`, par le premier
    rattachement de même table, clé (colonnes reliées par « , ») et référentiel,
    comme dw.regle_rattachement. Vide si aucun rattachement ne correspond."""
    rang = next(
        (r for r, regle in enumerate(rattachements.regles, start=1)
         if regle.table == table and ", ".join(regle.cle) == cle
         and regle.table_reference == reference),
        None,
    )
    if rang is None:
        return {}
    lignes = rattachements.lignes
    lignes = lignes[lignes["regle"] == rang]
    return {
        lignage(l["fichier_source"], l["feuille_source"], l["num_ligne_source"]):
            lignage(l["fichier_reference"], l["feuille_reference"], l["num_ligne_reference"])
        for l in lignes.to_dict("records")
    }


def _ordre_lignage(cle: Lignage) -> tuple:
    """Ordre du lignage en classement binaire, une feuille vide d'abord."""
    fichier, feuille, numero = cle
    return (fichier, feuille is not None, feuille or "", numero)


def _vides_d_abord(valeur) -> tuple:
    return (valeur is not None, "" if valeur is None else str(valeur))


# --- Chantiers -------------------------------------------------------------------


def chantiers_attendus(
    lignes_facture: dict[Lignage, dict],
    entetes: dict[Lignage, dict],
    interventions: dict[Lignage, dict],
    lien_entete: dict[Lignage, Lignage],
    lien_intervention: dict[Lignage, Lignage],
    parametres: dict[str, str],
) -> dict[Lignage, tuple[Lignage, int, int]]:
    """Interventions des chantiers de plusieurs jours : pour chacune, par son lignage,
    (lignage de l'intervention du premier jour, rang du jour, nombre de jours).

    `lignes_facture`, `entetes` et `interventions` sont les lignes de propre
    (`table_propre`), `lien_entete` et `lien_intervention` les rattachements des lignes
    de facture (`liens`), `parametres` ceux de dw.parametre_calcul.
    """
    article = parametres["article_chantier"]
    type_facture = parametres["type_piece_facture"]
    categorie = parametres["categorie_chantier"]
    entetes_par_intervention: dict[Lignage, set[Lignage]] = {}
    for cle, ligne in lignes_facture.items():
        if ligne.get("code_article") != article:
            continue
        entete, intervention = lien_entete.get(cle), lien_intervention.get(cle)
        if entete is None or intervention is None:
            continue
        if entete not in entetes or intervention not in interventions:
            continue
        if entetes[entete].get("type_piece") != type_facture:
            continue
        if interventions[intervention].get("categorie") != categorie:
            continue
        entetes_par_intervention.setdefault(intervention, set()).add(entete)
    groupes: dict[Lignage, list[Lignage]] = {}
    for intervention, liste in entetes_par_intervention.items():
        premier = min(liste, key=_ordre_lignage)
        groupes.setdefault(premier, []).append(intervention)
    resultat = {}
    for membres in groupes.values():
        if len(membres) < 2:
            continue
        membres.sort(key=lambda c: (
            _vides_d_abord(interventions[c].get("date_debut")),
            _vides_d_abord(interventions[c].get("heure_debut")),
            _ordre_lignage(c),
        ))
        for rang, membre in enumerate(membres, start=1):
            resultat[membre] = (membres[0], rang, len(membres))
    return resultat


def comparer_chantiers(
    attendus: dict[Lignage, tuple[Lignage, int, int]],
    interventions: list[Lignage],
    obtenus: dict[Lignage, tuple[Lignage, int, int]],
) -> tuple[int, str, str]:
    """Écarts entre les chantiers recalculés et ceux de dw : nombre d'interventions
    dont le chantier, le rang ou le nombre de jours diffère (une intervention absente
    d'un côté comptant comme un écart), puis « chantiers de plusieurs jours /
    interventions concernées » attendus et obtenus."""
    attendu_complet = {c: attendus.get(c, (c, 1, 1)) for c in interventions}
    cles = set(attendu_complet) | set(obtenus)
    ecarts = sum(1 for c in cles if attendu_complet.get(c) != obtenus.get(c))

    def resume(chantiers: dict) -> str:
        multiples = [v for v in chantiers.values() if v[2] > 1]
        return f"{len({v[0] for v in multiples})} / {len(multiples)}"

    return ecarts, resume(attendu_complet), resume(obtenus)


# --- Date du stock initial -------------------------------------------------------


def dates_stock_initial(regles: list) -> list[str]:
    """Dates du stock initial (AAAA-MM-JJ) déclarées par les règles de stock de
    config/gestion.yaml, sans doublon et triées."""
    dates = set()
    for regle in regles:
        if regle.get("type") == TYPE_STOCK and regle.get("date_initial") is not None:
            valeur = regle["date_initial"]
            dates.add(valeur.isoformat() if hasattr(valeur, "isoformat") else str(valeur))
    return sorted(dates)


# --- Vérification ----------------------------------------------------------------


def verifier(curseur, ecriture, sorties, ajouter: Callable, regles: list | None = None) -> None:
    """Contrôles de la famille « calculs » (voir frigeo.packs). `regles` : les règles de
    gestion, lues par défaut dans config/gestion.yaml."""
    from ..gestion import charger_regles_gestion

    curseur.execute(REQUETE_PARAMETRES)
    parametres = {str(c): str(v) for c, v in curseur.fetchall()}

    regles = charger_regles_gestion() if regles is None else regles
    dates = dates_stock_initial(regles)
    ajouter("date du stock initial de dw.parametre_calcul égale à celle de la règle de stock "
            "de config/gestion.yaml", " / ".join(dates) or None,
            parametres.get("date_stock_initial"))

    libelle = ("dw.fait_intervention : interventions dont le chantier, le rang du jour ou le "
               "nombre de jours diffère du recalcul")
    libelle_resume = "dw.fait_intervention : chantiers de plusieurs jours / interventions concernées"
    probleme = None
    if ecriture.preparation is None:
        probleme = "préparation de l'écriture absente"
    elif sorties is None or sorties.rattachements is None:
        probleme = "rattachements absents"
    elif any(p not in parametres for p in
             ("article_chantier", "type_piece_facture", "categorie_chantier")):
        probleme = "paramètre de chantier absent de dw.parametre_calcul"
    if probleme is not None:
        ajouter(libelle, probleme, None)
        return
    preparation, rattachements = ecriture.preparation, sorties.rattachements
    interventions = table_propre(preparation, "interventions")
    attendus = chantiers_attendus(
        table_propre(preparation, "factures_lignes"),
        table_propre(preparation, "factures_entetes"),
        interventions,
        liens(rattachements, "factures_lignes", "num_facture", "factures_entetes"),
        liens(rattachements, "factures_lignes", "id_intervention", "interventions"),
        parametres,
    )
    curseur.execute(REQUETE_CHANTIERS)
    obtenus = {
        lignage(f, fe, n): (lignage(cf, cfe, cn), int(jour), int(nb))
        for f, fe, n, cf, cfe, cn, jour, nb in curseur.fetchall()
    }
    ecarts, resume_attendu, resume_obtenu = comparer_chantiers(
        attendus, list(interventions), obtenus
    )
    ajouter(libelle, 0, ecarts)
    ajouter(libelle_resume, resume_attendu, resume_obtenu)
