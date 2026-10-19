"""Port Python da VM do STB-Core (src/lib.rs), restrito ao necessário para o benchmark.

Por que existe: o ambiente de desenvolvimento usado para este benchmark não tem
toolchain Rust. Este módulo reproduz a semântica da VM Rust:

* formato binário (DEF/REF/RPT/RPTEND/ALE/ERR/STP, little-endian);
* validação estática antes da execução (opcodes, limites, RPT/RPTEND balanceados,
  STP como última instrução, semente ALE não nula);
* limites MAX_OUTPUT_SIZE, MAX_LOOP_COUNT (por RPT) e MAX_VM_STEPS (global);
* modo estrito apenas (o encoder do benchmark nunca depende de modo permissivo).

Deve ser conferido contra `cargo test` sempre que houver toolchain Rust disponível.
"""

import struct

DEF, REF, RPT, RPTEND, ALE, ERR, STP = 0x01, 0x02, 0x03, 0x04, 0x07, 0x08, 0xFF

# EXTENSÃO DO BENCHMARK (não existe em src/lib.rs): RES n copia os próximos n bytes de
# um resíduo Ω transmitido à parte e classicamente comprimido. Só é aceito quando um
# resíduo é fornecido a execute(); com residue=None, a validação se comporta como o Rust.
RES = 0x09
RES_OVERHEAD = 5  # 1 (opcode) + 4 (u32 length)
# EXTENSÃO DO BENCHMARK (v2): COPY dist len copia `len` bytes que começam `dist` bytes atrás
# na saída já produzida (cópia intra-arquivo, como LZ77). Ativa junto com RES (residue != None).
COPY = 0x0A

MAX_OUTPUT_SIZE = 64 * 1024 * 1024
MAX_LOOP_COUNT = 1_000_000
MAX_VM_STEPS = 50_000_000


class VmError(Exception):
    """kind em: OutOfBounds, InvalidOpcode, GeneNotFound, LoopMismatch, Custom."""

    def __init__(self, kind, msg=""):
        super().__init__(f"{kind}: {msg}" if msg else kind)
        self.kind = kind
        self.msg = msg


# ---------------------------------------------------------------- leitura segura

def _u16(b, pc):
    if pc + 1 >= len(b):
        raise VmError("OutOfBounds")
    return struct.unpack_from("<H", b, pc)[0], pc + 2


def _u32(b, pc):
    if pc + 3 >= len(b):
        raise VmError("OutOfBounds")
    return struct.unpack_from("<I", b, pc)[0], pc + 4


def _u64(b, pc):
    if pc + 7 >= len(b):
        raise VmError("OutOfBounds")
    return struct.unpack_from("<Q", b, pc)[0], pc + 8


def _str(b, pc):
    n, pc = _u16(b, pc)
    if pc + n > len(b):
        raise VmError("OutOfBounds")
    return b[pc:pc + n].decode("utf-8", "replace"), pc + n


def _blob(b, pc):
    n, pc = _u32(b, pc)
    if pc + n > len(b):
        raise VmError("OutOfBounds")
    return b[pc:pc + n], pc + n


# ---------------------------------------------------------------- codificação

def enc_def(gene_id: str, data: bytes) -> bytes:
    idb = gene_id.encode("utf-8")
    return bytes([DEF]) + struct.pack("<H", len(idb)) + idb + struct.pack("<I", len(data)) + data


def enc_ref(gene_id: str) -> bytes:
    idb = gene_id.encode("utf-8")
    return bytes([REF]) + struct.pack("<H", len(idb)) + idb


def enc_copy(dist: int, length: int) -> bytes:
    return bytes([COPY]) + struct.pack("<II", dist, length)


def enc_res(n: int) -> bytes:
    return bytes([RES]) + struct.pack("<I", n)


def enc_rpt(count: int, body: bytes) -> bytes:
    return bytes([RPT]) + struct.pack("<I", count) + body + bytes([RPTEND])


STP_BYTES = bytes([STP])


# ---------------------------------------------------------------- validação

def validate_bytecode(bytes_: bytes, allow_residue: bool = False) -> None:
    """Equivalente a validate_bytecode() em src/lib.rs. Levanta VmError."""
    pc = 0
    depth = 0
    halted = False
    while pc < len(bytes_):
        if halted:
            raise VmError("Custom", "instruções após STP")
        op = bytes_[pc]
        pc += 1
        if op == RES and allow_residue:
            _, pc = _u32(bytes_, pc)
        elif op == COPY and allow_residue:
            dist, pc = _u32(bytes_, pc)
            length, pc = _u32(bytes_, pc)
            if dist == 0:
                raise VmError("Custom", "COPY distance 0")
            if length > MAX_OUTPUT_SIZE:
                raise VmError("Custom", "COPY length exceeds output limit")
        elif op == DEF:
            _, pc = _str(bytes_, pc)
            _, pc = _blob(bytes_, pc)
        elif op == REF:
            _, pc = _str(bytes_, pc)
        elif op == RPT:
            count, pc = _u32(bytes_, pc)
            if count > MAX_LOOP_COUNT:
                raise VmError("Custom", f"loop count {count} > {MAX_LOOP_COUNT}")
            depth += 1
        elif op == RPTEND:
            if depth == 0:
                raise VmError("LoopMismatch")
            depth -= 1
        elif op == ALE:
            seed, pc = _u64(bytes_, pc)
            length, pc = _u32(bytes_, pc)
            if seed == 0:
                raise VmError("Custom", "ALE seed 0")
            if length > MAX_OUTPUT_SIZE:
                raise VmError("Custom", "ALE length exceeds output limit")
        elif op == ERR:
            _, pc = _str(bytes_, pc)
        elif op == STP:
            if depth != 0:
                raise VmError("LoopMismatch")
            halted = True
        else:
            raise VmError("InvalidOpcode", str(op))
    if not halted:
        raise VmError("Custom", "programa não termina com STP")


# ---------------------------------------------------------------- execução

def execute(bytes_: bytes, library: dict, residue: bytes = None) -> bytes:
    """Executa o bytecode contra a biblioteca {id: payload}. Modo estrito.

    residue: resíduo Ω já descomprimido (habilita a extensão RES); None = formato Rust.
    """
    validate_bytecode(bytes_, allow_residue=residue is not None)
    pc = 0
    rp = 0  # posição de leitura no resíduo
    out = bytearray()
    local = {}
    steps = 0
    stack = []  # [pc_inicio, restantes]
    while pc < len(bytes_):
        op = bytes_[pc]
        pc += 1
        steps += 1
        if steps > MAX_VM_STEPS:
            raise VmError("Custom", f"limite de passos {MAX_VM_STEPS} excedido")
        if op == RES:
            n, pc = _u32(bytes_, pc)
            if rp + n > len(residue):
                raise VmError("OutOfBounds", "resíduo insuficiente")
            out += residue[rp:rp + n]
            rp += n
        elif op == COPY:
            dist, pc = _u32(bytes_, pc)
            length, pc = _u32(bytes_, pc)
            if dist == 0 or dist > len(out):
                raise VmError("Custom", f"COPY distance {dist} fora da saída ({len(out)} bytes)")
            if len(out) + length > MAX_OUTPUT_SIZE:
                raise VmError("Custom", "Output size limit exceeded")
            start = len(out) - dist
            if dist >= length:
                out += out[start:start + length]
            else:  # sobreposição: repete o padrão de `dist` bytes
                out += (out[start:] * (length // dist + 1))[:length]
        elif op == DEF:
            gid, pc = _str(bytes_, pc)
            data, pc = _blob(bytes_, pc)
            local[gid] = data
        elif op == REF:
            gid, pc = _str(bytes_, pc)
            if gid in local:
                data = local[gid]
            elif gid in library:
                data = library[gid]
            else:
                raise VmError("GeneNotFound", gid)
            if len(out) + len(data) > MAX_OUTPUT_SIZE:
                raise VmError("Custom", "Output size limit exceeded")
            out += data
        elif op == RPT:
            count, pc = _u32(bytes_, pc)
            if count == 0:
                # Pula o corpo até o RPTEND correspondente (validado antes).
                depth = 1
                while depth > 0:
                    if bytes_[pc] == RPT:
                        pc += 1
                        _, pc = _u32(bytes_, pc)
                        depth += 1
                    elif bytes_[pc] == RPTEND:
                        pc += 1
                        depth -= 1
                    else:
                        o = bytes_[pc]
                        pc += 1
                        if o == DEF:
                            _, pc = _str(bytes_, pc)
                            _, pc = _blob(bytes_, pc)
                        elif o in (REF, ERR):
                            _, pc = _str(bytes_, pc)
                        elif o == ALE:
                            _, pc = _u64(bytes_, pc)
                            _, pc = _u32(bytes_, pc)
                        elif o == RES:
                            _, pc = _u32(bytes_, pc)
                        elif o == COPY:
                            _, pc = _u32(bytes_, pc)
                            _, pc = _u32(bytes_, pc)
            else:
                stack.append([pc, count - 1])
        elif op == RPTEND:
            top = stack[-1]
            if top[1] > 0:
                top[1] -= 1
                pc = top[0]
            else:
                stack.pop()
        elif op == ALE:
            seed, pc = _u64(bytes_, pc)
            length, pc = _u32(bytes_, pc)
            x = seed
            mask = (1 << 64) - 1
            buf = bytearray(length)
            for k in range(length):
                x ^= (x << 13) & mask
                x ^= x >> 7
                x ^= (x << 17) & mask
                buf[k] = x & 0xFF
            if len(out) + length > MAX_OUTPUT_SIZE:
                raise VmError("Custom", "Output size limit exceeded")
            out += buf
        elif op == ERR:
            msg, pc = _str(bytes_, pc)
            raise VmError("Custom", msg)
        elif op == STP:
            break
    return bytes(out)
