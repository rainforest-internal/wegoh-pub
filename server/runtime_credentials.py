"""Resolve systemd per-service credentials before application configuration is read."""
import os,stat
from pathlib import Path

def apply_runtime_credentials(environ=None):
    environment=os.environ if environ is None else environ
    directory=environment.get('CREDENTIALS_DIRECTORY')
    if not directory:return
    base=Path(directory)
    if not base.is_absolute() or base.is_symlink() or not base.is_dir():raise RuntimeError('Invalid service credential directory')
    for name,variable in [('visit.key','WEGOH_VISIT_KEY_FILE'),('members.json','WEGOH_TEAM_MEMBERS_FILE')]:
        target=base/name
        info=target.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode)&0o022:raise RuntimeError('Unsafe service credential')
        if name=='visit.key' and info.st_size!=32:raise RuntimeError('Service encryption key is invalid')
        environment[variable]=str(target)
