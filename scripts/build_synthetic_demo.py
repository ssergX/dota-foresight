"""Reproduce the whole offline flow. Every record here is explicitly synthetic."""
from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / ".runtime/python-packages"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dota_coach.cli import main
from dota_coach.decisions.contracts import ActionObservation, DecisionBoundary
from dota_coach.decisions.evaluator import (ActivationInput, CONDITIONS, BOUND_PREDICATES,
                                           REQUIRED_CAPABILITIES)
from dota_coach.decisions.batch import read_batch, evaluate_batch
from dota_coach.evidence.contracts import Fact, SourceRef, TimeRef, content_hash
from dota_coach.validation import DatasetRecord, write_dataset


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def scenario(n, kind, bounds, *, unknown=False, feasible=True):
    clock = TimeRef(1000*n, 30*n, 1, 0, "synthetic.clock.v1", "verified")
    sid = f"synthetic:decision:{n}"
    source = SourceRef(sid, content_hash((sid, bounds, feasible)), "synthetic-rubric",
                       "synthetic.v1", "fixture-only", "synthetic.v1")
    values = (feasible, True, True, True) + bounds
    facts = tuple(Fact(f"{sid}:fact:{i}", "synthetic:player:0", p, v, "derived", clock, clock,
                       "screen", (source,), observer_ref="synthetic:player:0", method_version="synthetic.rubric.v1")
                  for i, (p, v) in enumerate(zip(CONDITIONS + BOUND_PREDICATES, values)))
    if unknown:
        facts = (replace(facts[0], value=None, status="unknown", source_refs=(), unknown_reason="synthetic_missing"),) + facts[1:]
    return ActivationInput(sid, 8001, "synthetic:player:0", "synthetic-patch", "synthetic.rubric.v1",
            DecisionBoundary(sid+":boundary", clock, "resolved", "synthetic-cue", (sid+":cue",)),
            ActionObservation(kind, "synthetic-defense", "complete", (sid+":activation-log",)),
            facts[:4], facts[4:], "synthetic")


def build(out: Path):
    inputs = out / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    raw = json.loads((ROOT / "tests/fixtures/opendota_match_sample.json").read_text(encoding="utf-8"))
    raw["patch"] = 0
    raw["players"][0]["purchase_log"] = [{"time": -20, "key": "synthetic_item_a"},
                                          {"time": 300, "key": "synthetic_item_b"}]
    series_paths = []
    for i in range(3):
        sample = json.loads(json.dumps(raw))
        sample["match_id"] = 8001+i
        path = inputs / f"match-{8001+i}.synthetic.json"
        write(path, sample)
        series_paths.append(str(path))
    replay = (ROOT / "tests/fixtures/replay_sample.jsonl").read_text(encoding="utf-8")
    replay += '\n' + '\n'.join(json.dumps(row) for row in [
        {"t":"ward","id":7,"generation":0,"time":-10,"kind":"obs","team":2,"x":-5000,"y":-3000,"op":"placed"},
        {"t":"ward","id":7,"generation":0,"time":2,"kind":"obs","team":2,"x":None,"y":None,"op":"gone"},
        {"t":"ward","id":7,"generation":1,"time":4,"kind":"sentry","team":3,"x":2000,"y":3000,"op":"placed"}])
    replay_path = inputs / "replay.synthetic.jsonl"
    replay_path.write_text(replay, encoding="utf-8")
    decisions = [scenario(1,"activation_commit",(5,7,1,3)),
                 scenario(2,"observed_no_activation",(5,7,1,3)),
                 scenario(3,"activation_commit",(1,5,3,7)),
                 scenario(4,"observed_no_activation",(5,7,1,3),unknown=True),
                 scenario(5,"observed_no_activation",(5,7,1,3),feasible=False)]
    batch_data = {"schema_version":"foresight.activation-batch.v1", "scope": {
        "patch":"synthetic-patch","criterion_version":"synthetic.rubric.v1",
        "capabilities":list(REQUIRED_CAPABILITIES),"rubric_source_ids":["synthetic-rubric-only"],
        "acceptable_floor":0},"discovery_status":"partial","decisions":[asdict(d) for d in decisions],
        "exclusions":[{"opportunity_id":"synthetic:gap:1","match_id":8001,"eligibility":"unknown",
                       "reason_codes":["synthetic-log-gap"]}]}
    batch_path = inputs / "activation-batch.synthetic.json"
    write(batch_path, batch_data)
    dataset = tuple(DatasetRecord(d.decision_id,d.input_hash,8001,content_hash(replay),
          d.subject_ref,d.patch,"development","synthetic") for d in decisions)
    dataset_path = inputs / "dataset.synthetic.jsonl"
    write_dataset(dataset_path, dataset)
    results = evaluate_batch(read_batch(json.dumps(batch_data), True))
    predictions = inputs / "predictions.synthetic.jsonl"
    predictions.write_text(''.join(json.dumps({k:e[k] for k in (
        "decision_id","input_hash","verdict","evaluator_version")})+'\n' for e in results["evaluations"]),encoding="utf-8")
    annotations = inputs / "annotations.empty.jsonl"
    annotations.write_text("",encoding="utf-8")
    commands = [
        ["dossier","--match-json",series_paths[0],"--replay-jsonl",str(replay_path),"--account-id","111","--synthetic","--out",str(out/"match")],
        ["evaluate","--batch-json",str(batch_path),"--experimental","--out",str(out/"criterion")],
        ["profile","--match-json",*series_paths,"--account-id","111","--synthetic","--out",str(out/"profile")],
        ["review-export","--batch-json",str(batch_path),"--dataset-jsonl",str(dataset_path),"--out",str(out/"blind-review")],
        ["review-quality","--dataset-jsonl",str(dataset_path),"--annotations-jsonl",str(annotations),
         "--predictions-jsonl",str(predictions),"--split","development","--out",str(out/"quality.json")]]
    for command in commands:
        if main(command) != 0:
            raise RuntimeError("demo stage failed: " + command[0])
    (out / "index.html").write_text("""<!doctype html><html lang='ru'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>Foresight — локальная проверка</title>
<style>body{font:18px system-ui;max-width:1000px;padding:20px;margin:40px auto;background:#131b25;color:#e2ebf5;line-height:1.6}a{color:#9ac8ff}li{margin:18px 0}.badge{padding:18px;background:#3b2d23;border-radius:12px}</style></head><body>
<h1>Foresight — проверка сквозного потока</h1><p class='badge'><b>Все данные синтетические.</b> Это проверка кода и интерфейса, не разбор реального игрока и не доказательство точности.</p>
<ul><li><a href='match/index.html'>Матч: эпизоды, источники, варды, покупки, обратная связь</a></li>
<li><a href='criterion/index.html'>Рубрика: хороший выбор, нарушение, альтернативы, отказ, техническая невозможность</a></li>
<li><a href='profile/index.html'>Серия: контекст, пропуски, знаменатели</a></li>
<li><a href='blind-review/README.md'>Независимая разметка</a> · <a href='blind-review/blind-cases.jsonl'>Слепые кейсы</a> · <a href='blind-review/annotation-template.jsonl'>Шаблон</a></li>
<li><a href='quality.json'>Метрики: нулевой реальный корпус, точность не установлена</a></li></ul>
<p>Живой критерий, точная видимость, рекомендации и тренировочный план закрыты до реальной проверки данных и независимой разметки.</p></body></html>""",encoding="utf-8")
    return out / "index.html"


if __name__ == "__main__":
    print(build(Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT / "out/full-demo"))
