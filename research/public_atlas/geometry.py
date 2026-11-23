"""Convert the provider frame to feet from the shooting team's basket."""
import json
from pathlib import Path

import numpy as np

RULES = json.loads(Path(__file__).with_name('court_rules.json').read_bytes())
BASELINE = -RULES['rim_from_baseline']
MIDCOURT = RULES['length'] / 2 + BASELINE
HALF_WIDTH = RULES['width'] / 2
CELL_FT = 2.5
COLS = int(np.ceil(RULES['width'] / CELL_FT))
ROWS = int(np.ceil((MIDCOURT - BASELINE) / CELL_FT))
ZONES = ('At the rim', 'Short two area', 'Midrange area', 'Corner three area',
         'Above the break', 'Other half', 'Unknown location')


def era_for(season):
    matches = [rule for rule in RULES['eras'] if rule['first_season'] <= season <= rule['last_season']]
    if len(matches) != 1:
        raise ValueError(f'Court dimensions are missing or ambiguous for {season}')
    return matches[0]


def line_geometry(depth, lateral, era):
    """Signed shortest distance to the finite arc or its corner segments."""
    radius, corner = era['arc_radius'], era['corner_distance']
    join = np.sqrt(radius ** 2 - corner ** 2)
    limit = np.arcsin(corner / radius)
    angle = np.clip(np.arctan2(lateral, depth), -limit, limit)
    arc_distance = np.hypot(depth - radius * np.cos(angle), lateral - radius * np.sin(angle))
    corner_distance = np.hypot(depth - np.clip(depth, BASELINE, join), np.abs(lateral) - corner)
    outside = np.where(depth <= join, np.abs(lateral) > corner, np.hypot(depth, lateral) > radius)
    return np.minimum(arc_distance, corner_distance) * np.where(outside, 1, -1), join


def locations(shots, era, zero_is_missing=False):
    home = shots.team_id.eq(shots.home_id)
    participants = home | shots.team_id.eq(shots.away_id)
    # wehoop's sign convention already encodes the attacking basket for each team.
    # Folding to the nearest basket would put real backcourt attempts near the rim.
    sign = np.where(home, 1, -1)
    depth = MIDCOURT - shots.coordinate_x.to_numpy(dtype=float) * sign
    lateral = shots.coordinate_y.to_numpy(dtype=float) * sign
    raw_depth = shots.coordinate_y_raw.to_numpy(dtype=float)
    raw_lateral = HALF_WIDTH - shots.coordinate_x_raw.to_numpy(dtype=float)
    verified = (participants.to_numpy() & np.isclose(depth, raw_depth, atol=1e-8, rtol=0)
                & np.isclose(lateral, raw_lateral, atol=1e-8, rtol=0))
    return locate(shots, era, depth, lateral, verified, zero_is_missing)


def locate(shots, era, depth, lateral, verified, zero_is_missing):
    finite = np.isfinite(depth) & np.isfinite(lateral)
    on_court = ((depth >= BASELINE) & (depth <= RULES['length'] + BASELINE)
                & (np.abs(lateral) <= HALF_WIDTH))
    origin = (depth == 0) & (lateral == 0)
    placeholder = origin & zero_is_missing
    known = finite & verified & on_court & ~placeholder
    half = known & (depth <= MIDCOURT)
    beyond = known & ~half
    shots['location_status'] = np.select(
        [~finite, placeholder, ~verified, ~on_court, beyond],
        ['missing', 'provider_origin_placeholder', 'coordinate_conflict', 'outside_court', 'other_half'], default='mapped')
    shots['depth_ft'] = np.where(known, depth, np.nan)
    shots['lateral_ft'] = np.where(known, lateral, np.nan)
    distance = np.hypot(depth, lateral)
    line, join = line_geometry(depth, lateral, era)
    shots['distance_ft'] = np.where(known, distance, np.nan)
    shots['line_offset_ft'] = np.where(known, line, np.nan)
    shots['court_id'] = era['id']
    # Whole foot locations sufficiently near a line can fall on either side after rounding.
    shots['near_three_line'] = known & (np.abs(line) <= np.sqrt(.5))
    shots['shot_location_disagrees'] = (known & (not era.get('arc_only', False)) & ~shots.near_three_line & shots.attempt_value.notna()
                                       & ((line > 0) != shots.attempt_value.eq(3).fillna(False)))
    shots['rim_coordinate'] = known & (depth == 0) & (lateral == 0)
    shots['zone'] = np.select([~known, beyond, (line > 0) & (depth <= join), line > 0, distance < 4, distance < 10],
                              [6, 5, 3, 4, 0, 1], default=2)
    bin_depth = np.clip(np.floor((depth[half] - BASELINE) / CELL_FT), 0, ROWS - 1).astype(int)
    bin_lateral = np.clip(np.floor((lateral[half] + HALF_WIDTH) / CELL_FT), 0, COLS - 1).astype(int)
    cells = np.where(beyond, -2, -1)
    cells[half] = bin_depth * COLS + bin_lateral
    shots['cell'] = cells
    return shots
