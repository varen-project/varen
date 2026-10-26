# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import numpy as np
import pandas as pd

from .constants import MEDIUM_VOLTAGE_WIRE_CLASS_NUMBER, LACVNET_COLUMN
from .geometry import distance_2d_from_bounds, _pca_components


def cleanShortLineCandidates(rawData, minDistance):
    """Remove wire clusters whose XY bounding-box diagonal is below *minDistance*.

    Parameters
    ----------
    rawData : np.ndarray
        (N, 5) array with columns [x, y, z, lacvnet, clusterID].
    minDistance : float
        Minimum acceptable XY span (m) for a cluster to be retained.

    Returns
    -------
    clustersOfLines : np.ndarray
        Medium-voltage, non-noise rows of clusters spanning at least *minDistance*.
    """
    clustersOfLines = rawData[
        (rawData[:, 3] == MEDIUM_VOLTAGE_WIRE_CLASS_NUMBER) & (rawData[:, 4] >= 0)
    ]

    dfAllLidar = pd.DataFrame(rawData, columns=['x', 'y', 'z', LACVNET_COLUMN, 'clusterID'])
    lidarLinesMax = dfAllLidar.groupby('clusterID').max().rename(
        columns={"x": "xMax", "y": "yMax", "z": "zMax"}
    )
    lidarLinesMin = dfAllLidar.groupby('clusterID').min().rename(
        columns={'x': 'xMin', 'y': 'yMin', 'z': 'zMin'}
    )
    lidarLinesMinMax = pd.merge(lidarLinesMax, lidarLinesMin, left_index=True, right_index=True)
    lidarLinesMinMax["distance"] = distance_2d_from_bounds(
        lidarLinesMinMax.xMin, lidarLinesMinMax.xMax,
        lidarLinesMinMax.yMin, lidarLinesMinMax.yMax,
    )
    clusterToRemove = lidarLinesMinMax.query('distance<@minDistance')
    clusterToRemove = clusterToRemove.index.astype(int)
    clusterToRemove = np.sort(np.unique(clusterToRemove))
    clustersOfLines = clustersOfLines[~np.isin(clustersOfLines[:, 4], clusterToRemove)]
    return clustersOfLines


def cleanPerpendicularCandidates(pcd, clustersOfLines, thresHold):
    """Filter clusters whose main direction is too perpendicular to the global line axis.

    Parameters
    ----------
    pcd : np.ndarray
    clustersOfLines : np.ndarray
    thresHold : float

    Returns
    -------
    np.ndarray
    """
    clusterToRemove = []
    orig_dir = _pca_components(pcd[:, 0:2], n_components=1)[0]
    clusterNumbers = np.unique(clustersOfLines[:, 4])
    for clusterNumber in clusterNumbers:
        clusterData = clustersOfLines[clustersOfLines[:, 4] == clusterNumber][:, 0:2]
        line_dir = _pca_components(clusterData, n_components=1)[0]
        dot_product = abs(np.dot(orig_dir, line_dir))
        if abs(dot_product) < thresHold:
            clusterToRemove.append(clusterNumber)

    clustersOfLines = clustersOfLines[~np.isin(clustersOfLines[:, 4], clusterToRemove)]
    return clustersOfLines
