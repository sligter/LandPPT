// Text measurement for browser environments using canvas measureText.
//
// Problem: DOM-based text measurement (getBoundingClientRect, offsetHeight)
// forces synchronous layout reflow. When components independently measure text,
// each measurement triggers a reflow of the entire document. This creates
// read/write interleaving that can cost 30ms+ per frame for 500 text blocks.
//
// Solution: two-phase measurement centered around canvas measureText.
//   prepare(text, font) — segments text via Intl.Segmenter, measures each word
//     via canvas, caches widths, and does one cached DOM calibration read per
//     font when emoji correction is needed. Call once when text first appears.
//   layout(prepared, maxWidth, lineHeight) — walks cached word widths with pure
//     arithmetic to count lines and compute height. Call on every resize.
//     ~0.0002ms per text.
//
// i18n: Intl.Segmenter handles CJK (per-character breaking), Thai, Arabic, etc.
//   Bidi: simplified rich-path metadata for mixed LTR/RTL custom rendering.
//   Punctuation merging: "better." measured as one unit (matches CSS behavior).
//   Trailing whitespace: hangs past line edge without triggering breaks (CSS behavior).
//   overflow-wrap: pre-measured grapheme widths enable character-level word breaking.
//
// Emoji correction: Chrome/Firefox canvas measures emoji wider than DOM at font
//   sizes <24px on macOS (Apple Color Emoji). The inflation is constant per emoji
//   grapheme at a given size, font-independent. Auto-detected by comparing canvas
//   vs actual DOM emoji width (one cached DOM read per font). Safari canvas and
//   DOM agree (both wider than fontSize), so correction = 0 there.
//
// Limitations:
//   - system-ui font: canvas resolves to different optical variants than DOM on macOS.
//     Use named fonts (Helvetica, Inter, etc.) for guaranteed accuracy.
//     See RESEARCH.md "Discovery: system-ui font resolution mismatch".
//
// Based on Sebastian Markbage's text-layout research (github.com/chenglou/text-layout).
import { computeSegmentLevels } from './bidi.js';
import { analyzeText, clearAnalysisCaches, endsWithClosingQuote, isCJK, kinsokuEnd, kinsokuStart, leftStickyPunctuation, setAnalysisLocale, } from './analysis.js';
import { clearMeasurementCaches, getCorrectedSegmentWidth, getEngineProfile, getFontMeasurementState, getSegmentGraphemePrefixWidths, getSegmentGraphemeWidths, getSegmentMetrics, textMayContainEmoji, } from './measurement.js';
import { countPreparedLines, layoutNextLineRange as stepPreparedLineRange, walkPreparedLines, } from './line-break.js';
let sharedGraphemeSegmenter = null;
// Rich-path only. Reuses grapheme splits while materializing multiple lines
// from the same prepared handle, without pushing that cache into the API.
let sharedLineTextCaches = new WeakMap();
function getSharedGraphemeSegmenter() {
    if (sharedGraphemeSegmenter === null) {
        sharedGraphemeSegmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' });
    }
    return sharedGraphemeSegmenter;
}
// --- Public API ---
function createEmptyPrepared(includeSegments) {
    if (includeSegments) {
        return {
            widths: [],
            lineEndFitAdvances: [],
            lineEndPaintAdvances: [],
            kinds: [],
            simpleLineWalkFastPath: true,
            segLevels: null,
            breakableWidths: [],
            breakablePrefixWidths: [],
            discretionaryHyphenWidth: 0,
            tabStopAdvance: 0,
            chunks: [],
            segments: [],
        };
    }
    return {
        widths: [],
        lineEndFitAdvances: [],
        lineEndPaintAdvances: [],
        kinds: [],
        simpleLineWalkFastPath: true,
        segLevels: null,
        breakableWidths: [],
        breakablePrefixWidths: [],
        discretionaryHyphenWidth: 0,
        tabStopAdvance: 0,
        chunks: [],
    };
}
function measureAnalysis(analysis, font, includeSegments) {
    const graphemeSegmenter = getSharedGraphemeSegmenter();
    const engineProfile = getEngineProfile();
    const { cache, emojiCorrection } = getFontMeasurementState(font, textMayContainEmoji(analysis.normalized));
    const discretionaryHyphenWidth = getCorrectedSegmentWidth('-', getSegmentMetrics('-', cache), emojiCorrection);
    const spaceWidth = getCorrectedSegmentWidth(' ', getSegmentMetrics(' ', cache), emojiCorrection);
    const tabStopAdvance = spaceWidth * 8;
    if (analysis.len === 0)
        return createEmptyPrepared(includeSegments);
    const widths = [];
    const lineEndFitAdvances = [];
    const lineEndPaintAdvances = [];
    const kinds = [];
    let simpleLineWalkFastPath = analysis.chunks.length <= 1;
    const segStarts = includeSegments ? [] : null;
    const breakableWidths = [];
    const breakablePrefixWidths = [];
    const segments = includeSegments ? [] : null;
    const preparedStartByAnalysisIndex = Array.from({ length: analysis.len });
    const preparedEndByAnalysisIndex = Array.from({ length: analysis.len });
    function pushMeasuredSegment(text, width, lineEndFitAdvance, lineEndPaintAdvance, kind, start, breakable, breakablePrefix) {
        if (kind !== 'text' && kind !== 'space' && kind !== 'zero-width-break') {
            simpleLineWalkFastPath = false;
        }
        widths.push(width);
        lineEndFitAdvances.push(lineEndFitAdvance);
        lineEndPaintAdvances.push(lineEndPaintAdvance);
        kinds.push(kind);
        segStarts?.push(start);
        breakableWidths.push(breakable);
        breakablePrefixWidths.push(breakablePrefix);
        if (segments !== null)
            segments.push(text);
    }
    for (let mi = 0; mi < analysis.len; mi++) {
        preparedStartByAnalysisIndex[mi] = widths.length;
        const segText = analysis.texts[mi];
        const segWordLike = analysis.isWordLike[mi];
        const segKind = analysis.kinds[mi];
        const segStart = analysis.starts[mi];
        if (segKind === 'soft-hyphen') {
            pushMeasuredSegment(segText, 0, discretionaryHyphenWidth, discretionaryHyphenWidth, segKind, segStart, null, null);
            preparedEndByAnalysisIndex[mi] = widths.length;
            continue;
        }
        if (segKind === 'hard-break') {
            pushMeasuredSegment(segText, 0, 0, 0, segKind, segStart, null, null);
            preparedEndByAnalysisIndex[mi] = widths.length;
            continue;
        }
        if (segKind === 'tab') {
            pushMeasuredSegment(segText, 0, 0, 0, segKind, segStart, null, null);
            preparedEndByAnalysisIndex[mi] = widths.length;
            continue;
        }
        const segMetrics = getSegmentMetrics(segText, cache);
        if (segKind === 'text' && segMetrics.containsCJK) {
            let unitText = '';
            let unitStart = 0;
            for (const gs of graphemeSegmenter.segment(segText)) {
                const grapheme = gs.segment;
                if (unitText.length === 0) {
                    unitText = grapheme;
                    unitStart = gs.index;
                    continue;
                }
                if (kinsokuEnd.has(unitText) ||
                    kinsokuStart.has(grapheme) ||
                    leftStickyPunctuation.has(grapheme) ||
                    (engineProfile.carryCJKAfterClosingQuote &&
                        isCJK(grapheme) &&
                        endsWithClosingQuote(unitText))) {
                    unitText += grapheme;
                    continue;
                }
                const unitMetrics = getSegmentMetrics(unitText, cache);
                const w = getCorrectedSegmentWidth(unitText, unitMetrics, emojiCorrection);
                pushMeasuredSegment(unitText, w, w, w, 'text', segStart + unitStart, null, null);
                unitText = grapheme;
                unitStart = gs.index;
            }
            if (unitText.length > 0) {
                const unitMetrics = getSegmentMetrics(unitText, cache);
                const w = getCorrectedSegmentWidth(unitText, unitMetrics, emojiCorrection);
                pushMeasuredSegment(unitText, w, w, w, 'text', segStart + unitStart, null, null);
            }
            preparedEndByAnalysisIndex[mi] = widths.length;
            continue;
        }
        const w = getCorrectedSegmentWidth(segText, segMetrics, emojiCorrection);
        const lineEndFitAdvance = segKind === 'space' || segKind === 'preserved-space' || segKind === 'zero-width-break'
            ? 0
            : w;
        const lineEndPaintAdvance = segKind === 'space' || segKind === 'zero-width-break'
            ? 0
            : w;
        if (segWordLike && segText.length > 1) {
            const graphemeWidths = getSegmentGraphemeWidths(segText, segMetrics, cache, emojiCorrection);
            const graphemePrefixWidths = engineProfile.preferPrefixWidthsForBreakableRuns
                ? getSegmentGraphemePrefixWidths(segText, segMetrics, cache, emojiCorrection)
                : null;
            pushMeasuredSegment(segText, w, lineEndFitAdvance, lineEndPaintAdvance, segKind, segStart, graphemeWidths, graphemePrefixWidths);
        }
        else {
            pushMeasuredSegment(segText, w, lineEndFitAdvance, lineEndPaintAdvance, segKind, segStart, null, null);
        }
        preparedEndByAnalysisIndex[mi] = widths.length;
    }
    const chunks = mapAnalysisChunksToPreparedChunks(analysis.chunks, preparedStartByAnalysisIndex, preparedEndByAnalysisIndex);
    const segLevels = segStarts === null ? null : computeSegmentLevels(analysis.normalized, segStarts);
    if (segments !== null) {
        return {
            widths,
            lineEndFitAdvances,
            lineEndPaintAdvances,
            kinds,
            simpleLineWalkFastPath,
            segLevels,
            breakableWidths,
            breakablePrefixWidths,
            discretionaryHyphenWidth,
            tabStopAdvance,
            chunks,
            segments,
        };
    }
    return {
        widths,
        lineEndFitAdvances,
        lineEndPaintAdvances,
        kinds,
        simpleLineWalkFastPath,
        segLevels,
        breakableWidths,
        breakablePrefixWidths,
        discretionaryHyphenWidth,
        tabStopAdvance,
        chunks,
    };
}
function mapAnalysisChunksToPreparedChunks(chunks, preparedStartByAnalysisIndex, preparedEndByAnalysisIndex) {
    const preparedChunks = [];
    for (let i = 0; i < chunks.length; i++) {
        const chunk = chunks[i];
        const startSegmentIndex = chunk.startSegmentIndex < preparedStartByAnalysisIndex.length
            ? preparedStartByAnalysisIndex[chunk.startSegmentIndex]
            : preparedEndByAnalysisIndex[preparedEndByAnalysisIndex.length - 1] ?? 0;
        const endSegmentIndex = chunk.endSegmentIndex < preparedStartByAnalysisIndex.length
            ? preparedStartByAnalysisIndex[chunk.endSegmentIndex]
            : preparedEndByAnalysisIndex[preparedEndByAnalysisIndex.length - 1] ?? 0;
        const consumedEndSegmentIndex = chunk.consumedEndSegmentIndex < preparedStartByAnalysisIndex.length
            ? preparedStartByAnalysisIndex[chunk.consumedEndSegmentIndex]
            : preparedEndByAnalysisIndex[preparedEndByAnalysisIndex.length - 1] ?? 0;
        preparedChunks.push({
            startSegmentIndex,
            endSegmentIndex,
            consumedEndSegmentIndex,
        });
    }
    return preparedChunks;
}
function prepareInternal(text, font, includeSegments, options) {
    const analysis = analyzeText(text, getEngineProfile(), options?.whiteSpace);
    return measureAnalysis(analysis, font, includeSegments);
}
// Diagnostic-only helper used by the browser benchmark harness to separate the
// text-analysis and measurement phases without duplicating the prepare logic.
export function profilePrepare(text, font, options) {
    const t0 = performance.now();
    const analysis = analyzeText(text, getEngineProfile(), options?.whiteSpace);
    const t1 = performance.now();
    const prepared = measureAnalysis(analysis, font, false);
    const t2 = performance.now();
    let breakableSegments = 0;
    for (const widths of prepared.breakableWidths) {
        if (widths !== null)
            breakableSegments++;
    }
    return {
        analysisMs: t1 - t0,
        measureMs: t2 - t1,
        totalMs: t2 - t0,
        analysisSegments: analysis.len,
        preparedSegments: prepared.widths.length,
        breakableSegments,
    };
}
// Prepare text for layout. Segments the text, measures each segment via canvas,
// and stores the widths for fast relayout at any width. Call once per text block
// (e.g. when a comment first appears). The result is width-independent — the
// same PreparedText can be laid out at any maxWidth and lineHeight via layout().
//
// Steps:
//   1. Normalize collapsible whitespace (CSS white-space: normal behavior)
//   2. Segment via Intl.Segmenter (handles CJK, Thai, etc.)
//   3. Merge punctuation into preceding word ("better." as one unit)
//   4. Split CJK words into individual graphemes (per-character line breaks)
//   5. Measure each segment via canvas measureText, cache by (segment, font)
//   6. Pre-measure graphemes of long words (for overflow-wrap: break-word)
//   7. Correct emoji canvas inflation (auto-detected per font size)
//   8. Optionally compute rich-path bidi metadata for custom renderers
export function prepare(text, font, options) {
    return prepareInternal(text, font, false, options);
}
// Rich variant used by callers that need enough information to render the
// laid-out lines themselves.
export function prepareWithSegments(text, font, options) {
    return prepareInternal(text, font, true, options);
}
function getInternalPrepared(prepared) {
    return prepared;
}
// Layout prepared text at a given max width and caller-provided lineHeight.
// Pure arithmetic on cached widths — no canvas calls, no DOM reads, no string
// operations, no allocations.
// ~0.0002ms per text block. Call on every resize.
//
// Line breaking rules (matching CSS white-space: normal + overflow-wrap: break-word):
//   - Break before any non-space segment that would overflow the line
//   - Trailing whitespace hangs past the line edge (doesn't trigger breaks)
//   - Segments wider than maxWidth are broken at grapheme boundaries
export function layout(prepared, maxWidth, lineHeight) {
    // Keep the resize hot path specialized. `layoutWithLines()` shares the same
    // break semantics but also tracks line ranges; the extra bookkeeping is too
    // expensive to pay on every hot-path `layout()` call.
    const lineCount = countPreparedLines(getInternalPrepared(prepared), maxWidth);
    return { lineCount, height: lineCount * lineHeight };
}
function getSegmentGraphemes(segmentIndex, segments, cache) {
    let graphemes = cache.get(segmentIndex);
    if (graphemes !== undefined)
        return graphemes;
    graphemes = [];
    const graphemeSegmenter = getSharedGraphemeSegmenter();
    for (const gs of graphemeSegmenter.segment(segments[segmentIndex])) {
        graphemes.push(gs.segment);
    }
    cache.set(segmentIndex, graphemes);
    return graphemes;
}
function getLineTextCache(prepared) {
    let cache = sharedLineTextCaches.get(prepared);
    if (cache !== undefined)
        return cache;
    cache = new Map();
    sharedLineTextCaches.set(prepared, cache);
    return cache;
}
function lineHasDiscretionaryHyphen(kinds, startSegmentIndex, startGraphemeIndex, endSegmentIndex) {
    return (endSegmentIndex > 0 &&
        kinds[endSegmentIndex - 1] === 'soft-hyphen' &&
        !(startSegmentIndex === endSegmentIndex && startGraphemeIndex > 0));
}
function buildLineTextFromRange(segments, kinds, cache, startSegmentIndex, startGraphemeIndex, endSegmentIndex, endGraphemeIndex) {
    let text = '';
    const endsWithDiscretionaryHyphen = lineHasDiscretionaryHyphen(kinds, startSegmentIndex, startGraphemeIndex, endSegmentIndex);
    for (let i = startSegmentIndex; i < endSegmentIndex; i++) {
        if (kinds[i] === 'soft-hyphen' || kinds[i] === 'hard-break')
            continue;
        if (i === startSegmentIndex && startGraphemeIndex > 0) {
            text += getSegmentGraphemes(i, segments, cache).slice(startGraphemeIndex).join('');
        }
        else {
            text += segments[i];
        }
    }
    if (endGraphemeIndex > 0) {
        if (endsWithDiscretionaryHyphen)
            text += '-';
        text += getSegmentGraphemes(endSegmentIndex, segments, cache).slice(startSegmentIndex === endSegmentIndex ? startGraphemeIndex : 0, endGraphemeIndex).join('');
    }
    else if (endsWithDiscretionaryHyphen) {
        text += '-';
    }
    return text;
}
function createLayoutLine(prepared, cache, width, startSegmentIndex, startGraphemeIndex, endSegmentIndex, endGraphemeIndex) {
    return {
        text: buildLineTextFromRange(prepared.segments, prepared.kinds, cache, startSegmentIndex, startGraphemeIndex, endSegmentIndex, endGraphemeIndex),
        width,
        start: {
            segmentIndex: startSegmentIndex,
            graphemeIndex: startGraphemeIndex,
        },
        end: {
            segmentIndex: endSegmentIndex,
            graphemeIndex: endGraphemeIndex,
        },
    };
}
function materializeLayoutLine(prepared, cache, line) {
    return createLayoutLine(prepared, cache, line.width, line.startSegmentIndex, line.startGraphemeIndex, line.endSegmentIndex, line.endGraphemeIndex);
}
function toLayoutLineRange(line) {
    return {
        width: line.width,
        start: {
            segmentIndex: line.startSegmentIndex,
            graphemeIndex: line.startGraphemeIndex,
        },
        end: {
            segmentIndex: line.endSegmentIndex,
            graphemeIndex: line.endGraphemeIndex,
        },
    };
}
function stepLineRange(prepared, start, maxWidth) {
    const line = stepPreparedLineRange(prepared, start, maxWidth);
    if (line === null)
        return null;
    return toLayoutLineRange(line);
}
function materializeLine(prepared, line) {
    return createLayoutLine(prepared, getLineTextCache(prepared), line.width, line.start.segmentIndex, line.start.graphemeIndex, line.end.segmentIndex, line.end.graphemeIndex);
}
// Batch low-level line geometry pass. This is the non-materializing counterpart
// to layoutWithLines(), useful for shrinkwrap and other aggregate geometry work.
export function walkLineRanges(prepared, maxWidth, onLine) {
    if (prepared.widths.length === 0)
        return 0;
    return walkPreparedLines(getInternalPrepared(prepared), maxWidth, line => {
        onLine(toLayoutLineRange(line));
    });
}
export function layoutNextLine(prepared, start, maxWidth) {
    const line = stepLineRange(prepared, start, maxWidth);
    if (line === null)
        return null;
    return materializeLine(prepared, line);
}
// Rich layout API for callers that want the actual line contents and widths.
// Caller still supplies lineHeight at layout time. Mirrors layout()'s break
// decisions, but keeps extra per-line bookkeeping so it should stay off the
// resize hot path.
export function layoutWithLines(prepared, maxWidth, lineHeight) {
    const lines = [];
    if (prepared.widths.length === 0)
        return { lineCount: 0, height: 0, lines };
    const graphemeCache = getLineTextCache(prepared);
    const lineCount = walkPreparedLines(getInternalPrepared(prepared), maxWidth, line => {
        lines.push(materializeLayoutLine(prepared, graphemeCache, line));
    });
    return { lineCount, height: lineCount * lineHeight, lines };
}
export function clearCache() {
    clearAnalysisCaches();
    sharedGraphemeSegmenter = null;
    sharedLineTextCaches = new WeakMap();
    clearMeasurementCaches();
}
export function setLocale(locale) {
    setAnalysisLocale(locale);
    clearCache();
}
