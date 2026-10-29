"""Copy installed distribution metadata/license files into a release notice folder."""
import importlib.metadata
from pathlib import Path
import shutil
import sys

destination = Path(sys.argv[1])
destination.mkdir(parents=True, exist_ok=True)
index = []
for dist in importlib.metadata.distributions():
    name = dist.metadata.get("Name", "unknown")
    index.append(f"{name} {dist.version}\nLicense: {dist.metadata.get('License-Expression') or dist.metadata.get('License') or 'See metadata'}\n")
    for file in dist.files or ():
        parts = Path(str(file)).parts
        if ".." in parts:
            continue
        if any(p.lower().startswith(("license", "copying", "notice")) for p in parts) or str(file).endswith(".dist-info/METADATA"):
            source = Path(dist.locate_file(file))
            target = destination/name/Path(*parts)
            if source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
(destination/"INDEX.txt").write_text("\n".join(index), encoding="utf-8")
