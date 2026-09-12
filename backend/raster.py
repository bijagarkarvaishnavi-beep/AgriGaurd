"""Sentinel-1 style change-detection raster engine (rasterio + numpy) with a deterministic DEMO fallback."""
import io, os, uuid
import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.mask import mask as raster_mask
from rasterio.warp import transform_geom
from pyproj import Transformer
from PIL import Image
import engine

RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'sentinel_results')
os.makedirs(RESULTS_DIR, exist_ok=True)
DEFAULT_POLYGON = [[51.505, -0.09], [51.51, -0.08], [51.508, -0.06], [51.502, -0.065]]
SIZE = 256
TO_3857 = Transformer.from_crs('EPSG:4326', 'EPSG:3857', always_xy=True)


def demo_raster(polygon=None, after=False):
    """Synthetic backscatter (dB) over the field bbox; the AFTER scene floods the southern DEMO band only."""
    xs, ys = TO_3857.transform([p[1] for p in polygon or DEFAULT_POLYGON], [p[0] for p in polygon or DEFAULT_POLYGON])
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    pad_x, pad_y = (maxx - minx) * 0.25, (maxy - miny) * 0.25
    res = max((maxx - minx + 2 * pad_x) / SIZE, (maxy - miny + 2 * pad_y) / SIZE, 1.0)
    top = maxy + pad_y
    rng = np.random.default_rng(7)
    arr = (-12 + rng.normal(0, 1, (SIZE, SIZE))).astype('float32')
    if after:
        rows = top - np.arange(SIZE) * res
        flood_top = miny + (maxy - miny) * engine.DEMO_FLOOD_BAND
        arr[rows < flood_top, :] -= 9
    profile = {'driver': 'GTiff', 'height': SIZE, 'width': SIZE, 'count': 1, 'dtype': 'float32', 'crs': 'EPSG:3857', 'transform': from_origin(minx - pad_x, top, res, res), 'nodata': -9999}
    with MemoryFile() as mem:
        with mem.open(**profile) as dst:
            dst.write(arr, 1)
        return mem.read()


def png_preview(path, arr):
    x = np.ma.filled(np.ma.asarray(arr).astype('float32'), np.nan)
    finite = np.isfinite(x)
    img = np.zeros(x.shape, dtype='uint8')
    if finite.any():
        lo, hi = np.percentile(x[finite], [2, 98])
        scaled = (np.where(finite, x, lo) - lo) / max(hi - lo, 1e-6) * 255
        img = np.clip(scaled, 0, 255).astype('uint8')
    Image.fromarray(img).save(path, optimize=True)


def field_geometry(field, crs):
    ring = [[p[1], p[0]] for p in field['polygon']] + [[field['polygon'][0][1], field['polygon'][0][0]]]
    return transform_geom('EPSG:4326', crs, {'type': 'Polygon', 'coordinates': [ring]})


def raster_run(before_data, after_data, field, threshold, source):
    from fastapi import HTTPException
    bm, am = MemoryFile(before_data), MemoryFile(after_data)
    try:
        bds, ads = bm.open(), am.open()
    except rasterio.errors.RasterioIOError:
        raise HTTPException(422, 'Uploaded file is not a readable GeoTIFF')
    try:
        if bds.crs != ads.crs or bds.shape != ads.shape or bds.transform != ads.transform:
            raise HTTPException(422, 'Before and after rasters must share CRS, dimensions, and transform')
        if not bds.crs:
            raise HTTPException(422, 'GeoTIFF must carry a coordinate reference system')
        b, a, transform = bds.read(1, masked=True), ads.read(1, masked=True), bds.transform
        if field:
            geom = field_geometry(field, bds.crs)
            try:
                b, transform = raster_mask(bds, [geom], crop=True, filled=False)
                a, _ = raster_mask(ads, [geom], crop=True, filled=False)
            except ValueError:
                raise HTTPException(422, 'Field polygon does not overlap the uploaded raster footprint')
            b, a = b[0], a[0]
        bf, af = np.ma.filled(b.astype('float32'), np.nan), np.ma.filled(a.astype('float32'), np.nan)
        valid = ~np.ma.getmaskarray(a) & ~np.ma.getmaskarray(b) & np.isfinite(af) & np.isfinite(bf)
        change = np.where(valid, af - bf, np.nan)
        flood = valid & (np.nan_to_num(change, nan=0.0) <= threshold)
        run_id = str(uuid.uuid4())
        folder = os.path.join(RESULTS_DIR, run_id)
        os.makedirs(folder)
        png_preview(os.path.join(folder, 'before.png'), np.ma.array(bf, mask=~valid))
        png_preview(os.path.join(folder, 'after.png'), np.ma.array(af, mask=~valid))
        png_preview(os.path.join(folder, 'change.png'), np.ma.array(change, mask=~valid))
        png_preview(os.path.join(folder, 'flood-mask.png'), flood.astype('float32'))
        pixels, total = int(flood.sum()), int(valid.sum())
        pct = round(pixels / total * 100, 1) if total else 0.0
        area_m2 = abs(transform.a * transform.e) * pixels
        return {'id': run_id, 'field_id': field['id'] if field else None, 'field_name': field['name'] if field else 'Unassigned raster', 'flood_percentage': pct,
                'flooded_hectares': round(area_m2 / 10000, 2), 'threshold_db': threshold, 'flood_pixels': pixels, 'valid_pixels': total, 'severity': engine.severity(pct), 'source': source,
                'artifacts': {name: f'/api/sentinel1/results/{run_id}/{name}' for name in ['before.png', 'after.png', 'change.png', 'flood-mask.png']}, 'created_at': engine_now()}
    finally:
        bds.close(); ads.close(); bm.close(); am.close()


def engine_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
