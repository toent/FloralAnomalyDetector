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


ESA_TO_HABITAT = {
    10:  'forest',
    20:  'shrubland',
    30:  'grasslands',
    40:  None,
    50:  None,
    60:  'desert',
    70:  'mountains',
    80:  'water',
    90:  'water',
    95:  'coastal',
    100: 'mountains',
}

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

# ESA WorldCover 2021 tile URL template. Tiles are 3x3 degree cells named by
# their south-west corner, e.g. N51E000 for the tile covering 51-54N, 0-3E.
ESA_TILE_URL = (
    'https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/'
    'ESA_WorldCover_10m_2021_v200_{tile}_Map.tif'
)

# Tiles are downloaded on first use and cached here.
# Set the ESA_TILE_CACHE environment variable to override.
TILE_CACHE_DIR = os.environ.get('ESA_TILE_CACHE', './esa_tiles')


def _tile_name(lat: float, lon: float) -> str:
    lat_floor = int(np.floor(lat / 3)) * 3
    lon_floor = int(np.floor(lon / 3)) * 3
    lat_str = f"{'N' if lat_floor >= 0 else 'S'}{abs(lat_floor):02d}"
    lon_str = f"{'E' if lon_floor >= 0 else 'W'}{abs(lon_floor):03d}"
    return f"{lat_str}{lon_str}"


def _get_tile_path(tile_name: str) -> str:
    os.makedirs(TILE_CACHE_DIR, exist_ok=True)
    path = os.path.join(TILE_CACHE_DIR, f"{tile_name}.tif")
    if not os.path.exists(path):
        url = ESA_TILE_URL.format(tile=tile_name)
        print(f"Downloading ESA tile {tile_name} ...")
        urllib.request.urlretrieve(url, path)
        print(f"Cached to {path}")
    return path


def coords_to_country(lat: float, lon: float) -> str | None:
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


def coords_to_habitat(lat: float, lon: float) -> tuple[str | None, int | None]:
    if not RASTERIO_AVAILABLE:
        raise RuntimeError(
            'rasterio is required for habitat resolution. '
            'Install it with: pip install rasterio'
        )

    tile_name = _tile_name(lat, lon)
    tile_path = _get_tile_path(tile_name)

    with rasterio.open(tile_path) as src:
        row, col = rowcol(src.transform, lon, lat)
        window = rasterio.windows.Window(col, row, 1, 1)
        data = src.read(1, window=window)
        esa_class = int(data[0, 0])

    return ESA_TO_HABITAT.get(esa_class), esa_class


def resolve_coordinates(lat: float, lon: float) -> dict:
    country = coords_to_country(lat, lon)

    try:
        habitat, esa_class = coords_to_habitat(lat, lon)
    except Exception as e:
        print(f"habitat resolution failed: {e}")
        habitat = None
        esa_class = None

    return {
        'country':   country,
        'habitat':   habitat,
        'esa_class': esa_class,
    }
