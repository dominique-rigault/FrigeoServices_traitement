"""Classeurs remplis par le métier : dossier commun et archivage des classeurs appliqués.

Ce module ne contient rien de propre à un client. Quatre classeurs Excel passent par
le métier : la revue du dictionnaire (notebook 03), le formulaire des règles de
contrôle (notebook 04), le formulaire des règles de gestion (notebook 05) et
l'arbitrage des anomalies (notebook 07). Ils portent des
valeurs du client et sont rangés ensemble hors du dépôt, dans data/formulaires/.
Un classeur appliqué est déplacé dans data/formulaires/appliques/, sous un nom qui
porte l'heure de l'archivage : il garde la trace des décisions du métier, et
l'export suivant repart d'un dossier où ne restent que les classeurs à traiter.
Les nombres affichés dans ces classeurs portent un séparateur des milliers, et les
cellules que le métier peut modifier ont un fond jaune clair.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, TypeVar

from openpyxl.styles import PatternFill, Protection

from . import dictionnaire as module_dictionnaire
from . import racine_projet

DOSSIER_ARCHIVES = "appliques"
# Séparateur des milliers des nombres écrits dans un texte (espace insécable).
SEPARATEUR_MILLIERS = chr(160)
# Format d'affichage d'un effectif dans une cellule : Excel y met le séparateur des
# milliers de sa langue (une espace en français), la valeur restant un nombre.
FORMAT_EFFECTIF = "#,##0"
# Fond des cellules modifiables (jaune clair), les autres cellules étant verrouillées.
COULEUR_MODIFIABLE = "FFF2CC"
# Mention du fond dans les modes d'emploi.
FOND_MODIFIABLE = "sur fond jaune clair"
# Entier d'au moins quatre chiffres qui n'est pas la partie décimale d'un nombre.
_ENTIER_LONG = re.compile(r"(?<![\d,])\d{4,}")
# Point décimal entre deux chiffres, hors d'un nombre plus long qui en aurait plusieurs.
_POINT_DECIMAL = re.compile(r"(?<![\d.])(\d+)\.(\d+)(?![\d.])")

Resultat = TypeVar("Resultat")


def _grouper(chiffres: str) -> str:
    """Chiffres groupés par trois depuis la droite, zéros de tête compris."""
    tete = len(chiffres) % 3 or 3
    groupes = [chiffres[:tete]] + [chiffres[i:i + 3] for i in range(tete, len(chiffres), 3)]
    return SEPARATEUR_MILLIERS.join(groupes)


def rendre_modifiable(cellule) -> None:
    """Déverrouille une cellule d'une feuille protégée et lui donne le fond des
    cellules modifiables."""
    cellule.protection = Protection(locked=False)
    cellule.fill = PatternFill(fill_type="solid", fgColor=COULEUR_MODIFIABLE)


def texte_entier(nombre: int) -> str:
    """Entier écrit avec un séparateur des milliers (« 10 191 »)."""
    signe = "-" if nombre < 0 else ""
    return signe + _grouper(str(abs(int(nombre))))


def separer_milliers(texte: str) -> str:
    """Texte dont les entiers d'au moins quatre chiffres reçoivent le séparateur des
    milliers; la partie décimale d'un nombre écrit avec une virgule n'est pas touchée.
    À n'appliquer qu'à un texte fait de nombres et de mots, sans date ni code."""
    return _ENTIER_LONG.sub(lambda m: _grouper(m.group()), texte)


def nombres_a_la_francaise(texte: str) -> str:
    """Texte dont les nombres décimaux prennent la virgule et les grands entiers le
    séparateur des milliers (« 12345 lignes, 98.5 % » devient « 12 345 lignes,
    98,5 % »). Même réserve que `separer_milliers`."""
    return separer_milliers(_POINT_DECIMAL.sub(r"\1,\2", texte))


def dossier_formulaires() -> Path:
    """Dossier des classeurs du métier : data/formulaires/, hors du dépôt."""
    return racine_projet() / "data" / "formulaires"


def dossier_archives(chemin: str | Path | None = None) -> Path:
    """Dossier des classeurs appliqués : `appliques/`, à côté du classeur."""
    dossier = Path(chemin).parent if chemin is not None else dossier_formulaires()
    return dossier / DOSSIER_ARCHIVES


def archiver_formulaire(chemin: str | Path, dossier: str | Path | None = None) -> Path:
    """Déplace un classeur appliqué dans `dossier` (par défaut data/formulaires/
    appliques) et rend son nouveau chemin.

    Le nom reçoit l'heure de l'archivage : `<nom>_<AAAA-MM-JJ>_<HHMMSS>.xlsx`. Une
    archive déjà présente sous ce nom n'est jamais remplacée. Sous Windows, un
    classeur ouvert dans Excel ne peut pas être déplacé (PermissionError) : rien
    n'est alors modifié.
    """
    chemin = Path(chemin)
    dossier = Path(dossier) if dossier is not None else dossier_archives(chemin)
    instant = module_dictionnaire._maintenant()
    archive = dossier / f"{chemin.stem}_{instant:%Y-%m-%d_%H%M%S}{chemin.suffix}"
    if archive.exists():
        raise FileExistsError(
            f"{archive} existe déjà : archivage refusé, rien n'a été modifié (relancer "
            "dans une seconde)"
        )
    dossier.mkdir(parents=True, exist_ok=True)
    try:
        chemin.rename(archive)
    except PermissionError:
        raise PermissionError(
            f"{chemin} ne peut pas être déplacé : fermer le classeur dans Excel, puis "
            "relancer la cellule (rien n'a été modifié)"
        ) from None
    return archive


def ecrire_et_archiver(
    chemin: str | Path,
    ecrire: Callable[[], Resultat],
    dossier: str | Path | None = None,
) -> tuple[Resultat, Path]:
    """Archive un classeur, puis écrit ce qu'il a décidé (`ecrire`, sans argument).

    L'archivage vient d'abord : un classeur ouvert dans Excel arrête tout avant
    l'écriture. Si l'écriture échoue, le classeur est remis à sa place, et
    l'erreur est transmise. Rend le résultat de `ecrire` et le chemin de l'archive.
    """
    chemin = Path(chemin)
    archive = archiver_formulaire(chemin, dossier)
    try:
        resultat = ecrire()
    except BaseException:
        archive.rename(chemin)
        raise
    return resultat, archive
