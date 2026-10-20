"""Resumo das variantes com Γ, por versão, contra zstd-19 e zstd-19+dicionário.

Lê bench/results/*.json e gera bench/RESULTS_GAMMA.md (e imprime o mesmo texto).

Versões (sempre citar junto dos números):
  v1-guloso : janela de Γ + COPY dentro do arquivo, parser guloso   (gamma_dict_v1-guloso[_swap].json)
  v2-otimo  : janela de Γ + COPY dentro do arquivo, parser ótimo    (gamma_dict_v2-otimo[_swap].json)
  v3-guloso : COPY só em Γ (E0/E1) e genes sem COPY (G0), guloso    (gamma_copy_v3-guloso_<fam>[_swap].json)
  v3-otimo  : COPY só em Γ (E0/E1) e genes sem COPY (G0), ótimo     (gamma_copy_v3-otimo_<fam>[_swap].json)

Variantes:
  A  genes + COPY dentro do arquivo (sem janela)            [v1/v2]
  B  janela de Γ + COPY dentro do arquivo, sem REF          [v1/v2]
  C  janela de Γ + COPY dentro do arquivo + REF de genes    [v1/v2]
  D  sem Γ, COPY dentro do arquivo (referência)             [v1/v2]
  E0 COPY só com fonte em Γ, sem genes                      [v3]
  E1 COPY só com fonte em Γ + REF de genes                  [v3]
  G0 genes sem COPY (REF/RPT apenas)                        [v3]

ρ amortizado: Γ cobrada (min(cru, LZMA2)) nas variantes com Γ; zstd-19+dict cobra o dicionário;
zstd-19 puro não cobra nada. Cabeçalho STB de 40 B por arquivo, como em todo o benchmark.
Empacotadores: "fluxos" = pack_streams (zstd-19 por fluxo); "rc" = codificador adaptativo (token_coder).

Uso: python3 bench/summarize_gamma.py [--md bench/RESULTS_GAMMA.md]
"""

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
FAMS = ("logs", "codigo", "csv", "binario")
GROUPS = [
    ("A genes + COPY intra", lambda v, c: v in ("v1-guloso", "v2-otimo") and c.startswith("A ")),
    ("B janela Γ + COPY intra", lambda v, c: v in ("v1-guloso", "v2-otimo") and c.startswith("B ")),
    ("C janela Γ + COPY intra + genes", lambda v, c: v in ("v1-guloso", "v2-otimo") and c.startswith("C ")),
    ("E0 COPY só em Γ", lambda v, c: v.startswith("v3") and c.startswith("E0 ")),
    ("E1 COPY só em Γ + genes", lambda v, c: v.startswith("v3") and c.startswith("E1 ")),
    ("G0 genes sem COPY", lambda v, c: v.startswith("v3") and c.startswith("G0 ")),
]
REF_NO_GAMMA = ("D sem Γ", lambda v, c: v in ("v1-guloso", "v2-otimo") and c.startswith("D "))


def load_split(swap: bool):
    """{família: [(versão, config, empacotador, ρ_amort, ρ_sem_custo, falhas)]}"""
    suf = "_swap" if swap else ""
    rows = {f: [] for f in FAMS}
    for fam in FAMS:
        for ver in ("v1-guloso", "v2-otimo"):
            p = RES / f"gamma_dict_{ver}{suf}.json"
            if p.exists():
                for variant, x in json.load(open(p)).get(fam, {}).items():
                    add(rows[fam], ver, f"{variant} {x['label']}", x)
        for parser in ("guloso", "otimo"):
            p = RES / f"gamma_copy_v3-{parser}_{fam}{suf}.json"
            if p.exists():
                for variant, x in json.load(open(p)).items():
                    add(rows[fam], x["versao"], f"{variant} {x['label']}", x)
    return rows


def add(out, ver, cfg, x):
    for pk, key, pay in (("fluxos", "rho_streams_amort", "rho_streams_payload"),
                         ("rc", "rho_rc_amort", "rho_rc_payload")):
        out.append((ver, cfg, pk, x[key], x[pay], x["fails"], x["gamma_charge"] if "gamma_charge" in x else None))


def baselines(swap: bool):
    d = json.load(open(RES / "zstd_baselines.json"))
    return d["swap" if swap else "normal"]


def pick(rows, pred):
    cands = [r for r in rows if pred(r[0], r[1])]
    return max(cands, key=lambda r: r[3]) if cands else None


def fmt(r, base):
    ver, cfg, pk, rho, pay, fails, _ = r
    return f"{ver} · {cfg} · {pk} · {rho:.3f} ({(rho / base - 1) * 100:+.1f}%)"


def render() -> str:
    out = []
    for swap in (False, True):
        label = "swap" if swap else "normal"
        rows, bl = load_split(swap), baselines(swap)
        out.append(f"## Divisão {label}\n")
        out.append("| Família | zstd-19 | zstd-19+dict | melhor com Γ (vs zstd-19+dict) | melhor sem Γ (vs zstd-19) |")
        out.append("|---|---|---|---|---|")
        for fam in FAMS:
            z19, zd = bl[fam]["zstd19"], bl[fam]["zstd19_dict"]
            best = max((r for r in rows[fam] if not r[1].startswith("D ")), key=lambda r: r[3])
            ref = pick(rows[fam], lambda v, c: REF_NO_GAMMA[1](v, c))
            out.append(f"| {fam} | {z19:.3f} | {zd:.3f} | {fmt(best, zd)} | {fmt(ref, z19)} |")
        out.append("")
        out.append("Melhor de cada grupo (ρ amortizado; % em relação ao zstd-19+dict):\n")
        out.append("| Família | Grupo | Versão · configuração · empacotador | ρ | falhas |")
        out.append("|---|---|---|---|---|")
        for fam in FAMS:
            zd = bl[fam]["zstd19_dict"]
            for name, pred in GROUPS:
                r = pick(rows[fam], pred)
                if r:
                    out.append(f"| {fam} | {name} | {fmt(r, zd)} | {r[3]:.3f} | {r[5]} |")
        out.append("")
    return "\n".join(out)


HEADER = """# Resultados com Γ: versões v1, v2 e v3

Gerado por `bench/summarize_gamma.py` a partir de `bench/results/` (ignorado pelo Git).
Reprodução: `exp_gamma_dict.py --parser guloso|otimo` (v1-guloso, v2-otimo),
`exp_gamma_copy.py --parser guloso|otimo` (v3-guloso, v3-otimo), `zstd_baselines.py`.

## Versões

- **v1-guloso**: janela de Γ + COPY dentro do arquivo, parser guloso.
- **v2-otimo**: a mesma janela, parser ótimo (DP).
- **v3-guloso / v3-otimo**: COPY só com fonte inteiramente em Γ (sem COPY dentro do arquivo); genes sem COPY (G0) também medidos.

Variantes: A genes + COPY intra; B janela + COPY intra (sem REF); C janela + COPY intra + REF; D sem Γ;
E0 COPY só em Γ; E1 COPY só em Γ + REF; G0 genes sem COPY.

## Leitura

- Nenhuma configuração supera o zstd-19 puro em nenhuma família e divisão. A melhor com Γ e a melhor sem Γ ficam abaixo dele.
- Contra o zstd-19+dicionário (que também paga o dicionário), a melhor configuração com Γ vence em CSV e pyc, usando G0 (genes sem COPY, fluxos). Nos logs e no código, perde: 8% e 0,6%.
- A configuração "D sem Γ" não paga Γ nem dicionário. Por isso ela é comparada ao zstd-19 puro, e não ao zstd-19+dicionário.
- COPY só em Γ (E0/E1) perde para genes sem COPY nos fluxos, em todas as famílias e nas duas divisões. Com o codificador adaptativo também fica abaixo da melhor configuração em todas as famílias.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default=None, help="caminho do arquivo markdown a gravar")
    args = ap.parse_args()
    text = (HEADER + "\n" + render()) if args.md else render()
    print(text)
    if args.md:
        Path(args.md).write_text(text + "\n")
        print("gravado:", args.md)


if __name__ == "__main__":
    main()
