"""Preprocess raw FJS benchmark files into scale-specific JSON instances.

The script reads every ``.fjs`` file from ``rawdata/`` by default, parses the
flexible job-shop processing data, derives transport-related matrices and
operation precedence relations, and writes renamed JSON instances into
``IFASSP_S/``, ``IFASSP_M/``, and ``IFASSP_L/``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any


HEADER_FIELDS = (
    "num_products",
    "num_operations",
    "num_units",
    "num_agvs_w",
    "num_agvs_f",
    "speed_w",
    "speed_f",
)

WAREHOUSE = "Warehouse"
DEFAULT_WAREHOUSE_COORDS = (0.5, 0.5)
SCALE_RULES = (
    ("small", "IFASSP-S", "IFASSP_S", 0, 49),
    ("medium", "IFASSP-M", "IFASSP_M", 50, 150),
    ("large", "IFASSP-L", "IFASSP_L", 151, None),
)
MAPPING_FIELDS = (
    "original_instance_name",
    "original_file",
    "scale_class",
    "renamed_instance_name",
    "renamed_file",
    "num_products",
    "num_operations",
    "num_units",
    "num_agvs_w",
    "num_agvs_f",
    "speed_w",
    "speed_f",
)


def stable_seed(instance_name: str, base_seed: int = 20260521) -> int:
    """Return a reproducible seed for each instance name."""
    digest = hashlib.sha256(instance_name.encode("utf-8")).hexdigest()
    return (int(digest[:16], 16) + base_seed) % (2**32)


def parse_number(token: str) -> int | float:
    """Parse integer-like values as int and decimal values as float."""
    value = float(token)
    return int(value) if value.is_integer() else value


def read_fjs(path: Path) -> dict[str, Any]:
    """Parse a benchmark file in the extended FJS format used in this folder."""
    tokens = path.read_text(encoding="utf-8").split()
    if len(tokens) < len(HEADER_FIELDS):
        raise ValueError(f"{path.name}: expected at least seven header values.")

    header_values = [parse_number(token) for token in tokens[: len(HEADER_FIELDS)]]
    base_info = dict(zip(HEADER_FIELDS, header_values))
    index = len(HEADER_FIELDS)

    product_operations: dict[int, int] = {}
    processing_times: dict[str, dict[int, int | float]] = {}

    for product_id in range(1, int(base_info["num_products"]) + 1):
        if index >= len(tokens):
            raise ValueError(f"{path.name}: missing operation count for product {product_id}.")

        operation_count = int(parse_number(tokens[index]))
        index += 1
        product_operations[product_id] = operation_count

        for operation_id in range(1, operation_count + 1):
            if index >= len(tokens):
                raise ValueError(
                    f"{path.name}: missing machine-option count for operation "
                    f"o{product_id}_{operation_id}."
                )

            option_count = int(parse_number(tokens[index]))
            index += 1
            operation_key = f"o{product_id}_{operation_id}"
            processing_times[operation_key] = {}

            for _ in range(option_count):
                if index + 1 >= len(tokens):
                    raise ValueError(f"{path.name}: incomplete machine-time pair for {operation_key}.")

                unit_id = int(parse_number(tokens[index]))
                processing_time = parse_number(tokens[index + 1])
                index += 2
                if not 1 <= unit_id <= int(base_info["num_units"]):
                    raise ValueError(
                        f"{path.name}: invalid unit id {unit_id} in {operation_key}; "
                        f"expected an integer between 1 and {base_info['num_units']}."
                    )
                processing_times[operation_key][unit_id] = processing_time

    if index != len(tokens):
        extra = len(tokens) - index
        raise ValueError(f"{path.name}: {extra} unused token(s) remain after parsing.")

    declared_operations = int(base_info["num_operations"])
    parsed_operations = sum(product_operations.values())
    if declared_operations != parsed_operations:
        raise ValueError(
            f"{path.name}: header declares {declared_operations} operations, "
            f"but {parsed_operations} operations were parsed."
        )

    return {
        "base_info": base_info,
        "product_operations": product_operations,
        "processing_times": processing_times,
    }


def generate_unit_coordinates(num_units: int, rng: random.Random) -> dict[str, tuple[float, float]]:
    """Generate reproducible coordinates for the warehouse and assembly units."""
    coordinates = {WAREHOUSE: DEFAULT_WAREHOUSE_COORDS}
    for unit_id in range(1, num_units + 1):
        coordinates[f"M{unit_id}"] = (round(rng.random(), 6), round(rng.random(), 6))
    return coordinates


def max_processing_time(processing_times: dict[str, dict[int, int | float]]) -> int | float:
    """Return the maximum processing time among all feasible operation-unit pairs."""
    values = [time for unit_times in processing_times.values() for time in unit_times.values()]
    if not values:
        raise ValueError("Processing-time data are empty.")
    return max(values)


def generate_distances(
    processing_times: dict[str, dict[int, int | float]],
    coordinates: dict[str, tuple[float, float]],
) -> dict[str, dict[str, int]]:
    """Compute the scaled Euclidean distance matrix."""
    scale = max_processing_time(processing_times)
    distances: dict[str, dict[str, int]] = {}

    for origin, origin_xy in coordinates.items():
        distances[origin] = {}
        for destination, destination_xy in coordinates.items():
            if origin == destination:
                distances[origin][destination] = 0
                continue

            euclidean_distance = math.dist(origin_xy, destination_xy)
            distances[origin][destination] = round(scale * euclidean_distance)

    return distances


def divide_distance_matrix(
    distances: dict[str, dict[str, int]],
    speed: int | float,
) -> dict[str, dict[str, int]]:
    """Convert distances into rounded travel times for a given AGV speed."""
    if speed <= 0:
        raise ValueError("AGV speed must be positive.")

    return {
        origin: {destination: round(distance / speed) for destination, distance in row.items()}
        for origin, row in distances.items()
    }


def generate_priority_dict(
    product_operations: dict[int, int],
    rng: random.Random,
    predecessor_probability: float = 0.7,
    max_predecessors: int = 3,
) -> dict[str, list[str]]:
    """Generate reproducible within-product predecessor sets.

    A random topological order is sampled for each product. Predecessors are
    then selected only from operations that appear earlier in this sampled
    order, which makes the precedence relations random while preserving
    acyclicity.
    """
    priority_dict: dict[str, list[str]] = {}

    for product_id in sorted(product_operations):
        operation_keys = [f"o{product_id}_{idx}" for idx in range(1, product_operations[product_id] + 1)]
        topological_order = operation_keys[:]
        rng.shuffle(topological_order)

        for index, operation_key in enumerate(topological_order):
            possible_predecessors = topological_order[:index]
            if not possible_predecessors or rng.random() >= predecessor_probability:
                priority_dict[operation_key] = []
                continue

            predecessor_count = rng.randint(1, min(max_predecessors, len(possible_predecessors)))
            predecessors = rng.sample(possible_predecessors, predecessor_count)
            priority_dict[operation_key] = sorted(predecessors, key=operation_sort_key)

    return dict(sorted(priority_dict.items(), key=lambda item: operation_sort_key(item[0])))


def operation_sort_key(operation_key: str) -> tuple[int, int]:
    """Sort operation identifiers of the form ``o<product>_<operation>`` numerically."""
    product_part, operation_part = operation_key.removeprefix("o").split("_")
    return int(product_part), int(operation_part)


def stringify_nested_keys(value: Any) -> Any:
    """Convert dictionary keys to strings for stable JSON serialization."""
    if isinstance(value, dict):
        return {str(key): stringify_nested_keys(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [stringify_nested_keys(item) for item in value]
    if isinstance(value, list):
        return [stringify_nested_keys(item) for item in value]
    return value


def build_instance(path: Path, base_seed: int) -> dict[str, Any]:
    """Create the complete preprocessed data object for one FJS file."""
    parsed = read_fjs(path)
    seed = stable_seed(path.stem, base_seed)
    rng = random.Random(seed)

    base_info = parsed["base_info"]
    product_operations = parsed["product_operations"]
    processing_times = parsed["processing_times"]

    unit_coordinates = generate_unit_coordinates(int(base_info["num_units"]), rng)
    distances = generate_distances(processing_times, unit_coordinates)
    agv_w_transport_times = divide_distance_matrix(distances, base_info["speed_w"])
    agv_f_transport_times = divide_distance_matrix(distances, base_info["speed_f"])
    priority_dict = generate_priority_dict(product_operations, rng)

    operations_with_predecessors = sum(1 for predecessors in priority_dict.values() if predecessors)
    total_precedence_relations = sum(len(predecessors) for predecessors in priority_dict.values())

    instance = {
        "metadata": {
            "instance_name": path.stem,
            "source_file": path.name,
            "format_version": "1.0",
            "generator": Path(__file__).name,
            "deterministic_seed": seed,
        },
        "base_info": base_info,
        "product_operations": product_operations,
        "unit_coordinates": unit_coordinates,
        "distances": distances,
        "agv_w_transport_times": agv_w_transport_times,
        "agv_f_transport_times": agv_f_transport_times,
        "processing_times": processing_times,
        "priority_dict": priority_dict,
        "statistics": {
            "max_processing_time": max_processing_time(processing_times),
            "operations_with_predecessors": operations_with_predecessors,
            "total_precedence_relations": total_precedence_relations,
            "average_predecessors_per_operation": round(
                total_precedence_relations / int(base_info["num_operations"]), 6
            ),
        },
    }
    return stringify_nested_keys(instance)


def write_json(instance: dict[str, Any], output_path: Path) -> None:
    """Write a preprocessed instance as UTF-8 JSON."""
    output_path.write_text(
        json.dumps(instance, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def scale_class(num_operations: int) -> tuple[str, str, str]:
    """Return the scale label, filename prefix, and output directory name."""
    for label, prefix, directory, lower, upper in SCALE_RULES:
        if num_operations >= lower and (upper is None or num_operations <= upper):
            return label, prefix, directory
    raise ValueError(f"Unsupported operation count: {num_operations}")


def prepare_output_dirs(root_dir: Path) -> dict[str, Path]:
    """Create scale directories and remove stale generated JSON files."""
    output_dirs: dict[str, Path] = {}
    for _, _, directory, _, _ in SCALE_RULES:
        output_dir = root_dir / directory
        output_dir.mkdir(parents=True, exist_ok=True)
        for old_file in output_dir.glob("*.json"):
            old_file.unlink()
        output_dirs[directory] = output_dir
    return output_dirs


def mapping_row(
    original_name: str,
    source_path: Path,
    scale_label: str,
    new_name: str,
    output_path: Path,
    base_info: dict[str, Any],
    root_dir: Path,
) -> dict[str, Any]:
    """Build one CSV mapping row."""
    return {
        "original_instance_name": original_name,
        "original_file": source_path.relative_to(root_dir).as_posix(),
        "scale_class": scale_label,
        "renamed_instance_name": new_name,
        "renamed_file": output_path.relative_to(root_dir).as_posix(),
        "num_products": base_info["num_products"],
        "num_operations": base_info["num_operations"],
        "num_units": base_info["num_units"],
        "num_agvs_w": base_info["num_agvs_w"],
        "num_agvs_f": base_info["num_agvs_f"],
        "speed_w": base_info["speed_w"],
        "speed_f": base_info["speed_f"],
    }


def write_mapping_csv(rows: list[dict[str, Any]], path: Path) -> None:
    """Write the instance-name mapping table."""
    with path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=MAPPING_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def preprocess_folder(input_dir: Path, root_dir: Path, base_seed: int = 20260521) -> tuple[list[Path], list[dict[str, Any]]]:
    """Preprocess all FJS files into scale-specific JSON folders."""
    output_dirs = prepare_output_dirs(root_dir)
    counters = {label: 0 for label, _, _, _, _ in SCALE_RULES}
    output_paths: list[Path] = []
    mapping_rows: list[dict[str, Any]] = []

    instances = []
    for fjs_path in sorted(input_dir.glob("*.fjs")):
        instance = build_instance(fjs_path, base_seed)
        instances.append((fjs_path, instance))

    instances.sort(
        key=lambda item: (
            [rule[0] for rule in SCALE_RULES].index(scale_class(int(item[1]["base_info"]["num_operations"]))[0]),
            int(item[1]["base_info"]["num_operations"]),
            item[0].stem,
        )
    )

    for fjs_path, instance in instances:
        base_info = instance["base_info"]
        label, prefix, directory = scale_class(int(base_info["num_operations"]))
        counters[label] += 1
        new_name = f"{prefix}{counters[label]:02d}"
        output_path = output_dirs[directory] / f"{new_name}.json"

        instance["metadata"]["original_instance_name"] = fjs_path.stem
        instance["metadata"]["instance_name"] = new_name
        write_json(instance, output_path)
        output_paths.append(output_path)
        mapping_rows.append(mapping_row(fjs_path.stem, fjs_path, label, new_name, output_path, base_info, root_dir))

    return output_paths, mapping_rows


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description="Preprocess raw .fjs files into scale-specific JSON benchmark folders."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("rawdata"),
        help="Directory containing raw .fjs files. Defaults to ./rawdata.",
    )
    parser.add_argument(
        "--base-seed",
        type=int,
        default=20260521,
        help="Base seed used to derive deterministic instance-specific random seeds.",
    )
    parser.add_argument(
        "--mapping-file",
        type=Path,
        default=Path("instance_name_mapping.csv"),
        help="CSV file used to record original and renamed instance names.",
    )
    return parser.parse_args()


def main() -> None:
    """Run folder-level preprocessing."""
    args = parse_args()
    root_dir = Path.cwd().resolve()
    input_dir = args.input_dir.resolve()
    mapping_file = args.mapping_file.resolve()
    output_paths, mapping_rows = preprocess_folder(
        input_dir=input_dir,
        root_dir=root_dir,
        base_seed=args.base_seed,
    )
    write_mapping_csv(mapping_rows, mapping_file)

    print(f"Processed {len(output_paths)} instance(s).")
    for label, _, directory, _, _ in SCALE_RULES:
        count = sum(1 for row in mapping_rows if row["scale_class"] == label)
        print(f"  {directory}: {count}")
    print(f"Mapping file: {mapping_file}")


if __name__ == "__main__":
    main()
