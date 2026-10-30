"""Classeurs remplis par le métier : dossier commun et archivage des classeurs appliqués.

Ce module ne contient rien de propre à un client. Quatre classeurs Excel passent par
le métier : la revue du dictionnaire (notebook 03), le formulaire des règles de
contrôle (notebook 04), le formulaire des règles de gestion (notebook 05) et
l'arbitrage des anomalies (notebook 07). Ils portent des
valeurs du client et sont rangés ensemble hors du dépôt, dans data/formulaires/.
Un classeur appliqué est déplacé dans data/formulaires/appliques/, sous un nom qui
porte l'heure de l'archivage : il garde la trace des décisions du métier, et
l'export suivant repart d'un dossier où ne restent que les classeurs à traiter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, TypeVar

from . import dictionnaire as module_dictionnaire
from . import racine_projet

DOSSIER_ARCHIVES = "appliques"

Resultat = TypeVar("Resultat")


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
