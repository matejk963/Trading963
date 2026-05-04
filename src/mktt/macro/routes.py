"""Flask routes for the Macro section (Liquidity + RRG)."""
from flask import render_template, request, jsonify
from . import macro_bp


@macro_bp.route('/')
def macro_page():
    return section_page('liquidity')


@macro_bp.route('/<section>')
def section_page(section):
    if section == 'liquidity':
        view = request.args.get('view', 'liquidity')
        return render_template('liquidity.html', active_section='liquidity', active_view=view)
    elif section == 'rrg':
        return render_template('rrg.html', active_section='rrg')
    else:
        return section_page('liquidity')


# =========================================================================
# Liquidity API endpoints
# =========================================================================

@macro_bp.route('/api/liquidity')
def api_liquidity():
    try:
        from .liquidity_service import build_dashboard_response
        return jsonify(build_dashboard_response())
    except Exception as e:
        return jsonify({'error': str(e)})


@macro_bp.route('/api/layer/<layer_id>')
def api_layer(layer_id):
    try:
        from .liquidity_service import build_layer_detail_response
        return jsonify(build_layer_detail_response(layer_id))
    except Exception as e:
        return jsonify({'error': str(e)})


@macro_bp.route('/api/overlay')
def api_overlay():
    asset = request.args.get('asset', 'SPY')
    try:
        from .liquidity_service import build_overlay_response
        return jsonify(build_overlay_response(asset))
    except Exception as e:
        return jsonify({'error': str(e)})


@macro_bp.route('/api/transmission')
def api_transmission():
    try:
        from .liquidity_service import build_transmission_response
        return jsonify(build_transmission_response())
    except Exception as e:
        return jsonify({'error': str(e)})


# =========================================================================
# RRG API endpoints
# =========================================================================

@macro_bp.route('/api/rrg')
def api_rrg():
    dataset = request.args.get('dataset', 'us')
    period = request.args.get('period', '2y')
    window = request.args.get('window', '13')
    trail = request.args.get('trail', '8')
    try:
        from .rrg_service import build_rrg_response
        return jsonify(build_rrg_response(dataset, period, window, trail))
    except Exception as e:
        return jsonify({'error': str(e)})


@macro_bp.route('/api/rrg/drill')
def api_rrg_drill():
    group = request.args.get('group', 'Energy')
    period = request.args.get('period', '2y')
    window = request.args.get('window', '13')
    trail = request.args.get('trail', '8')
    try:
        from .rrg_service import build_rrg_drill_response
        return jsonify(build_rrg_drill_response(group, period, window, trail))
    except Exception as e:
        return jsonify({'error': str(e)})
