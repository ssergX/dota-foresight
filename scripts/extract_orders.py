"""Write replay order callbacks as bytes without shell encoding conversion."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

from extract_trace import ROOT, run_extractor


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dem', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--context', action='store_true', help='include exact raw entity/handle associations')
    parser.add_argument('--tool', default=str(ROOT/'replay_tool'/('replay_tool.exe' if os.name=='nt' else 'replay_tool')))
    args = parser.parse_args(argv)
    dem, tool, out = (Path(p).resolve() for p in (args.dem,args.tool,args.out))
    if not dem.is_file() or not tool.is_file():
        parser.error('replay and built Go extractor must be existing files')
    if out in (dem,tool):
        parser.error('output must not overwrite replay or extractor')
    with dem.open('rb') as stream:
        if stream.read(8)!=b'PBDEMS2\x00':
            parser.error('expected a decompressed Source 2 replay')
        stream.seek(0)
        print('source .dem SHA-256: '+hashlib.file_digest(stream,'sha256').hexdigest(),flush=True)
    run_extractor(tool,dem,out,'--orders-context' if args.context else '--orders')
    print('Order callbacks complete; command stages and gameplay meanings remain unverified.')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
