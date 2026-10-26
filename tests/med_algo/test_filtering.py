# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import numpy as np
from med_algo.filtering import cleanShortLineCandidates


def test_cleanShortLineCandidates_removes_short():
    # Two clusters: cluster 0 is very short, cluster 1 spans distance > 0.10
    data = np.array([
        [0.0, 0.0, 10.0, 1, 0],
        [0.01, 0.0, 10.0, 1, 0],
        [0.0, 0.0, 10.0, 1, 1],
        [5.0, 5.0, 10.0, 1, 1],
    ])
    result = cleanShortLineCandidates(data, minDistance=0.10)
    clusters_remaining = np.unique(result[:, 4])
    assert 0 not in clusters_remaining
    assert 1 in clusters_remaining
