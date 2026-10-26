# MED-ALGo V2

**Medium-voltage wire detection from LiDAR point clouds.**

MED-ALGo processes `.las` / `.laz` LiDAR files to automatically detect, cluster, and model medium-voltage power lines as parabolic curves.

### Notes

- Profiling is enabled by default. Set `enable_profiling=False` to suppress the timing summary.
- NumPy `RankWarning` messages during parabola fitting are non-fatal and indicate a poorly conditioned polynomial fit for a particular cluster.



#### Coordinate System & Reprojection

All distance thresholds in MED-ALGo are expressed in **metres**. The pipeline's correctness therefore depends on input coordinates being in a **metric unit system**.

- If your LAS files have no embedded CRS, the pipeline assumes they are already in the target EPSG and skips reprojection automatically.

Use the following decision table to set `skip_reprojection`:

| Input LAS coordinate system | Unit | `skip_reprojection` | Notes |
|-----------------------------|------|---------------------|-------|
| Any **projected** CRS (UTM, Quebec Lambert, State Plane, …) | metres | `True` | Already metric — no transformation needed |
| Pre-normalized / local origin (coordinates translated to 0,0,0) | metres (relative) | `True` | Relative distances preserved — reprojection would corrupt coordinates |
| **Geographic** CRS (WGS84 EPSG:4326, NAD83, …) | **degrees** | `False` | **Must reproject** — degree-based coordinates break all metre thresholds |

> **Rule of thumb:** if your coordinates look like `(683500, 5093000, 42.5)` or `(0.5, 320.1, 12.3)` they are in metres → use `skip_reprojection=True`.  
> If they look like `(-73.5678, 45.1234, 42.5)` they are in degrees → set `skip_reprojection=False` and provide the appropriate `target_epsg`.

---





## Pipeline overview

| Stage | Description |
|-------|-------------|
| **1. Clustering** | Reads each LAS file, optionally reprojects to the target CRS (default EPSG:2950), and clusters wire points with HDBSCAN in an anisotropic (s, n, z) frame using an adaptive `min_cluster_size`. |
| **2. Candidate filtering** | Removes clusters that are too short or perpendicular to the main line axis. |
| **3. Huber RMSE merge** | Grows each seed cluster (longest first) by best-first merging of the free cluster with the lowest Huber RMSE to the seed's line + parabola, while RMSE <= `RMSE_ACCEPT_M`. |
| **4. Span gate** | Conductors covering more than `ACCEPTED_SEGMENT_LENGTH_PERCENTAGE` of the span are written as `FINAL_<name>_<id>.las`. |
| **5. Rescue** | Rejected fragments are paired best-first by joint Huber RMSE and written as `RESCUE_<name>_<id>.las`. |

---

## Installation for MED-ALGo

Refer to the main project [README.md](../../README.md) to install this algo.

## Usage

### 1. Prepare your data

Place your `.las` or `.laz` files **directly** in the input directory. Each file must contain a point attribute column named **`lacvnet`** with classification values (files without it are skipped automatically).

Expected input requirements:
- The expected dimension name is **`lacvnet`**.
- The expected wire class value is **`1`**.

> **The input directory is scanned non-recursively.** Only `.las` / `.laz` files located **at the top level** of the input directory are processed. Files inside sub-folders are **ignored**. If your data is organized in nested sub-directories, point the pipeline at the exact leaf folder that contains the files (see below).

**Default input directory**

The default input directory is defined in [`constants.py`](constants.py) as `MED_ALGO_INPUT = './input/'`. You can override it at runtime with the `--input-dir` parameter — handy to target a specific nested folder:

```bash
# Target a precise leaf folder containing the .las files
med-algo --input-dir ./input/TestSet/one_main_gap/HV
```


### 2. Run the pipeline

**From the command line (after installation):**

```bash
# Runs with defaults (./input/ → ./output/)
med-algo  
# Override the input directory (non-recursive: point to the exact folder of files)
med-algo --input-dir ./input/TestSet/one_main_gap/HV
# Override the output directory
med-algo --output-dir ./my_results/
```

**From Python code:**

```python
from med_algo import run_pipeline

if __name__ == '__main__':
    timings = run_pipeline(
        input_dir='./input/',
        output_dir='./output/',
        target_epsg=2950,          # Quebec Lambert (default)
        skip_reprojection=True,    # if input already in metres
        enable_profiling=True,     # Print timing breakdown
    )
    
    print("\n" + "="*50)
    print("Pipeline execution completed successfully!")
    print("="*50)
```

### 3. Check results

Output LAS files are written to the `output/` directory, prefixed with `FINAL_`. The console prints the number of detected phases per file and a profiling summary at the end.

---

## Configuration

Key parameters can be adjusted in `src/med_algo/constants.py`:

| Constant | Default | Description |
|----------|---------|-------------|
| `QUEBEC_EPSG` | `2950` | Target EPSG code for reprojection |
| `HDBSCAN_MIN_CLUSTER_DISTANCE_ACCEPTANCE` | `0.3` | HDBSCAN `cluster_selection_epsilon` (scaled frame) |
| `MIN_SAMPLE` | `3` | HDBSCAN `min_samples` |
| `MIN_ACCEPTED_DISTANCE_SEGMENT_M` | `0.10` | Minimum segment span to keep (meters) |
| `MINIMUM_NUMBER_POWERLINE_POINTS` | `20` | Minimum points required to proceed to parabola fitting |
| `MIN_DISTANCE_THRESHOLD` | `0.1` | Spine sampling step and minimum rescue-fragment span (m) |
| `RMSE_ACCEPT_M` | `0.30` | Max Huber RMSE for a cluster to join the seed conductor |
| `RMSE_HUBER_DELTA_M` | `0.10` | Huber loss delta (residuals beyond this count linearly) |
| `ACCEPTED_SEGMENT_LENGTH_PERCENTAGE` | `0.55` | Span fraction a conductor must cover to be emitted |
| `MEDIUM_VOLTAGE_WIRE_CLASS_NUMBER` | `1` | Classification value for medium-voltage wires |
| `LACVNET_COLUMN` | `'lacvnet'` | Scalar field name containing the wire classification |

---

## Running Tests for MED-ALGo

If you installed with development tools (`pip install -e '.[dev]'`), you can run tests:

```bash
python -m pytest tests/med_algo -v
```

Or with coverage reports:

```bash
python -m pytest tests/med_algo -v --cov=med_algo
```

All tests should pass.

---

## Performance benchmark (`test_Performance.py`)

`tests/test_Performance.py` is a standalone evaluation script (not a unit test). It runs
the full pipeline on every span of the test set and scores the detected conductors
against the ground truth, producing precision / recall / F1 metrics.

### Expected data layout

```
input/TestSet/<Category>/<WireType>/<span>_<degradation>.las
input/GroundTruth/<WireType>/FINAL_<span>_0_<id>.las
```

### Run it

From the project root:

```bash
python tests/test_Performance.py
```

### Output

Results are written to `output/performance/`:

| File | Description |
|------|-------------|
| `performance_results.csv` | Per-file metrics (Expected, Detected, TP, FP, FN, Precision, Recall, F1, time) |
| `performance_summary.csv` | Per-category / wire-type breakdown plus an `ALL` total row |
| `performance_f1_matrix.csv` | F1 pivot: rows = Category/WireType, columns = degradation level |
| `<Category>/<WireType>/<span>/` | The `FINAL_*` / `RESCUE_*` conductor LAS files for each span |

The console also prints an overall `TP / FP / FN / Precision / Recall / F1` line and a
per-category breakdown. The `output/performance/` directory is cleaned at the start of
each run.
