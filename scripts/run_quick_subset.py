#!/usr/bin/env python3
"""Generate and optionally run a small VillagerBench subset.

The subset is intended for quick methodology checks. It preserves existing
launch-config fields when pointed at a full config directory, then selects only
1-3 tasks per difficulty level for each benchmark suite.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


CONSTRUCTION_GOAL = (
    "Using the provided blueprint, please collaborate to place blocks in Minecraft. "
    "You can use materials from both your inventory and the chest. The task is complete "
    "once the blueprint is fully built."
)

CAKE_GOAL = (
    "You are on a farm where you need to collaborate to make a cake. Some ingredients "
    "are contained within chests, and if the ingredients are not in the chests, you may "
    "need to work together to acquire them. Crafting table is placed to craft items"
)

RABBIT_STEW_GOAL = (
    "You are on a farm where you need to collaborate to make a rabbit_stew. Some "
    "ingredients are contained within chests, and if the ingredients are not in the "
    "chests, you may need to work together to acquire them. Crafting table is placed "
    "to craft items"
)

PUZZLE_GOAL = (
    "Attention all agents, you are tasked with a cooperative multi-stage escape "
    "challenge. Each 10x10 room requires teamwork to solve puzzles and overcome "
    "obstacles. Be advised that you may be separated into different rooms, where direct "
    "collaboration isn't always possible. Despite this, leverage your strengths to "
    "progress as a unit. Upon task completion, you'll either be transported to the next "
    "room or the path will clear for you to proceed on foot. The rooms are aligned along "
    "the z-axis, with the center points spaced 10 units apart. Your final objective is to "
    "reach the exit at coordinates 130, -60, -140. Coordinate, adapt, and work together "
    "to escape. Good luck!"
)

SUITE_ORDER = ["construction", "farming", "escape"]
TASK_TYPE_TO_SUITE = {
    "construction": "construction",
    "farming": "farming",
    "puzzle": "escape",
}

MILK_SOURCES = ["milk_bucket in chest", "bucket in chest", "iron_ingot in chest"]
WHEAT_SOURCES = ["wheat in chest", "hay_block in chest", "wheat in farm", "hay_block in farm"]
SUGAR_SOURCES = ["sugar in chest", "sugar_cane in chest", "sugar_cane in farm"]

COOKED_RABBIT_SOURCES = ["rabbit in chest", "rabbit in pasture"]
BAKED_POTATO_SOURCES = ["potato in chest", "potato in farm"]
CARROT_SOURCES = ["carrot in chest", "carrot in farm"]
BROWN_MUSHROOM_SOURCES = ["brown_mushroom in chest", "brown_mushroom in farm"]
BOWL_SOURCES = ["bowl in chest", "acacia_log in pasture"]
COAL_SOURCES = ["coal in chest", "coal in mine"]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def clean_name(value: str) -> str:
    return (
        value.replace("-", "_")
        .replace(".", "_")
        .replace(" ", "_")
        .replace("/", "_")
        .replace(":", "_")
    )


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def resolve_path(root: Path, path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def base_config(args: argparse.Namespace, task_type: str, task_idx: int, agent_num: int, task_goal: str, task_name: str) -> dict[str, Any]:
    return {
        "api_model": args.api_model,
        "api_base": args.api_base,
        "task_type": task_type,
        "task_idx": task_idx,
        "agent_num": agent_num,
        "dig_needed": False,
        "max_task_num": 0,
        "task_goal": task_goal,
        "document_file": "",
        "host": args.host,
        "port": args.port,
        "task_name": task_name,
    }


def generated_configs(args: argparse.Namespace, root: Path) -> list[dict[str, Any]]:
    model = clean_name(args.api_model)
    configs: list[dict[str, Any]] = []

    if args.suite in ["all", "construction"]:
        descriptions = load_json(root / "data/blueprint_description_all.json")
        task_count = min(args.construction_tasks, len(descriptions))
        for idx in range(task_count):
            config = base_config(
                args,
                task_type="construction",
                task_idx=idx,
                agent_num=args.construction_agents,
                task_goal=CONSTRUCTION_GOAL,
                task_name=f"{model}_construction_task{idx}_{args.construction_agents}p",
            )
            config["document_file"] = "data/map_description.json"
            configs.append(config)

    if args.suite in ["all", "farming"]:
        settings = load_json(root / "data/farm_setting.json")
        task_count = min(args.farming_tasks, len(settings))
        for idx in range(task_count):
            goal = CAKE_GOAL if "cake" in settings[idx]["name"] else RABBIT_STEW_GOAL
            config = base_config(
                args,
                task_type="farming",
                task_idx=idx,
                agent_num=args.farming_agents,
                task_goal=goal,
                task_name=f"{model}_farming_task{idx}_{args.farming_agents}p",
            )
            config["document_file"] = "data/recipe_hint.json"
            configs.append(config)

    if args.suite in ["all", "escape"]:
        for max_task_num in args.escape_difficulties:
            for seed in range(args.escape_seeds):
                config = base_config(
                    args,
                    task_type="puzzle",
                    task_idx=seed,
                    agent_num=args.escape_agents,
                    task_goal=PUZZLE_GOAL,
                    task_name=f"{model}_puzzle_seed{seed}_tasks{max_task_num}_{args.escape_agents}p",
                )
                config["max_task_num"] = max_task_num
                configs.append(config)

    return configs


def load_source_configs(args: argparse.Namespace, root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    files: list[Path] = []
    for source_dir in args.source_dir:
        files.extend(sorted(resolve_path(root, source_dir).glob("*.json")))
    for source_config in args.source_config:
        files.append(resolve_path(root, source_config))

    configs: list[dict[str, Any]] = []
    source_files: list[str] = []
    for path in files:
        data = load_json(path)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            raise ValueError(f"{path} must contain a config object or list of configs")
        source_files.append(str(path.relative_to(root) if path.is_relative_to(root) else path))
        configs.extend(config for config in data if isinstance(config, dict))

    return dedupe_configs(configs), source_files


def dedupe_configs(configs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, int, int]] = set()
    unique: list[dict[str, Any]] = []
    for config in configs:
        suite = suite_for_config(config)
        if suite is None:
            continue
        key = (suite, int(config.get("task_idx", -1)), int(config.get("max_task_num", 0)))
        if key in seen:
            continue
        seen.add(key)
        unique.append(config)
    return unique


def suite_for_config(config: dict[str, Any]) -> str | None:
    return TASK_TYPE_TO_SUITE.get(str(config.get("task_type", "")))


def construction_complexity(blueprint: dict[str, Any], height_weight: float = 0.02, dig_needed: bool = False) -> float:
    blocks = blueprint["blocks"]
    block_positions = {tuple(block["position"]) for block in blocks}
    ground_level = min(block["position"][1] for block in blocks) - 1
    complexity = 0.0
    dig_num = 0

    for block in blocks:
        x, y, z = block["position"]
        if block["name"] in {"air", "water", "lava"}:
            continue

        if dig_needed and ("log" in block["name"] or "stone" in block["name"]):
            dig_num += 1

        connect_paths = []
        for dx, dy, dz in [(-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1)]:
            if (x + dx, y + dy, z + dz) in block_positions:
                connect_paths.append([dx, dy, dz])
        if y == ground_level:
            connect_paths.append([0, -1, 0])

        facing = block.get("facing", "A")
        filtered_paths = []
        for path in connect_paths:
            if facing == "W" and path == [-1, 0, 0]:
                continue
            if facing == "E" and path == [1, 0, 0]:
                continue
            if facing == "S" and path == [0, 0, -1]:
                continue
            if facing == "N" and path == [0, 0, 1]:
                continue
            if facing == "x" and path not in [[0, -1, 0], [0, 1, 0]]:
                continue
            if facing == "y" and path not in [[-1, 0, 0], [1, 0, 0]]:
                continue
            if facing == "z" and path not in [[0, 0, -1], [0, 0, 1]]:
                continue
            filtered_paths.append(path)

        complexity += (1 / (len(filtered_paths) + 1) + (y - ground_level) * height_weight) * 2

    if dig_needed:
        complexity += dig_num
    return complexity


def construction_metrics(root: Path, task_indices: set[int] | None = None) -> dict[int, dict[str, Any]]:
    blueprints = load_json(root / "data/building_blue_print.json")
    metrics: dict[int, dict[str, Any]] = {}
    indexes = sorted(task_indices) if task_indices is not None else range(len(blueprints))
    for idx in indexes:
        if idx < 0 or idx >= len(blueprints):
            continue
        blueprint = blueprints[idx]
        count = sum(1 for block in blueprint["blocks"] if block["name"] not in {"air", "water", "lava"})
        metrics[idx] = {
            "complexity": construction_complexity(blueprint),
            "block_count": count,
            "blueprint": blueprint.get("name", ""),
        }
    return metrics


def farming_complexity(task: dict[str, Any]) -> int:
    if "cake" in task["name"]:
        return (
            MILK_SOURCES.index(task["milk"])
            + WHEAT_SOURCES.index(task["wheat"])
            + SUGAR_SOURCES.index(task["sugar"])
            + 3
        )

    return (
        COOKED_RABBIT_SOURCES.index(task["cooked_rabbit"])
        + BAKED_POTATO_SOURCES.index(task["baked_potato"])
        + CARROT_SOURCES.index(task["carrot"])
        + BROWN_MUSHROOM_SOURCES.index(task["brown_mushroom"])
        + BOWL_SOURCES.index(task["bowl"])
        + COAL_SOURCES.index(task["coal"])
        + 6
    )


def farming_metrics(root: Path) -> dict[int, dict[str, Any]]:
    settings = load_json(root / "data/farm_setting.json")
    return {
        idx: {
            "complexity": farming_complexity(task),
            "recipe": task.get("name", ""),
        }
        for idx, task in enumerate(settings)
    }


def split_buckets(items: list[dict[str, Any]], bucket_count: int) -> list[list[dict[str, Any]]]:
    buckets: list[list[dict[str, Any]]] = []
    for bucket_idx in range(bucket_count):
        start = bucket_idx * len(items) // bucket_count
        end = (bucket_idx + 1) * len(items) // bucket_count
        buckets.append(items[start:end])
    return buckets


def level_labels(bucket_count: int) -> list[str]:
    if bucket_count == 3:
        return ["easy", "medium", "hard"]
    return [f"level_{idx + 1}" for idx in range(bucket_count)]


def pick_from_bucket(bucket: list[dict[str, Any]], per_level: int, selection: str) -> list[dict[str, Any]]:
    if len(bucket) <= per_level:
        return bucket
    if selection == "first":
        return bucket[:per_level]

    if per_level == 1:
        return [bucket[len(bucket) // 2]]

    indexes = [round(idx * (len(bucket) - 1) / (per_level - 1)) for idx in range(per_level)]
    picked: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index in indexes:
        if index not in seen:
            picked.append(bucket[index])
            seen.add(index)

    for index, item in enumerate(bucket):
        if len(picked) >= per_level:
            break
        if index not in seen:
            picked.append(item)
    return picked


def suffix_task_name(task_name: str, suffix: str) -> str:
    if not suffix:
        return task_name
    normalized = suffix if suffix.startswith("_") else f"_{suffix}"
    return f"{task_name}{normalized}"


def selected_config(record: dict[str, Any], suffix: str) -> dict[str, Any]:
    config = copy.deepcopy(record["config"])
    config["task_name"] = suffix_task_name(str(config["task_name"]), suffix)
    return config


def select_ranked_suite(
    suite: str,
    configs: list[dict[str, Any]],
    metrics: dict[int, dict[str, Any]],
    bucket_count: int,
    per_level: int,
    selection: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ranked = []
    for config in configs:
        idx = int(config["task_idx"])
        if idx not in metrics:
            continue
        item = {
            "suite": suite,
            "level": "",
            "config": config,
            **metrics[idx],
        }
        ranked.append(item)

    ranked.sort(key=lambda item: (item["complexity"], int(item["config"]["task_idx"])))
    buckets = split_buckets(ranked, bucket_count)
    labels = level_labels(bucket_count)

    selected: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    for label, bucket in zip(labels, buckets):
        for item in bucket:
            item["level"] = label
        picked = pick_from_bucket(bucket, per_level, selection)
        selected.extend(picked)
        summary[label] = {
            "available": len(bucket),
            "selected": len(picked),
            "complexity_min": bucket[0]["complexity"] if bucket else None,
            "complexity_max": bucket[-1]["complexity"] if bucket else None,
        }

    return selected, summary


def select_escape_suite(
    configs: list[dict[str, Any]],
    per_level: int,
    selection: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_level: dict[int, list[dict[str, Any]]] = {}
    for config in configs:
        level = int(config.get("max_task_num", 0))
        by_level.setdefault(level, []).append(
            {
                "suite": "escape",
                "level": f"level_{level}",
                "complexity": level,
                "config": config,
            }
        )

    selected: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    for level in sorted(by_level):
        bucket = sorted(by_level[level], key=lambda item: int(item["config"]["task_idx"]))
        picked = pick_from_bucket(bucket, per_level, selection)
        selected.extend(picked)
        summary[f"level_{level}"] = {
            "available": len(bucket),
            "selected": len(picked),
            "max_task_num": level,
        }
    return selected, summary


def build_subset(args: argparse.Namespace, root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_configs, source_files = load_source_configs(args, root)
    configs = source_configs if source_configs else dedupe_configs(generated_configs(args, root))
    enabled_suites = SUITE_ORDER if args.suite == "all" else [args.suite]

    construction_indices = {
        int(config.get("task_idx", -1))
        for config in configs
        if suite_for_config(config) == "construction"
    }
    construction = construction_metrics(root, construction_indices) if "construction" in enabled_suites else {}
    farming = farming_metrics(root) if "farming" in enabled_suites else {}

    selected_records: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    for suite in enabled_suites:
        suite_configs = [config for config in configs if suite_for_config(config) == suite]
        if suite == "construction":
            selected, suite_summary = select_ranked_suite(
                suite,
                suite_configs,
                construction,
                args.non_escape_levels,
                args.per_level,
                args.selection,
            )
        elif suite == "farming":
            selected, suite_summary = select_ranked_suite(
                suite,
                suite_configs,
                farming,
                args.non_escape_levels,
                args.per_level,
                args.selection,
            )
        elif suite == "escape":
            selected, suite_summary = select_escape_suite(suite_configs, args.per_level, args.selection)
        else:
            continue
        selected_records.extend(selected)
        summary[suite] = suite_summary

    if not selected_records:
        raise SystemExit("No tasks were selected. Check --suite and --source-dir/--source-config.")

    selected_configs = [selected_config(record, args.task_name_suffix) for record in selected_records]
    metadata = {
        "source": source_files or "generated_from_arguments",
        "settings": {
            "suite": args.suite,
            "per_level": args.per_level,
            "selection": args.selection,
            "non_escape_levels": args.non_escape_levels,
            "task_name_suffix": args.task_name_suffix,
        },
        "summary": summary,
        "selected": [metadata_record(record, config) for record, config in zip(selected_records, selected_configs)],
    }
    return selected_configs, metadata


def metadata_record(record: dict[str, Any], output_config: dict[str, Any]) -> dict[str, Any]:
    config = record["config"]
    entry = {
        "suite": record["suite"],
        "level": record["level"],
        "task_type": config["task_type"],
        "task_idx": config["task_idx"],
        "max_task_num": config.get("max_task_num", 0),
        "complexity": record.get("complexity"),
        "task_name": output_config["task_name"],
        "source_task_name": config.get("task_name"),
    }
    for key in ["block_count", "blueprint", "recipe"]:
        if key in record:
            entry[key] = record[key]
    return entry


def run_subset(args: argparse.Namespace, root: Path, output_path: Path) -> None:
    start_script = resolve_path(root, args.start_script)
    env = os.environ.copy()
    env.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-villager")
    env.setdefault("XDG_CACHE_HOME", "/tmp/.cache-villager")
    subprocess.run(
        [args.python, str(start_script), "--config", str(output_path)],
        cwd=root,
        env=env,
        check=True,
    )


def default_output_path(args: argparse.Namespace, root: Path) -> Path:
    model = clean_name(args.api_model)
    suite = "all" if args.suite == "all" else args.suite
    return root / "paper_configs" / "quick_subset" / f"{model}_{suite}_{args.per_level}x_quick_subset_config.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["all", "construction", "farming", "escape"], default="all")
    parser.add_argument("--per-level", type=int, choices=[1, 2, 3], default=1)
    parser.add_argument("--non-escape-levels", type=int, choices=[2, 3, 4, 5], default=3, help="Difficulty buckets for construction/farming.")
    parser.add_argument("--selection", choices=["first", "spread"], default="first")

    parser.add_argument("--source-dir", action="append", default=[], help="Directory of existing config JSON files to subset.")
    parser.add_argument("--source-config", action="append", default=[], help="Existing config JSON file to subset.")
    parser.add_argument("--output", help="Output config path. Defaults under paper_configs/quick_subset/.")
    parser.add_argument("--metadata-output", help="Metadata JSON path. Defaults next to --output.")
    parser.add_argument("--task-name-suffix", default="quick_subset", help="Suffix appended to result task_name values. Use '' to preserve names.")

    parser.add_argument("--api-model", default="gpt-4o")
    parser.add_argument("--api-base", default="https://api.poe.com/v1")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=25565)
    parser.add_argument("--construction-agents", type=int, default=2)
    parser.add_argument("--farming-agents", type=int, default=2)
    parser.add_argument("--escape-agents", type=int, default=2)
    parser.add_argument("--construction-tasks", type=int, default=100)
    parser.add_argument("--farming-tasks", type=int, default=100)
    parser.add_argument("--escape-seeds", type=int, default=5)
    parser.add_argument("--escape-difficulties", type=int, nargs="+", default=[1, 2, 3, 4, 5])

    parser.add_argument("--run", action="store_true", help="Run start_with_config.py after writing the subset config.")
    parser.add_argument("--python", default=sys.executable, help="Python executable used with --run.")
    parser.add_argument("--start-script", default="start_with_config.py", help="start_with_config.py path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = repo_root()
    output_path = resolve_path(root, args.output) if args.output else default_output_path(args, root)
    metadata_path = (
        resolve_path(root, args.metadata_output)
        if args.metadata_output
        else output_path.with_name(output_path.stem + "_metadata.json")
    )

    selected_configs, metadata = build_subset(args, root)
    write_json(output_path, selected_configs)
    write_json(metadata_path, metadata)

    print(f"Wrote {len(selected_configs)} quick-subset tasks to {output_path}")
    print(f"Wrote selection metadata to {metadata_path}")
    for suite in SUITE_ORDER:
        rows = [row for row in metadata["selected"] if row["suite"] == suite]
        if rows:
            print(f"  {suite}: {len(rows)} tasks")

    if args.run:
        run_subset(args, root, output_path)
    else:
        print(f"Run with: cd {root} && {args.python} {args.start_script} --config {output_path}")


if __name__ == "__main__":
    main()
