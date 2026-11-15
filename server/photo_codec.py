"""Bounded JPEG/PNG stdin -> metadata-stripped JPEG worker, never an HTTP route.
Dependencies load before an OS sandbox; untrusted pixels decode only afterwards.
"""
import ctypes,ctypes.util,errno,io,json,os,resource,socket,sys,warnings
MAX_INPUT=3*1024*1024
MAX_PIXELS=16000000
MAX_SIDE=8192
MAX_OUTPUT=3*1024*1024
class SandboxUnavailable(Exception):pass

def sandbox():
    if sys.platform.startswith('linux'):
        name=ctypes.util.find_library('seccomp')
        if not name:raise SandboxUnavailable()
        lib=ctypes.CDLL(name,use_errno=True)
        lib.seccomp_init.argtypes=[ctypes.c_uint32];lib.seccomp_init.restype=ctypes.c_void_p
        lib.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p];lib.seccomp_syscall_resolve_name.restype=ctypes.c_int
        class Compare(ctypes.Structure):_fields_=[('arg',ctypes.c_uint),('op',ctypes.c_int),('a',ctypes.c_uint64),('b',ctypes.c_uint64)]
        lib.seccomp_rule_add_array.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint,ctypes.POINTER(Compare)];lib.seccomp_rule_add_array.restype=ctypes.c_int
        lib.seccomp_load.argtypes=[ctypes.c_void_p];lib.seccomp_load.restype=ctypes.c_int
        lib.seccomp_release.argtypes=[ctypes.c_void_p]
        ctx=lib.seccomp_init(0x00050000|errno.EPERM)
        if not ctx:raise SandboxUnavailable()
        try:
            for call in ('brk','mmap','mmap2','mremap','munmap','mprotect','madvise','futex','futex_time64','clock_gettime','clock_gettime64','gettimeofday','getpid','gettid','getrandom','sched_yield','rt_sigaction','rt_sigprocmask','rt_sigreturn','sigaltstack','restart_syscall','exit','exit_group'):
                number=lib.seccomp_syscall_resolve_name(call.encode())
                if number>=0 and lib.seccomp_rule_add_array(ctx,0x7fff0000,number,0,None)!=0:raise SandboxUnavailable()
            for call in ('write','writev'):
                number=lib.seccomp_syscall_resolve_name(call.encode())
                for fd in (1,2):
                    cmp=Compare(0,4,fd,0)
                    if number>=0 and lib.seccomp_rule_add_array(ctx,0x7fff0000,number,1,ctypes.byref(cmp))!=0:raise SandboxUnavailable()
            if lib.seccomp_load(ctx)!=0:raise SandboxUnavailable()
        finally:lib.seccomp_release(ctx)
        return 'linux-seccomp-memory-only'
    if sys.platform=='darwin':
        # Seatbelt is fail-closed and remains unverified until run on an actual Mac.
        try:
            lib=ctypes.CDLL('/usr/lib/libsandbox.1.dylib');lib.sandbox_init.argtypes=[ctypes.c_char_p,ctypes.c_uint64,ctypes.POINTER(ctypes.c_char_p)];lib.sandbox_init.restype=ctypes.c_int
            error=ctypes.c_char_p();profile=b'(version 1)(deny default)(allow sysctl-read)(allow file-write-data (literal "/dev/stdout") (literal "/dev/stderr"))'
            if lib.sandbox_init(profile,0,ctypes.byref(error))!=0:raise SandboxUnavailable()
            return 'macos-seatbelt'
        except (OSError,AttributeError):raise SandboxUnavailable()from None
    raise SandboxUnavailable()

def main():
    resource.setrlimit(resource.RLIMIT_AS,(384*1024*1024,384*1024*1024));resource.setrlimit(resource.RLIMIT_CPU,(4,5));resource.setrlimit(resource.RLIMIT_FSIZE,(MAX_OUTPUT+1024,MAX_OUTPUT+1024));resource.setrlimit(resource.RLIMIT_CORE,(0,0));resource.setrlimit(resource.RLIMIT_NOFILE,(16,16))
    from PIL import Image,ImageOps,JpegImagePlugin,PngImagePlugin,TiffImagePlugin
    Image.MAX_IMAGE_PIXELS=MAX_PIXELS;PngImagePlugin.MAX_TEXT_CHUNK=65536;PngImagePlugin.MAX_TEXT_MEMORY=1024*1024
    warnings.simplefilter('error',Image.DecompressionBombWarning)
    probe=len(sys.argv)==2 and sys.argv[1]=='--probe'
    if not probe and (len(sys.argv)!=2 or sys.argv[1]not in('image/jpeg','image/png')):raise ValueError()
    raw=b''if probe else sys.stdin.buffer.read(MAX_INPUT+1)
    if not probe and(not raw or len(raw)>MAX_INPUT):raise ValueError()
    if not probe and not((sys.argv[1]=='image/jpeg'and raw.startswith(b'\xff\xd8\xff'))or(sys.argv[1]=='image/png'and raw.startswith(b'\x89PNG\r\n\x1a\n'))):raise ValueError()
    os.closerange(3,16);os.close(0);kind=sandbox()
    if probe:
        blocked=[]
        try:fd=os.open('/etc/passwd',os.O_RDONLY)
        except PermissionError:blocked.append('file')
        else:os.close(fd)
        try:sock=socket.socket()
        except PermissionError:blocked.append('network')
        else:sock.close()
        if set(blocked)!={'file','network'}:raise SandboxUnavailable()
        sys.stdout.buffer.write(json.dumps(dict(sandbox=kind,blocked=blocked)).encode());return
    with Image.open(io.BytesIO(raw),formats=['JPEG','PNG'])as image:
        width,height=image.size
        if min(width,height)<1 or max(width,height)>MAX_SIDE or width*height>MAX_PIXELS or getattr(image,'n_frames',1)!=1:raise ValueError()
        image.load();oriented=ImageOps.exif_transpose(image);oriented.thumbnail((2048,2048),Image.Resampling.LANCZOS)
        rgba=oriented.convert('RGBA');clean=Image.new('RGB',rgba.size,'white');clean.paste(rgba,mask=rgba.getchannel('A'));clean.info.clear();out=io.BytesIO();clean.save(out,format='JPEG',quality=82,optimize=False,exif=b'',icc_profile=None)
        encoded=out.getvalue()
        if len(encoded)>MAX_OUTPUT:raise ValueError()
        header=json.dumps(dict(width=clean.width,height=clean.height,sandbox=kind)).encode()+b'\n';sys.stdout.buffer.write(header+encoded)
if __name__=='__main__':
    try:main()
    except (ImportError,SandboxUnavailable):sys.exit(69)
    except Exception:sys.exit(65)
