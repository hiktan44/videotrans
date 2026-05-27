import argparse
import json
import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")
os.environ.setdefault("CT2_USE_EXPERIMENTAL_PACKED_GEMM", "0")

parent_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(parent_dir))

from app.abus_asr_faster_whisper import FasterWhisperInference
from app.abus_asr_parameters import WhisperParameters


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="tiny")
    parser.add_argument("--language", default="english")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--highlight-words", action="store_true")
    args = parser.parse_args()

    try:
        inference = FasterWhisperInference()
        params = WhisperParameters(
            model_size=args.model,
            lang=args.language,
            compute_type=args.compute_type,
        )
        subtitles = inference.transcribe_file(
            args.input,
            params,
            args.highlight_words,
            progress=None,
        ) or []
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump({"subtitles": subtitles}, f, ensure_ascii=False)
        return 0
    except Exception as exc:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
                f,
                ensure_ascii=False,
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
