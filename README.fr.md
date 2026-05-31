# oglap (SDK Python)

> SDK Python du protocole **OGLAP** — Offline Grid Location Addressing pour le profil Guinée (GGP).

🇬🇧 **English version** → [README.md](README.md)

Convertit des coordonnées GPS en codes d'adresse compacts, déterministes et lisibles (ex. `GN-CON-QYTC-B0B1-2282`) et inversement — entièrement hors ligne, sans API externe. Conçu pour les régions où l'adressage postal formel est rare ou peu fiable.

[![Version PyPI](https://img.shields.io/pypi/v/oglap.svg)](https://pypi.org/project/oglap/)
[![Versions Python](https://img.shields.io/pypi/pyversions/oglap.svg)](https://pypi.org/project/oglap/)
[![Licence : MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Sommaire

- [Pourquoi OGLAP ?](#pourquoi-oglap-)
- [Format du code LAP](#format-du-code-lap)
- [Installation](#installation)
- [Initialisation (obligatoire)](#initialisation-obligatoire)
- [API principale](#api-principale)
  - [`coordinates_to_lap` — encoder GPS → LAP](#coordinates_to_lap--encoder-gps--lap)
  - [`lap_to_coordinates` — décoder LAP → GPS](#lap_to_coordinates--décoder-lap--gps)
  - [`parse_lap_code` — parser un code en composants](#parse_lap_code--parser-un-code-en-composants)
  - [`validate_lap_code` — valider un code](#validate_lap_code--valider-un-code)
  - [`get_place_by_lap_code` — retrouver le lieu sous-jacent](#get_place_by_lap_code--retrouver-le-lieu-sous-jacent)
  - [`bbox_from_geometry` & `centroid_from_bbox`](#bbox_from_geometry--centroid_from_bbox)
  - [État et métadonnées](#état-et-métadonnées)
- [Fichiers de données et cache](#fichiers-de-données-et-cache)
- [Exemple complet de bout en bout](#exemple-complet-de-bout-en-bout)
- [Intégration dans un framework web](#intégration-dans-un-framework-web)
- [Performances](#performances)
- [Tests](#tests)
- [Versionnage et compatibilité](#versionnage-et-compatibilité)
- [Licence](#licence)

---

## Pourquoi OGLAP ?

Dans de nombreuses régions du monde, les adresses postales classiques n'existent pas ou ne sont pas fiables pour livrer un colis, dépêcher des secours ou partager sa position. OGLAP résout ce problème en découpant le pays en une grille déterministe et en attribuant à chaque cellule d'environ 1 m × 1 m un code court, copiable-collable.

- **Hors ligne d'abord** — fonctionne sans réseau une fois les données mises en cache.
- **Déterministe** — les mêmes coordonnées produisent toujours le même code ; le même code redonne toujours le même point.
- **Hiérarchique** — le préfixe révèle pays / région / zone, donc le code reste utile même tronqué.
- **Lisible** — uniquement A–Z majuscules et chiffres, aucun caractère ambigu.

---

## Format du code LAP

Un code LAP encode une localisation sur quatre niveaux hiérarchiques. Deux stratégies de grille coexistent :

### Grille locale (5 segments — à l'intérieur des zones administratives nommées)

```
GN  - CON  - QYTC - B0B1 - 2282
│      │      │      │      └─ Microspot   — 4 chiffres, offset métrique ~1 m dans le macrobloc
│      │      │      └─────── Macrobloc    — 4 chars [A–J][0–9][A–J][0–9], cellule ~100 m dans la zone
│      │      └────────────── Zone         — 4 chars, niveau administratif ≥8 immédiat (ex. QYTC pour Yattaya-Fossedè)
│      └───────────────────── Région       — 3 chars, niveau administratif 4 ou 6 immédiat (ex. CON pour Conakry)
└──────────────────────────── Pays         — code ISO alpha-2 (ex. GN pour Guinée)
```

### Grille nationale (4 segments — repli pour les zones rurales sans découpage de niveau ≥8)

```
GN  - NZE  - AABCDE - 4250
│      │      │        └─ Microspot   — 4 chiffres, offset ~1 m
│      │      └────────── Macrobloc    — 6 lettres, grille kilométrique nationale
│      └──────────────── Région       — 3 chars (ex. NZE pour Nzérékoré)
└─────────────────────── Pays         — code ISO alpha-2
```

Le SDK choisit automatiquement la bonne grille selon que la coordonnée se trouve à l'intérieur d'un polygone administratif nommé de niveau ≥8 ou non.

---

## Installation

```bash
pip install oglap
```

Requiert **Python ≥ 3.9** et dépend de [`shapely`](https://shapely.readthedocs.io/) (opérations géométriques) et [`httpx`](https://www.python-httpx.org/) (téléchargement async).

Installation dans un virtualenv neuf :

```bash
python -m venv .venv
source .venv/bin/activate    # Windows : .venv\Scripts\activate
pip install oglap
```

---

## Initialisation (obligatoire)

Appelez `init_oglap()` **une seule fois** au démarrage de l'application, avant toute fonction d'encodage/décodage. Au premier appel, trois fichiers JSON sont téléchargés depuis le CDN OGLAP (`https://s3.guinee.io/oglap/ggp/latest/`) et mis en cache dans `oglap-data/<version>/`. Les appels suivants se font instantanément depuis le cache.

```python
import asyncio
from oglap import init_oglap

async def main():
    def on_progress(*, label, status, percent, step, totalSteps, **_):
        # status ∈ 'downloading' | 'cached' | 'slow' | 'validating' | 'done' | 'error'
        if status == "downloading":
            print(f"\r↓ [{step}/{totalSteps}] {label} : {percent}%", end="")
        elif status == "cached":
            print(f"⚡ [{step}/{totalSteps}] {label} : chargé depuis le cache")
        elif status == "done":
            print(f"✓ [{step}/{totalSteps}] {label} : prêt")
        elif status == "error":
            print(f"✗ [{step}/{totalSteps}] {label} : erreur")

    report = await init_oglap({
        "version": "latest",          # 'latest' (par défaut) ou une version épinglée
        "data_dir": "oglap-data",     # dossier de cache local (défaut : 'oglap-data')
        "force_download": False,      # forcer le téléchargement même si le cache est présent
        "on_progress": on_progress,
    })

    if not report["ok"]:
        raise RuntimeError(f"Échec d'initialisation OGLAP : {report['error']}")

asyncio.run(main())
```

### Structure du rapport d'initialisation

| Clé            | Type           | Description                                                        |
| -------------- | -------------- | ------------------------------------------------------------------ |
| `ok`           | `bool`         | `True` si l'initialisation a réussi                                |
| `countryCode`  | `str \| None`  | Code pays actif, ex. `"GN"`                                        |
| `countryName`  | `str \| None`  | Nom affiché, ex. `"Guinea"`                                        |
| `bounds`       | `list \| None` | `[[swLat, swLon], [neLat, neLon]]`                                 |
| `checks`       | `list[dict]`   | Résultats de validation par étape — chacun `{id, status, message}` |
| `error`        | `str \| None`  | Premier message d'erreur fatal en cas d'échec                      |
| `dataDir`      | `str`          | Dossier de cache local résolu                                      |
| `dataLoaded`   | `dict`         | `{ok, count, message}` — lieux chargés dans le moteur              |

### Mode direct (apportez vos propres données)

Si vous avez déjà les fichiers JSON en mémoire (par ex. chargés vous-même ou embarqués dans l'application), ignorez le téléchargement :

```python
import json, asyncio
from oglap import init_oglap, load_oglap

async def main():
    profile    = json.load(open("mon-profil.json"))
    localities = json.load(open("mes-localites.json"))
    places     = json.load(open("mes-lieux.json"))

    report = await init_oglap(profile, localities)
    if not report["ok"]:
        raise RuntimeError(report["error"])

    load_oglap(places)   # charge la base de lieux dans le moteur

asyncio.run(main())
```

---

## API principale

Toutes les fonctions ci-dessous sont **synchrones** (pas de réseau, calcul pur en mémoire) sauf `init_oglap`. Importez-les depuis le package racine `oglap` :

```python
from oglap import (
    init_oglap,
    load_oglap,
    check_oglap,
    coordinates_to_lap,
    lap_to_coordinates,
    parse_lap_code,
    validate_lap_code,
    get_place_by_lap_code,
    bbox_from_geometry,
    centroid_from_bbox,
    get_package_version,
    get_country_code,
    get_country_sw,
    get_country_profile,
    get_oglap_prefectures,
    get_oglap_places,
)
```

### `coordinates_to_lap` — encoder GPS → LAP

```python
from oglap import coordinates_to_lap

result = coordinates_to_lap(9.5370, -13.6773)  # lat, lon

print(result["lapCode"])         # 'GN-CON-QYTC-B0B1-2282'
print(result["humanAddress"])    # 'B0B1-2282, Yattaya Fossedè, Conakry, Guinée'
print(result["isNationalGrid"])  # False
```

Retourne `None` si les coordonnées sont hors du pays (vérification en 3 couches : bbox → polygone pays → polygone administratif).

**Clés du résultat :**

| Clé              | Type           | Description                                                          |
| ---------------- | -------------- | -------------------------------------------------------------------- |
| `lapCode`        | `str`          | Code complet, ex. `"GN-CON-QYTC-B0B1-2282"`                          |
| `country`        | `str`          | Code pays, ex. `"GN"`                                                |
| `admin_level_2`  | `str`          | Code de région, ex. `"CON"`                                          |
| `admin_level_3`  | `str \| None`  | Code de zone (None en grille nationale)                              |
| `macroblock`     | `str`          | Segment macrobloc                                                    |
| `microspot`      | `str`          | Segment microspot                                                    |
| `isNationalGrid` | `bool`         | `True` si la grille nationale (rurale) a été utilisée                |
| `displayName`    | `str`          | Nom issu du géocodage inversé                                        |
| `humanAddress`   | `str`          | Adresse lisible avec séparateurs                                     |
| `address`        | `dict`         | Composants d'adresse structurés                                      |
| `originLat`      | `float`        | Latitude d'origine de la bbox du macrobloc                           |
| `originLon`      | `float`        | Longitude d'origine de la bbox du macrobloc                          |
| `pcode`          | `list[str]`    | P-codes UNOCHA des unités administratives correspondantes            |

### `lap_to_coordinates` — décoder LAP → GPS

```python
from oglap import lap_to_coordinates

coords = lap_to_coordinates("GN-CON-QYTC-B0B1-2282")
# {"lat": 9.5370, "lon": -13.6773}

# Le préfixe pays est optionnel :
lap_to_coordinates("CON-QYTC-B0B1-2282")  # même résultat
```

Retourne `None` si le code est structurellement invalide ou référence une région/zone inconnue.

### `parse_lap_code` — parser un code en composants

```python
from oglap import parse_lap_code

parsed = parse_lap_code("GN-CON-QYTC-B0B1-2282")
# {
#     "admin_level_2_Iso":  "GN-C",   # clé ISO de la région (CON résout vers sa clé style OSM)
#     "admin_level_3_code": "QYTC",   # code court de la zone
#     "macroblock":         "B0B1",
#     "microspot":          "2282",
#     "isNationalGrid":     False,
# }

# Les codes partiels sont aussi acceptés :
parse_lap_code("GN-CON-QYTC")  # région + zone uniquement — retourne {"admin_level_2_Iso", "admin_level_3_code"}
parse_lap_code("QYTC")         # zone uniquement          — retourne {"admin_level_3_code"}
```

> **Note :** le code pays (`GN`) n'est *pas* un champ de l'objet parsé — il est implicite et accessible via `get_country_code()`. Le segment région (ex. `CON`) est exposé sous `admin_level_2_Iso` (clé ISO style OSM, ex. `GN-C`), pas sous le code court à 3 lettres. Utilisez `get_oglap_prefectures()` pour faire le lien entre les deux si vous avez besoin du code court.

### `validate_lap_code` — valider un code

```python
from oglap import validate_lap_code

validate_lap_code("GN-CON-QYTC-B0B1-2282")  # → None  (valide)
validate_lap_code("GN-XXX-INVALID")         # → 'Unknown region code "XXX"'
```

Retourne `None` pour un code valide, ou une chaîne de message d'erreur en cas d'invalidité.

### `get_place_by_lap_code` — retrouver le lieu sous-jacent

```python
from oglap import get_place_by_lap_code

resolved = get_place_by_lap_code("GN-CON-QYTC-B0B1-2282")
# {
#     "place": {"place_id": ..., "address": {...}, "geojson": {...}, "display_name": ...},
#     "parsed": {"admin_level_2_Iso": ..., "admin_level_3_code": ..., ...},
#     # "originLat", "originLon" ne sont présents que lorsque isNationalGrid vaut True
# }

addr = resolved["place"]["address"]
nom = addr.get("village") or addr.get("town") or addr.get("city") or resolved["place"]["display_name"]
```

Pour les codes en grille nationale, `place` vaut `None` (ils ne se rattachent à aucun lieu nommé) et la réponse contient `originLat`/`originLon` égaux au point d'origine sud-ouest du pays — utilisables comme position de repli grossière.

### `bbox_from_geometry` & `centroid_from_bbox`

Helpers de géométrie pour manipuler les formes GeoJSON chargées en interne.

```python
from oglap import bbox_from_geometry, centroid_from_bbox

geometrie = {
    "type": "Polygon",
    "coordinates": [[[-13.70, 9.50], [-13.65, 9.50], [-13.65, 9.55], [-13.70, 9.55], [-13.70, 9.50]]],
}

bbox = bbox_from_geometry(geometrie)   # [minLat, maxLat, minLon, maxLon]
centre = centroid_from_bbox(bbox)      # [lat, lon]
```

### État et métadonnées

```python
from oglap import (
    check_oglap,
    get_package_version,
    get_country_code,
    get_country_sw,
    get_country_profile,
    get_oglap_prefectures,
    get_oglap_places,
)

check_oglap()              # → rapport d'initialisation (même structure)
get_package_version()      # → '2.0.0'
get_country_code()         # → 'GN'
get_country_sw()           # → [7.19, -15.37]
get_country_profile()      # → dict du profil pays chargé
get_oglap_prefectures()    # → {'GN.CON': 'CON', 'GN.NZE': 'NZE', ...}
get_oglap_places()         # → list[dict]  (lieux chargés — volumineux, à utiliser avec parcimonie)
```

---

## Fichiers de données et cache

Le SDK charge trois fichiers de référence depuis `https://s3.guinee.io/oglap/ggp/<version>/` :

| Fichier                             | Taille réseau | Sur disque | Description                                                       |
| ----------------------------------- | ------------- | ---------- | ----------------------------------------------------------------- |
| `gn_oglap_country_profile.json`     | ~1 Ko         | ~3 Ko      | Paramètres de grille, codes admin, règles de nommage, plage de compat. |
| `gn_localities_naming.json`         | ~25 Ko        | ~300 Ko    | Table de nommage des régions / préfectures / zones                |
| `gn_full.json`                      | ~2,5 Mo       | ~13 Mo     | Base de lieux avec polygones GeoJSON                              |

Le CDN sert les trois fichiers avec `Content-Encoding: gzip`. `httpx` décompresse de manière transparente : le fichier mis en cache sur disque est le JSON d'origine, vous n'avez jamais à manipuler de fichier gzippé.

Par défaut, ils sont mis en cache dans `./oglap-data/latest/`. Ce dossier est **gitignoré** dans ce dépôt (et dans le `.gitignore` modèle du SDK) et devrait l'être également dans le vôtre — les fichiers sont retéléchargés de façon reproductible par `init_oglap()`.

Pour forcer un nouveau téléchargement (par ex. après publication d'une mise à jour de jeu de données) :

```python
await init_oglap({"force_download": True})
```

---

## Exemple complet de bout en bout

```python
import asyncio
from oglap import (
    init_oglap,
    coordinates_to_lap,
    lap_to_coordinates,
    validate_lap_code,
    get_place_by_lap_code,
)


class LocationService:
    """Wrapper léger n'exposant que ce dont une app a typiquement besoin."""

    _pret: bool = False

    @classmethod
    async def init(cls) -> None:
        if cls._pret:
            return

        def progress(*, label, status, percent, step, totalSteps, **_):
            if status == "downloading":
                print(f"\r↓ [{step}/{totalSteps}] {label} : {percent}%", end="")
            elif status == "cached":
                print(f"⚡ [{step}/{totalSteps}] {label} : en cache")
            elif status == "done":
                print(f"✓ [{step}/{totalSteps}] {label} : prêt")

        report = await init_oglap({"on_progress": progress})
        if not report["ok"]:
            raise RuntimeError(f"Échec init OGLAP : {report['error']}")
        cls._pret = True

    @staticmethod
    def encode(lat: float, lon: float) -> str | None:
        result = coordinates_to_lap(lat, lon)
        return result["lapCode"] if result else None

    @staticmethod
    def decode(code: str) -> dict | None:
        return lap_to_coordinates(code)  # None si invalide

    @staticmethod
    def valider(code: str) -> str | None:
        return validate_lap_code(code)   # None = valide ; chaîne d'erreur sinon

    @staticmethod
    def resoudre(code: str) -> dict | None:
        r = get_place_by_lap_code(code)
        if not r or not r.get("place"):
            return None
        a = r["place"].get("address", {})
        return {
            "nom":        a.get("village") or a.get("town") or a.get("city") or r["place"].get("display_name"),
            "code_admin": r["parsed"]["admin_level_3_code"],
            "originLat":  r["originLat"],
            "originLon":  r["originLon"],
        }


async def main():
    await LocationService.init()

    code = LocationService.encode(9.660147, -13.588009)
    print(code)                              # 'GN-CON-QYTC-B0B1-2282'
    print(LocationService.decode(code))      # {'lat': ~9.660, 'lon': ~-13.588}
    print(LocationService.valider(code))     # None  (valide)
    print(LocationService.resoudre(code))    # {'nom': 'Yattaya Fossedè', ...}


asyncio.run(main())
```

---

## Intégration dans un framework web

### FastAPI

`init_oglap()` est asynchrone — appelez-le depuis le gestionnaire `lifespan` de FastAPI pour qu'il s'exécute une fois au démarrage et que le moteur soit chaud à chaque requête :

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from oglap import init_oglap, coordinates_to_lap, lap_to_coordinates

@asynccontextmanager
async def lifespan(app: FastAPI):
    report = await init_oglap()
    if not report["ok"]:
        raise RuntimeError(f"Échec init OGLAP : {report['error']}")
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/encode")
def encode(lat: float, lon: float):
    result = coordinates_to_lap(lat, lon)
    if not result:
        raise HTTPException(404, "Coordonnées hors du territoire")
    return result

@app.get("/decode/{code}")
def decode(code: str):
    coords = lap_to_coordinates(code)
    if not coords:
        raise HTTPException(400, "Code LAP invalide")
    return coords
```

### Django (vues synchrones)

Exécutez `init_oglap()` une seule fois au démarrage du process (par ex. depuis un hook `AppConfig.ready()` avec `asyncio.run`, ou une commande management). Les helpers d'encodage/décodage sont eux-mêmes synchrones et s'utilisent directement dans une vue classique.

---

## Performances

- **Index spatial** — `coordinates_to_lap` utilise un STRtree Shapely construit une seule fois lors de `load_oglap()`. Le géocodage inversé d'une coordonnée est en O(log N) pour la sélection de candidats + une petite vérification polygone-dans-polygone.
- **Validation bornée** — toutes les expressions régulières s'appliquent à des chaînes bornées et nettoyées — pas d'exposition ReDoS sur entrée utilisateur malformée.
- **Rejet en 3 couches** — les coordonnées hors pays sont court-circuitées par la vérification bbox, puis le polygone pays, puis le polygone administratif. Les appels hors pays coûtent ~µs.
- **État mono-processus** — le moteur conserve le jeu de données chargé dans un état au niveau du module. Réutilisez le process entre requêtes ; ne rechargez pas les données par requête.

---

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

La suite de tests compte environ 80 tests couvrant encodage, décodage, parsing, validation et déterminisme aller-retour sur les grilles locale et nationale.

---

## Versionnage et compatibilité

Le SDK déclare une plage de compatibilité avec le jeu de données du profil pays via un caret semver. Le fichier `gn_oglap_country_profile.json` actuellement publié exige que le SDK satisfasse `^2.0.0` — ce paquet suit donc la ligne 2.x. Les bumps majeurs du schéma du jeu de données s'accompagneront d'un bump majeur ici.

Vous pouvez inspecter la plage de compatibilité chargée à l'exécution :

```python
from oglap import get_country_profile
print(get_country_profile()["compatibility"])
# {'oglap_package_range': '^2.0.0', 'dataset_versions': ['2026-02-21T14:13:02.414Z']}
```

Si `init_oglap()` échoue avec une erreur de compatibilité, rétrogradez le SDK ou mettez à jour votre jeu de données en cache (`force_download=True`).

---

## Licence

MIT, avec une seule exigence supplémentaire — voir [LICENSE](LICENSE) pour le texte complet.

**Attribution.** Si vous publiez un produit, un service, une application, une bibliothèque ou un jeu de données qui utilise ce SDK (en totalité, en partie, ou sous une forme modifiée), merci d'inclure une mention visible indiquant qu'il utilise le protocole **OGLAP** — dans votre README, sur un écran « À propos » / « Crédits », ou tout emplacement équivalent visible des utilisateurs et contributeurs. Un lien vers le projet est apprécié lorsque c'est raisonnablement praticable.

Issues et contributions : <https://github.com/Guinee-IO/oglap-ggp-python-sdk/issues>
