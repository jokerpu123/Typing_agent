import argparse
import json
from time import perf_counter

from .decoding import group_beam_search


def main():
    parser = argparse.ArgumentParser(description="Full-pinyin constrained decoding baseline")
    parser.add_argument("--model", required=True, help="Existing local model directory")
    parser.add_argument("--context", default="")
    parser.add_argument("--pinyin", required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument("--beams", type=int, default=4)
    parser.add_argument("--groups", type=int, default=2)
    args = parser.parse_args()
    from .transformers_backend import TransformersBackend, make_constraint
    backend = TransformersBackend(args.model, args.context, args.device)
    start = perf_counter()
    candidates = group_beam_search(
        backend, make_constraint(), args.pinyin, beam_width=args.beams, groups=args.groups,
    )
    print(json.dumps({
        "decode_ms": round((perf_counter() - start) * 1000, 2),
        "candidates": [{"text": c.text, "log_probability": c.log_probability} for c in candidates],
        "baseline": "uncached reference; excludes model/tokenizer loading",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
