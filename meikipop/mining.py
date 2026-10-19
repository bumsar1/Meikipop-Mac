"""Local Yomitan rendering -> AnkiConnect. No browser database access."""
import copy
import base64
import hashlib
import html
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse
import requests

SETTINGS = Path(__file__).resolve().parent.parent / 'mining-settings.json'
MARKER = re.compile(r'\{([^{}]+)\}')

class MiningError(RuntimeError):
    pass

class MiningText(str):
    def __new__(cls, text, sentence, offset, window_frame=None, window_error=""):
        obj = super().__new__(cls, text)
        obj.sentence, obj.offset = sentence, offset
        obj.window_frame, obj.window_error = window_frame, window_error
        return obj


def attach_context(entries, text):
    # Never mutate cached DictionaryEntry instances: each displayed result owns its context.
    result = copy.deepcopy(entries)
    for entry in result or []:
        entry.mining_sentence = getattr(text, 'sentence', str(text))
        entry.mining_offset = getattr(text, 'offset', 0)
        entry.mining_window_frame = getattr(text, 'window_frame', None)
        entry.mining_window_error = getattr(text, 'window_error', '')
    return result


def render_fields(templates, values):
    def replace(match):
        key = match.group(1)
        if key not in values:
            raise MiningError('Yomitan did not return the field: ' + key)
        return str(values[key])
    return {name: MARKER.sub(replace, spec['value']) for name, spec in templates.items()}


class Miner:
    def __init__(self, settings=None):
        self.settings = settings or json.loads(SETTINGS.read_text())
        self.anki_config = self.settings['anki']
        self.session = requests.Session()
        self.session.trust_env = False
        for endpoint in [self.settings['yomitanServer'], self.anki_config['server']]:
            u = urlparse(endpoint)
            if u.scheme != 'http' or u.hostname not in ('127.0.0.1', 'localhost', '::1'):
                raise MiningError('The connection must be local to this Mac.')

    def post(self, url, data):
        try:
            response = self.session.post(url, json=data, timeout=getattr(self, 'timeout', (3, 90)))
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise MiningError('Cannot connect. Keep Anki and Brave open, and enable Yomitan API. ' + str(e)) from e
        except ValueError as e:
            raise MiningError('The connection did not return valid JSON.') from e

    def anki(self, action, **params):
        request = {'action': action, 'version': 6, 'params': params}
        if self.anki_config.get('apiKey'):
            request['key'] = self.anki_config['apiKey']
        result = self.post(self.anki_config['server'], request)
        if result.get('error'):
            raise MiningError('Anki: ' + str(result['error']))
        return result['result']

    def yomitan(self, action, **params):
        return self.post(self.settings['yomitanServer'].rstrip('/') + '/' + action, params)

    def word_exists(self, word):
        card = next(f for f in self.anki_config['cardFormats'] if f['name'] == self.settings['formatName'])
        fields = [name for name, spec in card['fields'].items() if spec['value'] == '{expression}']
        if len(fields) != 1 or not word:
            raise MiningError('Cannot determine the expression field for Anki checks.')
        def quote(value):
            # Escape Anki search syntax; field searches match the complete value.
            value = value.replace(chr(92), chr(92) * 2)
            for char in ('"', '*', '_'):
                value = value.replace(char, chr(92) + char)
            return '"' + value + '"'
        query = quote('deck:' + card['deck']) + ' ' + quote(fields[0] + ':' + word)
        result = self.anki('findNotes', query=query)
        if not isinstance(result, list):
            raise MiningError('Anki returned an invalid presence result.')
        return bool(result)

    def prepare(self, entry):
        frame = getattr(entry, 'mining_window_frame', None)
        if frame is None:
            raise MiningError('The window screenshot is missing. ' + getattr(entry, 'mining_window_error', '') + ' Select a window from the menu bar → Select Window for Anki Screenshots, then look up the word again.')
        image_data, extension = frame.card_image()
        image_name = 'meikipop_window_' + hashlib.sha256(image_data).hexdigest() + '.' + extension

        expected = next(f for f in self.anki_config['cardFormats'] if f['name'] == self.settings['formatName'])
        formats = self.yomitan('ankiCardFormats')
        live = next((f for f in formats if f['name'] == expected['name'] and f.get('type') == 'term'), None)
        if not live or any(live[k] != expected[k] for k in ('deck', 'model', 'fields')):
            raise MiningError('Select the Bilingual profile in Yomitan. If the fields have changed, export the settings again.')
        templates = live['fields']
        requested = {m for f in templates.values() for m in MARKER.findall(f['value'])}
        local = {'cloze-prefix', 'cloze-body', 'cloze-suffix', 'sentence', 'document-title', 'popup-selection-text'}
        markers = sorted((requested - local) | {'expression', 'reading'})
        payload = self.yomitan('ankiFields', text=entry.written_form or entry.reading,
                              type='term', markers=markers, maxEntries=32, includeMedia=True)
        if not isinstance(payload, dict) or not isinstance(payload.get('fields'), list):
            raise MiningError('This Yomitan version returned an unknown field format.')
        selected = None
        for candidate in payload['fields']:
            expression = html.unescape(re.sub('<[^>]*>', '', candidate.get('expression', '')))
            reading = html.unescape(re.sub('<[^>]*>', '', candidate.get('reading', ''))) or expression
            if expression == entry.written_form and reading == (entry.reading or entry.written_form):
                selected = dict(candidate)
                break
        if selected is None:
            raise MiningError('Yomitan did not find the exact selected word and reading. No card was created.')
        sentence = getattr(entry, 'mining_sentence', entry.written_form)
        offset = getattr(entry, 'mining_offset', 0)
        length = getattr(entry, 'mining_length', len(entry.written_form))
        if not (0 <= offset < len(sentence) and length > 0 and offset + length <= len(sentence)):
            raise MiningError('Could not determine the position of the word in the OCR text.')
        selected.update({'cloze-prefix': html.escape(sentence[:offset]),
                         'cloze-body': html.escape(sentence[offset:offset + length]),
                         'cloze-suffix': html.escape(sentence[offset + length:]),
                         'sentence': html.escape(sentence),
                         'document-title': 'Meikipop', 'popup-selection-text': ''})
        fields = render_fields(templates, selected)
        if not fields.get('MainDefinition', '').strip():
            raise MiningError('Yomitan returned no MainDefinition. Check that Jitendex is enabled.')
        if 'Picture' not in fields:
            raise MiningError('The note type is missing the Picture field.')
        fields['Picture'] = '<img src="' + image_name + '">'
        sentence_audio = getattr(entry, 'mining_sentence_audio', None)
        if sentence_audio:
            if 'SentenceAudio' not in fields:
                raise MiningError('The note type is missing the SentenceAudio field.')
            audio_name = 'meikipop_sentence_' + hashlib.sha256(sentence_audio).hexdigest() + '.wav'
            fields['SentenceAudio'] = '[sound:' + audio_name + ']'
        actual = self.anki('modelFieldNames' , modelName=live['model'])
        if set(fields) - set(actual):
            raise MiningError('The Anki note type is missing fields from the Yomitan configuration.')
        if live['deck'] not in self.anki('deckNames'):
            raise MiningError('The selected Anki deck does not exist.')
        note = {'deckName': live['deck'], 'modelName': live['model'], 'fields': fields,
                'tags': self.anki_config.get('tags', []),
                'options': {'allowDuplicate': False, 'duplicateScope': self.anki_config.get('duplicateScope', 'collection')}}
        if not self.anki('canAddNotes', notes=[note])[0]:
            raise MiningError('The card already exists or Anki rejected it. No card was created.')
        rendered = '\n'.join(fields.values())
        media = [m for key in ('dictionaryMedia', 'audioMedia') for m in payload.get(key, [])
                 if m.get('ankiFilename') and m['ankiFilename'] in rendered]
        if '{audio}' in [f['value'] for f in templates.values()] and not fields.get('ExpressionAudio'):
            raise MiningError('Yomitan found no audio for the word. No card was created.')
        media.append({"ankiFilename": image_name, "content": base64.b64encode(image_data).decode("ascii")})
        if sentence_audio:
            media.append({'ankiFilename': audio_name, 'content': base64.b64encode(sentence_audio).decode('ascii')})
        return note, media

    ANKI_BUNDLE_ID = 'net.ankiweb.dtop'
    ANKI_START_TIMEOUT = 45  # seconds; Anki can take a while to open a large collection

    def ensure_anki(self, progress=lambda text: None):
        """Start Anki in the background when it is closed, then wait until AnkiConnect answers."""
        try:
            self.anki('version')
            return
        except MiningError as e:
            if not isinstance(e.__cause__, requests.ConnectionError):
                raise
        progress('Anki was closed. Starting Anki…')
        import subprocess
        # -g: open in the background, so a full-screen game keeps the screen.
        if subprocess.run(['/usr/bin/open', '-g', '-b', self.ANKI_BUNDLE_ID], capture_output=True).returncode != 0:
            raise MiningError('Anki is closed and could not be started. Open Anki and try again.')
        deadline = time.monotonic() + self.ANKI_START_TIMEOUT
        while time.monotonic() < deadline:
            time.sleep(1)
            try:
                self.anki('version')
                progress('Anki started. Adding the card…')
                return
            except MiningError:
                continue
        raise MiningError('Anki started, but AnkiConnect did not answer. Check that AnkiConnect is installed, then try again.')

    def add(self, entry, progress=lambda text: None):
        self.ensure_anki(progress)
        if self.word_exists(entry.written_form or entry.reading):
            raise MiningError('Already in your Anki deck. No card was created.')
        note, media = self.prepare(entry)
        for item in media:
            name = item['ankiFilename']
            if Path(name).name != name or not item.get('content'):
                raise MiningError('Invalid media file from Yomitan.')
            stored = self.anki('storeMediaFile', filename=name, data=item['content'])
            if stored != name:
                raise MiningError('Anki changed the media filename; the card was not created.')
        try:
            note_id = self.anki('addNote', note=note)
        except MiningError as e:
            raise MiningError('Could not confirm the addition. Check Anki before trying again. ' + str(e)) from e
        if not isinstance(note_id, int):
            raise MiningError('Anki did not confirm that the card was created.')
        return note_id
