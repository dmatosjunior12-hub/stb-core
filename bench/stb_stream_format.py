"""Formato de fluxos v1 (fluxos-v1) para tokens G0: genes sem COPY (REF/RPT/LIT/STP).

Especificação completa: bench/STREAM_FORMAT.md. Resumo:

  arquivo  := versão(1 B = 0x01) fluxo_T fluxo_LEN fluxo_CNT fluxo_GID fluxo_R
  fluxo    := método(1 B) n(varint) tamanho_do_corpo(varint) corpo
  método   := 0 cru | 1 LZMA2 raw 9e | 2 zstd-19 | 3 codificador adaptativo (rc, só T/LEN/CNT/GID)

  T    : um byte por token (0 LIT, 1 REF, 2 RPT, 4 STP); o último token é sempre STP
  LEN  : comprimento de cada LIT (>= 1)            | corpo: varints (cru/LZMA/zstd) ou rc
  CNT  : contagem de cada RPT (>= RPT_MIN)          | idem
  GID  : id de gene de cada REF e RPT, nessa ordem  | idem; rc usa bit-tree de largura fixa
  R    : bytes de literal, na ordem dos LIT          | corpo: bytes (cru/LZMA/zstd)

O decodificador precisa do número de genes de Γ (`n_genes`) para a largura do bit-tree; o receptor
já tem Γ. Não há cabeçalho além da versão: contagens vêm de T, e o tamanho de R, da soma de LEN.
"""

import lzma

import rc
import stb_v2
import zstandard

FORMAT_VERSION = 1
M_RAW, M_LZMA, M_ZSTD, M_RC = 0, 1, 2, 3
MAX_ITEMS = 1 << 26  # teto de sanidade contra contagens corrompidas
TOKEN_KINDS = (stb_v2.T_LIT, stb_v2.T_REF, stb_v2.T_RPT, stb_v2.T_STP)

_ZC = zstandard.ZstdCompressor(level=19)
_ZD = zstandard.ZstdDecompressor()


# ----------------------------------------------------------------- métodos de corpo

def _gene_bits(n_genes: int) -> int:
    return max(1, (n_genes - 1).bit_length()) if n_genes else 0


def _rc_encode(kind: str, values, n_genes: int) -> bytes:
    enc = rc.Encoder()
    if kind == "T":
        models = [rc.TreeModel(3) for _ in range(len(TOKEN_KINDS) + 1)]
        prev = 0
        for v in values:
            models[prev].encode(enc, v)
            prev = v
    elif kind == "LEN":
        m = rc.IntModel()
        for v in values:
            m.encode(enc, v - 1)
    elif kind == "CNT":
        m = rc.IntModel()
        for v in values:
            m.encode(enc, v - stb_v2.RPT_MIN)
    elif kind == "GID":
        m = rc.TreeModel(_gene_bits(n_genes))
        for v in values:
            m.encode(enc, v)
    else:
        raise ValueError(kind)
    return enc.finish()


def _rc_decode(kind: str, body: bytes, n: int, n_genes: int) -> list:
    dec = rc.Decoder(body)
    out = []
    if kind == "T":
        models = [rc.TreeModel(3) for _ in range(len(TOKEN_KINDS) + 1)]
        prev = 0
        for _ in range(n):
            v = models[prev].decode(dec)
            out.append(v)
            prev = v
    elif kind == "LEN":
        m = rc.IntModel()
        out = [m.decode(dec) + 1 for _ in range(n)]
    elif kind == "CNT":
        m = rc.IntModel()
        out = [m.decode(dec) + stb_v2.RPT_MIN for _ in range(n)]
    elif kind == "GID":
        m = rc.TreeModel(_gene_bits(n_genes))
        out = [m.decode(dec) for _ in range(n)]
    return out


def _varints(values) -> bytes:
    buf = bytearray()
    for v in values:
        stb_v2.put_varint(buf, v)
    return bytes(buf)


def _parse_varints(raw: bytes, n: int) -> list:
    rd = stb_v2.VarintReader(raw)
    try:
        out = [rd.read() for _ in range(n)]
    except IndexError as exc:
        raise ValueError("fluxo de varints truncado") from exc
    if rd.pos != len(raw):
        raise ValueError("bytes sobrando no fluxo de varints")
    return out


def _pack_body(raw: bytes):
    """Melhor de cru, LZMA2 raw 9e e zstd-19 para um corpo; retorna (método, corpo)."""
    best_m, best = M_RAW, raw
    if raw:
        lz = lzma.compress(raw, format=lzma.FORMAT_RAW, filters=stb_v2.LZMA_FILTERS)
        if len(lz) < len(best):
            best_m, best = M_LZMA, lz
        zs = _ZC.compress(raw)
        if len(zs) < len(best):
            best_m, best = M_ZSTD, zs
    return best_m, best


def _unpack_body(method: int, body: bytes) -> bytes:
    """Descomprime um corpo; qualquer falha de LZMA/zstd vira ValueError."""
    if method == M_RAW:
        return body
    try:
        if method == M_LZMA:
            return lzma.decompress(body, format=lzma.FORMAT_RAW, filters=stb_v2.LZMA_FILTERS)
        if method == M_ZSTD:
            return _ZD.decompress(body)
    except (lzma.LZMAError, zstandard.ZstdError) as exc:
        raise ValueError(f"corpo corrompido (método {method}): {exc}") from exc
    raise ValueError(f"método de corpo inesperado: {method}")


# ----------------------------------------------------------------- registro de fluxo

def _encode_record(kind: str, values, n_genes: int) -> bytes:
    """Escolhe o menor entre os métodos permitidos para o fluxo `kind`."""
    if kind == "R":  # valores são bytes
        method, body = _pack_body(bytes(values))
    else:
        raw = bytes(values) if kind == "T" else _varints(values)
        method, body = _pack_body(raw)
        if kind != "R" and values:
            rc_body = _rc_encode(kind, values, n_genes)
            if len(rc_body) < len(body):
                method, body = M_RC, rc_body
    out = bytearray([method])
    stb_v2.put_varint(out, len(values))
    stb_v2.put_varint(out, len(body))
    out += body
    return bytes(out)


class _Reader:
    def __init__(self, buf: bytes):
        self.buf = buf
        self.pos = 0

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.buf):
            raise ValueError("arquivo truncado")
        b = self.buf[self.pos:self.pos + n]
        self.pos += n
        return b

    def byte(self) -> int:
        return self.take(1)[0]

    def varint(self) -> int:
        rd = stb_v2.VarintReader(self.buf)
        rd.pos = self.pos
        try:
            v = rd.read()
        except IndexError as exc:
            raise ValueError("arquivo truncado dentro de um varint") from exc
        self.pos = rd.pos
        return v


def _decode_record(rd: _Reader, kind: str, n_genes: int) -> list:
    method = rd.byte()
    n = rd.varint()
    size = rd.varint()
    if n > MAX_ITEMS:
        raise ValueError(f"contagem excessiva no fluxo {kind}: {n}")
    body = rd.take(size)
    if method == M_RC:
        if kind == "R":
            raise ValueError("fluxo R não aceita codificação adaptativa")
        return _rc_decode(kind, body, n, n_genes)
    raw = _unpack_body(method, body)
    if kind == "R":
        if len(raw) != n:
            raise ValueError("tamanho de R não confere com n")
        return list(raw)
    if kind == "T":
        if len(raw) != n:
            raise ValueError("tamanho de T não confere com n")
        return list(raw)
    return _parse_varints(raw, n)


# ----------------------------------------------------------------- arquivo

def encode(tokens, R: bytes, n_genes: int) -> bytes:
    """Serializa tokens G0 (LIT/REF/RPT/STP) e o fluxo R no formato fluxos-v1."""
    kinds, lens, cnts, gids = [], [], [], []
    lit_total = 0
    for t in tokens:
        k = t[0]
        if k not in TOKEN_KINDS:
            raise ValueError(f"token sem suporte no formato fluxos-v1 (G0 apenas): {k}")
        kinds.append(k)
        if k == stb_v2.T_LIT:
            lens.append(t[1])
            lit_total += t[1]
        elif k == stb_v2.T_REF:
            gids.append(_check_gid(t[1], n_genes))
        elif k == stb_v2.T_RPT:
            if t[1] < stb_v2.RPT_MIN:
                raise ValueError("RPT abaixo de RPT_MIN")
            cnts.append(t[1])
            gids.append(_check_gid(t[2], n_genes))
    if not kinds or kinds[-1] != stb_v2.T_STP or kinds.count(stb_v2.T_STP) != 1:
        raise ValueError("a lista de tokens deve terminar com um único STP")
    if lit_total != len(R):
        raise ValueError("soma dos LIT não confere com len(R)")
    out = bytearray([FORMAT_VERSION])
    out += _encode_record("T", kinds, n_genes)
    out += _encode_record("LEN", lens, n_genes)
    out += _encode_record("CNT", cnts, n_genes)
    out += _encode_record("GID", gids, n_genes)
    out += _encode_record("R", R, n_genes)
    return bytes(out)


def _check_gid(g: int, n_genes: int) -> int:
    if not (0 <= g < n_genes):
        raise ValueError(f"id de gene fora de Γ: {g}")
    return g


def decode(buf: bytes, n_genes: int):
    """Inverso de encode: retorna (tokens, R). Qualquer inconsistência levanta ValueError."""
    rd = _Reader(buf)
    if rd.byte() != FORMAT_VERSION:
        raise ValueError("versão de formato desconhecida")
    kinds = _decode_record(rd, "T", n_genes)
    lens = _decode_record(rd, "LEN", n_genes)
    cnts = _decode_record(rd, "CNT", n_genes)
    gids = _decode_record(rd, "GID", n_genes)
    R = bytes(_decode_record(rd, "R", n_genes))
    if rd.pos != len(buf):
        raise ValueError("bytes sobrando após o fluxo R")
    if not kinds or kinds[-1] != stb_v2.T_STP or kinds.count(stb_v2.T_STP) != 1:
        raise ValueError("T não termina com um único STP")
    tokens = []
    li = ci = gi = 0
    for k in kinds:
        if k == stb_v2.T_LIT:
            tokens.append((stb_v2.T_LIT, _next(lens, li, "LEN"))); li += 1
        elif k == stb_v2.T_REF:
            tokens.append((stb_v2.T_REF, _check_gid(_next(gids, gi, "GID"), n_genes))); gi += 1
        elif k == stb_v2.T_RPT:
            cnt = _next(cnts, ci, "CNT"); ci += 1
            tokens.append((stb_v2.T_RPT, cnt, _check_gid(_next(gids, gi, "GID"), n_genes))); gi += 1
        elif k == stb_v2.T_STP:
            tokens.append((stb_v2.T_STP,))
        else:
            raise ValueError(f"tipo de token inválido em T: {k}")
    if (li, ci, gi) != (len(lens), len(cnts), len(gids)):
        raise ValueError("contagens de LEN/CNT/GID sobrando")
    if sum(t[1] for t in tokens if t[0] == stb_v2.T_LIT) != len(R):
        raise ValueError("soma dos LIT não confere com len(R)")
    return tokens, R


def _next(seq: list, i: int, name: str):
    if i >= len(seq):
        raise ValueError(f"fluxo {name} com menos itens que T exige")
    return seq[i]
