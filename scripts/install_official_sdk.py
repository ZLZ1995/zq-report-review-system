"""Install the SDK's libidn ABI dependency from a pinned official Debian package."""
import hashlib,importlib.util,pathlib,shutil,subprocess,tempfile,urllib.request
URL='https://ftp.debian.org/debian/pool/main/libi/libidn/libidn11_1.33-3_amd64.deb'
SHA='0227af6e1e6d2aee6123f40ff8678e033ddf5165fcd8fa43a4851fd3832db5e2'
def main():
    import platform
    if platform.machine() not in ('x86_64','AMD64'):raise RuntimeError('OFFICIAL_SDK_REQUIRES_AMD64')
    with tempfile.TemporaryDirectory() as tmp:
        tmp=pathlib.Path(tmp);deb=tmp/'libidn11.deb'
        with urllib.request.urlopen(URL,timeout=60) as r:content=r.read()
        if hashlib.sha256(content).hexdigest()!=SHA:raise RuntimeError('DEPENDENCY_HASH_MISMATCH')
        deb.write_bytes(content);subprocess.run(['dpkg-deb','-x',str(deb),str(tmp/'out')],check=True)
        library=tmp/'out/lib/x86_64-linux-gnu/libidn.so.11.6.16'
        shutil.copy2(library,'/usr/local/lib/libidn.so.11.6.16')
        link=pathlib.Path('/usr/local/lib/libidn.so.11')
        if not link.exists():link.symlink_to('libidn.so.11.6.16')
    subprocess.run(['ldconfig'],check=True)
    sdk=pathlib.Path(importlib.util.find_spec('iFinDAPI').origin).parent
    subprocess.run(['chown','-R','appuser:appuser',str(sdk/'Linux')],check=True)
if __name__=='__main__':main()
