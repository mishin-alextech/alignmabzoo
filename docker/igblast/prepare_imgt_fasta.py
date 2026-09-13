"""Готовит IMGT-gapped FASTA с короткими идентификаторами генов."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("inputs", nargs="+", type=Path)
    arguments = parser.parse_args()

    seen: set[str] = set()
    with arguments.output.open("w", encoding="utf-8", newline="\n") as target:
        for source in arguments.inputs:
            for line in source.read_text(encoding="utf-8-sig").splitlines():
                if not line.startswith(">"):
                    target.write(line.strip() + "\n")
                    continue
                fields = line[1:].split("|")
                if len(fields) < 2 or not fields[1].strip():
                    raise ValueError(f"В {source} найден заголовок IMGT без имени гена.")
                identifier = fields[1].strip()
                if identifier in seen:
                    raise ValueError(f"В IMGT FASTA повторяется идентификатор {identifier}.")
                seen.add(identifier)
                target.write(f">{identifier}\n")


if __name__ == "__main__":
    main()
