"""Testes do benchmark: port da VM, encoder e construção de Γ.

Execute:  python3 -m unittest discover -s bench -v
"""

import random
import unittest

import stb_codec
import stb_vm


def lib_from(genes):
    return stb_codec.Library(genes)


class RoundTripTests(unittest.TestCase):
    def roundtrip(self, data, genes, residue_mode=False):
        lib = lib_from(genes)
        prog, _, om = stb_codec.encode(data, lib, residue_mode=residue_mode)
        out = stb_vm.execute(prog, lib.payload, residue=om)
        self.assertEqual(out, data)
        return prog

    def test_empty_input(self):
        prog = self.roundtrip(b"", [])
        self.assertEqual(prog, stb_vm.STP_BYTES)

    def test_pure_literals_raw_mode(self):
        data = bytes(random.Random(0).randrange(256) for _ in range(500))
        self.roundtrip(data, [])

    def test_pure_literals_residue_mode(self):
        data = bytes(random.Random(1).randrange(256) for _ in range(500))
        self.roundtrip(data, [], residue_mode=True)

    def test_gene_matches_and_literals_mixed(self):
        gene = b"A" * 40 + b"-gene-payload-0123456789-tail"  # 64 bytes
        data = b"xyz" * 7 + gene + b"literal bytes here" + gene + gene
        genes = [gene]
        self.roundtrip(data, genes)
        self.roundtrip(data, genes, residue_mode=True)

    def test_repeated_gene_uses_rpt(self):
        gene = bytes(range(64))
        data = gene * 5
        lib = lib_from([gene])
        prog, stats, _ = stb_codec.encode(data, lib)
        self.assertIn(stb_vm.RPT, prog)
        self.assertEqual(stb_vm.execute(prog, lib.payload), data)
        self.assertEqual(stats["ref_bytes"], len(data))

    def test_short_gene_not_used_after_literal_in_raw_mode(self):
        # Gene de 16 bytes depois de literais: custa 17 bytes, economiza 16 -> não usar.
        gene = b"0123456789abcdef"
        data = b"QQQQ" + gene
        lib = lib_from([gene])
        _, stats, _ = stb_codec.encode(data, lib)
        self.assertEqual(stats["ref_bytes"], 0)

    def test_short_gene_used_after_literal_in_residue_mode(self):
        gene = b"0123456789abcdef"
        data = b"QQQQ" + gene
        lib = lib_from([gene])
        _, stats, om = stb_codec.encode(data, lib, residue_mode=True)
        self.assertEqual(stats["ref_bytes"], len(gene))
        self.assertEqual(om, b"QQQQ")


class VmPortTests(unittest.TestCase):
    def test_missing_stp_rejected(self):
        with self.assertRaises(stb_vm.VmError):
            stb_vm.validate_bytecode(stb_vm.enc_def("a", b"x"))

    def test_unbalanced_loops_rejected(self):
        with self.assertRaises(stb_vm.VmError) as cm:
            stb_vm.validate_bytecode(bytes([stb_vm.RPTEND, stb_vm.STP]))
        self.assertEqual(cm.exception.kind, "LoopMismatch")
        with self.assertRaises(stb_vm.VmError) as cm:
            stb_vm.validate_bytecode(bytes([stb_vm.RPT, 2, 0, 0, 0, stb_vm.STP]))
        self.assertEqual(cm.exception.kind, "LoopMismatch")

    def test_instruction_after_stp_rejected(self):
        with self.assertRaises(stb_vm.VmError):
            stb_vm.validate_bytecode(bytes([stb_vm.STP, stb_vm.STP]))

    def test_ale_seed_zero_rejected(self):
        bytecode = bytes([stb_vm.ALE] + [0] * 8 + [4, 0, 0, 0] + [stb_vm.STP])
        with self.assertRaises(stb_vm.VmError):
            stb_vm.execute(bytecode, {})

    def test_res_rejected_without_residue(self):
        prog = stb_vm.enc_res(3) + stb_vm.STP_BYTES
        with self.assertRaises(stb_vm.VmError):
            stb_vm.execute(prog, {})

    def test_res_reads_residue_in_order(self):
        prog = stb_vm.enc_res(2) + stb_vm.enc_res(3) + stb_vm.STP_BYTES
        self.assertEqual(stb_vm.execute(prog, {}, residue=b"abcdefgh"), b"abcde")

    def test_res_beyond_residue_fails(self):
        prog = stb_vm.enc_res(5) + stb_vm.STP_BYTES
        with self.assertRaises(stb_vm.VmError):
            stb_vm.execute(prog, {}, residue=b"ab")

    def test_missing_gene_is_strict_error(self):
        prog = stb_vm.enc_ref("nope") + stb_vm.STP_BYTES
        with self.assertRaises(stb_vm.VmError) as cm:
            stb_vm.execute(prog, {})
        self.assertEqual(cm.exception.kind, "GeneNotFound")

    def test_local_def_shadows_library(self):
        prog = stb_vm.enc_def("g", b"local") + stb_vm.enc_ref("g") + stb_vm.STP_BYTES
        self.assertEqual(stb_vm.execute(prog, {"g": b"library"}), b"local")

    def test_nested_loops_and_zero_count(self):
        body = stb_vm.enc_def("x", b"AB") + stb_vm.enc_rpt(2, stb_vm.enc_ref("x"))
        prog = body + stb_vm.enc_rpt(0, stb_vm.enc_ref("missing")) + stb_vm.STP_BYTES
        self.assertEqual(stb_vm.execute(prog, {}), b"ABAB")


class LibraryTests(unittest.TestCase):
    def test_budget_respected_and_deterministic(self):
        rng = random.Random(5)
        words = [bytes(rng.choice(b"abcdefgh ") for _ in range(20)) for _ in range(30)]
        files = [b" ".join(rng.choice(words) for _ in range(400)) for _ in range(3)]
        budget = 4096
        g1 = stb_codec.build_library(files, budget)
        g2 = stb_codec.build_library(files, budget)
        self.assertEqual(g1, g2)
        lib = stb_codec.Library(g1)
        self.assertLessEqual(lib.serialized_size(), budget + 64)  # custo estimado por id
        self.assertGreater(len(g1), 0)

    def test_library_program_roundtrip(self):
        genes = [bytes(range(64)), b"hello world, this is a 32-byte gene!"]
        lib = stb_codec.Library(genes)
        prog = lib.as_program() + stb_vm.STP_BYTES
        self.assertEqual(stb_vm.execute(prog, {}), b"")  # DEFs definem, não emitem saída
        self.assertEqual(lib.serialized_size(), len(lib.as_program()))

    def test_gene_ids_are_unique_and_avoid_local_marker(self):
        ids = [stb_codec.gene_id(i) for i in range(5000)]
        self.assertEqual(len(set(ids)), 5000)
        self.assertNotIn(stb_codec.LOCAL_ID, "".join(ids))


class CopyTests(unittest.TestCase):
    """Extensão COPY (benchmark): cópia intra-arquivo, ativa só com resíduo."""

    def test_simple_copy(self):
        out = stb_vm.execute(stb_vm.enc_res(6) + stb_vm.enc_copy(6, 4) + stb_vm.STP_BYTES, {},
                             residue=b"abcdef")
        self.assertEqual(out, b"abcdefabcd")

    def test_overlapping_copy_repeats_pattern(self):
        # dist 1, len 5: "a" -> "aaaaaa"; dist 2, len 5 sobre "ab" -> "ababa"
        out = stb_vm.execute(stb_vm.enc_res(1) + stb_vm.enc_copy(1, 5) + stb_vm.STP_BYTES, {},
                             residue=b"a")
        self.assertEqual(out, b"aaaaaa")
        out = stb_vm.execute(stb_vm.enc_res(2) + stb_vm.enc_copy(2, 5) + stb_vm.STP_BYTES, {},
                             residue=b"ab")
        self.assertEqual(out, b"abababa")

    def test_distance_zero_rejected(self):
        prog = stb_vm.enc_res(1) + stb_vm.enc_copy(0, 1) + stb_vm.STP_BYTES
        with self.assertRaises(stb_vm.VmError):
            stb_vm.execute(prog, {}, residue=b"x")

    def test_distance_past_output_rejected(self):
        prog = stb_vm.enc_res(3) + stb_vm.enc_copy(4, 1) + stb_vm.STP_BYTES
        with self.assertRaises(stb_vm.VmError):
            stb_vm.execute(prog, {}, residue=b"abc")

    def test_copy_at_start_rejected(self):
        prog = stb_vm.enc_copy(1, 1) + stb_vm.STP_BYTES
        with self.assertRaises(stb_vm.VmError):
            stb_vm.execute(prog, {}, residue=b"")

    def test_copy_rejected_without_residue(self):
        prog = stb_vm.enc_res(1) + stb_vm.enc_copy(1, 1) + stb_vm.STP_BYTES
        with self.assertRaises(stb_vm.VmError):
            stb_vm.validate_bytecode(prog, allow_residue=False)
        with self.assertRaises(stb_vm.VmError):
            stb_vm.execute(prog, {})

    def test_copy_counted_inside_rpt(self):
        # RPT 3 { COPY dist 1 len 2 } sobre um "z": "z" + 3 * "zz" = 7 bytes de 'z'
        body = stb_vm.enc_copy(1, 2)
        prog = stb_vm.enc_res(1) + stb_vm.enc_rpt(3, body) + stb_vm.STP_BYTES
        self.assertEqual(stb_vm.execute(prog, {}, residue=b"z"), b"z" * 7)


class StbV2Tests(unittest.TestCase):
    def roundtrip(self, data, genes):
        import stb_v2
        lib = lib_from(genes)
        toks, R = stb_v2.tokenize(data, lib)
        blob = stb_v2.pack_streams(stb_v2.streams_from_tokens(toks, R))
        s2 = stb_v2.unpack_streams(blob)
        self.assertEqual(s2, stb_v2.streams_from_tokens(toks, R))
        prog = stb_v2.bytecode_from_tokens(stb_v2.tokens_from_streams(s2), lib)
        out = stb_vm.execute(prog, lib.payload, residue=s2["R"])
        self.assertEqual(out, data)
        return toks, blob

    def test_empty(self):
        self.roundtrip(b"", [])

    def test_intra_file_repeat_becomes_copy(self):
        import stb_v2
        data = b"0123456789-" * 40
        toks, _ = self.roundtrip(data, [])
        self.assertTrue(any(t[0] == stb_v2.T_COPY for t in toks))

    def test_random_bytes_roundtrip(self):
        data = bytes(random.Random(3).randrange(256) for _ in range(3000))
        self.roundtrip(data, [])

    def test_gene_and_copy_mixed(self):
        genes = [b"GENE-SEQUENCE-ABCDEFGH", b"another gene body"]
        data = b"xx" + genes[0] + b"-yy" + genes[0] + b"-yy" + genes[1] * 4 + b"zzz" * 9
        self.roundtrip(data, genes)

    def test_tokens_are_valid_stream_types(self):
        import stb_v2
        toks, _ = self.roundtrip(b"abcabcabcabcabc" * 5, [])
        self.assertEqual(toks[-1], (stb_v2.T_STP,))

    def test_bad_stream_method_rejected(self):
        import stb_v2
        with self.assertRaises(ValueError):
            stb_v2.unpack_stream(bytes([9, 0]), 0)


if __name__ == "__main__":
    unittest.main()
