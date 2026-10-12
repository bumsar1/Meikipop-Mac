# meikipop/dictionary/user_dicts.py
"""Extra Yomitan dictionaries layered on top of the main dictionary.pkl."""
import json
import logging
import os
import pickle
import re
import zipfile

from meikipop.utils.paths import paths

logger = logging.getLogger(__name__)

USER_DICT_DIR = os.path.join(paths.data_dir, 'user_dicts')
# Main dictionary IDs are JMdict sequence numbers (< 10M); user dicts sit far above them.
USER_ID_BASE = 2_000_000_000
USER_ID_STRIDE = 100_000_000


def list_user_dicts():
    """[(path, title, entry_count)] in load order."""
    if not os.path.isdir(USER_DICT_DIR):
        return []
    result = []
    for name in sorted(os.listdir(USER_DICT_DIR)):
        if not name.endswith('.pkl'):
            continue
        path = os.path.join(USER_DICT_DIR, name)
        meta = _read_meta(path)
        result.append((path, meta.get('title', name[:-4]), meta.get('entries', 0)))
    return result


def _read_meta(path):
    try:
        with open(path[:-4] + '.json', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def import_zip(zip_path, progress=lambda text: None):
    """Convert a Yomitan term dictionary .zip into a user dictionary; returns its title."""
    from meikipop.scripts.import_yomitan_dict_text import build_from_zip
    with zipfile.ZipFile(zip_path) as zf:
        try:
            with zf.open('index.json') as f:
                title = json.load(f).get('title') or os.path.basename(zip_path)
        except KeyError:
            raise ValueError('This is not a Yomitan dictionary (index.json is missing).')
        if not any(re.match(r'term_bank_\d+\.json', os.path.basename(n)) for n in zf.namelist()):
            raise ValueError(f'"{title}" has no word entries. Kanji and frequency-only dictionaries are not supported.')
        if any(t == title for _, t, _ in list_user_dicts()):
            raise ValueError(f'"{title}" is already installed.')
        progress(f'Reading {title}…')
        entries, lookup_map = build_from_zip(zf, dict_index=0, freq_override={})
    if not entries:
        raise ValueError(f'"{title}" contains no definitions that Meikipop can show.')
    for senses in entries.values():
        for sense in senses:
            sense['dict'] = title
    os.makedirs(USER_DICT_DIR, exist_ok=True)
    existing = [int(n[:3]) for n in os.listdir(USER_DICT_DIR) if re.match(r'\d{3}-.*\.pkl$', n)]
    slot = max(existing, default=0) + 1
    slug = re.sub(r'[^\w]+', '_', title).strip('_')[:40] or 'dictionary'
    path = os.path.join(USER_DICT_DIR, f'{slot:03d}-{slug}.pkl')
    progress(f'Saving {title}…')
    with open(path + '.tmp', 'wb') as f:
        pickle.dump({'entries': entries, 'lookup_map': dict(lookup_map)}, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(path + '.tmp', path)
    with open(path[:-4] + '.json', 'w', encoding='utf-8') as f:
        json.dump({'title': title, 'entries': len(entries), 'source': os.path.basename(zip_path)}, f, ensure_ascii=False)
    logger.info('Installed user dictionary %s (%d entries)', title, len(entries))
    return title


def remove(path):
    for p in (path, path[:-4] + '.json'):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass


def merge_into(dictionary):
    """Add every installed user dictionary to a loaded Dictionary, after the main entries."""
    for n, (path, title, _) in enumerate(list_user_dicts()):
        try:
            with open(path, 'rb') as f:
                data = pickle.load(f)
        except Exception as e:
            logger.error('Skipping user dictionary %s: %s', title, e)
            continue
        offset = USER_ID_BASE + n * USER_ID_STRIDE
        for entry_id, senses in data['entries'].items():
            dictionary.entries[entry_id + offset] = senses
        for surface, refs in data['lookup_map'].items():
            target = dictionary.lookup_map.setdefault(surface, [])
            target.extend((w, r, freq, entry_id + offset) for w, r, freq, entry_id in refs)
        logger.info('Loaded user dictionary %s', title)
