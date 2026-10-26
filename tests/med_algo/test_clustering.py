# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import numpy as np

from med_algo.clustering import _adaptive_min_cluster_size
from med_algo.constants import MCS_FLOOR, MCS_CEIL


def test_adaptive_mcs_clamped():
    assert _adaptive_min_cluster_size(0) == MCS_FLOOR
    assert _adaptive_min_cluster_size(1) == MCS_FLOOR
    assert _adaptive_min_cluster_size(10 ** 12) == MCS_CEIL


def test_adaptive_mcs_monotonic():
    sizes = [_adaptive_min_cluster_size(n) for n in np.logspace(1, 7, 20).astype(int)]
    assert sizes == sorted(sizes)
