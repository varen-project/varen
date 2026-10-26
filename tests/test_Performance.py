"""
Run the med_algo pipeline on every LAS file of the test set and generate a CSV
performance matrix (TP / FP / FN / Precision / Recall / F1 / time) by
geometric validation of the detected conductors against the ground truth.

Layout expected:
    input/TestSet/<Category>/<WireType>/<span>_<degradation>.las
    input/GroundTruth/<WireType>/FINAL_<span>_0_<id>.las
"""
import contextlib
import io
import os
import shutil
import stat
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import laspy
from scipy.spatial import cKDTree
from scipy.optimize import linear_sum_assignment

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from med_algo.constants import LACVNET_COLUMN, QUEBEC_EPSG  # noqa: E402
from med_algo.io import reproject_las_to_target  # noqa: E402
from med_algo.pipeline import process_las  # noqa: E402

# ─── Configuration ────────────────────────────────────────────────────
INPUT_ROOT  = ROOT / "input" / "TestSet"
GT_ROOT     = ROOT / "input" / "GroundTruth"
OUTPUT_ROOT = ROOT / "output" / "performance"
CSV_PATH    = OUTPUT_ROOT / "performance_results.csv"
SUMMARY_CSV_PATH = OUTPUT_ROOT / "performance_summary.csv"

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
        parts = stem[len("FINAL_"):].rsplit('_', 1)
        if len(parts) == 2:
            gt_map.setdefault(parts[0], []).append(f)
    return gt_map


def get_base_key(input_path):
    """zone_filshape_..._CUT_MONO_25 -> zone_filshape_..._CUT_MONO_0"""
    return input_path.stem.rsplit('_', 1)[0] + '_0'


def read_xyz(path, reproject=False):
    las = laspy.read(str(path))
    if reproject:
        with contextlib.redirect_stdout(io.StringIO()):
            las = reproject_las_to_target(las, QUEBEC_EPSG)
    return np.column_stack([las.x, las.y, las.z])


def build_gt_trees(gt_files):
    """Build one 3D KD-tree per GT conductor (in the pipeline's working CRS)."""
    trees = []
    for f in sorted(gt_files):
        pts = read_xyz(f, reproject=True)
        if len(pts) > 0:
            trees.append(cKDTree(pts))
    return trees


def validate_detected_line(det_pts_3d, gt_tree):
    """Fraction of predicted samples within DISTANCE_THRESHOLD of one GT conductor."""
    distances, _ = gt_tree.query(det_pts_3d)
    return np.sum(distances <= DISTANCE_THRESHOLD) / len(det_pts_3d)


def match_predictions(preds, gt_trees):
    """
    One-to-one matching of predictions to GT conductors.

    rho[j, i] = fraction of samples of prediction j within DISTANCE_THRESHOLD of
    conductor i; pair (j, i) is eligible if rho >= LENGTH_RATIO_THRESHOLD.
    Among eligible pairs, the Hungarian algorithm maximises first the number of
    matched pairs, then the sum of rho. Returns (TP, FP, rho matrix).
    """
    if not preds:
        return 0, 0, np.zeros((0, len(gt_trees)))
    if not gt_trees:
        return 0, len(preds), np.zeros((len(preds), 0))
    rho = np.array([[validate_detected_line(p, t) for t in gt_trees] for p in preds])
    eligible = rho >= LENGTH_RATIO_THRESHOLD
    big = len(preds) + len(gt_trees) + 1   # cardinality dominates the rho tie-break
    rows, cols = linear_sum_assignment(np.where(eligible, big + rho, 0.0), maximize=True)
    tp = int(eligible[rows, cols].sum())
    return tp, len(preds) - tp, rho


def prf(tp, fp, expected):
    det = tp + fp
    p = tp / det * 100 if det else 0
    r = tp / expected * 100 if expected else 0
    f1 = 2 * p * r / (p + r) if (p + r) else 0
    return p, r, f1


# ─── Pipeline driver ─────────────────────────────────────────────────
def process_file(las_path, output_dir):
    """Run process_las on one span, writing conductors to output_dir."""
    las = laspy.read(str(las_path))
    if LACVNET_COLUMN not in las.point_format.dimension_names:
        raise ValueError(f"'{LACVNET_COLUMN}' not in {las_path.name}")
    with contextlib.redirect_stdout(io.StringIO()):
        _, parabolas = process_las(las, las_path.stem, str(output_dir))
    return 0 if parabolas.empty else int(parabolas['cluster'].nunique())


def _force_remove(func, path, exc_info):
    os.chmod(path, stat.S_IWRITE)
    func(path)


# ─── Main ─────────────────────────────────────────────────────────────
def main():
    # Clean output directory to avoid stale files from previous runs
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT, onerror=_force_remove)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    gt_map = build_gt_map()
    print("GT base keys:")
    for k, v in gt_map.items():
        print(f"  {k}: {len(v)} wire(s)")

    las_files = sorted(INPUT_ROOT.rglob("*.las"))
    print(f"\nFound {len(las_files)} input .las files")
    if not las_files:
        return

    gt_trees = {k: build_gt_trees(v) for k, v in gt_map.items()}
    expected_wires = {k: len(v) for k, v in gt_map.items()}

    missing = {get_base_key(f) for f in las_files} - set(gt_map)
    for k in sorted(missing):
        print(f"  WARNING: no ground truth for base key {k}")

    total_expected = sum(expected_wires.get(get_base_key(f), 0) for f in las_files)
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

        print(f"  [{idx}/{len(las_files)}] {category}/{wire_type}/{las_path.name} ... ",
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

        # Geometric validation: one-to-one matching against individual GT conductors
        preds = [p for p in (read_xyz(f) for f in sorted(fd.glob("*.las"))) if len(p) > 0]
        tp, fp, _ = match_predictions(preds, gt_trees.get(base_key, []))
        fn = max(0, expected - tp)
        p_row, r_row, f1_row = prf(tp, fp, expected)

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

    # ── Detailed CSV ──────────────────────────────────────────────────
    df = pd.DataFrame(rows)
    df['_deg'] = pd.to_numeric(df['Degradation_pct'], errors='coerce')
    df = df.sort_values(['Category', 'WireType', '_deg']).drop(columns='_deg')
    df.to_csv(str(CSV_PATH), index=False)
    print(f"\nDetailed CSV saved to: {CSV_PATH}")

    # ── Overall ───────────────────────────────────────────────────────
    tp_total = int(df['TP'].sum())
    fp_total = int(df['FP'].sum())
    fn_total = int(df['FN'].sum())
    precision, recall, f1 = prf(tp_total, fp_total, total_expected)

    total_elapsed = time.perf_counter() - run_start
    print(f"\n{'='*70}")
    print(f"OVERALL: TP={tp_total}  FP={fp_total}  FN={fn_total}  "
          f"P={precision:.1f}%  R={recall:.1f}%  F1={f1:.1f}%")
    print(f"Total processing time: {total_elapsed:.1f}s  "
          f"(avg {total_elapsed/len(las_files):.1f}s/file)")
    print(f"{'='*70}")

    # ── Per-category performance matrix ───────────────────────────────
    summary = []
    print("\nPer-category breakdown:")
    for (cat, wt), grp in df.groupby(['Category', 'WireType']):
        tpg, fpg, fng = int(grp['TP'].sum()), int(grp['FP'].sum()), int(grp['FN'].sum())
        exp_g = int(grp['Expected'].sum())
        p_g, r_g, f1_g = prf(tpg, fpg, exp_g)
        print(f"  {cat}/{wt}: TP={tpg} FP={fpg} FN={fng} "
              f"P={p_g:.0f}% R={r_g:.0f}% F1={f1_g:.0f}%")
        summary.append({'Category': cat, 'WireType': wt, 'Files': len(grp),
                        'Expected': exp_g, 'TP': tpg, 'FP': fpg, 'FN': fng,
                        'Precision': round(p_g, 1), 'Recall': round(r_g, 1),
                        'F1': round(f1_g, 1), 'Time_s': round(grp['Time_s'].sum(), 2)})
    summary.append({'Category': 'ALL', 'WireType': 'ALL', 'Files': len(df),
                    'Expected': total_expected, 'TP': tp_total, 'FP': fp_total,
                    'FN': fn_total, 'Precision': round(precision, 1),
                    'Recall': round(recall, 1), 'F1': round(f1, 1),
                    'Time_s': round(total_elapsed, 2)})
    pd.DataFrame(summary).to_csv(str(SUMMARY_CSV_PATH), index=False)
    print(f"\nSummary CSV saved to: {SUMMARY_CSV_PATH}")

    # ── F1 matrix: rows = Category/WireType, columns = degradation ────
    f1_matrix = df.pivot_table(index=['Category', 'WireType'], columns='Degradation_pct',
                               values='F1', aggfunc='mean')
    f1_matrix = f1_matrix[sorted(f1_matrix.columns, key=lambda c: float(c))]
    f1_path = OUTPUT_ROOT / "performance_f1_matrix.csv"
    f1_matrix.to_csv(str(f1_path))
    print(f"F1 matrix saved to: {f1_path}")


if __name__ == "__main__":
    main()
