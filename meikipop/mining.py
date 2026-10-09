"""Local Yomitan rendering -> AnkiConnect. No browser database access."""
import copy
import base64
import hashlib
import html
import json
import re
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
            raise MiningError('Yomitan returnerede ikke feltet: ' + key)
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
                raise MiningError('Forbindelsen skal være lokal på denne Mac.')

    def post(self, url, data):
        try:
            response = self.session.post(url, json=data, timeout=(3, 90))
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise MiningError('Kan ikke forbinde. Hold Anki og Brave åbne, og slå Yomitan API til. ' + str(e)) from e
        except ValueError as e:
            raise MiningError('Forbindelsen returnerede ikke gyldig JSON.') from e

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

    def prepare(self, entry):
        frame = getattr(entry, 'mining_window_frame', None)
        if frame is None:
            raise MiningError('Vinduesbilledet mangler. ' + getattr(entry, 'mining_window_error', '') + ' Vælg vindue via menulinjen → Vælg vindue til Anki-billeder, og lav opslaget igen.')
        image_name = 'meikipop_window_' + frame.digest + '.png'

        expected = next(f for f in self.anki_config['cardFormats'] if f['name'] == self.settings['formatName'])
        formats = self.yomitan('ankiCardFormats')
        live = next((f for f in formats if f['name'] == expected['name'] and f.get('type') == 'term'), None)
        if not live or any(live[k] != expected[k] for k in ('deck', 'model', 'fields')):
            raise MiningError('Vælg profilen Bilingual i Yomitan. Hvis felterne er ændret, skal indstillingerne eksporteres igen.')
        templates = live['fields']
        requested = {m for f in templates.values() for m in MARKER.findall(f['value'])}
        local = {'cloze-prefix', 'cloze-body', 'cloze-suffix', 'sentence', 'document-title', 'popup-selection-text'}
        markers = sorted((requested - local) | {'expression', 'reading'})
        payload = self.yomitan('ankiFields', text=entry.written_form or entry.reading,
                              type='term', markers=markers, maxEntries=32, includeMedia=True)
        if not isinstance(payload, dict) or not isinstance(payload.get('fields'), list):
            raise MiningError('Denne Yomitan-version returnerede et ukendt feltformat.')
        selected = None
        for candidate in payload['fields']:
            expression = html.unescape(re.sub('<[^>]*>', '', candidate.get('expression', '')))
            reading = html.unescape(re.sub('<[^>]*>', '', candidate.get('reading', ''))) or expression
            if expression == entry.written_form and reading == (entry.reading or entry.written_form):
                selected = dict(candidate)
                break
        if selected is None:
            raise MiningError('Yomitan fandt ikke præcis det valgte ord og den valgte læsning. Intet kort oprettet.')
        sentence = getattr(entry, 'mining_sentence', entry.written_form)
        offset = getattr(entry, 'mining_offset', 0)
        length = getattr(entry, 'mining_length', len(entry.written_form))
        if not (0 <= offset < len(sentence) and length > 0 and offset + length <= len(sentence)):
            raise MiningError('Ordets placering i OCR-teksten kunne ikke bestemmes.')
        selected.update({'cloze-prefix': html.escape(sentence[:offset]),
                         'cloze-body': html.escape(sentence[offset:offset + length]),
                         'cloze-suffix': html.escape(sentence[offset + length:]),
                         'sentence': html.escape(sentence),
                         'document-title': 'Meikipop', 'popup-selection-text': ''})
        fields = render_fields(templates, selected)
        if not fields.get('MainDefinition', '').strip():
            raise MiningError('Yomitan gav ingen MainDefinition. Kontrollér at Jitendex er aktiveret.')
        if 'Picture' not in fields:
            raise MiningError('Korttypen mangler Picture-feltet.')
        fields['Picture'] = '<img src="' + image_name + '">'
        sentence_audio = getattr(entry, 'mining_sentence_audio', None)
        if sentence_audio:
            if 'SentenceAudio' not in fields:
                raise MiningError('Korttypen mangler SentenceAudio-feltet.')
            audio_name = 'meikipop_sentence_' + hashlib.sha256(sentence_audio).hexdigest() + '.wav'
            fields['SentenceAudio'] = '[sound:' + audio_name + ']'
        actual = self.anki('modelFieldNames' , modelName=live['model'])
        if set(fields) - set(actual):
            raise MiningError('Anki-korttypen mangler felter fra Yomitan-opsætningen.')
        if live['deck'] not in self.anki('deckNames'):
            raise MiningError('Det valgte Anki-deck findes ikke.')
        note = {'deckName': live['deck'], 'modelName': live['model'], 'fields': fields,
                'tags': self.anki_config.get('tags', []),
                'options': {'allowDuplicate': False, 'duplicateScope': self.anki_config.get('duplicateScope', 'collection')}}
        if not self.anki('canAddNotes', notes=[note])[0]:
            raise MiningError('Kortet findes allerede, eller Anki afviser det. Intet kort oprettet.')
        rendered = '\n'.join(fields.values())
        media = [m for key in ('dictionaryMedia', 'audioMedia') for m in payload.get(key, [])
                 if m.get('ankiFilename') and m['ankiFilename'] in rendered]
        if '{audio}' in [f['value'] for f in templates.values()] and not fields.get('ExpressionAudio'):
            raise MiningError('Yomitan fandt ingen lyd til ordet. Intet kort oprettet.')
        media.append({"ankiFilename": image_name, "content": base64.b64encode(frame.png).decode("ascii")})
        if sentence_audio:
            media.append({'ankiFilename': audio_name, 'content': base64.b64encode(sentence_audio).decode('ascii')})
        return note, media

    def add(self, entry):
        note, media = self.prepare(entry)
        for item in media:
            name = item['ankiFilename']
            if Path(name).name != name or not item.get('content'):
                raise MiningError('Ugyldig mediefil fra Yomitan.')
            stored = self.anki('storeMediaFile', filename=name, data=item['content'])
            if stored != name:
                raise MiningError('Anki ændrede mediefilnavnet; kortet blev ikke oprettet.')
        try:
            note_id = self.anki('addNote', note=note)
        except MiningError as e:
            raise MiningError('Tilføjelsen kunne ikke bekræftes. Kontrollér Anki før du prøver igen. ' + str(e)) from e
        if not isinstance(note_id, int):
            raise MiningError('Anki bekræftede ikke kortets oprettelse.')
        return note_id
