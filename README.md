# STB-Core v0.2

Reference implementation of **Structural Generative Transmission (STB)** —
a bio-inspired framework for transmitting generative instructions instead of raw data.

> ⚠️ Experimental. Not independently audited. Do not use in production.

## Preprint

> Matos Júnior, D. (2026). *Structural Generative Transmission (STB)*.
> Zenodo. https://doi.org/10.5281/zenodo.20528475

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

## Security limits

| Limit | Value |
|-------|-------|
| Max output size | 64 MB |
| Max loop iterations | 1,000,000 |
| Gene signature validation | SHA256 |
| Bytecode integrity | SHA256 (capsid) |

## Development note

STB-Core was developed collaboratively using AI-assisted code generation
as part of the research process described in the preprint above.

## License

MIT
