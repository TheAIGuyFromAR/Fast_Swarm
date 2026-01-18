"""
Motion Derivatives ML Analysis & Threshold Discovery

Phase 2 of the motion derivatives pipeline:
1. Load computed derivatives from Parquet
2. Run high-signal/low-compute statistical analyses
3. Discover optimal thresholds for coach/agent traits
4. GPU-accelerated ML (XGBoost, clustering) if available
5. Generate coach trait defaults

This script produces the DELIVERABLE: discovered thresholds that become
default values for coaches and agents.

Author: Coinswarm Research
Paper: "Snap, Crackle, Pop: Higher-Order Derivatives as Leading Indicators"
"""

import json
import sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import polars as pl

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Paths
DERIVATIVES_DIR = PROJECT_ROOT / "data" / "derivatives"
OUTPUT_DIR = PROJECT_ROOT / "data" / "analysis"
MODELS_DIR = PROJECT_ROOT / "models"
COACH_TRAITS_OUTPUT = PROJECT_ROOT / "src" / "Fast_Swarm" / "Agents" / "Coaches" / "generated_traits.py"


# =============================================================================
# DATA LOADING
# =============================================================================

def load_derivatives(
    symbols: list[str] | None = None,
    timeframes: list[str] | None = None,
    sample_frac: float | None = None
) -> pl.DataFrame:
    """
    Load derivative data from partitioned Parquet files.

    Args:
        symbols: Filter to specific symbols (None = all)
        timeframes: Filter to specific timeframes (None = all)
        sample_frac: Random sample fraction for faster analysis (None = all)
    """
    if not DERIVATIVES_DIR.exists():
        raise FileNotFoundError(
            f"Derivatives directory not found: {DERIVATIVES_DIR}\n"
            "Run analyze_motion_derivatives.py first!"
        )

    # Build path pattern
    if symbols and timeframes:
        dfs = []
        for sym in symbols:
            for tf in timeframes:
                path = DERIVATIVES_DIR / f"symbol={sym}" / f"timeframe={tf}" / "data.parquet"
                if path.exists():
                    dfs.append(pl.read_parquet(path))
        if not dfs:
            raise FileNotFoundError("No matching parquet files found")
        df = pl.concat(dfs)
    elif symbols:
        dfs = []
        for sym in symbols:
            path = DERIVATIVES_DIR / f"symbol={sym}"
            if path.exists():
                dfs.append(pl.read_parquet(path))
        df = pl.concat(dfs) if dfs else pl.DataFrame()
    elif timeframes:
        # Need to scan all symbols for specific timeframes
        dfs = []
        for sym_dir in DERIVATIVES_DIR.glob("symbol=*"):
            for tf in timeframes:
                path = sym_dir / f"timeframe={tf}" / "data.parquet"
                if path.exists():
                    dfs.append(pl.read_parquet(path))
        df = pl.concat(dfs) if dfs else pl.DataFrame()
    else:
        # Load everything
        df = pl.read_parquet(DERIVATIVES_DIR)

    if sample_frac and 0 < sample_frac < 1:
        df = df.sample(fraction=sample_frac, seed=42)

    return df


def get_derivative_columns(df: pl.DataFrame) -> list[str]:
    """Get all derivative feature columns."""
    deriv_names = ["velocity", "acceleration", "jerk", "snap", "crackle", "pop"]
    return [c for c in df.columns if any(d in c for d in deriv_names)]


def get_zscore_columns(df: pl.DataFrame) -> list[str]:
    """Get all z-score normalized derivative columns."""
    return [c for c in df.columns if "zscore" in c]


# =============================================================================
# HIGH SIGNAL / LOW COMPUTE ANALYSES
# =============================================================================

def correlation_with_future(
    df: pl.DataFrame,
    horizons: list[int] = [1, 5, 10, 30, 60]
) -> dict[int, list[tuple[str, float]]]:
    """
    THE most important analysis: which derivatives predict future price?

    Computes Pearson correlation between each derivative feature and
    future returns at various horizons.
    """
    print("  Computing forward return correlations...")

    # Convert to pandas for easier correlation
    pdf = df.to_pandas()
    deriv_cols = get_derivative_columns(df)

    results = {}
    for horizon in horizons:
        # Future return (percentage)
        pdf[f"future_return_{horizon}"] = pdf["close"].pct_change(horizon).shift(-horizon)

        correlations = {}
        for col in deriv_cols:
            if col in pdf.columns:
                corr = pdf[col].corr(pdf[f"future_return_{horizon}"])
                if pd.notna(corr) and abs(corr) > 0.02:  # Meaningful correlation
                    correlations[col] = corr

        # Sort by absolute correlation
        sorted_corrs = sorted(correlations.items(), key=lambda x: -abs(x[1]))
        results[horizon] = sorted_corrs[:30]  # Top 30

    return results


def quintile_analysis(
    df: pl.DataFrame,
    feature: str,
    horizon: int = 10
) -> dict[str, Any]:
    """
    Classic finance quintile analysis.

    Sorts data by feature value, splits into quintiles, measures
    average forward return per quintile.

    "When RSI jerk is in top 20%, price goes up X% on average"
    """
    pdf = df.select([feature, "close"]).to_pandas().dropna()

    if len(pdf) < 100:
        return {"error": "insufficient data"}

    pdf["future_return"] = pdf["close"].pct_change(horizon).shift(-horizon)
    pdf["quintile"] = pd.qcut(pdf[feature], q=5, labels=[1, 2, 3, 4, 5], duplicates="drop")

    stats = pdf.groupby("quintile")["future_return"].agg(["mean", "std", "count"])

    return {
        "feature": feature,
        "horizon": horizon,
        "quintiles": stats.to_dict(),
        "spread": float(stats.loc[5, "mean"] - stats.loc[1, "mean"]) if 5 in stats.index and 1 in stats.index else None,
    }


def conditional_probabilities(df: pl.DataFrame) -> dict[str, dict]:
    """
    Compute P(price_up | derivative_condition).

    These directly become trading rules:
    "If jerk positive AND accel negative, buy" → P(up) = 0.54
    """
    print("  Computing conditional probabilities...")

    pdf = df.to_pandas()
    pdf["price_up"] = (pdf["close"].shift(-1) > pdf["close"]).astype(int)

    # Define conditions to test
    conditions = []

    # Single derivative conditions
    if "close_jerk" in pdf.columns:
        conditions.extend([
            ("jerk_positive", pdf["close_jerk"] > 0),
            ("jerk_negative", pdf["close_jerk"] < 0),
            ("jerk_extreme_high", pdf["close_jerk"] > pdf["close_jerk"].quantile(0.95)),
            ("jerk_extreme_low", pdf["close_jerk"] < pdf["close_jerk"].quantile(0.05)),
        ])

    if "close_acceleration" in pdf.columns:
        conditions.extend([
            ("accel_positive", pdf["close_acceleration"] > 0),
            ("accel_negative", pdf["close_acceleration"] < 0),
        ])

    # Compound conditions (the interesting ones!)
    if "close_jerk" in pdf.columns and "close_acceleration" in pdf.columns:
        conditions.extend([
            ("jerk_pos_accel_neg", (pdf["close_jerk"] > 0) & (pdf["close_acceleration"] < 0)),
            ("jerk_neg_accel_pos", (pdf["close_jerk"] < 0) & (pdf["close_acceleration"] > 0)),
            ("jerk_accel_same_sign", (pdf["close_jerk"] > 0) == (pdf["close_acceleration"] > 0)),
            ("jerk_accel_opposite", (pdf["close_jerk"] > 0) != (pdf["close_acceleration"] > 0)),
        ])

    if "close_snap" in pdf.columns:
        conditions.append(
            ("high_snap", pdf["close_snap"].abs() > pdf["close_snap"].abs().quantile(0.9))
        )

    # Cross-indicator divergences
    if "close_velocity" in pdf.columns and "rsi_14_velocity" in pdf.columns:
        conditions.append(
            ("price_rsi_divergence", (pdf["close_velocity"] > 0) != (pdf["rsi_14_velocity"] > 0))
        )

    results = {}
    for name, mask in conditions:
        subset = pdf[mask]
        if len(subset) > 50:  # Minimum sample size
            p_up = subset["price_up"].mean()
            results[name] = {
                "count": len(subset),
                "p_up": float(p_up),
                "p_down": float(1 - p_up),
                "edge": float(p_up - 0.5),  # Edge over random
            }

    return results


def zero_crossing_analysis(df: pl.DataFrame, derivative_col: str = "close_jerk") -> dict:
    """
    Analyze what happens when derivatives cross zero (sign flips).

    Zero-crossing of jerk = acceleration peak/trough = potential reversal.
    """
    if derivative_col not in df.columns:
        return {"error": f"Column {derivative_col} not found"}

    pdf = df.select([derivative_col, "close"]).to_pandas().dropna()

    if len(pdf) < 100:
        return {"error": "insufficient data"}

    signs = np.sign(pdf[derivative_col])
    sign_changes = (signs != signs.shift(1)).astype(int)

    # Forward returns after zero-crossings
    cross_indices = sign_changes[sign_changes == 1].index
    forward_returns = []

    for idx in cross_indices:
        loc = pdf.index.get_loc(idx)
        if loc + 10 < len(pdf):
            future_close = pdf.iloc[loc + 10]["close"]
            current_close = pdf.iloc[loc]["close"]
            forward_returns.append((future_close / current_close) - 1)

    return {
        "derivative": derivative_col,
        "cross_rate": float(sign_changes.mean()),
        "avg_crosses_per_100": float(sign_changes.sum() / len(pdf) * 100),
        "avg_forward_return_10": float(np.mean(forward_returns)) if forward_returns else None,
        "std_forward_return_10": float(np.std(forward_returns)) if forward_returns else None,
        "sample_count": len(forward_returns),
    }


def streak_analysis(df: pl.DataFrame, col: str = "close_jerk") -> dict:
    """
    Analyze consecutive streaks of positive/negative derivatives.

    Long streaks = strong momentum
    Short streaks = choppy, mean-reverting
    """
    if col not in df.columns:
        return {"error": f"Column {col} not found"}

    pdf = df.select([col, "close"]).to_pandas().dropna()

    if len(pdf) < 100:
        return {"error": "insufficient data"}

    positive = (pdf[col] > 0).astype(int)

    # Count consecutive positives/negatives
    streak_groups = (positive != positive.shift()).cumsum()
    streaks = positive.groupby(streak_groups).cumsum()

    # Analyze returns after long streaks
    pdf["streak"] = streaks * np.sign(pdf[col])

    long_pos = pdf[pdf["streak"] > 5]
    long_neg = pdf[pdf["streak"] < -5]

    return {
        "derivative": col,
        "mean_streak_length": float(streaks.mean()),
        "max_streak_length": int(streaks.max()),
        "long_positive_count": len(long_pos),
        "long_negative_count": len(long_neg),
        "after_long_pos_return": float(long_pos["close"].pct_change(5).shift(-5).mean()) if len(long_pos) > 10 else None,
        "after_long_neg_return": float(long_neg["close"].pct_change(5).shift(-5).mean()) if len(long_neg) > 10 else None,
    }


def hurst_exponent(series: np.ndarray, max_lag: int = 100) -> float:
    """
    Compute Hurst exponent to determine trending vs mean-reverting.

    H > 0.5 = trending (momentum strategy)
    H < 0.5 = mean-reverting (reversion strategy)
    H = 0.5 = random walk
    """
    if len(series) < max_lag * 2:
        return np.nan

    lags = range(2, min(max_lag, len(series) // 2))
    tau = []

    for lag in lags:
        diff = series[lag:] - series[:-lag]
        std = np.std(diff)
        if std > 0:
            tau.append(std)
        else:
            tau.append(np.nan)

    valid = [(l, t) for l, t in zip(lags, tau) if not np.isnan(t) and t > 0]
    if len(valid) < 10:
        return np.nan

    lags_valid, tau_valid = zip(*valid)
    poly = np.polyfit(np.log(lags_valid), np.log(tau_valid), 1)
    return poly[0]


def analyze_hurst_by_group(df: pl.DataFrame) -> dict:
    """Compute Hurst exponent per symbol/timeframe."""
    print("  Computing Hurst exponents...")

    results = {}

    for symbol in df["symbol"].unique().to_list():
        for timeframe in df["timeframe"].unique().to_list():
            subset = df.filter(
                (pl.col("symbol") == symbol) & (pl.col("timeframe") == timeframe)
            )
            if len(subset) > 200:
                close_values = subset["close"].to_numpy()
                h = hurst_exponent(close_values)
                if not np.isnan(h):
                    strategy = "momentum" if h > 0.55 else "mean_reversion" if h < 0.45 else "neutral"
                    results[f"{symbol}_{timeframe}"] = {
                        "hurst": float(h),
                        "strategy": strategy,
                    }

    return results


def autocorrelation_analysis(df: pl.DataFrame, col: str = "close_jerk", max_lag: int = 20) -> dict:
    """
    Analyze autocorrelation decay to understand signal persistence.

    High autocorr = signal persists, ride momentum
    Fast decay = signal fades, mean-reversion opportunity
    """
    if col not in df.columns:
        return {"error": f"Column {col} not found"}

    pdf = df.select([col]).to_pandas().dropna()

    if len(pdf) < max_lag * 2:
        return {"error": "insufficient data"}

    autocorrs = [pdf[col].autocorr(lag=lag) for lag in range(1, max_lag + 1)]

    # Find half-life (when autocorr drops to 50%)
    half_life = max_lag
    if autocorrs[0] > 0:
        for i, ac in enumerate(autocorrs):
            if ac < autocorrs[0] * 0.5:
                half_life = i + 1
                break

    return {
        "derivative": col,
        "lag_1_autocorr": float(autocorrs[0]) if not np.isnan(autocorrs[0]) else None,
        "lag_5_autocorr": float(autocorrs[4]) if len(autocorrs) > 4 and not np.isnan(autocorrs[4]) else None,
        "half_life": half_life,
        "decay_rate": float((autocorrs[0] - autocorrs[-1]) / max_lag) if not np.isnan(autocorrs[0]) else None,
    }


# =============================================================================
# THRESHOLD DISCOVERY - THE KEY DELIVERABLE
# =============================================================================

def find_optimal_threshold(
    df: pl.DataFrame,
    feature: str,
    target_horizon: int = 10,
    n_thresholds: int = 100
) -> dict:
    """
    Find the threshold value that maximizes predictive edge.

    This is THE function that generates coach trait defaults!
    """
    pdf = df.select([feature, "close"]).to_pandas().dropna()

    if len(pdf) < 1000:
        return {"feature": feature, "error": "insufficient data"}

    # Compute future return
    pdf["future_return"] = pdf["close"].pct_change(target_horizon).shift(-target_horizon)
    pdf = pdf.dropna()

    if len(pdf) < 500:
        return {"feature": feature, "error": "insufficient data after dropna"}

    values = pdf[feature]
    thresholds = np.percentile(values, np.linspace(5, 95, n_thresholds))

    best_threshold = None
    best_edge = 0
    best_above_return = 0
    best_below_return = 0

    for thresh in thresholds:
        above_mask = pdf[feature] > thresh
        below_mask = pdf[feature] <= thresh

        if above_mask.sum() < 50 or below_mask.sum() < 50:
            continue

        above_return = pdf.loc[above_mask, "future_return"].mean()
        below_return = pdf.loc[below_mask, "future_return"].mean()

        edge = above_return - below_return

        if abs(edge) > abs(best_edge):
            best_edge = edge
            best_threshold = thresh
            best_above_return = above_return
            best_below_return = below_return

    if best_threshold is None:
        return {"feature": feature, "error": "no valid threshold found"}

    percentile = float((values < best_threshold).mean() * 100)

    return {
        "feature": feature,
        "optimal_threshold": float(best_threshold),
        "edge": float(best_edge),
        "edge_bps": float(best_edge * 10000),  # Basis points
        "percentile": percentile,
        "direction": "long_above" if best_edge > 0 else "short_above",
        "above_return": float(best_above_return),
        "below_return": float(best_below_return),
        "horizon": target_horizon,
    }


def discover_all_thresholds(df: pl.DataFrame, min_edge_bps: float = 10) -> list[dict]:
    """
    Find optimal thresholds for ALL derivative features.

    Returns sorted list by edge magnitude.
    """
    print("  Discovering optimal thresholds for all features...")

    deriv_cols = get_derivative_columns(df)
    results = []

    for i, col in enumerate(deriv_cols):
        if (i + 1) % 50 == 0:
            print(f"    Processed {i + 1}/{len(deriv_cols)} features...")

        result = find_optimal_threshold(df, col)
        if "error" not in result and abs(result.get("edge_bps", 0)) >= min_edge_bps:
            results.append(result)

    return sorted(results, key=lambda x: -abs(x.get("edge", 0)))


def threshold_stability(
    df: pl.DataFrame,
    feature: str,
    window_size: int = 50000,
    step: int = 10000
) -> dict:
    """
    Check if optimal threshold is STABLE over time.

    Stable thresholds = reliable coach traits
    Drifting thresholds = need adaptive strategy
    """
    pdf = df.select([feature, "close", "time"]).to_pandas().dropna().sort_values("time")

    if len(pdf) < window_size + step:
        return {"feature": feature, "error": "insufficient data for stability analysis"}

    thresholds_over_time = []

    for start in range(0, len(pdf) - window_size, step):
        window = pdf.iloc[start:start + window_size]
        window_df = pl.DataFrame(window)
        result = find_optimal_threshold(window_df, feature)

        if "error" not in result:
            thresholds_over_time.append({
                "start_idx": start,
                "threshold": result["optimal_threshold"],
                "edge": result["edge"],
            })

    if not thresholds_over_time:
        return {"feature": feature, "error": "no valid windows"}

    thresholds = [t["threshold"] for t in thresholds_over_time]
    mean_thresh = np.mean(thresholds)
    std_thresh = np.std(thresholds)

    # Stability score: 1 = perfectly stable, 0 = highly variable
    stability = 1 - (std_thresh / (abs(mean_thresh) + 1e-10))
    stability = max(0, min(1, stability))  # Clamp to [0, 1]

    # Trend: is threshold drifting over time?
    trend = np.polyfit(range(len(thresholds)), thresholds, 1)[0]

    return {
        "feature": feature,
        "mean_threshold": float(mean_thresh),
        "std_threshold": float(std_thresh),
        "stability": float(stability),
        "trend": float(trend),
        "n_windows": len(thresholds_over_time),
    }


def find_compound_rules(df: pl.DataFrame, max_conditions: int = 3) -> list[dict]:
    """
    Find multi-condition trading rules.

    "IF jerk > X AND accel < Y THEN buy" → win_rate, edge

    These become coach decision logic!
    """
    print("  Discovering compound trading rules...")

    # Features to combine
    features = []
    for col in ["close_jerk", "close_acceleration", "close_snap",
                "rsi_14_jerk", "macd_histogram_jerk", "volume_velocity"]:
        if col in df.columns:
            features.append(col)

    if len(features) < 2:
        return []

    pdf = df.select(features + ["close"]).to_pandas().dropna()
    pdf["future_up"] = (pdf["close"].shift(-10) > pdf["close"]).astype(int)
    pdf = pdf.dropna()

    if len(pdf) < 1000:
        return []

    # Find individual optimal thresholds first
    individual = {}
    for f in features:
        result = find_optimal_threshold(df, f)
        if "error" not in result:
            individual[f] = result

    # Test compound rules
    rules = []

    for n in range(2, min(max_conditions + 1, len(individual) + 1)):
        for combo in combinations(individual.keys(), n):
            # Build compound condition
            mask = pd.Series(True, index=pdf.index)
            rule_desc = []

            for feat in combo:
                thresh = individual[feat]["optimal_threshold"]
                direction = individual[feat]["direction"]

                if direction == "long_above":
                    mask &= pdf[feat] > thresh
                    rule_desc.append(f"{feat} > {thresh:.6f}")
                else:
                    mask &= pdf[feat] < thresh
                    rule_desc.append(f"{feat} < {thresh:.6f}")

            if mask.sum() >= 100:  # Minimum sample size
                win_rate = pdf.loc[mask, "future_up"].mean()
                edge = win_rate - 0.5

                rules.append({
                    "rule": " AND ".join(rule_desc),
                    "conditions": len(combo),
                    "features": list(combo),
                    "sample_count": int(mask.sum()),
                    "win_rate": float(win_rate),
                    "edge": float(edge),
                    "edge_pct": float(edge * 100),
                })

    return sorted(rules, key=lambda x: -x["edge"])[:20]


def thresholds_by_timeframe(df: pl.DataFrame) -> dict:
    """
    Find optimal thresholds per timeframe.

    1m jerk threshold likely differs from 1h jerk threshold!
    """
    print("  Analyzing thresholds by timeframe...")

    results = {}

    for tf in df["timeframe"].unique().to_list():
        tf_data = df.filter(pl.col("timeframe") == tf)
        if len(tf_data) > 5000:
            thresh = discover_all_thresholds(tf_data, min_edge_bps=5)
            results[tf] = thresh[:10]  # Top 10 per timeframe

    return results


def thresholds_by_regime(df: pl.DataFrame) -> dict:
    """
    Find thresholds that work in different market regimes.

    Bull market thresholds may fail in bear markets!
    """
    print("  Analyzing thresholds by regime...")

    pdf = df.to_pandas()

    # Simple regime detection: 50-period return
    pdf["return_50"] = pdf["close"].pct_change(50)
    pdf["regime"] = np.where(
        pdf["return_50"] > 0.05, "bull",
        np.where(pdf["return_50"] < -0.05, "bear", "chop")
    )

    results = {}

    for regime in ["bull", "bear", "chop"]:
        regime_data = pdf[pdf["regime"] == regime]
        if len(regime_data) > 5000:
            regime_df = pl.DataFrame(regime_data)
            thresh = discover_all_thresholds(regime_df, min_edge_bps=5)
            results[regime] = thresh[:10]

    return results


# =============================================================================
# COACH TRAIT GENERATION
# =============================================================================

def export_coach_defaults(
    threshold_results: list[dict],
    stability_results: list[dict]
) -> dict:
    """
    Convert analysis results to coach trait defaults.
    """
    coach_defaults = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "n_thresholds_analyzed": len(threshold_results),
            "n_stability_checks": len(stability_results),
        },
        "thresholds": {},
        "confidence": {},
    }

    # Extract thresholds for key derivatives
    key_derivatives = [
        "close_jerk", "close_acceleration", "close_velocity",
        "close_snap", "rsi_14_jerk", "macd_histogram_jerk"
    ]

    for result in threshold_results:
        feat = result.get("feature", "")
        if feat in key_derivatives:
            coach_defaults["thresholds"][feat] = {
                "value": result["optimal_threshold"],
                "direction": result["direction"],
                "edge_bps": result["edge_bps"],
                "percentile": result["percentile"],
            }

    # Add stability confidence
    for stab in stability_results:
        feat = stab.get("feature", "")
        if "error" not in stab:
            coach_defaults["confidence"][feat] = stab["stability"]

    return coach_defaults


def generate_coach_traits_code(coach_defaults: dict, compound_rules: list[dict]) -> str:
    """
    Generate Python code for CoachTraits dataclass.

    This is the DELIVERABLE - discovered thresholds become code!
    """

    # Extract key thresholds
    jerk_thresh = coach_defaults["thresholds"].get("close_jerk", {})
    accel_thresh = coach_defaults["thresholds"].get("close_acceleration", {})

    jerk_value = jerk_thresh.get("value", 0.0)
    jerk_direction = jerk_thresh.get("direction", "long_above")
    jerk_edge = jerk_thresh.get("edge_bps", 0)

    accel_value = accel_thresh.get("value", 0.0)
    accel_direction = accel_thresh.get("direction", "long_above")
    accel_edge = accel_thresh.get("edge_bps", 0)

    jerk_confidence = coach_defaults["confidence"].get("close_jerk", 0.5)
    accel_confidence = coach_defaults["confidence"].get("close_acceleration", 0.5)

    # Best compound rule
    best_rule = compound_rules[0] if compound_rules else {"rule": "N/A", "win_rate": 0.5, "edge": 0}

    code = f'''"""
Coach Trait Defaults - Generated from Motion Derivatives Analysis

Generated: {coach_defaults["metadata"]["generated_at"]}
Dataset: All assets, all timeframes from enhanced_candles
Thresholds analyzed: {coach_defaults["metadata"]["n_thresholds_analyzed"]}

These values are derived from historical analysis and represent
optimal starting points for coach/agent traits.

Paper: "Snap, Crackle, Pop: Higher-Order Derivatives as Leading Indicators"
"""

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class DerivedThresholds:
    """
    Thresholds discovered from motion derivatives analysis.

    These represent the optimal threshold values for each derivative
    that maximize predictive edge over the historical dataset.
    """

    # Jerk threshold (3rd derivative - regime change detection)
    jerk_threshold: float = {jerk_value:.8f}
    jerk_direction: str = "{jerk_direction}"  # "long_above" or "short_above"
    jerk_edge_bps: float = {jerk_edge:.2f}
    jerk_confidence: float = {jerk_confidence:.4f}  # Stability over time (0-1)

    # Acceleration threshold (2nd derivative - momentum)
    accel_threshold: float = {accel_value:.8f}
    accel_direction: str = "{accel_direction}"
    accel_edge_bps: float = {accel_edge:.2f}
    accel_confidence: float = {accel_confidence:.4f}

    # Accel-Jerk divergence weight
    # When accel and jerk have opposite signs, regime change is likely
    accel_jerk_divergence_weight: float = 0.3


@dataclass
class ShortTermCoachTraits:
    """
    Default traits for short-term (intraday) coach archetype.

    Optimized for 1m-15m timeframes.
    """

    # Derivative thresholds
    thresholds: DerivedThresholds = None

    # Position management
    max_position_pct: float = 0.1  # Max 10% of portfolio per position
    stop_loss_atr_mult: float = 2.0
    take_profit_atr_mult: float = 3.0

    # Roster management
    min_agent_elo: int = 1200  # Below this, agent gets benched
    max_roster_size: int = 5

    # Signal requirements
    min_signal_strength: float = 0.6  # Require 60%+ conviction

    def __post_init__(self):
        if self.thresholds is None:
            self.thresholds = DerivedThresholds()


@dataclass
class MediumTermCoachTraits:
    """
    Default traits for medium-term (swing) coach archetype.

    Optimized for 1h-4h timeframes.
    """

    thresholds: DerivedThresholds = None
    max_position_pct: float = 0.15
    stop_loss_atr_mult: float = 2.5
    take_profit_atr_mult: float = 4.0
    min_agent_elo: int = 1250
    max_roster_size: int = 7
    min_signal_strength: float = 0.55

    def __post_init__(self):
        if self.thresholds is None:
            self.thresholds = DerivedThresholds()


@dataclass
class LongTermCoachTraits:
    """
    Default traits for long-term (position) coach archetype.

    Optimized for 4h-1d timeframes.
    """

    thresholds: DerivedThresholds = None
    max_position_pct: float = 0.2
    stop_loss_atr_mult: float = 3.0
    take_profit_atr_mult: float = 5.0
    min_agent_elo: int = 1300
    max_roster_size: int = 10
    min_signal_strength: float = 0.5

    def __post_init__(self):
        if self.thresholds is None:
            self.thresholds = DerivedThresholds()


# Best compound trading rule discovered:
# {best_rule["rule"]}
# Win rate: {best_rule["win_rate"]*100:.1f}%
# Edge: {best_rule["edge"]*100:.2f}%

BEST_COMPOUND_RULE = {{
    "rule": "{best_rule["rule"]}",
    "win_rate": {best_rule["win_rate"]:.4f},
    "edge": {best_rule["edge"]:.4f},
}}


# All discovered thresholds (sorted by edge)
ALL_THRESHOLDS: Dict[str, Dict[str, Any]] = {json.dumps(coach_defaults["thresholds"], indent=4, default=str)}
'''

    return code


# =============================================================================
# GPU-ACCELERATED ANALYSIS (Optional)
# =============================================================================

def try_gpu_analysis(df: pl.DataFrame) -> dict | None:
    """
    Attempt GPU-accelerated ML analysis if RAPIDS is available.

    Falls back gracefully if GPU not available.
    """
    results = {}

    # Try XGBoost first (most likely to be available)
    try:
        import xgboost as xgb

        print("  XGBoost available - running feature importance analysis...")

        pdf = df.to_pandas()

        # Prepare features
        deriv_cols = [c for c in pdf.columns if any(
            d in c for d in ["velocity", "acceleration", "jerk", "snap", "crackle", "pop"]
        ) and "zscore" in c]

        if not deriv_cols:
            deriv_cols = [c for c in pdf.columns if any(
                d in c for d in ["velocity", "acceleration", "jerk", "snap", "crackle", "pop"]
            )]

        if not deriv_cols:
            print("    No derivative columns found for XGBoost")
            return results

        # Target: next-bar direction
        pdf["future_up"] = (pdf["close"].shift(-1) > pdf["close"]).astype(int)
        pdf = pdf.dropna(subset=deriv_cols + ["future_up"])

        if len(pdf) < 1000:
            print("    Insufficient data for XGBoost")
            return results

        X = pdf[deriv_cols].fillna(0)
        y = pdf["future_up"]

        # Try GPU first, fall back to CPU
        try:
            params = {
                "tree_method": "hist",  # Will use GPU if available
                "device": "cuda",
                "objective": "binary:logistic",
                "eval_metric": "auc",
                "max_depth": 6,
                "learning_rate": 0.1,
                "n_estimators": 100,
            }
            dtrain = xgb.DMatrix(X, label=y)
            model = xgb.train(params, dtrain, num_boost_round=100, verbose_eval=False)
            results["xgboost_device"] = "GPU"
        except Exception:
            params = {
                "tree_method": "hist",
                "objective": "binary:logistic",
                "eval_metric": "auc",
                "max_depth": 6,
                "learning_rate": 0.1,
            }
            dtrain = xgb.DMatrix(X, label=y)
            model = xgb.train(params, dtrain, num_boost_round=100, verbose_eval=False)
            results["xgboost_device"] = "CPU"

        # Get feature importance
        importance = model.get_score(importance_type="gain")
        sorted_importance = sorted(importance.items(), key=lambda x: -x[1])

        results["xgboost_top_features"] = [
            {"feature": feat, "importance": float(imp)}
            for feat, imp in sorted_importance[:20]
        ]

        print(f"    XGBoost complete ({results['xgboost_device']})")
        print(f"    Top feature: {sorted_importance[0][0]} (gain: {sorted_importance[0][1]:.2f})")

    except ImportError:
        print("  XGBoost not available - skipping")
    except Exception as e:
        print(f"  XGBoost error: {e}")

    return results if results else None


# =============================================================================
# MAIN ANALYSIS PIPELINE
# =============================================================================

def run_full_analysis(
    symbols: list[str] | None = None,
    timeframes: list[str] | None = None,
    sample_frac: float | None = None,
    skip_gpu: bool = False,
) -> dict:
    """
    Run the complete motion derivatives analysis pipeline.

    This is the main entry point that:
    1. Loads derivative data
    2. Runs statistical analyses
    3. Discovers optimal thresholds
    4. Generates coach trait defaults
    """
    print("=" * 60)
    print("MOTION DERIVATIVES ML ANALYSIS")
    print("Discovering thresholds for coach/agent traits")
    print("=" * 60)
    print()

    # Create output directories
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # Load data
    print("[1/8] Loading derivative data...")
    df = load_derivatives(symbols=symbols, timeframes=timeframes, sample_frac=sample_frac)
    print(f"  Loaded {len(df):,} rows with {len(df.columns)} columns")
    print()

    results = {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rows": len(df),
            "columns": len(df.columns),
            "symbols": df["symbol"].unique().to_list() if "symbol" in df.columns else [],
            "timeframes": df["timeframe"].unique().to_list() if "timeframe" in df.columns else [],
        }
    }

    # Phase 1: Forward return correlations
    print("[2/8] Computing forward return correlations...")
    results["correlations"] = correlation_with_future(df)
    if results["correlations"]:
        top_corr = results["correlations"].get(10, [])
        if top_corr:
            print(f"  Top predictor (10-bar): {top_corr[0][0]} (r={top_corr[0][1]:.4f})")
    print()

    # Phase 2: Conditional probabilities
    print("[3/8] Computing conditional probabilities...")
    results["conditional_probs"] = conditional_probabilities(df)
    best_cond = max(results["conditional_probs"].items(), key=lambda x: abs(x[1].get("edge", 0)), default=None)
    if best_cond:
        print(f"  Best condition: {best_cond[0]} (edge={best_cond[1]['edge']*100:.2f}%)")
    print()

    # Phase 3: Zero-crossing and streak analysis
    print("[4/8] Analyzing derivative patterns...")
    results["zero_crossings"] = {}
    results["streaks"] = {}
    for col in ["close_jerk", "close_acceleration", "rsi_14_jerk"]:
        if col in df.columns:
            results["zero_crossings"][col] = zero_crossing_analysis(df, col)
            results["streaks"][col] = streak_analysis(df, col)
    print()

    # Phase 4: Hurst and autocorrelation
    print("[5/8] Computing Hurst exponents and autocorrelation...")
    results["hurst"] = analyze_hurst_by_group(df)
    results["autocorrelation"] = {}
    for col in ["close_jerk", "close_velocity"]:
        if col in df.columns:
            results["autocorrelation"][col] = autocorrelation_analysis(df, col)
    print()

    # Phase 5: Threshold discovery (THE KEY STEP)
    print("[6/8] Discovering optimal thresholds...")
    results["thresholds"] = discover_all_thresholds(df)
    if results["thresholds"]:
        print(f"  Found {len(results['thresholds'])} thresholds with edge >= 10bps")
        print(f"  Top threshold: {results['thresholds'][0]['feature']}")
        print(f"    Value: {results['thresholds'][0]['optimal_threshold']:.6f}")
        print(f"    Edge: {results['thresholds'][0]['edge_bps']:.1f} bps")
    print()

    # Phase 6: Threshold stability
    print("[7/8] Checking threshold stability over time...")
    results["stability"] = []
    top_features = [t["feature"] for t in results["thresholds"][:10]]
    for feat in top_features:
        stab = threshold_stability(df, feat)
        if "error" not in stab:
            results["stability"].append(stab)
            print(f"  {feat}: stability={stab['stability']:.2f}")
    print()

    # Phase 7: Compound rules
    print("[8/8] Discovering compound trading rules...")
    results["compound_rules"] = find_compound_rules(df)
    if results["compound_rules"]:
        print(f"  Found {len(results['compound_rules'])} compound rules")
        print(f"  Best rule: {results['compound_rules'][0]['rule']}")
        print(f"    Win rate: {results['compound_rules'][0]['win_rate']*100:.1f}%")
    print()

    # Optional: GPU analysis
    if not skip_gpu:
        print("[Bonus] Attempting GPU-accelerated analysis...")
        gpu_results = try_gpu_analysis(df)
        if gpu_results:
            results["gpu_analysis"] = gpu_results
        print()

    # Generate coach defaults
    print("=" * 60)
    print("GENERATING COACH TRAIT DEFAULTS")
    print("=" * 60)

    coach_defaults = export_coach_defaults(results["thresholds"], results["stability"])
    results["coach_defaults"] = coach_defaults

    # Generate Python code
    coach_code = generate_coach_traits_code(coach_defaults, results["compound_rules"])

    # Save everything
    print()
    print("Saving results...")

    # Save JSON results
    results_file = OUTPUT_DIR / "motion_derivatives_analysis.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  Analysis results: {results_file}")

    # Save coach traits code
    COACH_TRAITS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(COACH_TRAITS_OUTPUT, "w") as f:
        f.write(coach_code)
    print(f"  Coach traits code: {COACH_TRAITS_OUTPUT}")

    print()
    print("=" * 60)
    print("ANALYSIS COMPLETE")
    print("=" * 60)

    # Summary
    if results["thresholds"]:
        print()
        print("TOP 5 PREDICTIVE DERIVATIVES:")
        for i, t in enumerate(results["thresholds"][:5], 1):
            print(f"  {i}. {t['feature']}")
            print(f"     Threshold: {t['optimal_threshold']:.6f} ({t['direction']})")
            print(f"     Edge: {t['edge_bps']:.1f} bps")

    if results["compound_rules"]:
        print()
        print("BEST TRADING RULE:")
        rule = results["compound_rules"][0]
        print(f"  {rule['rule']}")
        print(f"  Win rate: {rule['win_rate']*100:.1f}% | Edge: {rule['edge']*100:.2f}%")

    return results


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyze motion derivatives and discover optimal thresholds"
    )
    parser.add_argument(
        "--symbols", "-s",
        nargs="+",
        help="Filter to specific symbols"
    )
    parser.add_argument(
        "--timeframes", "-t",
        nargs="+",
        help="Filter to specific timeframes"
    )
    parser.add_argument(
        "--sample",
        type=float,
        help="Sample fraction for faster analysis (e.g., 0.1 for 10%%)"
    )
    parser.add_argument(
        "--skip-gpu",
        action="store_true",
        help="Skip GPU-accelerated analysis"
    )

    args = parser.parse_args()

    run_full_analysis(
        symbols=args.symbols,
        timeframes=args.timeframes,
        sample_frac=args.sample,
        skip_gpu=args.skip_gpu,
    )
