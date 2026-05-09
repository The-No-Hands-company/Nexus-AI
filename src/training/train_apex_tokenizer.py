from __future__ import annotations

import argparse
import json
from pathlib import Path


def train_apex_tokenizer(
    corpus_file: Path,
    output_dir: Path,
    vocab_size: int = 32000,
    min_frequency: int = 2,
) -> dict:
    if not corpus_file.is_file():
        raise FileNotFoundError(f"Corpus not found: {corpus_file}")

    try:
        from tokenizers import Tokenizer, decoders, models, normalizers, pre_tokenizers, trainers
        from transformers import PreTrainedTokenizerFast
    except ImportError as exc:
        raise ImportError(
            "Tokenizer dependencies missing. Install with: pip install tokenizers transformers"
        ) from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    special_tokens = ["[PAD]", "[UNK]", "<s>", "</s>", "<user>", "<assistant>", "<system>"]

    tokenizer = Tokenizer(models.BPE(unk_token="[UNK]"))
    tokenizer.normalizer = normalizers.Sequence([normalizers.NFKC()])
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tokenizer.decoder = decoders.ByteLevel()

    trainer = trainers.BpeTrainer(
        vocab_size=max(2048, int(vocab_size)),
        min_frequency=max(1, int(min_frequency)),
        special_tokens=special_tokens,
    )
    tokenizer.train(files=[str(corpus_file)], trainer=trainer)

    tokenizer_json = output_dir / "tokenizer.json"
    tokenizer.save(str(tokenizer_json))

    hf_tokenizer = PreTrainedTokenizerFast(
        tokenizer_file=str(tokenizer_json),
        unk_token="[UNK]",
        pad_token="[PAD]",
        bos_token="<s>",
        eos_token="</s>",
    )
    hf_tokenizer.save_pretrained(str(output_dir))

    summary = {
        "corpus": str(corpus_file),
        "tokenizer_dir": str(output_dir),
        "vocab_size": int(hf_tokenizer.vocab_size),
        "special_tokens": special_tokens,
    }
    (output_dir / "tokenizer_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train Apex tokenizer from text corpus.")
    parser.add_argument("--corpus", required=True, help="Input text corpus path")
    parser.add_argument("--output-dir", required=True, help="Tokenizer output directory")
    parser.add_argument("--vocab-size", type=int, default=32000)
    parser.add_argument("--min-frequency", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = train_apex_tokenizer(
        corpus_file=Path(args.corpus),
        output_dir=Path(args.output_dir),
        vocab_size=args.vocab_size,
        min_frequency=args.min_frequency,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
