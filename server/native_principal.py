"""Trusted native identity type; a public JSON version is never an auth discriminator."""

class NativePrincipal(dict):
    """Minted only after mTLS plus live grant/slot/epoch checks in the auth service."""

def is_native_principal(value):
    return isinstance(value, NativePrincipal)
