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
- [ ] MAX_VM_STEPS global execution limit
- [ ] Expanded test suite with corpus fixtures

## v0.4 (planned)
- [ ] Content-defined chunking backend (FastCDC integration)
- [ ] Benchmark framework against DEFLATE / zstd / H.264 baselines
- [ ] Measurement of ρ_STB on real data

## v1.0 (future)
- [ ] End-to-end STB prototype on a real domain (video or text)
- [ ] Empirical validation as described in the paper (Section 12, item 6)
