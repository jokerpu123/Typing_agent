"""Small smoke benchmark; results are not a representative accuracy evaluation."""
import argparse
import json
from pathlib import Path
from statistics import median
from time import perf_counter

from .decoding import group_beam_search


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--cases", default="benchmarks/smoke.jsonl")
    parser.add_argument("--output", default="benchmarks/latest.json")
    parser.add_argument("--beams", type=int, default=4)
    parser.add_argument("--groups", type=int, default=2)
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    args = parser.parse_args()
    from .transformers_backend import TransformersBackend, make_constraint
    cases = [json.loads(line) for line in Path(args.cases).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not cases:
        raise ValueError("Benchmark needs at least one case")
    loaded_at = perf_counter()
    backend = TransformersBackend(args.model, "", args.device)
    load_ms = (perf_counter() - loaded_at) * 1000
    constraint = make_constraint()
    rows = []
    # Includes a separately labelled cold pass; repeat is warm, not independent data.
    for pass_name in ("cold", "warm"):
        for case in cases:
            start = perf_counter()
            backend.set_context(case["context"])
            candidates = group_beam_search(backend, constraint, case["pinyin"],
                                           beam_width=args.beams, groups=args.groups)
            elapsed = (perf_counter() - start) * 1000
            texts = [c.text for c in candidates]
            rows.append(dict(case, pass_name=pass_name, candidates=texts, latency_ms=elapsed,
                             top1=bool(texts and texts[0] == case["expected"]),
                             hit_returned=case["expected"] in texts))
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    warm = [r for r in rows if r["pass_name"] == "warm"]
    output = {"model": args.model, "beams": args.beams, "groups": args.groups,
              "torch": backend.torch.__version__,
              "device": backend.torch.cuda.get_device_name(0) if args.device == "cuda" else "cpu",
              "dtype": str(next(backend.model.parameters()).dtype),
              "gpu_peak_allocated_bytes": backend.torch.cuda.max_memory_allocated() if args.device == "cuda" else None,
              "load_ms": load_ms, "warm_median_ms": median(r["latency_ms"] for r in warm),
              "warm_max_ms": max(r["latency_ms"] for r in warm),
              "top1": sum(r["top1"] for r in warm) / len(warm), "rows": rows,
              "limitation": "Tiny hand-written smoke set; no general accuracy or P95 claim."}
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
