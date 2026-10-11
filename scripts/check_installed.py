"""Install the built wheel into a clean venv and exercise it outside the checkout.

Dependencies are read from the wheel. No PYTHONPATH, local .runtime or editable
source is allowed to mask missing package files. No network API is called.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default="dist")
    parser.add_argument("--wheelhouse", help="optional predownloaded dependencies; disables index access")
    args = parser.parse_args(argv)
    wheels = sorted(Path(args.directory).resolve().glob("*.whl"))
    if len(wheels) != 1:
        parser.error("expected exactly one built wheel")
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONUTF8"] = "1"
    with tempfile.TemporaryDirectory(prefix="foresight-installed-") as temporary:
        target = Path(temporary)
        venv.EnvBuilder(with_pip=True).create(target / "venv")
        python = target / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        install = [str(python), "-m", "pip", "install", "-c", str(ROOT / "constraints-python312.txt")]
        if args.wheelhouse:
            install += ["--no-index", "--find-links", str(Path(args.wheelhouse).resolve())]
        subprocess.run(install + [str(wheels[0])], cwd=target, env=environment, check=True)
        subprocess.run([str(python), "-m", "pip", "check"], cwd=target, env=environment, check=True)
        subprocess.run([str(python), "-m", "dota_coach.cli", "--help"], cwd=target, env=environment, check=True)
        subprocess.run([str(python), "-m", "dota_coach.cli", "dossier", "--match-json",
                        str(ROOT / "tests/fixtures/opendota_match_sample.json"), "--replay-jsonl",
                        str(ROOT / "tests/fixtures/replay_sample.jsonl"), "--account-id", "111",
                        "--synthetic", "--out", str(target / "report")], cwd=target, env=environment, check=True)
        verification = """from importlib.resources import files
import json
from pathlib import Path
from dota_coach.coach.principles import _load_sections
from dota_coach.ingest.semantic_events import build_semantic_events, project_semantic_timeline
from dota_coach.learning.resource_plan import compute_resource_plan
from dota_coach.learning.build_planner import build_source_context, create_build_plan
from dota_coach.learning.build_plan_surface import render_build_plan_form
from dota_coach.ingest.semantic_lifecycle import build_semantic_lifecycles
from dota_coach.ingest.objective_state import build_objective_state, project_objective_state
from dota_coach.ingest.order_source import load_order_source
from dota_coach.ingest.constraint_source import write_constraint_source, load_constraint_source
from dota_coach.ingest.event_visibility import extract_event_visibility, load_event_visibility_source
from dota_coach.evidence.clock_math import verified_bounds, numeric_interval
from dota_coach.video.trace_clips import build_activation_clips, verified_clip_path
from dota_coach.evidence.temporal import project_temporal_knowledge, TemporalKnowledgePolicy
from dota_coach.decisions.choice_window import resolve_choice_windows, load_choice_evidence
from dota_coach.decisions.choice_monitor import monitor_choice_stream, load_monitor_input
from dota_coach.decisions.command_census import census_commands, load_command_input
from dota_coach.ingest.command_binding import load_command_binding_source
from dota_coach.ingest.command_stages import bridge_command_stages, StageReceipt, StageRegistry
from dota_coach.decisions.mechanics_adapter import summarize_constraint_mechanics, monitor_mechanical_stream
from dota_coach.decisions.movement import evaluate_movement, load_movement_input
from dota_coach.decisions.defensive_impact import evaluate_defensive_impact, load_defensive_impact_input
from dota_coach.validation.criterion_gate import evaluate_gate, check_inference
from dota_coach.ingest.projectile_source import load_projectile_source
from dota_coach.ingest.unit_control import build_unit_control_source
from dota_coach.ingest.impact_prefix import compile_impact_prefix, load_impact_prefix_input
from dota_coach.decisions.impact_pipeline import assess_impact_case, recheck_case_assessment
from dota_coach.learning.verified_history import build_verified_history, compare_verified_progress, select_verified_study_episodes
from dota_coach.decisions.terrain import evaluate_terrain, load_terrain_input
from dota_coach.analytical_workflow import evaluate_prefix_workflow, evaluate_history_workflow
from dota_coach.learning.ward_analysis import analyze_ward_prefix, analyze_ward_task
from dota_coach.decisions.opportunity_discovery import discover_resource_opportunities
from dota_coach.learning.ward_plan import create_ward_plan
from dota_coach.learning.ward_plan_surface import render_ward_plan_form
from dota_coach.validation.review_workspace import write_review_workspace, append_review
assert files('dota_coach.coach').joinpath('principles.md').is_file()
assert files('dota_coach.coach').joinpath('moment_principles.md').is_file()
assert _load_sections(Path(str(files('dota_coach.coach').joinpath('principles.md'))))
assert _load_sections(Path(str(files('dota_coach.coach').joinpath('moment_principles.md'))))
report = json.loads(Path('report/analysis.json').read_text(encoding='utf-8'))
assert report['dataset_kind'] == 'synthetic'
video_smoke = build_activation_clips({'match_id':1, 'dataset_kind':'synthetic', 'entries':[]}, Path('video-navigation-smoke'))
assert video_smoke['status'] == 'not_supplied' and not video_smoke['training_eligible']
assert Path('report/index.html').is_file()
print('Installed wheel: CLI, resources and offline report pass outside checkout')
"""
        subprocess.run([str(python), "-c", verification], cwd=target, env=environment, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
