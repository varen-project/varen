# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import time


def _now():
    """Return a high-resolution timestamp used for profiling."""
    return time.perf_counter()


def _add_timing(stats, key, start):
    """Accumulate elapsed time for a profiling key."""
    stats[key] = stats.get(key, 0.0) + (_now() - start)
