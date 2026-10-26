# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

# ─── Dataset ──────────────────────────────────────────────────────────────
LACVNET_COLUMN = 'lacvnet'            # point attribute holding the wire class labels
MEDIUM_VOLTAGE_WIRE_CLASS_NUMBER = 1  # class value of medium-voltage wire points

# ─── 1. HDBSCAN phase clustering ──────────────────────────────────────────
MIN_SAMPLE = 3                                 # HDBSCAN min_samples
HDBSCAN_MIN_CLUSTER_DISTANCE_ACCEPTANCE = 0.3  # cluster_selection_epsilon (scaled frame)
MAX_DISTANCE_THRESHOLD = 0.70           # feeds AVG_DISTANCE_THRESHOLD (candidate filtering)
MIN_DISTANCE_THRESHOLD = 0.1            # spine sampling step and minimum rescue-fragment span (m)
MIN_SCALED_SPAN_EPSILON_RATIO = 20      # scaled span must cover at least this many epsilon-widths
W_S_MIN = 0.05                          # clamps of the adaptive along-wire weight w_s
W_S_MAX = 1.0
MCS_FLOOR = 3                           # clamps of the adaptive min_cluster_size
MCS_CEIL = 15

# ─── 2. Candidate filtering ───────────────────────────────────────────────
MIN_ACCEPTED_DISTANCE_SEGMENT_M = 0.10  # clusters with a shorter XY span are dropped
MINIMUM_NUMBER_POWERLINE_POINTS = 20
AVG_DISTANCE_THRESHOLD = (MAX_DISTANCE_THRESHOLD + MIN_DISTANCE_THRESHOLD) / 2.0

# ─── 3. Huber RMSE merge ──────────────────────────────────────────────────
# A candidate joins the seed conductor when its Huber RMSE to the seed curve is
# <= RMSE_ACCEPT_M; residuals beyond RMSE_HUBER_DELTA_M count linearly.
RMSE_ACCEPT_M = 0.30
RMSE_HUBER_DELTA_M = 0.10

# ─── 4. Span gate ─────────────────────────────────────────────────────────
ACCEPTED_SEGMENT_LENGTH_PERCENTAGE = 0.55

# ─── 5. Rescue ────────────────────────────────────────────────────────────
# Fragment and pair coherence use the merge Huber RMSE (RMSE_ACCEPT_M).
RESCUE_MIN_LENGTH_PERCENTAGE = 0.40        # min rescued span, fraction of the corridor

# An end-to-end pair is joined only if the leading fragment's lateral trend,
# extrapolated across the gap, lines up with the trailing fragment.
RESCUE_MAX_LATERAL_OFFSET_M = 0.5          # max lateral misalignment across the gap (m)
RESCUE_JUNCTION_WINDOW_M = 1.0             # near-end window used to estimate lateral pos (m)

# ─── 6. Runtime ──────────────────────────────────────────────────────────────
ENABLE_PROFILING = True            # print timing of the pipeline stages
SKIP_REPROJECTION = False          # let the pipeline inspect and reproject if needed

# ─── 7. Algorithm setup parameters────────────────────────────────────────────
# COORDINATE SYSTEMS & GEOSPATIAL SETTINGS
# Default EPSG code for Quebec (Quebec Lambert / MTM zone 8, NAD83)
QUEBEC_EPSG = 2950

# Whitelist of valid EPSG codes for security (prevents DoS via invalid codes)
# Includes common North American UTM zones and other popular CRS
# Add new EPSG codes here as needed for your region
VALID_EPSG_CODES = {
    # Quebec & Canada
    2950,      # Quebec Lambert (NAD83)
    # North American UTM Zones (NAD83)
    # Add/remove zones as needed for your coverage area
    26915,     # UTM Zone 15N (Midwest US)
    26916,     # UTM Zone 16N (Central US)
    26917,     # UTM Zone 17N (Eastern US)
    26918,     # UTM Zone 18N (Eastern Canada)
    26919,     # UTM Zone 19N (Maritime provinces)
    26920,     # UTM Zone 20N (Maritime provinces)
    # Additional North American CRS
    2927,      # Washington State Plane South (NAD83)
    2928,      # Washington State Plane North (NAD83)
}

# Security: Maximum allowed LAS/LAZ file size in bytes (prevents DoS via huge files)
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB

MED_ALGO_INPUT = './input/'
MED_ALGO_OUTPUT = './output/'
MED_ALGO_TEMP_SK_DIR = './outputTempSK/'