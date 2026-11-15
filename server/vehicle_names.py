"""Vehicle display names chosen by the owning account.

The name lives in the owner's encrypted vehicle profile next to the plate
number, keyed by installation. An empty stored name follows the default
"{account name}의 차", so renaming the account renames unnamed vehicles too.
The connection request label in the authorization consent is not a name.
"""
import unicodedata
from psycopg.rows import tuple_row
from private_records import VisitCipher

NAME_LIMIT = 20


def valid_vehicle_name(value):
    """Empty means the default name; otherwise 1..20 trimmed scalars without control or line separators."""
    return type(value) is str and (value == '' or (
        len(value) <= NAME_LIMIT and value == value.strip()
        and not any(unicodedata.category(c)[0] == 'C' or unicodedata.category(c) in ('Zl', 'Zp') for c in value)))


def owner_name(auth, saved):
    name = saved.get('displayName')
    if not name:
        member = auth.stored_member(saved)
        if not member:
            raise ValueError('Account name unavailable')
        name = member['name']
    return name


def default_vehicle_name(auth, saved):
    return owner_name(auth, saved) + '의 차'


def vehicle_name(auth, saved, installation_key):
    """Effective name of one installation for the decrypted account record."""
    stored = saved.get('vehicleProfiles', {}).get(installation_key, {}).get('name', '')
    return stored or default_vehicle_name(auth, saved)


def account_vehicle_names(auth, conn, owner):
    """Name lookup for one owner's installations, decrypting the account once when first used."""
    loaded = []

    def name(installation_key):
        if not loaded:
            with conn.cursor(row_factory=tuple_row) as cursor:
                row = cursor.execute('SELECT protected FROM team_accounts WHERE account_id=%s', (owner,)).fetchone()
            if not row:
                raise ValueError('Account unavailable')
            loaded.append(VisitCipher().restore('team-account:' + owner, 'identity', row[0]))
        return vehicle_name(auth, loaded[0], installation_key)
    return name
