#!/usr/bin/env python3
"""Summarize VillagerBench score.json files into paper-style averages."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def infer_task_type(score: dict, folder_name: str) -> str:
    if "block_hit_rate" in score or "view_hit_rate" in score:
        return "construction"
    if "score" in score and "cooperation" in score:
        return "farming"
    if "complete_score" in score or "complexity_score" in score:
        return "puzzle"
    for name in ["construction", "farming", "puzzle", "escape", "meta"]:
        if name in folder_name:
            return "puzzle" if name == "escape" else name
    return "unknown"


def metrics_for(task_type: str, score: dict) -> dict:
    if task_type == "construction":
        return {
            "C": score.get("block_hit_rate", 0) * 100,
            "VHR": score.get("view_hit_rate", 0) * 100,
            "E": score.get("efficiency", 0),
            "B": score.get("balance", 0),
        }
    if task_type == "farming":
        return {
            "C": score.get("score", 0),
            "ACR": score.get("cooperation", 0),
            "E": score.get("efficiency", 0),
            "B": score.get("balance", 0),
        }
    if task_type == "puzzle":
        return {
            "C": score.get("complete_score", 0) * 100,
            "E": score.get("efficiency", 0),
            "B": score.get("balance", 0),
            "complexity": score.get("complexity_score", 0),
        }
    return {}


def summarize(result_dir: Path):
    groups = defaultdict(list)
    skipped = []

    for score_path in sorted(result_dir.glob("*/score.json")):
        try:
            score = load_json(score_path)
        except json.JSONDecodeError:
            skipped.append((score_path.parent.name, "invalid score.json"))
            continue

        config_path = score_path.parent / "config.json"
        config = load_json(config_path) if config_path.exists() else {}
        task_type = config.get("task_type") or infer_task_type(score, score_path.parent.name)
        api_model = config.get("api_model", "unknown")
        agent_num = config.get("agent_num", "unknown")
        metrics = metrics_for(task_type, score)
        if not metrics:
            skipped.append((score_path.parent.name, "unknown metric schema"))
            continue

        groups[(task_type, api_model, agent_num)].append(metrics)

    return groups, skipped


def print_summary(groups):
    for (task_type, api_model, agent_num), rows in sorted(groups.items()):
        keys = sorted({key for row in rows for key in row})
        averages = {key: mean(row.get(key, 0) for row in rows) for key in keys}
        metric_text = " ".join(f"{key}={averages[key]:.3f}" for key in keys)
        print(f"{task_type:13} model={api_model:22} agents={agent_num} n={len(rows):3} {metric_text}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", default="result")
    args = parser.parse_args()

    groups, skipped = summarize(Path(args.result_dir))
    print_summary(groups)
    if skipped:
        print("\nSkipped:")
        for name, reason in skipped:
            print(f"  {name}: {reason}")


if __name__ == "__main__":
    main()
