# Anomaly Detector: Decision Process

## Overview

The detector scores each plant/country/habitat combination on a scale from 0 to 1, where 0 is maximally suspicious and 1 is completely normal. It combines two parallel signals: a machine learning model (IsolationForest) that catches statistical outliers, and a hand-crafted plausibility score that directly penalises geographic impossibilities.

---

## Step 1: Extract the Genus

The scientific name is split on whitespace and the first word is taken as the genus. So `Opuntia humifusa` becomes `Opuntia`. This matters because genus is a broader category than species, so "has this genus ever been seen in this country/habitat" is a more robust signal than "has this exact species been seen there."

---

## Step 2: Look Up Frequency Counts

For the entry being scored, the model looks up five counts from tables built at training time:

- How many times this genus appears in this country across the whole dataset.
- How many times this exact species appears in this country.
- How many times this genus appears in this habitat type globally.
- How many times this exact species appears in this habitat type globally.
- How many times this habitat type appears in this country at all.

If a combination has never been seen, the count is zero. These counts are then log-scaled with `log1p` so that the difference between 1 and 10 occurrences matters more than the difference between 1000 and 1010.

---

## Step 3: Compute the Two Fraction Features

This is the most important step for catching geographic nonsense.

**`hab_frac_in_country`** is the number of entries with this habitat in this country, divided by the total number of entries for that country. If Norway has 31 flora entries and zero of them are desert, this fraction is exactly `0.0`. This directly encodes "does this habitat even exist in this country according to the dataset."

**`genus_frac_in_habitat`** is how many of all entries in this habitat globally belong to this genus, divided by the total entries in that habitat. A cactus genus in a tundra habitat would be near zero here even if the cactus is well-represented elsewhere.

---

## Step 4: IsolationForest Scoring

The IsolationForest takes all the log-scaled counts, the two fractions, the label-encoded country and habitat, and a few other features as a feature vector. It scores the entry by how easy it is to isolate with random cuts through the feature space:

- Entries that sit in a dense normal region need many cuts to isolate and receive a higher score.
- Entries that are statistical outliers get isolated quickly and receive a lower score.

This catches within-distribution weirdness, like a species appearing in an unusual number of countries, or a genus that is very rare in a habitat where it does technically exist.

---

## Step 5: Plausibility Scoring

This is a separate hand-crafted score that runs in parallel to the IsolationForest. It directly penalises the zero-frequency cases that IsolationForest struggles with, because IsolationForest was only trained on entries that exist in the dataset and cannot reliably distinguish "unseen combo" from "rare but valid."

The formula combines three terms:

| Term | Weight | What it captures |
|---|---|---|
| `hab_frac * 10`, clipped to 1 | 0.5 | How common this habitat is in this country |
| `genus_hab_frac * 5`, clipped to 1 | 0.4 | How typical this genus is for this habitat globally |
| Genus seen in country before (0 or 1) | 0.1 | Small bonus if the genus has any presence in this country |

A desert plant in Norway gets `hab_frac = 0.0`, which drives this score to near zero immediately regardless of what IsolationForest thinks.

---

## Step 6: Combine into a Final Score

```
final_score = 0.4 * IsolationForest_normalised + 0.6 * plausibility
```

The IsolationForest score is first normalised to 0-1 using the min/max seen during training. Then the two are blended, with plausibility weighted higher because it directly captures the geographic signal. The result is a single number between 0 and 1.

---

## Step 7: Threshold Decision

The final score is compared against a threshold set at the **5th percentile** of all training scores. Anything below it is flagged as an anomaly. The 5% figure is the `contamination` parameter, meaning the model is calibrated to expect roughly 5% of entries to be suspicious. This can be raised or lowered to make the detector more or less aggressive.

---

## Step 8: Low-Support Check

Before any of the above scoring happens, the habitat is checked against a list of habitats that had fewer than **30 entries** in the training data. If it matches, the entry skips scoring entirely and returns `INSUFFICIENT DATA` instead, because the model has no meaningful basis for what normal looks like in that habitat. Tundra is currently the only habitat that triggers this, with 6 entries in the dataset.

---

## Summary

```
Input: scientific_name, country, habitat
        |
        v
Low-support habitat? --> INSUFFICIENT DATA
        |
        v
Look up frequency counts + compute fractions
        |
        +---> IsolationForest score (statistical outlier detection)
        |
        +---> Plausibility score (geographic/habitat fitness)
        |
        v
final_score = 0.4 * IF + 0.6 * plausibility
        |
        v
final_score < threshold? --> ANOMALY
                         --> NORMAL
```
