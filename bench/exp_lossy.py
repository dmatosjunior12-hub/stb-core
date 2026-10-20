#!/usr/bin/env python3
"""stb-lossy-v1: experimento com perda (regime perceptual, métrica SSIM).

Compara o STB com tolerância contra JPEG, WebP e duas referências:
- Q+xz: o mesmo quantizador do resíduo aplicado a todos os pixels, sem genes.
  Isola o efeito dos genes: se STB não supera Q+xz, os genes não ajudam.
- zstd-19 exato: referência sem perda.

Regras declaradas (não calibradas; ver bench/LOSSY.md):
- Imagens em tons de cinza, cortadas para múltiplos de 8. Blocos 8x8 em varredura.
- Critério de aceitação de gene: SSIM local do bloco (mesma fórmula do SSIM, sem janela
  deslizante, com C1 e C2 do SSIM) >= tau. Cada bloco recebe o primeiro gene que satisfaz,
  na ordem FLAT -> REF -> PLANE; se nenhum satisfaz, RES (resíduo quantizado com passo q).
  RES é sempre permitido. Um piloto com MSE como critério foi descartado: MSE baixo aceitava
  blocos texturados trocados por média plana, com SSIM global ruim.
- REF aponta para um dos últimos W = 1024 blocos já decodificados. Γ não é um arquivo
  separado: a biblioteca são os blocos decodificados, e seu custo é o das próprias
  instruções que a constroem.
- Custo do STB: 40 B de capsídeo (como no fluxos-v1) + fluxos. Q+xz paga só seus
  fluxos. JPEG e WebP pagam o arquivo inteiro.
- Para cada alvo de SSIM, a configuração de menor bpp com SSIM >= alvo.
- O decodificador é de referência em Python. A via com perda não passa pela VM STB.

Uso: python bench/exp_lossy.py [--images camera,moon] [--out bench/results/lossy_stb-lossy-v1.json]
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

VERSION = "stb-lossy-v1"
B = 8  # tamanho do bloco
W = 1024  # janela da biblioteca de REF (blocos decodificados)
CAPSID_BYTES = 40
PLANE_STEP = 0.25  # passo dos coeficientes de gradiente (int8)
FLAT, REF, PLANE, RES = 0, 1, 2, 3
TAU_GRID = [0.9999, 0.99, 0.97, 0.94, 0.9, 0.8]  # limiar de SSIM local por bloco
Q_GRID = [1, 2, 4, 8, 16, 32]  # passo do quantizador do resíduo
C1 = (0.01 * 255) ** 2
C2 = (0.03 * 255) ** 2
JPEG_Q = [10, 20, 30, 40, 50, 60, 70, 80, 90, 95]
WEBP_Q = [10, 20, 30, 40, 50, 60, 70, 80, 90, 95]
TARGETS = [0.90, 0.95, 0.98, 0.9999]  # 0.9999 = sem perda
LZMA_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 9 | lzma.PRESET_EXTREME}]

_YY, _XX = np.mgrid[0:B, 0:B]
_DESIGN = np.stack([np.ones(B * B), _XX.ravel(), _YY.ravel()], 1).astype(float)
_PINV = np.linalg.pinv(_DESIGN)


# ---------------------------------------------------------------- imagens


def _gray(img):
    return np.asarray(Image.fromarray(img).convert("L"))


def _crop8(img):
    h, w = img.shape
    return np.ascontiguousarray(img[: h // B * B, : w // B * B])


def load_images():
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


# ---------------------------------------------------------------- stb-lossy-v1


def encode(img, q, tau, usar_ref=True):
    """Codifica uma imagem. Devolve (blob, reconstrução, contagem por gene)."""
    h, w = img.shape
    X = to_blocks(img)
    n = X.shape[0]
    dec = np.zeros((n, B * B), np.int32)
    escolhas = np.zeros(n, np.uint8)
    valores, refs, res = bytearray(), bytearray(), bytearray()
    contagem = [0, 0, 0, 0]
    for k in range(n):
        x = X[k]
        v = int(np.clip(np.round(x.mean()), 0, 255))
        plano_flat = np.full(B * B, v, np.int32)
        rec, escolha = None, None
        if bssim(x, plano_flat) >= tau:
            escolha, rec = FLAT, plano_flat
            valores.append(v)
        if rec is None and usar_ref and k > 0:
            lo = max(0, k - W)
            s = bssim(x, dec[lo:k].astype(float))
            j = int(np.argmax(s))
            if s[j] >= tau:
                off = (k - 1) - (lo + j)  # 0 = bloco mais recente
                escolha, rec = REF, dec[lo + j].copy()
                refs += bytes([off & 0xFF, off >> 8])
        if rec is None:
            a, bq, cq = plane_fit(x)
            pr = plane_render(a, bq, cq)
            if bssim(x, pr.astype(float)) >= tau:
                escolha, rec = PLANE, pr
                valores += bytes([a, bq & 0xFF, cq & 0xFF])
        if rec is None:
            niveis = quant(x, q)
            escolha, rec = RES, dequant(niveis, q)
            res += bytes(niveis.astype(np.uint8))
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


def rodar_imagem(img):
    linhas = []
    for q in Q_GRID:
        blob, rec = encode_qxz(img, q)
        if not np.array_equal(decode_qxz(blob), rec):
            raise AssertionError("Q+xz: decodificação diferente da reconstrução")
        linhas.append(medir(img, "Q+xz", f"q={q}", len(blob), rec))
    for variante, usar_ref in [(VERSION, True), (VERSION + " sem REF", False)]:
        for q in Q_GRID:
            for tau in TAU_GRID:
                blob, rec, contagem = encode(img, q, tau, usar_ref)
                if not np.array_equal(decode(blob), rec):
                    raise AssertionError(f"{variante} q={q} tau={tau}: decodificação diferente")
                linha = medir(img, variante, f"q={q},tau={tau}", len(blob) + CAPSID_BYTES, rec)
                linha["genes"] = dict(zip(["FLAT", "REF", "PLANE", "RES"], contagem))
                linhas.append(linha)
    for codec, fmt, qs in [("JPEG", "JPEG", JPEG_Q), ("WebP", "WEBP", WEBP_Q)]:
        for qq in qs:
            tam, rec = encode_pil(img, fmt, qq)
            linhas.append(medir(img, codec, f"quality={qq}", tam, rec))
    raw = img.tobytes()
    exato = zstd.ZstdCompressor(level=19).compress(raw)
    linhas.append(medir(img, "zstd-19 (exato)", "exato", len(exato), img))
    return linhas


def melhor_em(linhas, codec, alvo):
    cands = [r for r in linhas if r["codec"] == codec and r["ssim"] >= alvo]
    return min(cands, key=lambda r: r["bpp"]) if cands else None


CODECS_RESUMO = [VERSION, VERSION + " sem REF", "Q+xz", "JPEG", "WebP", "zstd-19 (exato)"]


def resumir(resultados):
    resumo = {}
    for alvo in TARGETS:
        por_codec = {}
        for codec in CODECS_RESUMO:
            por_codec[codec] = {
                nome: (melhor_em(linhas, codec, alvo) or {}) for nome, linhas in resultados.items()
            }
        resumo[str(alvo)] = por_codec
    return resumo


def media_geo_razao(resultados, alvo, a, b):
    """Média geométrica de bpp(a)/bpp(b) nas imagens em que os dois atingem o alvo."""
    razoes = []
    for linhas in resultados.values():
        ra, rb = melhor_em(linhas, a, alvo), melhor_em(linhas, b, alvo)
        if ra and rb:
            razoes.append(ra["bpp"] / rb["bpp"])
    if not razoes:
        return None, 0
    return math.exp(sum(math.log(x) for x in razoes) / len(razoes)), len(razoes)


def imprimir(resultados):
    for alvo in TARGETS:
        print(f"\n=== alvo SSIM >= {alvo} ===")
        print(f"{'imagem':10s}" + "".join(f"{c[:17]:>19s}" for c in CODECS_RESUMO))
        for nome, linhas in resultados.items():
            celulas = []
            for codec in CODECS_RESUMO:
                r = melhor_em(linhas, codec, alvo)
                celulas.append(f"{r['bpp']:.3f}/{r['ssim']:.3f}" if r else "—")
            print(f"{nome:10s}" + "".join(f"{c:>19s}" for c in celulas))
        print("bpp / SSIM da melhor configuração por codec (— = alvo não atingido)")
        for outro in ["JPEG", "WebP", "Q+xz", VERSION + " sem REF"]:
            g, n = media_geo_razao(resultados, alvo, VERSION, outro)
            txt = f"{g:.3f} (n={n})" if g is not None else "sem imagens comparáveis"
            print(f"  média geométrica bpp {VERSION} / {outro}: {txt}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default="", help="lista separada por vírgula; padrão: todas")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "results", f"lossy_{VERSION}.json"))
    args = ap.parse_args()
    imagens = load_images()
    if args.images:
        escolhidas = args.images.split(",")
        imagens = {k: imagens[k] for k in escolhidas}
    resultados = {}
    for nome, img in imagens.items():
        t0 = time.time()
        resultados[nome] = rodar_imagem(img)
        print(f"{nome}: {img.shape}, {len(resultados[nome])} pontos, {time.time() - t0:.1f} s", file=sys.stderr)
    imprimir(resultados)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(
            {"versao": VERSION, "alvos": TARGETS, "resultados": resultados, "resumo": resumir(resultados)},
            f,
            ensure_ascii=False,
            indent=1,
        )
    print(f"\nJSON: {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
