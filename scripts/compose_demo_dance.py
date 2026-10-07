"""Render a reproducible sample-free synth-pop/garage demo, not an artist imitation.

Usage: uv run --no-sync python scripts/compose_demo_dance.py OUTPUT_DIRECTORY
This is procedural synthesis, not a hosted AI music service. No external audio.
"""
from pathlib import Path
import json
import sys
import wave

import numpy as np


def compose(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rate, bpm, bars = 48000, 138, 16
    beat = 60 / bpm
    audio = np.zeros((int((bars * 4 * beat + .8) * rate), 2))
    rng = np.random.default_rng(20261007)
    notes = []

    def add(start, sound, pan=0):
        first = round(start * rate)
        count = min(len(sound), len(audio) - first)
        audio[first:first+count, 0] += sound[:count] * np.sqrt((1-pan)/2)
        audio[first:first+count, 1] += sound[:count] * np.sqrt((1+pan)/2)

    def tone(midi, duration, kind, level):
        t = np.arange(round(duration*rate))/rate
        frequency = 440 * 2 ** ((midi-69)/12)
        if kind == 'bass':
            y = np.sin(2*np.pi*frequency*t) + .25*np.sin(4*np.pi*frequency*t)
            envelope = np.minimum(t/.008, 1)*np.exp(-t/0.22)
        else:
            y = sum(np.sin(2*np.pi*frequency*(1+detune)*t + phase)/harmonic
                    for harmonic, detune, phase in [(1, -.002, 0), (2, .001, .3), (3, 0, .1)])
            envelope = np.minimum(t/.006, 1)*np.exp(-t/.115)
        return level*y*envelope*np.minimum((duration-t)/.025, 1)

    progression = [[54, 57, 61, 64], [50, 54, 57, 61], [57, 61, 64, 68], [52, 56, 59, 62]]
    kick_t = np.arange(round(.28*rate))/rate
    kick = .7*np.sin(2*np.pi*(47*kick_t + 65*.025*(1-np.exp(-kick_t/.025))))*np.exp(-kick_t/.065)
    snare_t = np.arange(round(.15*rate))/rate
    noise = rng.normal(0, 1, len(snare_t))
    snare = .19*(noise-np.roll(noise, 1))*np.exp(-snare_t/.027)+.12*np.sin(2*np.pi*185*snare_t)*np.exp(-snare_t/.035)
    hat_t = np.arange(round(.045*rate))/rate
    noise = rng.normal(0, 1, len(hat_t))
    hat = .026*(noise-np.roll(noise, 1))*np.exp(-hat_t/.011)
    for bar in range(bars):
        origin = bar*4*beat
        chord = progression[bar % 4]
        for b in (0, 1.5, 2, 2.75, 3.5):
            add(origin+b*beat, kick)
            notes.append({'instrument': 'kick', 'beat': bar*4+b})
        for b in (1, 3):
            add(origin+b*beat, snare)
        for step in range(8):
            add(origin+(step*.5 + (.065 if step % 2 else 0))*beat, hat, .25*(-1)**step)
        for b in (0, .75, 1.5, 2.5, 3.25):
            add(origin+b*beat, tone(chord[0]-12, .3, 'bass', .24))
        for step in (0, 3, 6, 8, 11, 14):
            for note in chord:
                add(origin+step*.25*beat, tone(note+12, .4, 'pluck', .07), .35 if note%2 else -.35)
        if bar >= 4:
            for step, index in enumerate((3, 2, 1, 2, 3, 1, 0, 2)):
                add(origin+(step*.5+.25)*beat, tone(chord[index]+24, .22, 'pluck', .065), .12)
    audio *= np.minimum(np.arange(len(audio))/rate/.015, 1)[:, None]
    audio *= np.minimum((len(audio)-np.arange(len(audio)))/rate/.6, 1)[:, None]
    audio /= max(1, np.max(np.abs(audio))/.85)
    path = folder/'neon-steps-138.wav'
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(2); stream.setsampwidth(2); stream.setframerate(rate)
        stream.writeframes((audio*32767).astype('<i2').tobytes())
    (folder/'composition.json').write_text(json.dumps({'title': 'Neon Steps', 'bpm': bpm,
        'bars': bars, 'sample_rate': rate, 'seed': 20261007, 'method': 'procedural oscillator/noise synthesis',
        'external_samples': False, 'artist_imitation': False, 'human_listening_review': False,
        'beat_grid_is_score_not_measured_audio_onsets': True, 'kick_events': notes}, indent=2))
    return path


if __name__ == '__main__':
    print(compose(sys.argv[1]))
