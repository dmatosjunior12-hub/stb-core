"""Testes do benchmark: port da VM, encoder e construção de Γ.

Execute:  python3 -m unittest discover -s bench -v
"""

import random
import unittest

import numpy as np

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


class ParserTests(unittest.TestCase):
    """Parsers guloso, lazy e ótimo (stb_v2): round-trip, COPY só quando permitido, e custo do DP."""

    def sample(self):
        rnd = random.Random(7)
        genes = [b"GENE-SEQUENCE-ABCDEFGH", b"another gene body here!"]
        parts = [genes[0], b"-x-", genes[1], b"%06d" % rnd.randrange(10**6), genes[0] * 2]
        parts += [bytes(rnd.randrange(256) for _ in range(40)), b"abcabcabc" * 9, b"\x00" * 50]
        return b"".join(parts), genes

    def check_roundtrip(self, data, genes, parser, allow_copy):
        import stb_v2
        lib = lib_from(genes)
        toks, R = stb_v2.tokenize(data, lib, parser, allow_copy)
        s = stb_v2.streams_from_tokens(toks, R)
        s2 = stb_v2.unpack_streams(stb_v2.pack_streams(s))
        prog = stb_v2.bytecode_from_tokens(stb_v2.tokens_from_streams(s2), lib)
        self.assertEqual(stb_vm.execute(prog, lib.payload, residue=s2["R"]), data)
        return toks

    def test_all_parsers_roundtrip_with_and_without_copy(self):
        import stb_v2
        data, genes = self.sample()
        for parser in stb_v2.PARSERS:
            for allow_copy in (True, False):
                with self.subTest(parser=parser, allow_copy=allow_copy):
                    toks = self.check_roundtrip(data, genes, parser, allow_copy)
                    if not allow_copy:
                        self.assertFalse(any(t[0] == stb_v2.T_COPY for t in toks))

    def test_copy_used_for_intra_file_repeat(self):
        import stb_v2
        data = b"0123456789-" * 40
        for parser in stb_v2.PARSERS:
            toks = self.check_roundtrip(data, [], parser, True)
            self.assertTrue(any(t[0] == stb_v2.T_COPY for t in toks), parser)

    def test_optimal_model_cost_not_above_greedy(self):
        import stb_v2
        data, genes = self.sample()
        lib = lib_from(genes)

        def model_bits(events):
            total = 0.0
            for e in events:
                if e[0] == "L":
                    total += stb_v2.LIT_BITS * e[2]
                elif e[0] == "G":
                    total += stb_v2.GENE_BITS
                else:
                    total += stb_v2._copy_bits(e[1], e[2])
            return total

        for allow_copy in (True, False):
            g = model_bits(stb_v2.parse(data, lib, "greedy", allow_copy))
            o = model_bits(stb_v2.parse(data, lib, "optimal", allow_copy))
            self.assertLessEqual(o, g + 1e-9)

    def test_events_cover_input_exactly(self):
        import stb_v2
        data, genes = self.sample()
        lib = lib_from(genes)
        for parser in stb_v2.PARSERS:
            pos = 0
            for e in stb_v2.parse(data, lib, parser, True):
                if e[0] == "L":
                    self.assertEqual(e[1], pos)
                    pos += 1
                elif e[0] == "G":
                    self.assertEqual(data[pos:pos + e[2]], genes[e[1]])
                    pos += e[2]
                else:
                    self.assertGreaterEqual(e[1], 1)
                    self.assertLessEqual(e[1], pos)
                    pos += e[2]
            self.assertEqual(pos, len(data), parser)


class RangeCoderTests(unittest.TestCase):
    """Codificador aritmético adaptativo (rc.py) e codificação de tokens (token_coder.py)."""

    def test_bits_roundtrip_and_skewed_source_compresses(self):
        import rc
        rnd = random.Random(1)
        bits = [int(rnd.random() < 0.05) for _ in range(5000)]
        slot = [rc.PROB_INIT, 0]
        enc = rc.Encoder()
        for b in bits:
            enc.bit(slot, b)
        buf = enc.finish()
        slot = [rc.PROB_INIT, 0]
        dec = rc.Decoder(buf)
        self.assertEqual([dec.bit(slot) for _ in bits], bits)
        self.assertLess(len(buf), len(bits) // 8 // 2)  # fonte com p=0.05 cabe em bem menos que 1 bit/bit

    def test_int_and_tree_models_roundtrip(self):
        import rc
        values = [0, 1, 2, 3, 7, 8, 1000, 65535, 10**6, 2**31 - 1]
        ints = rc.IntModel()
        tree = rc.TreeModel(12)
        enc = rc.Encoder()
        for v in values:
            ints.encode(enc, v)
            tree.encode(enc, v % 4096)
        buf = enc.finish()
        ints, tree, dec = rc.IntModel(), rc.TreeModel(12), rc.Decoder(buf)
        out = []
        for _ in values:
            out.append(ints.decode(dec))
            out.append(tree.decode(dec))
        self.assertEqual(out[0::2], values)
        self.assertEqual(out[1::2], [v % 4096 for v in values])

    def test_int_model_rejects_negative(self):
        import rc
        with self.assertRaises(ValueError):
            rc.IntModel().encode(rc.Encoder(), -1)

    def test_truncated_stream_raises(self):
        import rc
        import token_coder
        import stb_v2
        buf = token_coder.encode_tokens([(stb_v2.T_LIT, 5), (stb_v2.T_STP,)], b"hello", 0)
        with self.assertRaises(ValueError):
            token_coder.decode_tokens(buf[:-3], 0)
        with self.assertRaises(ValueError):
            rc.Decoder(b"").bit([rc.PROB_INIT, 0])

    def test_token_roundtrip_with_genes_copies_and_rpt(self):
        import token_coder
        import stb_v2
        genes = [b"GENE-SEQUENCE-ABCDEFGH", b"another gene body here!", b"x" * 40]
        lib = lib_from(genes)
        data = (genes[0] + b"-" + genes[1] + genes[1] + genes[1] + b"0123456789" * 9
                + bytes(range(60)) + genes[2])
        for parser in stb_v2.PARSERS:
            for allow_copy in (True, False):
                with self.subTest(parser=parser, allow_copy=allow_copy):
                    toks, R = stb_v2.tokenize(data, lib, parser, allow_copy)
                    blob = token_coder.encode_tokens(toks, R, len(genes))
                    self.assertEqual(token_coder.decode_tokens(blob, len(genes)), (toks, R))
                    prog = stb_v2.bytecode_from_tokens(toks, lib)
                    self.assertEqual(stb_vm.execute(prog, lib.payload, residue=R), data)

    def test_no_library_roundtrip(self):
        import token_coder
        import stb_v2
        data = b"abcabcabc" * 30 + bytes(range(256))
        empty = lib_from([])
        toks, R = stb_v2.tokenize(data, empty, "greedy", True)
        blob = token_coder.encode_tokens(toks, R, 0)
        self.assertEqual(token_coder.decode_tokens(blob, 0), (toks, R))

    def test_unconsumed_literals_rejected(self):
        import token_coder
        import stb_v2
        with self.assertRaises(ValueError):
            token_coder.encode_tokens([(stb_v2.T_LIT, 2), (stb_v2.T_STP,)], b"abc", 0)


class GammaCopyTests(unittest.TestCase):
    """Janela de Γ (exp_gamma_dict.py) e COPY restrito a Γ (exp_gamma_copy.py), v1 a v3."""

    def test_restricted_copies_source_inside_gamma(self):
        import exp_gamma_copy as ec
        G = b"the quick brown fox jumps over the lazy dog " * 4
        idx = ec.GammaIndex(G)
        data = b"quick brown fox jumps over the lazy cat, the quick brown fox"
        comb = G + data
        found = 0
        for p in range(len(data)):
            for dist, L in idx.copies(comb, p, len(data)):
                found += 1
                j = len(G) + p - dist
                self.assertGreaterEqual(j, 0)
                self.assertLessEqual(j + L, len(G))  # a fonte inteira está dentro de Γ
        self.assertGreater(found, 0)

    def test_roundtrip_v3_variants_both_parsers(self):
        import exp_gamma_copy as ec
        import exp_gamma_dict as egd
        import token_coder
        genes = [b"GENE-SEQUENCE-ABCDEFGH", b"another gene body here!", b"x" * 40]
        lib = lib_from(genes)
        G = b"".join(genes)
        gidx = ec.GammaIndex(G)
        data = (G[5:40] + b"-xyz-" + G[100:160] + b"0123456789" * 3 + bytes(range(50))
                + genes[2] + genes[0])
        for parser in ("guloso", "otimo"):
            for variant in ("G0", "E0", "E1"):
                with self.subTest(parser=parser, variant=variant):
                    toks, R = ec.tokens_for(variant, parser, data, lib, gidx, G)
                    n_genes = len(genes) if variant in ("G0", "E1") else 0
                    blob = token_coder.encode_tokens(toks, R, n_genes)
                    self.assertEqual(token_coder.decode_tokens(blob, n_genes), (toks, R))
                    self.assertTrue(egd.verify_vm(toks, R, lib, G, data))

    def test_roundtrip_v1_v2_window_variants(self):
        import exp_gamma_dict as egd
        genes = [b"GENE-SEQUENCE-ABCDEFGH", b"another gene body here!", b"x" * 40]
        lib = lib_from(genes)
        G = b"".join(genes)
        data = G[5:40] + b"-xyz-" + genes[1] * 2 + b"abcabcabc" * 9 + genes[2]
        for parser in ("guloso", "otimo"):
            for variant in ("A", "B", "C", "D"):
                with self.subTest(parser=parser, variant=variant):
                    toks, R = egd.variant_tokens(variant, data, lib, G, parser)
                    self.assertTrue(egd.verify_vm(toks, R, lib, G, data))


class StreamFormatTests(unittest.TestCase):
    """Formato de fluxos fluxos-v1 (stb_stream_format.py), tokens G0."""

    GENES = [bytes([i % 256]) * 8 + bytes([i // 256]) for i in range(300)]  # 300 genes distintos

    def _toks(self, rnd, n=200):
        import stb_v2
        toks = []
        for _ in range(n):
            k = rnd.choice(("lit", "ref", "rpt"))
            if k == "lit":
                toks.append((stb_v2.T_LIT, rnd.randint(1, 40)))
            elif k == "ref":
                toks.append((stb_v2.T_REF, rnd.randrange(300)))
            else:
                toks.append((stb_v2.T_RPT, rnd.randint(3, 50), rnd.randrange(300)))
        toks.append((stb_v2.T_STP,))
        R = bytes(rnd.randrange(256) for _ in range(sum(t[1] for t in toks if t[0] == stb_v2.T_LIT)))
        return toks, R

    def test_roundtrip_random_token_lists(self):
        import stb_stream_format as sf
        rnd = random.Random(7)
        for _ in range(20):
            toks, R = self._toks(rnd)
            blob = sf.encode(toks, R, 300)
            self.assertEqual(sf.decode(blob, 300), (toks, R))

    def test_roundtrip_only_stp_and_empty_literals(self):
        import stb_stream_format as sf
        import stb_v2
        toks = [(stb_v2.T_STP,)]
        self.assertEqual(sf.decode(sf.encode(toks, b"", 0), 0), (toks, b""))
        toks = [(stb_v2.T_REF, 0), (stb_v2.T_STP,)]
        self.assertEqual(sf.decode(sf.encode(toks, b"", 1), 1), (toks, b""))

    def test_rc_models_roundtrip_per_stream(self):
        import stb_stream_format as sf
        import stb_v2
        rnd = random.Random(3)
        kinds = [rnd.choice((0, 1, 2, 4)) for _ in range(500)] + [4]
        lens = [rnd.randint(1, 1000) for _ in range(300)]
        cnts = [rnd.randint(3, 5000) for _ in range(300)]
        gids = [rnd.randrange(300) for _ in range(300)]
        for kind, vals in (("T", kinds), ("LEN", lens), ("CNT", cnts), ("GID", gids)):
            with self.subTest(kind=kind):
                body = sf._rc_encode(kind, vals, 300)
                self.assertEqual(sf._rc_decode(kind, body, len(vals), 300), vals)

    def test_incompressible_residue_stored_raw(self):
        import stb_stream_format as sf
        import stb_v2
        rnd = random.Random(11)
        R = bytes(rnd.randrange(256) for _ in range(4000))
        toks = [(stb_v2.T_LIT, len(R)), (stb_v2.T_STP,)]
        blob = sf.encode(toks, R, 0)
        # cabeçalho: versão, depois o registro T (método, n, tamanho); R é o último registro
        rd = sf._Reader(blob)
        rd.byte()
        for kind in ("T", "LEN", "CNT", "GID"):
            sf._decode_record(rd, kind, 0)
        self.assertEqual(blob[rd.pos], sf.M_RAW)

    def test_structural_rejections(self):
        import stb_stream_format as sf
        import stb_v2
        good = sf.encode([(stb_v2.T_LIT, 3), (stb_v2.T_STP,)], b"abc", 0)
        bad_inputs = {
            "versão": bytes([9]) + good[1:],
            "truncado": good[:-2],
            "bytes sobrando": good + b"\x00",
            "vazio": b"",
        }
        for name, buf in bad_inputs.items():
            with self.subTest(case=name):
                with self.assertRaises(ValueError):
                    sf.decode(buf, 0)
        with self.assertRaises(ValueError):  # COPY não existe no fluxos-v1
            sf.encode([(stb_v2.T_COPY, 1, 6), (stb_v2.T_STP,)], b"", 0)
        with self.assertRaises(ValueError):  # gene fora de Γ
            sf.encode([(stb_v2.T_REF, 5), (stb_v2.T_STP,)], b"", 3)
        with self.assertRaises(ValueError):  # sem STP final
            sf.encode([(stb_v2.T_LIT, 1)], b"a", 0)
        with self.assertRaises(ValueError):  # soma dos LIT não confere com R
            sf.encode([(stb_v2.T_LIT, 2), (stb_v2.T_STP,)], b"a", 0)

    def test_every_single_bit_flip_is_detected_by_digest(self):
        """O digest do cabeçalho é SHA-256(bytecode ‖ R): nenhuma inversão de bit pode passar."""
        import hashlib
        import stb_stream_format as sf
        import stb_v2
        lib = lib_from(self.GENES[:3])
        toks = [(stb_v2.T_LIT, 5), (stb_v2.T_REF, 1), (stb_v2.T_RPT, 7, 2), (stb_v2.T_STP,)]
        R = b"hello"
        digest = hashlib.sha256(stb_v2.bytecode_from_tokens(toks, lib) + R).digest()
        blob = sf.encode(toks, R, 3)
        silent = 0
        for j in range(len(blob)):
            for bit in range(8):
                x = bytearray(blob)
                x[j] ^= 1 << bit
                try:
                    t2, R2 = sf.decode(bytes(x), 3)
                except ValueError:
                    continue
                if hashlib.sha256(stb_v2.bytecode_from_tokens(t2, lib) + R2).digest() == digest:
                    silent += 1
        self.assertEqual(silent, 0)


try:
    import exp_lossy  # precisa de numpy, Pillow e scikit-image
except ImportError:  # pragma: no cover - ambiente sem as dependências do experimento
    exp_lossy = None


@unittest.skipIf(exp_lossy is None, "exp_lossy requer Pillow e scikit-image")
class LossyTests(unittest.TestCase):
    """Codec com perda stb-lossy-v1 (exp_lossy.py)."""

    def _img(self):
        import numpy as np

        rng = np.random.default_rng(1)
        img = np.zeros((32, 48), np.uint8)
        img[:, :16] = 100  # região plana
        img[:, 16:32] = rng.integers(0, 256, (32, 16))  # ruído (sem gene)
        img[:, 32:] = np.tile(np.arange(16, dtype=np.uint8) * 8, (32, 1))  # gradiente
        img[8:16, 16:32] = img[0:8, 0:16]  # bloco repetido (REF)
        return img

    def test_decoder_matches_encoder_reconstruction(self):
        import numpy as np

        img = self._img()
        for q in (1, 4, 16):
            for tau in (0.9999, 0.9, 0.5):
                for usar_ref in (True, False):
                    blob, rec, _ = exp_lossy.encode(img, q, tau, usar_ref)
                    self.assertTrue(np.array_equal(exp_lossy.decode(blob), rec), (q, tau, usar_ref))

    def test_no_genes_and_q1_is_exact(self):
        import numpy as np

        img = self._img()
        blob, rec, contagem = exp_lossy.encode(img, 1, 2.0, True)  # limiar impossível: só RES
        self.assertEqual(contagem, [0, 0, 0, 32 * 48 // 64])
        self.assertTrue(np.array_equal(rec, img))
        self.assertTrue(np.array_equal(exp_lossy.decode(blob), img))

    def test_constant_image_uses_flat_only(self):
        import numpy as np

        img = np.full((16, 16), 77, np.uint8)
        blob, rec, contagem = exp_lossy.encode(img, 8, 0.9999, True)
        self.assertEqual(contagem, [4, 0, 0, 0])
        self.assertTrue(np.array_equal(exp_lossy.decode(blob), img))

    def test_every_truncation_is_rejected(self):
        blob, _, _ = exp_lossy.encode(self._img(), 4, 0.9, True)
        for n in range(len(blob)):
            with self.assertRaises(ValueError, msg=f"prefixo de {n} bytes foi aceito"):
                exp_lossy.decode(blob[:n])

    def test_rd_decoder_matches_encoder_reconstruction(self):
        import numpy as np

        img = self._img()
        for q in (1, 8):
            for lam in (100, 3000, 30000):
                for usar_ref in (True, False):
                    blob, rec, _ = exp_lossy.encode(img, q, usar_ref=usar_ref, lam=lam)
                    self.assertTrue(np.array_equal(exp_lossy.decode(blob), rec), (q, lam, usar_ref))

    def test_structured_images_are_deterministic_and_aligned(self):
        import numpy as np

        from synth_structured import carregar_estruturadas

        a = carregar_estruturadas()
        b = carregar_estruturadas()
        self.assertEqual(set(a), {"grafico_linha", "grafico_barras", "documento", "tabela", "interface", "diagrama"})
        for nome in a:
            self.assertEqual(a[nome].dtype, np.uint8)
            self.assertEqual(a[nome].shape, (512, 512))
            self.assertEqual(a[nome].shape[0] % 8, 0)
            self.assertTrue(np.array_equal(a[nome], b[nome]), nome)

    def test_qxz_roundtrip(self):
        import numpy as np

        img = self._img()
        for q in (1, 2, 8):
            blob, rec = exp_lossy.encode_qxz(img, q)
            self.assertTrue(np.array_equal(exp_lossy.decode_qxz(blob), rec))


class RedeTests(unittest.TestCase):
    """Opção B: códigos de símbolo de 6 bits e simulador de transporte (exp_rede.py)."""

    def test_sec_code_corrects_every_single_flip(self):
        import exp_rede as er

        for c in er.CODIGO_SEC:
            for bit in range(6):
                recebido = int(c) ^ (1 << bit)
                dec = er.CODIGO_SEC[int(np.argmin(er.POP[recebido ^ er.CODIGO_SEC]))]
                self.assertEqual(int(dec), int(c))

    def test_even_parity_detects_every_single_flip(self):
        import exp_rede as er

        for c in er.PARES:
            for bit in range(6):
                self.assertEqual(er.POP[int(c) ^ (1 << bit)] % 2, 1)

    def test_grec_decoder_maps_data_words_to_themselves(self):
        import exp_rede as er

        self.assertTrue(np.array_equal(er.TABELA_GREC[:48], np.arange(48)))
        self.assertTrue(np.all(er.TABELA_GREC < 48))

    def test_pair_bound_for_48_words(self):
        import exp_rede as er

        pares, contidos = er.limite_par_hipercubo()
        self.assertEqual((pares, contidos), (32, 16))

    def test_symbol_error_is_zero_without_noise(self):
        import exp_rede as er

        r = er.simular_simbolos(0.0, 2000, np.random.default_rng(1))
        for v in r.values():
            self.assertEqual(v["erro"], 0.0)
            self.assertEqual(v["apagamento"], 0.0)

    def test_arq_without_loss_takes_exact_time(self):
        import exp_rede as er

        # Sem perda, o último pacote é enviado no slot K-1 e chega RTT/2 depois.
        self.assertEqual(er.tempo_arq(100, 0.0, 10, 50, np.random.default_rng(0)), 99 + 5)

    def test_arq_time_grows_with_loss(self):
        import exp_rede as er

        rng = np.random.default_rng(3)
        t0 = er.tempo_arq(500, 0.0, 20, 200, rng)
        t1 = er.tempo_arq(500, 0.2, 20, 200, rng)
        self.assertGreater(t1, t0)

    def test_fountain_formula(self):
        import exp_rede as er

        self.assertAlmostEqual(er.tempo_fountain(1000, 0.0, 10), 1000 * 1.02 + 5)


if __name__ == "__main__":
    unittest.main()
