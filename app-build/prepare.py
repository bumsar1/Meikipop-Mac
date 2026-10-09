from pathlib import Path
from PIL import Image
from huggingface_hub import hf_hub_download
import json
build=Path(__file__).resolve().parent; src=build.parent
Image.open(src/'meikipop/resources/icon.ico').save(build/'Meikipop.icns')
models=[]
for repo,name in [('rtr46/meiki.text.detect.v0','meiki.text.detect.v0.1.960x544.onnx'),('rtr46/meiki.txt.recognition.v0','meiki.text.rec.v0.960x32.onnx'),('rtr46/meiki.txt.recognition.v0','meiki.text.rec.v0.vertical.32x480.onnx')]:
    models.append((hf_hub_download(repo, name, local_files_only=True),'models'))
(build/'models.json').write_text(json.dumps(models))
print([(Path(p).stat().st_size,d) for p,d in models])

import importlib.metadata as md
import shutil
licenses=build/'licenses'; licenses.mkdir(exist_ok=True)
for dist in md.distributions():
    for f in dist.files or []:
        if 'dist-info' not in str(f) or not any(x in f.name.lower() for x in ['license','copying','notice']):
            continue
        p=Path(dist.locate_file(f))
        if p.is_file():
            dest=licenses/dist.metadata['Name']/str(f).split('.dist-info/',1)[-1]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p,dest)
