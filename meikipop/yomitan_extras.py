# meikipop/yomitan_extras.py
"""Frequency lists and inflection explanations from the user's own Yomitan dictionaries.

Asked from the Lookup thread through the local Yomitan API (~25 ms), so the popup is drawn once
with everything. When Yomitan is not running, lookups carry on without these extras.
"""
import json
import logging
import threading
import time
from collections import OrderedDict

from meikipop.config.config import config

logger = logging.getLogger(__name__)

TIMEOUT = (0.15, 0.6)       # connect, read (seconds): never hold up a lookup for long
OFFLINE_RETRY_SECONDS = 10  # after a failure, skip Yomitan for a while instead of waiting each time
CACHE_SIZE = 300


class YomitanExtras:
    def __init__(self):
        self._session = None
        self._url = None
        self._cache = OrderedDict()
        self._offline_until = 0.0
        self._lock = threading.Lock()

    def _endpoint(self):
        if self._url is None:
            import requests
            from meikipop.mining import SETTINGS
            server = json.loads(SETTINGS.read_text())['yomitanServer'].rstrip('/')
            self._session = requests.Session()
            self._session.trust_env = False
            self._url = server + '/termEntries'
        return self._url

    def fetch(self, text):
        """{(term, reading): {'frequencies': [(dictionary, 'v1, v2')], 'inflections': [[(name, description)]]}}"""
        with self._lock:
            if text in self._cache:
                self._cache.move_to_end(text)
                return self._cache[text]
        if time.monotonic() < self._offline_until:
            return {}
        try:
            response = self._session_post(text)
            result = parse_term_entries(response)
        except Exception as e:
            logger.debug("Yomitan extras unavailable: %s", e)
            self._offline_until = time.monotonic() + OFFLINE_RETRY_SECONDS
            return {}
        with self._lock:
            self._cache[text] = result
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return result

    def _session_post(self, text):
        url = self._endpoint()
        r = self._session.post(url, json={'term': text}, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    def attach(self, entries, text):
        """Adds .yomitan_frequencies / .yomitan_inflections to matching DictionaryEntry objects."""
        if not entries or not (config.show_frequency_lists or config.show_inflections):
            return
        from meikipop.dictionary.lookup import DictionaryEntry
        words = [e for e in entries if isinstance(e, DictionaryEntry)]
        if not words:
            return
        extras = self.fetch(str(text)[:config.max_lookup_length])
        for entry in words:
            found = extras.get((entry.written_form, entry.reading or entry.written_form))
            if found:
                entry.yomitan_frequencies = found['frequencies']
                entry.yomitan_inflections = found['inflections']


def parse_term_entries(payload):
    result = {}
    for d in (payload or {}).get('dictionaryEntries', []):
        chains = []
        for candidate in d.get('inflectionRuleChainCandidates') or []:
            chain = [(r.get('name', ''), r.get('description', '')) if isinstance(r, dict) else (str(r), '')
                     for r in candidate.get('inflectionRules') or []]
            if chain and chain not in chains:
                chains.append(chain)
        for h, headword in enumerate(d.get('headwords', [])):
            key = (headword.get('term', ''), headword.get('reading') or headword.get('term', ''))
            item = result.setdefault(key, {'frequencies': OrderedDict(), 'inflections': []})
            for f in d.get('frequencies', []):
                if f.get('headwordIndex', 0) != h:
                    continue
                value = f.get('displayValue') or str(f.get('frequency', ''))
                values = item['frequencies'].setdefault(f.get('dictionaryAlias') or f.get('dictionary', '?'), [])
                if value and value not in values:
                    values.append(value)
            for chain in chains:
                if chain not in item['inflections']:
                    item['inflections'].append(chain)
    return {key: {'frequencies': [(name, ', '.join(v)) for name, v in item['frequencies'].items() if v],
                  'inflections': item['inflections']}
            for key, item in result.items()}
