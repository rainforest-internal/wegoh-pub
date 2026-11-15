"""Owned dev snapshot: one public JSON contract, no generic JSON exposure."""
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ops import dev

class DevAssetsTests(unittest.TestCase):
    def test_exact_native_wire_is_in_real_owned_dev_snapshot(self):
        # Exercise the real collector with owned minimal files, so this storage
        # unit does not consume unrelated, still-edited product UI or screen maps.
        authoritative=(dev.SERVER/'native_access_wire.json').read_bytes()
        with tempfile.TemporaryDirectory(prefix="wegoh-wire-dev-") as directory:
            root=Path(directory);server=root/'server';web=server/'web';web.mkdir(parents=True)
            (server/'native_access_wire.json').write_bytes(authoritative)
            (web/'native-access-wire.json').write_bytes(authoritative)
            (web/'index.html').write_text('<html></html>')
            (web/'unrelated-private.json').write_text('{"private":"not public"}')
            for name,data in [('android/app/src/main/res/font/asta_sans.ttf',b'collector fixture, not a rendered font'),
                              ('android/third_party/asta-sans/OFL.txt',b'fixture license'),
                              ('docs/platform-screen-map.json',b'{}')]:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            state=root/'state';state.mkdir(mode=0o700)
            with patch.object(dev,'SERVER',server),patch.object(dev,'ROOT',root):
                target=dev.stage_web(state)
            self.assertEqual((target/'native-access-wire.json').read_bytes(),authoritative)
            self.assertFalse((target/'public-assets.json').exists())
            self.assertFalse((target/'unrelated-private.json').exists())
    def test_mismatched_wire_is_rejected_before_creating_snapshot(self):
        with tempfile.TemporaryDirectory(prefix="wegoh-wire-mismatch-") as directory:
            root=Path(directory);server=root/'server';web=server/'web';web.mkdir(parents=True)
            (web/'native-access-wire.json').write_text('{}');(server/'native_access_wire.json').write_text('{"different":true}')
            state=root/'state';state.mkdir(mode=0o700)
            with patch.object(dev,'SERVER',server),patch.object(dev,'ROOT',root),self.assertRaisesRegex(RuntimeError,'authoritative contract'):
                dev.stage_web(state)
            self.assertFalse((state/'web').exists())
if __name__=='__main__':unittest.main()
