"""Resolve the official SDK ABI dependency in non-root/custom build images."""
import ctypes,hashlib,io,os,platform,tarfile,tempfile,urllib.request
from pathlib import Path
DEB_URL='https://ftp.debian.org/debian/pool/main/libi/libidn/libidn11_1.33-3_amd64.deb'
DEB_SHA='0227af6e1e6d2aee6123f40ff8678e033ddf5165fcd8fa43a4851fd3832db5e2'
LIB_SHA='ea4c9cc069441bb3ec12de8b41b874aa59dc8f6f10d9a21be8d2e59ecb0c3c69'
def extract_library(data):
    if hashlib.sha256(data).hexdigest()!=DEB_SHA:raise ValueError('NATIVE_PACKAGE_HASH_MISMATCH')
    if data[:8]!=b'!<arch>\n':raise ValueError('INVALID_NATIVE_PACKAGE')
    offset=8
    while offset+60<=len(data):
        header=data[offset:offset+60];size=int(header[48:58]);name=header[:16].decode().strip().rstrip('/')
        body=data[offset+60:offset+60+size];offset+=60+size+(size%2)
        if name.startswith('data.tar'):
            with tarfile.open(fileobj=io.BytesIO(body),mode='r:*') as archive:
                # Extract a single verified regular file, never arbitrary paths.
                member=archive.getmember('./lib/x86_64-linux-gnu/libidn.so.11.6.16')
                if not member.isfile() or member.size>1024*1024:raise ValueError('INVALID_NATIVE_LIBRARY')
                library=archive.extractfile(member).read()
            if hashlib.sha256(library).hexdigest()!=LIB_SHA:raise ValueError('NATIVE_LIBRARY_HASH_MISMATCH')
            return library
    raise ValueError('NATIVE_LIBRARY_NOT_FOUND')
def ensure_native():
    if platform.system()!='Linux':return
    if platform.machine()!='x86_64':raise OSError('SDK_ARCHITECTURE_UNSUPPORTED')
    try:ctypes.CDLL('libidn.so.11',mode=ctypes.RTLD_GLOBAL);return
    except OSError:pass
    directory=Path.home()/'.cache/zq-ifind-native';directory.mkdir(parents=True,exist_ok=True)
    library=directory/'libidn.so.11'
    if not library.exists() or hashlib.sha256(library.read_bytes()).hexdigest()!=LIB_SHA:
        with urllib.request.urlopen(DEB_URL,timeout=20) as response:data=response.read(1024*1024)
        raw=extract_library(data)
        fd,name=tempfile.mkstemp(dir=directory)
        try:
            with os.fdopen(fd,'wb') as file:file.write(raw)
            os.replace(name,library)
        finally:
            if os.path.exists(name):os.unlink(name)
    ctypes.CDLL(str(library),mode=ctypes.RTLD_GLOBAL)
