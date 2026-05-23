# FJS Instance Data Preprocessing

This repository contains flexible job-shop scheduling (FJS) benchmark instances
and a reproducible preprocessing script for generating directly usable instance
data files. The preprocessed files are intended for academic use in scheduling
experiments involving assembly units, workpiece AGVs, and material AGVs.

## File Structure

Each raw instance is stored as a plain-text `.fjs` file. The first line contains
seven scalar values in the following order:

| Field | Description |
| --- | --- |
| `NUM_PRODUCTS` | Number of products or jobs. |
| `NUM_OPERATIONS` | Total number of operations across all products. |
| `NUM_UNITS` | Number of assembly units or alternative processing units. |
| `NUM_AGVS_W` | Number of workpiece AGVs. |
| `NUM_AGVS_F` | Number of material AGVs. |
| `speed_w` | Travel speed of workpiece AGVs. |
| `speed_f` | Travel speed of material AGVs. |

After the header, each product is described sequentially. For product `i`, the
first value is the number of operations assigned to that product. For each
operation, the next value is the number of feasible assembly units for that
operation, followed by repeated `(unit_id, processing_time)` pairs. Therefore,
one operation block has the following structure:

```text
number_of_feasible_units unit_1 processing_time_1 unit_2 processing_time_2 ...
```

The preprocessing script names operations as `o<i>_<j>`, where `i` is the
product index and `j` is the operation index within that product.

## Preprocessing Method

Run the preprocessing script from the repository root:

```bash
python data_preprocessing.py
```

By default, the script reads all `.fjs` files in the current folder and writes
one `.json` file for each instance into the `data/` directory, using the same
base filename. JSON is the default output format because it is
language-independent, easy to validate, and suitable for public research
repositories.

The script performs the following steps for each instance:

1. Parse the seven header values directly from the first line.
2. Parse product-level operation counts and operation-level feasible
   assembly-unit processing times.
3. Validate that the parsed number of operations matches `NUM_OPERATIONS`.
4. Generate deterministic coordinates for the warehouse and assembly units.
   The warehouse is fixed at `(0.5, 0.5)`, and assembly-unit coordinates are
   generated from an instance-specific deterministic seed.
5. Compute the distance matrix as the rounded scaled Euclidean distance:

```text
distance(i, j) = round(max_processing_time * EuclideanDistance(i, j))
```

6. Compute workpiece-AGV and material-AGV travel-time matrices by dividing the
   distance matrix by `speed_w` and `speed_f`, respectively.
7. Generate deterministic within-product precedence relations. Only earlier
   operations of the same product can be predecessors, so the precedence graph
   is acyclic by construction.
8. Write the preprocessed data object to disk.

If an input file fails strict structural validation, the script skips that file
and records the reason in `preprocessing_errors.json`. This prevents one
malformed instance from interrupting the preprocessing of the complete
benchmark folder while preserving a transparent audit trail.

## Output Data Fields

Each generated JSON file contains the following top-level fields:

| Field | Description |
| --- | --- |
| `metadata` | Instance name, source filename, generator name, format version, and deterministic seed. |
| `base_info` | Header information parsed from the `.fjs` file. |
| `product_operations` | Number of operations for each product. |
| `unit_coordinates` | Coordinates of the warehouse and assembly units. |
| `distances` | Scaled distance matrix. |
| `agv_w_transport_times` | Travel-time matrix for workpiece AGVs. |
| `agv_f_transport_times` | Travel-time matrix for material AGVs. |
| `transport_times` | Backward-compatible alias of `distances`. |
| `processing_times` | Feasible unit-processing-time mapping for each operation. |
| `priority_dict` | Predecessor list for each operation. |
| `statistics` | Summary statistics derived during preprocessing. |

## Optional Python Output

If a Python module is preferred, run:

```bash
python data_preprocessing.py --format py
```

This creates one `.py` file per `.fjs` instance in the `data/` directory, with
uppercase variable names such as `NUM_PRODUCTS`, `PROCESSING_TIMES`,
`DISTANCES`, and `PRIORITY_DICT`.

## Reproducibility

All derived random quantities are generated from deterministic seeds based on
the instance filename and the script-level base seed. Running the same command
on the same `.fjs` files will therefore reproduce identical coordinates,
distance matrices, transport-time matrices, and precedence relations.

The default base seed is `20260523`. It can be changed explicitly:

```bash
python data_preprocessing.py --base-seed 20260523
```

## Suggested Manuscript Description

The raw benchmark instances were first parsed from the `.fjs` files, where the
header specifies the numbers of products, operations, assembly units, workpiece
AGVs and material AGVs, together with the corresponding AGV speeds. For each
product, the operation sequence and all feasible assembly-unit processing times
were extracted and encoded as structured instance data. A deterministic
instance-specific seed was then used to generate the warehouse and assembly-unit
coordinates, from which a scaled Euclidean distance matrix was computed using
the maximum processing time as the scaling factor. Workpiece- and material-AGV
travel-time matrices were obtained by dividing the distance matrix by the
respective AGV speeds. Finally, within-product precedence relations were
generated only from earlier operations of the same product, ensuring that the
resulting precedence graph is acyclic and reproducible.

## Data Integrity Note

The current folder contains one invalid raw file, `kumar10.fjs`. Strict parsing
reports an invalid assembly-unit identifier in operation `o4_1`, where the file
contains unit id `13` although the header declares only four assembly units.
This file is therefore skipped by default and documented in
`preprocessing_errors.json`.
