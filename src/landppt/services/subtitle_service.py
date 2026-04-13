"""
Subtitle generation utilities (SRT).

MVP:
- Build sentence/chunk-level cues inside each slide's audio duration.
- Default style is handled by ffmpeg burn-in (alignment=bottom-center, single line).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Tuple


@dataclass(frozen=True)
class SubtitleCue:
    start_ms: int
    end_ms: int
    text: str


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[\u3002\uff01\uff1f.!?;\uff1b])\s*")
_CHUNK_SPLIT_RE = re.compile(r"(?<=[\uff0c,\u3001\uff1b;:\uff1a])\s*")
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’_-][A-Za-z0-9]+)*")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_COMMA_PAUSE_RE = re.compile(r"[\uff0c,\u3001\uff1b;:\uff1a]")
_SENTENCE_PAUSE_RE = re.compile(r"[\u3002\uff01\uff1f.!?]")


def _ms_to_srt_timestamp(ms: int) -> str:
    ms = max(0, int(ms))
    hours, rem = divmod(ms, 3600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _clean_subtitle_text(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("\u00a0", " ")
    return text.strip()


def _split_sentences(text: str) -> List[str]:
    text = _clean_subtitle_text(text)
    if not text:
        return []
    parts = _SENTENCE_SPLIT_RE.split(text)
    parts = [_clean_subtitle_text(p) for p in parts if _clean_subtitle_text(p)]
    return parts or [text]


def _chunk_single_line(text: str, *, max_chars: int = 36) -> List[str]:
    """
    Ensure single-line cues by chunking long sentences.
    For Chinese, char count works reasonably; for English, also acceptable for MVP.
    """
    text = _clean_subtitle_text(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    split_parts = _CHUNK_SPLIT_RE.split(text)
    split_parts = [_clean_subtitle_text(p) for p in split_parts if _clean_subtitle_text(p)]
    if not split_parts:
        split_parts = [text]

    chunks: List[str] = []
    buf = ""
    for part in split_parts:
        if not buf:
            buf = part
            continue
        candidate = f"{buf} {part}".strip()
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            if buf:
                chunks.append(_clean_subtitle_text(buf))
            buf = part
    if buf:
        chunks.append(_clean_subtitle_text(buf))

    final: List[str] = []
    for c in chunks:
        if len(c) <= max_chars:
            final.append(c)
            continue
        start = 0
        while start < len(c):
            end = min(len(c), start + max_chars)
            piece = _clean_subtitle_text(c[start:end])
            if piece:
                final.append(piece)
            start = end
    return final


def _estimate_text_weight(text: str) -> float:
    text = _clean_subtitle_text(text)
    if not text:
        return 1.0

    cjk_count = len(_CJK_RE.findall(text))
    word_count = len(_WORD_RE.findall(text))
    comma_pauses = len(_COMMA_PAUSE_RE.findall(text))
    sentence_pauses = len(_SENTENCE_PAUSE_RE.findall(text))

    text_wo_words = _WORD_RE.sub("", text)
    other_symbols = len(re.findall(r"[^\s]", text_wo_words)) - cjk_count - comma_pauses - sentence_pauses
    other_symbols = max(0, other_symbols)

    units = (
        cjk_count * 1.0
        + word_count * 2.2
        + other_symbols * 0.35
        + comma_pauses * 1.1
        + sentence_pauses * 2.0
    )
    return max(1.0, float(units))


def _allocate_weighted_durations(total_ms: int, weights: List[float]) -> List[int]:
    total_ms = max(1, int(total_ms))
    if not weights:
        return []
    if len(weights) == 1:
        return [total_ms]

    count = len(weights)
    safe_weights = [max(0.01, float(w or 0.0)) for w in weights]
    avg_budget = total_ms / count
    min_cue_ms = int(avg_budget * 0.45)
    min_cue_ms = max(160, min(650, min_cue_ms))
    min_cue_ms = min(min_cue_ms, max(80, total_ms // count))

    base = [min_cue_ms] * count
    remaining = total_ms - (min_cue_ms * count)
    if remaining < 0:
        weight_sum = sum(safe_weights) or 1.0
        proportional = [total_ms * (w / weight_sum) for w in safe_weights]
        durations = [max(1, int(x)) for x in proportional]
        durations[-1] = max(1, durations[-1] + (total_ms - sum(durations)))
        return durations

    weight_sum = sum(safe_weights) or 1.0
    raw_extras = [remaining * (w / weight_sum) for w in safe_weights]
    extras = [int(x) for x in raw_extras]
    drift = remaining - sum(extras)
    if drift > 0:
        order = sorted(
            range(count),
            key=lambda idx: (raw_extras[idx] - extras[idx], safe_weights[idx]),
            reverse=True,
        )
        for idx in order[:drift]:
            extras[idx] += 1

    durations = [base_ms + extra_ms for base_ms, extra_ms in zip(base, extras)]
    durations[-1] = max(1, durations[-1] + (total_ms - sum(durations)))
    return durations


def _boundary_cost(candidate_ms: int, desired_ms: int, tolerance_ms: int) -> int:
    dist = abs(int(candidate_ms) - int(desired_ms))
    if dist <= tolerance_ms:
        return dist * dist
    over = dist - tolerance_ms
    return (tolerance_ms * tolerance_ms) + (over * over * 6)


def _select_boundary_sequence(
    *,
    desired_boundaries_ms: List[int],
    candidate_boundaries_ms: List[int],
    start_ms: int,
    end_ms: int,
    min_gap_ms: int,
    tolerance_ms: int,
) -> List[int]:
    desired = [int(x) for x in desired_boundaries_ms if start_ms + min_gap_ms < int(x) < end_ms - min_gap_ms]
    candidates = sorted(
        set(
            int(x)
            for x in candidate_boundaries_ms
            if start_ms + min_gap_ms < int(x) < end_ms - min_gap_ms
        )
    )
    need = len(desired)
    if need == 0 or len(candidates) < need:
        return []

    inf = 10**18
    cand_count = len(candidates)
    dp = [[inf] * cand_count for _ in range(need)]
    prev_idx = [[-1] * cand_count for _ in range(need)]

    for j, candidate in enumerate(candidates):
        if cand_count - (j + 1) < need - 1:
            continue
        dp[0][j] = _boundary_cost(candidate, desired[0], tolerance_ms)

    for i in range(1, need):
        remaining_needed = need - i - 1
        for j in range(i, cand_count):
            candidate = candidates[j]
            if cand_count - (j + 1) < remaining_needed:
                continue
            best_cost = inf
            best_prev = -1
            for p in range(i - 1, j):
                prev_candidate = candidates[p]
                if candidate - prev_candidate < min_gap_ms:
                    continue
                prev_cost = dp[i - 1][p]
                if prev_cost >= inf:
                    continue
                cost = prev_cost + _boundary_cost(candidate, desired[i], tolerance_ms)
                if cost < best_cost:
                    best_cost = cost
                    best_prev = p
            dp[i][j] = best_cost
            prev_idx[i][j] = best_prev

    last_i = need - 1
    best_j = -1
    best_cost = inf
    for j in range(last_i, cand_count):
        if dp[last_i][j] < best_cost:
            best_cost = dp[last_i][j]
            best_j = j
    if best_j < 0 or best_cost >= inf:
        return []

    chosen = [0] * need
    cur_j = best_j
    for i in range(last_i, -1, -1):
        chosen[i] = candidates[cur_j]
        cur_j = prev_idx[i][cur_j]
    return chosen


def build_slide_cues(
    *,
    slide_text: str,
    slide_start_ms: int,
    slide_duration_ms: int,
    max_chars_per_line: int = 36,
) -> List[SubtitleCue]:
    slide_start_ms = int(slide_start_ms)
    slide_duration_ms = max(250, int(slide_duration_ms))

    sentences: List[str] = []
    for s in _split_sentences(slide_text):
        sentences.extend(_chunk_single_line(s, max_chars=max_chars_per_line))

    sentences = [s for s in sentences if s]
    if not sentences:
        return []

    if len(sentences) == 1 and len(sentences[0]) > max_chars_per_line:
        sentences = _chunk_single_line(sentences[0], max_chars=max_chars_per_line)

    weights = [_estimate_text_weight(s) for s in sentences]
    allocated = _allocate_weighted_durations(slide_duration_ms, weights)

    cues: List[SubtitleCue] = []
    cur = slide_start_ms
    for text, dur in zip(sentences, allocated):
        start = cur
        end = min(slide_start_ms + slide_duration_ms, cur + dur)
        if end - start < 120:
            continue
        cues.append(SubtitleCue(start_ms=start, end_ms=end, text=text))
        cur = end
    return cues


def build_slide_cues_snapped(
    *,
    slide_text: str,
    slide_start_ms: int,
    slide_duration_ms: int,
    boundary_mids_ms: List[int],
    max_chars_per_line: int = 36,
    snap_tolerance_ms: int = 800,
) -> List[SubtitleCue]:
    """
    Build cues and snap cue boundaries to detected pause boundaries (e.g. silence midpoints).
    boundary_mids_ms are relative to the slide (0..duration).
    """
    cues = build_slide_cues(
        slide_text=slide_text,
        slide_start_ms=slide_start_ms,
        slide_duration_ms=slide_duration_ms,
        max_chars_per_line=max_chars_per_line,
    )
    if len(cues) <= 1:
        return cues

    if not boundary_mids_ms:
        return cues

    slide_start_ms = int(slide_start_ms)
    slide_end_ms = slide_start_ms + max(0, int(slide_duration_ms))
    candidates = []
    for b in boundary_mids_ms:
        try:
            b = int(b)
        except Exception:
            continue
        if b <= 0 or b >= int(slide_duration_ms):
            continue
        candidates.append(slide_start_ms + b)
    if not candidates:
        return cues
    candidates = sorted(set(candidates))

    desired_boundaries = [cue.end_ms for cue in cues[:-1]]
    selected_boundaries = _select_boundary_sequence(
        desired_boundaries_ms=desired_boundaries,
        candidate_boundaries_ms=candidates,
        start_ms=slide_start_ms,
        end_ms=slide_end_ms,
        min_gap_ms=220,
        tolerance_ms=max(100, int(snap_tolerance_ms)),
    )

    prev_boundary = cues[0].start_ms
    snapped: List[SubtitleCue] = []
    for idx in range(len(cues)):
        cue = cues[idx]
        start_ms = prev_boundary
        if idx == len(cues) - 1:
            snapped.append(
                SubtitleCue(
                    start_ms=start_ms,
                    end_ms=slide_end_ms,
                    text=cue.text,
                )
            )
            break

        desired_end = cue.end_ms
        best = selected_boundaries[idx] if idx < len(selected_boundaries) else None
        if best is None:
            best_dist = None
            for c in candidates:
                if c <= prev_boundary + 220:
                    continue
                if c >= slide_end_ms - 220:
                    continue
                dist = abs(c - desired_end)
                if dist <= snap_tolerance_ms and (best_dist is None or dist < best_dist):
                    best = c
                    best_dist = dist

        end_ms = best if best is not None else desired_end
        if end_ms - max(cue.start_ms, prev_boundary) < 200:
            end_ms = min(slide_end_ms - 250, max(cue.start_ms, prev_boundary) + 200)

        snapped.append(
            SubtitleCue(
                start_ms=start_ms,
                end_ms=end_ms,
                text=cue.text,
            )
        )
        prev_boundary = end_ms

    if snapped:
        last = snapped[-1]
        if last.end_ms < slide_end_ms:
            snapped[-1] = SubtitleCue(start_ms=last.start_ms, end_ms=slide_end_ms, text=last.text)
    return snapped


def build_srt(cues: Iterable[SubtitleCue]) -> str:
    lines: List[str] = []
    for idx, cue in enumerate(cues, start=1):
        start = _ms_to_srt_timestamp(cue.start_ms)
        end = _ms_to_srt_timestamp(max(cue.end_ms, cue.start_ms + 1))
        text = _clean_subtitle_text(cue.text)
        if not text:
            continue
        lines.append(str(idx))
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_srt_for_slides(
    *,
    slides: List[Tuple[str, int]],
    max_chars_per_line: int = 36,
) -> str:
    """
    Args:
        slides: list of (slide_text, duration_ms) in play order.
    """
    cues: List[SubtitleCue] = []
    cursor_ms = 0
    for slide_text, duration_ms in slides:
        cues.extend(
            build_slide_cues(
                slide_text=slide_text,
                slide_start_ms=cursor_ms,
                slide_duration_ms=duration_ms,
                max_chars_per_line=max_chars_per_line,
            )
        )
        cursor_ms += max(0, int(duration_ms))
    return build_srt(cues)
