"""Read-only public corpus acquisition; immutable receipts, bounded downloads."""
from __future__ import annotations

import argparse
import bz2
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".runtime/python-packages"))
import requests


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for data in iter(lambda: f.read(1024*1024), b""):
            h.update(data)
    return h.hexdigest()


def get_json(url, target):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()
    target.write_bytes(r.content)
    receipt = {"url":r.url,"checked_at":datetime.now(timezone.utc).isoformat(),
               "http_status":r.status_code,"sha256":digest(target),
               "artifact":target.name,"verification":"source_response_only"}
    target.with_suffix(target.suffix+".receipt.json").write_text(json.dumps(receipt,indent=2),encoding="utf-8")
    return data


def acquire(out, match_id=None, max_candidates=5):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if match_id is None:
        rows=get_json("https://api.opendota.com/api/proMatches",out/"pro-matches.json")
        candidates=[r["match_id"] for r in rows[:max_candidates]]
    else:
        candidates=[match_id]
    attempts=[]
    for mid in candidates:
        if type(mid) is not int or mid<=0:
            raise ValueError("positive match ID required")
        time.sleep(1.1)
        raw=get_json(f"https://api.opendota.com/api/matches/{mid}",out/f"match-{mid}.json")
        if raw.get("match_id")!=mid or not raw.get("players"):
            attempts.append({"match_id":mid,"status":"invalid_source_response"})
            continue
        url=raw.get("replay_url")
        if not url:
            attempts.append({"match_id":mid,"status":"replay_url_absent"})
            continue
        parsed=urlsplit(url)
        if parsed.scheme not in ("http","https") or not parsed.hostname or not parsed.hostname.endswith(".valve.net"):
            raise ValueError("unsupported public replay host")
        compressed=out/f"{mid}.dem.compressed"
        temp=compressed.with_suffix(".part")
        # Valve's returned source may be HTTP; do not falsely relabel transport.
        size=0
        with requests.get(url,stream=True,timeout=(20,45)) as response:
            response.raise_for_status()
            with temp.open("wb") as f:
                for block in response.iter_content(1024*1024):
                    size+=len(block)
                    if size>256*1024*1024:
                        raise ValueError("compressed replay exceeds 256 MiB acquisition limit")
                    f.write(block)
                f.flush();os.fsync(f.fileno())
            receipt={"match_id":mid,"url":response.url,"checked_at":datetime.now(timezone.utc).isoformat(),
                     "http_status":response.status_code,"compressed_sha256":digest(temp),
                     "compressed_bytes":size,"verification":"transport_and_hash_only"}
        os.replace(temp,compressed)
        with compressed.open("rb") as f:
            magic=f.read(8)
        dem=out/f"{mid}.dem"
        pending=dem.with_suffix(".dem.part")
        if magic.startswith(b"BZh"):
            reader=bz2.BZ2File(compressed,"rb")
            codec="bz2"
        elif magic.startswith(b"\x28\xb5\x2f\xfd"):
            import zstandard
            reader=zstandard.ZstdDecompressor().stream_reader(compressed.open("rb"))
            codec="zstd"
        elif magic.startswith(b"PBDEMS2"):
            reader=compressed.open("rb")
            codec="uncompressed"
        else:
            raise ValueError("unknown replay compression magic")
        unpacked=0
        with reader, pending.open("wb") as f:
            for block in iter(lambda: reader.read(1024*1024),b""):
                unpacked+=len(block)
                if unpacked>768*1024*1024:
                    raise ValueError("raw replay exceeds 768 MiB acquisition limit")
                f.write(block)
            f.flush();os.fsync(f.fileno())
        with pending.open("rb") as f:
            if f.read(8)!=b"PBDEMS2\x00":
                raise ValueError("not a Source 2 replay")
        os.replace(pending,dem)
        receipt.update({"codec":codec,"raw_sha256":digest(dem),"raw_bytes":unpacked,
                        "raw_artifact":dem.name,"patch_id":raw.get("patch"),
                        "client_validation":"not_performed"})
        (out/f"replay-{mid}.receipt.json").write_text(json.dumps(receipt,indent=2),encoding="utf-8")
        attempts.append({"match_id":mid,"status":"acquired","dem":str(dem)})
        (out/"acquisition.json").write_text(json.dumps(attempts,indent=2),encoding="utf-8")
        print(json.dumps(receipt))
        return dem
    (out/"acquisition.json").write_text(json.dumps(attempts,indent=2),encoding="utf-8")
    raise RuntimeError("no available replay in supplied candidates")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",default=str(ROOT/"out/real-data"))
    p.add_argument("--match-id",type=int)
    args=p.parse_args()
    acquire(args.out,args.match_id)
