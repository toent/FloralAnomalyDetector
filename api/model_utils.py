import numpy as np
import pandas as pd


def compute_plausibility(hab_frac, genus_hab_frac, genus_country_seen):
    hab_score       = np.clip(hab_frac * 10, 0, 1)
    genus_hab_score = np.clip(genus_hab_frac * 5, 0, 1)
    gc_bonus        = 0.1 * genus_country_seen
    return float(np.clip((hab_score * 0.5 + genus_hab_score * 0.4 + gc_bonus) / 1.1, 0, 1))


def check_entry(scientific_name: str, country: str, habitat: str, bundle: dict) -> dict:
    iforest                  = bundle['iforest']
    IF_MIN                   = bundle['IF_MIN']
    IF_MAX                   = bundle['IF_MAX']
    THRESHOLD                = bundle['THRESHOLD']
    le_country               = bundle['le_country']
    le_habitat               = bundle['le_habitat']
    genus_country_freq       = bundle['genus_country_freq']
    species_country_freq     = bundle['species_country_freq']
    species_total_countries  = bundle['species_total_countries']
    genus_total_countries    = bundle['genus_total_countries']
    hab_country_freq         = bundle['hab_country_freq']
    genus_habitat_freq       = bundle['genus_habitat_freq']
    species_habitat_freq     = bundle['species_habitat_freq']
    country_total            = bundle['country_total']
    habitat_total            = bundle['habitat_total']
    country_habitat_diversity = bundle['country_habitat_diversity']
    low_support_habitats     = bundle['low_support_habitats']

    genus            = scientific_name.split()[0]
    primary_habitat  = habitat.split(';')[0].strip()

    gc_v  = genus_country_freq.query('genus==@genus and country==@country')['genus_country_freq']
    sc_v  = species_country_freq.query('scientific_name==@scientific_name and country==@country')['species_country_freq']
    stc_v = species_total_countries.query('scientific_name==@scientific_name')['species_total_countries']
    gtc_v = genus_total_countries.query('genus==@genus')['genus_total_countries']
    hc_v  = hab_country_freq.query('primary_habitat==@primary_habitat and country==@country')['hab_country_freq']
    gh_v  = genus_habitat_freq.query('genus==@genus and primary_habitat==@primary_habitat')['genus_habitat_freq']
    sh_v  = species_habitat_freq.query('scientific_name==@scientific_name and primary_habitat==@primary_habitat')['species_habitat_freq']
    ct_v  = country_total.query('country==@country')['country_total_entries']
    ht_v  = habitat_total.query('primary_habitat==@primary_habitat')['habitat_total_entries']
    cd_v  = country_habitat_diversity.query('country==@country')['country_habitat_diversity']

    gc  = float(gc_v.values[0])  if len(gc_v)  else 0.0
    sc  = float(sc_v.values[0])  if len(sc_v)  else 0.0
    stc = float(stc_v.values[0]) if len(stc_v) else 1.0
    gtc = float(gtc_v.values[0]) if len(gtc_v) else 1.0
    hc  = float(hc_v.values[0])  if len(hc_v)  else 0.0
    gh  = float(gh_v.values[0])  if len(gh_v)  else 0.0
    sh  = float(sh_v.values[0])  if len(sh_v)  else 0.0
    ct  = float(ct_v.values[0])  if len(ct_v)  else 1.0
    ht  = float(ht_v.values[0])  if len(ht_v)  else 1.0
    cd  = float(cd_v.values[0])  if len(cd_v)  else 1.0

    try:
        c_enc = int(le_country.transform([country])[0])
    except ValueError:
        c_enc = 0
    try:
        h_enc = int(le_habitat.transform([primary_habitat])[0])
    except ValueError:
        h_enc = 0

    hab_frac   = hc / ct
    genus_frac = gh / ht

    row = pd.DataFrame([{
        'log_genus_country_freq':    np.log1p(gc),
        'log_species_country_freq':  np.log1p(sc),
        'log_hab_country_freq':      np.log1p(hc),
        'log_genus_habitat_freq':    np.log1p(gh),
        'log_species_habitat_freq':  np.log1p(sh),
        'log_country_total_entries': np.log1p(ct),
        'hab_frac_in_country':       hab_frac,
        'genus_frac_in_habitat':     genus_frac,
        'country_habitat_diversity': cd,
        'species_total_countries':   stc,
        'genus_total_countries':     gtc,
        'country_enc':               c_enc,
        'habitat_enc':               h_enc,
    }])

    if_s  = float(iforest.decision_function(row)[0])
    if_n  = (if_s - IF_MIN) / (IF_MAX - IF_MIN)
    plaus = compute_plausibility(hab_frac, genus_frac, float(gc > 0))
    final = 0.4 * if_n + 0.6 * plaus

    if primary_habitat in low_support_habitats:
        verdict = 'INSUFFICIENT DATA: habitat too rare in dataset to score reliably'
    elif final < THRESHOLD:
        verdict = 'ANOMALY: suspicious entry'
    else:
        verdict = 'NORMAL: plausible entry'

    return {
        'scientific_name':  scientific_name,
        'country':          country,
        'habitat':          habitat,
        'final_score':      round(final, 4),
        'plausibility':     round(plaus, 4),
        'if_score':         round(if_s, 4),
        'hab_frac_country': round(hab_frac, 4),
        'verdict':          verdict,
    }
