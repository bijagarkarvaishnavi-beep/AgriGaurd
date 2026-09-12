import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest
import engine

SEED = [[51.505, -0.09], [51.51, -0.08], [51.508, -0.06], [51.502, -0.065]]
SQUARE = [[0.0, 0.0], [0.0, 0.01], [0.01, 0.01], [0.01, 0.0]]


def test_geodesic_hectares_of_known_square():
    # 0.01° x 0.01° at the equator ≈ 1.1057 km x 1.1132 km ≈ 123.1 ha
    assert engine.hectares(SQUARE) == pytest.approx(123.1, abs=0.2)
    assert engine.acres(100) == 247.1
    assert engine.hectares([[0, 0], [0, 0.00001], [0.00001, 0.00001]]) == 0.01


def test_polygon_validation():
    assert engine.polygon_problem(SEED) is None
    assert 'three' in engine.polygon_problem([[0, 0], [1, 1]])
    assert 'WGS84' in engine.polygon_problem([[95, 0], [0, 1], [1, 1]])
    assert 'invalid' in engine.polygon_problem([[0, 0], [1, 1], [1, 0], [0, 1]])  # bow-tie self-intersection


@pytest.mark.parametrize('flooded,total,expected', [(0, 100, 0.0), (65, 100, 65.0), (33.333, 100, 33.3), (150, 100, 100.0), (5, 0, 0.0)])
def test_flood_percent(flooded, total, expected):
    assert engine.flood_percent(flooded, total) == expected


@pytest.mark.parametrize('pct,expected', [(0, 'LOW'), (19.9, 'LOW'), (20, 'MEDIUM'), (49.9, 'MEDIUM'), (50, 'HIGH'), (100, 'HIGH')])
def test_severity_thresholds(pct, expected):
    assert engine.severity(pct) == expected


def test_demo_flood_is_deterministic_partial_overlap():
    flooded, pct = engine.demo_flood(SEED)
    assert engine.demo_flood(SEED) == (flooded, pct)
    assert 0 < flooded < engine.hectares(SEED)
    assert 40 <= pct <= 70
    assert engine.severity(pct) == 'HIGH'
    _, square_pct = engine.demo_flood(SQUARE)
    assert square_pct == pytest.approx(55.0, abs=0.5)


@pytest.mark.parametrize('moisture,rain,condition,risk', [(78, 38, 'Saturated', 'HIGH'), (70, 20, 'Saturated', 'HIGH'), (69, 38, 'Moist', 'MEDIUM'), (55, 5, 'Moist', 'MEDIUM'), (45, 5, 'Moist', 'LOW'), (20, 0, 'Dry', 'LOW')])
def test_soil_assessment(moisture, rain, condition, risk):
    soil = engine.soil_assessment('Loam', moisture, rain)
    assert soil['condition'] == condition and soil['waterlogging_risk'] == risk and soil['type'] == 'Loam'


def test_crop_recommendations_prefer_rice_when_waterlogged():
    wet = engine.crop_recommendations(engine.soil_assessment('Loam', 78, 38))
    assert [c['name'] for c in wet] == ['Rice', 'Soybean', 'Maize']
    assert wet[0]['score'] > wet[1]['score'] > wet[2]['score']
    assert all(0 <= c['score'] <= 100 and c['reason'] and c['warning'] for c in wet)
    dry = engine.crop_recommendations(engine.soil_assessment('Sandy loam', 40, 0))
    assert dry[0]['name'] in ('Soybean', 'Maize')
    assert dry[0]['score'] > next(c for c in dry if c['name'] == 'Rice')['score']


def test_planting_readiness_bands():
    soil_wet = engine.soil_assessment('Loam', 78, 38)
    assert engine.planting_readiness(55.2, soil_wet, 38) == {'percentage': 38, 'status': 'NOT RECOMMENDED', 'reason': 'Flooded soil, saturated moisture, heavy rain window'}
    soil_dry = engine.soil_assessment('Loam', 40, 0)
    ready = engine.planting_readiness(0, soil_dry, 0)
    assert ready['percentage'] == 100 and ready['status'] == 'READY'
    caution = engine.planting_readiness(50, soil_dry, 0)
    assert caution['percentage'] == 70 and caution['status'] == 'READY'
    assert engine.planting_readiness(51, soil_dry, 0)['status'] == 'CAUTION'
    assert engine.planting_readiness(93, soil_dry, 0)['status'] == 'NOT RECOMMENDED'


def test_alerts_follow_conditions():
    soil = engine.soil_assessment('Loam', 78, 38)
    flood = {'flood_percentage': 55.2, 'severity': 'HIGH'}
    assert engine.alerts(flood, soil, {'status': 'NOT RECOMMENDED'}) == ['Flood detected inside field', 'HIGH severity flood condition', 'Waterlogging risk is HIGH', 'Planting not recommended until drainage improves']
    assert engine.alerts({'flood_percentage': 0, 'severity': 'LOW'}, engine.soil_assessment('Loam', 30, 0), {'status': 'READY'}) == []
