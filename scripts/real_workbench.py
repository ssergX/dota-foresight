"""Open the checked local replay stage with the bundled or installed Python."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'.runtime/python-packages'))
if hasattr(sys.stdout,'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from dota_coach.cli import main


if __name__=='__main__':
    catalogs=sorted((ROOT/'out/valve-catalog/snapshots').glob('*/catalog.json'),key=lambda p:p.stat().st_mtime_ns)
    if not catalogs:
        raise SystemExit('Каталог отсутствует. Сначала создайте source snapshot командой catalog.')
    args=['serve','--match-json',str(ROOT/'out/real-data/match-9030822324.json'),
        '--extraction-json',str(ROOT/'out/real-analysis/extraction.json'),
        '--catalog-json',str(catalogs[-1]),'--catalog-raw-dir',str(ROOT/'out/valve-catalog/raw'),
        '--study-json',str(ROOT/'out/study-live/discovery.json'),'--out',str(ROOT/'out/workbench')]
    if (ROOT/'out/real-analysis/action-states.json').exists():
        args+=['--action-states-json',str(ROOT/'out/real-analysis/action-states.json')]
    if (ROOT/'out/real-data/9030822324.combat-names.jsonl').exists():
        args+=['--combat-names-jsonl',str(ROOT/'out/real-data/9030822324.combat-names.jsonl')]
    for option,path in (('--orders-jsonl','out/real-data/9030822324.orders.jsonl'),
                        ('--constraint-source-jsonl','out/real-analysis/raw-constraints.jsonl'),
                        ('--event-visibility-jsonl','out/real-analysis/event-visibility.jsonl')):
        if (ROOT/path).exists():
            args += [option,str(ROOT/path)]
    if (ROOT/'out/real-data/9030822324.orders-context.jsonl').exists():
        args += ['--command-binding-jsonl',str(ROOT/'out/real-data/9030822324.orders-context.jsonl')]
    if (ROOT/'out/real-data/9030822324.projectiles.jsonl').exists():
        args += ['--projectiles-jsonl',str(ROOT/'out/real-data/9030822324.projectiles.jsonl')]
    if (ROOT/'out/real-data/9030822324.trace.named.jsonl').exists():
        args += ['--unit-control-trace',str(ROOT/'out/real-data/9030822324.trace.named.jsonl')]
    raise SystemExit(main(args+sys.argv[1:]))
