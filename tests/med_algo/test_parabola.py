# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Smoke tests for the parabola module."""
import numpy as np
import pandas as pd

from med_algo.parabola import rmseMergeClusters


def test_collinear_segments_merge_into_one_conductor():
    rng = np.random.default_rng(42)
    n = 200
    x = np.linspace(0, 100, n)
    y = 0.5 * x + rng.normal(0, 0.01, n)
    z = 0.001 * x ** 2 - 0.1 * x + 10 + rng.normal(0, 0.01, n)
    cluster = np.where(x < 50, 0, 1)
    df = pd.DataFrame({'x': x, 'y': y, 'z': z, 'cluster': cluster})

    start = np.array([0.0, 0.0])
    end = np.array([100.0, 50.0])

    merged, theory = rmseMergeClusters(df, [0, 1], start, end)
    assert set(merged['cluster'].unique()) == {0}
    assert len(merged) == n
    assert theory.shape[1] == 4
    assert set(np.unique(theory[:, 3])) == {0.0}
