"""
Transmission Chain Calculations
7-stage liquidity flow from CB impulse to real economy
"""
import pandas as pd
import numpy as np
import logging
from typing import Dict, Optional, Tuple

from config.indicators import (
    LAYER1_INDICATORS, LAYER2A_INDICATORS, LAYER2B_INDICATORS,
    TRANSMISSION_STAGES
)
from calculations.liquidity_indicators import (
    calculate_continuous_layer_scores,
    calculate_continuous_indicator_score,
    calculate_roc_4w, calculate_roc_12m,
    calculate_rolling_zscore
)

logger = logging.getLogger(__name__)


def _detect_zscore_window(series):
    """Detect appropriate Z-score window based on frequency"""
    if len(series) > 50:
        avg_gap = (series.index[-1] - series.index[0]).days / len(series)
        if avg_gap > 15:
            return 60
        elif avg_gap > 4:
            return 260
    return 1260


def calculate_stage_scores(raw_data: pd.DataFrame) -> Dict[int, pd.Series]:
    """
    Calculate Z-score time series for each of the 7 transmission stages.

    Returns:
        Dict mapping stage number to Z-score time series (mean of stage indicators)
    """
    # Pre-calculate all layer Z-scores
    l1_scores = calculate_continuous_layer_scores(raw_data, LAYER1_INDICATORS)
    l2a_scores = calculate_continuous_layer_scores(raw_data, LAYER2A_INDICATORS)
    l2b_scores = calculate_continuous_layer_scores(raw_data, LAYER2B_INDICATORS)

    all_layer_scores = {}
    for col in l1_scores.columns:
        all_layer_scores[col] = l1_scores[col]
    for col in l2a_scores.columns:
        all_layer_scores[col] = l2a_scores[col]
    for col in l2b_scores.columns:
        all_layer_scores[col] = l2b_scores[col]

    stage_results = {}

    for stage_num, stage_config in TRANSMISSION_STAGES.items():
        stage_indicator_series = []

        for ind_id, ind_config in stage_config['indicators'].items():
            series = None

            if 'source' in ind_config:
                # Pull from pre-calculated layer scores
                source_id = ind_id
                # Handle capacity_util_hot -> capacity_util mapping
                if source_id == 'capacity_util_hot':
                    source_id = 'capacity_util'

                if source_id in all_layer_scores:
                    series = all_layer_scores[source_id].copy()
                    # Stage 6 inverts L2b indicators (L2b is counterintuitive,
                    # but in stage 6 we want strong economy = positive)
                    if ind_config.get('invert_for_stage', False):
                        series = -series
            else:
                # Calculate from raw FRED data
                fred_code = ind_config.get('fred_code')
                if fred_code and fred_code in raw_data.columns:
                    raw_series = raw_data[fred_code].dropna()
                    if len(raw_series) >= 50:
                        # Apply EMA smoothing to noisy series before ROC
                        signal_type = ind_config.get('signal_type', 'roc_12m')
                        if signal_type == 'roc_4w':
                            # TGA, RRP etc. are very noisy — smooth with 8-period EMA first
                            raw_series = raw_series.ewm(span=8, adjust=False).mean()
                        fake_config = {
                            'signal_type': signal_type,
                            'invert': ind_config.get('invert', False)
                        }
                        series = calculate_continuous_indicator_score(raw_series, fake_config)

            if series is not None and not series.empty:
                stage_indicator_series.append(series)

        if stage_indicator_series:
            # Combine into DataFrame and take mean
            combined = pd.DataFrame({f'ind_{i}': s for i, s in enumerate(stage_indicator_series)})
            combined = combined.ffill()
            stage_mean = combined.mean(axis=1, skipna=True)
            # Apply 4-week EMA to smooth the stage composite
            stage_results[stage_num] = stage_mean.ewm(span=4, adjust=False).mean()

    return stage_results


def calculate_stage_current(raw_data: pd.DataFrame) -> Dict[int, dict]:
    """
    Calculate current stage scores with metadata.

    Returns:
        Dict mapping stage number to dict with:
        - score: float (latest Z-score)
        - status: 'positive' | 'neutral' | 'negative'
        - name: stage name
        - question: stage question
    """
    stage_series = calculate_stage_scores(raw_data)
    results = {}

    for stage_num, stage_config in TRANSMISSION_STAGES.items():
        score = np.nan
        if stage_num in stage_series:
            s = stage_series[stage_num].dropna()
            if not s.empty:
                score = s.iloc[-1]

        if np.isnan(score):
            status = 'neutral'
        elif score > 0.3:
            status = 'positive'
        elif score < -0.3:
            status = 'negative'
        else:
            status = 'neutral'

        results[stage_num] = {
            'score': score,
            'status': status,
            'name': stage_config['name'],
            'question': stage_config['question'],
        }

    return results


def detect_transmission_break(stage_scores: Dict[int, dict]) -> Tuple[Optional[int], str]:
    """
    Find the first stage where signal turns negative after a positive upstream stage.

    Returns:
        (break_stage, regime_label)
        break_stage is None if no break detected
    """
    scores = {k: v['score'] for k, v in stage_scores.items() if not np.isnan(v['score'])}

    if not scores:
        return None, 'No Data'

    # Check if Stage 1 is negative (no impulse to transmit)
    if scores.get(1, 0) < -0.3:
        return None, 'No CB Impulse'

    # Find first break
    prev_positive = False
    for stage in range(1, 8):
        if stage not in scores:
            continue
        if scores[stage] > 0.3:
            prev_positive = True
        elif prev_positive and scores[stage] < -0.3:
            return stage, _get_break_label(stage)

    # No break found - determine how far transmission has reached
    last_positive = 0
    for stage in range(1, 8):
        if stage in scores and scores[stage] > 0.3:
            last_positive = stage

    return None, _get_flow_label(last_positive, scores)


def _get_break_label(break_stage: int) -> str:
    """Get descriptive label for a transmission break"""
    labels = {
        2: 'Trapped Liquidity - QE not transmitting',
        3: 'Wholesale active, risk appetite absent',
        4: 'Spreads tight, banks not lending',
        5: 'Credit flowing, assets not responding',
        6: 'Assets repricing, real economy not responding',
        7: 'Cycle peak - reversal risk building',
    }
    return labels.get(break_stage, f'Break at Stage {break_stage}')


def _get_flow_label(last_positive: int, scores: dict) -> str:
    """Get descriptive label for transmission flow"""
    # Check for fragile rally (Stage 5 green but 2-4 red)
    if scores.get(5, 0) > 0.3:
        if any(scores.get(s, 0) < -0.3 for s in [2, 3, 4]):
            return 'Asset rally without transmission - FRAGILE'

    labels = {
        0: 'No positive stages',
        1: 'Impulse only - waiting for transmission',
        2: 'Early - impulse created, transmission starting',
        3: 'Mid cycle - risk appetite returning',
        4: 'Mid cycle - credit expanding',
        5: 'Late mid - assets pricing in',
        6: 'Late cycle - fully transmitted, watch Stage 7',
        7: 'Cycle peak - reversal risk building',
    }
    return labels.get(last_positive, 'Unknown')


CYCLE_COLORS = {
    'Early - impulse created, transmission starting': 'blue',
    'Mid cycle - risk appetite returning': 'green',
    'Mid cycle - credit expanding': 'green',
    'Late mid - assets pricing in': 'yellow',
    'Late cycle - fully transmitted, watch Stage 7': 'orange',
    'Cycle peak - reversal risk building': 'red',
    'Trapped Liquidity - QE not transmitting': 'red',
    'Wholesale active, risk appetite absent': 'red',
    'Spreads tight, banks not lending': 'red',
    'Asset rally without transmission - FRAGILE': 'red',
    'No CB Impulse': 'gray',
    'No positive stages': 'gray',
    'Impulse only - waiting for transmission': 'blue',
}
