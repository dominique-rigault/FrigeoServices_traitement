"""Outils de traitement des données de Frigéo Services."""

from pathlib import Path


def racine_projet() -> Path:
    """Remonte jusqu'au dossier qui contient .git."""
    courant = Path.cwd().resolve()
    for dossier in [courant, *courant.parents]:
        if (dossier / ".git").exists():
            return dossier
    raise RuntimeError("Racine du projet introuvable")