# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import numpy as np
import pandas as pd

from .constants import (
    MIN_DISTANCE_THRESHOLD,
    RMSE_ACCEPT_M,
    RMSE_HUBER_DELTA_M,
    RESCUE_MIN_LENGTH_PERCENTAGE,
    RESCUE_JUNCTION_WINDOW_M,
    RESCUE_MAX_LATERAL_OFFSET_M,
    MED_ALGO_OUTPUT,
)
from .geometry import choose_dx_for_line
from .fitting import robust_polyfit_huber
from .io import createLasFile


def rmseMergeClusters(rawData, clusterNumbers, start_point, end_point):
    """
    Merge cluster segments into conductors by best-first RMSE growth.

    Seeds are visited in ``clusterNumbers`` order (longest XY bounding-box
    diagonal first). For the current seed set a line u(t) and a parabola z(t)
    are fitted (Huber) along the dominant horizontal axis t. Every free
    cluster k gets

        r_p^2  = (du_p / sqrt(1 + m^2))^2 + dz_p^2
        RMSE_k = sqrt(mean_p[ 2 * rho_delta(r_p) ])

    over all its points (plan-perpendicular and vertical residuals), where
    rho_delta is the Huber loss with delta = RMSE_HUBER_DELTA_M (r^2/2 below
    delta, delta*(r - delta/2) above), so stray points weigh linearly. The free
    cluster with the lowest RMSE is merged if RMSE_k <= RMSE_ACCEPT_M, the curve
    is refitted on the enlarged set and the step repeats. A seed whose own RMSE
    exceeds RMSE_ACCEPT_M is incoherent and is not emitted.

    Parameters
    ----------
    rawData : pd.DataFrame
        Must contain columns ``x``, ``y``, ``z``, ``cluster``.
    clusterNumbers : array-like
        Cluster IDs in seed priority order.
    start_point, end_point : np.ndarray
        (2,) corridor centre-line endpoints.

    Returns
    -------
    UpdatedCluster : pd.DataFrame
        Rows of ``rawData`` belonging to emitted conductors, ``cluster`` = seed ID.
    finalParabolaTheory : np.ndarray, shape (P, 4)
        Sampled spines ``[x, y, z, seed ID]`` over the corridor.
    """
    xyz = rawData[['x', 'y', 'z']].to_numpy(dtype=float)
    uniq, inv = np.unique(rawData['cluster'].to_numpy(), return_inverse=True)
    K = len(uniq)
    counts = np.bincount(inv, minlength=K)
    testOnY = np.ptp(xyz[:, 1]) > np.ptp(xyz[:, 0])
    ind, dep = (1, 0) if testOnY else (0, 1)
    t, u, z = xyz[:, ind], xyz[:, dep], xyz[:, 2]
    t_min, t_max = min(start_point[ind], end_point[ind]), max(start_point[ind], end_point[ind])

    owner = np.full(K, -1)
    new_labels = rawData['cluster'].to_numpy(copy=True)
    keep = np.zeros(len(xyz), dtype=bool)
    spines = []
    seeds = np.searchsorted(uniq, np.asarray(clusterNumbers))
    for seed in seeds:
        if owner[seed] >= 0:
            continue
        owner[seed] = seed
        members = [seed]
        curve = None
        while True:
            sel = np.isin(inv, members)
            cl = robust_polyfit_huber(t[sel], u[sel], 1)
            cp = robust_polyfit_huber(t[sel], z[sel], 2)
            if len(cl) != 2 or len(cp) != 3:
                curve = None
                break
            curve = (cl, cp)
            r2 = ((u - np.polyval(cl, t)) ** 2 / (1.0 + cl[0] ** 2)
                  + (z - np.polyval(cp, t)) ** 2)
            d = RMSE_HUBER_DELTA_M
            rho2 = np.where(r2 <= d * d, r2, 2.0 * d * np.sqrt(r2) - d * d)
            rmse = np.sqrt(np.bincount(inv, weights=rho2, minlength=K) / counts)
            if len(members) == 1 and rmse[seed] > RMSE_ACCEPT_M:
                curve = None
                break
            free = np.flatnonzero(owner < 0)
            if not len(free):
                break
            best = free[np.argmin(rmse[free])]
            if rmse[best] > RMSE_ACCEPT_M:
                break
            owner[best] = seed
            members.append(best)
        if curve is None:
            for k in members:
                owner[k] = -1
            continue
        cl, cp = curve
        dx = choose_dx_for_line(m_line=cl[0], max_spacing=MIN_DISTANCE_THRESHOLD, snap=0.001, safety=0.85)
        ts = np.arange(t_min, t_max, dx, dtype=float)
        us, zs = np.polyval(cl, ts), np.polyval(cp, ts)
        xs, ys = (us, ts) if testOnY else (ts, us)
        spines.append(np.column_stack((xs, ys, zs, np.full(len(ts), uniq[seed], dtype=float))))
        sel = np.isin(inv, members)
        keep |= sel
        new_labels[sel] = uniq[seed]

    UpdatedCluster = rawData[keep].copy()
    UpdatedCluster['cluster'] = new_labels[keep]
    finalParabolaTheory = np.vstack(spines) if spines else np.empty((0, 4))
    return UpdatedCluster, finalParabolaTheory


def rescueRejectedClusters(rejectedClusters, mergedPoints, lineSpanDistance, name,
                           start_point, end_point, output_dir=MED_ALGO_OUTPUT):
    """
    Recover rejected clusters by merging non-overlapping fragment pairs
    into coherent parabolas.

    Coherence uses the same Huber RMSE as ``rmseMergeClusters``: a fragment
    enters the pool if its RMSE to its own line+parabola is <= RMSE_ACCEPT_M
    and its XY span is >= MIN_DISTANCE_THRESHOLD. A pair is scored by a joint
    fit on both fragments (worst of the two per-fragment RMSEs); the
    lowest-scoring pair is joined first while its score is <= RMSE_ACCEPT_M,
    and scores involving the joined fragment are refreshed. A result is
    emitted when its span exceeds RESCUE_MIN_LENGTH_PERCENTAGE of the corridor.

    Parameters
    ----------
    rejectedClusters : list of int
        Cluster IDs rejected by ``saveFiles``.
    mergedPoints : pd.DataFrame
        Merged wire points (``x, y, z, cluster``) from ``rmseMergeClusters``.
    lineSpanDistance : float
        Corridor length (m).
    name : str
        Output file prefix, e.g. ``'RESCUE_<span>'``.
    start_point, end_point : np.ndarray
        (2,) corridor centre-line endpoints.
    output_dir : str
        Output directory path.

    Returns
    -------
    pd.DataFrame
        Rescued spine samples ``[x, y, z, cluster]`` (empty if none).
    """
    empty_result = pd.DataFrame(columns=['x', 'y', 'z', 'cluster'])

    if not rejectedClusters or mergedPoints.empty:
        return empty_result

    # Corridor geometry
    MinX, MinY = min(start_point[0], end_point[0]), min(start_point[1], end_point[1])
    MaxX, MaxY = max(start_point[0], end_point[0]), max(start_point[1], end_point[1])
    testOnY = (MaxY - MinY > MaxX - MinX)
    ind = 1 if testOnY else 0
    dep = 0 if testOnY else 1
    t_corridor = np.arange(MinY if testOnY else MinX, MaxY if testOnY else MaxX, 0.05, dtype=float)

    def _fit_curve(pts):
        if len(pts) < 5:
            return None
        coeffL = robust_polyfit_huber(pts[:, ind], pts[:, dep], degree=1)
        coeffP = robust_polyfit_huber(pts[:, ind], pts[:, 2], degree=2)
        if len(coeffL) != 2 or len(coeffP) != 3:
            return None
        return coeffL, coeffP

    def _huber_rmse(pts, curve):
        # Same residual and Huber loss as rmseMergeClusters.
        coeffL, coeffP = curve
        t = pts[:, ind]
        r2 = ((pts[:, dep] - np.polyval(coeffL, t)) ** 2 / (1.0 + coeffL[0] ** 2)
              + (pts[:, 2] - np.polyval(coeffP, t)) ** 2)
        d = RMSE_HUBER_DELTA_M
        rho2 = np.where(r2 <= d * d, r2, 2.0 * d * np.sqrt(r2) - d * d)
        return float(np.sqrt(rho2.mean()))

    def _spine(curve):
        coeffL, coeffP = curve
        dep_v = np.polyval(coeffL, t_corridor)
        z_v = np.polyval(coeffP, t_corridor)
        if testOnY:
            return np.column_stack((dep_v, t_corridor, z_v))
        return np.column_stack((t_corridor, dep_v, z_v))

    def _compatible(pa, pb):
        # Reject if fragments overlap along corridor axis (different phases)
        a_min, a_max = pa[:, ind].min(), pa[:, ind].max()
        b_min, b_max = pb[:, ind].min(), pb[:, ind].max()
        shorter = min(a_max - a_min, b_max - b_min)
        if shorter > 0 and (min(a_max, b_max) - max(a_min, b_min)) / shorter > 0.05:
            return False
        # Advanced corridor check: reject end-to-end pairs that are laterally
        # offset (i.e. different phases). Extrapolate the leading fragment's
        # lateral (dep) trend across the gap and compare to the trailing
        # fragment's actual lateral position at its near end.
        leading, trailing = (pa, pb) if a_min <= b_min else (pb, pa)

        # Robust (Huber) linear fit of the leading fragment's lateral trend.
        lateral_slope, lateral_intercept = robust_polyfit_huber(
            leading[:, ind], leading[:, dep], degree=1)

        # Estimate the trailing fragment's lateral position at its near end,
        # using only the points within the junction window closest to the gap.
        junction = trailing[:, ind].min()
        near_end_points = trailing[trailing[:, ind] <= junction + RESCUE_JUNCTION_WINDOW_M]
        if len(near_end_points):
            trailing_lateral = np.median(near_end_points[:, dep])
        else:
            trailing_lateral = trailing[0, dep]

        # Predict where the leading trend lands at the junction and compare.
        predicted_lateral = lateral_slope * junction + lateral_intercept
        return abs(predicted_lateral - trailing_lateral) <= RESCUE_MAX_LATERAL_OFFSET_M

    def _pair_score(fi, fj):
        # Joint fit on both fragments; score = worst per-fragment Huber RMSE.
        pa, pb = fragments[fi]['pts'], fragments[fj]['pts']
        if not _compatible(pa, pb):
            return None
        curve = _fit_curve(np.vstack([pa, pb]))
        if curve is None:
            return None
        score = max(_huber_rmse(pa, curve), _huber_rmse(pb, curve))
        return (score, curve) if score <= RMSE_ACCEPT_M else None

    # --- Build fragment pool (keep only fragments coherent with their own curve) ---
    fragments = {}
    for rc, grp in mergedPoints.loc[
        mergedPoints['cluster'].isin(rejectedClusters), ['x', 'y', 'z', 'cluster']
    ].groupby('cluster', sort=False):
        pts = grp[['x', 'y', 'z']].to_numpy()
        curve = _fit_curve(pts)
        if curve is None or _huber_rmse(pts, curve) > RMSE_ACCEPT_M:
            continue
        xy = pts[:, :2]
        span = float(np.hypot(np.ptp(xy[:, 0]), np.ptp(xy[:, 1])))
        # Guard: fragments shorter than MIN_DISTANCE_THRESHOLD are too unreliable to merge.
        if span < MIN_DISTANCE_THRESHOLD:
            continue
        fragments[rc] = {'pts': pts, 'span': span, 'curve': curve}

    if len(fragments) < 2:
        return empty_result

    # --- Best-first merge: join the pair with the lowest joint Huber RMSE ---
    frag_ids = list(fragments)
    scores = {}
    for i, fi in enumerate(frag_ids):
        for fj in frag_ids[i + 1:]:
            s = _pair_score(fi, fj)
            if s is not None:
                scores[(fi, fj)] = s
    while scores:
        (fi, fj), (_, curve) = min(scores.items(), key=lambda kv: kv[1][0])
        merged_pts = np.vstack([fragments[fi]['pts'], fragments[fj]['pts']])
        xy = merged_pts[:, :2]
        fragments[fi] = {
            'pts': merged_pts,
            'span': float(np.hypot(np.ptp(xy[:, 0]), np.ptp(xy[:, 1]))),
            'curve': curve,
        }
        del fragments[fj]
        scores = {p: s for p, s in scores.items() if fi not in p and fj not in p}
        for fk in fragments:
            if fk != fi:
                s = _pair_score(fi, fk)
                if s is not None:
                    scores[(fi, fk)] = s

    # --- Emit accepted fragments ---
    min_span = RESCUE_MIN_LENGTH_PERCENTAGE * lineSpanDistance
    rescued_chunks = []

    for fid, f in fragments.items():
        if f['span'] <= min_span:
            continue
        spine = _spine(f['curve'])
        parabola_arr = np.column_stack((spine, np.full(len(spine), fid)))
        createLasFile(pd.DataFrame(parabola_arr, columns=['x', 'y', 'z', 'cluster']),
                      f'{name}_{fid}', output_dir)
        rescued_chunks.append(parabola_arr)
        print(f'  Rescued cluster {fid} (span: {f["span"]:.1f}m, '
              f'Huber RMSE: {_huber_rmse(f["pts"], f["curve"]):.3f}m)')

    if rescued_chunks:
        result = pd.DataFrame(np.vstack(rescued_chunks), columns=['x', 'y', 'z', 'cluster'])
        print(f'  Total rescued phases: {result["cluster"].nunique()}')
        return result
    return empty_result