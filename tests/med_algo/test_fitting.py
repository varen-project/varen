# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import numpy as np
import pytest

from med_algo.fitting import (
    huber_weights,
    approximateLineOrParabola,
    robust_polyfit_huber,
)


def test_huber_weights_no_outliers():
    resid = np.zeros(10)
    w = huber_weights(resid)
    np.testing.assert_array_equal(w, np.ones(10))


def test_approximateLineOrParabola_line():
    x = np.array([0, 1, 2, 3, 4], dtype=float)
    y = 2.0 * x + 1.0
    coeffs = approximateLineOrParabola(x, y, 1)
    assert len(coeffs) == 2
    assert pytest.approx(coeffs[0], abs=1e-6) == 2.0
    assert pytest.approx(coeffs[1], abs=1e-6) == 1.0


def test_robust_polyfit_huber_parabola():
    x = np.linspace(-5, 5, 50)
    y = 0.5 * x ** 2 - 2.0 * x + 3.0
    coeffs = robust_polyfit_huber(x, y, degree=2)
    assert len(coeffs) == 3
    assert pytest.approx(coeffs[0], abs=1e-3) == 0.5
