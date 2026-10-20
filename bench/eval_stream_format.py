"""Avalia o formato de fluxos fluxos-v1 contra o empacotador legado (stb_v2.pack_streams).

Configuração fixa: G0 (genes sem COPY) com parser ótimo, a melhor combinação encontrada.
Para cada arquivo: tokeniza, serializa nas duas formas, decodifica o fluxos-v1, confere o digest
SHA-256(bytecode ‖ R) do cabeçalho e executa o programa pela VM. Só conta o arquivo se tudo bater.

Contabilidade igual à do resto do benchmark: cabeçalho de 40 B por arquivo (ov) e Γ cobrada
(min(cru, LZMA2)) na razão amortizada. ρ payload = sem Γ.

Versões nos nomes e na saída:
  legado  : stb_v2.pack_streams (empacotador anterior, 6 fluxos incluindo DIST vazio)
  fluxos-v1 : bench/stb_stream_format.py (5 fluxos, métodos cru/LZMA/zstd/rc)

Uso: python3 bench/eval_stream_format.py [--swap] [--families logs,codigo,csv,binario]
Saída: bench/results/stream_format_fluxos-v1[_swap]_<família>.json
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

import run_benchmark as rb
import stb_codec
import stb_stream_format as sf
import stb_v2
import stb_vm

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "data" / "corpus"
OUT = HERE / "results"
PARSER = "optimal"


def run(family: str, swap: bool) -> dict:
    train = [p.read_bytes() for p in sorted((CORPUS / family / "train").iterdir())]
    test = [p.read_bytes() for p in sorted((CORPUS / family / "test").iterdir())]
    if swap:
        train, test = test, train
    lib = stb_codec.Library(stb_codec.build_library(train, rb.BUDGET))
    G = rb.gamma_charge(lib)[1]
    n_genes = len(lib.genes)
    orig, n = sum(map(len, test)), len(test)
    ov = stb_codec.CAPSID_BYTES * n
    legacy = fmt = 0
    fails = vm_fails = digest_fails = 0
    t0 = time.perf_counter()
    for d in test:
        toks, R = stb_v2.tokenize(d, lib, PARSER, False)
        legacy += len(stb_v2.pack_streams(stb_v2.streams_from_tokens(toks, R)))
        blob = sf.encode(toks, R, n_genes)
        fmt += len(blob)
        digest = hashlib.sha256(stb_v2.bytecode_from_tokens(toks, lib) + R).digest()  # digest do cabeçalho
        try:
            t2, R2 = sf.decode(blob, n_genes)
            prog = stb_v2.bytecode_from_tokens(t2, lib)
            if hashlib.sha256(prog + R2).digest() != digest:
                digest_fails += 1
                continue
            if (t2, R2) != (toks, R):
                fails += 1
                continue
            if stb_vm.execute(prog, lib.payload, residue=R2) != d:
                vm_fails += 1
        except (ValueError, IndexError, stb_vm.VmError) as exc:
            print(f"    [falha] {exc}", flush=True)
            fails += 1
    el = time.perf_counter() - t0
    res = {
        "versao_formato": "fluxos-v1",
        "versao_legado": "pack_streams (legado)",
        "parser": PARSER,
        "split": "swap" if swap else "normal",
        "files": n,
        "orig_bytes": orig,
        "gamma_charge": G,
        "bytes_legado": legacy,
        "bytes_fluxos_v1": fmt,
        "rho_legado_payload": orig / (legacy + ov),
        "rho_fluxos_v1_payload": orig / (fmt + ov),
        "rho_legado_amort": orig / (legacy + ov + G),
        "rho_fluxos_v1_amort": orig / (fmt + ov + G),
        "ganho_pct_amort": ((legacy + ov + G) / (fmt + ov + G) - 1) * 100,
        "falhas_decodificacao": fails,
        "falhas_digest": digest_fails,
        "falhas_vm": vm_fails,
        "time_s": round(el, 1),
    }
    print(f"  {family:8s} {res['split']:6s} legado={res['rho_legado_amort']:.3f} "
          f"fluxos-v1={res['rho_fluxos_v1_amort']:.3f} ({res['ganho_pct_amort']:+.2f}%) "
          f"payload {res['rho_legado_payload']:.3f}->{res['rho_fluxos_v1_payload']:.3f} "
          f"falhas dec={fails} digest={digest_fails} vm={vm_fails} t={el:.0f}s", flush=True)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--swap", action="store_true")
    ap.add_argument("--families", default="logs,codigo,csv,binario")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    for fam in args.families.split(","):
        res = run(fam, args.swap)
        name = f"stream_format_fluxos-v1{'_swap' if args.swap else ''}_{fam}.json"
        (OUT / name).write_text(json.dumps(res, indent=1))
        print("gravado:", OUT / name, flush=True)


if __name__ == "__main__":
    main()
