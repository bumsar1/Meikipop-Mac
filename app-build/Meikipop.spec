from pathlib import Path
import json
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
src=Path(SPECPATH).parent
data=json.loads((Path(SPECPATH)/'models.json').read_text())
data += [(str(src/'mining-settings.json'),'.'),(str(src/'LICENSE'),'licenses'),(str(Path.home()/'Library/Application Support/meikipop/dictionary.pkl'),'.')]
data += [(str(Path(SPECPATH)/'licenses'), 'licenses/third-party')]
data += collect_data_files('meikipop', include_py_files=True)
hidden=collect_submodules('meikipop') + ['pynput.mouse._darwin','pynput.keyboard._darwin','Quartz','AppKit','Foundation','GameController','ApplicationServices']
a=Analysis([str(Path(SPECPATH)/'launcher.py')], pathex=[str(src)], binaries=[(str(src/'native/GameAudio'), 'native')], datas=data, hiddenimports=hidden, excludes=['torch','tensorflow','matplotlib','pandas','scipy','tkinter','IPython'], noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='Meikipop',debug=False,strip=False,upx=False,console=False,argv_emulation=False,target_arch='arm64')
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='Meikipop')
app=BUNDLE(coll,name='Meikipop.app',icon=str(Path(SPECPATH)/'Meikipop.icns'),bundle_identifier='local.gustav.meikipop',info_plist={'CFBundleDisplayName':'Meikipop','CFBundleShortVersionString':'2.0.5','CFBundleVersion':'20261019.2','CFBundleDevelopmentRegion':'en','CFBundleLocalizations':['en'],'NSHighResolutionCapable':True,'LSUIElement':True,'NSAudioCaptureUsageDescription':'When game audio is enabled, Meikipop keeps a short audio buffer from the selected game for SentenceAudio on your Anki cards.','NSScreenCaptureUsageDescription':'Meikipop reads Japanese text and captures the selected game window for your Anki cards.'})
