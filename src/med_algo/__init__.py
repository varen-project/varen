# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""MED_ALGO - Medium-voltage wire detection from LiDAR point clouds."""

import logging

logging.getLogger(__name__).addHandler(logging.NullHandler())

from .pipeline import run_pipeline
from .constants import (
    MIN_DISTANCE_THRESHOLD,
    RMSE_ACCEPT_M,
    RMSE_HUBER_DELTA_M,
    QUEBEC_EPSG,
    HDBSCAN_MIN_CLUSTER_DISTANCE_ACCEPTANCE,
    MEDIUM_VOLTAGE_WIRE_CLASS_NUMBER,
    LACVNET_COLUMN,
)
from .geometry import create_center_line, distance_2d_from_bounds, getMinMaxDistance, _pca_components
from .fitting import robust_polyfit_huber, approximateLineOrParabola
from .clustering import cluster_wire_points
from .io import reproject_las_to_target, createLasFile, saveFiles
from .filtering import cleanShortLineCandidates, cleanPerpendicularCandidates
from .parabola import rmseMergeClusters, rescueRejectedClusters

__all__ = [
    "run_pipeline",
    "process_las",
    "create_center_line",
    "distance_2d_from_bounds",
    "getMinMaxDistance",
    "_pca_components",
    "robust_polyfit_huber",
    "approximateLineOrParabola",
    "cluster_wire_points",
    "reproject_las_to_target",
    "createLasFile",
    "saveFiles",
    "cleanShortLineCandidates",
    "cleanPerpendicularCandidates",
    "rmseMergeClusters",
    "rescueRejectedClusters",
    "MIN_DISTANCE_THRESHOLD",
    "RMSE_ACCEPT_M",
    "RMSE_HUBER_DELTA_M",
    "QUEBEC_EPSG",
    "HDBSCAN_MIN_CLUSTER_DISTANCE_ACCEPTANCE",
    "MEDIUM_VOLTAGE_WIRE_CLASS_NUMBER",
    "LACVNET_COLUMN",
]
