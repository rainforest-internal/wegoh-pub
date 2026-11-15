"""Credential/DB boundary for the dedicated systemd enrollment UID only."""
import os,re,stat,time
from pathlib import Path
import psycopg
from psycopg.conninfo import conninfo_to_dict
from fastapi import HTTPException
from runtime_credentials import apply_runtime_credentials
from team_auth import TeamAuth,hashed
from enrollment_crypto import read_cf_token

SYSTEMD_CREDENTIAL_BASE=Path('/run/credentials/wegoh-live-enrollment.service')


def credential_bytes(base,name,maximum):
    flags=os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC
    directory=os.open(base,flags|os.O_DIRECTORY)
    try:
        descriptor=os.open(name,flags,dir_fd=directory)
        try:
            info=os.fstat(descriptor)
            mode=stat.S_IMODE(info.st_mode)
            owned=info.st_uid==os.geteuid() and mode in(0o400,0o600)
            # systemd prefers root-owned files with a named service-UID read ACL;
            # chown is only its fallback. Trust that manager only at this exact
            # read-only per-unit mount, never arbitrary root/group-readable files.
            managed=(info.st_uid==0 and info.st_gid==0 and mode in(0o400,0o440)
                and Path(base)==SYSTEMD_CREDENTIAL_BASE
                and bool(os.fstatvfs(directory).f_flag & os.ST_RDONLY))
            if not stat.S_ISREG(info.st_mode) or not(owned or managed) or not 0<info.st_size<=maximum:
                raise RuntimeError('Unsafe enrollment credential')
            raw=os.read(descriptor,maximum+1)
            if len(raw)!=info.st_size:raise RuntimeError('Enrollment credential changed')
            return raw
        finally:os.close(descriptor)
    finally:os.close(directory)


def configure_runtime(environ=None):
    env=os.environ if environ is None else environ
    if os.geteuid()==0:raise RuntimeError('Dedicated nonroot enrollment user required')
    directory=env.get('CREDENTIALS_DIRECTORY','')
    if not directory or not Path(directory).is_absolute():raise RuntimeError('Enrollment credentials required')
    apply_runtime_credentials(env)
    credential_bytes(directory,'visit.key',32)
    credential_bytes(directory,'members.json',65536)
    try:secret=credential_bytes(directory,'team-auth.secret',256).decode('ascii').strip()
    except UnicodeError:raise RuntimeError('Invalid enrollment credential')from None
    if not re.fullmatch(r'[A-Za-z0-9_-]{43,128}',secret):raise RuntimeError('Invalid enrollment credential')
    env['WEGOH_API_KEY']=secret
    enabled=env.get('WEGOH_ENROLLMENT_ISSUER_ENABLED','0')
    if enabled not in('0','1'):raise RuntimeError('Explicit enrollment issuer mode required')
    env.pop('WEGOH_ENROLLMENT_CF_TOKEN_FILE',None)
    if enabled=='1':
        if not env.get('WEGOH_ENROLLMENT_ZONE_ID') or not env.get('WEGOH_ENROLLMENT_CA_ID'):
            raise RuntimeError('Enrollment issuer configuration incomplete')
        raw=credential_bytes(directory,'cf-api.token',1024)
        # Preserve the generic issuer's strict current-UID/private-file contract.
        # Only this service's volatile0700 RuntimeDirectory receives the copy;
        # no token is placed in argv, environment values, source or backups.
        volatile=Path(env.get('RUNTIME_DIRECTORY',''))
        if not volatile.is_absolute()or volatile.is_symlink():raise RuntimeError('Private enrollment runtime directory required')
        info=volatile.lstat()
        if not stat.S_ISDIR(info.st_mode)or info.st_uid!=os.geteuid()or stat.S_IMODE(info.st_mode)!=0o700:raise RuntimeError('Unsafe enrollment runtime directory')
        target=volatile/('cf-api-'+str(os.getpid())+'.token')
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
        try:
            with os.fdopen(fd,'wb')as stream:stream.write(raw);stream.flush();os.fchmod(stream.fileno(),0o400);os.fsync(stream.fileno())
        except BaseException:raise RuntimeError('Enrollment runtime credential unavailable')from None
        env['WEGOH_ENROLLMENT_CF_TOKEN_FILE']=str(target)
        read_cf_token(target)


def verify_database_scope(dsn):
    options=conninfo_to_dict(dsn)
    expected={'dbname':'wegoh_live','user':'wegohenroll','host':'/var/run/postgresql','connect_timeout':'3','options':'-csearch_path=public'}
    if options!=expected:raise RuntimeError('Dedicated enrollment Unix peer DSN required')
    with psycopg.connect(dsn)as conn:
        _verify_connection_scope(conn)


def _verify_connection_scope(conn):
    row=conn.execute("SELECT current_user,rolsuper,rolcreatedb,rolcreaterole,rolinherit,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
    if not row or row[0]!='wegohenroll' or any(row[1:]):raise RuntimeError('Enrollment role privilege boundary failed')
    if conn.execute('SELECT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user))').fetchone()[0]:raise RuntimeError('Enrollment role membership forbidden')
    if conn.execute("SELECT has_database_privilege(current_database(),'CREATE') OR has_schema_privilege('public','CREATE')").fetchone()[0]:raise RuntimeError('Enrollment DDL privilege forbidden')
    allowed={'team_accounts':set(),'vehicle_enrollments':{'SELECT','INSERT','UPDATE'},
        'vehicle_enrollment_rate_limits':{'SELECT','INSERT','UPDATE','DELETE'},
        'native_v2_connections':{'SELECT','INSERT','UPDATE'},
        'native_v2_certificates':{'INSERT'},'native_v2_issuer_approvals':{'SELECT'},
        'native_v2_certificate_recovery':{'SELECT'},'native_v2_installations':set()}
    column_allowed={'team_accounts':{'SELECT':{'account_id','protected'}},
        'native_v2_installations':{'SELECT':{'installation_key_id','current_generation','revision','revoked_at'},
                                  'UPDATE':{'current_generation','revision'}}}
    rows=conn.execute("SELECT n.nspname,c.relname,c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN('r','p','v','m','f') AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'").fetchall()
    found=set()
    for schema,name,oid in rows:
        expected_rights=allowed.get(name,set())if schema=='public'else set()
        if schema=='public' and name in allowed:found.add(name)
        for privilege in('SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER'):
            permitted=conn.execute('SELECT has_table_privilege(%s,%s)',(oid,privilege)).fetchone()[0]
            if schema=='public' and name in column_allowed:
                if permitted:raise RuntimeError('Enrollment account table grant forbidden')
            elif permitted!=(privilege in expected_rights):raise RuntimeError('Enrollment table privilege boundary failed')
        if schema=='public' and name in column_allowed:
            for column, in conn.execute('SELECT attname FROM pg_attribute WHERE attrelid=%s AND attnum>0 AND NOT attisdropped',(oid,)):
                for privilege in('SELECT','INSERT','UPDATE','REFERENCES'):
                    permitted=conn.execute('SELECT has_column_privilege(%s,%s,%s)',(oid,column,privilege)).fetchone()[0]
                    if permitted!=(column in column_allowed[name].get(privilege,set())):raise RuntimeError('Enrollment account column privilege boundary failed')
        elif not expected_rights:
            if conn.execute("SELECT has_any_column_privilege(%s,'SELECT,INSERT,UPDATE,REFERENCES')",(oid,)).fetchone()[0]:raise RuntimeError('Unrelated enrollment column grant forbidden')
    if found!=set(allowed):raise RuntimeError('Enrollment schema incomplete')
    if conn.execute("SELECT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE p.prosecdef AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' AND has_function_privilege(p.oid,'EXECUTE'))").fetchone()[0]:raise RuntimeError('Enrollment security-definer access forbidden')
    if conn.execute("SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE CASE WHEN c.relkind='S' AND n.nspname NOT LIKE 'pg_%' THEN has_sequence_privilege(c.oid,'USAGE,SELECT,UPDATE') ELSE false END)").fetchone()[0]:raise RuntimeError('Enrollment sequence privilege forbidden')


class EnrollmentRuntimeAuth(TeamAuth):
    def __init__(self,dsn,secret):
        super().__init__(dsn,secret,enrollment_only=True)

    def rate(self,scope,*,limit=60):
        # Dedicated rate metadata: this UID cannot delete the main API's buckets.
        bucket=int(time.time())//60
        with psycopg.connect(self.dsn)as conn:
            conn.execute('DELETE FROM vehicle_enrollment_rate_limits WHERE bucket<%s',(bucket-2,))
            hits=conn.execute('INSERT INTO vehicle_enrollment_rate_limits(scope_hash,bucket,hits) VALUES(%s,%s,1) ON CONFLICT(scope_hash) DO UPDATE SET bucket=excluded.bucket,hits=CASE WHEN vehicle_enrollment_rate_limits.bucket=excluded.bucket THEN vehicle_enrollment_rate_limits.hits+1 ELSE 1 END RETURNING hits',(hashed(scope),bucket)).fetchone()[0]
        if hits>limit:raise HTTPException(429,'Request limit exceeded',headers={'Retry-After':'60'})
