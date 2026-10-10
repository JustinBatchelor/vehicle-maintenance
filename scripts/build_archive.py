"""Create an OpenShift-compatible archive without macOS metadata or local data."""
import tarfile
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
target=Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/garage-build.tar.gz')
with tarfile.open(target,'w:gz',format=tarfile.GNU_FORMAT) as archive:
    for name in ['Containerfile','requirements.lock','manage.py','config','garage','templates','static','data']:
        path=root/name
        for p in ([path] if path.is_file() else sorted(path.rglob('*'))):
            if p.is_file() and '__pycache__' not in p.parts:
                archive.add(p,arcname=str(p.relative_to(root)),recursive=False)
print(f'Build archive: {target}')
