# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import numpy as np
import pandas as pd
import pytest

from med_algo.geometry import (
    create_center_line,
    getMinMaxDistance,
    distance_2d_from_bounds,
    choose_dx_for_line,
)


def test_create_center_line_horizontal():
    pts = np.array([[0, 0], [10, 0], [5, 0.1], [5, -0.1]])
    start, end = create_center_line(pts)
    # The line should run roughly along X
    assert abs(start[0] - end[0]) > 5


def test_getMinMaxDistance():
    df = pd.DataFrame({'x': [0.0, 3.0], 'y': [0.0, 4.0]})
    assert pytest.approx(getMinMaxDistance(df), abs=1e-6) == 5.0


def test_distance_2d_from_bounds_scalar():
    assert pytest.approx(distance_2d_from_bounds(0, 3, 0, 4), abs=1e-6) == 5.0


def test_choose_dx_for_line_flat():
    dx = choose_dx_for_line(0.0, max_spacing=0.10, snap=0.001, safety=1.0)
    assert 0 < dx <= 0.10
