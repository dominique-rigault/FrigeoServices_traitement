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
  les cinq mesures de contrôle restent dans le modèle;
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

## À venir (étape 8)

Tableau de bord direction (8.2), tableau de bord qualité (8.3), pages
d'extraction vers les lignes et les anomalies (8.4), ergonomie mobile et
documentation finale (8.5).
