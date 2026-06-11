import io

import numpy as np
import pycountry
import requests
import reverse_geocoder as rg

try:
    import rasterio
    from rasterio.io import MemoryFile
    RASTERIO_AVAILABLE = True
except ImportError:
    RASTERIO_AVAILABLE = False


# ESA WorldCover 2021 land cover class codes mapped to the habitat vocabulary
# used in the flora dataset. Where a class has no clean equivalent (cropland,
# built-up) it maps to None, which the caller handles as unknown.
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

# Terrascope WCS endpoint for ESA WorldCover 2021.
# Returns a tiny single-pixel GeoTIFF for the requested bounding box.
# No tile storage needed, no large downloads.
WCS_URL = (
    "https://services.terrascope.be/wcs/v2"
    "?SERVICE=WCS&VERSION=2.0.1&REQUEST=GetCoverage"
    "&COVERAGEID=WORLDCOVER_2021_MAP"
    "&BBOX={bbox}"
    "&CRS=EPSG:4326&RESPONSE_CRS=EPSG:4326"
    "&FORMAT=image/tiff"
)

# Size of the bounding box around the coordinate in degrees.
# 0.00005 degrees is about 5 metres, giving a single pixel at 10m resolution.
BBOX_DELTA = 0.00005

# Request timeout in seconds. Terrascope usually responds in under 2 seconds.
WCS_TIMEOUT = 10


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
    Resolve a coordinate pair to a habitat string using the Terrascope WCS API.
    Fetches a single-pixel GeoTIFF into memory, no tile storage required.
    Returns None if the request fails or the ESA class has no habitat equivalent.
    """
    if not RASTERIO_AVAILABLE:
        raise RuntimeError(
            'rasterio is required for habitat resolution. '
            'Install it with: pip install rasterio'
        )

    bbox = (
        f"{lon - BBOX_DELTA},{lat - BBOX_DELTA},"
        f"{lon + BBOX_DELTA},{lat + BBOX_DELTA}"
    )
    url = WCS_URL.format(bbox=bbox)

    response = requests.get(url, timeout=(3, 5))
    response.raise_for_status()

    with MemoryFile(io.BytesIO(response.content)) as memfile:
        with memfile.open() as dataset:
            data = dataset.read(1)
            esa_class = int(data.flat[0])

    return ESA_TO_HABITAT.get(esa_class), esa_class


def resolve_coordinates(lat: float, lon: float) -> dict:
    """
    Resolve a coordinate pair to both country and habitat.
    Returns a dict with 'country', 'habitat', and 'esa_class' keys.
    habitat and esa_class are None if resolution fails.
    """
    country = coords_to_country(lat, lon)

    try:
        habitat, esa_class = coords_to_habitat(lat, lon)
    except Exception:
        habitat = None
        esa_class = None

    return {
        'country':   country,
        'habitat':   habitat,
        'esa_class': esa_class,
    }
