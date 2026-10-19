# STB-Core v0.2

Reference implementation of **Structural Generative Transmission (STB)** —
a bio-inspired framework for transmitting generative instructions instead of raw data.

> ⚠️ Experimental. Not independently audited. Do not use in production.

## Preprint

> Matos Júnior, D. (2026). *Structural Generative Transmission (STB)*.
> Zenodo. https://doi.org/10.5281/zenodo.20528475

> Matos Júnior, D. (2026). *Structural Generative Transmission (STB) — Part II: 
> Bio-Inspired Architectural Extensions as a Disciplined Research Program* (Version 1.2).
> Zenodo. https://doi.org/10.5281/zenodo.22045957

## What this implements

| Layer | Component | Status |
|-------|-----------|--------|
| C1 | Purification (Ψ scoring) | ✅ |
| C2 | Gene library + fitness metric | ✅ |
| C3 | Metalanguage AST + bytecode compiler | ✅ |
| C4 | Digital capsid (SHA256 checksum) | ✅ |
| L5 | STB Virtual Machine | ✅ |
| — | Residual compression (zstd) | ✅ optional |

What is **not** implemented: automatic gene discovery, domain-specific
calibration of Ψ coefficients, empirical benchmarking.

## Build

```bash
cargo build
cargo test
```

With zstd residual compression:

```bash
cargo build --features zstd
```

## Quick example

```rust
use stb_core::{Instruction, Compiler, STBVM, GeneLibrary};

let ast = Instruction::Seq(vec![
    Instruction::Def {
        id: "msg".to_string(),
        data: b"Hello STB!".to_vec(),
    },
    Instruction::Rpt {
        count: 3,
        body: Box::new(Instruction::Ref { id: "msg".to_string() }),
    },
    Instruction::Stp,
]);

let bytecode = Compiler::compile(&ast).unwrap();
let mut vm = STBVM::new(GeneLibrary::new());
let output = vm.execute_bytecode(&bytecode).unwrap();
```

## Benchmark

`bench/` compara o formato STB com DEFLATE, xz e zstd em dados reais (logs do Loghub, CSVs,
código e `.pyc` da stdlib), contando a biblioteca de genes (comprimida) no custo e treinando-a só
com dados de treino. Resultado atual: nem o STB atual, nem as variantes com resíduo comprimido
(STB+Ω) e com COPY (STB-v2) superam o zstd-19 sem dicionário em nenhuma família estruturada.
Detalhes e limitações em [`bench/RESULTS.md`](bench/RESULTS.md).

```bash
pip install -r bench/requirements.txt
python3 bench/build_corpus.py && python3 bench/run_benchmark.py
```

## Security limits

| Limit | Value |
|-------|-------|
| Max output size | 64 MB |
| Max loop iterations | 1,000,000 **por RPT** (não global) |
| Max VM steps | 50,000,000 **global** (inclui RPT/RPTEND) |
| Bytecode validation | estática, antes da execução: opcodes válidos, RPT/RPTEND balanceados, `STP` como última instrução |
| ALE seed | não pode ser `0` (estado xorshift absorvente) |
| Gene signature validation | SHA256 (detecta corrupção, **não** adulteração: o hash fica no mesmo arquivo) |
| Bytecode integrity | SHA256 (capsid); bytecode com checksum inválido **nunca** é executado |

## Development note

STB-Core was developed collaboratively using AI-assisted code generation
as part of the research process described in the preprint above.

## License

MIT
