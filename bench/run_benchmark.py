"""Benchmark STB-Core vs. DEFLATE e zstd, com dicionário/biblioteca treinados só no treino.

Métodos:
  zlib-9        DEFLATE nível 9 (sem dicionário)
  zstd-19       zstd nível 19 (sem dicionário)
  zstd-19+dict  zstd nível 19 com dicionário treinado (orçamento 110 KiB)
  STB           encoder de bench/stb_codec.py com biblioteca Γ treinada (orçamento 110 KiB);
                literais crus no programa (formato atual do STB-Core)
  STB+Ω         mesmo encoder, mas os literais vão para um resíduo Ω comprimido com zstd-19
                e o programa usa RES n. RES NÃO existe no STB-Core: é extensão proposta.

Contabilidade (a biblioteca/dicionário é SEMPRE contado):
  isolado    cada arquivo é transmitido sozinho; o dicionário/Γ é pago em cada arquivo.
  amortizado o dicionário/Γ é pago uma vez para a família (receptor já o possui).

Para STB, o custo por arquivo é P (programa) + C (cabeçalho fixo de 40 bytes) [+ Γ].
Round-trip é verificado para todos os arquivos de todos os métodos.

Uso:  python3 bench/run_benchmark.py     (requer: zstandard, numpy; ver requirements.txt)
"""

import json
import platform
import statistics
import sys
import time
import zlib
from datetime import date
from pathlib import Path

import numpy as np
import zstandard

import build_corpus
import stb_codec
import stb_vm

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "data" / "corpus"
RESULTS_JSON = HERE / "data" / "results.json"
RESULTS_MD = HERE / "RESULTS.md"

BUDGET = 110 * 1024        # orçamento de Γ e de dicionário zstd (bytes)
ZSTD_SAMPLE = 16 * 1024    # tamanho dos amostras entregues ao treinador zstd
CAPSID = stb_codec.CAPSID_BYTES
FAMILY_LABELS = {
    "logs": "Logs reais (Loghub, 16 sistemas, split temporal)",
    "codigo": "Código-fonte Python (stdlib, split por arquivo)",
    "csv": "CSV reais (seaborn-data, split temporal por linhas)",
    "binario": "Bytecode .pyc (stdlib, split por arquivo)",
    "aleatorio": "Controle: bytes aleatórios (sem estrutura)",
}


def load(family, split):
    d = CORPUS / family / split
    return [(p.name, p.read_bytes()) for p in sorted(d.iterdir())]


def train_zstd_dict(train_bytes, budget=BUDGET):
    samples = []
    for b in train_bytes:
        for i in range(0, len(b), ZSTD_SAMPLE):
            chunk = b[i:i + ZSTD_SAMPLE]
            if len(chunk) >= 256:
                samples.append(chunk)
    try:
        return zstandard.train_dictionary(budget, samples).as_bytes()
    except zstandard.ZstdError as exc:  # amostras insuficientes/inválidas
        print(f"    [aviso] treino do dicionário zstd falhou: {exc}")
        return None


def bench_family(family):
    train = [b for _, b in load(family, "train")]
    test = load(family, "test")
    orig_total = sum(len(b) for _, b in test)
    n = len(test)
    res = {"files": n, "orig_bytes": orig_total, "methods": {}}

    # ---- zlib-9
    t = time.perf_counter()
    sizes = []
    for name, b in test:
        c = zlib.compress(b, 9)
        assert zlib.decompress(c) == b, f"zlib round-trip falhou: {name}"
        sizes.append(len(c))
    res["methods"]["zlib-9"] = {"iso": sum(sizes), "amort": sum(sizes), "payload": sum(sizes),
                                "fail": 0, "time_s": time.perf_counter() - t}

    # ---- zstd-19
    cctx = zstandard.ZstdCompressor(level=19)
    dctx = zstandard.ZstdDecompressor()
    t = time.perf_counter()
    sizes, fails = [], 0
    for name, b in test:
        c = cctx.compress(b)
        if dctx.decompress(c) != b:
            fails += 1
        sizes.append(len(c))
    res["methods"]["zstd-19"] = {"iso": sum(sizes), "amort": sum(sizes), "payload": sum(sizes),
                                 "fail": fails, "time_s": time.perf_counter() - t}

    # ---- zstd-19 + dicionário
    zdict = train_zstd_dict(train)
    if zdict is not None:
        cdict = zstandard.ZstdCompressor(level=19, dict_data=zstandard.ZstdCompressionDict(zdict))
        ddict = zstandard.ZstdDecompressor(dict_data=zstandard.ZstdCompressionDict(zdict))
        t = time.perf_counter()
        sizes, fails = [], 0
        for name, b in test:
            c = cdict.compress(b)
            if ddict.decompress(c) != b:
                fails += 1
            sizes.append(len(c))
        D = len(zdict)
        res["methods"]["zstd-19+dict"] = {
            "iso": sum(sizes) + D * n, "amort": sum(sizes) + D, "payload": sum(sizes), "fail": fails,
            "time_s": time.perf_counter() - t, "dict_bytes": D,
        }
    else:
        res["methods"]["zstd-19+dict"] = None

    # ---- STB: formato atual (literais crus) e STB+Ω (extensão com resíduo comprimido)
    t_build = time.perf_counter()
    genes = stb_codec.build_library(train, BUDGET)
    lib = stb_codec.Library(genes)
    build_s = time.perf_counter() - t_build
    G = lib.serialized_size()
    gene_info = {"gamma_bytes": G, "genes": len(genes), "build_s": build_s}

    t = time.perf_counter()
    sizes, fails, ref_bytes, lit_bytes, genes_used = [], 0, 0, 0, []
    for name, b in test:
        prog, st, _ = stb_codec.encode(b, lib)
        try:
            if stb_vm.execute(prog, lib.payload) != b:
                fails += 1
        except stb_vm.VmError as exc:
            print(f"    [falha] STB {name}: {exc}")
            fails += 1
        sizes.append(len(prog))
        ref_bytes += st["ref_bytes"]
        lit_bytes += st["literal_bytes"]
        genes_used.append(st["genes_used"])
    res["methods"]["STB"] = {
        "iso": sum(sizes) + CAPSID * n + G * n,
        "amort": sum(sizes) + CAPSID * n + G,
        "payload": sum(sizes) + CAPSID * n,
        "fail": fails,
        "time_s": time.perf_counter() - t,
        **gene_info,
        "ref_share": ref_bytes / orig_total if orig_total else 0.0,
        "literal_share": lit_bytes / orig_total if orig_total else 0.0,
        "genes_used_mean": statistics.mean(genes_used) if genes_used else 0.0,
    }

    t = time.perf_counter()
    p_sizes, o_sizes, fails = [], [], 0
    for name, b in test:
        prog, _, om = stb_codec.encode(b, lib, residue_mode=True)
        om_c = cctx.compress(om) if om else b""
        try:
            om_d = zstandard.ZstdDecompressor().decompress(om_c) if om_c else b""
            if stb_vm.execute(prog, lib.payload, residue=om_d) != b:
                fails += 1
        except (stb_vm.VmError, zstandard.ZstdError) as exc:
            print(f"    [falha] STB+Ω {name}: {exc}")
            fails += 1
        p_sizes.append(len(prog))
        o_sizes.append(len(om_c))
    res["methods"]["STB+Ω"] = {
        "iso": sum(p_sizes) + sum(o_sizes) + CAPSID * n + G * n,
        "amort": sum(p_sizes) + sum(o_sizes) + CAPSID * n + G,
        "payload": sum(p_sizes) + sum(o_sizes) + CAPSID * n,
        "fail": fails,
        "time_s": time.perf_counter() - t,
        **gene_info,
        "residue_share": sum(o_sizes) / orig_total if orig_total else 0.0,
    }
    return res


def rho(orig, comp):
    return orig / comp if comp else float("inf")


def render_summary(results):
    structured = [f for f in results if f != "aleatorio"]
    wins = 0
    lines = ["## Resumo", ""]
    for fam in structured:
        r = results[fam]
        m = r["methods"]
        z = rho(r["orig_bytes"], m["zstd-19"]["iso"])
        zd = rho(r["orig_bytes"], m["zstd-19+dict"]["payload"]) if m["zstd-19+dict"] else float("nan")
        so = rho(r["orig_bytes"], m["STB+Ω"]["payload"])
        sr = rho(r["orig_bytes"], m["STB"]["payload"])
        if z > so and z > sr:
            wins += 1
        lines.append(
            f"- **{FAMILY_LABELS.get(fam, fam).split(' (')[0]}**: zstd-19 ρ = {z:.2f}; "
            f"zstd-19+dict ρ = {zd:.2f}; STB+Ω ρ = {so:.2f}; STB ρ = {sr:.2f} "
            f"(ρ sem custo de dicionário/Γ)."
        )
    lines += [
        "",
        f"Em {wins} de {len(structured)} famílias estruturadas, zstd-19 sem dicionário supera as duas "
        "variantes do STB mesmo quando o dicionário/Γ não é contado. No controle aleatório, todos "
        "os métodos ficam em ~1,0, como esperado.",
        "",
        "Conclusão limitada a este formato, a este encoder e a este orçamento de Γ. Ver "
        "“Ambiente e limitações” e a análise de sensibilidade.",
        "",
    ]
    return "\n".join(lines)


def render_md(results, env):
    lines = [
        "# Resultados do benchmark STB vs. DEFLATE/zstd",
        "",
        f"Gerado em {env['date']} por `bench/run_benchmark.py`.",
        "",
        "Razão de compressão ρ = bytes originais / bytes transmitidos (maior é melhor). "
        "Biblioteca/dicionário treinados **somente** nos dados de treino; medidos somente no teste.",
        "",
        "- **isolado**: o dicionário/biblioteca é pago em cada arquivo (cada arquivo é transmitido sozinho).",
        "- **amortizado**: dicionário/biblioteca pago uma vez por família (receptor já o possui).",
        "- STB inclui um cabeçalho fixo de 40 bytes por arquivo. A coluna \"sem custo de dicionário/Γ\" mostra a força "
        "do codificador sem a biblioteca, para isolar o efeito da estratégia de literais.",
        "",
        render_summary(results),
    ]
    for fam, r in results.items():
        lines += [
            f"## {FAMILY_LABELS.get(fam, fam)}",
            "",
            f"Arquivos de teste: {r['files']} · tamanho original: {r['orig_bytes']/1024:.1f} KiB",
            "",
            "| Método | ρ isolado | ρ amortizado | ρ sem custo de dicionário/Γ | Falhas de round-trip | Tempo (s) |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for name in ("zlib-9", "zstd-19", "zstd-19+dict", "STB", "STB+Ω"):
            m = r["methods"].get(name)
            if m is None:
                lines.append(f"| {name} | — | — | — | — | — |")
                continue
            lines.append(
                f"| {name} | {rho(r['orig_bytes'], m['iso']):.3f} | {rho(r['orig_bytes'], m['amort']):.3f} "
                f"| {rho(r['orig_bytes'], m['payload']):.3f} | {m['fail']} | {m['time_s']:.2f} |"
            )
        s = r["methods"]["STB"]
        s2 = r["methods"]["STB+Ω"]
        lines += [
            "",
            f"Γ: {s['genes']} genes, {s['gamma_bytes']/1024:.1f} KiB. "
            f"STB (formato atual): {100*s['ref_share']:.1f}% dos bytes saem de REF, "
            f"{100*s['literal_share']:.1f}% são literais crus; "
            f"média de {s['genes_used_mean']:.0f} genes distintos por arquivo. "
            f"STB+Ω: resíduo comprimido = {100*s2['residue_share']:.1f}% do original.",
            "",
        ]
    lines += [
        "## Ambiente e limitações",
        "",
        f"- Python {env['python']}, zstandard {env['zstandard']}, numpy {env['numpy']}, {env['platform']}.",
        "- A VM usada pelo STB é um **port Python** de `src/lib.rs` (`bench/stb_vm.py`); o ambiente não tem "
        "toolchain Rust. O round-trip é verificado com esse port, não com o binário Rust.",
        "- O encoder é deliberadamente simples (guloso, genes de 16/32/64 bytes). Ele mede o formato atual, "
        "não o limite teórico do STB.",
        "- O formato não tem REF para bytes já emitidos; repetições intra-arquivo fora de Γ viram literais.",
        "- STB+Ω usa a operação RES, que só existe no port do benchmark (extensão proposta). Ela é a "
        "variante compatível com o paper (resíduo classicamente comprimido), não o formato implementado hoje.",
        "- Dados: Loghub (logpai/loghub), seaborn-data e a stdlib do Python instalada no ambiente. "
        "Os hashes dos arquivos estão em `bench/data/manifest.json` (gerado, fora do Git).",
        "",
    ]
    return "\n".join(lines)


SENS_FAMILIES = ("logs", "codigo", "csv")
SENS_BUDGETS_KIB = (32, 110, 512)


def sensitivity(family):
    """Repete STB, STB+Ω e zstd+dict variando o orçamento de Γ/dicionário."""
    train = [b for _, b in load(family, "train")]
    test = load(family, "test")
    orig_total = sum(len(b) for _, b in test)
    n = len(test)
    cctx = zstandard.ZstdCompressor(level=19)
    rows = []
    for kib in SENS_BUDGETS_KIB:
        budget = kib * 1024
        row = {"budget_kib": kib}
        zdict = train_zstd_dict(train, budget)
        if zdict is not None:
            c = zstandard.ZstdCompressor(level=19, dict_data=zstandard.ZstdCompressionDict(zdict))
            sizes = [len(c.compress(b)) for _, b in test]
            row["zstd-19+dict"] = (sum(sizes), sum(sizes) + len(zdict))
        lib = stb_codec.Library(stb_codec.build_library(train, budget))
        G = lib.serialized_size()
        p_sizes = []
        for _, b in test:
            prog, _, _ = stb_codec.encode(b, lib)
            assert stb_vm.execute(prog, lib.payload) == b
            p_sizes.append(len(prog))
        stb_payload = sum(p_sizes) + CAPSID * n
        row["STB"] = (stb_payload, stb_payload + G)
        o_sizes = []
        for _, b in test:
            prog, _, om = stb_codec.encode(b, lib, residue_mode=True)
            om_c = cctx.compress(om) if om else b""
            assert stb_vm.execute(prog, lib.payload,
                                  residue=zstandard.ZstdDecompressor().decompress(om_c) if om_c else b"") == b
            o_sizes.append(len(prog) + len(om_c))
        omega_payload = sum(o_sizes) + CAPSID * n
        row["STB+Ω"] = (omega_payload, omega_payload + G)
        row["gamma_kib"] = G / 1024
        rows.append(row)
        print(f"    orçamento {kib} KiB: STB+Ω amort={rho(orig_total, omega_payload + G):.3f}")
    return {"files": n, "orig_bytes": orig_total, "rows": rows}


def render_sensitivity(sens):
    lines = [
        "## Sensibilidade ao orçamento de Γ/dicionário",
        "",
        "ρ com orçamento de 32, 110 e 512 KiB (mesmo treino, mesmo teste). Entre parênteses: "
        "ρ sem custo de dicionário/Γ.",
        "",
        "| Família | Orçamento | Γ real (KiB) | zstd-19+dict | STB | STB+Ω |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for fam, r in sens.items():
        for row in r["rows"]:
            cells = []
            for m in ("zstd-19+dict", "STB", "STB+Ω"):
                if m not in row:
                    cells.append("—")
                    continue
                payload, amort = row[m]
                cells.append(f"{rho(r['orig_bytes'], amort):.3f} ({rho(r['orig_bytes'], payload):.3f})")
            lines.append(f"| {FAMILY_LABELS.get(fam, fam).split(' (')[0]} | {row['budget_kib']} KiB | "
                         f"{row['gamma_kib']:.1f} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("O treinador zstd recomenda ~100× o tamanho do dicionário em dados de treino; "
                 "aqui o treino tem 0,3–2,5 MB por família, o que pode subestimar o zstd+dict.")
    lines.append("")
    return "\n".join(lines)


def main():
    if not CORPUS.exists():
        build_corpus.build()
    results = {}
    for fam in ("logs", "codigo", "csv", "binario", "aleatorio"):
        print(f"[{fam}]")
        t = time.perf_counter()
        results[fam] = bench_family(fam)
        print(f"    concluído em {time.perf_counter() - t:.1f}s")
    sens = {}
    for fam in SENS_FAMILIES:
        print(f"[sensibilidade {fam}]")
        sens[fam] = sensitivity(fam)
    env = {
        "date": date.today().isoformat(),
        "python": platform.python_version(),
        "zstandard": zstandard.__version__,
        "numpy": np.__version__,
        "platform": platform.system().lower() + "-" + platform.machine(),
    }
    RESULTS_JSON.write_text(json.dumps({"env": env, "results": results, "sensitivity": sens}, indent=1))
    RESULTS_MD.write_text(render_md(results, env) + render_sensitivity(sens))
    print(f"\nresultados: {RESULTS_MD}")


if __name__ == "__main__":
    sys.setrecursionlimit(10000)
    main()
