import os
import urllib.request

import numpy as np
import pycountry
import reverse_geocoder as rg

try:
    import rasterio
    from rasterio.transform import rowcol
    RASTERIO_AVAILABLE = True
except ImportError:
    RASTERIO_AVAILABLE = False


# ESA WorldCover 2021 land cover class codes mapped to the habitat vocabulary
# used in the flora dataset. Where a class has no clean equivalent (cropland,
# built-up) it maps to None, which the caller can handle as unknown.
ESA_TO_HABITAT = {
    10:  'forest',      # Tree cover
    20:  'shrubland',   # Shrubland
    30:  'grasslands',  # Grassland
    40:  None,          # Cropland: no direct habitat equivalent
    50:  None,          # Built-up: no direct habitat equivalent
    60:  'desert',      # Bare / sparse vegetation
    70:  'mountains',   # Snow and ice: high-altitude, maps to mountains
    80:  'water',       # Permanent water bodies
    90:  'water',       # Herbaceous wetland
    95:  'coastal',     # Mangroves
    100: 'mountains',   # Moss and lichen: tundra/alpine, maps to mountains
}

# ISO 3166-1 alpha-2 codes to the exact country name strings used in the dataset.
# Most countries resolve cleanly through pycountry; this dict overrides the ones
# that don't match or use a different convention in the dataset.
ISO2_OVERRIDES = {
    'BO': 'Bolivia',
    'BN': 'Brunei',
    'CV': 'Cape Verde',
    'CZ': 'Czech Republic',
    'CD': 'Democratic Republic of the Congo',
    'AN': 'Dutch Caribbean',
    'GB': 'United Kingdom',
    'FK': 'Falkland Islands',
    'FM': 'Federated States of Micronesia',
    'GE': 'Georgia (country)',
    'IR': 'Iran',
    'CI': 'Ivory Coast',
    'XK': 'Kosovo',
    'LA': 'Laos',
    'MD': 'Moldova',
    'KP': 'North Korea',
    'PN': 'Pitcairn Islands',
    'CG': 'Republic of the Congo',
    'RU': 'Russia',
    'KR': 'South Korea',
    'SZ': 'Swaziland',
    'SY': 'Syria',
    'ST': 'São Tomé and Príncipe',
    'TW': 'Taiwan',
    'TZ': 'Tanzania',
    'VN': 'Vietnam',
}

# WorldCover tiles are downloaded on demand and cached in this directory.
TILE_CACHE_DIR = os.environ.get('ESA_TILE_CACHE', './esa_tiles')

# ESA WorldCover 2021 tile URL template. Tiles are 3x3 degree cells named by
# their south-west corner, e.g. N51E000 for the tile covering 51-54N, 0-3E.
ESA_TILE_URL = (
    'https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/'
    'ESA_WorldCover_10m_2021_v200_{tile}_Map.tif'
)


def _tile_name(lat: float, lon: float) -> str:
    """Return the ESA WorldCover tile name covering a given coordinate."""
    lat_floor = int(np.floor(lat / 3)) * 3
    lon_floor = int(np.floor(lon / 3)) * 3
    lat_str = f"{'N' if lat_floor >= 0 else 'S'}{abs(lat_floor):02d}"
    lon_str = f"{'E' if lon_floor >= 0 else 'W'}{abs(lon_floor):03d}"
    return f"{lat_str}{lon_str}"


def _get_tile_path(tile_name: str) -> str:
    """Return local path to a cached ESA tile, downloading it if necessary."""
    os.makedirs(TILE_CACHE_DIR, exist_ok=True)
    path = os.path.join(TILE_CACHE_DIR, f"{tile_name}.tif")
    if not os.path.exists(path):
        url = ESA_TILE_URL.format(tile=tile_name)
        print(f"Downloading ESA tile {tile_name} from {url} ...")
        urllib.request.urlretrieve(url, path)
        print(f"Saved to {path}")
    return path


def coords_to_country(lat: float, lon: float) -> str | None:
    """
    Resolve a coordinate pair to the country name string used in the dataset.
    Returns None if the coordinate cannot be resolved.
    """
    results = rg.search((lat, lon), verbose=False)
    if not results:
        return None

    iso2 = results[0].get('cc', '').upper()

    if iso2 in ISO2_OVERRIDES:
        return ISO2_OVERRIDES[iso2]

    country = pycountry.countries.get(alpha_2=iso2)
    if country:
        return country.name

    return None


def coords_to_habitat(lat: float, lon: float) -> str | None:
    """
    Resolve a coordinate pair to a habitat string using ESA WorldCover 2021.
    Downloads and caches the relevant tile on first use.
    Returns None if rasterio is unavailable, the tile cannot be fetched,
    or the ESA class has no habitat equivalent (cropland, built-up).
    """
    if not RASTERIO_AVAILABLE:
        raise RuntimeError(
            'rasterio is required for habitat resolution. '
            'Install it with: pip install rasterio'
        )

    tile_name = _tile_name(lat, lon)

    try:
        tile_path = _get_tile_path(tile_name)
    except Exception as e:
        raise RuntimeError(f"Could not fetch ESA tile {tile_name}: {e}") from e

    with rasterio.open(tile_path) as src:
        row, col = rowcol(src.transform, lon, lat)
        window = rasterio.windows.Window(col, row, 1, 1)
        data = src.read(1, window=window)
        esa_class = int(data[0, 0])

    return ESA_TO_HABITAT.get(esa_class)


def resolve_coordinates(lat: float, lon: float) -> dict:
    """
    Resolve a coordinate pair to both country and habitat.
    Returns a dict with 'country', 'habitat', and 'esa_class' keys.
    habitat and esa_class are None if resolution fails.
    """
    country = coords_to_country(lat, lon)

    try:
        tile_name = _tile_name(lat, lon)
        tile_path = _get_tile_path(tile_name)
        with rasterio.open(tile_path) as src:
            row, col = rowcol(src.transform, lon, lat)
            window = rasterio.windows.Window(col, row, 1, 1)
            data = src.read(1, window=window)
            esa_class = int(data[0, 0])
        habitat = ESA_TO_HABITAT.get(esa_class)
    except Exception:
        esa_class = None
        habitat = None

    return {
        'country':   country,
        'habitat':   habitat,
        'esa_class': esa_class,
    }
