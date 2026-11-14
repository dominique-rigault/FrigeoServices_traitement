# Tableaux de bord Power BI

Ce guide décrit le modèle des tableaux de bord de l'étape 8,
`powerbi/frigeo_tableaux.pbit` : le rapport destiné à la direction
(indicateurs métier) et au suivi de la qualité des données. Il complète le
modèle de vérification (`powerbi.md`), dont il est issu et dont il reprend
les prérequis, la connexion paramétrée et les règles de confidentialité.

## Origine et différences avec le modèle de vérification

Le fichier est créé en ouvrant `frigeo_verification.pbit` (mêmes paramètres
`Serveur` et `Base`), puis enregistré sous `powerbi/frigeo_tableaux.pbix`.
Trois différences de modèle, décidées à l'étape 8 :

- les pages de tableaux bruts (Dimensions, Faits, Qualité) sont supprimées;
  les cinq mesures de contrôle restent dans le modèle, rangées dans la table
  de mesures (voir plus bas), et la page `Indicateurs` garde leurs cartes;
- le Calendrier est marqué comme table de dates (*Outils de table > Marquer
  comme table de dates*, colonne Date) : la vue `pbi.Calendrier` n'ayant
  plus les membres -1 et -2, la colonne Date n'a pas de vide, et les
  fonctions de comparaison temporelle (SAMEPERIODLASTYEAR) s'appuient
  dessus; les faits à date absente ou hors calendrier tombent dans la
  ligne « (Vide) » des axes de dates;
- quatre relations inactives vers Calendrier[Clé date] complètent les
  relations actives des dates principales : Lignes de facture et Achats
  (Clé date d'échéance), Écritures comptables (Clé date de pièce),
  Chantiers (Clé date de fin). Une mesure les activera par USERELATIONSHIP
  au premier besoin; aucun tableau de bord du cahier des charges ne
  l'exige aujourd'hui.

Le modèle compte donc 26 relations : 22 actives et 4 inactives.

## Fichiers et dépôt

Comme le modèle de vérification : `powerbi/frigeo_tableaux.pbit` versionné
(aucune donnée, aucun chemin, paramètres vidés à l'export), le fichier de
travail `frigeo_tableaux.pbix` hors dépôt.

## Table de mesures

Toutes les mesures vivent dans une table `Mesures` sans donnée, créée par
*Accueil > Entrer des données* (une colonne `Colonne technique`, vide et
masquée) : ce n'est pas une source, seulement un rangement, qui garde les
mesures en un seul endroit quand elles se multiplient. Elles sont classées en
dossiers d'affichage (*Vue Modèle > Propriétés > Dossier d'affichage*) :
Activité, Rentabilité, Performance, Évolution, Contrôle.

Conventions communes :

- périmètre des indicateurs : les interventions retenues
  (`Retenue pour les indicateurs = TRUE()`);
- intervention réalisée : ni annulée ni reportée (`Statut`); une intervention
  au statut vide compterait comme réalisée, mais aucune n'est retenue dans le
  jeu Frigéo;
- les filtres écrits dans une mesure passent par `KEEPFILTERS`, pour s'ajouter
  à ceux du visuel au lieu de les remplacer (sans lui, un segment sur `Statut`
  ou `Retenue` serait ignoré sans prévenir);
- `Facturable` est un texte (`O`, `N`);
- formats réglés sur la mesure : Devise en euros à deux décimales pour les
  montants, pourcentage à une décimale pour les taux, nombre entier pour les
  décomptes.

```
CA HT retenu = CALCULATE([CA HT total], KEEPFILTERS('Interventions'[Retenue pour les indicateurs] = TRUE()))
Marge retenue = CALCULATE([Marge opérationnelle totale], KEEPFILTERS('Interventions'[Retenue pour les indicateurs] = TRUE()))
Taux de marge = DIVIDE([Marge retenue], [CA HT retenu])
Interventions retenues = CALCULATE(COUNTROWS('Interventions'), KEEPFILTERS('Interventions'[Retenue pour les indicateurs] = TRUE()))
Interventions réalisées = CALCULATE(COUNTROWS('Interventions'), KEEPFILTERS('Interventions'[Retenue pour les indicateurs] = TRUE()), KEEPFILTERS(NOT 'Interventions'[Statut] IN {"Annulée", "Reportée"}))
Heures réalisées = DIVIDE(CALCULATE(SUM('Interventions'[Durée (min)]), KEEPFILTERS('Interventions'[Retenue pour les indicateurs] = TRUE()), KEEPFILTERS(NOT 'Interventions'[Statut] IN {"Annulée", "Reportée"})), 60)
Clients actifs = CALCULATE(DISTINCTCOUNT('Interventions'[Clé client]), KEEPFILTERS('Interventions'[Retenue pour les indicateurs] = TRUE()), KEEPFILTERS(NOT 'Interventions'[Statut] IN {"Annulée", "Reportée"}))
CA par intervention = DIVIDE([CA HT retenu], [Interventions réalisées])
CA par heure = DIVIDE([CA HT retenu], [Heures réalisées])
Durée moyenne (h) = DIVIDE([Heures réalisées], [Interventions réalisées])
Taux d'annulation = DIVIDE(CALCULATE(COUNTROWS('Interventions'), KEEPFILTERS('Interventions'[Retenue pour les indicateurs] = TRUE()), KEEPFILTERS('Interventions'[Statut] IN {"Annulée", "Reportée"})), [Interventions retenues])
Part non facturable = DIVIDE(CALCULATE([Interventions réalisées], KEEPFILTERS('Interventions'[Facturable] = "N")), [Interventions réalisées])
CA HT N-1 = CALCULATE([CA HT retenu], SAMEPERIODLASTYEAR('Calendrier'[Date]))
Marge N-1 = CALCULATE([Marge retenue], SAMEPERIODLASTYEAR('Calendrier'[Date]))
Interventions réalisées N-1 = CALCULATE([Interventions réalisées], SAMEPERIODLASTYEAR('Calendrier'[Date]))
Heures réalisées N-1 = CALCULATE([Heures réalisées], SAMEPERIODLASTYEAR('Calendrier'[Date]))
Évolution du CA = DIVIDE([CA HT retenu] - [CA HT N-1], [CA HT N-1])
Évolution de la marge = DIVIDE([Marge retenue] - [Marge N-1], [Marge N-1])
Évolution des interventions = DIVIDE([Interventions réalisées] - [Interventions réalisées N-1], [Interventions réalisées N-1])
```

Les quatre autres mesures de contrôle (`CA HT total`, `Marge opérationnelle
totale`, `Interventions avec marge`, `Interventions retenues`) sont décrites
dans `powerbi.md`.

### Comparaison à l'année précédente

Un filtre de niveau rapport `Calendrier[Période chargée] = True` limite toutes
les pages à la période chargée (colonne calculée dans la base, voir
`powerbi.md`) : les mois sans données disparaissent des axes, et l'année en
cours n'est comparée qu'aux mêmes mois de l'année précédente
(SAMEPERIODLASTYEAR lève de lui-même ce filtre pour lire l'année
précédente, le Calendrier étant marqué table de dates). Sur plusieurs années à
la fois, une évolution n'a pas de sens (15 mois comparés à 3) : les pages
utilisent un segment Année à sélection unique, et les tableaux n'affichent pas
le total des colonnes d'évolution.

### Valeurs de contrôle (période de fin 2026-03)

Marge retenue 722 999,95 €, taux de marge 44,0 %, 9 843 interventions
réalisées, 16 063,3 heures, 653 clients actifs, CA par intervention
167,13 €, CA par heure 102,41 €, durée moyenne 1,63 h, taux d'annulation
3,0 %, part non facturable 3,8 %. CA du premier trimestre 309 292,47 € en
2026 contre 293 430,99 € en 2025 (+5,4 %).

### Indicateur reporté

Le délai moyen de facturation (date de facture moins date d'intervention)
rapproche deux faits ligne à ligne : c'est une règle métier, à calculer dans
la base (colonne de la vue `Interventions`), pas en DAX.

## À venir (étape 8)

Tableau de bord direction (8.2), tableau de bord qualité (8.3), pages
d'extraction vers les lignes et les anomalies (8.4), ergonomie mobile et
documentation finale (8.5).
