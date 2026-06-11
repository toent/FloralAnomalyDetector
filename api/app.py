import pickle
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from api.model_utils import check_entry
from api.geo_utils import resolve_coordinates

MODEL_PATH = 'Floral-Anomaly-Detector.pkl'

bundle = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the model bundle once on startup, stays in memory for all requests.
    with open(MODEL_PATH, 'rb') as f:
        loaded = pickle.load(f)
    bundle.update(loaded)
    print(f"Model loaded from {MODEL_PATH}")
    yield
    bundle.clear()


app = FastAPI(
    title='Floral Anomaly Detector',
    description='Detects suspicious plant/country/habitat combinations.',
    version='1.0.0',
    lifespan=lifespan,
)


class PredictRequest(BaseModel):
    scientific_name: str
    country: str
    habitat: str


class PredictResponse(BaseModel):
    scientific_name: str
    country: str
    habitat: str
    final_score: float
    plausibility: float
    if_score: float
    hab_frac_country: float
    verdict: str


class CoordinateRequest(BaseModel):
    scientific_name: str
    lat: float
    lon: float


class CoordinateResponse(BaseModel):
    scientific_name: str
    lat: float
    lon: float
    resolved_country: str | None
    resolved_habitat: str | None
    esa_class: int | None
    final_score: float | None
    plausibility: float | None
    if_score: float | None
    hab_frac_country: float | None
    verdict: str


def _insufficient_data_response(field: str, value: str) -> dict:
    return {
        'final_score':      None,
        'plausibility':     None,
        'if_score':         None,
        'hab_frac_country': None,
        'verdict':          f'INSUFFICIENT DATA: {field} "{value}" could not be resolved.',
    }


@app.get('/health')
def health():
    return {'status': 'ok', 'model_loaded': len(bundle) > 0}


@app.post('/predict', response_model=PredictResponse)
def predict(request: PredictRequest):
    if not bundle:
        raise HTTPException(status_code=503, detail='Model not loaded.')

    if not request.scientific_name.strip():
        raise HTTPException(status_code=422, detail='scientific_name cannot be empty.')
    if not request.country.strip():
        raise HTTPException(status_code=422, detail='country cannot be empty.')
    if not request.habitat.strip():
        raise HTTPException(status_code=422, detail='habitat cannot be empty.')

    result = check_entry(
        request.scientific_name,
        request.country,
        request.habitat,
        bundle,
    )
    return result


@app.post('/predict/from_coordinates', response_model=CoordinateResponse)
def predict_from_coordinates(request: CoordinateRequest):
    if not bundle:
        raise HTTPException(status_code=503, detail='Model not loaded.')

    if not (-90 <= request.lat <= 90):
        raise HTTPException(status_code=422, detail='lat must be between -90 and 90.')
    if not (-180 <= request.lon <= 180):
        raise HTTPException(status_code=422, detail='lon must be between -180 and 180.')

    geo = resolve_coordinates(request.lat, request.lon)
    country = geo['country']
    habitat = geo['habitat']
    esa_class = geo['esa_class']

    base = {
        'scientific_name': request.scientific_name,
        'lat':             request.lat,
        'lon':             request.lon,
        'resolved_country': country,
        'resolved_habitat': habitat,
        'esa_class':        esa_class,
    }

    if country is None:
        return CoordinateResponse(
            **base,
            **_insufficient_data_response('country', f'coords ({request.lat}, {request.lon})'),
        )

    if habitat is None:
        esa_label = f'ESA class {esa_class}' if esa_class is not None else 'unknown ESA class'
        return CoordinateResponse(
            **base,
            **_insufficient_data_response('habitat', esa_label),
        )

    result = check_entry(request.scientific_name, country, habitat, bundle)

    return CoordinateResponse(
        **base,
        **{k: result[k] for k in ['final_score', 'plausibility', 'if_score', 'hab_frac_country', 'verdict']},
    )


@app.post('/predict/batch', response_model=list[PredictResponse])
def predict_batch(requests: list[PredictRequest]):
    if not bundle:
        raise HTTPException(status_code=503, detail='Model not loaded.')
    if len(requests) > 500:
        raise HTTPException(status_code=422, detail='Batch size cannot exceed 500 entries.')

    return [
        check_entry(r.scientific_name, r.country, r.habitat, bundle)
        for r in requests
    ]
