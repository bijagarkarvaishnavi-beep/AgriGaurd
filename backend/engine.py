"""Deterministic flood / soil / crop / readiness engine. Pure functions, no I/O."""
from pyproj import Geod
from shapely.geometry import Polygon, box
from shapely.validation import explain_validity

GEOD = Geod(ellps='WGS84')
HA_TO_ACRES = 2.47105
DEMO_FLOOD_BAND = 0.55  # southern share of the field bbox covered by the DEMO waterbody


def to_lonlat(poly):
    return [(p[1], p[0]) for p in poly]


def geodesic_hectares(lonlat):
    if len(lonlat) < 3:
        return 0.0
    area, _ = GEOD.polygon_area_perimeter(*zip(*lonlat))
    return abs(area) / 10000


def hectares(poly):
    return max(0.01, round(geodesic_hectares(to_lonlat(poly)), 2))


def acres(ha):
    return round(ha * HA_TO_ACRES, 2)


def polygon_problem(poly):
    if len(poly) < 3 or any(len(p) != 2 for p in poly):
        return 'polygon must contain at least three latitude/longitude pairs'
    if any(abs(p[0]) > 90 or abs(p[1]) > 180 for p in poly):
        return 'polygon coordinates must be valid WGS84 latitude/longitude values'
    shape = Polygon(to_lonlat(poly))
    if not shape.is_valid:
        return f'polygon geometry is invalid: {explain_validity(shape)}'
    return None


def flood_percent(flooded_ha, total_ha):
    if total_ha <= 0:
        return 0.0
    return round(min(100.0, flooded_ha / total_ha * 100), 1)


def severity(pct):
    return 'HIGH' if pct >= 50 else 'MEDIUM' if pct >= 20 else 'LOW'


def demo_water_polygon(poly):
    shape = Polygon(to_lonlat(poly))
    minx, miny, maxx, maxy = shape.bounds
    return box(minx - 1, miny - 1, maxx + 1, miny + (maxy - miny) * DEMO_FLOOD_BAND)


def demo_flood(poly):
    field = Polygon(to_lonlat(poly))
    inter = field.intersection(demo_water_polygon(poly))
    parts = getattr(inter, 'geoms', [inter])
    flooded = sum(geodesic_hectares(list(part.exterior.coords)) for part in parts if not part.is_empty and part.geom_type == 'Polygon')
    total = geodesic_hectares(to_lonlat(poly))
    return round(flooded, 2), flood_percent(flooded, total)


def soil_assessment(soil_type, moisture, rainfall_mm):
    condition = 'Saturated' if moisture >= 70 else 'Moist' if moisture >= 40 else 'Dry'
    risk = 'HIGH' if moisture >= 70 and rainfall_mm >= 20 else 'MEDIUM' if moisture >= 55 or rainfall_mm >= 20 else 'LOW'
    return {'type': soil_type, 'moisture': moisture, 'condition': condition, 'waterlogging_risk': risk}


CROPS = {
    'Rice': {'ideal_moisture': 0.85, 'season_fit': 0.95, 'water_tolerance': 1.0, 'reason': 'Tolerates saturated soil', 'warning': 'Delay transplanting until water recedes'},
    'Soybean': {'ideal_moisture': 0.5, 'season_fit': 0.85, 'water_tolerance': 0.35, 'reason': 'Good seasonal fit', 'warning': 'Needs drainage before sowing'},
    'Maize': {'ideal_moisture': 0.4, 'season_fit': 0.7, 'water_tolerance': 0.1, 'reason': 'Available season window', 'warning': 'Not suitable for current waterlogging'},
}


def crop_recommendations(soil):
    wet = soil['moisture'] / 100
    out = []
    for name, c in CROPS.items():
        score = 100 * (0.55 * (1 - abs(wet - c['ideal_moisture'])) + 0.45 * c['season_fit'])
        if soil['waterlogging_risk'] == 'HIGH' and c['water_tolerance'] < 0.5:
            score -= 20
        out.append({'name': name, 'score': int(round(max(0, min(100, score)))), 'reason': c['reason'], 'warning': c['warning']})
    return sorted(out, key=lambda x: -x['score'])


def planting_readiness(flood_pct, soil, rainfall_mm):
    penalty = 0.6 * flood_pct + 0.3 * max(0, soil['moisture'] - 50) + (20 if rainfall_mm >= 30 else 10 if rainfall_mm >= 15 else 0)
    pct = int(round(max(0, min(100, 100 - penalty))))
    status = 'READY' if pct >= 70 else 'CAUTION' if pct >= 45 else 'NOT RECOMMENDED'
    reasons = []
    if flood_pct >= 20:
        reasons.append('flooded soil')
    if soil['moisture'] >= 70:
        reasons.append('saturated moisture')
    if rainfall_mm >= 15:
        reasons.append('heavy rain window')
    return {'percentage': pct, 'status': status, 'reason': (', '.join(reasons) or 'conditions within planting range').capitalize()}


def alerts(flood, soil, readiness):
    out = []
    if flood['flood_percentage'] > 0:
        out.append('Flood detected inside field')
    if flood['severity'] != 'LOW':
        out.append(f"{flood['severity']} severity flood condition")
    if soil['waterlogging_risk'] == 'HIGH':
        out.append('Waterlogging risk is HIGH')
    if readiness['status'] == 'NOT RECOMMENDED':
        out.append('Planting not recommended until drainage improves')
    return out
