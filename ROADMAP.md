# STB-Core Roadmap

## v0.2 (current)
- [x] Purification engine (Ψ scoring, classification)
- [x] Gene library with SHA256 validation and fitness metric
- [x] Reconstruction bytecode compiler
- [x] STB Virtual Machine (DEF/REF/RPT/ALE/ERR/STP)
- [x] Digital capsid with checksum
- [x] Digital apoptosis (permissive mode)
- [x] Optional zstd residual compression

## v0.3 (planned)
- [ ] Iterative `skip_instruction` (eliminate recursion stack risk)
- [ ] CSPRNG seed for ALE (replace predictable XorShift)
- [x] MAX_VM_STEPS global execution limit (50M passos)
- [x] Validação estática do bytecode antes da execução (STP final, RPT/RPTEND balanceados)
- [x] Política `Partial` não executa mais bytecode com checksum inválido
- [ ] Expanded test suite with corpus fixtures

## v0.4 (planned)
- [ ] Content-defined chunking backend (FastCDC integration)
- [x] Benchmark framework against DEFLATE / zstd (`bench/`); H.264 ainda pendente
- [ ] Baseline de vídeo (H.264) no benchmark
- [x] Measurement of ρ_STB on real data (logs, código, CSV, .pyc; ver `bench/RESULTS.md`): o formato atual fica abaixo do zstd
- [ ] Encoder com REF a bytes já emitidos (in-file), a maior lacuna medida

## v1.0 (future)
- [ ] End-to-end STB prototype on a real domain (video or text)
- [ ] Empirical validation as described in the paper (Section 12, item 6)
