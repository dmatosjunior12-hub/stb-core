"""Baselines (zstd-19, zstd-19+dict, xz-9e) para a mesma divisão usada por compare_parsers.py.

Uso:  python3 bench/baselines_split.py [--swap]   -> bench/results/baselines[_swap].json
Custo do dicionário zstd = min(cru, LZMA2 raw 9e), amortizado uma vez por família (mesma regra de Γ).
"""
import argparse
import json
import lzma
from pathlib import Path

import zstandard

import run_benchmark as rb
import stb_v2

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
FAMILIES = ("logs", "codigo", "csv", "binario")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--swap", action="store_true")
    args = ap.parse_args()
    res = {}
    for fam in FAMILIES:
        train = rb.load(fam, "train")
        test = rb.load(fam, "test")
        train = [b for _, b in train]
        test = [b for _, b in test]
        if args.swap:
            train, test = test, train
        orig = sum(map(len, test))
        c19 = zstandard.ZstdCompressor(level=19)
        plain = sum(len(c19.compress(b)) for b in test)
        xz = sum(len(lzma.compress(b, format=lzma.FORMAT_XZ, preset=9 | lzma.PRESET_EXTREME)) for b in test)
        zdict = rb.train_zstd_dict(train)
        if zdict is not None:
            cd = zstandard.ZstdCompressor(level=19, dict_data=zstandard.ZstdCompressionDict(zdict))
            dsz = sum(len(cd.compress(b)) for b in test)
            D = rb.charged(zdict)
            dict_rho_amort = orig / (dsz + D)
            dict_rho_payload = orig / dsz
        else:
            dict_rho_amort = dict_rho_payload = float("nan")
        res[fam] = {
            "orig": orig,
            "zstd19_rho": orig / plain,
            "xz9e_rho": orig / xz,
            "zstd19_dict_rho_amort": dict_rho_amort,
            "zstd19_dict_rho_payload": dict_rho_payload,
        }
        print(f"  {fam:8s} zstd-19={orig/plain:6.3f} xz-9e={orig/xz:6.3f} "
              f"zstd+dict amort={dict_rho_amort:6.3f} (sem custo={dict_rho_payload:6.3f})", flush=True)
    OUT.mkdir(exist_ok=True)
    name = "baselines_swap.json" if args.swap else "baselines.json"
    (OUT / name).write_text(json.dumps(res, indent=1))
    print("gravado:", OUT / name)


if __name__ == "__main__":
    main()
