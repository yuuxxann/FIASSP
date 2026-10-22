# FIASSP Benchmark Instances

This repository provides benchmark instances for the flexible island assembly shop scheduling problem (FIASSP), together with a reproducible preprocessing script that converts raw `.fjs` files into structured JSON data. The instances are intended to support comparative computational studies involving assembly units, base-workpiece AGVs, and component-kit AGVs. Everyone is welcome to use these results as a comparative baseline.

## Repository Contents

The raw instances are stored in `rawdata/` as plain-text `.fjs` files derived from the Fattahi, Kumar, and Behnke benchmark families. The preprocessing script writes renamed JSON instances directly into three scale-specific folders:

| Folder                | Scale rule                      |
| --------------------- | ------------------------------- |
| `FIASSP_S/`  | `num_operations < 50`        |
| `FIASSP_M/` | `50 <= num_operations <= 150` |
| `FIASSP_L/`  | `num_operations > 150`        |

The file `instance_name_mapping.csv` records the correspondence between the original raw instance names and the renamed benchmark names, together with the `base_info` fields for each instance.

## Raw FJS Format

The first line of each `.fjs` file contains seven scalar values:

| Field              | Description                          |
| ------------------ | ------------------------------------ |
| `NUM_PRODUCTS`   | Number of products or jobs.          |
| `NUM_OPERATIONS` | Total number of operations.          |
| `NUM_UNITS`      | Number of assembly units.            |
| `NUM_AGVS_W`     | Number of base-workpiece AGVs.       |
| `NUM_AGVS_F`     | Number of component-kit AGVs.        |
| `speed_w`        | Travel speed of base-workpiece AGVs. |
| `speed_f`        | Travel speed of component-kit AGVs.  |

The remaining content describes products sequentially. For each product, the first value is the number of operations. For each operation, the first value is the number of feasible assembly units, followed by repeated `(unit_id, processing_time)` pairs:

```text
number_of_feasible_units unit_1 processing_time_1 unit_2 processing_time_2 ...
```

Operations are indexed as `o<i>_<j>`, where `i` denotes the product and `j` denotes the operation position within that product.

## Preprocessing Procedure

Run the preprocessing script from the repository root:

```bash
python data_preprocessing.py
```

By default, the script reads all `.fjs` files from `rawdata/`, validates the declared operation count, assigns deterministic coordinates to the warehouse and assembly units, computes a scaled Euclidean distance matrix, and derives separate travel-time matrices for base-workpiece and component-kit AGVs. For each product, a random topological order of its operations is first sampled; predecessor relations are then randomly selected from operations that appear earlier in this sampled order, so the resulting precedence graph is random but acyclic by construction.

The generated instances are renamed using compact academic benchmark identifiers: `FIASSP-Sxx`, `FIASSP-Mxx`, and `FIASSP-Lxx`. The original raw instance name is preserved in the JSON metadata as `original_instance_name` and is also listed in `instance_name_mapping.csv`.

## Processed JSON Fields

Each JSON file contains the following fields:

| Field                     | Description                                                                                                     |
| ------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `metadata`              | Instance name, original instance name, source filename, generator name, format version, and deterministic seed. |
| `base_info`             | Header information parsed from the`.fjs` file.                                                                |
| `product_operations`    | Number of operations for each product.                                                                          |
| `unit_coordinates`      | Coordinates of the warehouse and assembly units.                                                                |
| `distances`             | Scaled distance matrix.                                                                                         |
| `agv_w_transport_times` | Travel-time matrix for base-workpiece AGVs.                                                                     |
| `agv_f_transport_times` | Travel-time matrix for component-kit AGVs.                                                                      |
| `processing_times`      | Feasible assembly-unit processing times for each operation.                                                     |
| `priority_dict`         | Predecessor operations for each operation.                                                                      |
| `statistics`            | Summary statistics derived during preprocessing.                                                                |

## Reproducibility

All random quantities are generated from deterministic instance-specific seeds. The default base seed is `20260521`; it can be changed explicitly:

```bash
python data_preprocessing.py --base-seed 20260521
```

Using the same raw files and seed reproduces the same coordinates, distance matrices, travel-time matrices, precedence relations, renamed JSON files, and mapping table.
