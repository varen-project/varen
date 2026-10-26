# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import math
from types import SimpleNamespace

import laspy
import numpy as np
from sklearn.cluster import HDBSCAN
from joblib import Memory

from .constants import (
    HDBSCAN_MIN_CLUSTER_DISTANCE_ACCEPTANCE,
    MIN_SAMPLE,
    MIN_SCALED_SPAN_EPSILON_RATIO,
    W_S_MIN,
    W_S_MAX,
    MCS_FLOOR,
    MCS_CEIL,
    MEDIUM_VOLTAGE_WIRE_CLASS_NUMBER,
    LACVNET_COLUMN,
)
from .geometry import _pca_components

memory = Memory("./hdbscan_cache", verbose=0)


def pre_scale_for_phase_clustering(points_xyz, w_s=0.10, w_n=2.0, w_z=1.0):
    """Project wire points into a locally-aligned frame and apply anisotropic scaling.

    Parameters
    ----------
    points_xyz : np.ndarray, shape (N, 3)
        Raw 3-D point coordinates [x, y, z].
    w_s : float
        Scale weight for the along-wire coordinate.
    w_n : float
        Scale weight for the cross-wire horizontal coordinate.
    w_z : float
        Scale weight for the vertical coordinate.

    Returns
    -------
    X_scaled : np.ndarray, shape (N, 3)
    local : np.ndarray, shape (N, 3)
    transform : dict
    """
    xy = points_xyz[:, :2]
    z = points_xyz[:, 2]

    centroid_xy = xy.mean(axis=0)

    u = _pca_components(xy, n_components=1)[0]
    n_perp = np.array([-u[1], u[0]])

    dxy = xy - centroid_xy
    s = dxy @ u
    n = dxy @ n_perp

    local = np.column_stack([s, n, z])
    X_scaled = np.column_stack([w_s * s, w_n * n, w_z * z])

    transform = {
        "centroid_xy": centroid_xy,
        "u_along": u,
        "n_cross": n_perp,
    }
    return X_scaled, local, transform


@memory.cache
def _run_hdbscan_cached(X_scaled, mcs, min_sample, epsilon):
    """Return HDBSCAN labels for one ``min_cluster_size`` (mcs) value.

    sklearn's ``HDBSCAN`` does not expose a ``memory=`` parameter (unlike the
    old standalone ``hdbscan`` package), so the single-linkage tree cannot be
    shared across mcs values in-process.  Instead this whole function is
    wrapped with ``@memory.cache``: identical ``(X, mcs, min_sample, epsilon)``
    inputs return cached labels from disk, so repeated runs on the same file
    are effectively free.

    sklearn's epsilon search can raise ``TypeError`` (``traverse_upwards``);
    the fit is then repeated with ``cluster_selection_epsilon=0``.
    """
    def _fit(eps):
        return HDBSCAN(
            min_cluster_size=int(mcs),
            min_samples=int(min_sample),
            metric="euclidean",
            cluster_selection_epsilon=eps,
            cluster_selection_method="leaf",
            algorithm="kd_tree",
            alpha=0.85,
            copy=False,
        ).fit(X_scaled).labels_
    try:
        return _fit(float(epsilon))
    except TypeError:
        return _fit(0.0)


def _adaptive_min_cluster_size(n_points):
    """Derive HDBSCAN ``min_cluster_size`` from a span's wire-point count.

    On the 1001-file Xeso_Base sweep the per-span optimal ``min_cluster_size``
    grows with the logarithm of the point count (a proxy for the number of
    lateral phases present in the span). The fitted rule is::

        mcs = clip(0.9 * round(4.2 * log10(n_points) - 0.5), MCS_FLOOR, MCS_CEIL)

    Parameters
    ----------
    n_points : int
        Number of finite wire points in the span being clustered.

    Returns
    -------
    int
        ``min_cluster_size`` clamped to ``[MCS_FLOOR, MCS_CEIL]``.
    """
    if n_points <= 0:
        return MCS_FLOOR
    mcs = round(4.2 * math.log10(n_points) - 0.5) * 0.9
    return int(np.clip(mcs, MCS_FLOOR, MCS_CEIL))


def _fit_hdbscan_safe(points_xyz, epsilon, min_sample):
    """
    Cluster wire points with HDBSCAN using adaptive along-wire compression
    and an adaptive ``min_cluster_size`` (mcs).

    Processing steps
    ----------------
    1. **NaN/Inf filtering** — non-finite rows are masked out; the returned
       ``finite_mask`` maps labels back to the original index space.
    2. **Adaptive along-wire scale** — the physical span along the primary
       PCA axis is measured and an along-wire weight ``w_s`` is derived so
       that the scaled span covers at least
       ``MIN_SCALED_SPAN_EPSILON_RATIO × epsilon`` units, clamped to
       ``[W_S_MIN, W_S_MAX]``.
    3. **Pre-scaling** — ``pre_scale_for_phase_clustering`` projects points
       into a local ``(s, n, z)`` frame and applies ``(w_s, w_n, w_z)``
       weights so that cross-wire and vertical separations dominate the
       HDBSCAN distance metric.
    4. **Adaptive mcs** — ``min_cluster_size`` is derived from the number
       of finite points by ``_adaptive_min_cluster_size`` and HDBSCAN is
       run once (results cached on disk by ``_run_hdbscan_cached``).

    Parameters
    ----------
    points_xyz : array-like, shape (N, 3)
        3-D wire point coordinates ``[x, y, z]`` in metres (EPSG:2950).
        May contain NaN/Inf; affected rows are excluded before fitting.
    epsilon : float
        ``cluster_selection_epsilon`` forwarded to HDBSCAN.  Controls the
        minimum cluster separation in the scaled feature space.
    min_sample : int
        ``min_samples`` forwarded to HDBSCAN and used as the minimum number
        of finite points required to attempt a fit.

    Returns
    -------
    model : types.SimpleNamespace or None
        Object with a ``.labels_`` attribute containing integer cluster IDs
        for each finite input point (noise = −1).  ``None`` when there are
        fewer than ``max(2, min_sample)`` finite points.
    finite_mask : np.ndarray of bool, shape (N,)
        Boolean mask indicating which rows of ``points_xyz`` are finite and
        were included in the fit.
    """
    pts = np.asarray(points_xyz, dtype=np.float64)
    finite_mask = np.isfinite(pts).all(axis=1)
    pts_clean = pts[finite_mask]

    min_sample = int(min_sample)
    epsilon = float(epsilon)

    if pts_clean.shape[0] < max(2, min_sample):
        return None, finite_mask

    # --- Adaptive along-wire scale weight ---
    xy = pts_clean[:, :2]
    u = _pca_components(xy, n_components=1)[0]
    span_m = float(np.ptp((xy - xy.mean(axis=0)) @ u))
    w_s = np.clip(
        (MIN_SCALED_SPAN_EPSILON_RATIO * epsilon) / max(span_m, 0.1),
        W_S_MIN, W_S_MAX,
    )

    X_scaled, _, _ = pre_scale_for_phase_clustering(pts_clean, w_s=w_s)

    mcs = _adaptive_min_cluster_size(pts_clean.shape[0])
    best_labels = _run_hdbscan_cached(X_scaled, mcs, min_sample, epsilon)

    return SimpleNamespace(labels_=best_labels), finite_mask



def cluster_wire_points(las):
    """Cluster medium-voltage wire points in a LAS cloud using HDBSCAN.

    Adds a ``ClusterID`` extra dimension to the LAS object.

    Parameters
    ----------
    las : laspy.LasData
        LAS data whose coordinates are already in the target CRS.

    Returns
    -------
    laspy.LasData
        The same LAS object with ``ClusterID`` populated.
    """
    points = np.vstack((las.x, las.y, las.z)).T

    classification = getattr(las, LACVNET_COLUMN)
    mask = classification == MEDIUM_VOLTAGE_WIRE_CLASS_NUMBER
    filtered_points = points[mask]
    las.add_extra_dim(laspy.ExtraBytesParams(name="ClusterID", type=np.int32))

    if len(filtered_points) > 0:
        clusterer, finite_mask = _fit_hdbscan_safe(
            filtered_points,
            HDBSCAN_MIN_CLUSTER_DISTANCE_ACCEPTANCE,
            MIN_SAMPLE,
        )

        labels = np.full(filtered_points.shape[0], -1, dtype=int)
        if clusterer is not None:
            labels[finite_mask] = clusterer.labels_

        all_labels = np.full_like(classification, fill_value=-1, dtype=int)
        all_labels[mask] = labels
        las.ClusterID = all_labels
    return las
