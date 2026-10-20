"""Codificação adaptativa dos tokens do STB-v2 e dos literais, com um único fluxo aritmético.

Formato (sem cabeçalho; o fim é marcado pelo token STP):
  para cada token, na ordem do programa:
    tipo      TreeModel(3), contexto = tipo anterior
    LIT n     IntModel(n-1); depois n bytes de literal, cada um TreeModel(8) com contexto = byte anterior
    REF g     TreeModel(bits de g), g é o índice do gene (só se houver Γ)
    RPT c g   IntModel(c-RPT_MIN) e TreeModel(bits de g)
    COPY d l  IntModel(d-1) e IntModel(l-MIN_COPY)
    STP       nada

O decodificador precisa apenas do número de genes de Γ (`n_genes`), que o receptor já tem
pela biblioteca. Por isso não há cabeçalho.
"""

import rc
import stb_v2

TYPE_BITS = 3


def _gene_bits(n_genes: int) -> int:
    return max(1, (n_genes - 1).bit_length()) if n_genes else 0


class _Models:
    def __init__(self, n_genes: int):
        self.type = [rc.TreeModel(TYPE_BITS) for _ in range(5)]
        self.lit_len = rc.IntModel()
        self.lit_byte = [rc.TreeModel(8) for _ in range(256)]
        gb = _gene_bits(n_genes)
        self.gene = rc.TreeModel(gb) if gb else None
        self.rpt_cnt = rc.IntModel()
        self.copy_dist = rc.IntModel()
        self.copy_len = rc.IntModel()


def encode_tokens(tokens, R: bytes, n_genes: int) -> bytes:
    enc = rc.Encoder()
    m = _Models(n_genes)
    prev_type = 0
    prev_byte = 0
    ri = 0
    for t in tokens:
        kind = t[0]
        m.type[prev_type].encode(enc, kind)
        prev_type = kind
        if kind == stb_v2.T_LIT:
            n = t[1]
            m.lit_len.encode(enc, n - 1)
            for b in R[ri:ri + n]:
                m.lit_byte[prev_byte].encode(enc, b)
                prev_byte = b
            ri += n
        elif kind == stb_v2.T_REF:
            m.gene.encode(enc, t[1])
        elif kind == stb_v2.T_RPT:
            m.rpt_cnt.encode(enc, t[1] - stb_v2.RPT_MIN)
            m.gene.encode(enc, t[2])
        elif kind == stb_v2.T_COPY:
            m.copy_dist.encode(enc, t[1] - 1)
            m.copy_len.encode(enc, t[2] - stb_v2.MIN_COPY)
        elif kind != stb_v2.T_STP:
            raise ValueError(f"tipo de token inválido: {kind}")
    if ri != len(R):
        raise ValueError("bytes de literal não consumidos pelos tokens")
    return enc.finish()


def decode_tokens(buf: bytes, n_genes: int):
    """Retorna (tokens, R), o mesmo par que `stb_v2.tokenize` produz."""
    dec = rc.Decoder(buf)
    m = _Models(n_genes)
    tokens = []
    R = bytearray()
    prev_type = 0
    prev_byte = 0
    while True:
        kind = m.type[prev_type].decode(dec)
        prev_type = kind
        if kind == stb_v2.T_LIT:
            n = m.lit_len.decode(dec) + 1
            tokens.append((stb_v2.T_LIT, n))
            for _ in range(n):
                b = m.lit_byte[prev_byte].decode(dec)
                R.append(b)
                prev_byte = b
        elif kind == stb_v2.T_REF:
            if m.gene is None:
                raise ValueError("REF sem biblioteca")
            tokens.append((stb_v2.T_REF, m.gene.decode(dec)))
        elif kind == stb_v2.T_RPT:
            if m.gene is None:
                raise ValueError("RPT sem biblioteca")
            cnt = m.rpt_cnt.decode(dec) + stb_v2.RPT_MIN
            tokens.append((stb_v2.T_RPT, cnt, m.gene.decode(dec)))
        elif kind == stb_v2.T_COPY:
            dist = m.copy_dist.decode(dec) + 1
            length = m.copy_len.decode(dec) + stb_v2.MIN_COPY
            tokens.append((stb_v2.T_COPY, dist, length))
        elif kind == stb_v2.T_STP:
            tokens.append((stb_v2.T_STP,))
            return tokens, bytes(R)
        else:
            raise ValueError(f"tipo de token inválido na decodificação: {kind}")
