import io
import json
import os
import pathlib
import tempfile
import unittest
from private_records import VisitCipher,PrivateRecordError
import backup_vault

class PrivateRecordTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.key=pathlib.Path(self.folder.name)/'key'
        self.key.write_bytes(os.urandom(32));self.key.chmod(0o600)
        self.previous=os.environ.get('WEGOH_VISIT_KEY_FILE');os.environ['WEGOH_VISIT_KEY_FILE']=str(self.key)
    def tearDown(self):
        if self.previous is None:os.environ.pop('WEGOH_VISIT_KEY_FILE',None)
        else:os.environ['WEGOH_VISIT_KEY_FILE']=self.previous
        self.folder.cleanup()
    def test_visit_authentication_and_owner_binding(self):
        cipher=VisitCipher();record=dict(place=dict(name='SYNTHETIC PRIVATE PLACE',latitude=37.5),visitedAt=123456789)
        protected=cipher.protect('owner','visit',record)
        self.assertNotIn(b'SYNTHETIC',protected)
        self.assertEqual(record,cipher.restore('owner','visit',protected))
        self.assertNotEqual(protected,cipher.protect('owner','visit',record))
        for owner,visit,data in [('other','visit',protected),('owner','other',protected),('owner','visit',protected[:-1]+bytes([protected[-1]^1]))]:
            with self.assertRaises(PrivateRecordError):cipher.restore(owner,visit,data)
    def test_streamed_backup_roundtrip_and_tamper(self):
        raw=(b'SYNTHETIC PRIVATE BACKUP\x00'*10000)
        output=io.BytesIO();backup_vault.encrypt(io.BytesIO(raw),output)
        protected=output.getvalue();self.assertNotIn(b'SYNTHETIC',protected)
        backup_vault.decrypt(io.BytesIO(protected))
        restored=io.BytesIO();backup_vault.decrypt(io.BytesIO(protected),restored);self.assertEqual(raw,restored.getvalue())
        from cryptography.exceptions import InvalidTag
        with self.assertRaises(InvalidTag):backup_vault.decrypt(io.BytesIO(protected[:-1]+bytes([protected[-1]^1])))

if __name__=='__main__':unittest.main(verbosity=2)
