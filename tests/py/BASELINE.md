# Bash baseline

Timings of the Bash implementation from `just bench` (`tests/py/bench.py`),
the reference the Python port is measured against. The hook budget in
`docs/python-port.md` is 500 ms at p95 (50% of the 1 s Codex SessionEnd
default).

## Hosts

| Host | Hardware | OS | Bash | git | jq |
|---|---|---|---|---|---|
| dirac | MacBook Pro 2017 (14,2), Intel Core i5-7267U, 2 cores / 4 threads, 8 GB, SSD (ext4) | Ubuntu 24.04, Linux 7.0.0-38 | 5.2.21 | 2.43.0 | 1.7 |
| CI (`ubuntu-latest`) | not yet measured: needs a pushed branch | | | | |

dirac is the slowest host that runs agent sessions. The other one, einstein,
is a desktop; maxwell is a Windows dual-boot of einstein's hardware.

## dirac, 2026-10-24, commit 502ec0c

### Live knowledge base (copy)

Corpus: copy: 210 articles, 2489 archived and 18 pending observations, 57 questions. Search term `commit`. 20 runs after one warm-up.

| Command | p50 ms | p95 ms |
|---|---:|---:|
| `search commit` | 2101 | 2198 |
| `search --json commit` | 5190 | 5550 |
| `section --file <first-article> --number 1` | 97 | 104 |
| `toc --map` | 126 | 143 |
| `status --brief` | 1281 | 1320 |
| `stale --count` | 1219 | 1277 |
| `pending` | 81 | 98 |
| `context` | 3809 | 4215 |
| `session-context` | 1370 | 1432 |
| `hook:session-start` | 1423 | 1476 |
| `hook:session-end` | 93 | 98 |

### Synthetic 10× corpus

Corpus: synthetic scale=10 seed=0: 2100 articles, 24890 archived and 180 pending observations, 570 questions. Search term `benchmarkbeta`. 20 runs after one warm-up.

| Command | p50 ms | p95 ms |
|---|---:|---:|
| `search benchmarkbeta` | 2893 | 3547 |
| `search --json benchmarkbeta` | 6195 | 6607 |
| `section --file <first-article> --number 1` | 88 | 92 |
| `toc --map` | 1043 | 1112 |
| `status --brief` | 14545 | 15206 |
| `stale --count` | 14452 | 14979 |
| `pending` | 660 | 691 |
| `context` | 21842 | 22801 |
| `session-context` | 15678 | 16197 |
| `hook:session-start` | 15635 | 16316 |
| `hook:session-end` | 200 | 210 |

## Findings

- SessionStart exceeds the hook budget on the live knowledge base: 1.5 s
  at p95, three times the 500 ms target. At 10× it is 16 s.
- `status`, `stale`, `context`, and `session-context` grow about linearly
  with the corpus: 10× to 12× between the two corpora. `toc --map` and
  `pending` grow about 8×.
- `search` grows sub-linearly, from 2.2 s to 3.5 s at p95. `search --json`
  takes 1.9 to 2.5 times as long as plain `search`.
- `section` is flat. The SessionEnd flush doubles but stays under 210 ms at
  p95 with the pre-commit hook running.

## Reproduce

```bash
just bench --impl bash --content "$KNOWLEDGE_BASE/content" > live.json
just bench --impl bash --scale 10 > 10x.json
```

The raw reports are in `baseline/`.
