# Floral Anomaly Detector: Setup Guide

## Project Structure

```
FloralAnomalyDetector/
    api/
        __init__.py
        app.py
        geo_utils.py
        model_utils.py
    Dockerfile
    fly.toml
    Procfile
    requirements.txt
    flora_dataset.csv
    FloralAnomalyDetector.ipynb
    Floral-Anomaly-Detector.pkl
    test_dataset.csv
    anomaly_detector_explained.md
    .gitignore
```

---

## Prerequisites

- Python 3.12
- Git
- flyctl CLI (for deployment)

---

## Local Setup

**1. Clone the repository.**

```bash
git clone https://github.com/toent/FloralAnomalyDetector.git
cd FloralAnomalyDetector
```

**2. Create and activate a virtual environment.**

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Mac/Linux
source .venv/bin/activate
```

**3. Install dependencies.**

```bash
pip install -r requirements.txt
```

**4. Run the notebook.**

Open `FloralAnomalyDetector.ipynb` in VS Code or Jupyter and run all cells top to bottom. This trains the model and saves `Floral-Anomaly-Detector.pkl` to the repo root.

**5. Start the API server.**

```bash
uvicorn api.app:app --reload
```

The server runs at `http://localhost:8000`. Interactive API docs are at `http://localhost:8000/docs`.

---

## API Endpoints

### `GET /health`
Check whether the server is up and the model is loaded.

### `POST /predict`
Score a single plant/country/habitat combination directly.

```json
{
  "scientific_name": "Opuntia humifusa",
  "country": "Norway",
  "habitat": "desert"
}
```

### `POST /predict/from_coordinates`
Resolve a coordinate pair to country and habitat via reverse geocoding and ESA WorldCover, then score the entry. The first request for a new region downloads and caches the ESA tile, subsequent requests in the same area are instant.

```json
{
  "scientific_name": "Opuntia humifusa",
  "lat": 47.218,
  "lon": -74.606
}
```

### `POST /predict/batch`
Score up to 500 entries in one request. Accepts a list of the same body as `/predict`.

---

## Verdict Values

| Verdict | Meaning |
|---|---|
| `NORMAL: plausible entry` | Score above threshold, entry looks legitimate. |
| `ANOMALY: suspicious entry` | Score below threshold, entry is geographically or ecologically implausible. |
| `INSUFFICIENT DATA: ...` | Habitat has fewer than 30 entries in the dataset, or coordinates could not be resolved. Not scored. |

---

## Deploying to Fly.io

**1. Install flyctl.**

```bash
# Windows
winget install flyctl

# Mac
brew install flyctl
```

**2. Log in.**

```bash
fly auth login
```

**3. Create the persistent volume for ESA tile caching.**

Only needs to be run once.

```bash
fly volumes create esa_tiles --size 10 --region yyz
```

**4. Deploy.**

```bash
fly deploy
```

Fly reads `fly.toml` and `Dockerfile` from the repo root and builds the container. The live URL is `https://floral-anomaly-detector.fly.dev`.

**5. Subsequent deploys.**

```bash
fly deploy
```

Or set up GitHub Actions for automatic deploys on every push to main:

```yaml
# .github/workflows/fly.yml
name: Deploy to Fly.io
on:
  push:
    branches:
      - main

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - run: fly deploy --remote-only
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

Add your token to GitHub repo secrets under `Settings > Secrets > FLY_API_TOKEN`. Get the token with:

```bash
fly auth token
```

---

## ESA Tile Cache

The `/predict/from_coordinates` endpoint uses ESA WorldCover 2021 to resolve habitat from coordinates. Tiles are large GeoTIFF files downloaded on first use per 3x3 degree region and cached on the Fly volume at `/data/esa_tiles`.

The cache survives redeploys because it is stored on the persistent volume. If you ever need to clear it:

```bash
fly ssh console
rm -rf /data/esa_tiles/*
```

To override the cache location, set the `ESA_TILE_CACHE` environment variable.

---

## Hosting Requirements

If you want to deploy this on a different platform, these are the requirements the host must meet.

### For all endpoints

| Requirement | Details |
|---|---|
| Python 3.12 | Earlier versions may work but are untested. |
| GDAL system libraries | Required by rasterio. Must be installed at the OS level, not just via pip. On Debian/Ubuntu: `apt-get install libgdal-dev gdal-bin`. |
| At least 1GB RAM | The model pkl and pandas lookup tables need room. 512MB is not enough and will crash on startup. |
| Writable filesystem | The ESA tile cache needs a directory it can write to. Configurable via the `ESA_TILE_CACHE` environment variable. |

### For `/predict/from_coordinates` specifically

This endpoint makes outbound HTTP requests to two external services. If your host blocks or restricts outbound traffic, this endpoint will fail while `/predict` and `/predict/batch` continue to work fine.

| Service | URL | Purpose |
|---|---|---|
| ESA WorldCover S3 | `https://esa-worldcover.s3.eu-central-1.amazonaws.com` | Downloads GeoTIFF tiles for habitat resolution. Only called once per 3x3 degree region, then cached locally. |
| Reverse geocoder | Offline, no outbound request | Country resolution is done entirely offline using a bundled dataset. No external call needed. |

### Known platform compatibility

| Platform | Works | Notes |
|---|---|---|
| Fly.io | Yes | No outbound restrictions, persistent volumes available for tile cache. |
| Railway | Yes | No outbound restrictions, but no persistent storage on free tier so tiles re-download on each restart. |
| Render free tier | No | Blocks outbound connections to external S3, causing the coordinates endpoint to crash the worker. |
| VPS (DigitalOcean, Hetzner) | Yes | Full network access, full filesystem access. Most flexible option. |
| Heroku | Yes | No outbound restrictions, but no free tier. Ephemeral filesystem means tiles re-download on each dyno restart. |

### If your host blocks outbound traffic

If `/predict/from_coordinates` is not available on your chosen host, the other two endpoints still work fully. You can either pass country and habitat directly via `/predict`, or pre-resolve coordinates to country/habitat before sending the request using a local script.

---

## Retraining the Model

Open `FloralAnomalyDetector.ipynb`, run all cells, and re-pickle the model. The last cell saves `Floral-Anomaly-Detector.pkl`. Commit the new pkl and run `fly deploy`.

---

## Useful Commands

```bash
fly logs          # Live server logs
fly status        # Machine health
fly volumes list  # List persistent volumes
fly ssh console   # SSH into the running machine
```