# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
import os
import numpy as np
import laspy
import pandas as pd
from pyproj import Transformer, CRS

logger = logging.getLogger(__name__)

from .constants import QUEBEC_EPSG, ACCEPTED_SEGMENT_LENGTH_PERCENTAGE, VALID_EPSG_CODES, MED_ALGO_OUTPUT
from .geometry import getMinMaxDistance


def reproject_las_to_target(las, target_epsg=QUEBEC_EPSG, skip_reprojection=False):
    """Reproject LAS coordinates in-place to the target EPSG.

    Parameters
    ----------
    las : laspy.LasData
        Input LAS data object.
    target_epsg : int
        Target EPSG code for reprojection. Must be in VALID_EPSG_CODES.
        Default: QUEBEC_EPSG (2950, Quebec Lambert)
        
        For other regions, specify the appropriate EPSG code:
        - UTM Zone 16N (Central US): 26916
        - UTM Zone 17N (Eastern US): 26917
        - UTM Zone 18N (Eastern Canada): 26918
        
        To add new EPSG codes for your region, edit VALID_EPSG_CODES in constants.py
    skip_reprojection : bool
        If True, bypass all CRS validation and coordinate transformation entirely.
        Use this when input files have been pre-normalized to a local coordinate
        system (coordinates translated to local origin). In that case the CRS
        metadata in the file header is no longer valid and reprojection would
        corrupt the coordinates. Relative distances between points are preserved.
        Default: False

    Returns
    -------
    laspy.LasData
        Reprojected LAS data, or unchanged LAS data if skip_reprojection=True.
        
    Raises
    ------
    ValueError
        If target_epsg is not in the whitelist of valid EPSG codes (prevents DoS attacks).
    """
    if skip_reprojection:
        print("  Reprojection skipped (pre-normalized local coordinate system).")
        return las

    # Security: Validate EPSG code (prevent DoS via invalid coordinate transformations)
    if target_epsg not in VALID_EPSG_CODES:
        raise ValueError(
            f"EPSG code {target_epsg} is not in the whitelist of allowed codes. "
            f"Valid codes: {sorted(VALID_EPSG_CODES)}\n"
            f"To add support for your region's EPSG code, edit VALID_EPSG_CODES in constants.py"
        )

    original_crs = las.header.parse_crs()
    try:
        target_crs = CRS.from_epsg(target_epsg)
    except Exception as e:
        logger.debug("CRS.from_epsg(%d) failed: %s", target_epsg, e)
        raise ValueError(
            f"EPSG code {target_epsg} could not be loaded. "
            f"Verify the code is correct and pyproj is up to date."
        ) from e

    # Validate target CRS is a projected (metric) CRS — geographic CRS (degrees)
    # since all distance thresholds are metre-based.
    if not target_crs.is_projected:
        raise ValueError(
            f"EPSG:{target_epsg} is a geographic (degree-based) CRS and cannot be used "
            f"as a reprojection target. All pipeline thresholds are in metres.\n"
            f"Choose a projected metric CRS for your region (e.g., a UTM zone). "
            f"Find yours at https://epsg.io — search your region and select a "
            f"'Projected CRS' result."
        )

    if original_crs is None:
        logger.warning("CRS information missing in input file. Proceeding with default projection.")
        return las

    if CRS.is_exact_same(original_crs, target_crs):
        print(f"  CRS is already EPSG:{target_epsg}, skipping reprojection.")
        return las

    print(f"  Reprojecting from {original_crs.to_epsg() or original_crs.name} to EPSG:{target_epsg}")

    transformer = Transformer.from_crs(original_crs, target_crs, always_xy=True)
    x_new, y_new, z_new = transformer.transform(las.x, las.y, las.z)

    las.header.offsets = np.array([
        np.floor(x_new.min()),
        np.floor(y_new.min()),
        np.floor(z_new.min()),
    ])
    las.header.scales = np.array([0.001, 0.001, 0.001])

    las.x = x_new
    las.y = y_new
    las.z = z_new

    # Write the new CRS into the header VLRs (WKT record for LAS 1.4)
    wkt = target_crs.to_wkt()
    new_vlr = laspy.VLR(
        user_id="LASF_Projection",
        record_id=2112,
        description="OGC Transformation Record",
        record_data=wkt.encode("utf-8"),
    )
    # Remove any pre-existing CRS VLRs (GeoTIFF and WKT), then add the new WKT one
    las.vlrs = [
        v for v in las.vlrs
        if not (v.user_id.strip("\x00") == "LASF_Projection"
                and v.record_id in (34735, 34736, 34737, 2112))
    ]
    las.vlrs.append(new_vlr)

    return las


def createLasFile(toAddArr, fileName, output_dir=MED_ALGO_OUTPUT):
    """Write clustered parabola points to a LAS file.

    Parameters
    ----------
    toAddArr : pd.DataFrame
        Must contain columns ``x``, ``y``, ``z``, ``cluster``.
    fileName : str
        Base name (without extension).
    output_dir : str
        Output directory path.
    """
    header = laspy.LasHeader(point_format=6, version="1.4")
    las = laspy.LasData(header)

    las.x = toAddArr.x
    las.y = toAddArr.y
    las.z = toAddArr.z
    las.classification = toAddArr.cluster.astype(np.uint8) + 1

    las.write(os.path.join(output_dir, fileName + ".las"))


def saveFiles(lineSpanDistance, localUpdatedCluster, theoricalParabola, name, output_dir=MED_ALGO_OUTPUT):
    """Validate parabola segments and write accepted ones to LAS files.

    Parameters
    ----------
    lineSpanDistance : float
    localUpdatedCluster : pd.DataFrame
    theoricalParabola : np.ndarray
    name : str
    output_dir : str

    Returns
    -------
    tuple[pd.DataFrame, list]
        Filtered theoretical parabola points and list of rejected cluster IDs.
    """
    clusterToRemove = []
    if len(theoricalParabola) > 0:
        updatedCluster = pd.DataFrame(theoricalParabola, columns=['x', 'y', 'z', 'cluster'])
        clusterNumbers = np.unique(updatedCluster.cluster)
        for clusterNumber in clusterNumbers:
            clusterData = updatedCluster.query('cluster == @clusterNumber')
            lineSegmentDistance = getMinMaxDistance(localUpdatedCluster.query('cluster == @clusterNumber'))
            detectedPercentage = lineSegmentDistance / lineSpanDistance
            if detectedPercentage > ACCEPTED_SEGMENT_LENGTH_PERCENTAGE:
                createLasFile(clusterData, name + '_' + str(clusterNumber), output_dir)
            else:
                clusterToRemove = clusterToRemove + [clusterNumber]
    dfTheoricalPrabola = pd.DataFrame(theoricalParabola, columns=['x', 'y', 'z', 'cluster'])
    dfTheoricalPrabola = dfTheoricalPrabola[~dfTheoricalPrabola['cluster'].isin(clusterToRemove)]
    return dfTheoricalPrabola, clusterToRemove
