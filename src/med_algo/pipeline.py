# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""High-level pipeline that ties all stages together.

Pipeline (one span = one LAS/LAZ file):
  1. HDBSCAN phase clustering in an anisotropic (s, n, z) frame with an
     adaptive min_cluster_size.
  2. Removal of short and perpendicular cluster candidates.
  3. Best-first Huber RMSE merge of the segments into conductors.
  4. Span gate: conductors covering > ACCEPTED_SEGMENT_LENGTH_PERCENTAGE of the
     span are written as FINAL_<name>_<id>.las.
  5. Rescue: rejected fragments are paired best-first by joint Huber RMSE and
     written as RESCUE_<name>_<id>.las.
"""

import glob
import logging
import os
import time
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import laspy

from .constants import (
    QUEBEC_EPSG,
    MIN_ACCEPTED_DISTANCE_SEGMENT_M,
    MINIMUM_NUMBER_POWERLINE_POINTS,
    MEDIUM_VOLTAGE_WIRE_CLASS_NUMBER,
    ENABLE_PROFILING,
    LACVNET_COLUMN,
    SKIP_REPROJECTION,
    MAX_FILE_SIZE,
    MED_ALGO_INPUT,
    MED_ALGO_OUTPUT,
    MED_ALGO_TEMP_SK_DIR,
)
from .utils import _now, _add_timing
from .geometry import create_center_line, distance_2d_from_bounds
from .clustering import cluster_wire_points
from .io import reproject_las_to_target, saveFiles
from .filtering import cleanShortLineCandidates, cleanPerpendicularCandidates
from .parabola import rmseMergeClusters, rescueRejectedClusters


def process_las(las, name, output_dir=MED_ALGO_OUTPUT, target_epsg=QUEBEC_EPSG, timings=None,
                skip_reprojection=SKIP_REPROJECTION):
    """
    Run the full detection pipeline on one span.

    Steps: reprojection, HDBSCAN clustering, short/perpendicular candidate
    filtering, Huber RMSE merge, span gate (``saveFiles``) and rescue
    (``rescueRejectedClusters``). Conductors are written to ``output_dir`` as
    ``FINAL_<name>_<id>.las`` and ``RESCUE_<name>_<id>.las``.

    Parameters
    ----------
    las : laspy.LasData
        Input span; must contain the ``LACVNET_COLUMN`` attribute.
    name : str
        Span name used in the output file names.
    output_dir : str
        Folder where conductor LAS files are written.
    target_epsg : int
        Target EPSG code for reprojection.
    skip_reprojection : bool
        If True, bypass CRS validation and coordinate reprojection.
    timings : dict, optional
        Accumulates per-stage timings (seconds).

    Returns
    -------
    las : laspy.LasData
        The reprojected input with the ``ClusterID`` attribute.
    parabolas : pd.DataFrame
        Spine samples ``[x, y, z, cluster]`` of every emitted conductor.
    """
    timings = {} if timings is None else timings
    parabolas = pd.DataFrame(columns=['x', 'y', 'z', 'cluster'])

    print('\n 1  - Clustering : ', name)
    t = _now()
    las = reproject_las_to_target(las, target_epsg, skip_reprojection=skip_reprojection)
    las = cluster_wire_points(las)
    _add_timing(timings, 'read_and_cluster', t)

    rawData = np.vstack([las.x, las.y, las.z, getattr(las, LACVNET_COLUMN), las.ClusterID]).transpose((1, 0))
    rawData = rawData[rawData[:, 3] == MEDIUM_VOLTAGE_WIRE_CLASS_NUMBER]
    if rawData.size == 0:
        return las, parabolas
    start_point, end_point = create_center_line(rawData[:, 0:2])
    lineSpanDistance = distance_2d_from_bounds(start_point[0], end_point[0], start_point[1], end_point[1])

    print("\n 2  - Filtering Short candidates ")
    t = _now()
    clustersOfLines = cleanShortLineCandidates(rawData, MIN_ACCEPTED_DISTANCE_SEGMENT_M)
    clustersOfLines = cleanPerpendicularCandidates(rawData, clustersOfLines, thresHold=0.85)
    _add_timing(timings, 'filter_candidates', t)
    if clustersOfLines.size <= MINIMUM_NUMBER_POWERLINE_POINTS:
        return las, parabolas

    print("\n 3  - Merging segments (Huber RMSE) ")
    t = _now()
    rawDataDf = pd.DataFrame(clustersOfLines, columns=['x', 'y', 'z', 'prediction', 'cluster'])
    cluster_stats = rawDataDf.groupby('cluster').agg(
        x_min=('x', 'min'), x_max=('x', 'max'),
        y_min=('y', 'min'), y_max=('y', 'max'))
    cluster_stats['Distance'] = distance_2d_from_bounds(
        cluster_stats['x_min'], cluster_stats['x_max'],
        cluster_stats['y_min'], cluster_stats['y_max'])
    # Seeds: longest XY bounding-box diagonal first
    cluster_distance_df = cluster_stats[['Distance']].reset_index()
    cluster_distance_df = cluster_distance_df.sort_values(by='Distance', ascending=False)
    clusterNumbers = cluster_distance_df['cluster'].values
    UpdatedCluster, finalParabolaTheory = rmseMergeClusters(
        rawDataDf, clusterNumbers, start_point, end_point)
    _add_timing(timings, 'merge', t)

    print("\n 4  - Saving Merged Parabolas ")
    t = _now()
    parabolas, rejectedClusters = saveFiles(
        lineSpanDistance, UpdatedCluster, finalParabolaTheory, 'FINAL_' + name, output_dir)
    _add_timing(timings, 'save_outputs', t)

    if rejectedClusters:
        print("\n 5  - Rescuing rejected clusters")
        t = _now()
        rescued = rescueRejectedClusters(
            rejectedClusters, UpdatedCluster, lineSpanDistance, 'RESCUE_' + name,
            start_point, end_point, output_dir)
        if not rescued.empty:
            parabolas = pd.concat([parabolas, rescued])
        _add_timing(timings, 'rescue', t)
    return las, parabolas

logger = logging.getLogger(__name__)


def run_pipeline(
    input_dir=MED_ALGO_INPUT,
    output_dir=MED_ALGO_OUTPUT,
    temp_sk_dir=MED_ALGO_TEMP_SK_DIR,
    target_epsg=QUEBEC_EPSG,
    skip_reprojection=SKIP_REPROJECTION,
    enable_profiling=ENABLE_PROFILING,
):
    """Execute the full MED_ALGO pipeline on every LAS/LAZ file in *input_dir*.

    Parameters
    ----------
    input_dir : str
        Path to the folder containing .las / .laz input files.
    output_dir : str
        Folder where FINAL_* / RESCUE_* conductor LAS files are written.
    temp_sk_dir : str
        Folder where the input clouds with the ``ClusterID`` attribute are written.
    target_epsg : int
        Target EPSG code for coordinate reprojection. Default: 2950 (Quebec Lambert).
        Ignored when skip_reprojection=True.
        
        **Regional examples:**
        - 2950: Quebec Lambert (default, Quebec, Canada)
        - 26916: UTM Zone 16N (Illinois, Indiana, Missouri, etc.)
        - 26917: UTM Zone 17N (Ohio, Pennsylvania, West Virginia, etc.)
        - 26918: UTM Zone 18N (Eastern Canada, Nova Scotia, etc.)
        - 4326: WGS84 (Global GPS standard, less precise for distance calculations)
        - 3857: Web Mercator (web mapping, not recommended for distance analysis)
        
        Valid EPSG codes are whitelisted in constants.py::VALID_EPSG_CODES for security.
        To add support for your region:
        
        1. Find your region's EPSG code: https://epsg.io
        2. Edit src/med_algo/constants.py
        3. Add your EPSG code to VALID_EPSG_CODES set
        4. Example: ``VALID_EPSG_CODES.add(26916)``  # Add UTM Zone 16N
    skip_reprojection : bool
        If True, bypass CRS validation and coordinate reprojection for all input
        files. Use this when input files have been pre-normalized to a local
        coordinate system (e.g., coordinates translated to a local origin)
        where the EPSG metadata in file headers is no longer valid and
        reprojection would corrupt the coordinates. Relative distances between
        points are preserved and all pipeline algorithms work correctly.
        
        For inputs already in a projected metric CRS (UTM, Lambert, etc.),
        leaving this False is safe and free — the pipeline detects the CRS
        match and skips reprojection automatically.
        
        Default: False (safe for open-source use — reprojection is a no-op
        for metric inputs and protects against silent corruption for
        degree-based inputs such as WGS84/EPSG:4326).
    enable_profiling : bool
        If True, print timing breakdown at the end.

    Returns
    -------
    dict
        Timing dictionary with profiling data for every stage.
    """
    start_time = time.time()
    timings = {}

    try:
        output_path = Path(output_dir).resolve()
        base_path = Path(MED_ALGO_OUTPUT).resolve()
        if not str(output_path).startswith(str(base_path)):
            raise ValueError(
                f"output_dir must be within {MED_ALGO_OUTPUT} directory. "
                f"Attempted: {output_path}, Base: {base_path}"
            )
    except Exception as e:
        logger.debug("Output path validation failed: %s", e)
        raise ValueError("Invalid output directory path.") from e

    # ------------------------------------------------------------------
    # 0. Clean old outputs
    # ------------------------------------------------------------------
    print('Erasing OLD data:')
    t_cleanup = _now()
    for folder in (output_dir, temp_sk_dir):
        os.makedirs(folder, exist_ok=True)
        folder_real = os.path.realpath(folder)
        files_to_delete = (
            glob.glob(os.path.join(folder, "*.las"))
            + glob.glob(os.path.join(folder, "*.laz"))
        )
        for file_path in files_to_delete:
            try:
                # Security: Validate file is within target directory (prevent symlink attacks)
                real_file_path = os.path.realpath(file_path)
                if not real_file_path.startswith(folder_real):
                    logger.warning("Skipping '%s' — resolves outside target directory.", file_path)
                    continue
                os.remove(real_file_path)
                logger.info("Deleted: %s", file_path)
            except FileNotFoundError:
                logger.debug("Already gone (race condition): %s", file_path)
            except PermissionError:
                logger.warning("Permission denied deleting '%s'.", file_path)
            except OSError:
                logger.exception("Failed to delete '%s'.", file_path)
    _add_timing(timings, 'cleanup_outputs', t_cleanup)

    # ------------------------------------------------------------------
    # 1. Process each input file
    # ------------------------------------------------------------------
    for inputFile in sorted(os.listdir(input_dir)):
        if not inputFile.endswith(('.las', '.laz')):
            continue
        name = os.path.splitext(inputFile)[0]
        print('\nProcessing: ', inputFile)

        file_path = os.path.join(input_dir, inputFile)
        file_size = os.path.getsize(file_path)
        if file_size > MAX_FILE_SIZE:
            print(
                f"  WARNING: '{inputFile}' ({file_size / (1024**2):.1f} MB) exceeds "
                f"MAX_FILE_SIZE ({MAX_FILE_SIZE // (1024**2)} MB) — skipping."
            )
            continue

        las = laspy.read(file_path)
        if LACVNET_COLUMN not in las.point_format.dimension_names:
            print(f"Column '{LACVNET_COLUMN}' does not exist in the point format of the LAS file. "
                  "Please ensure it is present for clustering.")
            continue
        las, parabolas = process_las(
            las, name, output_dir, target_epsg, timings,
            skip_reprojection=skip_reprojection,
        )
        las.write(os.path.join(temp_sk_dir, name + '.las'))
        if not parabolas.empty:
            print('\n*******NUMBER OF DETECTED PHASES:', parabolas['cluster'].nunique())

    end_time = time.time()
    print(f"\nExecution time: {end_time - start_time:.2f} seconds")
    if enable_profiling and timings:
        print("\n[PROFILE] Total")
        for key in sorted(timings.keys()):
            print(f"  - {key}: {timings[key]:.3f}s")

    return timings


def _cli():
    """Entry point for the ``med-algo`` console script."""

    parser = argparse.ArgumentParser(
        description="Medium-voltage wire detection from LiDAR point clouds",
        prog="med-algo"
    )
    parser.add_argument(
        '--input-dir',
        default=MED_ALGO_INPUT,
        help=f'path to input directory with .las/.laz files (default: {MED_ALGO_INPUT})'
    )
    parser.add_argument(
        '--output-dir',
        default=MED_ALGO_OUTPUT,
        help=f'path to output directory (default: {MED_ALGO_OUTPUT})'
    )
    parser.add_argument(
        '--target-epsg',
        type=int,
        default=QUEBEC_EPSG,
        help=f'target EPSG code for reprojection (default: {QUEBEC_EPSG})'
    )
    parser.add_argument(
        '--no-profiling',
        action='store_true',
        help='disable profiling output'
    )
    parser.add_argument(
        '--skip-reprojection',
        action='store_true',
        default=SKIP_REPROJECTION,
        help=(
            'skip CRS validation and coordinate reprojection entirely. '
            'Use when input files are pre-normalized to a local coordinate system '
            '(coordinates translated to local origin). '
            'The EPSG metadata in file headers is ignored and coordinates are used as-is.'
        )
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    run_pipeline(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        temp_sk_dir=MED_ALGO_TEMP_SK_DIR,
        target_epsg=args.target_epsg,
        skip_reprojection=args.skip_reprojection,
        enable_profiling=not args.no_profiling,
    )
