"""Détermination du périmètre de traitement à partir de la dernière période déposée.

Convention de dépôt des fichiers
- l'exemplaire annuel 2025 se trouve dans data/raw/2025
- chaque export mensuel porte sa période dans son nom, par exemple
  interventions_2026-04.csv, et peut être déposé directement dans
  data/raw/2026 ou dans un sous-dossier portant le nom du mois, par exemple
  data/raw/2026/2026-04
- les référentiels se trouvent dans data/referentiels
"""

from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

PERIODE_ANNUELLE = "2025"
PREMIER_MOIS = "2026-01"

MODELES_NOMS = {
    "interventions": "interventions_{p}.csv",
    "pieces_interventions": "pieces_interventions_{p}.csv",
    "factures": "factures_{p}.xlsx",
    "achats": "achats_{p}.xlsx",
}
NOM_FEC_ANNUEL = "999000001FEC20251231.txt"
MODELE_FEC_MENSUEL = "FEC_extraction_{p}.txt"
REFERENTIELS = {
    "intervenants": "intervenants.xlsx",
    "clients": "clients.csv",
    "fournisseurs": "fournisseurs.csv",
    "catalogue_pieces": "catalogue_pieces.xlsx",
    "parametres_couts": "parametres_couts.xlsx",
}


def periodes(periode_fin: str) -> list[str]:
    """Liste des périodes à traiter, de l'année 2025 jusqu'à periode_fin incluse."""
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", periode_fin):
        raise ValueError(
            f"PERIODE_FIN doit avoir la forme AAAA-MM, valeur reçue {periode_fin!r}"
        )
    if periode_fin < PREMIER_MOIS:
        raise ValueError(f"PERIODE_FIN doit être au moins égale à {PREMIER_MOIS}")
    annee, mois = (int(x) for x in PREMIER_MOIS.split("-"))
    fin_annee, fin_mois = (int(x) for x in periode_fin.split("-"))
    resultat = [PERIODE_ANNUELLE]
    while (annee, mois) <= (fin_annee, fin_mois):
        resultat.append(f"{annee}-{mois:02d}")
        mois += 1
        if mois > 12:
            annee, mois = annee + 1, 1
    return resultat


def noms_attendus(periode: str) -> dict[str, str]:
    """Nom de fichier attendu pour chaque flux périodique d'une période."""
    noms = {flux: modele.format(p=periode) for flux, modele in MODELES_NOMS.items()}
    if periode == PERIODE_ANNUELLE:
        noms["fec"] = NOM_FEC_ANNUEL
    else:
        noms["fec"] = MODELE_FEC_MENSUEL.format(p=periode)
    return noms


@dataclass
class Perimetre:
    data_dir: Path
    periode_fin: str
    periodes: list[str]
    fichiers: list[dict] = field(default_factory=list)
    manquants: list[str] = field(default_factory=list)
    ambigus: dict[str, list[Path]] = field(default_factory=dict)
    ignores: list[Path] = field(default_factory=list)

    @property
    def date_coupure(self) -> date:
        """Dernier jour de la période de fin, utilisé pour les décalages de fin d'extraction."""
        annee, mois = (int(x) for x in self.periode_fin.split("-"))
        return date(annee, mois, monthrange(annee, mois)[1])

    def verifier(self) -> None:
        """Arrête le traitement avec un message clair si le périmètre est incomplet."""
        erreurs = []
        if self.manquants:
            erreurs.append(
                "Fichiers attendus introuvables\n  " + "\n  ".join(self.manquants)
            )
        for nom, chemins in self.ambigus.items():
            endroits = "\n  ".join(
                c.relative_to(self.data_dir).as_posix() for c in chemins
            )
            erreurs.append(f"Fichier {nom} présent à plusieurs endroits\n  {endroits}")
        if erreurs:
            raise RuntimeError(
                "\n".join(erreurs)
                + "\nVérifiez le dépôt des fichiers et la valeur de PERIODE_FIN."
            )

    def resume(self) -> str:
        return (
            f"{len(self.periodes)} périodes ({', '.join(self.periodes)}), "
            f"{len(self.fichiers)} fichiers retenus, "
            f"date de coupure {self.date_coupure.isoformat()}, "
            f"{len(self.ignores)} fichiers de data/raw hors périmètre"
        )

    def tableau(self) -> pd.DataFrame:
        return pd.DataFrame(
            [{k: v for k, v in f.items() if k != "chemin"} for f in self.fichiers]
        )


def decouvrir(data_dir: Path, periode_fin: str) -> Perimetre:
    """Repère les fichiers du périmètre par leur nom, où qu'ils soient dans data/raw."""
    raw = data_dir / "raw"
    index: dict[str, list[Path]] = {}
    for chemin in raw.rglob("*"):
        if chemin.is_file():
            index.setdefault(chemin.name, []).append(chemin)

    perimetre = Perimetre(
        data_dir=data_dir, periode_fin=periode_fin, periodes=periodes(periode_fin)
    )
    utilises = set()

    def retenir(flux: str, periode: str | None, chemin: Path) -> None:
        perimetre.fichiers.append(
            {
                "flux": flux,
                "periode": periode,
                "fichier": chemin.name,
                "chemin_relatif": chemin.relative_to(data_dir).as_posix(),
                "chemin": chemin,
            }
        )
        utilises.add(chemin)

    for periode in perimetre.periodes:
        for flux, nom in noms_attendus(periode).items():
            trouves = index.get(nom, [])
            if len(trouves) == 1:
                retenir(flux, periode, trouves[0])
            elif not trouves:
                perimetre.manquants.append(nom)
            else:
                perimetre.ambigus[nom] = trouves

    for flux, nom in REFERENTIELS.items():
        chemin = data_dir / "referentiels" / nom
        if chemin.is_file():
            retenir(flux, None, chemin)
        else:
            perimetre.manquants.append(f"referentiels/{nom}")

    perimetre.ignores = sorted(
        c for chemins in index.values() for c in chemins if c not in utilises
    )
    return perimetre