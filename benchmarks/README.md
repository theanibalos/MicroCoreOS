# Benchmark: Token Comparison for AI Context

This directory contains side-by-side implementations of the same feature (`CreateUser`) 
using different architectures. The goal is to measure how much context (tokens) an AI 
needs to understand and modify each implementation.

## Architectures Compared

1. **clean_arch_fastapi/** - Traditional Clean Architecture (6 files)
2. **micro_core_os/** - MicroCoreOS Architecture (1 file)

## Running the Benchmark

```bash
python benchmark.py
```

## Results

| Architecture | Files | Lines | Tokens (Est.) |
|--------------|-------|-------|---------------|
| Clean Architecture | 6 | ~180 | ~3,500 |
| MicroCoreOS | 1 | ~45 | ~850 |

**Reduction: ~75% fewer tokens for the AI to process.**
