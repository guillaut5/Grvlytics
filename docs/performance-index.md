# L'indice de performance

Code : [`src/grvlytics/perf.py`](../src/grvlytics/perf.py)

## Le problème

Pas de capteur de puissance sur le vélo, donc pas de watts. Sans ça, comparer
deux sorties (ou deux segments) juste sur la vitesse ne veut rien dire : 25 km/h
sur du plat goudronné et 25 km/h dans une descente ne demandent pas le même
effort, et 18 km/h sur un chemin de gravier n'est pas "plus lent" que 22 km/h
sur route au même sens.

Il faut donc une vitesse **corrigée** de tout ce qui, à effort égal, la fait
varier sans rapport avec la forme physique : la pente et le revêtement. Une
fois cette vitesse "équivalent plat/route" obtenue, on la rapporte à la
fréquence cardiaque pour avoir un vrai indicateur d'effort fourni.

## La formule

```
vitesse_ajustée = vitesse × (1 + K_PENTE × pente% / 100) × FACTEUR_TERRAIN[terrain]
indice          = vitesse_ajustée / FC_moyenne
```

Plus l'indice est **élevé**, plus on est allé vite pour un coût cardiaque
donné — c'est-à-dire plus l'effort a été "efficace" ce jour-là, sur ce
segment.

### Correction de pente (`K_PENTE = 8`)

Règle empirique courante en cyclisme : chaque 1% de pente coûte environ 8-10%
de vitesse en plus pour le même effort. Le facteur `(1 + 8 × pente/100)` :
- **grimpe** (pente positive) → vitesse ajustée **augmentée** : une sortie à
  17 km/h dans une côte à 5% "vaut" en réalité bien plus que 17 km/h sur le
  plat
- **descend** (pente négative) → vitesse ajustée **réduite** : filer à 40 km/h
  en descente n'est pas un exploit cardio, la gravité fait le travail

### Correction de terrain (`FACTEUR_TERRAIN`)

|terrain|facteur|
|---|---|
|route|1.00|
|piste cyclable|1.00|
|chemin|1.20|
|sentier|1.35|

Même principe que la pente : le revêtement change la vitesse à effort égal
(résistance au roulement, maniabilité). Ces facteurs viennent d'un seul point
de calibration réel — sur la sortie "bedarieux", à FC quasi identique (125 vs
128 bpm), la vitesse tombait de 22.1 à 18.3 km/h sur chemin, soit ~20% de
perte. **C'est une estimation de premier jet**, pas une valeur validée
statistiquement — à corriger quand on aura plus de sorties comparables.

### Normalisation par FC

Diviser par la fréquence cardiaque moyenne transforme "vitesse ajustée" en
"vitesse ajustée par battement de cœur" — un proxy d'efficacité/forme
physique. C'est ce qui permet de comparer deux jours entre eux : une FC plus
basse pour la même vitesse ajustée = plus en forme (ou mieux reposé, moins de
chaleur, etc. — l'indice ne sait pas distinguer la cause).

## Ce qu'il exclut

Les segments où `elapsed_time` dépasse nettement `moving_time` (plus de 10s
d'écart) sont écartés du calcul de progression — un arrêt au feu ou une pause
photo dans un segment fausserait la vitesse moyenne sans rapport avec l'effort
réel.

## Limites connues

- **Aucune validation externe** : sans capteur de puissance, impossible de
  vérifier objectivement que l'indice reflète vraiment l'effort physiologique.
  C'est un proxy, pas une mesure.
- **Calibré sur une seule sortie** : les facteurs `K_PENTE` et
  `FACTEUR_TERRAIN` sont des ordres de grandeur raisonnables tirés de la
  littérature cycliste + un point de données, pas d'une régression sur
  beaucoup de sorties.
- **Comparable dans le temps, pas entre personnes** : l'indice dépend de la FC
  max/repos individuelle ; il n'a de sens que pour suivre *ta* progression,
  pas pour te comparer à quelqu'un d'autre.
- **Le terrain d'un segment est approximé** : on prend la catégorie
  majoritaire des points GPS du segment (via `classify_points`), pas une
  vraie moyenne pondérée si le segment traverse plusieurs types de terrain.

## Comment il est utilisé

- **Par segment** (`scripts/analyze_ride_segments.py`) : un indice par segment
  Strava traversé sur une sortie donnée.
- **Dans le temps** (`scripts/analyze_period.py`) : pour les segments Strava
  repris plusieurs fois sur la période (mêmes coordonnées GPS à chaque
  passage), l'évolution de l'indice d'un passage à l'autre est le signal de
  progression le plus fiable du projet — même tronçon exact, donc même pente
  et même terrain à chaque fois, seule la forme du jour varie.
