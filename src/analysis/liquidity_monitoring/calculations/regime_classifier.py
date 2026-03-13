"""
Regime Classifier
Classifies liquidity regime based on layer directions
"""
import pandas as pd
from typing import Tuple, Dict
from config.indicators import REGIME_LABELS


def get_layer_direction(layer_score: float, threshold: float = 0.5) -> int:
    """
    Convert layer score to direction

    Args:
        layer_score: Aggregate layer score
        threshold: Threshold for direction classification

    Returns:
        +1 (positive/expansionary)
         0 (neutral)
        -1 (negative/contractionary)
    """
    if layer_score > threshold:
        return 1
    elif layer_score < -threshold:
        return -1
    return 0


def classify_regime(l1_score: float, l2a_score: float, l2b_score: float,
                    threshold: float = 0.5) -> Dict:
    """
    Classify current liquidity regime based on layer scores

    Args:
        l1_score: Layer 1 (CB Liquidity) score
        l2a_score: Layer 2a (Wholesale) score
        l2b_score: Layer 2b (Economic Reality) score
        threshold: Direction classification threshold

    Returns:
        Dict with regime classification details
    """
    l1_dir = get_layer_direction(l1_score, threshold)
    l2a_dir = get_layer_direction(l2a_score, threshold)
    l2b_dir = get_layer_direction(l2b_score, threshold)

    regime_key = (l1_dir, l2a_dir, l2b_dir)

    # Get regime label from config
    regime_label = REGIME_LABELS.get(regime_key, 'Undefined Regime')

    # Determine overall bias
    total_direction = l1_dir + l2a_dir + l2b_dir
    if total_direction > 0:
        bias = 'Bullish'
    elif total_direction < 0:
        bias = 'Bearish'
    else:
        bias = 'Neutral'

    # Determine color coding
    if total_direction >= 2:
        color = 'green'
    elif total_direction == 1:
        color = 'lightgreen'
    elif total_direction == 0:
        color = 'yellow'
    elif total_direction == -1:
        color = 'orange'
    else:
        color = 'red'

    return {
        'regime': regime_label,
        'regime_key': regime_key,
        'l1_direction': l1_dir,
        'l2a_direction': l2a_dir,
        'l2b_direction': l2b_dir,
        'total_direction': total_direction,
        'bias': bias,
        'color': color,
        'l1_label': _direction_to_label(l1_dir, 'CB'),
        'l2a_label': _direction_to_label(l2a_dir, 'Private'),
        'l2b_label': _direction_to_label(l2b_dir, 'Economy'),
    }


def _direction_to_label(direction: int, layer_name: str) -> str:
    """Convert direction to descriptive label"""
    if direction > 0:
        if layer_name == 'CB':
            return 'Easing'
        elif layer_name == 'Private':
            return 'Expanding'
        else:  # Economy
            return 'Weakening'  # Counterintuitive!
    elif direction < 0:
        if layer_name == 'CB':
            return 'Tightening'
        elif layer_name == 'Private':
            return 'Contracting'
        else:  # Economy
            return 'Overheating'
    else:
        return 'Neutral'


def get_regime_description(regime_key: Tuple[int, int, int]) -> str:
    """
    Get detailed description for a regime

    Args:
        regime_key: (L1, L2a, L2b) direction tuple

    Returns:
        Description string explaining the regime
    """
    descriptions = {
        (1, 1, 1): (
            "Central bank is easing, private sector is expanding, and economy is weak. "
            "This is the most bullish setup - maximum liquidity support with room to run. "
            "Historically leads to strong risk asset performance."
        ),
        (1, 1, -1): (
            "Central bank is easing and private sector expanding, but economy is overheating. "
            "Recovery is underway but inflation may force CB to reconsider. "
            "Late-stage easing cycle - watch for policy pivot."
        ),
        (1, -1, 1): (
            "Central bank is easing but private sector not transmitting. "
            "This indicates transmission mechanism is broken - banks not lending despite CB support. "
            "May require additional policy intervention or structural reforms."
        ),
        (-1, 1, -1): (
            "Central bank is tightening into a strong economy while private sector still expanding. "
            "Classic late-cycle dynamics - economy running hot, CB trying to cool it. "
            "Private sector momentum may persist but watch for credit tightening effects."
        ),
        (-1, -1, 1): (
            "Central bank is tightening and private sector contracting while economy weakens. "
            "Potential policy error - tightening into weakness. "
            "High risk of recession if this persists. Watch for policy pivot signals."
        ),
        (-1, -1, -1): (
            "Maximum contraction across all layers. Economy overheating despite tight policy. "
            "Stagflation risk is elevated. Bearish for risk assets. "
            "This regime typically precedes significant market drawdowns."
        ),
        (0, 0, 0): (
            "All layers neutral - transition period with no clear direction. "
            "Markets may be range-bound. Wait for clearer signals."
        ),
    }

    return descriptions.get(regime_key, "Mixed signals across layers. Monitor for emerging trends.")


def calculate_historical_regimes(layer_scores: pd.DataFrame,
                                  threshold: float = 0.5) -> pd.DataFrame:
    """
    Calculate historical regime classifications

    Args:
        layer_scores: DataFrame with L1, L2a, L2b columns
        threshold: Direction threshold

    Returns:
        DataFrame with regime classifications over time
    """
    results = []

    for date, row in layer_scores.iterrows():
        regime_info = classify_regime(
            row['L1'], row['L2a'], row['L2b'], threshold
        )
        regime_info['Date'] = date
        results.append(regime_info)

    df = pd.DataFrame(results)
    df = df.set_index('Date')

    return df


def get_regime_transitions(regimes: pd.DataFrame) -> pd.DataFrame:
    """
    Identify regime transitions (changes)

    Args:
        regimes: DataFrame from calculate_historical_regimes

    Returns:
        DataFrame with transition dates and from/to regimes
    """
    transitions = []

    prev_regime = None
    for date, row in regimes.iterrows():
        current_regime = row['regime']
        if prev_regime is not None and current_regime != prev_regime:
            transitions.append({
                'date': date,
                'from_regime': prev_regime,
                'to_regime': current_regime,
                'from_bias': regimes.loc[regimes['regime'] == prev_regime, 'bias'].iloc[-1] if len(regimes.loc[regimes['regime'] == prev_regime]) > 0 else 'Unknown',
                'to_bias': row['bias']
            })
        prev_regime = current_regime

    return pd.DataFrame(transitions)


def get_regime_statistics(regimes: pd.DataFrame) -> Dict:
    """
    Calculate statistics about regime durations and frequencies

    Args:
        regimes: DataFrame from calculate_historical_regimes

    Returns:
        Dict with regime statistics
    """
    stats = {
        'current_regime': regimes['regime'].iloc[-1],
        'current_bias': regimes['bias'].iloc[-1],
        'regime_counts': regimes['regime'].value_counts().to_dict(),
        'bias_counts': regimes['bias'].value_counts().to_dict(),
        'avg_direction': regimes['total_direction'].mean(),
    }

    # Calculate current regime duration
    current = regimes['regime'].iloc[-1]
    duration = 0
    for regime in reversed(regimes['regime'].tolist()):
        if regime == current:
            duration += 1
        else:
            break
    stats['current_duration_weeks'] = duration

    return stats
