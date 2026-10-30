"""Offline tests: python -m unittest discover tests
Set PANAU_TEST_SAVE (and optionally PANAU_TEST_OTHER) to real JustCause2SaveNN.sav files to also test the save layer."""
import os
import struct
import unittest

from panau import data
from panau.hashing import hashlittle
from panau.save import world
from panau.save.format import EMPTY_KEY, WORLD_SLOTS


class Hashing(unittest.TestCase):
    def test_known_values(self):
        self.assertEqual(hashlittle(b''), 0xDEADBEEF)
        # hashes as they appear in the game's own data: a save's section table, placement-file property names
        self.assertEqual(hashlittle(b'ResourceItemHandler'), 0xB0F23D91)
        self.assertEqual(hashlittle(b'_class'), 0x1473B179)


class Data(unittest.TestCase):
    def test_targets(self):
        t = data.targets()
        kinds = {k for k, *_ in t}
        self.assertEqual(kinds, {'item', 'sabotage'})
        self.assertEqual(sum(1 for k, *_ in t if k == 'item'), 2524)
        self.assertGreater(sum(1 for k, *_ in t if k == 'sabotage'), 3500)
        self.assertEqual(len({g for _, _, g, _ in t}), len(t))
        self.assertTrue(all(abs(p[0]) < 17000 and abs(p[2]) < 17000 for *_, p in t))

    def test_flags_and_links(self):
        self.assertTrue(all(len(k) == 4 and v in (0, 1) for k, v in data.done_flags().items()))
        self.assertEqual(len(data.pipeline_panels()), 55)
        self.assertEqual(len(data.settlements()), 405)


class WorldTable(unittest.TestCase):
    def empty_world(self):
        return [(0, struct.pack('<I', WORLD_SLOTS)), (1, struct.pack('<I', 0)),
                (9, EMPTY_KEY * WORLD_SLOTS), (10, bytes((WORLD_SLOTS + 7) // 8))]

    def test_copy_groups_inserts_at_probe_position(self):
        tk = bytes.fromhex('3639fe59')
        out = world.copy_groups(self.empty_world(), {0x12345678: {tk: 1}}, [0x12345678])
        st = world.states(out)
        self.assertEqual(st[0x12345678], {tk: 1})
        key = tk + struct.pack('<I', 0x12345678)
        slot = struct.unpack('<Q', key)[0] % WORLD_SLOTS
        self.assertEqual(dict(out)[9][slot * 8:slot * 8 + 8], key)
        self.assertEqual(struct.unpack('<I', dict(out)[1])[0], 1)

    def test_is_done_uses_per_type_polarity(self):
        flags = {bytes.fromhex('aaaaaaaa'): 0}
        self.assertTrue(world.is_done({bytes.fromhex('aaaaaaaa'): 0}, flags))
        self.assertFalse(world.is_done({bytes.fromhex('aaaaaaaa'): 1}, flags))


@unittest.skipUnless(os.environ.get('PANAU_TEST_SAVE'), 'set PANAU_TEST_SAVE to a real save')
class RealSave(unittest.TestCase):
    def test_round_trip(self):
        from panau.save.format import Save
        s = Save.load(os.environ['PANAU_TEST_SAVE'])
        self.assertEqual(s.to_bytes(), s.raw)

    @unittest.skipUnless(os.environ.get('PANAU_TEST_OTHER'), 'set PANAU_TEST_OTHER to a second save')
    def test_merge_is_complete(self):
        import tempfile
        from panau.save import audit, merge
        a, b = os.environ['PANAU_TEST_SAVE'], os.environ['PANAU_TEST_OTHER']
        out, _ = merge.merge(a, b)
        with tempfile.NamedTemporaryFile(suffix='.sav', delete=False) as f:
            f.write(out)
        try:
            self.assertFalse(any(m for m, _ in audit.objectives(f.name, [a, b]).values()))
            self.assertFalse(any(audit.sections(f.name, [a, b]).values()))
        finally:
            os.remove(f.name)


if __name__ == '__main__':
    unittest.main()
