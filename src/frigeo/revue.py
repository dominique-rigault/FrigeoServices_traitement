"""Classeur Excel de revue du dictionnaire par le métier (étape 2d).

Le dictionnaire généré n'est ni ouvert dans Excel ni modifié à la main : il est
exporté dans un classeur où le métier choisit un statut par règle et par valeur.
Ce module ne contient rien de propre à un client.
"""

from __future__ import annotations

import unicodedata
from datetime import date
from pathlib import Path
from typing import NamedTuple

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, Protection
from openpyxl.worksheet.datavalidation import DataValidation

from . import racine_projet
from .dictionnaire import STATUTS, _valeurs_renseignees
from .profilage import _NATURES_TEXTE

FEUILLE_MODE_EMPLOI = "mode_emploi"
FEUILLE_REGLES = "regles"
FEUILLE_VALEURS = "valeurs"

COLONNES_REGLES = (
    "table",
    "colonne",
    "regle",
    "proposition",
    "motif",
    "nb_a_arbitrer",
    "statut",
    "regle_retenue",
    "commentaire",
)
COLONNES_VALEURS = (
    "table",
    "colonne",
    "valeur",
    "effectif",
    "origine",
    "remarque",
    "statut",
    "commentaire",
)
# Colonnes que le métier peut modifier; les autres cellules sont verrouillées.
MODIFIABLES_REGLES = ("statut", "regle_retenue", "commentaire")
MODIFIABLES_VALEURS = ("statut", "commentaire")
# Colonnes à saisir sur une ligne ajoutée en bas de la feuille des valeurs.
SAISIE_AJOUT = ("table", "colonne", "valeur", "statut", "commentaire")

ORIGINE_LISTE = "liste proposée"
ORIGINE_A_ARBITRER = "à arbitrer"
ORIGINE_AJOUT = "ajoutée"

# Règles que le métier peut donner lui-même, avec le statut « documenté ».
REGLES_RETENUES = {
    "obligatoire": ("obligatoire", "facultatif", "toujours vide"),
    "nature": ("texte", "nombre natif", "date native", *_NATURES_TEXTE),
}
LIGNES_AJOUT = 200
LARGEURS = {
    "table": 22,
    "colonne": 26,
    "regle": 12,
    "proposition": 26,
    "motif": 55,
    "nb_a_arbitrer": 14,
    "statut": 13,
    "regle_retenue": 24,
    "commentaire": 50,
    "valeur": 34,
    "effectif": 10,
    "origine": 16,
    "remarque": 24,
}


def chemin_revue(periode_fin: str) -> Path:
    """Emplacement par défaut du classeur : data/revue/, hors du dépôt."""
    return racine_projet() / "data" / "revue" / f"dictionnaire_revue_{periode_fin}.xlsx"


def lignes_regles(dictionnaire: dict) -> list[dict]:
    """Lignes de la feuille des règles, dans l'ordre du dictionnaire.

    Deux lignes par colonne (`obligatoire`, `nature`), plus une ligne `valeurs`
    quand une liste fermée est proposée : elle porte la question « cette colonne
    est-elle bien une liste fermée ? ».
    """
    lignes = []
    for table, colonnes in dictionnaire.items():
        for colonne, regles in colonnes.items():
            for nom in ("obligatoire", "nature"):
                regle = regles[nom]
                ecarts = sum(
                    valeur
                    for valeur in regle["a_arbitrer"].values()
                    if isinstance(valeur, int) and not isinstance(valeur, bool)
                )
                lignes.append(
                    {
                        "table": table,
                        "colonne": colonne,
                        "regle": nom,
                        "proposition": regle["regle"],
                        "motif": regle["motif"],
                        "nb_a_arbitrer": ecarts,
                        "statut": regle["statut"],
                    }
                )
            valeurs = regles["valeurs"]
            if isinstance(valeurs["regle"], list):
                lignes.append(
                    {
                        "table": table,
                        "colonne": colonne,
                        "regle": "valeurs",
                        "proposition": f"liste de {len(valeurs['regle'])} valeurs",
                        "motif": valeurs["motif"],
                        "nb_a_arbitrer": len(valeurs["a_arbitrer"]),
                        "statut": valeurs["statut"],
                    }
                )
    return lignes


def _remarque(valeur: str) -> str:
    """Signale ce qui ne se voit pas à l'écran dans une valeur."""
    remarques = []
    if valeur != valeur.strip(" \t"):
        remarques.append("espaces en bord")
    if " " in valeur or " " in valeur:
        remarques.append("espace insécable")
    return ", ".join(remarques)


def lignes_valeurs(
    dictionnaire: dict, tables: dict[str, pd.DataFrame] | None = None
) -> list[dict]:
    """Lignes de la feuille des valeurs : une ligne par valeur des listes proposées.

    Les valeurs à arbitrer portent l'effectif enregistré dans le dictionnaire. Pour
    celles de la liste proposée, l'effectif est compté dans `tables` si elles sont
    fournies, et laissé vide sinon. Une colonne sans liste (dont toute colonne
    sensible) ne donne aucune ligne.
    """
    lignes = []
    for table, colonnes in dictionnaire.items():
        for colonne, regles in colonnes.items():
            valeurs = regles["valeurs"]
            if not isinstance(valeurs["regle"], list):
                continue
            effectifs = {}
            if tables is not None and table in tables and colonne in tables[table]:
                presentes = _valeurs_renseignees(tables[table][colonne])
                effectifs = presentes.astype(str).value_counts().to_dict()
            for valeur in valeurs["regle"]:
                effectif = effectifs.get(valeur)
                lignes.append(
                    {
                        "table": table,
                        "colonne": colonne,
                        "valeur": valeur,
                        "effectif": None if effectif is None else int(effectif),
                        "origine": ORIGINE_LISTE,
                        "remarque": _remarque(valeur),
                        "statut": valeurs["statut"],
                    }
                )
            for element in valeurs["a_arbitrer"]:
                lignes.append(
                    {
                        "table": table,
                        "colonne": colonne,
                        "valeur": element["valeur"],
                        "effectif": element["effectif"],
                        "origine": ORIGINE_A_ARBITRER,
                        "remarque": _remarque(element["valeur"]),
                        "statut": valeurs["statut"],
                    }
                )
    return lignes


def _mode_emploi(periode_fin: str, nb_regles: int, nb_valeurs: int) -> list[str]:
    return [
        "Revue du dictionnaire des données",
        f"Période de fin : {periode_fin}. Classeur généré le {date.today():%d/%m/%Y}.",
        f"À revoir : {nb_regles} lignes dans la feuille « {FEUILLE_REGLES} », "
        f"{nb_valeurs} lignes dans la feuille « {FEUILLE_VALEURS} ».",
        "",
        "Ce qui est attendu",
        "Pour chaque ligne, choisir un statut dans le menu déroulant et, si besoin, "
        "écrire un commentaire. Une ligne laissée à « observé » n'est pas revue : "
        "elle pourra l'être plus tard.",
        "",
        f"Feuille « {FEUILLE_REGLES} » : les règles proposées pour chaque colonne",
        "valide : la proposition est la règle. Impossible si la proposition est "
        "« à décider ».",
        "invalide : la proposition est écartée et rien ne la remplace. Dire pourquoi "
        "en commentaire.",
        "documenté : vous donnez vous-même la règle, dans la colonne regle_retenue "
        "(à remplir avec ce statut, à laisser vide avec les autres).",
        "Sur une ligne « valeurs », la question est : cette colonne n'accepte-t-elle "
        "qu'une liste fermée de valeurs ? Le statut invalide écarte toute la liste, "
        f"sans avoir à revoir ses valeurs dans la feuille « {FEUILLE_VALEURS} ».",
        "",
        f"Feuille « {FEUILLE_VALEURS} » : les valeurs des listes proposées",
        "valide : la valeur est légitime.",
        "invalide : la valeur est une erreur, elle sera signalée en anomalie.",
        "La colonne remarque signale ce qui ne se voit pas à l'écran (espaces en "
        "bord, espace insécable).",
        "Pour ajouter une valeur légitime absente de la liste : remplir table, "
        "colonne et valeur sur une ligne vide en bas de la feuille, avec le statut "
        "documenté.",
        "",
        "Règles à respecter pour que le classeur puisse être réimporté",
        "Ne modifier que les colonnes statut, regle_retenue et commentaire (les "
        "autres cellules sont verrouillées).",
        "Ne pas renommer, déplacer ni supprimer de feuilles, de colonnes ou de lignes.",
        "Ne pas ajouter de lignes, sauf en bas de la feuille des valeurs comme "
        "indiqué ci-dessus.",
        "Choisir les statuts dans le menu déroulant, sans les saisir autrement.",
        "Enregistrer au format .xlsx, sans changer le nom du fichier.",
        "Le filtre de la ligne d'en-tête peut être utilisé librement.",
    ]


def _ecrire_texte(cellule, valeur) -> None:
    """Écrit une valeur comme texte, pour qu'Excel ne la transforme pas.

    Sans cela, « 076 » deviendrait 76, « 2026-03-01 » une date et « =1+1 » une formule.
    """
    cellule.value = valeur
    cellule.number_format = "@"
    if isinstance(valeur, str):
        cellule.data_type = "s"


def _menu(feuille, choix) -> DataValidation:
    menu = DataValidation(
        type="list", formula1='"' + ",".join(choix) + '"', allow_blank=True
    )
    menu.error = "Choisir une valeur dans le menu déroulant."
    menu.errorTitle = "Valeur non prévue"
    feuille.add_data_validation(menu)
    return menu


def _remplir(feuille, colonnes, lignes, modifiables, lignes_ajout=0) -> None:
    """Écrit l'en-tête et les lignes, puis protège la feuille hors colonnes modifiables."""
    for indice, nom in enumerate(colonnes, start=1):
        cellule = feuille.cell(row=1, column=indice, value=nom)
        cellule.font = Font(bold=True)
        feuille.column_dimensions[cellule.column_letter].width = LARGEURS[nom]
    for numero, ligne in enumerate(lignes, start=2):
        for indice, nom in enumerate(colonnes, start=1):
            cellule = feuille.cell(row=numero, column=indice)
            valeur = ligne.get(nom)
            if isinstance(valeur, int):
                cellule.value = valeur
            else:
                _ecrire_texte(cellule, valeur)
            if nom in modifiables:
                cellule.protection = Protection(locked=False)
    fin = len(lignes) + 1
    for numero in range(fin + 1, fin + lignes_ajout + 1):
        for indice, nom in enumerate(colonnes, start=1):
            if nom in SAISIE_AJOUT:
                cellule = feuille.cell(row=numero, column=indice)
                cellule.number_format = "@"
                cellule.protection = Protection(locked=False)
    derniere = feuille.cell(row=1, column=len(colonnes)).column_letter
    feuille.freeze_panes = "A2"
    feuille.auto_filter.ref = f"A1:{derniere}{max(fin + lignes_ajout, 2)}"
    feuille.protection.sheet = True
    feuille.protection.autoFilter = False
    feuille.protection.formatColumns = False


def exporter_revue(
    dictionnaire: dict,
    periode_fin: str,
    chemin: str | Path | None = None,
    *,
    tables: dict[str, pd.DataFrame] | None = None,
    ecraser: bool = False,
) -> Path:
    """Écrit le classeur de revue du dictionnaire et rend son chemin.

    Sans `ecraser=True`, refuse de remplacer un classeur existant : une revue y est
    peut-être en cours. `tables` (les tables chargées) sert seulement à compter
    l'effectif des valeurs des listes proposées.
    """
    chemin = Path(chemin) if chemin is not None else chemin_revue(periode_fin)
    if chemin.exists() and not ecraser:
        raise FileExistsError(
            f"{chemin} existe déjà : export refusé (ecraser=True pour forcer)"
        )
    regles = lignes_regles(dictionnaire)
    valeurs = lignes_valeurs(dictionnaire, tables)

    classeur = Workbook()
    notice = classeur.active
    notice.title = FEUILLE_MODE_EMPLOI
    notice.column_dimensions["A"].width = 120
    for numero, texte in enumerate(
        _mode_emploi(periode_fin, len(regles), len(valeurs)), start=1
    ):
        cellule = notice.cell(row=numero, column=1)
        _ecrire_texte(cellule, texte)
        cellule.alignment = Alignment(wrap_text=True, vertical="top")
        if numero == 1 or texte.startswith(("Ce qui", "Feuille", "Règles à")):
            cellule.font = Font(bold=True)
    notice.protection.sheet = True

    feuille = classeur.create_sheet(FEUILLE_REGLES)
    _remplir(feuille, COLONNES_REGLES, regles, MODIFIABLES_REGLES)
    statut = COLONNES_REGLES.index("statut") + 1
    retenue = COLONNES_REGLES.index("regle_retenue") + 1
    menu_statut = _menu(feuille, STATUTS)
    menus_retenue = {nom: _menu(feuille, choix) for nom, choix in REGLES_RETENUES.items()}
    for numero, ligne in enumerate(regles, start=2):
        menu_statut.add(feuille.cell(row=numero, column=statut))
        cellule = feuille.cell(row=numero, column=retenue)
        if ligne["regle"] in menus_retenue:
            menus_retenue[ligne["regle"]].add(cellule)
        else:
            # Une liste de valeurs se revoit dans la feuille des valeurs.
            cellule.protection = Protection(locked=True)

    feuille = classeur.create_sheet(FEUILLE_VALEURS)
    _remplir(feuille, COLONNES_VALEURS, valeurs, MODIFIABLES_VALEURS, LIGNES_AJOUT)
    statut = COLONNES_VALEURS.index("statut") + 1
    menu_statut = _menu(feuille, STATUTS)
    for numero in range(2, len(valeurs) + LIGNES_AJOUT + 2):
        menu_statut.add(feuille.cell(row=numero, column=statut))

    chemin.parent.mkdir(parents=True, exist_ok=True)
    classeur.save(chemin)
    return chemin


# Statuts admis sur une valeur observée : « documenté » est réservé aux ajouts.
STATUTS_VALEUR_EXPORTEE = ("observé", "valide", "invalide")
A_DECIDER = "à décider"


class Revue(NamedTuple):
    """Décisions lues dans un classeur de revue, contrôlées mais pas encore fusionnées."""

    regles: pd.DataFrame
    valeurs: pd.DataFrame
    avertissements: list[str]


def _choix(valeur) -> str:
    """Texte d'un statut ou d'une règle retenue, normalisé (NFC, espaces en bord ôtés)."""
    if valeur is None:
        return ""
    return unicodedata.normalize("NFC", str(valeur)).strip()


def _commentaire(valeur) -> str:
    return "" if valeur is None else str(valeur).strip()


def _est_vide(valeur) -> bool:
    return valeur is None or (isinstance(valeur, str) and valeur.strip() == "")


def _lire_feuille(classeur, nom: str, colonnes: tuple[str, ...]) -> list[tuple[int, dict]]:
    """Lignes non vides d'une feuille, avec leur numéro de ligne Excel.

    Lève une ValueError si la feuille manque ou si son en-tête n'est pas celui exporté.
    """
    if nom not in classeur.sheetnames:
        raise ValueError(f"feuille « {nom} » absente")
    lignes = classeur[nom].iter_rows(values_only=True)
    entete = tuple(next(lignes, ()))
    while entete and entete[-1] is None:
        entete = entete[:-1]
    if entete != colonnes:
        raise ValueError(
            f"feuille « {nom} » : en-tête modifié, attendu {', '.join(colonnes)}"
        )
    resultat = []
    for numero, valeurs in enumerate(lignes, start=2):
        valeurs = tuple(valeurs[: len(colonnes)]) + (None,) * (len(colonnes) - len(valeurs))
        if all(_est_vide(valeur) for valeur in valeurs):
            continue
        resultat.append((numero, dict(zip(colonnes, valeurs))))
    return resultat


def _controler_regles(lignes, dictionnaire) -> tuple[list[dict], list[str]]:
    attendues = {
        (l["table"], l["colonne"], l["regle"]): l["proposition"]
        for l in lignes_regles(dictionnaire)
    }
    decisions, problemes, vues = [], [], set()
    for numero, ligne in lignes:
        ou = f"{FEUILLE_REGLES}, ligne {numero}"
        cle = (ligne["table"], ligne["colonne"], ligne["regle"])
        if cle not in attendues:
            problemes.append(f"{ou} : règle inconnue {cle} (classeur périmé ou ligne ajoutée)")
            continue
        if cle in vues:
            problemes.append(f"{ou} : règle {cle} présente plusieurs fois")
            continue
        vues.add(cle)
        proposition = attendues[cle]
        if ligne["proposition"] != proposition:
            problemes.append(
                f"{ou} : proposition {ligne['proposition']!r} différente du dictionnaire "
                f"({proposition!r}), classeur périmé, à réexporter"
            )
        statut = _choix(ligne["statut"])
        retenue = _choix(ligne["regle_retenue"])
        commentaire = _commentaire(ligne["commentaire"])
        regle = ligne["regle"]
        if statut == "":
            problemes.append(f"{ou} : statut vide (laisser « observé » si la règle n'est pas revue)")
        elif statut not in STATUTS:
            problemes.append(f"{ou} : statut inconnu {statut!r}")
        elif statut == "valide" and proposition == A_DECIDER:
            problemes.append(
                f"{ou} : une proposition « {A_DECIDER} » ne peut pas être validée "
                "(choisir documenté et une règle retenue)"
            )
        elif statut == "invalide" and commentaire == "":
            problemes.append(f"{ou} : commentaire obligatoire avec le statut invalide")
        if regle not in REGLES_RETENUES:
            if statut == "documenté":
                problemes.append(
                    f"{ou} : statut documenté impossible sur une liste, ajouter les "
                    f"valeurs dans la feuille « {FEUILLE_VALEURS} »"
                )
            if retenue:
                problemes.append(f"{ou} : regle_retenue interdite sur une liste")
        elif statut == "documenté" and retenue == "":
            problemes.append(f"{ou} : regle_retenue obligatoire avec le statut documenté")
        elif statut == "documenté" and retenue not in REGLES_RETENUES[regle]:
            problemes.append(f"{ou} : regle_retenue {retenue!r} hors du menu de la règle {regle}")
        elif statut != "documenté" and retenue:
            problemes.append(f"{ou} : regle_retenue réservée au statut documenté")
        decisions.append(
            {
                "table": cle[0],
                "colonne": cle[1],
                "regle": regle,
                "statut": statut,
                "regle_retenue": retenue or None,
                "commentaire": commentaire,
                "ligne_excel": numero,
            }
        )
    for cle in attendues.keys() - vues:
        problemes.append(f"{FEUILLE_REGLES} : règle {cle} absente du classeur")
    return decisions, problemes


def _controler_valeurs(lignes, dictionnaire) -> tuple[list[dict], list[str]]:
    exportees = {
        (l["table"], l["colonne"], l["valeur"]): l["origine"]
        for l in lignes_valeurs(dictionnaire)
    }
    colonnes = {(table, colonne) for table, cols in dictionnaire.items() for colonne in cols}
    decisions, problemes, vues = [], [], set()
    for numero, ligne in lignes:
        ou = f"{FEUILLE_VALEURS}, ligne {numero}"
        table, colonne, valeur = ligne["table"], ligne["colonne"], ligne["valeur"]
        statut = _choix(ligne["statut"])
        ajout = _est_vide(ligne["origine"])
        cle = (table, colonne, valeur)
        if ajout:
            origine = ORIGINE_AJOUT
            if (table, colonne) not in colonnes:
                problemes.append(f"{ou} : colonne {table}.{colonne} absente du dictionnaire")
            if _est_vide(valeur):
                problemes.append(f"{ou} : valeur vide")
            elif not isinstance(valeur, str):
                problemes.append(
                    f"{ou} : valeur {valeur!r} lue comme {type(valeur).__name__}, "
                    "la saisir comme texte"
                )
            elif cle in exportees or cle in vues:
                problemes.append(f"{ou} : valeur {valeur!r} déjà présente pour {table}.{colonne}")
            if statut != "documenté":
                problemes.append(f"{ou} : une valeur ajoutée doit porter le statut documenté")
        else:
            origine = ligne["origine"]
            if cle not in exportees or exportees[cle] != origine:
                problemes.append(
                    f"{ou} : valeur {valeur!r} de {table}.{colonne} inconnue du "
                    "dictionnaire (classeur périmé ou ligne modifiée)"
                )
                continue
            if cle in vues:
                problemes.append(f"{ou} : valeur {valeur!r} présente plusieurs fois")
                continue
            if statut not in STATUTS_VALEUR_EXPORTEE:
                problemes.append(
                    f"{ou} : statut {statut!r} impossible sur une valeur observée "
                    f"(choisir parmi {', '.join(STATUTS_VALEUR_EXPORTEE)})"
                )
        vues.add(cle)
        decisions.append(
            {
                "table": table,
                "colonne": colonne,
                "valeur": valeur,
                "origine": origine,
                "statut": statut,
                "commentaire": _commentaire(ligne["commentaire"]),
                "ligne_excel": numero,
            }
        )
    for cle in exportees.keys() - vues:
        problemes.append(f"{FEUILLE_VALEURS} : valeur {cle} absente du classeur")
    return decisions, problemes


def _avertissements(regles: list[dict], valeurs: list[dict]) -> list[str]:
    """Listes écartées dont des valeurs ont pourtant été revues (non bloquant)."""
    ecartees = {
        (r["table"], r["colonne"])
        for r in regles
        if r["regle"] == "valeurs" and r["statut"] == "invalide"
    }
    revues: dict[tuple[str, str], int] = {}
    for v in valeurs:
        cle = (v["table"], v["colonne"])
        if cle in ecartees and v["statut"] in ("valide", "invalide"):
            revues[cle] = revues.get(cle, 0) + 1
    return [
        f"{table}.{colonne} : liste écartée, mais {n} valeurs revues "
        "(statuts conservés, sans effet tant que la liste est écartée)"
        for (table, colonne), n in sorted(revues.items())
    ]


def importer_revue(chemin: str | Path, dictionnaire: dict) -> Revue:
    """Lit un classeur de revue et contrôle chaque décision, sans modifier le dictionnaire.

    `dictionnaire` est le dictionnaire courant : un classeur exporté avant une
    régénération qui a changé une proposition est refusé (classeur périmé). Tous les
    problèmes bloquants sont listés en une fois dans une ValueError, avec la feuille et
    le numéro de ligne Excel. Les avertissements ne bloquent pas l'import.
    """
    chemin = Path(chemin)
    classeur = load_workbook(chemin, read_only=True, data_only=True)
    try:
        try:
            lignes_r = _lire_feuille(classeur, FEUILLE_REGLES, COLONNES_REGLES)
            lignes_v = _lire_feuille(classeur, FEUILLE_VALEURS, COLONNES_VALEURS)
        except ValueError as erreur:
            raise ValueError(f"Classeur de revue invalide ({chemin})\n  {erreur}") from None
    finally:
        classeur.close()

    regles, problemes_r = _controler_regles(lignes_r, dictionnaire)
    valeurs, problemes_v = _controler_valeurs(lignes_v, dictionnaire)
    problemes = problemes_r + problemes_v
    if problemes:
        raise ValueError(
            f"Classeur de revue invalide ({chemin}), {len(problemes)} problèmes\n  "
            + "\n  ".join(problemes)
        )
    return Revue(
        pd.DataFrame(regles, columns=[
            "table", "colonne", "regle", "statut", "regle_retenue", "commentaire", "ligne_excel",
        ]),
        pd.DataFrame(valeurs, columns=[
            "table", "colonne", "valeur", "origine", "statut", "commentaire", "ligne_excel",
        ]),
        _avertissements(regles, valeurs),
    )
