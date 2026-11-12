# Stage contracts

Each stage reads and writes only the files listed here. A replacement
implementation of a stage must produce the same files in the same format;
then nothing else needs to change.

`source/` means `work/sources/<source_id>/`; `short/` means `work/shorts/<short_id>/`.
Times are in seconds from the start of the file.

| Stage | Works on | Reads | Writes |
|---|---|---|---|
| download | source | – (registry record) | `source/source.mp4` |
| transcribe | source | `source/source.mp4` | `source/transcript.json` |
| shots | source | `source/source.mp4` | `source/shots.json` |
| describe | source | source.mp4, shots | `source/shot_descriptions.json` |
| select | source | transcript, shots | `source/candidates.json` |
| script | source | transcript, shots, candidates | `source/scripts.json` |
| check | source | transcript, shots, candidates, scripts | `source/checked.json` |
| narrate | short | `short/script.json` | `short/narration.wav`, `short/narration.json` |
| captions | short | script, narration.wav, narration.json | `short/captions.json`, `short/captions.ass` |
| render | short | source.mp4, shots, script, narration, captions | `short/final.mp4` |
| package | short | final.mp4, script, captions | `short/package.json` (+ files in `output/review/`) |

Short folders are created by `python -m pipeline shorts <source_id>` from every `pass` in checked.json.

## short/script.json
SCRIPT (see scripts.json) plus `"review"` (the deciding review) and `"rewritten"`.

## short/narration.wav / narration.json
WAV, any sample rate, mono. `{"voice", "speed", "duration", "speech_end", "sentences": [{"i", "text", "start", "end"}]}`;
sentence times are where each sentence's speech starts/ends in the WAV.

## short/captions.json / captions.ass
`{"total_duration", "speech_end", "words": [{"text", "s", "e", "sent"}], "groups": [[...]]}`.
`total_duration` is the final video length (narration + end card). captions.ass is a complete
1080x1920 ASS file (captions, header, attribution end card) that render burns in as-is.

## short/final.mp4
1080x1920, 30 fps, H.264 + AAC, exactly `total_duration` long, narration as the only audio.

## output/review/<short_id>.mp4 + .json
Sidecar: `title, description (with attribution, source URL, licence), privacy="private",
duration_seconds, source (registry record), script, scores, review, rewritten, created`.

## source/shot_descriptions.json
`{"source_id", "model": "..." or null, "descriptions": {"<shot i>": "what is on screen"}}` — may be empty
(impl "none"); briefs then show only what is said during each shot.

## Other plug-in kinds (not stages)
- **Finders** `pipeline/discover/finders/<name>.py`: `search(cfg, known_urls) -> (candidates, rejected)`;
  each candidate carries a complete registry record whose licence was verified on the source page.
- **Scorers** `pipeline/discover/scorers/<name>.py`: `score(candidates, cfg) -> {url: {fit, reason, topics}}`.
- **Daily jobs** `pipeline/daily/<name>.py`: `run(ctx)`; listed in `[daily] jobs`.

## source/candidates.json
`{"source_id", "candidates": [{"candidate_id": "c1", "topic", "question", "angle", "start", "end", "visual_evidence", "risks"}]}` — best first.

## source/scripts.json
`{"source_id", "scripts": [SCRIPT]}` where SCRIPT is (format defined in `pipeline/core/script_format.py`):
```json
{"candidate_id": "c1", "source_id": "...", "title": "...", "question": "...",
 "sentences": ["Sentence 0", "Sentence 1"],
 "shots": [{"shot": 37, "sentence": 0, "reason": "..."}],
 "description": "...", "facts": ["..."], "attribution": "(always the registry's attribution_text)",
 "word_count": 130, "est_seconds": 52.0, "footage_seconds": 75.8, "window": [397.0, 445.0]}
```
`shot` refers to `i` in shots.json; `sentence` is a 0-based index into `sentences`.

## source/checked.json
```json
{"source_id": "...", "results": [{
  "candidate_id": "c1", "verdict": "pass | reject", "rewritten": false,
  "script": SCRIPT,
  "first_review":  {"verdict", "model_verdict", "scores": {...6 scores...}, "issues": [], "local": {...}},
  "second_review": {"...only if rewritten..."}}]}
```
Only results with `"verdict": "pass"` may become Shorts.

## source/source.mp4
Any video file FFmpeg can read. Licence must already be approved in the registry.

## source/transcript.json
```json
{
  "source_id": "pre_a_is_for_atom",
  "model": "large-v3-turbo",
  "duration": 866.1,
  "segments": [
    {"start": 92.06, "end": 94.82, "text": "scientists have learned...",
     "words": [{"w": "scientists", "s": 92.06, "e": 92.44}]}
  ]
}
```
Extra keys are allowed; these keys are required.

## source/shots.json
```json
{
  "source_id": "pre_a_is_for_atom",
  "fps": 29.97, "width": 640, "height": 480,
  "shots": [{"i": 0, "start": 0.0, "end": 4.2}]
}
```
Shots are in order, do not overlap, and cover the whole video.

## Rules for every stage
- Write outputs atomically (write a temp file, then rename) so a crash never leaves half a file.
- Scratch files go in `<unit>/_tmp/`.
- Settings come from the stage's block in `pipeline.toml`, passed in as `cfg`.
- The runner checks the source registry before every stage; stages must not download
  or use any video other than their unit's registered source.
