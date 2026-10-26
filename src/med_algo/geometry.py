# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import math
import numpy as np


def _pca_components(data, n_components=1):
    """Return the top principal-component directions via numpy SVD.

    Replicates sklearn PCA behaviour including the deterministic sign-flip
    so that the largest absolute value in each left singular vector is positive.
    """
    centered = data - data.mean(axis=0)
    U, _, Vt = np.linalg.svd(centered, full_matrices=False)
    # sklearn svd_flip: for each component, flip sign so the max |U| entry is positive
    max_abs_idx = np.argmax(np.abs(U), axis=0)
    signs = np.sign(U[max_abs_idx, range(U.shape[1])])
    Vt *= signs[:, np.newaxis]
    return Vt[:n_components]


def create_center_line(points_2d):
    """Compute the center line of a 2D point cloud using PCA.

    Parameters
    ----------
    points_2d : np.ndarray
        (N, 2) array of X, Y coordinates.

    Returns
    -------
    start_point_2d : np.ndarray
        2D start coordinate of the center line.
    end_point_2d : np.ndarray
        2D end coordinate of the center line.
    """
    centroid = np.mean(points_2d, axis=0)

    components = _pca_components(points_2d, n_components=2)

    main_axis = components[0]

    centered_points = points_2d - centroid
    projections = np.dot(centered_points, main_axis)

    true_min = np.min(projections)
    true_max = np.max(projections)

    start_point_2d = centroid + true_min * main_axis
    end_point_2d = centroid + true_max * main_axis

    return start_point_2d, end_point_2d


def getMinMaxDistance(dataframe):
    """Return XY span distance from a DataFrame containing x and y columns."""
    minX = dataframe['x'].min()
    minY = dataframe['y'].min()
    maxX = dataframe['x'].max()
    maxY = dataframe['y'].max()
    return math.sqrt((maxX - minX) ** 2 + (maxY - minY) ** 2)


def distance_2d_from_bounds(min_x, max_x, min_y, max_y):
    """Euclidean distance between (min_x, min_y) and (max_x, max_y).

    Works with scalars and pandas Series/NumPy arrays.
    """
    dx = max_x - min_x
    dy = max_y - min_y
    return np.hypot(dx, dy)


def choose_dx_for_line(m_line, max_spacing=0.10, snap=0.001, safety=1.0):
    """Compute an x-step ensuring Euclidean spacing between successive
    (x, y) points along y = m_line * x + b_line is <= max_spacing.

    Parameters
    ----------
    m_line : float
        Slope of the line.
    max_spacing : float
        Maximum allowed Euclidean spacing.
    snap : float
        Step quantum.
    safety : float
        Safety margin (< 1.0 makes it tighter).

    Returns
    -------
    float
        Snapped x-step value.
    """
    dx_raw = (max_spacing / math.sqrt(1.0 + m_line ** 2)) * safety
    dx_snapped = math.floor(dx_raw / snap) * snap

    if dx_snapped <= 0:
        dx_snapped = snap
    return round(dx_snapped, 4)
