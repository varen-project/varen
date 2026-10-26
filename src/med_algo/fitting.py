# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import numpy as np
from numpy.polynomial import Polynomial


def huber_weights(resid, c=1.345, scale=None):
    """Compute Huber weights for residuals."""
    if scale is None:
        med = np.median(resid)
        mad = np.median(np.abs(resid - med)) + 1e-12
        scale = 1.4826 * mad
    r = resid / (scale + 1e-12)
    w = np.ones_like(r)
    mask = np.abs(r) > c
    w[mask] = c / np.abs(r[mask])
    return w


def approximateLineOrParabola(x, y, degree):
    """Fit a polynomial and return coefficients ordered from highest degree to constant."""
    p = Polynomial.fit(x, y, deg=degree)
    coefficients = p.convert().coef[::-1]
    if len(coefficients) >= 2:
        return coefficients
    return []


def robust_polyfit_huber(x, y, degree, max_iter=10, c=1.345):
    """Iteratively reweighted least-squares polynomial fit using Huber weights.

    Parameters
    ----------
    x, y : array-like
        Data points.
    degree : int
        Polynomial degree.
    max_iter : int
        Maximum IRLS iterations.
    c : float
        Huber threshold parameter.

    Returns
    -------
    np.ndarray
        Coefficients from highest degree to constant term.
    """
    if len(x) <= 10:
        return approximateLineOrParabola(x, y, degree)

    x = np.asarray(x)
    y = np.asarray(y)
    mask = np.isfinite(x) & np.isfinite(y)
    w = np.ones(mask.sum())
    xx, yy = x[mask], y[mask]

    p = Polynomial.fit(xx, yy, deg=degree, w=w)
    for _ in range(max_iter):
        resid = yy - p(xx)
        w_new = huber_weights(resid, c=c)
        if np.allclose(w_new, w):
            break
        w = w_new
        p = Polynomial.fit(xx, yy, deg=degree, w=w)

    coeffs_low_to_high = p.convert().coef
    return coeffs_low_to_high[::-1]
