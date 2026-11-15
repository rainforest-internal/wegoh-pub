"""Operator-file pin checks; no engine dispatch or data acquisition."""
import hashlib,json,tempfile,unittest
from pathlib import Path
from discovery_local import DiscoveryError
from discovery_local_config import load
from facility_provider import dataset_digest
from rest_stop_data import DATASET

class DiscoveryConfigTests(unittest.TestCase):
    def test_absent_valid_pins_unknown_config_and_mutated_manifest_catalog_denied(self):
        self.assertIsNone(load(None))
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            manifest=root/'graph.json';manifest.write_text(json.dumps(dict(success=True,sourceSha256='a'*64,graphFiles=1,graphFileHashes={'synthetic.gph':'b'*64})))
            catalog=root/'places.json';catalog.write_text(json.dumps(dict(schemaVersion=1,source=dict(sourceSha256='a'*64,dataAsOf='2030-01-01T00:00:00+00:00',bounds=[124,32,132,40],publisher='Synthetic',url='https://download.geofabrik.de/fixture',attribution='© OpenStreetMap contributors',license='ODbL-1.0',geometryCoverage='named tagged nodes only; ways and relations not covered',live=False),places=[])))
            sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
            value=dict(endpoint='http://127.0.0.1:1',graphSource=dict(sourceId='synthetic',sourceSha256='a'*64,dataAsOf='2030-01-01T00:00:00+00:00',bounds=dict(west=124,south=32,east=132,north=40),attribution='© OpenStreetMap contributors',license='ODbL-1.0'),graphManifestPath=str(manifest),graphManifestSha256=sha(manifest),placeCatalogPath=str(catalog),placeCatalogSha256=sha(catalog),officialDatasetSha256=dataset_digest(DATASET))
            config=root/'config.json'
            def write():config.write_text(json.dumps(value))
            def denied():
                with self.assertRaises(DiscoveryError) as raised:load(config)
                self.assertEqual(raised.exception.status,503)
            write();local=load(config);self.assertEqual(local.provider.query_seconds,8);self.assertEqual(local.provider.timeout_seconds,3);self.assertEqual(local.provider.max_snap_meters,50)
            value['extra']=True;write();denied();del value['extra']
            value['endpoint']='https://example.invalid';write();denied();value['endpoint']='http://127.0.0.1:1'
            write();manifest.write_text(manifest.read_text()+' ');denied()
            value['graphManifestSha256']=sha(manifest);write();catalog.write_text(catalog.read_text()+' ');denied()

if __name__=='__main__':unittest.main()
