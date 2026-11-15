"""Existing browser device UX with exact current owner, lock and downward consent."""
from datetime import datetime,timezone
from fastapi import HTTPException
from psycopg.rows import dict_row
from native_authorization import fail,restore
from native_access_management import list_owned,lookup_owned_locked
from vehicle_names import account_vehicle_names
from native_access_retention import RetentionError,reduce_grant_scopes
from team_data import changed

class NativeAccessBrowser:
    def list_owned_devices(self,owner):
        with self.db() as conn:
            return list_owned(conn,owner,vehicle_name=account_vehicle_names(self.auth,conn,owner),now=self.now())

    def _owned_lock(self,conn,owner,device):
        with conn.cursor(row_factory=dict_row)as cursor:
            initial=cursor.execute("SELECT installation_key_id FROM native_v2_grants WHERE account_id=%s AND device_id=%s",
            (owner,device)).fetchone()
        if not initial:return None
        self.lock(conn,initial["installation_key_id"])
        return lookup_owned_locked(conn,owner,device)

    def revoke_owned_device(self,owner,device):
        with self.db() as conn:
            grant=self._owned_lock(conn,owner,device)
            if not grant:return False
            self._revoke(conn,grant["grant_id"],self.now())
            changed(conn,owner,"devices")
            return True

    def _owned_snapshot(self,conn,grant):
        self._live(grant)
        consent=restore("consent",grant["grant_id"],grant["protected_consent"])
        name=account_vehicle_names(self.auth,conn,grant["account_id"])(grant["installation_key_id"])
        return dict(authorizationVersion=1,deviceId=grant["device_id"],name=name,
            revision=grant["consent_version"],consentVersion=grant["consent_version"],scopes=consent["scopes"],
            keepSignedIn=consent["keepSignedIn"],expiresAt=datetime.fromtimestamp(grant["expires_at"],timezone.utc),
            grantExpiresAt=grant["expires_at"])

    def owned_permissions(self,owner,device):
        with self.db() as conn:
            grant=self._owned_lock(conn,owner,device)
            return self._owned_snapshot(conn,grant) if grant else None

    def reduce_owned_scopes(self,owner,device,value):
        with self.db() as conn:
            grant=self._owned_lock(conn,owner,device)
            if not grant:raise HTTPException(404,"Device unavailable")
            self._live(grant)
            if type(value) is not dict or set(value)!={"revision","scopes"}:
                raise HTTPException(400,"Invalid device scopes")
            try:
                result=reduce_grant_scopes(conn,grant,value["scopes"],expected_consent_version=value["revision"])
            except RetentionError as error:
                raise HTTPException(403 if str(error)=="SCOPE_DENIED" else 409,str(error)) from None
            if result["terminal"]:
                self._revoke(conn,grant["grant_id"],self.now())
                changed(conn,owner,"devices")
                return dict(authorizationVersion=1,deviceId=device,status="revoked")
            if result["changed"]:changed(conn,owner,"devices")
            current=conn.execute("SELECT * FROM native_v2_grants WHERE grant_id=%s",(grant["grant_id"],)).fetchone()
            return self._owned_snapshot(conn,current)

