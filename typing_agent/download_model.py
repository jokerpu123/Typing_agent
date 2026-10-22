"""Download official Base weights with a disk guard and pinned Hub revision."""
import argparse
import json
import os
from pathlib import Path
import shutil


REPO = "Qwen/Qwen3-1.7B-Base"
PATTERNS = ["*.json", "*.safetensors", "*.txt", "*.model", "README.md", "LICENSE"]


def check_space(destination, required_bytes):
    path = Path(destination).resolve()
    while not path.exists():
        path = path.parent
    free = shutil.disk_usage(path).free
    if free < required_bytes:
        raise RuntimeError(
            f"Insufficient disk space: {free / 1e9:.2f} GB free; "
            f"need {required_bytes / 1e9:.2f} GB at {destination}. "
            "Free space or pass --destination on another drive."
        )


def main():
    import fnmatch
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", default="models/Qwen3-1.7B-Base")
    args = parser.parse_args()
    destination = Path(args.destination).resolve()
    # Fail before any network request if even the known weight size cannot fit.
    check_space(destination, 4_500_000_000)
    os.environ.setdefault("HF_HOME", str(destination.parent / ".huggingface"))
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    from huggingface_hub import HfApi, snapshot_download
    info = HfApi().model_info(REPO, files_metadata=True)
    selected = [f for f in info.siblings if any(fnmatch.fnmatch(f.rfilename, p) for p in PATTERNS)]
    expected = sum(f.size or 0 for f in selected)
    check_space(destination, expected + 1_000_000_000)
    print(f"Downloading {REPO}@{info.sha}: {expected / 1e9:.2f} GB", flush=True)
    snapshot_download(REPO, revision=info.sha, local_dir=destination, allow_patterns=PATTERNS, max_workers=2)
    (destination / "download_manifest.json").write_text(json.dumps({
        "repo": REPO, "revision": info.sha,
        "files": {f.rfilename: f.size for f in selected},
    }, indent=2), encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
