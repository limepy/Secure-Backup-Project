"""Generate deterministic test data for demonstrations."""

import argparse
import random
from pathlib import Path


def generate(output, count=300, total_mb=100, seed=2026):
    if not 300 <= count <= 500 or not 0 < total_mb <= 200:
        raise ValueError('Required: 300-500 files and a total size above 0 up to 200 MB.')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('The output directory must be empty.')
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    size, remainder = divmod(int(total_mb * 1_000_000), count)
    for index in range(count):
        folder = output / f'group-{index // 50}'
        folder.mkdir(exist_ok=True)
        (folder / f'file-{index:04d}.bin').write_bytes(rng.randbytes(size + (index < remainder)))
    return f'Created {count} files, {int(total_mb * 1_000_000)} bytes.'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--count', type=int, default=300)
    parser.add_argument('--mb', type=float, default=100)
    parser.add_argument('--seed', type=int, default=2026)
    args = parser.parse_args()
    try:
        print(generate(args.output, args.count, args.mb, args.seed))
    except (OSError, ValueError) as error:
        parser.exit(1, f'ERROR: {error}\n')
