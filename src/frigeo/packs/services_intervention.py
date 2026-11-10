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

CUMP et coût des pièces (`cump_attendus`, `couts_attendus`) : pour chaque pièce du
catalogue et chaque mois, du mois du stock initial à celui de la période de fin, les
achats (au mois de la date de leur facture, un avoir comptant en négatif) et les
consommations retenus, d'une pièce connue et avec leur quantité, donnent le stock
et le CUMP de fin de mois; chaque consommation est valorisée au CUMP de début de son
mois, ou reçoit le motif qui l'en empêche. Les arrondis sont ceux du pack : opérandes
à 6 décimales, CUMP à 4 décimales chaque mois, coût au centime, la moitié
s'éloignant de zéro.

Marge opérationnelle (`marges_attendues`) : pour chaque intervention, le CA de ses
lignes de facture retenues, les coûts salarial (coût horaire chargé de la
rémunération en vigueur, du type de contrat de la période d'emploi rattachée et des
paramètres de coûts de l'année, arrondi à 4 décimales), de déplacement et des pièces,
la marge et le motif de la première composante impossible, comme
dw.calculer_marges; une ligne de facture ou une consommation liée exclue des
indicateurs laisse vides le CA ou le coût des pièces, et la marge. Le coût salarial
total, qui dépend des salaires, est affiché « masqué ».

Aucune valeur du client n'est affichée : seulement des décomptes et des dates de
paramètres.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Callable

import pandas as pd

from ..structure_base import SCHEMA_PROPRE

Lignage = tuple[str, "str | None", int]

TYPE_STOCK = "solde_jamais_negatif"

REQUETE_PARAMETRES = "SELECT cle, valeur FROM dw.parametre_calcul ORDER BY cle"
REQUETE_PERIODE = "SELECT periode_fin FROM qualite.execution WHERE id_execution = ?"
REQUETE_CUMP = (
    "SELECT p.ref_piece, k.mois, k.stock_debut, k.cump_debut, k.quantite_achetee, "
    "k.valeur_achats, k.quantite_consommee, k.stock_fin, k.cump_fin "
    "FROM dw.cump_mensuel AS k JOIN dw.dim_piece AS p ON p.id_piece = k.id_piece"
)
REQUETE_COUTS = (
    "SELECT fichier_source, feuille_source, num_ligne_source, cump_applique, cout_ht, "
    "motif_calcul FROM dw.fait_consommation"
)

MOTIF_QUANTITE = "quantité vide"
MOTIF_PIECE_VIDE = "pièce non renseignée"
MOTIF_PIECE_INTROUVABLE = "pièce introuvable"
MOTIF_DATE_VIDE = "date vide"
MOTIF_HORS_MOIS = "date hors des mois du calcul"
MOTIF_CUMP = "CUMP inconnu"
MOTIFS = (MOTIF_QUANTITE, MOTIF_PIECE_VIDE, MOTIF_PIECE_INTROUVABLE, MOTIF_DATE_VIDE,
          MOTIF_HORS_MOIS, MOTIF_CUMP)

SIX = Decimal("0.000001")
QUATRE = Decimal("0.0001")
DEUX = Decimal("0.01")

REQUETE_TAUX = "SELECT type_contrat, colonne_taux FROM dw.parametre_taux_charges"
REQUETE_MARGES = (
    "SELECT fichier_source, feuille_source, num_ligne_source, ca_ht, cout_salarial, "
    "cout_deplacement, cout_pieces, marge, motif_calcul "
    "FROM dw.fait_intervention"
)

MOTIF_MARGE_DATE = "date vide"
MOTIF_MARGE_DUREE = "durée vide"
MOTIF_MARGE_INTERVENANT = "intervenant non rattaché"
MOTIF_MARGE_INTERVENANT_EXCLU = "intervenant non retenu"
MOTIF_MARGE_REMUNERATION_EXCLUE = "rémunération non retenue"
MOTIF_MARGE_REMUNERATION = "rémunération inconnue à la date"
MOTIF_MARGE_PARAMETRES_EXCLUS = "paramètres de coûts de l'année non retenus"
MOTIF_MARGE_PARAMETRES = "paramètres de coûts de l'année absents"
MOTIF_MARGE_TAUX = "taux de charges inconnu"
MOTIF_MARGE_HEURES = "heures annuelles ou taux d'activité vides ou nuls"
MOTIF_MARGE_DISTANCE = "distance ou coût kilométrique vide"
MOTIF_MARGE_PIECE = "coût d'une pièce inconnu"
MOTIF_MARGE_FACTURE_EXCLUE = "ligne de facture non retenue"
MOTIF_MARGE_CONSOMMATION_EXCLUE = "consommation non retenue"
MOTIFS_MARGE = (MOTIF_MARGE_DATE, MOTIF_MARGE_DUREE, MOTIF_MARGE_INTERVENANT,
                MOTIF_MARGE_INTERVENANT_EXCLU, MOTIF_MARGE_REMUNERATION_EXCLUE,
                MOTIF_MARGE_REMUNERATION, MOTIF_MARGE_PARAMETRES_EXCLUS,
                MOTIF_MARGE_PARAMETRES, MOTIF_MARGE_TAUX,
                MOTIF_MARGE_HEURES, MOTIF_MARGE_DISTANCE, MOTIF_MARGE_PIECE,
                MOTIF_MARGE_FACTURE_EXCLUE, MOTIF_MARGE_CONSOMMATION_EXCLUE)

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


# --- CUMP et coût des pièces ----------------------------------------------------


def _decimal(valeur) -> Decimal | None:
    return None if valeur is None else Decimal(str(valeur))


def _arrondi(nombre: Decimal, pas: Decimal) -> Decimal:
    """Arrondi au plus proche, la moitié s'éloignant de zéro (ROUND de T-SQL)."""
    return nombre.quantize(pas, rounding=ROUND_HALF_UP)


def _mois(date) -> str | None:
    """Premier jour du mois d'une date AAAA-MM-JJ."""
    return None if date is None else str(date)[:7] + "-01"


def mois_du_calcul(date_initiale: str, periode_fin: str) -> list[str]:
    """Mois du calcul, du mois de la date du stock initial à celui de `periode_fin`
    (AAAA-MM), en premiers jours de mois AAAA-MM-JJ."""
    annee, mois = int(date_initiale[:4]), int(date_initiale[5:7])
    fin = (int(periode_fin[:4]), int(periode_fin[5:7]))
    resultat = []
    while (annee, mois) <= fin:
        resultat.append(f"{annee:04d}-{mois:02d}-01")
        annee, mois = (annee + 1, 1) if mois == 12 else (annee, mois + 1)
    return resultat


def pieces_catalogue(catalogue: dict[Lignage, dict]) -> dict[str, tuple[Decimal, Decimal | None]]:
    """Stock et CUMP initiaux de chaque pièce, par code : ceux de la première ligne du
    catalogue de ce code dans l'ordre du lignage (comme dw.dim_piece); stock vide
    compté zéro, CUMP arrondi à 4 décimales."""
    pieces = {}
    for cle in sorted(catalogue, key=_ordre_lignage):
        ligne = catalogue[cle]
        code = ligne.get("ref_piece")
        if code is None or code in pieces:
            continue
        stock = _decimal(ligne.get("stock_initial")) or Decimal(0)
        cump = _decimal(ligne.get("cump_initial"))
        pieces[code] = (stock, None if cump is None else _arrondi(cump, QUATRE))
    return pieces


def _code_piece(cle: Lignage, ligne: dict, lien_piece: dict, catalogue: dict) -> tuple:
    """(code de la pièce, motif) d'une ligne qui cite une pièce par ref_piece."""
    if ligne.get("ref_piece") is None:
        return None, MOTIF_PIECE_VIDE
    reference = lien_piece.get(cle)
    if reference is None or reference not in catalogue:
        return None, MOTIF_PIECE_INTROUVABLE
    return catalogue[reference].get("ref_piece"), None


def achats_retenus(lignes: dict[Lignage, dict], entetes: dict[Lignage, dict],
                   lien_entete: dict, lien_piece: dict,
                   catalogue: dict[Lignage, dict]) -> list[tuple[str, str, Decimal, Decimal]]:
    """Achats qui comptent dans le CUMP : (code, mois, quantité, montant HT) de chaque
    ligne d'achat retenue (son en-tête trouvé retenu aussi), d'une pièce connue, avec
    quantité, montant et date de facture de l'en-tête."""
    resultat = []
    for cle, ligne in lignes.items():
        entete = entetes.get(lien_entete.get(cle)) if lien_entete.get(cle) else None
        if ligne.get("retenue") != 1 or (entete is not None and entete.get("retenue") != 1):
            continue
        code, motif = _code_piece(cle, ligne, lien_piece, catalogue)
        quantite, montant = _decimal(ligne.get("quantite")), _decimal(ligne.get("montant_ht"))
        if motif or quantite is None or montant is None or entete is None:
            continue
        mois = _mois(entete.get("date_facture"))
        if mois is not None:
            resultat.append((code, mois, quantite, montant))
    return resultat


def consommations(lignes: dict[Lignage, dict], lien_piece: dict,
                  catalogue: dict[Lignage, dict], mois: list[str]) -> dict[Lignage, tuple]:
    """Chaque consommation, par lignage : (code, mois, quantité, retenue, motif), le
    motif étant celui qui empêche de la valoriser avant le CUMP (quantité vide, pièce
    non renseignée ou introuvable, date vide ou hors des mois du calcul), None sinon."""
    resultat = {}
    for cle, ligne in lignes.items():
        quantite = _decimal(ligne.get("quantite"))
        code, motif_piece = _code_piece(cle, ligne, lien_piece, catalogue)
        date = ligne.get("date_sortie")
        mois_ligne = _mois(date)
        if quantite is None:
            motif = MOTIF_QUANTITE
        elif motif_piece:
            motif = motif_piece
        elif date is None:
            motif = MOTIF_DATE_VIDE
        elif mois_ligne not in mois:
            motif = MOTIF_HORS_MOIS
        else:
            motif = None
        resultat[cle] = (code, mois_ligne, quantite, ligne.get("retenue") == 1, motif)
    return resultat


def cump_fin_de_mois(stock_debut: Decimal, cump_debut: Decimal | None, quantite: Decimal,
                     valeur: Decimal) -> Decimal | None:
    """CUMP de fin de mois, comme dw.cump_fin_de_mois : stock négatif ou sans CUMP
    pesant zéro, CUMP de début gardé sans achat ou si le dénominateur n'est pas
    positif, opérandes à 6 décimales, résultat arrondi à 4 décimales."""
    stock = _arrondi(stock_debut, SIX) if stock_debut > 0 and cump_debut is not None else Decimal(0)
    achetee = _arrondi(quantite, SIX)
    if achetee == 0 or stock + achetee <= 0:
        return cump_debut
    with localcontext() as contexte:
        contexte.prec = 60
        numerateur = stock * (cump_debut or Decimal(0)) + _arrondi(valeur, SIX)
        return _arrondi(numerateur / (stock + achetee), QUATRE)


def cump_attendus(pieces: dict[str, tuple[Decimal, Decimal | None]],
                  achats: list[tuple], consommees: dict[Lignage, tuple],
                  mois: list[str]) -> dict[tuple[str, str], tuple]:
    """CUMP mensuel de chaque pièce, par (code, mois) : (stock de début, CUMP de début,
    quantité achetée, valeur des achats, quantité consommée, stock de fin, CUMP de
    fin), comme dw.cump_mensuel. Seules les consommations retenues, sans motif,
    comptent."""
    zero = Decimal(0)
    totaux: dict[tuple[str, str], list[Decimal]] = {}
    for code, mois_achat, quantite, montant in achats:
        if code in pieces and mois_achat in mois:
            total = totaux.setdefault((code, mois_achat), [zero, zero, zero])
            total[0] += quantite
            total[1] += montant
    for code, mois_sortie, quantite, retenue, motif in consommees.values():
        if retenue and motif is None and code in pieces:
            totaux.setdefault((code, mois_sortie), [zero, zero, zero])[2] += quantite
    resultat = {}
    for code, (stock, cump) in pieces.items():
        for mois_calcul in mois:
            achetee, valeur, consommee = totaux.get((code, mois_calcul), (zero, zero, zero))
            stock_fin = stock + achetee - consommee
            cump_fin = cump_fin_de_mois(stock, cump, achetee, valeur)
            resultat[(code, mois_calcul)] = (stock, cump, achetee, valeur, consommee,
                                             stock_fin, cump_fin)
            stock, cump = stock_fin, cump_fin
    return resultat


def couts_attendus(consommees: dict[Lignage, tuple],
                   cump: dict[tuple[str, str], tuple]) -> dict[Lignage, tuple]:
    """Chaque consommation, par lignage : (CUMP appliqué, coût HT, motif), au CUMP de
    début de son mois, le coût arrondi au centime; vides avec le motif sinon."""
    resultat = {}
    for cle, (code, mois_sortie, quantite, _, motif) in consommees.items():
        cump_debut = None if motif else cump[(code, mois_sortie)][1]
        if motif is None and cump_debut is None:
            motif = MOTIF_CUMP
        if motif:
            resultat[cle] = (None, None, motif)
        else:
            with localcontext() as contexte:
                contexte.prec = 60
                cout = _arrondi(_arrondi(quantite, SIX) * cump_debut, DEUX)
            resultat[cle] = (cump_debut, cout, None)
    return resultat


def _ecarts(attendus: dict, obtenus: dict) -> int:
    """Clés dont la valeur diffère, une clé absente d'un côté comptant comme un écart."""
    return sum(1 for c in set(attendus) | set(obtenus) if attendus.get(c) != obtenus.get(c))


def _motifs(couts: dict) -> str:
    """« motif n » pour chaque motif présent, dans l'ordre de `MOTIFS`, ou « aucun »."""
    comptes = {m: sum(1 for v in couts.values() if v[2] == m) for m in MOTIFS}
    return "; ".join(f"{m} {n}" for m, n in comptes.items() if n) or "aucun"


def _total(couts: dict) -> Decimal:
    return sum((v[1] for v in couts.values() if v[1] is not None), Decimal(0))


# --- Marge opérationnelle --------------------------------------------------------


def _premiere(lignes: list[tuple[Lignage, dict]]) -> dict | None:
    """Première ligne dans l'ordre du lignage, None s'il n'y en a pas."""
    return min(lignes, key=lambda l: _ordre_lignage(l[0]))[1] if lignes else None


def remuneration_en_vigueur(remunerations: dict[Lignage, dict], matricule: str,
                            date: str) -> dict | None:
    """Ligne de rémunération du matricule, retenue ou non, de date d'effet la plus
    récente qui ne dépasse pas `date`, la première dans l'ordre du lignage à égalité."""
    candidates = [
        (cle, l) for cle, l in remunerations.items()
        if l.get("matricule") == matricule
        and l.get("date_effet") is not None and str(l["date_effet"]) <= date
    ]
    if not candidates:
        return None
    plus_recente = max(str(l["date_effet"]) for _, l in candidates)
    return _premiere([(c, l) for c, l in candidates if str(l["date_effet"]) == plus_recente])


def parametres_annee(parametres_couts: dict[Lignage, dict], annee: int) -> dict | None:
    """Ligne des paramètres de coûts de l'année, retenue ou non, la première dans
    l'ordre du lignage s'il y en a plusieurs."""
    return _premiere([
        (cle, l) for cle, l in parametres_couts.items()
        if l.get("annee") is not None
        and _decimal(l["annee"]) == annee
    ])


def cout_horaire(salaire, taux_charges, heures, taux_activite) -> Decimal | None:
    """Coût horaire chargé, comme dw.calculer_marges : salaire × 12 × (1 + taux de
    charges) / (heures annuelles × taux d'activité), opérandes à 6 décimales, arrondi
    à 4 décimales; None si une entrée manque ou si les heures ou le taux d'activité
    ne sont pas positifs."""
    salaire, taux_charges = _decimal(salaire), _decimal(taux_charges)
    heures, taux_activite = _decimal(heures), _decimal(taux_activite)
    if salaire is None or taux_charges is None or heures is None or taux_activite is None:
        return None
    if heures <= 0 or taux_activite <= 0:
        return None
    with localcontext() as contexte:
        contexte.prec = 60
        annuel = _arrondi(_arrondi(salaire, SIX) * 12, SIX)
        charge = annuel * (1 + _arrondi(taux_charges, SIX))
        denominateur = _arrondi(_arrondi(heures, SIX) * _arrondi(taux_activite, SIX), SIX)
        return _arrondi(charge / denominateur, QUATRE)


def marges_attendues(
    interventions: dict[Lignage, dict],
    intervenants: dict[Lignage, dict],
    lien_intervenant: dict[Lignage, Lignage],
    remunerations: dict[Lignage, dict],
    parametres_couts: dict[Lignage, dict],
    taux_charges: dict[str, str],
    lignes_facture: list[tuple[Lignage, bool, Decimal | None]],
    consommees: list[tuple[Lignage, bool, Decimal | None]],
) -> dict[Lignage, tuple]:
    """Marge de chaque intervention, par lignage : (CA, coût salarial, coût de
    déplacement, coût des pièces, marge, motif).

    `taux_charges` : colonne du taux de charges de chaque type de contrat
    (dw.parametre_taux_charges); `lignes_facture` et `consommees` : pour chaque ligne
    liée à une intervention, (lignage de l'intervention, retenue du fait, montant HT
    ou coût).

    Une ligne de référence non retenue (période d'emploi rattachée, rémunération en
    vigueur, paramètres de l'année) ne sert à aucun calcul et n'est pas remplacée par
    une autre : le coût qui en dépend reste vide, avec son motif. Une ligne de
    facture ou une consommation liée non retenue laisse de même vides le CA ou le
    coût des pièces, et la marge.
    """
    zero = Decimal(0)
    ca: dict[Lignage, Decimal] = {}
    pieces: dict[Lignage, Decimal] = {}
    inconnus: set[Lignage] = set()
    factures_exclues: set[Lignage] = set()
    consommations_exclues: set[Lignage] = set()
    for intervention, retenue, montant in lignes_facture:
        if retenue:
            ca[intervention] = ca.get(intervention, zero) + (montant or zero)
        else:
            factures_exclues.add(intervention)
    for intervention, retenue, cout in consommees:
        if not retenue:
            consommations_exclues.add(intervention)
        elif cout is None:
            inconnus.add(intervention)
        else:
            pieces[intervention] = pieces.get(intervention, zero) + cout
    resultat = {}
    for cle, ligne in interventions.items():
        date = ligne.get("date_debut")
        duree = _decimal(ligne.get("duree_min"))
        trajet = _decimal(ligne.get("duree_trajet_min"))
        distance = _decimal(ligne.get("distance_km"))
        reference = lien_intervenant.get(cle)
        intervenant = intervenants.get(reference) if reference is not None else None
        matricule = intervenant.get("matricule") if intervenant else None
        remuneration = (remuneration_en_vigueur(remunerations, matricule, str(date))
                        if matricule is not None and date is not None else None)
        couts = parametres_annee(parametres_couts, int(str(date)[:4])) if date else None
        colonne = taux_charges.get(intervenant.get("type_contrat")) if intervenant else None
        taux = couts.get(colonne) if couts and colonne else None
        salaire = remuneration.get("salaire_brut_mensuel") if remuneration else None
        intervenant_exclu = intervenant is not None and intervenant.get("retenue") != 1
        remuneration_exclue = remuneration is not None and remuneration.get("retenue") != 1
        couts_exclus = couts is not None and couts.get("retenue") != 1
        horaire = None
        if not (intervenant_exclu or remuneration_exclue or couts_exclus):
            horaire = cout_horaire(
                salaire, taux, couts.get("heures_annuelles") if couts else None,
                remuneration.get("taux_activite") if remuneration else None,
            )
        cout_km = _decimal(couts.get("cout_km")) if couts and not couts_exclus else None
        with localcontext() as contexte:
            contexte.prec = 60
            salarial = (_arrondi((duree + trajet) * horaire / 60, DEUX)
                        if horaire is not None and duree is not None and trajet is not None
                        else None)
            deplacement = (_arrondi(_arrondi(distance, SIX) * _arrondi(cout_km, SIX), DEUX)
                           if distance is not None and cout_km is not None else None)
        cout_pieces = (None if cle in inconnus or cle in consommations_exclues
                       else pieces.get(cle, zero))
        chiffre = None if cle in factures_exclues else _arrondi(ca.get(cle, zero), DEUX)
        if date is None:
            motif = MOTIF_MARGE_DATE
        elif duree is None or trajet is None:
            motif = MOTIF_MARGE_DUREE
        elif matricule is None:
            motif = MOTIF_MARGE_INTERVENANT
        elif intervenant_exclu:
            motif = MOTIF_MARGE_INTERVENANT_EXCLU
        elif remuneration_exclue:
            motif = MOTIF_MARGE_REMUNERATION_EXCLUE
        elif salaire is None:
            motif = MOTIF_MARGE_REMUNERATION
        elif couts_exclus:
            motif = MOTIF_MARGE_PARAMETRES_EXCLUS
        elif couts is None:
            motif = MOTIF_MARGE_PARAMETRES
        elif taux is None:
            motif = MOTIF_MARGE_TAUX
        elif horaire is None:
            motif = MOTIF_MARGE_HEURES
        elif deplacement is None:
            motif = MOTIF_MARGE_DISTANCE
        elif cle in inconnus:
            motif = MOTIF_MARGE_PIECE
        elif cle in factures_exclues:
            motif = MOTIF_MARGE_FACTURE_EXCLUE
        elif cle in consommations_exclues:
            motif = MOTIF_MARGE_CONSOMMATION_EXCLUE
        else:
            motif = None
        marge = (chiffre - salarial - deplacement - cout_pieces
                 if None not in (chiffre, salarial, deplacement, cout_pieces) else None)
        resultat[cle] = (chiffre, salarial, deplacement, cout_pieces, marge, motif)
    return resultat


def lignes_facture_liees(lignes: dict[Lignage, dict], entetes: dict[Lignage, dict],
                         lien_entete: dict, lien_intervention: dict) -> list[tuple]:
    """Lignes de facture liées à une intervention : (lignage de l'intervention, retenue
    du fait, montant HT), la ligne n'étant retenue que si son en-tête trouvé l'est."""
    resultat = []
    for cle, ligne in lignes.items():
        intervention = lien_intervention.get(cle)
        if intervention is None:
            continue
        reference = lien_entete.get(cle)
        entete = entetes.get(reference) if reference is not None else None
        retenue = ligne.get("retenue") == 1 and (entete is None or entete.get("retenue") == 1)
        resultat.append((intervention, retenue, _decimal(ligne.get("montant_ht"))))
    return resultat


def _motifs_marge(marges: dict) -> str:
    """« motif n » pour chaque motif présent, dans l'ordre de `MOTIFS_MARGE`, ou « aucun »."""
    comptes = {m: sum(1 for v in marges.values() if v[5] == m) for m in MOTIFS_MARGE}
    return "; ".join(f"{m} {n}" for m, n in comptes.items() if n) or "aucun"


def _somme(marges: dict, rang: int) -> Decimal:
    return sum((v[rang] for v in marges.values() if v[rang] is not None), Decimal(0))


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
    _verifier_cump(curseur, ecriture, rattachements, parametres, ajouter)


def _verifier_cump(curseur, ecriture, rattachements, parametres: dict, ajouter) -> None:
    """Contrôles du CUMP mensuel et du coût des pièces (voir l'en-tête du module)."""
    libelle_cump = ("dw.cump_mensuel : pièces et mois dont le stock, les mouvements ou le "
                    "CUMP diffèrent du recalcul")
    curseur.execute(REQUETE_PERIODE, ecriture.id_execution)
    periode = curseur.fetchall()
    date_initiale = parametres.get("date_stock_initial")
    if not periode or date_initiale is None:
        ajouter(libelle_cump, "période de fin ou date du stock initial absente", None)
        return
    mois = mois_du_calcul(date_initiale, str(periode[0][0]))
    preparation = ecriture.preparation
    catalogue = table_propre(preparation, "catalogue_pieces")
    pieces = pieces_catalogue(catalogue)
    achats = achats_retenus(
        table_propre(preparation, "achats_lignes"),
        table_propre(preparation, "achats_entetes"),
        liens(rattachements, "achats_lignes", "num_piece_achat", "achats_entetes"),
        liens(rattachements, "achats_lignes", "ref_piece", "catalogue_pieces"),
        catalogue,
    )
    consommees = consommations(
        table_propre(preparation, "pieces_interventions"),
        liens(rattachements, "pieces_interventions", "ref_piece", "catalogue_pieces"),
        catalogue, mois,
    )
    cump = cump_attendus(pieces, achats, consommees, mois)
    couts = couts_attendus(consommees, cump)

    curseur.execute(REQUETE_CUMP)
    cump_obtenu = {
        (str(code), mois_lu.isoformat() if hasattr(mois_lu, "isoformat") else str(mois_lu)):
            tuple(_decimal(v) for v in valeurs)
        for code, mois_lu, *valeurs in curseur.fetchall()
    }
    curseur.execute(REQUETE_COUTS)
    couts_obtenus = {
        lignage(f, fe, n): (_decimal(c), _decimal(t), m)
        for f, fe, n, c, t, m in curseur.fetchall()
    }
    ajouter("dw.cump_mensuel : lignes (pièces × mois)", len(cump), len(cump_obtenu))
    ajouter(libelle_cump, 0, _ecarts(cump, cump_obtenu))
    ajouter("dw.fait_consommation : consommations dont le CUMP appliqué, le coût ou le "
            "motif diffère du recalcul", 0, _ecarts(couts, couts_obtenus))
    ajouter("dw.fait_consommation : consommations sans coût, par motif",
            _motifs(couts), _motifs(couts_obtenus))
    ajouter("dw.fait_consommation : coût total des pièces", _total(couts),
            _total(couts_obtenus))
    _verifier_marges(curseur, ecriture, rattachements, consommees, couts, ajouter)


def _verifier_marges(curseur, ecriture, rattachements, consommees: dict, couts: dict,
                     ajouter) -> None:
    """Contrôles de la marge opérationnelle de chaque intervention."""
    preparation = ecriture.preparation
    curseur.execute(REQUETE_TAUX)
    taux = {str(t): str(c) for t, c in curseur.fetchall()}
    lien_conso = liens(rattachements, "pieces_interventions", "id_intervention",
                       "interventions")
    consommations_liees = [
        (lien_conso[cle], retenue, couts[cle][1])
        for cle, (_, _, _, retenue, _) in consommees.items() if cle in lien_conso
    ]
    marges = marges_attendues(
        table_propre(preparation, "interventions"),
        table_propre(preparation, "intervenants"),
        liens(rattachements, "interventions", "intervenant", "intervenants"),
        table_propre(preparation, "remunerations"),
        table_propre(preparation, "parametres_couts"),
        taux,
        lignes_facture_liees(
            table_propre(preparation, "factures_lignes"),
            table_propre(preparation, "factures_entetes"),
            liens(rattachements, "factures_lignes", "num_facture", "factures_entetes"),
            liens(rattachements, "factures_lignes", "id_intervention", "interventions"),
        ),
        consommations_liees,
    )
    curseur.execute(REQUETE_MARGES)
    obtenues = {
        lignage(f, fe, n): (*(_decimal(v) for v in montants), motif)
        for f, fe, n, *montants, motif in curseur.fetchall()
    }
    ajouter("dw.fait_intervention : interventions dont le CA, un coût, la marge ou le motif "
            "diffère du recalcul", 0, _ecarts(marges, obtenues))
    ajouter("dw.fait_intervention : interventions sans marge, par motif",
            _motifs_marge(marges), _motifs_marge(obtenues))
    ajouter("dw.fait_intervention : interventions avec une marge",
            sum(1 for v in marges.values() if v[4] is not None),
            sum(1 for v in obtenues.values() if v[4] is not None))
    ajouter("dw.fait_intervention : CA total", _somme(marges, 0), _somme(obtenues, 0))
    ajouter("dw.fait_intervention : coût salarial total", _somme(marges, 1),
            _somme(obtenues, 1), True)
    ajouter("dw.fait_intervention : coût de déplacement total", _somme(marges, 2),
            _somme(obtenues, 2))
    ajouter("dw.fait_intervention : coût des pièces total", _somme(marges, 3),
            _somme(obtenues, 3))
    ajouter("dw.fait_intervention : marge totale", _somme(marges, 4), _somme(obtenues, 4))
