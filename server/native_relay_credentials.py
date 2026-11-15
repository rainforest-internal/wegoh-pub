"""Purpose-only issuer relay key; never falls back to an account auth secret."""
import os,stat
from pathlib import Path

def load_relay_key(environ=None):
    env=os.environ if environ is None else environ
    directory=env.get('CREDENTIALS_DIRECTORY')
    if directory:
        if env.get('WEGOH_NATIVE_RELAY_KEY_FILE'):raise RuntimeError('Ambiguous native relay credential source')
        base=Path(directory)
        if not base.is_absolute() or base.is_symlink():raise RuntimeError('Managed native relay credential required')
        parent=os.open(base,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            fd=os.open('native-relay.key',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
            readonly=bool(os.fstatvfs(parent).f_flag & os.ST_RDONLY)
        finally:os.close(parent)
    else:
        path=Path(env.get('WEGOH_NATIVE_RELAY_KEY_FILE',''))
        if not path.is_absolute():raise RuntimeError('Explicit private native relay credential required')
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC);readonly=False
    try:
        info=os.fstat(fd);mode=stat.S_IMODE(info.st_mode)
        owned=info.st_uid==os.geteuid() and mode in (0o400,0o600)
        managed=bool(directory) and readonly and info.st_uid==0 and info.st_gid==0 and mode in (0o400,0o440)
        if not stat.S_ISREG(info.st_mode) or info.st_size!=32 or not (owned or managed):raise RuntimeError('Unsafe native relay credential')
        raw=os.read(fd,33)
        if len(raw)!=32:raise RuntimeError('Native relay credential changed')
        return raw
    finally:os.close(fd)
