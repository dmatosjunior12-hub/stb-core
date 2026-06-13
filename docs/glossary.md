# Glossary

| Term | Definition |
|------|------------|
| **Gene** | Reusable data primitive: tuple (σ, ρ, π) — signature, representation, reconstruction procedure |
| **GeneLibrary** (Γ) | Shared domain library of genes, persistent and concurrent-safe |
| **Purification** | Separation of source X into structural (X_s), substitutable (X_a), and residual (X_r) components |
| **Ψ(x_i)** | Multi-criteria scoring function used in C1 to classify segments |
| **Fitness F(g_i)** | Gene utility metric: usage × quality − storage − compute cost |
| **Bytecode** | Binary program P encoding reconstruction instructions |
| **Capsid** | Transmission header C: domain, version, checksum, tolerance, fallback |
| **STB-VM** | Virtual machine that executes bytecode P against GeneLibrary to reconstruct X̂ |
| **Apoptosis** | Automatic reconstruction abort when gene failure rate exceeds 50% |
| **Residue (Ω)** | Classically-compressed irreducible component transmitted alongside P |
| **τ** | Admissible distortion tolerance: exact, perceptual, or semantic |
| **ρ_STB** | STB compression ratio: \|X\| / (\|P\| + \|Ω\| + \|C\|) |
