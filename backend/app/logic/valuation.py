"""
valuation.py — computes the as-is range from size-adjusted comps.

BLIND RULE: the as-is range is COMPUTED here from fetched comps and AVMs.
It must never be loaded from validation/.

Algorithm (v2 — WLS with Gaussian size-band weights):
  1. Weight each comp by proximity to subject sqft using a Gaussian kernel.
     bandwidth = max(150, 0.10 * subject_sqft).
     Newer-build comps get an additional 0.5x penalty.
  2. Fit WLS: price_per_sqft = a + b*sqft using weighted OLS.
  3. Predict ppsf at subject sqft -> size-adjusted midpoint.
  4. Spread = max(weighted sigma x sqft, $5k). Round to $100.
  5. AVM average shown alongside as reference only; not blended.
  6. If comp-derived mid and AVM avg diverge >8%, widen range and
     lower confidence by 0.10.

Bandwidth choice: max(150, 0.10 * sqft) — proportional rule that
generalizes across house sizes. Comps >200 sqft away lose influence
rapidly; closest-size comps dominate without hard cutoffs.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional


def _wls(xs: List[float], ys: List[float], ws: List[float]):
    """
    Weighted least squares: fit y = a + b*x.
    Returns (a, b, weighted_mean_x, weighted_mean_y, sum_weights).
    """
    if len(xs) < 2:
        raise ValueError("Need at least 2 comps for regression.")
    sw   = sum(ws)
    mx   = sum(w * x for w, x in zip(ws, xs)) / sw
    my   = sum(w * y for w, y in zip(ws, ys)) / sw
    num  = sum(ws[i] * (xs[i] - mx) * (ys[i] - my) for i in range(len(xs)))
    den  = sum(ws[i] * (xs[i] - mx) ** 2 for i in range(len(xs)))
    if den == 0:
        raise ValueError("All comps have the same sqft; cannot fit regression.")
    b = num / den
    a = my - b * mx
    return a, b, mx, my, sw


def _weighted_sigma(xs, ys, ws, a, b) -> float:
    """Weighted residual sigma (ppsf units)."""
    sw = sum(ws)
    n  = len(xs)
    if n < 3:
        return 0.0
    wss = sum(ws[i] * (ys[i] - (a + b * xs[i])) ** 2 for i in range(n))
    return math.sqrt(wss / (sw * (n - 2) / n))


def _comp_weights(comps: list, subject_sqft: float) -> List[float]:
    """
    Gaussian size-proximity weight x newer-build penalty.
    bandwidth = max(150, 10% of subject sqft).
    Proportional rule generalizes across house sizes; comps >200 sqft away
    lose influence rapidly so closest-size comps dominate.
    """
    bw = max(150.0, 0.10 * subject_sqft)
    weights = []
    for c in comps:
        dist = float(c["sqft"]) - subject_sqft
        size_w = math.exp(-0.5 * (dist / bw) ** 2)
        newer_penalty = 0.5 if "note" in c else 1.0
        weights.append(size_w * newer_penalty)
    return weights


def compute_as_is_range(property_inputs: dict) -> dict:
    """
    Compute the as-is valuation range from fetched comps and AVMs.

    Returns:
      low, mid, high, avm_avg (reference only), ppsf_predicted,
      confidence, note, comp_detail (per-comp debug dict), regression dict.
    """
    county       = property_inputs["public_county_facts"]
    avms         = property_inputs["fetched_avms"]
    comps        = property_inputs["fetched_comps"]
    subject_sqft = float(county["sqft"])

    avm_values = [v for v in avms.values() if isinstance(v, (int, float))]
    avm_avg = sum(avm_values) / len(avm_values) if avm_values else None

    xs = [float(c["sqft"])                          for c in comps]
    ys = [float(c["price"]) / float(c["sqft"])      for c in comps]
    ws = _comp_weights(comps, subject_sqft)

    a, b, mx_w, my_w, sw = _wls(xs, ys, ws)

    ppsf_pred = a + b * subject_sqft
    mid = round(ppsf_pred * subject_sqft, -2)

    sigma_ppsf = _weighted_sigma(xs, ys, ws, a, b)
    spread = max(sigma_ppsf * subject_sqft, 5_000)
    spread = round(spread, -2)

    low  = round(mid - spread, -2)
    high = round(mid + spread, -2)

    confidence = 0.75
    notes: List[str] = []

    if avm_avg is not None:
        divergence = abs(mid - avm_avg) / avm_avg
        if divergence > 0.08:
            extra  = round((divergence - 0.08) * avm_avg, -2)
            low    = round(low  - extra, -2)
            high   = round(high + extra, -2)
            confidence -= 0.10
            notes.append(
                f"Comp mid (${mid:,.0f}) and AVM avg (${avm_avg:,.0f}) "
                f"diverge {divergence:.1%}; range widened."
            )

    notes.append("MLS-only metrics (precise DOM, sale-to-list) unavailable in v1.")
    if any("note" in c for c in comps):
        notes.append("One or more comps down-weighted as newer or atypical build.")

    Sxx_w = sum(ws[i] * (xs[i] - mx_w) ** 2 for i in range(len(xs)))
    comp_detail = []
    for i, c in enumerate(comps):
        pred_ppsf = a + b * xs[i]
        resid     = ys[i] - pred_ppsf
        hat = ws[i] * (xs[i] - mx_w) ** 2 / Sxx_w + ws[i] / sw if Sxx_w > 0 else 0
        comp_detail.append({
            "address":       c.get("address", f"comp{i+1}"),
            "sqft":          xs[i],
            "price":         float(c["price"]),
            "actual_ppsf":   round(ys[i], 2),
            "pred_ppsf":     round(pred_ppsf, 2),
            "residual_ppsf": round(resid, 4),
            "residual_$":    round(resid * xs[i], 0),
            "weight":        round(ws[i], 4),
            "leverage":      round(hat, 4),
            "note":          c.get("note", ""),
            "sold":          c.get("sold", ""),
        })

    bw_used = max(150.0, 0.10 * subject_sqft)

    return {
        "low":            float(low),
        "mid":            float(mid),
        "high":           float(high),
        "avm_avg":        float(avm_avg) if avm_avg is not None else None,
        "ppsf_predicted": round(ppsf_pred, 2),
        "confidence":     round(confidence, 2),
        "note":           " ".join(notes),
        "comp_detail":    comp_detail,
        "regression":     {
            "a":                    round(a, 4),
            "b":                    round(b, 6),
            "bandwidth":            round(bw_used, 0),
            "weighted_mean_sqft":   round(mx_w, 0),
        },
    }
