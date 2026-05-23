"""Preprocess FJS benchmark files into reusable instance data files.

The script reads every ``.fjs`` file in the current directory, parses the
flexible job-shop processing data, derives transport-related matrices and
operation precedence relations, and writes one output file per input instance.
JSON is used by default because it is language-independent and convenient for
archival release with a paper repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path
from pprint import pformat
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


def stable_seed(instance_name: str, base_seed: int = 20260523) -> int:
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

    Only earlier operations of the same product may be selected as predecessors;
    therefore, the resulting precedence graph is acyclic by construction.
    """
    priority_dict: dict[str, list[str]] = {}

    for product_id in sorted(product_operations):
        operation_keys = [f"o{product_id}_{idx}" for idx in range(1, product_operations[product_id] + 1)]
        for index, operation_key in enumerate(operation_keys):
            possible_predecessors = operation_keys[:index]
            if not possible_predecessors or rng.random() >= predecessor_probability:
                priority_dict[operation_key] = []
                continue

            predecessor_count = rng.randint(1, min(max_predecessors, len(possible_predecessors)))
            predecessors = rng.sample(possible_predecessors, predecessor_count)
            priority_dict[operation_key] = sorted(predecessors, key=operation_sort_key)

    return priority_dict


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
        "transport_times": distances,
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


def write_python(instance: dict[str, Any], output_path: Path) -> None:
    """Write a preprocessed instance as a Python module with uppercase variables."""
    lines = [
        '"""Preprocessed benchmark instance generated from an FJS file."""',
        "",
        f"METADATA = {pformat(instance['metadata'], width=100, sort_dicts=False)}",
        f"BASE_INFO = {pformat(instance['base_info'], width=100, sort_dicts=False)}",
        f"NUM_PRODUCTS = {instance['base_info']['num_products']}",
        f"NUM_OPERATIONS = {instance['base_info']['num_operations']}",
        f"NUM_UNITS = {instance['base_info']['num_units']}",
        f"NUM_AGVS_W = {instance['base_info']['num_agvs_w']}",
        f"NUM_AGVS_F = {instance['base_info']['num_agvs_f']}",
        f"SPEED_W = {instance['base_info']['speed_w']}",
        f"SPEED_F = {instance['base_info']['speed_f']}",
        f"PRODUCT_OPERATIONS = {pformat(instance['product_operations'], width=100, sort_dicts=False)}",
        f"UNIT_COORDINATES = {pformat(instance['unit_coordinates'], width=100, sort_dicts=False)}",
        f"DISTANCES = {pformat(instance['distances'], width=100, sort_dicts=False)}",
        f"AGV_W_TRANSPORT_TIMES = {pformat(instance['agv_w_transport_times'], width=100, sort_dicts=False)}",
        f"AGV_F_TRANSPORT_TIMES = {pformat(instance['agv_f_transport_times'], width=100, sort_dicts=False)}",
        "TRANSPORT_TIMES = DISTANCES.copy()",
        f"PROCESSING_TIMES = {pformat(instance['processing_times'], width=100, sort_dicts=False)}",
        f"PRIORITY_DICT = {pformat(instance['priority_dict'], width=100, sort_dicts=False)}",
        f"STATISTICS = {pformat(instance['statistics'], width=100, sort_dicts=False)}",
        "",
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")


def preprocess_folder(
    input_dir: Path,
    output_dir: Path,
    output_format: str = "json",
    overwrite: bool = True,
    base_seed: int = 20260523,
) -> list[Path]:
    """Preprocess all FJS files in a directory in lexicographic order."""
    writers = {"json": write_json, "py": write_python}
    suffix = f".{output_format}"
    output_paths: list[Path] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    for fjs_path in sorted(input_dir.glob("*.fjs")):
        output_path = output_dir / f"{fjs_path.stem}{suffix}"
        if output_path.exists() and not overwrite:
            raise FileExistsError(f"{output_path.name} already exists. Use --overwrite to replace it.")

        instance = build_instance(fjs_path, base_seed)
        writers[output_format](instance, output_path)
        output_paths.append(output_path)

    return output_paths


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description="Preprocess all .fjs benchmark files in a folder into JSON or Python data files."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory containing .fjs files. Defaults to the current working directory.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for generated files. Defaults to <input-dir>/data.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "py"),
        default="json",
        help="Output file format. JSON is recommended for paper repositories.",
    )
    parser.add_argument(
        "--base-seed",
        type=int,
        default=20260523,
        help="Base seed used to derive deterministic instance-specific random seeds.",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Fail if an output file already exists.",
    )
    return parser.parse_args()


def main() -> None:
    """Run folder-level preprocessing."""
    args = parse_args()
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve() if args.output_dir else input_dir / "data"
    output_paths = preprocess_folder(
        input_dir=input_dir,
        output_dir=output_dir,
        output_format=args.format,
        overwrite=not args.no_overwrite,
        base_seed=args.base_seed,
    )

    print(f"Processed {len(output_paths)} FJS instance(s).")
    print(f"Output directory: {output_dir}")
    for output_path in output_paths:
        print(f"  {output_path.name}")


if __name__ == "__main__":
    main()
