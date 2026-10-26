# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from pathlib import Path

import laspy
import numpy as np
import pytest

import med_algo.pipeline as pipeline


def _write_minimal_las_with_lacvnet(file_path: Path) -> None:
    """Create the smallest valid LAS file needed to exercise pipeline checks."""
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.add_extra_dim(laspy.ExtraBytesParams(name="lacvnet", type=np.uint8))

    las = laspy.LasData(header)
    las.x = np.array([0.0, 1.0, 2.0])
    las.y = np.array([0.0, 0.0, 0.0])
    las.z = np.array([10.0, 10.1, 10.2])
    las.lacvnet = np.array([1, 1, 1], dtype=np.uint8)
    las.write(str(file_path))


def test_path_traversal_protection_blocks_output_outside_base(tmp_path, monkeypatch):
    base_output = tmp_path / "safe_output"
    input_dir = tmp_path / "input"
    base_output.mkdir()
    input_dir.mkdir()

    monkeypatch.setattr(pipeline, "MED_ALGO_OUTPUT", str(base_output))

    outside_output = tmp_path.parent / "outside_output"
    with pytest.raises(ValueError, match="Invalid output directory path"):
        pipeline.run_pipeline(
            input_dir=str(input_dir),
            output_dir=str(outside_output),
            enable_profiling=False,
        )


def test_invalid_epsg_is_rejected(tmp_path, monkeypatch):
    base_output = tmp_path / "safe_output"
    run_output = base_output / "run"
    input_dir = tmp_path / "input"
    base_output.mkdir()
    input_dir.mkdir()

    monkeypatch.setattr(pipeline, "MED_ALGO_OUTPUT", str(base_output))

    _write_minimal_las_with_lacvnet(input_dir / "sample.las")

    with pytest.raises(ValueError, match="not in the whitelist of allowed codes"):
        pipeline.run_pipeline(
            input_dir=str(input_dir),
            output_dir=str(run_output),
            target_epsg=999999999,
            skip_reprojection=False,
            enable_profiling=False,
        )


def test_oversized_las_is_skipped_before_read(tmp_path, monkeypatch, capsys):
    base_output = tmp_path / "safe_output"
    run_output = base_output / "run"
    input_dir = tmp_path / "input"
    base_output.mkdir()
    input_dir.mkdir()

    monkeypatch.setattr(pipeline, "MED_ALGO_OUTPUT", str(base_output))
    monkeypatch.setattr(pipeline, "MAX_FILE_SIZE", 8)

    oversized_file = input_dir / "too_large.las"
    oversized_file.write_bytes(b"x" * 64)

    def _unexpected_read(*args, **kwargs):
        raise AssertionError("laspy.read should not be called for oversized files")

    monkeypatch.setattr(pipeline.laspy, "read", _unexpected_read)

    timings = pipeline.run_pipeline(
        input_dir=str(input_dir),
        output_dir=str(run_output),
        enable_profiling=False,
    )

    captured = capsys.readouterr()
    assert "exceeds MAX_FILE_SIZE" in captured.out
    assert isinstance(timings, dict)
