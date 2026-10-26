# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
Run the pipeline on all files and generate a CSV report
with per-file detection counts and geometric validation against GT.
"""
import os, traceback, time
from pathlib import Path
import numpy as np
import pandas as pd
import laspy
from scipy.spatial import cKDTree
from med_algo.constants import LACVNET_COLUMN, MED_ALGO_INPUT, MED_ALGO_OUTPUT
from med_algo.pipeline import process_las

# ─── Configuration ────────────────────────────────────────────────────
INPUT_ROOT  = Path(MED_ALGO_INPUT) / "TestSet"
GT_ROOT     = Path(MED_ALGO_INPUT) / "GroundTruth"
OUTPUT_ROOT = Path(MED_ALGO_OUTPUT)
CSV_PATH    = Path(MED_ALGO_OUTPUT) / "Results.csv"

DISTANCE_THRESHOLD     = 0.15   # 15 cm proximity
LENGTH_RATIO_THRESHOLD = 0.80   # 80% coverage for TP


# ─── GT helpers ───────────────────────────────────────────────────────
def build_gt_map():
    """Map base_key -> list of GT LAS file paths."""
    gt_map = {}
    for f in GT_ROOT.rglob("*.las"):
        stem = f.stem
        if not stem.startswith("FINAL_"):
            continue
        inner = stem[len("FINAL_"):]
        parts = inner.rsplit('_', 1)
        if len(parts) == 2:
            gt_map.setdefault(parts[0], []).append(f)
    return gt_map


def get_base_key(input_path):
    """zone_filshape_..._CUT_MONO_25 -> zone_filshape_..._CUT_MONO_0"""
    stem = input_path.stem
    parts = stem.rsplit('_', 1)
    return parts[0] + '_0'


def build_gt_tree(gt_files):
    """Build a combined 3D KD-tree from GT LAS files."""
    all_pts = []
    for f in gt_files:
        las = laspy.read(str(f))
        pts = np.column_stack([las.x, las.y, las.z])
        if len(pts) > 0:
            all_pts.append(pts)
    if not all_pts:
        return None
    return cKDTree(np.vstack(all_pts))


def validate_detected_line(det_pts_3d, gt_tree):
    if gt_tree is None:
        return 0.0
    distances, _ = gt_tree.query(det_pts_3d)
    return np.sum(distances <= DISTANCE_THRESHOLD) / len(det_pts_3d)


# ─── Pipeline driver ─────────────────────────────────────────────────
def process_file(las_path, output_dir):
    las = laspy.read(str(las_path))
    if LACVNET_COLUMN not in las.point_format.dimension_names:
        raise ValueError(f"'{LACVNET_COLUMN}' not in {las_path.name}")

    _, parabolas = process_las(las, las_path.stem, str(output_dir))
    if parabolas.empty:
        return 0
    return int(parabolas['cluster'].nunique())


# ─── Main ─────────────────────────────────────────────────────────────
def main():
    # Clean output directory to avoid stale files from previous runs
    import shutil, stat
    def _force_remove(func, path, exc_info):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT, onerror=_force_remove)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    gt_map = build_gt_map()
    print("GT base keys:")
    for k, v in gt_map.items():
        print(f"  {k}: {len(v)} wire(s)")

    las_files = sorted(INPUT_ROOT.rglob("*.las"))
    print(f"\nFound {len(las_files)} input .las files")

    # Pre-build GT KD-trees
    gt_trees = {}
    expected_wires = {}
    for base_key, gt_files in gt_map.items():
        gt_trees[base_key] = build_gt_tree(gt_files)
        expected_wires[base_key] = len(gt_files)

    total_expected = sum(
        expected_wires.get(get_base_key(f), 0) for f in las_files)
    print(f"Total expected GT wires: {total_expected}\n")

    rows = []
    run_start = time.perf_counter()

    for idx, las_path in enumerate(las_files, 1):
        base_key = get_base_key(las_path)
        expected = expected_wires.get(base_key, 0)

        rel = las_path.relative_to(INPUT_ROOT)
        category  = rel.parts[0] if len(rel.parts) > 1 else ""
        wire_type = rel.parts[1] if len(rel.parts) > 2 else ""
        deg_str   = las_path.stem.rsplit('_', 1)[-1]

        fd = OUTPUT_ROOT / category / wire_type / las_path.stem
        fd.mkdir(parents=True, exist_ok=True)

        print(f"  [{idx}/{len(las_files)}] "
              f"{category}/{wire_type}/{las_path.name} ... ",
              end="", flush=True)
        t_file = time.perf_counter()
        try:
            n_detected = process_file(las_path, fd)
            elapsed_file = time.perf_counter() - t_file
            tag = "OK" if n_detected == expected else "MISMATCH"
            print(f"{n_detected} detected (expected {expected}) [{tag}] ({elapsed_file:.1f}s)")
        except Exception as e:
            elapsed_file = time.perf_counter() - t_file
            n_detected = 0
            print(f"ERROR: {e} ({elapsed_file:.1f}s)")
            traceback.print_exc()

        # Geometric validation
        gt_tree = gt_trees.get(base_key)
        tp = fp = 0
        det_files = sorted(fd.glob("*.las")) if fd.exists() else []
        for det_file in det_files:
            det_las = laspy.read(str(det_file))
            det_pts = np.column_stack([det_las.x, det_las.y, det_las.z])
            if len(det_pts) == 0:
                continue
            ratio = validate_detected_line(det_pts, gt_tree)
            if ratio >= LENGTH_RATIO_THRESHOLD:
                tp += 1
            else:
                fp += 1

        fn = max(0, expected - tp)
        det = tp + fp
        p_row = tp / det * 100 if det else 0
        r_row = tp / expected * 100 if expected else 0
        f1_row = 2 * p_row * r_row / (p_row + r_row) if (p_row + r_row) else 0
        rows.append({
            'Category': category,
            'WireType': wire_type,
            'Degradation_pct': deg_str,
            'File': las_path.name,
            'Expected': expected,
            'Detected': n_detected,
            'TP': tp,
            'FP': fp,
            'FN': fn,
            'Precision': round(p_row, 1),
            'Recall': round(r_row, 1),
            'F1': round(f1_row, 1),
            'Time_s': round(elapsed_file, 2),
        })

    # ── Build CSV ─────────────────────────────────────────────────────
    df = pd.DataFrame(rows)
    df.to_csv(str(CSV_PATH), index=False)
    print(f"\nDetailed CSV saved to: {CSV_PATH}")

    # ── Summary ───────────────────────────────────────────────────────
    tp_total = int(df['TP'].sum())
    fp_total = int(df['FP'].sum())
    fn_total = int(df['FN'].sum())
    detected_total = tp_total + fp_total
    precision = tp_total / detected_total * 100 if detected_total else 0
    recall = tp_total / total_expected * 100 if total_expected else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

    total_elapsed = time.perf_counter() - run_start
    print(f"\n{'='*70}")
    print(f"OVERALL: TP={tp_total}  FP={fp_total}  FN={fn_total}  "
          f"P={precision:.1f}%  R={recall:.1f}%  F1={f1:.1f}%")
    print(f"Total processing time: {total_elapsed:.1f}s  "
          f"(avg {total_elapsed/len(las_files):.1f}s/file)")
    print(f"{'='*70}")

    print("\nPer-category breakdown:")
    for (cat, wt), grp in df.groupby(['Category', 'WireType']):
        tpg = int(grp['TP'].sum())
        fpg = int(grp['FP'].sum())
        fng = int(grp['FN'].sum())
        det_g = tpg + fpg
        p_g = tpg / det_g * 100 if det_g else 0
        exp_g = int(grp['Expected'].sum())
        r_g = tpg / exp_g * 100 if exp_g else 0
        f1_g = 2 * p_g * r_g / (p_g + r_g) if (p_g + r_g) else 0
        print(f"  {cat}/{wt}: TP={tpg} FP={fpg} FN={fng} "
              f"P={p_g:.0f}% R={r_g:.0f}% F1={f1_g:.0f}%")


if __name__ == "__main__":
    main()
