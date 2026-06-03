#!/usr/bin/env python3
"""Generate launch configs for the VillagerAgent paper experiments.

The generated JSON files are compatible with start_with_config.py.
They are intentionally deterministic and do not call any LLM APIs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


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


def clean_name(value: str) -> str:
    return (
        value.replace("-", "_")
        .replace(".", "_")
        .replace(" ", "_")
        .replace("/", "_")
        .replace(":", "_")
    )


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def base_config(args, task_type: str, task_idx: int, agent_num: int, task_goal: str, task_name: str):
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


def construction_configs(args, repo_root: Path):
    task_count = min(args.construction_tasks, len(load_json(repo_root / "data/blueprint_description_all.json")))
    model = clean_name(args.api_model)
    configs = []
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
    return configs


def farming_configs(args, repo_root: Path):
    settings = load_json(repo_root / "data/farm_setting.json")
    task_count = min(args.farming_tasks, len(settings))
    model = clean_name(args.api_model)
    configs = []
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
    return configs


def escape_configs(args, repo_root: Path):
    # The paper describes 25 escape tasks as five difficulty levels with fixed seeds.
    # In this codebase, max_task_num controls generated puzzle length and task_idx is
    # passed as the StateTree seed.
    _ = load_json(repo_root / "data/escape_atom.json")
    model = clean_name(args.api_model)
    configs = []
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


def write_config(configs, output_dir: Path, name: str):
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / name
    with path.open("w", encoding="utf-8") as f:
        json.dump(configs, f, indent=2)
    print(f"Wrote {len(configs)} configs to {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=["construction", "farming", "escape", "all"], default="all")
    parser.add_argument("--api-model", default="gpt-4-1106-preview")
    parser.add_argument("--api-base", default="https://api.openai.com/v1")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=25565)
    parser.add_argument("--output-dir", default="paper_configs")
    parser.add_argument("--construction-agents", type=int, default=2)
    parser.add_argument("--farming-agents", type=int, default=2)
    parser.add_argument("--escape-agents", type=int, default=2)
    parser.add_argument("--construction-tasks", type=int, default=100)
    parser.add_argument("--farming-tasks", type=int, default=100)
    parser.add_argument("--escape-seeds", type=int, default=5)
    parser.add_argument("--escape-difficulties", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    output_dir = repo_root / args.output_dir
    model = clean_name(args.api_model)

    if args.suite in ["construction", "all"]:
        write_config(
            construction_configs(args, repo_root),
            output_dir,
            f"{model}_paper_construction_config.json",
        )

    if args.suite in ["farming", "all"]:
        write_config(
            farming_configs(args, repo_root),
            output_dir,
            f"{model}_paper_farming_config.json",
        )

    if args.suite in ["escape", "all"]:
        write_config(
            escape_configs(args, repo_root),
            output_dir,
            f"{model}_paper_escape_config.json",
        )


if __name__ == "__main__":
    main()
