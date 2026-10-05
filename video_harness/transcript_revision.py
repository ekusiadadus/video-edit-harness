"""Immutable spelling corrections tied to existing timed word IDs."""

import copy
import re
from pathlib import Path

from .transcript import load_transcript, save_transcript


def _join(words):
    text = ''
    for word in words:
        part = word['text'].strip()
        if text and re.search(r'[A-Za-z0-9]$', text) and re.match(r'[A-Za-z0-9]', part):
            text += ' '
        text += part
    return text


def revise_transcript(input_path, output_folder, changes, actor, note):
    """Correct exact word text while retaining IDs, source, timing and probability.

    changes: [{word_id: existing ID, text: replacement}]. The original sealed
    transcript and its semantic response remain referenced in revision_history.
    """
    if not isinstance(actor, str) or not actor.strip() or not isinstance(note, str) or not note.strip():
        raise ValueError('Correction requires actor and note')
    if not isinstance(changes, list) or not changes:
        raise ValueError('Correction requires word changes')
    original = load_transcript(input_path)
    result = copy.deepcopy(original)
    word_by_id = {word['id']: word for word in result['words']}
    seen = set()
    audit = []
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError('Invalid word correction')
        word_id = change.get('word_id')
        if word_id not in word_by_id or word_id in seen:
            raise ValueError('Unknown or duplicate correction word id')
        replacement = change.get('text')
        if not isinstance(replacement, str) or not replacement.strip() or replacement != replacement.strip():
            raise ValueError('Invalid correction text')
        word = word_by_id[word_id]
        if replacement == word['text']:
            raise ValueError('Correction must change word text')
        seen.add(word_id)
        audit.append({'word_id': word_id, 'before': word['text'], 'after': replacement,
                      'start': word['start'], 'end': word['end']})
        word['text'] = replacement
    previous_semantic = original.get('semantic_text')
    result['semantic_text'] = _join(result['words'])
    result['semantic_text_provenance'] = 'derived_from_corrected_timed_words'
    for segment in result['segments']:
        included = [word for word in result['words'] if segment['start'] <= word['start'] and word['end'] <= segment['end']]
        if included:
            segment['text'] = _join(included)
        else:
            result['warnings'].append(f"Segment {segment['id']} has no fully aligned words; text retained for review")
    history = result.setdefault('revision_history', [])
    history.append({'parent_result_sha256': original['result_sha256'],
                    'parent_path': str(Path(input_path).resolve()),
                    'actor': actor, 'note': note, 'changes': audit,
                    'previous_semantic_text': previous_semantic})
    result['warnings'].append('Corrected text uses existing timed word anchors; verify semantic alignment and pronunciation')
    return save_transcript(output_folder, result)
