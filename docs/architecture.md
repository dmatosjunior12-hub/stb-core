# STB Architecture

## Pipeline

```
Source X
  └─[C1 Purification]──► X_s, X_a, X_r
       └─[C2 Gene Library]──► GeneLibrary (Γ)
            └─[C3 Bytecode Compiler]──► Program P
                 └─[C4 Digital Capsid]──► TransmissionUnit T=(C,Γ,P,Ω)
                      └─[L5 STB-VM]──► X̂  (d(X,X̂) ≤ τ)
```

## Layers

| Layer | Component | Rust struct |
|-------|-----------|-------------|
| C1 | Purification | `psi_score`, `classify` |
| C2 | Gene library | `Gene`, `GeneLibrary` |
| C3 | Compiler | `Instruction`, `Compiler`, `BytecodeProgram` |
| C4 | Capsid | `Capsid`, `TransmissionUnit` |
| L5 | VM | `STBVM` |

## Safety limits

| Limit | Value | Rationale |
|-------|-------|-----------|
| Max output | 64 MB | OOM protection |
| Max loop count | 1,000,000 | DoS protection |
| Gene signature | SHA256 | Integrity on load |
| Bytecode checksum | SHA256 | Integrity on transmit |

For theoretical background see the [paper](https://doi.org/10.5281/zenodo.20528475).
