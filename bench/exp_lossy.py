#!/usr/bin/env python3
"""Experimento com perda (regime perceptual, métrica SSIM).

Versões do codificador (o fluxo e o decodificador são os mesmos nas duas):
- stb-lossy-v1: escolha gananciosa. Para cada bloco, o primeiro gene na ordem
  FLAT -> REF -> PLANE cujo SSIM local >= tau; senão RES.
- stb-lossy-v2-rd: escolha por custo. Para cada bloco, o candidato que minimiza
  bits + lam * (1 - SSIM_local), entre FLAT, REF, PLANE e RES.

Referências: Q+xz (mesmo quantizador, sem genes), JPEG, WebP (Pillow) e zstd-19 exato.
Conjuntos: "naturais" (imagens do scikit-image) e "estruturadas" (synth_structured.py).

Regras (ver bench/LOSSY.md):
- Imagens em tons de cinza, cortadas para múltiplos de 8. Blocos 8x8 em varredura.
- REF aponta para um dos últimos W = 1024 blocos já decodificados. Γ não é um arquivo
  separado: a biblioteca são os blocos decodificados.
- Custo do STB: 40 B de capsídeo + fluxos. Q+xz paga só os fluxos. JPEG/WebP pagam o arquivo.
- Para cada alvo de SSIM, a configuração de menor bpp com SSIM >= alvo (por imagem).
- Custo de bits usado só na escolha RD (modelo, não medido): FLAT 8, REF 16, PLANE 24,
  RES 64 * log2(256 // q + 1). Os tamanhos medidos são os dos fluxos reais.
- O decodificador é de referência, em Python. A via com perda não passa pela VM STB.

Uso:
  python bench/exp_lossy.py --modo limiar --conjunto naturais
  python bench/exp_lossy.py --modo rd --conjunto estruturadas
"""

import argparse
import io
import json
import lzma
import math
import os
import sys
import time

import numpy as np
import zstandard as zstd
from PIL import Image
from skimage import data as skdata
from skimage.metrics import peak_signal_noise_ratio, structural_similarity

import synth_structured

VERSAO_LIMIAR = "stb-lossy-v1"
VERSAO_RD = "stb-lossy-v2-rd"
VERSAO_POR_MODO = {"limiar": VERSAO_LIMIAR, "rd": VERSAO_RD}

B = 8  # tamanho do bloco
W = 1024  # janela da biblioteca de REF (blocos decodificados)
CAPSID_BYTES = 40
PLANE_STEP = 0.25  # passo dos coeficientes de gradiente (int8)
FLAT, REF, PLANE, RES = 0, 1, 2, 3
TAU_GRID = [0.9999, 0.99, 0.97, 0.94, 0.9, 0.8]  # limiar de SSIM local (modo limiar)
LAM_GRID = [100, 300, 1000, 3000, 10000, 30000]  # peso da distorção (modo rd)
Q_GRID = [1, 2, 4, 8, 16, 32]  # passo do quantizador do resíduo
JPEG_Q = [10, 20, 30, 40, 50, 60, 70, 80, 90, 95]
WEBP_Q = [10, 20, 30, 40, 50, 60, 70, 80, 90, 95]
TARGETS = [0.90, 0.95, 0.98, 0.9999]  # 0.9999 = quase sem perda
LZMA_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 9 | lzma.PRESET_EXTREME}]
C1 = (0.01 * 255) ** 2
C2 = (0.03 * 255) ** 2

_YY, _XX = np.mgrid[0:B, 0:B]
_DESIGN = np.stack([np.ones(B * B), _XX.ravel(), _YY.ravel()], 1).astype(float)
_PINV = np.linalg.pinv(_DESIGN)


# ---------------------------------------------------------------- imagens


def _gray(img):
    return np.asarray(Image.fromarray(img).convert("L"))


def _crop8(img):
    h, w = img.shape
    return np.ascontiguousarray(img[: h // B * B, : w // B * B])


def load_images(conjunto="naturais"):
    if conjunto == "estruturadas":
        return {k: _crop8(np.asarray(v, dtype=np.uint8)) for k, v in synth_structured.carregar_estruturadas().items()}
    fontes = {
        "camera": skdata.camera,
        "astronaut": lambda: _gray(skdata.astronaut()),
        "moon": skdata.moon,
        "brick": skdata.brick,
        "grass": skdata.grass,
        "gravel": skdata.gravel,
        "page": skdata.page,
        "coffee": lambda: _gray(skdata.coffee()),
    }
    return {k: _crop8(np.asarray(f(), dtype=np.uint8)) for k, f in fontes.items()}


# ---------------------------------------------------------------- blocos


def to_blocks(img):
    h, w = img.shape
    return img.reshape(h // B, B, w // B, B).transpose(0, 2, 1, 3).reshape(-1, B * B).astype(np.int32)


def from_blocks(blocks, h, w):
    return blocks.reshape(h // B, w // B, B, B).transpose(0, 2, 1, 3).reshape(h, w).astype(np.uint8)


def plane_fit(bloco):
    """Coeficientes (a, b, c) do plano a + b*j + c*i, com b e c quantizados."""
    coef = _PINV @ bloco.astype(float)
    a = int(np.clip(np.round(coef[0]), 0, 255))
    bq = int(np.clip(np.round(coef[1] / PLANE_STEP), -128, 127))
    cq = int(np.clip(np.round(coef[2] / PLANE_STEP), -128, 127))
    return a, bq, cq


def plane_render(a, bq, cq):
    p = a + PLANE_STEP * bq * _XX.ravel() + PLANE_STEP * cq * _YY.ravel()
    return np.clip(np.round(p), 0, 255).astype(np.int32)


def quant(bloco, q):
    return np.clip(bloco // q, 0, 255 // q)


def dequant(niveis, q):
    return np.clip(niveis * q + q // 2, 0, 255).astype(np.int32)


def bssim(x, y):
    """SSIM local de um bloco x contra blocos y de forma (..., 64)."""
    mx = x.mean()
    my = y.mean(axis=-1)
    vx = x.var()
    vy = y.var(axis=-1)
    cov = ((x - mx) * (y - my[..., None])).mean(axis=-1)
    return ((2 * mx * my + C1) * (2 * cov + C2)) / ((mx**2 + my**2 + C1) * (vx + vy + C2))


# ---------------------------------------------------------------- empacotamento


def _uvarint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _read_uvarint(buf, pos):
    resultado, shift = 0, 0
    while True:
        if pos >= len(buf):
            raise ValueError("varint truncado")
        b = buf[pos]
        pos += 1
        resultado |= (b & 0x7F) << shift
        if not b & 0x80:
            return resultado, pos
        shift += 7
        if shift > 35:
            raise ValueError("varint longo demais")


def _pack_sub(raw):
    """Um fluxo: método (0 cru, 1 LZMA2 raw 9e), tamanho cru, tamanho do corpo, corpo."""
    metodo, corpo = 0, raw
    comp = lzma.compress(raw, format=lzma.FORMAT_RAW, filters=LZMA_FILTERS)
    if len(comp) < len(corpo):
        metodo, corpo = 1, comp
    return bytes([metodo]) + _uvarint(len(raw)) + _uvarint(len(corpo)) + corpo


def _unpack_sub(buf, pos):
    if pos >= len(buf):
        raise ValueError("fluxo ausente")
    metodo = buf[pos]
    pos += 1
    n_raw, pos = _read_uvarint(buf, pos)
    n_corpo, pos = _read_uvarint(buf, pos)
    if pos + n_corpo > len(buf):
        raise ValueError("corpo truncado")
    corpo = buf[pos : pos + n_corpo]
    pos += n_corpo
    if metodo == 0:
        raw = bytes(corpo)
    elif metodo == 1:
        try:
            raw = lzma.decompress(corpo, format=lzma.FORMAT_RAW, filters=LZMA_FILTERS)
        except lzma.LZMAError as e:
            raise ValueError(f"LZMA inválido: {e}") from e
    else:
        raise ValueError(f"método desconhecido: {metodo}")
    if len(raw) != n_raw:
        raise ValueError("tamanho do fluxo não confere")
    return raw, pos


def _pack_choices(ch):
    pad = (-len(ch)) % 4
    arr = np.concatenate([ch, np.zeros(pad, np.uint8)]).reshape(-1, 4).astype(np.uint8)
    return (arr[:, 0] | (arr[:, 1] << 2) | (arr[:, 2] << 4) | (arr[:, 3] << 6)).astype(np.uint8).tobytes()


def _unpack_choices(raw, n):
    if len(raw) != (n + 3) // 4:
        raise ValueError("fluxo de escolhas com tamanho errado")
    a = np.frombuffer(raw, np.uint8)
    return np.stack([(a >> s) & 3 for s in (0, 2, 4, 6)], 1).ravel()[:n]


# ---------------------------------------------------------------- stb-lossy


def _bits_res(q):
    return 64 * math.log2(256 // q + 1)


def _candidatos(x, k, dec, q, usar_ref):
    """Gera (escolha, reconstrução, SSIM local, bits estimados, payload) na ordem FLAT, REF, PLANE, RES.

    O último candidato (RES) é sempre gerado.
    """
    v = int(np.clip(np.round(x.mean()), 0, 255))
    plano = np.full(B * B, v, np.int32)
    yield FLAT, plano, float(bssim(x, plano)), 8, bytes([v])
    if usar_ref and k > 0:
        lo = max(0, k - W)
        s = bssim(x, dec[lo:k].astype(float))
        j = int(np.argmax(s))
        off = (k - 1) - (lo + j)  # 0 = bloco mais recente
        yield REF, dec[lo + j].copy(), float(s[j]), 16, bytes([off & 0xFF, off >> 8])
    a, bq, cq = plane_fit(x)
    pr = plane_render(a, bq, cq)
    yield PLANE, pr, float(bssim(x, pr.astype(float))), 24, bytes([a, bq & 0xFF, cq & 0xFF])
    niveis = quant(x, q)
    yield RES, dequant(niveis, q), float(bssim(x, dequant(niveis, q).astype(float))), _bits_res(q), bytes(niveis.astype(np.uint8))


def encode(img, q, tau=0.9, usar_ref=True, lam=None):
    """Codifica uma imagem.

    lam is None: modo limiar (stb-lossy-v1), com limiar tau.
    lam numérico: modo rd (stb-lossy-v2-rd), minimizando bits + lam * (1 - SSIM_local).
    Devolve (blob, reconstrução, contagem por gene [FLAT, REF, PLANE, RES]).
    """
    h, w = img.shape
    X = to_blocks(img)
    n = X.shape[0]
    dec = np.zeros((n, B * B), np.int32)
    escolhas = np.zeros(n, np.uint8)
    valores, refs, res = bytearray(), bytearray(), bytearray()
    contagem = [0, 0, 0, 0]
    for k in range(n):
        x = X[k]
        if lam is None:
            escolhido = None
            for cand in _candidatos(x, k, dec, q, usar_ref):
                if cand[2] >= tau or cand[0] == RES:
                    escolhido = cand
                    break
        else:
            cands = list(_candidatos(x, k, dec, q, usar_ref))
            escolhido = min(cands, key=lambda c: c[3] + lam * (1.0 - c[2]))
        escolha, rec, _, _, payload = escolhido
        if escolha in (FLAT, PLANE):
            valores += payload
        elif escolha == REF:
            refs += payload
        else:
            res += payload
        escolhas[k] = escolha
        contagem[escolha] += 1
        dec[k] = rec
    blob = (
        _uvarint(h)
        + _uvarint(w)
        + bytes([q])
        + _pack_sub(_pack_choices(escolhas))
        + _pack_sub(bytes(valores))
        + _pack_sub(bytes(refs))
        + _pack_sub(bytes(res))
    )
    return blob, from_blocks(dec, h, w), contagem


def decode(blob):
    pos = 0
    h, pos = _read_uvarint(blob, pos)
    w, pos = _read_uvarint(blob, pos)
    if h == 0 or w == 0 or h % B or w % B:
        raise ValueError("dimensões inválidas")
    if pos >= len(blob):
        raise ValueError("passo de quantização ausente")
    q = blob[pos]
    pos += 1
    if q == 0:
        raise ValueError("passo de quantização zero")
    n = (h // B) * (w // B)
    raw_ch, pos = _unpack_sub(blob, pos)
    valores, pos = _unpack_sub(blob, pos)
    refs, pos = _unpack_sub(blob, pos)
    res, pos = _unpack_sub(blob, pos)
    if pos != len(blob):
        raise ValueError("bytes sobrando após os fluxos")
    escolhas = _unpack_choices(raw_ch, n)
    if len(refs) % 2:
        raise ValueError("fluxo REF com tamanho ímpar")
    dec = np.zeros((n, B * B), np.int32)
    vi = ri = si = 0
    for k in range(n):
        c = int(escolhas[k])
        if c == FLAT:
            if vi + 1 > len(valores):
                raise ValueError("fluxo de valores esgotado")
            rec = np.full(B * B, valores[vi], np.int32)
            vi += 1
        elif c == REF:
            if 2 * ri + 2 > len(refs):
                raise ValueError("fluxo REF esgotado")
            off = refs[2 * ri] | (refs[2 * ri + 1] << 8)
            ri += 1
            if off >= min(k, W):
                raise ValueError("referência REF fora da janela")
            rec = dec[k - 1 - off].copy()
        elif c == PLANE:
            if vi + 3 > len(valores):
                raise ValueError("fluxo de valores esgotado")
            a = valores[vi]
            bq = valores[vi + 1] - 256 if valores[vi + 1] >= 128 else valores[vi + 1]
            cq = valores[vi + 2] - 256 if valores[vi + 2] >= 128 else valores[vi + 2]
            vi += 3
            rec = plane_render(a, bq, cq)
        else:
            if si + B * B > len(res):
                raise ValueError("fluxo de resíduo esgotado")
            niveis = np.frombuffer(res[si : si + B * B], np.uint8).astype(np.int32)
            si += B * B
            if niveis.max() > 255 // q:
                raise ValueError("nível de resíduo fora do intervalo")
            rec = dequant(niveis, q)
        dec[k] = rec
    if vi != len(valores) or ri * 2 != len(refs) or si != len(res):
        raise ValueError("algum fluxo não foi consumido por completo")
    return from_blocks(dec, h, w)


# ---------------------------------------------------------------- referências


def encode_qxz(img, q):
    h, w = img.shape
    niveis = quant(img.astype(np.int32), q).astype(np.uint8)
    blob = _uvarint(h) + _uvarint(w) + bytes([q]) + _pack_sub(niveis.tobytes())
    return blob, dequant(niveis.astype(np.int32), q).astype(np.uint8)


def decode_qxz(blob):
    pos = 0
    h, pos = _read_uvarint(blob, pos)
    w, pos = _read_uvarint(blob, pos)
    if pos >= len(blob) or blob[pos] == 0:
        raise ValueError("passo inválido")
    q = blob[pos]
    pos += 1
    raw, pos = _unpack_sub(blob, pos)
    if pos != len(blob) or len(raw) != h * w:
        raise ValueError("Q+xz inválido")
    return dequant(np.frombuffer(raw, np.uint8).astype(np.int32), q).reshape(h, w).astype(np.uint8)


def encode_pil(img, fmt, qualidade):
    buf = io.BytesIO()
    im = Image.fromarray(img)
    if fmt == "WEBP":
        im = im.convert("RGB")
    im.save(buf, format=fmt, quality=qualidade)
    data = buf.getvalue()
    rec = np.asarray(Image.open(io.BytesIO(data)).convert("L"))
    return len(data), rec


# ---------------------------------------------------------------- experimento


def _psnr(a, b):
    with np.errstate(divide="ignore"):
        v = float(peak_signal_noise_ratio(a, b, data_range=255))
    return v if math.isfinite(v) else None


def medir(img, codec, cfg, tamanho, rec):
    h, w = img.shape
    return {
        "codec": codec,
        "cfg": cfg,
        "bytes": int(tamanho),
        "bpp": tamanho * 8 / (h * w),
        "ssim": float(structural_similarity(img, rec, data_range=255)),
        "psnr": _psnr(img, rec),
    }


def rodar_imagem(img, modo):
    principal = VERSAO_POR_MODO[modo]
    linhas = []
    for q in Q_GRID:
        blob, rec = encode_qxz(img, q)
        if not np.array_equal(decode_qxz(blob), rec):
            raise AssertionError("Q+xz: decodificação diferente da reconstrução")
        linhas.append(medir(img, "Q+xz", f"q={q}", len(blob), rec))
    for variante, usar_ref in [(principal, True), (principal + " sem REF", False)]:
        for q in Q_GRID:
            grade = TAU_GRID if modo == "limiar" else LAM_GRID
            for p in grade:
                if modo == "limiar":
                    blob, rec, contagem = encode(img, q, tau=p, usar_ref=usar_ref)
                    cfg = f"q={q},tau={p}"
                else:
                    blob, rec, contagem = encode(img, q, usar_ref=usar_ref, lam=p)
                    cfg = f"q={q},lam={p}"
                if not np.array_equal(decode(blob), rec):
                    raise AssertionError(f"{variante} {cfg}: decodificação diferente")
                linha = medir(img, variante, cfg, len(blob) + CAPSID_BYTES, rec)
                linha["genes"] = dict(zip(["FLAT", "REF", "PLANE", "RES"], contagem))
                linhas.append(linha)
    for codec, fmt, qs in [("JPEG", "JPEG", JPEG_Q), ("WebP", "WEBP", WEBP_Q)]:
        for qq in qs:
            tam, rec = encode_pil(img, fmt, qq)
            linhas.append(medir(img, codec, f"quality={qq}", tam, rec))
    exato = zstd.ZstdCompressor(level=19).compress(img.tobytes())
    linhas.append(medir(img, "zstd-19 (exato)", "exato", len(exato), img))
    return linhas


def melhor_em(linhas, codec, alvo):
    cands = [r for r in linhas if r["codec"] == codec and r["ssim"] >= alvo]
    return min(cands, key=lambda r: r["bpp"]) if cands else None


def codecs_resumo(principal):
    return [principal, principal + " sem REF", "Q+xz", "JPEG", "WebP", "zstd-19 (exato)"]


def resumir(resultados, principal):
    resumo = {}
    for alvo in TARGETS:
        resumo[str(alvo)] = {
            codec: {nome: (melhor_em(linhas, codec, alvo) or {}) for nome, linhas in resultados.items()}
            for codec in codecs_resumo(principal)
        }
    return resumo


def contagens(resultados, a, b, alvo):
    """Vitórias, empates e derrotas de a contra b por imagem (bpp menor vence), e média geométrica."""
    vit = emp = der = 0
    razoes = []
    for linhas in resultados.values():
        ra, rb = melhor_em(linhas, a, alvo), melhor_em(linhas, b, alvo)
        if not (ra and rb):
            continue
        r = ra["bpp"] / rb["bpp"]
        razoes.append(r)
        if r < 0.999:
            vit += 1
        elif r > 1.001:
            der += 1
        else:
            emp += 1
    geo = math.exp(sum(math.log(x) for x in razoes) / len(razoes)) if razoes else None
    return {"melhor": vit, "empate": emp, "pior": der, "n": len(razoes), "geo": geo}


def imprimir(resultados, principal):
    cods = codecs_resumo(principal)
    for alvo in TARGETS:
        print(f"\n=== alvo SSIM >= {alvo} ===")
        print(f"{'imagem':14s}" + "".join(f"{c[:17]:>19s}" for c in cods))
        for nome, linhas in resultados.items():
            celulas = []
            for codec in cods:
                r = melhor_em(linhas, codec, alvo)
                celulas.append(f"{r['bpp']:.3f}/{r['ssim']:.3f}" if r else "—")
            print(f"{nome:14s}" + "".join(f"{c:>19s}" for c in celulas))
        print("Contagem por imagem (principal contra a referência; melhor/empate/pior; média geométrica de bpp):")
        for outro in [principal + " sem REF", "Q+xz", "JPEG", "WebP"]:
            c = contagens(resultados, principal, outro, alvo)
            if c["n"]:
                print(f"  vs {outro:22s}: {c['melhor']}/{c['empate']}/{c['pior']} (n={c['n']}), geo={c['geo']:.3f}")
            else:
                print(f"  vs {outro:22s}: sem imagens comparáveis")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["limiar", "rd"], default="limiar")
    ap.add_argument("--conjunto", choices=["naturais", "estruturadas"], default="naturais")
    ap.add_argument("--images", default="", help="lista separada por vírgula; padrão: todas do conjunto")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    principal = VERSAO_POR_MODO[args.modo]
    imagens = load_images(args.conjunto)
    if args.images:
        imagens = {k: imagens[k] for k in args.images.split(",")}
    resultados = {}
    for nome, img in imagens.items():
        t0 = time.time()
        resultados[nome] = rodar_imagem(img, args.modo)
        print(f"{nome}: {img.shape}, {len(resultados[nome])} pontos, {time.time() - t0:.1f} s", file=sys.stderr)
    imprimir(resultados, principal)
    out = args.out or os.path.join(os.path.dirname(__file__), "results", f"lossy_{principal}_{args.conjunto}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(
            {
                "versao": principal,
                "conjunto": args.conjunto,
                "alvos": TARGETS,
                "resultados": resultados,
                "resumo": resumir(resultados, principal),
            },
            f,
            ensure_ascii=False,
            indent=1,
        )
    print(f"\nJSON: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
