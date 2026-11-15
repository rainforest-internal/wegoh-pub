"""Explicit fixture-only facility selection; does not alter operating data."""
import unittest
from collections import Counter
from fastapi import HTTPException
import team_discovery as discovery
from rest_stop_data import DATASET
from discovery_local import prepare

class RestSignalFilters(unittest.TestCase):
    def test_real_public_flags_preserve_unknown_and_rest_spaces(self):
        self.assertEqual(Counter(x["facilities"]["restSpace"]for x in DATASET["items"]),{True:142,False:73})
        point=DATASET["items"][0]
        anchor=dict(kind="selected-place",place=dict(id="public-rest-anchor",provider="map",name="Public snapshot anchor",address="",latitude=point["latitude"],longitude=point["longitude"]))
        # The explicit broad radius uses actual public rows; each required flag must be true.
        for facilities in (["toilet"],["nursing"],["restSpace"],["nursing","restSpace"]):
            body=dict(anchor=anchor,requiredFacilities=facilities,radiusMeters=200000,limit=20)
            result=discovery.query(body)
            self.assertTrue(result["items"])
            self.assertTrue(all(all(row["facilities"][key]is True for key in facilities)for row in result["items"]))
            self.assertEqual(result["applied"]["requiredFacilities"],facilities)
            road=dict(anchor=anchor,requiredFacilities=facilities,roadSearch=dict(bounds=dict(west=124,south=32,east=132,north=40),order="distance"))
            self.assertEqual(prepare(road,"rest").facilities,tuple(facilities))
        for unsupported in ("smoking","drowsy","food"):
            with self.assertRaises(HTTPException):discovery.query(dict(anchor=anchor,requiredFacilities=[unsupported]))
        self.assertIsNone(result["items"][0]["currentOpen"])
        self.assertIsNone(result["items"][0]["price"])
if __name__=="__main__":unittest.main()
