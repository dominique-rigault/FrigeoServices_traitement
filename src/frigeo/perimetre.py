"""Détermination du périmètre de traitement à partir de la dernière période déposée.

Les noms de fichiers, formats et emplacements sont lus dans config/sources.yaml,
à la racine du dépôt. Ce module ne contient aucun nom propre à un client.

Convention de dépôt des fichiers
- les exports périodiques portent leur période dans leur nom, par exemple
  interventions_2026-04.csv, et peuvent être déposés n'importe où dans data/raw,
  directement ou dans un sous-dossier, par exemple data/raw/2026/2026-04
- les référentiels se trouvent dans data/referentiels
"""

from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

FORMATS = ("texte", "excel")
MOTIF_PERIODE = r"\d{4}-(0[1-9]|1[0-2])"


def chemin_configuration() -> Path:
    """Chemin de config/sources.yaml à la racine du projet."""
    from frigeo import racine_projet

    return racine_projet() / "config" / "sources.yaml"


def tables_du_flux(flux: dict) -> dict[str, dict]:
    """Tables extraites d'un flux, avec leurs options (feuille pour Excel)."""
    tables = flux["tables"]
    if isinstance(tables, dict):
        return {nom: dict(options or {}) for nom, options in tables.items()}
    return {nom: {} for nom in tables}


def verifier_configuration(config) -> None:
    """Arrête le traitement avec la liste des problèmes si la configuration est invalide."""
    if not isinstance(config, dict):
        raise RuntimeError("La configuration des sources doit être un dictionnaire YAML")
    erreurs = []
    for cle in ("periodes", "flux"):
        if cle not in config:
            erreurs.append(f"Clé absente à la racine, {cle}")
    if erreurs:
        raise RuntimeError("Configuration des sources invalide\n  " + "\n  ".join(erreurs))

    cfg_periodes = config["periodes"]
    for cle in ("annuelle", "premier_mois"):
        if not isinstance(cfg_periodes.get(cle), str):
            erreurs.append(
                f"periodes.{cle} est absent ou n'est pas un texte (l'écrire entre guillemets)"
            )
    premier = cfg_periodes.get("premier_mois")
    if isinstance(premier, str) and not re.fullmatch(MOTIF_PERIODE, premier):
        erreurs.append(f"periodes.premier_mois doit avoir la forme AAAA-MM, reçu {premier!r}")

    tables_vues: dict[str, str] = {}
    for nom, flux in (config["flux"] or {}).items():
        ou = f"Flux {nom}"
        a_motif, a_fichier = "motif" in flux, "fichier" in flux
        if a_motif == a_fichier:
            erreurs.append(f"{ou} doit avoir soit motif, soit fichier")
        if a_motif and "{p}" not in flux["motif"]:
            erreurs.append(f"{ou} le motif doit contenir {{p}}")
        if "motif_annuel" in flux and not a_motif:
            erreurs.append(f"{ou} motif_annuel n'a de sens qu'avec motif")
        attendu = "raw" if a_motif else "referentiels"
        if flux.get("emplacement") != attendu:
            erreurs.append(f"{ou} emplacement doit valoir {attendu}")
        format_ = flux.get("format")
        if format_ not in FORMATS:
            erreurs.append(f"{ou} format doit valoir {' ou '.join(FORMATS)}")
        if format_ == "texte":
            for cle in ("encodage", "separateur"):
                if not flux.get(cle):
                    erreurs.append(f"{ou} {cle} est obligatoire pour un fichier texte")
        ligne = flux.get("ligne_entete")
        if not isinstance(ligne, int) or ligne < 1:
            erreurs.append(f"{ou} ligne_entete doit être un entier d'au moins 1")
        if not flux.get("tables"):
            erreurs.append(f"{ou} doit déclarer au moins une table")
            continue
        for table, options in tables_du_flux(flux).items():
            if table in tables_vues:
                erreurs.append(f"Table {table} déclarée dans {tables_vues[table]} et {nom}")
            tables_vues[table] = nom
            if format_ == "excel" and not options.get("feuille"):
                erreurs.append(f"{ou} la table {table} doit indiquer sa feuille")
    if erreurs:
        raise RuntimeError("Configuration des sources invalide\n  " + "\n  ".join(erreurs))


def charger_configuration(chemin: Path | None = None) -> dict:
    """Lit et valide la configuration des sources."""
    chemin = chemin or chemin_configuration()
    if not chemin.is_file():
        raise RuntimeError(f"Configuration des sources introuvable {chemin}")
    with open(chemin, encoding="utf-8") as fichier:
        config = yaml.safe_load(fichier)
    verifier_configuration(config)
    return config


def periodes(periode_fin: str, config: dict) -> list[str]:
    """Liste des périodes à traiter, de la période annuelle jusqu'à periode_fin incluse."""
    if not re.fullmatch(MOTIF_PERIODE, periode_fin):
        raise ValueError(
            f"PERIODE_FIN doit avoir la forme AAAA-MM, valeur reçue {periode_fin!r}"
        )
    premier = config["periodes"]["premier_mois"]
    if periode_fin < premier:
        raise ValueError(f"PERIODE_FIN doit être au moins égale à {premier}")
    annee, mois = (int(x) for x in premier.split("-"))
    fin_annee, fin_mois = (int(x) for x in periode_fin.split("-"))
    resultat = [config["periodes"]["annuelle"]]
    while (annee, mois) <= (fin_annee, fin_mois):
        resultat.append(f"{annee}-{mois:02d}")
        mois += 1
        if mois > 12:
            annee, mois = annee + 1, 1
    return resultat


def noms_attendus(config: dict, periode: str) -> dict[str, str]:
    """Nom de fichier attendu pour chaque flux périodique d'une période."""
    annuelle = config["periodes"]["annuelle"]
    noms = {}
    for flux, spec in config["flux"].items():
        if "motif" not in spec:
            continue
        modele = spec["motif"]
        if periode == annuelle and "motif_annuel" in spec:
            modele = spec["motif_annuel"]
        noms[flux] = modele.format(p=periode)
    return noms


@dataclass
class Perimetre:
    data_dir: Path
    periode_fin: str
    periodes: list[str]
    config: dict
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


def decouvrir(
    data_dir: Path, periode_fin: str, config: dict | None = None
) -> Perimetre:
    """Repère les fichiers du périmètre par leur nom, où qu'ils soient dans data/raw."""
    config = config if config is not None else charger_configuration()
    raw = data_dir / "raw"
    index: dict[str, list[Path]] = {}
    for chemin in raw.rglob("*"):
        if chemin.is_file():
            index.setdefault(chemin.name, []).append(chemin)

    perimetre = Perimetre(
        data_dir=data_dir,
        periode_fin=periode_fin,
        periodes=periodes(periode_fin, config),
        config=config,
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
        for flux, nom in noms_attendus(config, periode).items():
            trouves = index.get(nom, [])
            if len(trouves) == 1:
                retenir(flux, periode, trouves[0])
            elif not trouves:
                perimetre.manquants.append(nom)
            else:
                perimetre.ambigus[nom] = trouves

    for flux, spec in config["flux"].items():
        if "fichier" not in spec:
            continue
        chemin = data_dir / spec["emplacement"] / spec["fichier"]
        if chemin.is_file():
            retenir(flux, None, chemin)
        else:
            perimetre.manquants.append(f"{spec['emplacement']}/{spec['fichier']}")

    perimetre.ignores = sorted(
        c for chemins in index.values() for c in chemins if c not in utilises
    )
    return perimetre