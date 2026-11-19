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
Activité, Rentabilité, Performance, Évolution, Contrôle et Affichage
(mesures de présentation, voir plus bas).

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
Clients actifs N-1 = CALCULATE([Clients actifs], SAMEPERIODLASTYEAR('Calendrier'[Date]))
Évolution des heures = DIVIDE([Heures réalisées] - [Heures réalisées N-1], [Heures réalisées N-1])
Évolution des clients actifs = DIVIDE([Clients actifs] - [Clients actifs N-1], [Clients actifs N-1])
Taux de marge N-1 = DIVIDE([Marge N-1], [CA HT N-1])
Écart de taux de marge (pt) = IF(ISBLANK([Taux de marge N-1]), BLANK(), ([Taux de marge] - [Taux de marge N-1]) * 100)
Chantiers en alerte = CALCULATE(DISTINCTCOUNT('Interventions'[Clé chantier]), KEEPFILTERS('Interventions'[Alerte marge négative] = TRUE()))
Marge des chantiers en alerte = CALCULATE([Marge opérationnelle totale], KEEPFILTERS('Interventions'[Alerte marge négative] = TRUE()))
Chantiers en alerte N-1 = CALCULATE([Chantiers en alerte], SAMEPERIODLASTYEAR('Calendrier'[Date]))
Marge des chantiers en alerte N-1 = CALCULATE([Marge des chantiers en alerte], SAMEPERIODLASTYEAR('Calendrier'[Date]))
Part des interventions avec marge = DIVIDE(CALCULATE([Interventions avec marge], KEEPFILTERS('Interventions'[Retenue pour les indicateurs] = TRUE())), [Interventions retenues])
```

Les évolutions ont le format `▲ 0.0 %;▼ 0.0 %;0.0 %` (flèche selon le
signe), l'écart de taux de marge `▲ 0.0 " pt";▼ 0.0 " pt";0.0 " pt"`. Les
chantiers en alerte sont comptés par la clé de chantier d'Interventions, et
non dans la table Chantiers, pour que le segment Année filtre chaque jour par
sa propre date; l'alerte n'existant que sur des lignes retenues, aucun filtre
de retenue n'est ajouté.

Mesures de présentation (dossier Affichage) : elles ne calculent rien de
nouveau, elles mettent en forme une valeur que les visuels ne savent pas
afficher eux-mêmes (voir « Réglages de Power BI Desktop »).

```
CA HT retenu (k€) = DIVIDE([CA HT retenu], 1000)
CA HT N-1 (k€) = DIVIDE([CA HT N-1], 1000)
Marge retenue (k€) = DIVIDE([Marge retenue], 1000)
Marge N-1 (k€) = DIVIDE([Marge N-1], 1000)
Marge des chantiers en alerte N-1 (affichage) = VAR m = [Marge des chantiers en alerte N-1] RETURN IF(ISBLANK(m), BLANK(), FORMAT(m, "#,0 €"))
Couleur de catégorie = IF(SELECTEDVALUE('Catégories d''intervention'[Catégorie]) IN {"(hors liste)", "(non renseignée)"}, "#A3ABA6", "#2E7D1E")
Couleur du type de commerce = IF(SELECTEDVALUE('Clients'[Type de commerce]) IN {"(non renseigné)", "(client introuvable)"}, "#A3ABA6", "#2E7D1E")
```

Les mesures en k€ ont le format `#,0.0 " k€";-#,0.0 " k€"` : la section des
valeurs négatives, explicite, colle le signe au nombre (`-0,1 k€`).

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

Alerte de marge négative : 146 chantiers, tous d'un jour, pour une marge de
-5 548,69 € sur la période chargée; 127 chantiers et -5 164,80 € en 2025,
19 chantiers et -383,89 € au premier trimestre 2026 (33 chantiers et
-704,20 € au premier trimestre 2025). Ces deux mesures ont leur carte sur la
page `Indicateurs`, avec les mesures de contrôle.

### Indicateur reporté

Le délai moyen de facturation (date de facture moins date d'intervention)
rapproche deux faits ligne à ligne : c'est une règle métier, à calculer dans
la base (colonne de la vue `Interventions`), pas en DAX.

## Thème et toile

Le thème `powerbi/frigeo_theme.json` (*Affichage > Thèmes > Parcourir les
thèmes*) reprend les couleurs du site : vert `#2E7D1E` (valeurs, sélection),
vert profond `#123D08` (titres), fond de page `#F4F8F0`, gris `#A3ABA6`
pour l'année précédente et les cas sans valeur exploitable, bon et mauvais
`#2E7D1E` et `#B42318`, palette catégorielle lisible par les daltoniens
(`#2E7D1E, #3B6FB6, #B9731F, #C2416B, #6E57C9`), police Segoe UI. Il est
versionné par une exception du `.gitignore`.

Les pages ont une toile de 1280 × 720 (*Format de la page > Paramètres du
canevas*). Elles suivent une même grille : marge de 24 à gauche et à droite,
titre et sous-titre en X 24, Y 16, segment Année en haut à droite
(X 1016, Y 16, 240 × 44), cartes de 196 × 120 en Y 76 au pas de 207
(X 24, 231, 438, 645, 852, 1059), visuels à partir de Y 212.

Le segment Année est un segment de boutons (sélection unique et forcée,
sélection en vert), présent sur chaque page. Les tableaux n'affichent pas
de total sur les colonnes d'évolution, qui n'aurait pas de sens.

## Page Direction

- Six cartes : CA, marge, taux de marge, interventions réalisées, heures
  réalisées, clients actifs. Chacune porte deux étiquettes de référence :
  l'évolution (ou l'écart de taux, en points), fléchée et colorée par règle,
  et la valeur de l'année précédente.
- CA mensuel (X 24, Y 212, 820 × 240) : courbe lissée avec marqueurs, axe
  à partir de zéro, « Mois courant » en vert et « Même mois année
  précédente » en gris, en k€. Elle n'est pas filtrée par le segment Année
  (*Format > Modifier les interactions*) et montre les 15 mois chargés.
- Marge par catégorie (X 860, Y 212, 396 × 240) : barres en k€, taux de
  marge en info-bulle, catégories « (hors liste) » et « (non renseignée) »
  en gris (mesure Couleur de catégorie).
- 20 premiers clients (X 24, Y 468, 620 × 236) : table client, CA, marge,
  taux, interventions, filtre N premiers sur le CA.
- Performance (X 660, Y 468, 596 × 236) : matrice des cinq indicateurs de
  performance, valeurs sur les lignes.

Le sous-titre « Données chargées jusqu'au 31/03/2026 » est écrit en dur :
il deviendra une mesure texte (sous-étape 8.5).

## Page Rentabilité

- Quatre cartes : marge et taux de marge (comme sur la page Direction),
  chantiers en alerte et marge des alertes, valeurs en rouge `#B42318`,
  avec l'année précédente; la marge des alertes est arrondie à l'euro.
- Marge par intervenant (X 24, Y 212, 608 × 238) et marge par type de
  commerce (X 648, Y 212, 608 × 238) : barres horizontales en k€, triées
  par marge décroissante, avec en info-bulle le taux de marge, le CA, la
  part des interventions avec marge et le nombre d'interventions
  réalisées. La part avec marge dit si une barre basse vient d'une marge
  faible ou d'interventions sans marge calculable; le nombre
  d'interventions, si elle vient d'un faible volume (arrivée ou départ en
  cours d'année, temps partiel). Les types « (non renseigné) » et
  « (client introuvable) » sont en gris (mesure Couleur du type de
  commerce). Ces deux libellés viennent de la vue `pbi.Clients` : membre
  -1 ou client sans type, et membre -2, la marge des interventions dont le
  client est absent du référentiel.
- 20 premiers clients par marge (X 24, Y 466, 608 × 238) : la table de la
  page Direction, filtre N premiers et tri sur la marge.
- Interventions à marge négative (X 648, Y 466, 608 × 238) : table
  filtrée sur `Interventions[Alerte marge négative] = True`, triée par
  marge croissante : date, client, intervenant, CA, coûts salarial, de
  déplacement et des pièces, marge, en euros sans décimale, avec total
  (égal à la carte de la marge des alertes). C'est la descente vers les
  composantes de coût demandée par le cahier des charges; chaque jour d'un
  chantier en alerte y a sa ligne.

## Alerte de marge négative

La règle est calculée dans la base (`dw.calculer_alertes`, script
`004_calculs.sql` du pack), pas en DAX, et vérifiée par la famille calculs
de `# VERIFICATION BASE`. La marge se lit au niveau du chantier : un
chantier est en alerte quand tous ses jours sont retenus, que son premier
jour est facturable et ni annulé ni reporté, qu'une ligne de facture retenue
cite l'un de ses jours, qu'aucun jour n'est sans marge et que la somme des
marges de ses jours est négative. Sont donc exclus, comme le demande le
cahier des charges, les interventions non facturables et les jours de
chantier inclus au forfait, et aussi les annulations sur place (seul le
déplacement est facturé, pratique normale) et les chantiers pas encore
facturés (ils relèvent de l'alerte des interventions non facturées). La
colonne `Alerte marge négative` de Chantiers et d'Interventions porte la
même valeur sur chaque jour du chantier : la page Rentabilité descend ainsi
aux jours sans relation entre ces deux tables.

## Réglages de Power BI Desktop

Notés sur la version 2.159 (Microsoft Store), dont les intitulés peuvent
changer :

- carte récente : les étiquettes de référence se règlent dans le volet
  Format, avec un titre par étiquette; les unités d'affichage et les
  décimales n'apparaissent qu'après avoir choisi une mesure précise dans
  *Légende > Appliquer les paramètres à*, et sont à refaire après chaque
  remplacement de champ;
- un format personnalisé au niveau du visuel (`#,0,.0 " k€"`) vaut pour la
  valeur principale, pas pour les étiquettes de référence, qui abrègent
  d'elles-mêmes (« K ») : d'où les mesures du dossier Affichage, en k€ par
  division ou en texte par FORMAT; FORMAT d'une valeur vide rend un texte
  vide et non « -- », d'où le test ISBLANK;
- le segment classique ne règle pas la couleur de sélection : utiliser le
  segment de boutons;
- couleur de barre par mesure : *Format > Barres > Couleur > fx*, style de
  mise en forme **Valeur du champ** (et non Règles);
- pas de pas de graduation réglable sur un axe continu;
- matrice : en-têtes de colonnes impossibles à masquer (police réduite,
  texte blanc); un trait vertical vient de la bordure, pas du quadrillage;
  changer le type d'un visuel (table en matrice) garde les champs et une
  partie du format;
- format d'une mesure : le bouton « , » du ruban donne l'espace des
  milliers en français;
- après une recréation de la base (`--recreer`), *Accueil > Actualiser*
  peut signaler à tort une « référence cyclique » sur une requête : dans
  l'éditeur Power Query, *Actualiser l'aperçu > Actualiser tout*, puis
  *Fermer et appliquer*.

## À venir (étape 8)

Tableau de bord qualité (8.3), pages d'extraction vers les lignes et les
anomalies (8.4), ergonomie mobile, sous-titre daté automatiquement et
documentation finale (8.5).
