"""Optional operator-owned keyless local data composition; no implicit service.

Only this process configuration selects files, pins and numeric loopback URL.
Request bodies cannot override them. Manifest provenance is not engine attestation.
"""
import hashlib
import json
from pathlib import Path
import re
from discovery_local import DiscoveryError, LocalDiscovery, fail, bounds
from road_provider import GraphSource, ValhallaRoadProvider
from place_provider import OsmPlaceCatalog, PlaceCatalogError
from facility_provider import OfficialRestCatalog
from rest_stop_data import DATASET

HASH=re.compile(r'[a-f0-9]{64}')
def document(path, maximum, expected=None):
    file=Path(path)
    if file.is_symlink() or not file.is_file(): fail('DISCOVERY_CONFIGURATION_INVALID',503)
    with file.open('rb') as stream: raw=stream.read(maximum+1)
    if len(raw)>maximum: fail('DISCOVERY_CONFIGURATION_INVALID',503)
    if expected is not None and (not isinstance(expected,str) or not HASH.fullmatch(expected) or hashlib.sha256(raw).hexdigest()!=expected):
        fail('DISCOVERY_CONFIGURATION_PIN_MISMATCH',503)
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: fail('DISCOVERY_CONFIGURATION_INVALID',503)
            result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:fail('DISCOVERY_CONFIGURATION_INVALID',503))

def load(path):
    if not path:return None
    try:
        value=document(path,8192)
        keys={'endpoint','graphSource','graphManifestPath','graphManifestSha256','placeCatalogPath','placeCatalogSha256','officialDatasetSha256'}
        if type(value) is not dict or set(value)!=keys:fail('DISCOVERY_CONFIGURATION_INVALID',503)
        graph=value['graphSource']
        if type(graph) is not dict or set(graph)!={'sourceId','sourceSha256','dataAsOf','bounds','attribution','license'}:
            fail('DISCOVERY_CONFIGURATION_INVALID',503)
        if any(not isinstance(graph[k],str) or not 1<=len(graph[k])<=512 or any(ord(c)<32 for c in graph[k]) for k in ('sourceId','dataAsOf','attribution','license')):
            fail('DISCOVERY_CONFIGURATION_INVALID',503)
        source=GraphSource(graph['sourceId'],graph['sourceSha256'],graph['dataAsOf'],bounds(graph['bounds']),graph['attribution'],graph['license'])
        manifest=document(value['graphManifestPath'],1024*1024,value['graphManifestSha256'])
        if type(manifest)is not dict:fail('DISCOVERY_GRAPH_MANIFEST_INVALID',503)
        hashes=manifest.get('graphFileHashes')
        if manifest.get('success') is not True or manifest.get('sourceSha256')!=source.source_sha256 or type(hashes)is not dict or not hashes or manifest.get('graphFiles')!=len(hashes) or any(not isinstance(v,str) or not HASH.fullmatch(v) for v in hashes.values()):
            fail('DISCOVERY_GRAPH_MANIFEST_INVALID',503)
        places=OsmPlaceCatalog.load(value['placeCatalogPath'],expected_sha256=value['placeCatalogSha256'])
        rest=OfficialRestCatalog(DATASET,expected_dataset_sha256=value['officialDatasetSha256'])
        provider=ValhallaRoadProvider(value['endpoint'],source,timeout_seconds=3,query_seconds=8,max_snap_meters=50)
        return LocalDiscovery(provider,places,rest,official_dataset_sha256=value['officialDatasetSha256'])
    except DiscoveryError:
        raise
    except (OSError,ValueError,TypeError,KeyError,RecursionError):
        fail('DISCOVERY_CONFIGURATION_INVALID',503)
