import json
import os
import re
import time
from io import BytesIO
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

import pandas as pd
import requests
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright


# =========================
# CONFIGURAZIONE
# =========================
INPUT_FILE = "detail_links_multi_page.xlsx"
OUTPUT_FILE = "Step4.xlsx"

OLLAMA_MODEL = "llama3.2"
OLLAMA_API_URL = "http://localhost:11434/api/chat"

HEADLESS = True
SLEEP_BETWEEN_ROWS = 1.5
SAVE_EVERY = 1
MAX_ROWS = None               # None = tutte le righe
REQUEST_TIMEOUT_SECONDS = 180


def patch_playwright_frame_detach_bug():
    """
    Work around a Playwright internal race where a frame can be detached twice
    and Page._on_frame_detached raises ValueError on list.remove(frame).
    Some highly dynamic configurators continuously create/destroy iframes.
    """
    try:
        from playwright._impl._page import Page as _ImplPage
    except Exception:
        return

    if getattr(_ImplPage, "_oai_frame_detach_bug_patched", False):
        return

    original = _ImplPage._on_frame_detached

    def _safe_on_frame_detached(self, frame):
        try:
            if frame in self._frames:
                self._frames.remove(frame)
        except Exception:
            pass
        try:
            frame._detached = True
        except Exception:
            pass
        try:
            self.emit(_ImplPage.Events.FrameDetached, frame)
        except Exception:
            pass

    _ImplPage._on_frame_detached = _safe_on_frame_detached
    _ImplPage._oai_frame_detach_bug_patched = True


patch_playwright_frame_detach_bug()
PAGE_GOTO_TIMEOUT_MS = 30000
POST_GOTO_WAIT_MS = 5000
MAX_SEED_URLS = 8
MAX_INTERNAL_LINKS_TO_EXPLORE = 8
MAX_INTERNAL_DISCOVERY_PAGES = 12
VISUALIZATION_OLLAMA_MIN_CONFIDENCE = 75
GOOGLE_SEARCH_MAX_RESULTS = 4  # legacy safety constant; Google browser search is not used in this version
ALTERNATIVE_CANDIDATES_TO_OPEN = 4

ENABLE_VISUALIZATION_TYPE = True   # Se False, salta completamente la colonna "Tipo di visualizzazione" e tutte le operazioni collegate
ENABLE_MOBILE_OPTIMIZATION_SCORE = True   # Se False, salta completamente la colonna "Ottimizzato per Mobile?" e tutte le operazioni collegate
ENABLE_COMPATIBILITY_CONSTRAINT_SCORE = True   # Se False, salta completamente la colonna "Presenza di regole/vincoli di compatibilità?" e tutte le operazioni collegate
ENABLE_COMPLEXITY_SCORE = True   # Se False, salta completamente la colonna "Livello di Complessità" e tutte le operazioni collegate

COMPATIBILITY_PROBE_MAX_CANDIDATES = 6
COMPATIBILITY_PROBE_MAX_ACTIONS = 4
COMPATIBILITY_PROBE_WAIT_MS = 900
ENABLE_COMPATIBILITY_OLLAMA_REVIEW = True
COMPATIBILITY_OLLAMA_MIN_CONFIDENCE = 70
COMPATIBILITY_NAVIGATION_TIMEOUT_MS = 4500
COMPATIBILITY_MULTILAYER_MAX_LAYERS = 3

ENABLE_COMPLEXITY_OLLAMA_REVIEW = True
COMPLEXITY_OLLAMA_MIN_CONFIDENCE = 70
COMPLEXITY_MIN_SCORE = 1
COMPLEXITY_MAX_SCORE = 5

MOBILE_VIEWPORT_WIDTH = 390
MOBILE_VIEWPORT_HEIGHT = 844
MOBILE_DEVICE_PROFILE = "iPhone 13"
MOBILE_SCROLL_STEPS = 5
MOBILE_SCROLL_WAIT_MS = 700
MOBILE_MIN_SCORE = 1
MOBILE_MAX_SCORE = 5
ENABLE_MOBILE_OLLAMA_REVIEW = True
MOBILE_OLLAMA_MIN_CONFIDENCE = 70

ALLOWED_VISUALIZATION_TYPES = {"Static 2D", "Interactive 3D"}
YES_NO_VALUES = {"SI", "NO"}


# =========================
# UTILITY GENERALI
# =========================
def normalize_space(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def clean_lines(text):
    lines = []
    for line in (text or "").splitlines():
        line = normalize_space(line)
        if line:
            lines.append(line)
    return lines


def compress_visible_text(text, max_chars=6000):
    lines = clean_lines(text)
    seen = set()
    result = []
    current_len = 0

    for line in lines:
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)

        if current_len + len(line) + 1 > max_chars:
            break

        result.append(line)
        current_len += len(line) + 1

    return "\n".join(result)


def get_value_after_label(lines, label):
    labels_to_skip = {
        "PRODUCT",
        "INDUSTRY",
        "COUNTRY",
        "CUSTOMIZATION OPTIONS",
        "FEATURES",
        "FORM",
        "FIT",
        "FUNCTION",
        "ONLINE ORDER",
        "RESPONSIVE",
    }

    for i, line in enumerate(lines):
        if line.upper() == label.upper():
            for j in range(i + 1, len(lines)):
                candidate = lines[j].strip()
                if not candidate:
                    continue
                if candidate.upper() in labels_to_skip:
                    continue
                return candidate

    return ""


def format_seconds(seconds):
    seconds = int(round(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def safe_to_excel(df, filepath):
    try:
        df.to_excel(filepath, index=False)
    except PermissionError:
        raise PermissionError(
            f"Non riesco a salvare '{filepath}'. "
            f"Probabilmente il file è aperto in Excel. Chiudilo e rilancia."
        )


def safe_page_goto(page, url, timeout_ms=PAGE_GOTO_TIMEOUT_MS, post_wait_ms=POST_GOTO_WAIT_MS):
    page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass

    if post_wait_ms > 0:
        page.wait_for_timeout(post_wait_ms)


def call_ollama(prompt):
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }

    response = requests.post(OLLAMA_API_URL, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()

    data = response.json()
    return data["message"]["content"]


# =========================
# NORMALIZZAZIONI VALORI
# =========================
def normalize_visualization_type(value):
    raw = normalize_space(value)
    if not raw:
        return ""

    upper = raw.upper()

    if upper == "AR" or "AUGMENTED REALITY" in upper or "REALTÀ AUMENTATA" in upper or "REALTA AUMENTATA" in upper:
        return "Interactive 3D"

    if "INTERACTIVE" in upper or "3D" in upper or "360" in upper or "ROTATABLE" in upper or "ROTABILE" in upper:
        return "Interactive 3D"

    if "STATIC" in upper or "2D" in upper or "IMMAG" in upper:
        return "Static 2D"

    return ""


def infer_visualization_type_from_free_text(text):
    text_l = normalize_space(text).lower()
    if not text_l:
        return ""

    ar_signals = [
        "augmented reality",
        "realtà aumentata",
        "realta aumentata",
        "view in your space",
        "quick look",
        "scene viewer",
        ".usdz",
        " rel=ar",
    ]
    if any(signal in text_l for signal in ar_signals):
        return "Interactive 3D"

    strong_3d_signals = [
        "babylon.js",
        "three.js",
        "three js",
        "webgl",
        "sketchfab",
        "verge3d",
        "playcanvas",
        "model-viewer",
        "model viewer",
        "360°",
        "360 degree",
        "360-degree",
        "360 view",
        "drag to rotate",
        "rotate the model",
        "rotatable",
        "rotabile",
        "3d viewer",
        "3d configurator",
    ]
    if any(signal in text_l for signal in strong_3d_signals):
        return "Interactive 3D"

    static_signals = [
        "static image",
        "static images",
        "immagini statiche",
        "preview image",
        "preview images",
        "product image",
        "gallery image",
        "solo immagini",
        "2d preview",
        "2d",
    ]
    if any(signal in text_l for signal in static_signals):
        return "Static 2D"

    return ""


def compute_image_difference_ratio(image_a_bytes, image_b_bytes, resize_to=(280, 280), pixel_threshold=18):
    try:
        img_a = Image.open(BytesIO(image_a_bytes)).convert("L").resize(resize_to)
        img_b = Image.open(BytesIO(image_b_bytes)).convert("L").resize(resize_to)
        diff = ImageChops.difference(img_a, img_b)
        hist = diff.histogram()
        changed_pixels = sum(hist[pixel_threshold:])
        total_pixels = resize_to[0] * resize_to[1]
        if total_pixels <= 0:
            return 0.0
        return changed_pixels / total_pixels
    except Exception:
        return 0.0


def count_view_orientation_hints(text):
    text_l = normalize_space(text).lower()
    if not text_l:
        return 0
    keywords = [
        "view", "vista", "vue", "ansicht", "visione",
        "front", "frontal", "side", "profile", "profilo", "profil",
        "back", "rear", "left", "right", "top", "bottom",
        "sole", "sun", "lenses", "lens", "frame", "frames",
        "rotate", "drag", "360"
    ]
    return sum(1 for kw in keywords if kw in text_l)


def get_main_viewer_candidate_info(page):
    try:
        return page.evaluate(
            r"""
            () => {
                for (const oldEl of document.querySelectorAll('[data-oai-viewer-probe="1"]')) {
                    oldEl.removeAttribute('data-oai-viewer-probe');
                }

                const viewportW = Math.max(window.innerWidth || 0, 1);
                const viewportH = Math.max(window.innerHeight || 0, 1);
                const viewportArea = viewportW * viewportH;
                const centerX = viewportW / 2;
                const centerY = viewportH / 2;
                const candidates = [...document.querySelectorAll('model-viewer, canvas, svg, img, iframe')];
                let best = null;
                let bestScore = -Infinity;

                function isVisible(el, rect, style) {
                    if (!rect) return false;
                    if (rect.width < 220 || rect.height < 160) return false;
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    if (parseFloat(style.opacity || '1') < 0.1) return false;
                    if (rect.bottom < 0 || rect.right < 0 || rect.top > viewportH || rect.left > viewportW) return false;
                    return true;
                }

                for (const el of candidates) {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    if (!isVisible(el, rect, style)) continue;

                    const tag = el.tagName.toLowerCase();
                    const src = (el.currentSrc || el.src || el.getAttribute('src') || '').toLowerCase();
                    const alt = (el.alt || el.getAttribute('aria-label') || el.getAttribute('title') || '').toLowerCase();
                    const textHint = (src + ' ' + alt).trim();
                    if (/(logo|icon|avatar|flag|favicon|payment|sprite|banner|hero-bg)/.test(textHint) && tag === 'img') {
                        continue;
                    }

                    const area = rect.width * rect.height;
                    const areaRatio = area / viewportArea;
                    const elCenterX = rect.left + rect.width / 2;
                    const elCenterY = rect.top + rect.height / 2;
                    const centerDistance = Math.abs(elCenterX - centerX) + Math.abs(elCenterY - centerY);
                    const nearCenterBonus = Math.max(0, 2500 - centerDistance);
                    const topHalfBonus = rect.top < viewportH * 0.72 ? 1200 : 0;
                    const cursor = (style.cursor || '').toLowerCase();
                    const cursorBonus = ['grab', 'grabbing', 'move', 'all-scroll', 'pointer'].includes(cursor) ? 2200 : 0;
                    const tagBonusMap = { 'model-viewer': 5000, 'canvas': 3600, 'svg': 2400, 'iframe': 1800, 'img': 1200 };
                    const tagBonus = tagBonusMap[tag] || 0;
                    const score = areaRatio * 15000 + nearCenterBonus + topHalfBonus + cursorBonus + tagBonus;

                    if (score > bestScore) {
                        bestScore = score;
                        best = {
                            tag,
                            width: rect.width,
                            height: rect.height,
                            area_ratio: areaRatio,
                            cursor,
                            src: src,
                            alt: alt,
                            center_distance: centerDistance,
                            score
                        };
                        bestScore = score;
                    }
                }

                if (!best) return null;

                for (const el of candidates) {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    if (!isVisible(el, rect, style)) continue;
                    const tag = el.tagName.toLowerCase();
                    const src = (el.currentSrc || el.src || el.getAttribute('src') || '').toLowerCase();
                    const alt = (el.alt || el.getAttribute('aria-label') || el.getAttribute('title') || '').toLowerCase();
                    const area = rect.width * rect.height;
                    const areaRatio = area / viewportArea;
                    const elCenterX = rect.left + rect.width / 2;
                    const elCenterY = rect.top + rect.height / 2;
                    const centerDistance = Math.abs(elCenterX - centerX) + Math.abs(elCenterY - centerY);
                    const nearCenterBonus = Math.max(0, 2500 - centerDistance);
                    const topHalfBonus = rect.top < viewportH * 0.72 ? 1200 : 0;
                    const cursor = (style.cursor || '').toLowerCase();
                    const cursorBonus = ['grab', 'grabbing', 'move', 'all-scroll', 'pointer'].includes(cursor) ? 2200 : 0;
                    const tagBonusMap = { 'model-viewer': 5000, 'canvas': 3600, 'svg': 2400, 'iframe': 1800, 'img': 1200 };
                    const tagBonus = tagBonusMap[tag] || 0;
                    const score = areaRatio * 15000 + nearCenterBonus + topHalfBonus + cursorBonus + tagBonus;
                    if (Math.abs(score - best.score) < 0.001 && tag === best.tag && Math.abs(rect.width - best.width) < 1 && Math.abs(rect.height - best.height) < 1 && Math.abs(centerDistance - best.center_distance) < 1) {
                        el.setAttribute('data-oai-viewer-probe', '1');
                        return best;
                    }
                }

                return null;
            }
            """
        )
    except Exception:
        return None


def probe_interactive_3d_viewer(page, dom_signals, visible_text=""):
    info = get_main_viewer_candidate_info(page)
    if not info:
        return None

    locator = page.locator('[data-oai-viewer-probe="1"]').first
    try:
        locator.scroll_into_view_if_needed(timeout=2500)
    except Exception:
        pass

    try:
        box = locator.bounding_box()
    except Exception:
        box = None

    if not box or box.get("width", 0) < 220 or box.get("height", 0) < 160:
        return None

    try:
        before = locator.screenshot(timeout=5000, animations="disabled")
        page.wait_for_timeout(250)
        idle = locator.screenshot(timeout=5000, animations="disabled")

        start_x = box["x"] + box["width"] * 0.25
        end_x = box["x"] + box["width"] * 0.75
        y = box["y"] + box["height"] * 0.52

        page.mouse.move(start_x, y)
        page.mouse.down()
        page.mouse.move(end_x, y, steps=18)
        page.mouse.up()
        page.wait_for_timeout(450)

        after = locator.screenshot(timeout=5000, animations="disabled")
    except Exception:
        return None

    baseline_ratio = compute_image_difference_ratio(before, idle)
    drag_ratio = compute_image_difference_ratio(idle, after)

    view_hint_text = " ".join([
        visible_text or "",
        " ".join(dom_signals.get("button_texts", [])),
        " ".join(dom_signals.get("label_texts", [])),
        " ".join(dom_signals.get("link_texts", [])),
        " ".join(dom_signals.get("rotate_text_hints", [])),
    ])
    view_hint_count = count_view_orientation_hints(view_hint_text)

    cursor = (info.get("cursor") or "").lower()
    cursor_interactive = cursor in {"grab", "grabbing", "move", "all-scroll", "pointer"}
    structural_3d_hint = (
        info.get("tag") in {"model-viewer", "canvas", "svg", "iframe"}
        or dom_signals.get("webgl_canvas_count", 0) > 0
        or dom_signals.get("three_global", False)
        or dom_signals.get("babylon_global", False)
        or dom_signals.get("model_viewer_global", False)
        or len(dom_signals.get("rotate_text_hints", [])) > 0
        or view_hint_count >= 3
    )

    very_strong_drag_evidence = drag_ratio >= 0.12 and (drag_ratio - baseline_ratio) >= 0.05
    strong_drag_evidence = drag_ratio >= 0.07 and drag_ratio >= max(0.03, baseline_ratio * 2.2) and (drag_ratio - baseline_ratio) >= 0.025

    if very_strong_drag_evidence and (cursor_interactive or structural_3d_hint):
        return (
            "Interactive 3D",
            f"Deterministic interaction probe: dragging the main viewer changed the product substantially (diff={drag_ratio:.3f}, baseline={baseline_ratio:.3f}, tag={info.get('tag')})"
        )

    if strong_drag_evidence and structural_3d_hint:
        return (
            "Interactive 3D",
            f"Deterministic interaction probe: the main viewer reacts to drag like a rotatable model (diff={drag_ratio:.3f}, baseline={baseline_ratio:.3f}, tag={info.get('tag')})"
        )

    return None


# =========================
# COOKIE / ESTRAZIONE PAGINA DATABASE
# =========================
def try_accept_cookies(page):
    possible_buttons = [
        "OK, I agree",
        "I agree",
        "Accept",
        "Accept all",
        "Allow all",
        "Agree",
        "Akzeptieren",
        "Alle akzeptieren",
        "Aceptar",
        "Tout accepter",
        "Ich stimme zu",
        "Zustimmen",
        "Accept All",
        "Allow all cookies",
        "Accept all cookies",
    ]

    for text in possible_buttons:
        locator = page.get_by_text(text, exact=False).first
        try:
            if locator.is_visible(timeout=1500):
                locator.click(timeout=2500)
                page.wait_for_timeout(1200)
                return
        except Exception:
            pass


def extract_detail_data(page):
    company = ""
    product = ""
    industry = ""
    country = ""
    configurator_link = ""

    try:
        company = page.locator("h1").first.inner_text().strip()
    except Exception:
        company = ""

    try:
        visible_text = page.locator("body").inner_text()
    except Exception:
        visible_text = ""

    lines = clean_lines(visible_text)

    product = get_value_after_label(lines, "PRODUCT")
    industry = get_value_after_label(lines, "INDUSTRY")
    country = get_value_after_label(lines, "COUNTRY")

    try:
        configurator_link = page.locator("a:has-text('TRY THE CONFIGURATOR')").first.get_attribute("href")
    except Exception:
        configurator_link = ""

    return {
        "company": company,
        "product": product,
        "industry": industry,
        "country": country,
        "configurator_url": configurator_link,
    }


def get_page_dom_signals(page):
    try:
        dom_info = page.evaluate(
            r"""
            () => {
                function extractTexts(selector, maxItems = 30) {
                    const elements = [...document.querySelectorAll(selector)];
                    const texts = elements
                        .map(el => (el.innerText || el.value || el.getAttribute('aria-label') || '').trim())
                        .map(t => t.replace(/\\s+/g, ' '))
                        .filter(Boolean);

                    const unique = [];
                    const seen = new Set();

                    for (const t of texts) {
                        const key = t.toLowerCase();
                        if (!seen.has(key)) {
                            seen.add(key);
                            unique.push(t);
                        }
                        if (unique.length >= maxItems) break;
                    }

                    return unique;
                }

                function limitedMatchesFromElements(selector, regex, maxItems = 20) {
                    const elements = [...document.querySelectorAll(selector)];
                    const found = [];
                    const seen = new Set();

                    for (const el of elements) {
                        const text = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim();
                        if (!text) continue;
                        if (!regex.test(text)) continue;
                        const key = text.toLowerCase();
                        if (seen.has(key)) continue;
                        seen.add(key);
                        found.push(text);
                        if (found.length >= maxItems) break;
                    }

                    return found;
                }

                function getScriptHints(maxItems = 20) {
                    const keywords = ['three', 'babylon', 'blend4web', 'b4w', 'model-viewer', 'spline', 'sketchfab', 'verge3d', 'playcanvas', 'scene-viewer', 'quick-look', 'usdz', 'augmented', 'webgl'];
                    const scripts = [...document.querySelectorAll('script')];
                    const hits = [];
                    const seen = new Set();

                    for (const s of scripts) {
                        const raw = ((s.src || '') + ' ' + (s.type || '')).trim();
                        const low = raw.toLowerCase();
                        if (!raw) continue;
                        if (!keywords.some(k => low.includes(k))) continue;
                        if (seen.has(low)) continue;
                        seen.add(low);
                        hits.push(raw);
                        if (hits.length >= maxItems) break;
                    }

                    return hits;
                }

                function getImageSrcHints(maxItems = 12) {
                    const elements = [...document.querySelectorAll('img')];
                    const hits = [];
                    const seen = new Set();

                    for (const el of elements) {
                        const raw = (el.currentSrc || el.src || '').trim();
                        if (!raw) continue;
                        const low = raw.toLowerCase();
                        if (seen.has(low)) continue;
                        seen.add(low);
                        hits.push(raw);
                        if (hits.length >= maxItems) break;
                    }

                    return hits;
                }

                function getLargeImageCount() {
                    let count = 0;
                    const viewportArea = Math.max(window.innerWidth * window.innerHeight, 1);
                    for (const img of document.querySelectorAll('img')) {
                        try {
                            const rect = img.getBoundingClientRect();
                            const area = Math.max(rect.width, 0) * Math.max(rect.height, 0);
                            if (area >= viewportArea * 0.12 || rect.width >= window.innerWidth * 0.55 || rect.height >= window.innerHeight * 0.55) {
                                count += 1;
                            }
                        } catch (e) {}
                    }
                    return count;
                }

                function countAnchorsWithHref() {
                    return [...document.querySelectorAll('a[href]')].filter(a => (a.getAttribute('href') || '').trim()).length;
                }

                function getVisibleTextLength() {
                    const bodyText = ((document.body && (document.body.innerText || document.body.textContent)) || '').replace(/\\s+/g, ' ').trim();
                    return bodyText.length;
                }

                function countMeaningfulTextBlocks() {
                    const selectors = 'h1, h2, h3, p, li, label, button, a, span, div';
                    const nodes = [...document.querySelectorAll(selectors)];
                    let count = 0;
                    const seen = new Set();
                    for (const node of nodes) {
                        const text = (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim();
                        if (!text) continue;
                        if (text.length < 12) continue;
                        const key = text.toLowerCase();
                        if (seen.has(key)) continue;
                        seen.add(key);
                        count += 1;
                        if (count >= 40) break;
                    }
                    return count;
                }

                function countImageExtensionHits() {
                    let count = 0;
                    for (const img of document.querySelectorAll('img')) {
                        const src = (img.currentSrc || img.src || '').toLowerCase();
                        if (!src) continue;
                        if (src.includes('.jpg') || src.includes('.jpeg') || src.includes('.png') || src.includes('.webp')) {
                            count += 1;
                        }
                    }
                    return count;
                }

                function countWebGLCanvases() {
                    let count = 0;
                    for (const canvas of document.querySelectorAll('canvas')) {
                        try {
                            const gl = canvas.getContext('webgl') || canvas.getContext('webgl2') || canvas.getContext('experimental-webgl');
                            if (gl) count += 1;
                        } catch (e) {}
                    }
                    return count;
                }

                const arRegex = /\b(ar|augmented reality|view in your space|quick look|scene viewer)\b/i;
                const rotateRegex = /\b(rotate|spin|drag to rotate|drag to spin|swipe to rotate|turn around|360(?:°| degree| degrees| view)?|view 360)\b/i;

                return {
                    heading_texts: extractTexts('h1, h2, h3', 20),
                    button_texts: extractTexts('button, input[type="button"], input[type="submit"]', 30),
                    link_texts: extractTexts('a', 30),
                    label_texts: extractTexts('label', 20),
                    ar_text_hints: limitedMatchesFromElements('a, button, [role="button"], span, div', arRegex, 20),
                    rotate_text_hints: limitedMatchesFromElements('a, button, [role="button"], span, div', rotateRegex, 20),
                    script_hints: getScriptHints(20),
                    img_src_hints: getImageSrcHints(12),
                    select_count: document.querySelectorAll('select').length,
                    option_count: document.querySelectorAll('option').length,
                    input_count: document.querySelectorAll('input').length,
                    checkbox_count: document.querySelectorAll('input[type="checkbox"]').length,
                    radio_count: document.querySelectorAll('input[type="radio"]').length,
                    range_count: document.querySelectorAll('input[type="range"]').length,
                    number_input_count: document.querySelectorAll('input[type="number"]').length,
                    text_input_count: document.querySelectorAll('input[type="text"], textarea').length,
                    form_count: document.querySelectorAll('form').length,
                    button_count: document.querySelectorAll('button, input[type="button"], input[type="submit"]').length,
                    canvas_count: document.querySelectorAll('canvas').length,
                    webgl_canvas_count: countWebGLCanvases(),
                    iframe_count: document.querySelectorAll('iframe').length,
                    img_count: document.querySelectorAll('img').length,
                    large_image_count: getLargeImageCount(),
                    image_extension_src_count: countImageExtensionHits(),
                    anchor_count: countAnchorsWithHref(),
                    visible_text_length: getVisibleTextLength(),
                    meaningful_text_block_count: countMeaningfulTextBlocks(),
                    video_count: document.querySelectorAll('video').length,
                    svg_count: document.querySelectorAll('svg').length,
                    model_viewer_count: document.querySelectorAll('model-viewer').length,
                    ar_rel_link_count: document.querySelectorAll('a[rel*="ar" i]').length,
                    usdz_link_count: [...document.querySelectorAll('a[href], source[src], model-viewer[src]')].filter(el => {
                        const val = (el.getAttribute('href') || el.getAttribute('src') || '').toLowerCase();
                        return val.includes('.usdz') || val.includes('scene-viewer') || val.includes('quick-look');
                    }).length,
                    three_global: !!window.THREE,
                    babylon_global: !!window.BABYLON,
                    blend4web_global: !!window.b4w || !!window.blend4web,
                    model_viewer_global: !!window.ModelViewerElement,
                    meta_description: ((document.querySelector('meta[name="description"]') || {}).content || '').trim(),
                    meta_og_description: ((document.querySelector('meta[property="og:description"]') || {}).content || '').trim()
                };
            }
            """
        )
        return dom_info
    except Exception:
        return {
            "heading_texts": [],
            "button_texts": [],
            "link_texts": [],
            "label_texts": [],
            "ar_text_hints": [],
            "rotate_text_hints": [],
            "script_hints": [],
            "img_src_hints": [],
            "select_count": 0,
            "option_count": 0,
            "input_count": 0,
            "checkbox_count": 0,
            "radio_count": 0,
            "range_count": 0,
            "number_input_count": 0,
            "text_input_count": 0,
            "form_count": 0,
            "button_count": 0,
            "canvas_count": 0,
            "webgl_canvas_count": 0,
            "iframe_count": 0,
            "img_count": 0,
            "large_image_count": 0,
            "image_extension_src_count": 0,
            "anchor_count": 0,
            "visible_text_length": 0,
            "meaningful_text_block_count": 0,
            "video_count": 0,
            "svg_count": 0,
            "model_viewer_count": 0,
            "ar_rel_link_count": 0,
            "usdz_link_count": 0,
            "three_global": False,
            "babylon_global": False,
            "blend4web_global": False,
            "model_viewer_global": False,
            "meta_description": "",
            "meta_og_description": "",
        }


# =========================
# PARSER RISPOSTA OLLAMA
# =========================
def strip_code_fences(text):
    text = (text or "").strip()
    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def escape_invalid_backslashes(s):
    return re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", s)


def normalize_confidence(value):
    if value is None or value == "":
        return ""

    try:
        val = float(value)
        if 0 <= val <= 1:
            val = val * 100
        val = round(val)
        if val < 0:
            val = 0
        if val > 100:
            val = 100
        return int(val)
    except Exception:
        return ""


def normalize_yes_no_value(value):
    raw = normalize_space(value).strip().upper()
    if not raw:
        return ""

    yes_values = {"SI", "SÌ", "YES", "Y", "TRUE", "1", "ACTIVE"}
    no_values = {"NO", "N", "FALSE", "0", "INACTIVE"}

    if raw in yes_values:
        return "SI"
    if raw in no_values:
        return "NO"

    return ""


def try_parse_json_candidates(raw_output):
    text = strip_code_fences(raw_output)
    candidates = [text]

    if "{" in text and "}" in text:
        candidates.append(text[text.find("{"): text.rfind("}") + 1])

    if "{" in text:
        partial = text[text.find("{"):]
        diff = partial.count("{") - partial.count("}")
        if diff > 0:
            candidates.append(partial + ("}" * diff))
        else:
            candidates.append(partial)

    repaired = []
    for cand in candidates:
        repaired.append(escape_invalid_backslashes(cand))
    candidates.extend(repaired)

    already_seen = set()

    for cand in candidates:
        cand = cand.strip()
        if not cand or cand in already_seen:
            continue
        already_seen.add(cand)

        try:
            parsed = json.loads(cand)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    return None


def regex_extract_field(raw_output, field_name):
    text = strip_code_fences(raw_output)

    pattern_quoted = rf'"?{re.escape(field_name)}"?\s*:\s*"((?:[^"\\]|\\.)*)"'
    m = re.search(pattern_quoted, text, flags=re.IGNORECASE | re.DOTALL)
    if m:
        value = m.group(1)
        value = value.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t")
        value = value.replace("\\\\", "\\")
        return value.strip()

    pattern_unquoted = rf'"?{re.escape(field_name)}"?\s*:\s*([^\n,\}}]+)'
    m = re.search(pattern_unquoted, text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip().strip('"').strip()

    return ""


def regex_extract_yes_no_field(raw_output, field_name):
    text = strip_code_fences(raw_output)
    patterns = [
        rf'"?{re.escape(field_name)}"?\s*:\s*"(SI|NO|YES|TRUE|FALSE)"',
        rf'"?{re.escape(field_name)}"?\s*:\s*(SI|NO|YES|TRUE|FALSE)',
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            return normalize_yes_no_value(m.group(1))
    return ""


def regex_extract_attivo(raw_output):
    text = strip_code_fences(raw_output)

    patterns = [
        r'"?(?:attivo|active)"?\s*:\s*"(SI|NO|YES|TRUE|FALSE)"',
        r'"?(?:attivo|active)"?\s*:\s*(SI|NO|YES|TRUE|FALSE)',
        r'\b(?:attivo|active)\b[^\n:]*:\s*(SI|NO|YES|TRUE|FALSE)',
    ]

    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            return normalize_yes_no_value(m.group(1))

    upper_text = text.upper()
    if any(token in upper_text for token in ['"ATTIVO"', 'ATTIVO', '"ACTIVE"', 'ACTIVE']):
        if any(token in upper_text for token in ['"SI"', ': SI', '"YES"', ': YES', '"TRUE"', ': TRUE']):
            return "SI"
        if any(token in upper_text for token in ['"NO"', ': NO', '"FALSE"', ': FALSE']):
            return "NO"

    return ""


def regex_extract_visualization_type(raw_output):
    text = strip_code_fences(raw_output)
    upper = text.upper()

    patterns = [
        r'"?tipo_visualizzazione"?\s*:\s*"([^"]+)"',
        r'"?tipo_visualizzazione"?\s*:\s*([^\n,\}]+)',
        r'"?visualization_type"?\s*:\s*"([^"]+)"',
        r'"?visualization_type"?\s*:\s*([^\n,\}]+)',
        r'"?tipo"?\s*:\s*"([^"]+)"',
        r'"?tipo"?\s*:\s*([^\n,\}]+)',
    ]

    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            normalized = normalize_visualization_type(m.group(1))
            if normalized:
                return normalized

    inferred = infer_visualization_type_from_free_text(text)
    if inferred:
        return inferred

    if "INTERACTIVE 3D" in upper or ('"AR"' not in upper and (" 3D" in upper or "360" in upper)):
        return "Interactive 3D"
    if '"AR"' in upper or re.search(r'\bAR\b', upper):
        return "AR"
    if "STATIC 2D" in upper or " 2D" in upper or "STATIC" in upper:
        return "Static 2D"

    return ""


def parse_ollama_classification(raw_output):
    parsed = try_parse_json_candidates(raw_output)

    if parsed is not None:
        attivo = normalize_yes_no_value(parsed.get("attivo", "")) or normalize_yes_no_value(parsed.get("active", ""))
        confidence = normalize_confidence(parsed.get("confidence", ""))
        motivo = normalize_space(parsed.get("motivo", "")) or normalize_space(parsed.get("reason", ""))

        if attivo not in YES_NO_VALUES:
            attivo = regex_extract_attivo(raw_output)

        if not motivo:
            motivo = regex_extract_field(raw_output, "motivo") or regex_extract_field(raw_output, "reason")

        if attivo in YES_NO_VALUES:
            return attivo, confidence, motivo or "Reason not provided by the model", ""

    attivo = regex_extract_attivo(raw_output)
    confidence = normalize_confidence(regex_extract_field(raw_output, "confidence"))
    motivo = regex_extract_field(raw_output, "motivo") or regex_extract_field(raw_output, "reason")

    if attivo in YES_NO_VALUES:
        parser_warning = "Ollama response was not perfect JSON, but it was recovered with a permissive parser"
        return attivo, confidence, motivo or "Reason partially recovered", parser_warning

    upper = (raw_output or "").upper()
    if "SI" in upper and "NO" not in upper:
        return "SI", confidence, motivo or "Classification inferred from model text", "Weak fallback"
    if "YES" in upper and "NO" not in upper:
        return "SI", confidence, motivo or "Classification inferred from model text", "Weak fallback"
    if "NO" in upper and "SI" not in upper and "YES" not in upper:
        return "NO", confidence, motivo or "Classification inferred from model text", "Weak fallback"

    raise ValueError(f"Unable to interpret Ollama response: {raw_output}")


def parse_ollama_visualization_classification(raw_output):
    parsed = try_parse_json_candidates(raw_output)

    if parsed is not None:
        candidate_fields = [
            parsed.get("tipo_visualizzazione", ""),
            parsed.get("visualization_type", ""),
            parsed.get("tipo", ""),
            parsed.get("type", ""),
        ]

        tipo = ""
        for candidate in candidate_fields:
            tipo = normalize_visualization_type(candidate)
            if tipo:
                break

        confidence = normalize_confidence(parsed.get("confidence", ""))
        motivo = normalize_space(parsed.get("motivo", "")) or normalize_space(parsed.get("reason", ""))

        if not tipo:
            tipo = regex_extract_visualization_type(raw_output)

        if not motivo:
            motivo = regex_extract_field(raw_output, "motivo") or regex_extract_field(raw_output, "reason")

        if tipo in ALLOWED_VISUALIZATION_TYPES:
            return tipo, confidence, motivo or "Reason not provided by the model", ""

    tipo = regex_extract_visualization_type(raw_output)
    confidence = normalize_confidence(regex_extract_field(raw_output, "confidence"))
    motivo = regex_extract_field(raw_output, "motivo") or regex_extract_field(raw_output, "reason")

    if tipo in ALLOWED_VISUALIZATION_TYPES:
        parser_warning = "Ollama visualization response was recovered with a permissive parser"
        return tipo, confidence, motivo or "Reason partially recovered", parser_warning

    raise ValueError(f"Unable to interpret visualization classification: {raw_output}")




def normalize_mobile_score_value(value):
    if value is None or value == "":
        return ""

    if isinstance(value, str):
        value = normalize_space(value)
        if not value:
            return ""
        m = re.search(r'(?<!\d)([1-5])(?!\d)', value)
        if m:
            return int(m.group(1))

    try:
        num = int(round(float(value)))
        if MOBILE_MIN_SCORE <= num <= MOBILE_MAX_SCORE:
            return num
    except Exception:
        pass

    return ""


def parse_ollama_mobile_assessment(raw_output):
    parsed = try_parse_json_candidates(raw_output)

    if parsed is not None:
        candidate_fields = [
            parsed.get("mobile_score", ""),
            parsed.get("score", ""),
            parsed.get("rating", ""),
            parsed.get("mobile_rating", ""),
        ]

        score = ""
        for candidate in candidate_fields:
            score = normalize_mobile_score_value(candidate)
            if score != "":
                break

        confidence = normalize_confidence(parsed.get("confidence", ""))
        reason = (
            normalize_space(parsed.get("reason", ""))
            or normalize_space(parsed.get("motivo", ""))
            or normalize_space(parsed.get("summary", ""))
        )

        if score == "":
            score = (
                normalize_mobile_score_value(regex_extract_field(raw_output, "mobile_score"))
                or normalize_mobile_score_value(regex_extract_field(raw_output, "score"))
                or normalize_mobile_score_value(regex_extract_field(raw_output, "rating"))
                or normalize_mobile_score_value(regex_extract_field(raw_output, "mobile_rating"))
            )

        if not reason:
            reason = (
                regex_extract_field(raw_output, "reason")
                or regex_extract_field(raw_output, "motivo")
                or regex_extract_field(raw_output, "summary")
            )

        if score != "":
            return score, confidence, reason or "Reason not provided by the model", ""

    score = (
        normalize_mobile_score_value(regex_extract_field(raw_output, "mobile_score"))
        or normalize_mobile_score_value(regex_extract_field(raw_output, "score"))
        or normalize_mobile_score_value(regex_extract_field(raw_output, "rating"))
        or normalize_mobile_score_value(regex_extract_field(raw_output, "mobile_rating"))
    )
    confidence = normalize_confidence(regex_extract_field(raw_output, "confidence"))
    reason = (
        regex_extract_field(raw_output, "reason")
        or regex_extract_field(raw_output, "motivo")
        or regex_extract_field(raw_output, "summary")
    )

    if score != "":
        parser_warning = "Ollama mobile assessment response was recovered with a permissive parser"
        return score, confidence, reason or "Reason partially recovered", parser_warning

    raise ValueError(f"Unable to interpret mobile assessment: {raw_output}")


def parse_ollama_selected_urls(raw_output, available_urls):
    parsed = try_parse_json_candidates(raw_output)
    selected = []

    if parsed is not None:
        raw_list = parsed.get("selected_urls", [])
        if isinstance(raw_list, list):
            for item in raw_list:
                item = normalize_space(item)
                if item and item in available_urls and item not in selected:
                    selected.append(item)

    if not selected:
        for url in available_urls:
            if url in raw_output and url not in selected:
                selected.append(url)

    return selected[:ALTERNATIVE_CANDIDATES_TO_OPEN]


def parse_ollama_candidate_assessment(raw_output):
    parsed = try_parse_json_candidates(raw_output)

    if parsed is not None:
        match_prodotto = (
            normalize_yes_no_value(parsed.get("match_prodotto", ""))
            or normalize_yes_no_value(parsed.get("product_match", ""))
            or normalize_yes_no_value(parsed.get("match", ""))
        )
        if match_prodotto not in YES_NO_VALUES:
            match_prodotto = (
                regex_extract_yes_no_field(raw_output, "match_prodotto")
                or regex_extract_yes_no_field(raw_output, "product_match")
                or regex_extract_yes_no_field(raw_output, "match")
            )

        attivo = normalize_yes_no_value(parsed.get("attivo", "")) or normalize_yes_no_value(parsed.get("active", ""))
        if attivo not in YES_NO_VALUES:
            attivo = regex_extract_attivo(raw_output)

        confidence = normalize_confidence(parsed.get("confidence", ""))
        motivo = (
            normalize_space(parsed.get("motivo", ""))
            or normalize_space(parsed.get("reason", ""))
            or regex_extract_field(raw_output, "motivo")
            or regex_extract_field(raw_output, "reason")
        )

        if match_prodotto in YES_NO_VALUES and attivo in YES_NO_VALUES:
            return match_prodotto, attivo, confidence, motivo or "Reason not provided by the model", ""

    match_prodotto = (
        regex_extract_yes_no_field(raw_output, "match_prodotto")
        or regex_extract_yes_no_field(raw_output, "product_match")
        or regex_extract_yes_no_field(raw_output, "match")
    )
    attivo = regex_extract_attivo(raw_output)
    confidence = normalize_confidence(regex_extract_field(raw_output, "confidence"))
    motivo = regex_extract_field(raw_output, "motivo") or regex_extract_field(raw_output, "reason")

    if match_prodotto in YES_NO_VALUES and attivo in YES_NO_VALUES:
        return match_prodotto, attivo, confidence, motivo or "Reason partially recovered", "Permissive parser"

    raise ValueError(f"Unable to interpret alternative candidate assessment: {raw_output}")


# =========================
# EURISTICHE CONFIGURATORE ATTIVO
# =========================
def extract_domain(url):
    try:
        host = urlparse(url).netloc.lower().strip()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""




def get_site_root_url(url):
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return ""
        return f"{parsed.scheme}://{parsed.netloc}/"
    except Exception:
        return ""


def normalize_url_for_dedup(url):
    url = normalize_space(url)
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        path = parsed.path or "/"
        if path != "/":
            path = path.rstrip("/") or "/"
        normalized = parsed._replace(query="", fragment="", path=path)
        return normalized.geturl()
    except Exception:
        return url


def tokenize_company_name(company):
    raw = normalize_space(company).lower()
    if not raw:
        return []
    tokens = re.findall(r"[a-z0-9]+", raw)
    stop = {"the", "and", "of", "srl", "spa", "inc", "llc", "ltd", "gmbh", "sa", "sas", "co"}
    cleaned = []
    for token in tokens:
        if token in stop:
            continue
        if len(token) <= 2:
            continue
        cleaned.append(token)
    return cleaned


def is_excluded_external_url(url):
    url_l = (url or "").lower()
    excluded_fragments = [
        "configurator-database.com",
        "google.com",
        "googleusercontent.com",
        "youtube.com",
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "pinterest.",
        "twitter.com",
        "x.com",
        "tiktok.com",
        "freelancer.com",
        "upwork.com",
        "fiverr.com",
        "peopleperhour.com",
        "guru.com",
        "indeed.com",
        "glassdoor.com",
    ]
    return any(fragment in url_l for fragment in excluded_fragments)


def looks_like_official_site_candidate(url, anchor_text, company_tokens=None):
    url_l = (url or "").lower()
    text_l = normalize_space(anchor_text).lower()
    full = f"{url_l} {text_l}"

    negative = [
        "/blog", "/news", "/article", "/articles", "/journal", "/story", "/stories",
        "/review", "/reviews", "/test", "forum", "press", "editorial",
        "amazon.", "ebay.", "etsy.", "wikipedia.org", "youtube.com",
    ]
    if any(sig in full for sig in negative):
        return False

    positive = [
        "website", "official", "site officiel", "official site", "shop", "store",
        "custom", "configurator", "configurateur", "builder", "designer",
        "personaliz", "personnalis", "design your own", "back to website"
    ]
    if any(sig in full for sig in positive):
        return True

    company_tokens = company_tokens or []
    domain = extract_domain(url)
    if company_tokens and domain:
        hits = sum(1 for token in company_tokens if token in domain)
        if hits >= 1:
            return True

    return False


def extract_external_seed_urls_from_page(page, company, max_links=MAX_SEED_URLS):
    try:
        page_url = page.url
    except Exception:
        page_url = ""

    try:
        raw_links = page.evaluate(r"""
        () => {
            const anchors = [...document.querySelectorAll('a[href]')];
            const out = [];
            const seen = new Set();
            for (const a of anchors) {
                const href = (a.href || a.getAttribute('href') || '').trim();
                if (!href) continue;
                const text = ((a.innerText || a.textContent || a.getAttribute('aria-label') || '')).replace(/\\s+/g, ' ').trim();
                const key = href.toLowerCase() + '||' + text.toLowerCase();
                if (seen.has(key)) continue;
                seen.add(key);
                out.push({href, text});
                if (out.length >= 250) break;
            }
            return out;
        }
        """)
    except Exception:
        return []

    company_tokens = tokenize_company_name(company)
    candidates = []
    seen = set()

    for item in raw_links:
        href = normalize_space(item.get("href", ""))
        text_value = normalize_space(item.get("text", ""))
        if not href:
            continue
        try:
            abs_url = urljoin(page_url, href)
        except Exception:
            abs_url = href

        abs_url = normalize_url_for_dedup(abs_url)
        if not abs_url.lower().startswith(("http://", "https://")):
            continue
        if is_excluded_external_url(abs_url):
            continue
        if domains_compatible(abs_url, page_url):
            continue
        if abs_url in seen:
            continue

        score = 0
        if looks_like_official_site_candidate(abs_url, text_value, company_tokens):
            score += 6
        domain = extract_domain(abs_url)
        token_hits = sum(1 for token in company_tokens if token in domain)
        score += min(token_hits * 3, 6)
        combined = f"{abs_url.lower()} {text_value.lower()}"
        if any(sig in combined for sig in ["website", "official", "shop", "store"]):
            score += 2
        if text_value:
            score += 1
        if score <= 0:
            continue

        seen.add(abs_url)
        candidates.append((score, abs_url, text_value))

    candidates.sort(key=lambda x: (-x[0], x[1]))
    return [{"url": url, "text": text_value, "score": score} for score, url, text_value in candidates[:max_links]]


def build_internal_discovery_seed_urls(detail_page, configurator_url, original_final_url, company):
    seeds = []

    def add(url):
        normalized = normalize_url_for_dedup(url)
        if normalized and normalized not in seeds:
            seeds.append(normalized)

    add(original_final_url)
    add(configurator_url)

    for source_url in [original_final_url, configurator_url]:
        if source_url:
            add(get_site_root_url(source_url))

    for item in extract_external_seed_urls_from_page(detail_page, company, max_links=MAX_SEED_URLS):
        add(item.get("url", ""))
        add(get_site_root_url(item.get("url", "")))

    return seeds[:MAX_SEED_URLS]


def count_distinct_keyword_hits(text, keywords):
    text_l = (text or "").lower()
    return sum(1 for kw in keywords if kw in text_l)


def has_step_like_headings(dom_signals):
    texts = []
    for key in ["heading_texts", "label_texts", "button_texts"]:
        texts.extend(dom_signals.get(key, []))

    patterns = [
        r"\bstep\s*\d+",
        r"\b\d+\s*[\.)-]\s*",
        r"\bselect\b",
        r"\bchoose\b",
        r"\bshape\b",
        r"\bsize\b",
        r"\bpattern\b",
        r"\bcolor\b",
        r"\bmaterial\b",
        r"\bforma\b",
        r"\bmisura\b",
        r"\bcolore\b",
        r"\bmateriale\b",
        r"\bseleziona\b",
        r"\bscegli\b",
    ]

    matches = 0
    for t in texts:
        t_l = (t or "").lower()
        if any(re.search(p, t_l) for p in patterns):
            matches += 1
    return matches >= 2


def count_short_choice_labels(dom_signals):
    ignore_texts = {
        "shop", "custom", "gift cards", "gift card", "search", "account", "cart", "bag", "bags",
        "menu", "home", "contact", "about", "wishlist", "login", "log in", "sign up", "sale",
        "new arrivals", "collections", "view all", "all", "products"
    }

    candidates = []
    for key in ["link_texts", "button_texts", "heading_texts"]:
        candidates.extend(dom_signals.get(key, []))

    cleaned = []
    seen = set()
    for text in candidates:
        t = normalize_space(text)
        if not t:
            continue
        t_l = t.lower()
        if t_l in ignore_texts:
            continue
        if any(x in t_l for x in ["add to cart", "buy now", "learn more", "read more", "shop now"]):
            continue
        if len(t) > 28:
            continue
        if len(t.split()) > 4:
            continue
        if not re.search(r"[a-zA-Z]", t):
            continue
        if t_l in seen:
            continue
        seen.add(t_l)
        cleaned.append(t)
    return len(cleaned)


def detect_configurator_entry_page(title, final_url, visible_text, dom_signals):
    combined_text = " ".join([
        title or "",
        final_url or "",
        visible_text or "",
        " ".join(dom_signals.get("heading_texts", [])),
        " ".join(dom_signals.get("button_texts", [])),
        " ".join(dom_signals.get("link_texts", [])),
    ]).lower()

    url_l = (final_url or "").lower()
    custom_path_signals = [
        "/custom",
        "/custom/",
        "pages/custom",
        "design-your-own",
        "designyourown",
        "personalize",
        "personalise",
        "personalizar",
        "personnaliser",
        "personnalis",
        "konfigurator",
        "configurador",
        "configure",
        "configurator",
        "configurateur",
        "builder",
        "designer",
    ]
    custom_copy_signals = [
        "design your own",
        "build your",
        "custom",
        "customize",
        "customise",
        "personalize",
        "personalise",
        "personalizar",
        "personnaliser",
        "personnalisez",
        "personnalisable",
        "konfigurieren",
        "konfigurator",
        "configura",
        "configure",
        "configurator",
        "configurateur",
        "start with",
        "choose your",
        "select your",
        "pick your",
    ]
    entry_copy_signals = [
        "choose bag",
        "choose your bag",
        "choose a bag",
        "select your bag",
        "select a bag",
        "pick your bag",
        "choose style",
        "choose your style",
        "select style",
        "choose model",
        "select model",
        "choose product",
        "select product",
        "choisissez",
        "sélectionnez",
        "seleccione",
        "wählen sie",
        "modell wählen",
        "produkt wählen",
        "producto",
        "modelo",
    ]

    has_custom_path = any(signal in url_l for signal in custom_path_signals)
    has_custom_copy = any(signal in combined_text for signal in custom_copy_signals)
    has_entry_copy = any(signal in combined_text for signal in entry_copy_signals)
    short_choice_count = count_short_choice_labels(dom_signals)
    image_count = dom_signals.get("img_count", 0)
    button_count = dom_signals.get("button_count", 0)
    link_count = len(dom_signals.get("link_texts", []))

    if has_custom_path and short_choice_count >= 3 and image_count >= 3 and (has_custom_copy or has_entry_copy or link_count >= 4):
        return "SI", "Classificazione deterministica: landing page del configuratore con scelta del prodotto/modello iniziale"

    if has_entry_copy and short_choice_count >= 3 and image_count >= 3 and (has_custom_path or has_custom_copy):
        return "SI", "Classificazione deterministica: prima schermata del configuratore con selezione del prodotto da personalizzare"

    if has_custom_path and image_count >= 4 and short_choice_count >= 4 and button_count <= 3:
        return "SI", "Classificazione deterministica: pagina dedicata al percorso custom con griglia di modelli iniziali"

    return None


def detect_image_only_placeholder_page(title, final_url, visible_text, dom_signals):
    title_l = (title or "").lower()
    url_l = (final_url or "").lower()
    text_l = normalize_space(visible_text).lower()
    full_text = " ".join([
        title_l,
        url_l,
        text_l,
        " ".join(x.lower() for x in dom_signals.get("heading_texts", [])),
        " ".join(x.lower() for x in dom_signals.get("button_texts", [])),
        " ".join(x.lower() for x in dom_signals.get("link_texts", [])),
    ])

    strong_controls = has_strong_configurator_controls(dom_signals)
    entry_page_positive = detect_configurator_entry_page(title, final_url, visible_text, dom_signals)
    if strong_controls or entry_page_positive is not None:
        return None

    img_count = dom_signals.get("img_count", 0)
    large_image_count = dom_signals.get("large_image_count", 0)
    visible_text_length = dom_signals.get("visible_text_length", len(text_l))
    meaningful_text_block_count = dom_signals.get("meaningful_text_block_count", 0)
    anchor_count = dom_signals.get("anchor_count", 0)
    button_count = dom_signals.get("button_count", 0)
    form_count = dom_signals.get("form_count", 0)
    input_count = dom_signals.get("input_count", 0)
    select_count = dom_signals.get("select_count", 0)
    canvas_count = dom_signals.get("canvas_count", 0)
    webgl_canvas_count = dom_signals.get("webgl_canvas_count", 0)
    model_viewer_count = dom_signals.get("model_viewer_count", 0)
    iframe_count = dom_signals.get("iframe_count", 0)
    short_choice_count = count_short_choice_labels(dom_signals)
    image_src_hints = [s.lower() for s in dom_signals.get("img_src_hints", [])]
    static_image_src_hits = sum(1 for s in image_src_hints if any(ext in s for ext in [".jpg", ".jpeg", ".png", ".webp"]))

    non_tool_copy_signals = [
        "coming soon",
        "launching soon",
        "teaser",
        "hero image",
        "hero-banner",
        "banner",
        "lookbook",
        "campaign",
        "editorial",
        "poster",
    ]

    if (
        img_count == 1
        and large_image_count >= 1
        and visible_text_length <= 140
        and meaningful_text_block_count <= 2
        and anchor_count <= 3
        and button_count <= 2
        and form_count == 0
        and input_count == 0
        and select_count == 0
        and canvas_count == 0
        and webgl_canvas_count == 0
        and model_viewer_count == 0
        and iframe_count == 0
        and short_choice_count <= 2
    ):
        return "NO", "Classificazione deterministica: pagina composta essenzialmente da una singola immagine statica, senza vero configuratore"

    if (
        img_count <= 2
        and large_image_count >= 1
        and static_image_src_hits >= 1
        and visible_text_length <= 220
        and meaningful_text_block_count <= 3
        and anchor_count <= 4
        and short_choice_count <= 2
        and not strong_controls
        and canvas_count == 0
        and webgl_canvas_count == 0
        and model_viewer_count == 0
    ):
        return "NO", "Classificazione deterministica: pagina dominata da immagine/banner statico, non ambiente di configurazione"

    if any(signal in full_text for signal in non_tool_copy_signals) and img_count <= 2 and meaningful_text_block_count <= 3 and not strong_controls:
        return "NO", "Classificazione deterministica: pagina teaser/editoriale con immagine, non configuratore"

    return None


def compute_configurator_control_score(dom_signals):
    score = 0
    if dom_signals.get("form_count", 0) >= 1:
        score += 1
    if dom_signals.get("input_count", 0) >= 6:
        score += 2
    if dom_signals.get("checkbox_count", 0) + dom_signals.get("radio_count", 0) >= 3:
        score += 2
    if dom_signals.get("range_count", 0) >= 1:
        score += 2
    if dom_signals.get("number_input_count", 0) >= 1:
        score += 1
    if dom_signals.get("select_count", 0) >= 1 or dom_signals.get("option_count", 0) >= 6:
        score += 1
    if dom_signals.get("button_count", 0) >= 2:
        score += 1
    if dom_signals.get("svg_count", 0) >= 5:
        score += 1
    return score


def has_strong_configurator_controls(dom_signals):
    control_score = compute_configurator_control_score(dom_signals)
    if control_score >= 5:
        return True

    if (
        dom_signals.get("checkbox_count", 0) + dom_signals.get("radio_count", 0) >= 4
        and (dom_signals.get("range_count", 0) >= 1 or dom_signals.get("number_input_count", 0) >= 1)
    ):
        return True

    if dom_signals.get("input_count", 0) >= 8 and dom_signals.get("button_count", 0) >= 2:
        return True

    return False


def detect_non_tool_context_page(title, final_url, visible_text, dom_signals=None):
    title_l = (title or "").lower()
    url_l = (final_url or "").lower()
    text_l = (visible_text or "").lower()
    full_text = " ".join([title_l, url_l, text_l])
    domain = extract_domain(final_url)

    if dom_signals is None:
        dom_signals = {}

    strong_controls = has_strong_configurator_controls(dom_signals)

    image_only_negative = detect_image_only_placeholder_page(title, final_url, visible_text, dom_signals)
    if image_only_negative is not None:
        return image_only_negative

    explicit_bad_domains = [
        "freelancer.com",
        "upwork.com",
        "fiverr.com",
        "peopleperhour.com",
        "guru.com",
        "indeed.com",
        "glassdoor.com",
    ]
    if any(domain == bad or domain.endswith("." + bad) for bad in explicit_bad_domains):
        return "NO", f"Classificazione deterministica: pagina marketplace/job platform ({domain})"

    job_marketplace_signals = [
        "post a project",
        "hire freelancers",
        "about the client",
        "client verification",
        "member since",
        "payment method verified",
        "other jobs from this client",
        "posted over",
        "completed",
        "/ hour",
        "per hour",
        "bids",
        "bid now",
        "project budget",
        "freelancer",
        "upwork",
        "fiverr",
        "peopleperhour",
    ]

    editorial_signals = [
        "interview with",
        "blog",
        "article",
        "news",
        "case study",
        "press release",
        "read more",
        "published",
        "author",
        "journal",
        "story",
        "stories",
        "getting to know",
        "review",
        "reviews",
        "hands-on",
        "test outdoor",
        "test sac",
        "avis",
        "essai",
    ]

    marketplace_hits = [s for s in job_marketplace_signals if s in full_text]
    editorial_hits = [s for s in editorial_signals if s in full_text]

    if not strong_controls and len(marketplace_hits) >= 2:
        return "NO", f"Classificazione deterministica: pagina informativa/job post, non configuratore ({', '.join(marketplace_hits[:3])})"

    if not strong_controls and len(editorial_hits) >= 2:
        return "NO", f"Classificazione deterministica: pagina editoriale/articolo, non configuratore ({', '.join(editorial_hits[:3])})"

    return None


def looks_generic_homepage_like_page(title, final_url, visible_text, dom_signals):
    url_l = (final_url or "").lower()
    text_blob = " ".join([
        title or "",
        visible_text or "",
        " ".join(dom_signals.get("heading_texts", [])),
        " ".join(dom_signals.get("button_texts", [])),
        " ".join(dom_signals.get("link_texts", [])),
    ]).lower()

    parsed = urlparse(final_url or "")
    path = (parsed.path or "/").strip().lower()
    segments = [seg for seg in path.split("/") if seg]
    locale_like = re.compile(r"^[a-z]{2}(?:-[a-z]{2})?$", re.IGNORECASE)
    rootish_segments = [seg for seg in segments if not locale_like.match(seg)]
    rootish = len(rootish_segments) == 0

    custom_path = any(token in url_l for token in [
        "configurator", "builder", "custom", "design", "personal", "watchstudio", "studio", "mix-and-match", "mixandmatch", "unique"
    ])
    if custom_path:
        return False

    if detect_configurator_entry_page(title, final_url, visible_text, dom_signals) is not None:
        return False

    if has_strong_configurator_controls(dom_signals):
        return False

    nav_keywords = [
        "shop", "discover", "support", "service", "services", "mobile", "phones", "phone", "tablet", "tv",
        "audio", "appliance", "watches", "watch", "wearables", "accessories", "offers", "search", "account",
        "cart", "bag", "wishlist", "login", "log in", "sign in", "home"
    ]
    custom_copy = [
        "customize", "customise", "personalize", "personalise", "configurator", "builder", "design your",
        "build your", "mix and match", "watch studio", "studio", "unique"
    ]

    nav_hits = count_distinct_keyword_hits(text_blob, nav_keywords)
    custom_hits = count_distinct_keyword_hits(text_blob, custom_copy)
    control_score = compute_configurator_control_score(dom_signals)
    anchor_count = dom_signals.get("anchor_count", 0)
    button_count = dom_signals.get("button_count", 0)
    meaningful_text_block_count = dom_signals.get("meaningful_text_block_count", 0)

    if rootish and nav_hits >= 4 and control_score <= 2 and anchor_count >= 8 and meaningful_text_block_count <= 10 and custom_hits <= 2:
        return True

    if rootish and nav_hits >= 5 and button_count <= 6 and control_score <= 1 and custom_hits <= 1:
        return True

    return False


def detect_hard_positive_configurator(title, final_url, visible_text, dom_signals):
    negative_context = detect_non_tool_context_page(title, final_url, visible_text, dom_signals)
    if negative_context is not None:
        return None

    entry_page_positive = detect_configurator_entry_page(title, final_url, visible_text, dom_signals)
    if entry_page_positive is not None:
        return entry_page_positive

    if looks_generic_homepage_like_page(title, final_url, visible_text, dom_signals):
        return None

    combined_text = " ".join([
        title or "",
        final_url or "",
        visible_text or "",
        " ".join(dom_signals.get("heading_texts", [])),
        " ".join(dom_signals.get("button_texts", [])),
        " ".join(dom_signals.get("label_texts", [])),
        " ".join(dom_signals.get("link_texts", [])),
    ]).lower()

    strong_action_keywords = [
        "configurator", "configurateur", "configurador", "konfigurator",
        "customizer", "customiser", "product builder", "builder", "designer",
        "personalize", "personalise", "personalizar", "personnaliser",
        "configure", "configura", "konfigurieren", "build your", "design your",
        "customise", "customize",
    ]
    option_keywords = [
        "choose", "select", "option", "variant", "size", "shape", "material",
        "color", "colour", "fabric", "pattern", "width", "height", "length",
        "dimension", "finish", "border", "text", "engraving", "upload", "preview",
        "step", "steps", "forma", "misura", "larghezza", "altezza", "colore",
        "materiale", "tessuto", "bordo", "seleziona", "scegli",
        "choisissez", "sélectionnez", "couleur", "matière", "taille", "largeur",
        "hauteur", "motif", "tissu", "seleccione", "tamaño", "modelo",
        "produkt", "größe", "farbe", "muster",
    ]

    action_hits = count_distinct_keyword_hits(combined_text, strong_action_keywords)
    option_hits = count_distinct_keyword_hits(combined_text, option_keywords)
    control_score = compute_configurator_control_score(dom_signals)

    url_has_config_path = any(token in (final_url or "").lower() for token in ["configurator", "builder", "custom", "design", "personal"])
    step_like = has_step_like_headings(dom_signals)

    if url_has_config_path and control_score >= 3 and (action_hits >= 1 or option_hits >= 3 or step_like):
        return "SI", "Classificazione deterministica: URL e controlli coerenti con un configuratore"

    if action_hits >= 1 and control_score >= 3 and option_hits >= 2:
        return "SI", "Classificazione deterministica: segnali espliciti di customizer/configurator"

    if step_like and control_score >= 4 and option_hits >= 3:
        return "SI", "Classificazione deterministica: pagina multi-step con molte opzioni configurabili"

    if (
        dom_signals.get("checkbox_count", 0) + dom_signals.get("radio_count", 0) >= 4
        and (dom_signals.get("range_count", 0) >= 1 or dom_signals.get("number_input_count", 0) >= 1)
        and option_hits >= 4
    ):
        return "SI", "Classificazione deterministica: opzioni selezionabili + controlli dimensionali tipici di configuratore"

    return None


def fallback_attivo_from_heuristics(title, final_url, visible_text, dom_signals, parse_exception=None):
    context_negative = detect_non_tool_context_page(title, final_url, visible_text, dom_signals)
    if context_negative is not None:
        attivo, motivo = context_negative
        if parse_exception:
            motivo = f"{motivo} | fallback dopo errore parser/risposta Ollama: {parse_exception}"
        return attivo, motivo, 100, "hard_rule"

    hard_positive = detect_hard_positive_configurator(title, final_url, visible_text, dom_signals)
    if hard_positive is not None:
        attivo, motivo = hard_positive
        if parse_exception:
            motivo = f"{motivo} | fallback dopo errore parser/risposta Ollama: {parse_exception}"
        return attivo, motivo, 85, "heuristic_active"

    hard_negative = detect_hard_negative_page(title, final_url, visible_text)
    if hard_negative is not None:
        attivo, motivo = hard_negative
        if parse_exception:
            motivo = f"{motivo} | fallback dopo errore parser/risposta Ollama: {parse_exception}"
        return attivo, motivo, 100, "hard_rule"

    return None

# =========================
# LOGICA IBRIDA - ATTIVO
# =========================
def detect_hard_negative_page(title, final_url, visible_text):
    title_l = (title or "").lower()
    url_l = (final_url or "").lower()
    text_l = (visible_text or "").lower()

    full_text = " ".join([title_l, url_l, text_l])

    domain_sale_signals = [
        "this domain is for sale",
        "domain for sale",
        "buy this domain",
        "buy now",
        "start payment plan",
        "domain expert",
        "inquire about this domain",
        "make an offer",
        "own this domain",
        "purchase this domain",
        "acquire this domain",
        "domain name for sale",
        "parked free",
        "sedo domain parking",
    ]

    domain_sale_providers = [
        "hugedomains",
        "sedo",
        "afternic",
        "dan.com",
        "undeveloped.com",
        "parkingcrew",
        "bodis",
        "uniregistry",
        "godaddy broker",
        "domainmarket",
        "namebright",
        "buydomains",
        "perfectdomain",
    ]

    hard_error_signals = [
        "404 not found",
        "page not found",
        "error 404",
        "site can't be reached",
        "this site can’t be reached",
        "server not found",
        "dns_probe_finished",
        "access denied",
        "forbidden",
        "domain may be for sale",
        "ssl error",
        "there is no ssl certificate configured for this domain",
        "err_ssl",
        "your connection is not private",
        "privacy error",
        "secure connection failed",
        "connection is not private",
        "domain blocked",
        "blocked domain",
        "this domain has been blocked",
        "this domain was blocked",
        "domain suspended",
        "this domain has been suspended",
        "site suspended",
        "account suspended",
        "website disabled",
        "website unavailable",
        "domain disabled",
        "domain deactivated",
        "diese domain wurde gesperrt",
        "domain wurde gesperrt",
        "gesperrte domain",
        "gesperrt!",
        "dominio sospeso",
        "dominio bloccato",
        "sitio suspendido",
        "dominio suspendido",
        "dominio bloqueado",
        "domaine suspendu",
        "domaine bloqué",
        "domaine bloque",
    ]

    matched_sale_phrases = [s for s in domain_sale_signals if s in full_text]
    matched_sale_providers = [s for s in domain_sale_providers if s in full_text]
    matched_error_signals = [s for s in hard_error_signals if s in full_text]

    short_blocked_patterns = [
        ("gesperrt" in text_l and "domain" in text_l),
        ("suspended" in text_l and any(token in text_l for token in ["domain", "site", "website", "account"])),
        ("blocked" in text_l and any(token in text_l for token in ["domain", "site", "website", "account"])),
        ("bloqué" in text_l and "domaine" in text_l),
        ("bloque" in text_l and "domaine" in text_l),
        ("bloqueado" in text_l and "dominio" in text_l),
        ("bloccato" in text_l and "dominio" in text_l),
        ("suspendido" in text_l and "dominio" in text_l),
        ("sospeso" in text_l and "dominio" in text_l),
    ]

    if matched_sale_providers and (matched_sale_phrases or "domain" in full_text):
        return "NO", f"Deterministic classification: parked / domain sale page ({', '.join(matched_sale_providers[:3])})"

    if len(matched_sale_phrases) >= 2:
        return "NO", f"Deterministic classification: domain sale page ({', '.join(matched_sale_phrases[:3])})"

    if matched_error_signals:
        return "NO", f"Deterministic classification: evident error / blocked page ({', '.join(matched_error_signals[:3])})"

    if any(short_blocked_patterns):
        return "NO", "Deterministic classification: blocked or suspended domain page"

    return None


def evaluate_configurator_page_with_ollama(page):
    try:
        final_url = page.url
    except Exception:
        final_url = ""

    try:
        title = page.title()
    except Exception:
        title = ""

    try:
        visible_text = page.locator("body").inner_text()
    except Exception:
        visible_text = ""

    dom_signals = get_page_dom_signals(page)

    hard_negative = detect_hard_negative_page(title, final_url, visible_text)
    if hard_negative is not None:
        attivo, motivo = hard_negative
        return attivo, motivo, 100, title, final_url, "", "", "hard_rule"

    context_negative = detect_non_tool_context_page(title, final_url, visible_text, dom_signals)
    if context_negative is not None:
        attivo, motivo = context_negative
        return attivo, motivo, 100, title, final_url, "", "", "hard_rule"

    hard_positive = detect_hard_positive_configurator(title, final_url, visible_text, dom_signals)
    if hard_positive is not None:
        attivo, motivo = hard_positive
        return attivo, motivo, 90, title, final_url, "", "", "heuristic_active"

    visible_text_excerpt = compress_visible_text(visible_text, max_chars=6000)

    prompt = f"""
You are a web page classifier.

Decide whether the final page reached from the database link is an ACTIVE PRODUCT CONFIGURATOR.

Rules:
- Return SI if the page shows a real configurator, customizer, product builder, designer, or a page clearly dedicated to immediately starting the product configuration flow.
- The page language can be any language. Do not rely only on English or Italian keywords.
- Positive signals include editable options, steps, variants, colors, dimensions, materials, personalization controls, dynamic preview, and buttons or links to configure, customize, design, or build.
- A page can still be SI even if it is only the first step of the customization flow, for example a page where the user first chooses the base model or product to customize.
- Return NO if the page is a 404, an error page, a generic homepage, a corporate page, a generic ecommerce page, a standard catalog page, a plain product page without real configuration, or any page that does not actually let the user enter the configuration experience.
- Domain parking, domain sale pages, and domain marketplaces are ALWAYS NO.
- If the evidence is mixed, choose the most likely answer, but be conservative.
- Return ONLY one valid JSON object on a SINGLE LINE.
- Use confidence as an integer from 0 to 100.

Exact format:
{{"active":"SI","confidence":85,"reason":"brief explanation"}}

PAGE DATA

TITLE:
{title}

FINAL URL:
{final_url}

VISIBLE PAGE TEXT:
{visible_text_excerpt}

DOM / INTERACTION SIGNALS:
{json.dumps(dom_signals, ensure_ascii=False)}
""".strip()

    raw_output = call_ollama(prompt)
    try:
        attivo, confidence, motivo, parser_warning = parse_ollama_classification(raw_output)
        if attivo == "NO" and hard_positive is not None:
            _, heuristic_reason = hard_positive
            confidence = max(confidence or 0, 85)
            motivo = f"{motivo} | Correzione euristica: {heuristic_reason}"
            return "SI", motivo, confidence, title, final_url, raw_output, parser_warning, "ollama_plus_heuristic_active"
        return attivo, motivo, confidence, title, final_url, raw_output, parser_warning, "ollama"
    except Exception as exc:
        fallback = fallback_attivo_from_heuristics(title, final_url, visible_text, dom_signals, parse_exception=str(exc))
        if fallback is not None:
            attivo, motivo, confidence, decision_source = fallback
            return attivo, motivo, confidence, title, final_url, raw_output, "Fallback euristico dopo risposta Ollama non interpretabile", decision_source
        raise

def normalize_compatibility_score_value(value):
    if value is None or value == "":
        return ""

    if isinstance(value, str):
        value = normalize_space(value)
        if not value:
            return ""
        m = re.search(r'(?<!\d)([1-5])(?!\d)', value)
        if m:
            return int(m.group(1))

    try:
        num = int(round(float(value)))
        if 1 <= num <= 5:
            return num
    except Exception:
        pass

    return ""


def parse_ollama_compatibility_assessment(raw_output):
    parsed = try_parse_json_candidates(raw_output)

    if parsed is not None:
        candidate_fields = [
            parsed.get("compatibility_score", ""),
            parsed.get("compatibility_constraints_score", ""),
            parsed.get("constraint_score", ""),
            parsed.get("score", ""),
            parsed.get("rating", ""),
        ]

        score = ""
        for candidate in candidate_fields:
            score = normalize_compatibility_score_value(candidate)
            if score != "":
                break

        confidence = normalize_confidence(parsed.get("confidence", ""))
        reason = (
            normalize_space(parsed.get("reason", ""))
            or normalize_space(parsed.get("motivo", ""))
            or normalize_space(parsed.get("summary", ""))
        )

        if score == "":
            score = (
                normalize_compatibility_score_value(regex_extract_field(raw_output, "compatibility_score"))
                or normalize_compatibility_score_value(regex_extract_field(raw_output, "compatibility_constraints_score"))
                or normalize_compatibility_score_value(regex_extract_field(raw_output, "constraint_score"))
                or normalize_compatibility_score_value(regex_extract_field(raw_output, "score"))
                or normalize_compatibility_score_value(regex_extract_field(raw_output, "rating"))
            )

        if not reason:
            reason = (
                regex_extract_field(raw_output, "reason")
                or regex_extract_field(raw_output, "motivo")
                or regex_extract_field(raw_output, "summary")
            )

        if score != "":
            return score, confidence, reason or "Reason not provided by the model", ""

    score = (
        normalize_compatibility_score_value(regex_extract_field(raw_output, "compatibility_score"))
        or normalize_compatibility_score_value(regex_extract_field(raw_output, "compatibility_constraints_score"))
        or normalize_compatibility_score_value(regex_extract_field(raw_output, "constraint_score"))
        or normalize_compatibility_score_value(regex_extract_field(raw_output, "score"))
        or normalize_compatibility_score_value(regex_extract_field(raw_output, "rating"))
    )
    confidence = normalize_confidence(regex_extract_field(raw_output, "confidence"))
    reason = (
        regex_extract_field(raw_output, "reason")
        or regex_extract_field(raw_output, "motivo")
        or regex_extract_field(raw_output, "summary")
    )

    if score != "":
        parser_warning = "Ollama compatibility assessment response was recovered with a permissive parser"
        return score, confidence, reason or "Reason partially recovered", parser_warning

    raise ValueError(f"Unable to interpret compatibility assessment: {raw_output}")



# =========================
# LOGICA IBRIDA - TIPO VISUALIZZAZIONE (STEP 1)
# =========================
def detect_visualization_hard_rule(title, final_url, visible_text, dom_signals):
    network_signals = {
        "asset_3d_count": 0,
        "model_content_type_count": 0,
    }
    strong_primary_3d_evidence = (
        dom_signals.get("model_viewer_count", 0) > 0
        or dom_signals.get("webgl_canvas_count", 0) > 0
        or dom_signals.get("three_global", False)
        or dom_signals.get("babylon_global", False)
        or dom_signals.get("blend4web_global", False)
        or dom_signals.get("model_viewer_global", False)
    )
    full_text = " ".join([
        (title or "").lower(),
        (final_url or "").lower(),
        (visible_text or "").lower(),
        " ".join(x.lower() for x in dom_signals.get("ar_text_hints", [])),
        " ".join(x.lower() for x in dom_signals.get("rotate_text_hints", [])),
        " ".join(x.lower() for x in dom_signals.get("script_hints", [])),
    ])

    ar_keywords = [
        "augmented reality",
        "view in your space",
        "quick look",
        "scene viewer",
        "realtà aumentata",
        "realta aumentata",
        ".usdz",
    ]

    if (
        dom_signals.get("ar_rel_link_count", 0) > 0
        or dom_signals.get("usdz_link_count", 0) > 0
        or any(k in full_text for k in ar_keywords)
    ):
        return "Interactive 3D", "Classificazione deterministica: segnali AR/3D espliciti (AR accorpata a Interactive 3D)"

    rotate_hints_count = len(dom_signals.get("rotate_text_hints", []))
    model_viewer_count = dom_signals.get("model_viewer_count", 0)
    webgl_canvas_count = dom_signals.get("webgl_canvas_count", 0)

    three_d_script_signal = any(
        any(k in hint.lower() for k in ["three", "babylon", "model-viewer", "spline", "sketchfab", "verge3d", "playcanvas", "webgl"])
        for hint in dom_signals.get("script_hints", [])
    )

    strong_3d_interaction_signal = any(signal in full_text for signal in [
        "drag to rotate",
        "rotate the model",
        "spin",
        "360°",
        "360 degree",
        "360-degree",
        "360 view",
        "3d viewer",
        "interactive 3d",
    ])

    # Promuovi a 3D solo se esiste evidenza forte di viewer/modello realmente manipolabile.
    if model_viewer_count > 0:
        return "Interactive 3D", "Classificazione deterministica: presenza di model-viewer"

    if webgl_canvas_count > 0 and (rotate_hints_count > 0 or strong_3d_interaction_signal):
        return "Interactive 3D", "Classificazione deterministica: canvas WebGL con segnali di interazione 3D"

    if (dom_signals.get("three_global", False) or dom_signals.get("babylon_global", False) or dom_signals.get("model_viewer_global", False) or three_d_script_signal) and (rotate_hints_count > 0 or strong_3d_interaction_signal):
        return "Interactive 3D", "Classificazione deterministica: librerie 3D + segnali di interazione espliciti"

    # Se esistono librerie/global 3D ma non c'è evidenza di manipolazione, non promuovere a 3D.
    explicit_3d_tech_without_interaction = (
        model_viewer_count == 0
        and webgl_canvas_count == 0
        and rotate_hints_count == 0
        and not strong_3d_interaction_signal
        and (
            dom_signals.get("three_global", False)
            or dom_signals.get("babylon_global", False)
            or dom_signals.get("model_viewer_global", False)
            or three_d_script_signal
        )
    )

    strong_2d_configuration_signal = (
        dom_signals.get("img_count", 0) >= 1
        and (
            dom_signals.get("radio_count", 0) >= 2
            or dom_signals.get("checkbox_count", 0) >= 2
            or dom_signals.get("range_count", 0) >= 1
            or dom_signals.get("option_count", 0) >= 4
            or dom_signals.get("svg_count", 0) >= 4
        )
    )

    product_detail_like_static_page = (
        not strong_primary_3d_evidence
        and dom_signals.get("img_count", 0) >= 1
        and dom_signals.get("webgl_canvas_count", 0) == 0
        and network_signals.get("asset_3d_count", 0) == 0
        and network_signals.get("model_content_type_count", 0) == 0
        and dom_signals.get("model_viewer_count", 0) == 0
        and any(token in full_text for token in ["warenkorb", "paarpreis", "artikel-nr", "lieferzeit", "price", "add to cart", "cart", "sku", "product"])
    )

    if explicit_3d_tech_without_interaction and strong_2d_configuration_signal:
        return "Static 2D", "Classificazione deterministica: librerie 3D presenti ma senza evidenza di viewer manipolabile; configurazione visivamente 2D"

    if (
        rotate_hints_count == 0
        and model_viewer_count == 0
        and webgl_canvas_count == 0
        and strong_2d_configuration_signal
        and dom_signals.get("img_count", 0) >= 1
    ):
        return "Static 2D", "Classificazione deterministica: anteprime/immagini statiche con controlli di configurazione 2D"

    return None



def attach_network_resource_tracker(page):
    tracker = {"items": []}
    seen = set()

    def on_response(response):
        try:
            url = normalize_space(getattr(response, "url", "") or "")
        except Exception:
            url = ""
        if not url:
            return

        content_type = ""
        try:
            content_type = normalize_space(response.header_value("content-type") or "")
        except Exception:
            try:
                headers = response.headers
                if isinstance(headers, dict):
                    content_type = normalize_space(headers.get("content-type", ""))
            except Exception:
                content_type = ""

        key = f"{url.lower()}||{content_type.lower()}"
        if key in seen:
            return
        seen.add(key)
        tracker["items"].append({
            "url": url,
            "content_type": content_type,
        })

    page.on("response", on_response)
    return tracker


def get_accessible_child_frames(page):
    frames = []
    try:
        all_frames = page.frames
    except Exception:
        return frames

    main_frame = None
    try:
        main_frame = page.main_frame
    except Exception:
        main_frame = None

    for frame in all_frames or []:
        try:
            if main_frame is not None and frame == main_frame:
                continue
        except Exception:
            pass
        frames.append(frame)

    return frames


def get_context_resource_entries(context_obj, limit=250):
    try:
        return context_obj.evaluate(r"""
        (maxItems) => {
            const entries = performance.getEntriesByType('resource') || [];
            const out = [];
            const seen = new Set();

            for (const entry of entries) {
                const name = (entry.name || '').trim();
                const initiatorType = (entry.initiatorType || '').trim();
                if (!name) continue;
                const key = `${name.toLowerCase()}||${initiatorType.toLowerCase()}`;
                if (seen.has(key)) continue;
                seen.add(key);
                out.push({url: name, content_type: initiatorType});
                if (out.length >= maxItems) break;
            }

            return out;
        }
        """, limit) or []
    except Exception:
        return []


def get_context_dom_resource_entries(context_obj, limit=200):
    try:
        return context_obj.evaluate(r"""
        (maxItems) => {
            const selectors = ['script[src]', 'img[src]', 'iframe[src]', 'source[src]', 'model-viewer[src]', 'a[href]'];
            const out = [];
            const seen = new Set();

            for (const selector of selectors) {
                for (const el of document.querySelectorAll(selector)) {
                    const val = (el.getAttribute('src') || el.getAttribute('href') || el.src || el.href || '').trim();
                    if (!val) continue;
                    const key = val.toLowerCase();
                    if (seen.has(key)) continue;
                    seen.add(key);
                    out.push({url: val, content_type: ''});
                    if (out.length >= maxItems) return out;
                }
            }

            return out;
        }
        """, limit) or []
    except Exception:
        return []


def get_iframe_metrics(page):
    try:
        return page.evaluate(r"""
        () => {
            const viewportArea = Math.max((window.innerWidth || 1) * (window.innerHeight || 1), 1);
            let largeCount = 0;
            let visibleLargeCount = 0;
            const srcHints = [];
            const seen = new Set();

            for (const iframe of document.querySelectorAll('iframe')) {
                try {
                    const rect = iframe.getBoundingClientRect();
                    const area = Math.max(rect.width, 0) * Math.max(rect.height, 0);
                    const src = (iframe.getAttribute('src') || iframe.src || '').trim();
                    if (src && !seen.has(src.toLowerCase())) {
                        seen.add(src.toLowerCase());
                        srcHints.push(src);
                    }

                    const isLarge = (iframe.height && parseInt(iframe.height, 10) >= 500)
                        || rect.height >= 420
                        || area >= viewportArea * 0.18;
                    const isVisible = rect.bottom > 0 && rect.right > 0 && rect.top < (window.innerHeight || 0) && rect.left < (window.innerWidth || 0);

                    if (isLarge) largeCount += 1;
                    if (isLarge && isVisible) visibleLargeCount += 1;
                } catch (e) {}
            }

            return {
                large_iframe_count: largeCount,
                visible_large_iframe_count: visibleLargeCount,
                iframe_src_hints: srcHints.slice(0, 12)
            };
        }
        """) or {}
    except Exception:
        return {
            'large_iframe_count': 0,
            'visible_large_iframe_count': 0,
            'iframe_src_hints': []
        }


def collect_context_dom_signals_with_scroll(context_obj, max_steps=4, per_step_wait_seconds=0.35):
    snapshots = []

    try:
        first = get_page_dom_signals(context_obj)
        if isinstance(first, dict):
            snapshots.append(first)
    except Exception:
        pass

    try:
        scroll_meta = context_obj.evaluate(
            """
            () => ({
                scrollHeight: Math.max(
                    document.body ? document.body.scrollHeight : 0,
                    document.documentElement ? document.documentElement.scrollHeight : 0
                ),
                viewportHeight: window.innerHeight || 0
            })
            """
        ) or {}
    except Exception:
        scroll_meta = {}

    scroll_height = int(scroll_meta.get('scrollHeight', 0) or 0)
    viewport_height = int(scroll_meta.get('viewportHeight', 0) or 0)

    positions = [0]
    if scroll_height > 0 and viewport_height > 0 and scroll_height > int(viewport_height * 1.10):
        max_offset = max(scroll_height - viewport_height, 0)
        for i in range(1, max_steps + 1):
            positions.append(int(round(max_offset * i / max_steps)))

    deduped_positions = []
    seen_positions = set()
    for pos in positions:
        if pos in seen_positions:
            continue
        seen_positions.add(pos)
        deduped_positions.append(pos)

    for pos in deduped_positions[1:]:
        try:
            context_obj.evaluate("(y) => window.scrollTo(0, y)", pos)
            time.sleep(per_step_wait_seconds)
            snap = get_page_dom_signals(context_obj)
            if isinstance(snap, dict):
                snapshots.append(snap)
        except Exception:
            continue

    try:
        if len(deduped_positions) > 1:
            context_obj.evaluate("() => window.scrollTo(0, 0)")
            time.sleep(0.15)
    except Exception:
        pass

    return snapshots


def get_network_resource_signals(page, resource_tracker=None):
    network_items = []
    seen = set()

    def add_item(url, content_type=""):
        url = normalize_space(url)
        content_type = normalize_space(content_type)
        if not url:
            return
        key = f"{url.lower()}||{content_type.lower()}"
        if key in seen:
            return
        seen.add(key)
        network_items.append({
            "url": url,
            "content_type": content_type,
        })

    if resource_tracker and isinstance(resource_tracker, dict):
        for item in resource_tracker.get("items", []):
            add_item(item.get("url", ""), item.get("content_type", ""))

    for item in get_context_resource_entries(page, limit=400):
        add_item(item.get("url", ""), item.get("content_type", ""))

    for item in get_context_dom_resource_entries(page, limit=300):
        add_item(item.get("url", ""), item.get("content_type", ""))

    child_frames = get_accessible_child_frames(page)
    for frame in child_frames:
        for item in get_context_resource_entries(frame, limit=250):
            add_item(item.get("url", ""), item.get("content_type", ""))
        for item in get_context_dom_resource_entries(frame, limit=180):
            add_item(item.get("url", ""), item.get("content_type", ""))
        try:
            frame_url = normalize_space(frame.url or "")
            if frame_url:
                add_item(frame_url, "frame")
        except Exception:
            pass

    asset_3d_exts = [
        ".obj", ".glb", ".gltf", ".fbx", ".stl", ".dae",
        ".3dm", ".ply", ".mtl", ".usd"
    ]
    ar_exts = [".usdz"]
    viewer_keywords = [
        "model-viewer", "three", "babylon", "blend4web", "b4w", "sketchfab",
        "spline", "verge3d", "playcanvas", "shapediver"
    ]

    asset_3d_urls = []
    ar_asset_urls = []
    viewer_platform_urls = []
    model_content_type_hits = []
    iframe_configurator_urls = []

    for item in network_items:
        url = item.get("url", "")
        content_type = item.get("content_type", "")
        url_l = url.lower()
        ct_l = content_type.lower()

        if "frame" in ct_l and any(token in url_l for token in ["configurator", "konfigurator", "custom", "builder", "config", "3d"]):
            iframe_configurator_urls.append(url)

        if any(ext in url_l for ext in ar_exts) or "model/vnd.usdz" in ct_l:
            ar_asset_urls.append(url)

        if (
            any(ext in url_l for ext in asset_3d_exts)
            or ct_l.startswith("model/")
            or "gltf" in ct_l
            or ("octet-stream" in ct_l and any(ext.replace(".", "") in url_l for ext in [".glb", ".gltf", ".obj", ".fbx", ".stl", ".dae", ".3dm", ".ply", ".mtl", ".usd"]))
        ):
            asset_3d_urls.append(url)

        if ct_l.startswith("model/") or "gltf" in ct_l or ("model" in ct_l and any(token in ct_l for token in ["gltf", "obj", "usdz"])):
            model_content_type_hits.append(f"{url} [{content_type}]")

        if any(keyword in url_l for keyword in viewer_keywords):
            viewer_platform_urls.append(url)

    def unique_limited(values, limit=8):
        out = []
        seen_local = set()
        for value in values:
            key = value.lower()
            if key in seen_local:
                continue
            seen_local.add(key)
            out.append(value)
            if len(out) >= limit:
                break
        return out

    return {
        "resource_count": len(network_items),
        "asset_3d_urls": unique_limited(asset_3d_urls, 8),
        "asset_3d_count": len(unique_limited(asset_3d_urls, 50)),
        "ar_asset_urls": unique_limited(ar_asset_urls, 8),
        "ar_asset_count": len(unique_limited(ar_asset_urls, 50)),
        "viewer_platform_urls": unique_limited(viewer_platform_urls, 8),
        "viewer_platform_count": len(unique_limited(viewer_platform_urls, 50)),
        "model_content_type_hits": unique_limited(model_content_type_hits, 8),
        "model_content_type_count": len(unique_limited(model_content_type_hits, 50)),
        "iframe_configurator_urls": unique_limited(iframe_configurator_urls, 8),
        "iframe_configurator_count": len(unique_limited(iframe_configurator_urls, 50)),
        "child_frame_count": len(child_frames),
    }


def merge_dom_signal_snapshots(snapshots):
    if not snapshots:
        return {}

    merged = {}
    list_keys = {
        "heading_texts", "button_texts", "link_texts", "label_texts",
        "ar_text_hints", "rotate_text_hints", "script_hints", "img_src_hints"
    }

    for snap in snapshots:
        if not isinstance(snap, dict):
            continue
        for key, value in snap.items():
            if key in list_keys:
                existing = merged.setdefault(key, [])
                seen = {str(x).lower() for x in existing}
                for item in value or []:
                    item_s = normalize_space(str(item))
                    if not item_s:
                        continue
                    item_key = item_s.lower()
                    if item_key in seen:
                        continue
                    seen.add(item_key)
                    existing.append(item_s)
            elif isinstance(value, bool):
                merged[key] = bool(merged.get(key, False) or value)
            elif isinstance(value, int):
                merged[key] = max(int(merged.get(key, 0)), value)
            else:
                if key not in merged or not merged.get(key):
                    merged[key] = value

    return merged



def collect_visualization_signals_with_scroll(page, resource_tracker=None):
    snapshots = []
    positions_checked = []
    frame_urls_seen = []

    def collect_current_state(current_scroll_pos=0):
        try:
            snap = get_page_dom_signals(page)
            if isinstance(snap, dict):
                iframe_metrics = get_iframe_metrics(page)
                for k, v in iframe_metrics.items():
                    if isinstance(v, list):
                        snap[k] = v
                    else:
                        snap[k] = v
                snapshots.append(snap)
                positions_checked.append(current_scroll_pos)
        except Exception:
            pass

        for frame in get_accessible_child_frames(page):
            try:
                frame_url = normalize_space(frame.url or '')
            except Exception:
                frame_url = ''

            if frame_url and frame_url.lower() not in {u.lower() for u in frame_urls_seen}:
                frame_urls_seen.append(frame_url)

            frame_snapshots = collect_context_dom_signals_with_scroll(frame, max_steps=3, per_step_wait_seconds=0.25)
            for fsnap in frame_snapshots:
                if not isinstance(fsnap, dict):
                    continue
                fsnap = dict(fsnap)
                fsnap['from_child_frame'] = True
                if frame_url:
                    existing_urls = list(fsnap.get('iframe_src_hints', [])) if isinstance(fsnap.get('iframe_src_hints', []), list) else []
                    existing_urls.insert(0, frame_url)
                    fsnap['iframe_src_hints'] = existing_urls[:12]
                snapshots.append(fsnap)

    collect_current_state(0)

    try:
        scroll_meta = page.evaluate(
            """
            () => ({
                scrollHeight: Math.max(
                    document.body ? document.body.scrollHeight : 0,
                    document.documentElement ? document.documentElement.scrollHeight : 0
                ),
                viewportHeight: window.innerHeight || 0
            })
            """
        )
    except Exception:
        scroll_meta = {"scrollHeight": 0, "viewportHeight": 0}

    scroll_height = int(scroll_meta.get("scrollHeight", 0) or 0)
    viewport_height = int(scroll_meta.get("viewportHeight", 0) or 0)

    positions = [0]
    if scroll_height > 0 and viewport_height > 0 and scroll_height > int(viewport_height * 1.15):
        max_offset = max(scroll_height - viewport_height, 0)
        steps = 5
        for i in range(1, steps + 1):
            pos = int(round(max_offset * i / steps))
            positions.append(pos)

    deduped_positions = []
    seen_positions = set()
    for pos in positions:
        if pos in seen_positions:
            continue
        seen_positions.add(pos)
        deduped_positions.append(pos)

    for pos in deduped_positions[1:]:
        try:
            page.evaluate("(y) => window.scrollTo(0, y)", pos)
            page.wait_for_timeout(900)
            try_accept_cookies(page)
            page.wait_for_timeout(350)
            collect_current_state(pos)
        except Exception:
            continue

    try:
        if deduped_positions and deduped_positions[-1] != 0:
            page.evaluate("() => window.scrollTo(0, 0)")
            page.wait_for_timeout(250)
    except Exception:
        pass

    merged_dom = merge_dom_signal_snapshots(snapshots)
    network_signals = get_network_resource_signals(page, resource_tracker=resource_tracker)
    merged_dom["scroll_positions_checked"] = positions_checked
    merged_dom["scroll_snapshot_count"] = len(snapshots)
    merged_dom["scrolled_beyond_initial_viewport"] = len(deduped_positions) > 1
    merged_dom["child_frame_urls"] = frame_urls_seen[:12]
    merged_dom["child_frame_count"] = len(frame_urls_seen)

    return merged_dom, network_signals


def evaluate_visualization_type_deterministic(page, resource_tracker=None):
    try:
        final_url = page.url
    except Exception:
        final_url = ""

    try:
        title = page.title()
    except Exception:
        title = ""

    try:
        visible_text = page.locator("body").inner_text()
    except Exception:
        visible_text = ""

    dom_signals, network_signals = collect_visualization_signals_with_scroll(page, resource_tracker=resource_tracker)

    full_text = " ".join([
        (title or "").lower(),
        (final_url or "").lower(),
        (visible_text or "").lower(),
        " ".join(x.lower() for x in dom_signals.get("ar_text_hints", [])),
        " ".join(x.lower() for x in dom_signals.get("rotate_text_hints", [])),
        " ".join(x.lower() for x in dom_signals.get("script_hints", [])),
        (dom_signals.get("meta_description", "") or "").lower(),
        (dom_signals.get("meta_og_description", "") or "").lower(),
        " ".join(x.lower() for x in dom_signals.get("iframe_src_hints", [])),
        " ".join(x.lower() for x in dom_signals.get("child_frame_urls", [])),
        " ".join(x.lower() for x in network_signals.get("asset_3d_urls", [])),
        " ".join(x.lower() for x in network_signals.get("ar_asset_urls", [])),
        " ".join(x.lower() for x in network_signals.get("viewer_platform_urls", [])),
    ])

    semantic_text = " ".join([
        (title or "").lower(),
        (final_url or "").lower(),
        (dom_signals.get("meta_description", "") or "").lower(),
        (dom_signals.get("meta_og_description", "") or "").lower(),
        " ".join(x.lower() for x in dom_signals.get("heading_texts", [])),
        " ".join(x.lower() for x in dom_signals.get("button_texts", [])),
        " ".join(x.lower() for x in dom_signals.get("label_texts", [])),
        " ".join(x.lower() for x in dom_signals.get("iframe_src_hints", [])),
        " ".join(x.lower() for x in dom_signals.get("child_frame_urls", [])),
    ])

    has_3d_script_signal = any(
        any(token in hint.lower() for token in ["three", "babylon", "blend4web", "b4w", "model-viewer", "spline", "sketchfab", "verge3d", "playcanvas", "shapediver", "webgl"])
        for hint in dom_signals.get("script_hints", [])
    )

    explicit_3d_page_semantics = (
        ("3d" in semantic_text or "360" in semantic_text or "dreidimensional" in semantic_text)
        and any(token in semantic_text for token in ["configur", "konfig", "custom", "builder", "viewer", "model", "design", "rotate"])
    )

    interactive_score = 0
    interactive_reasons = []

    if dom_signals.get("model_viewer_count", 0) > 0:
        interactive_score += 7
        interactive_reasons.append("model-viewer element")
    if network_signals.get("asset_3d_count", 0) > 0:
        interactive_score += 6
        interactive_reasons.append("3D asset downloaded")
    if network_signals.get("asset_3d_count", 0) >= 2:
        interactive_score += 1
        interactive_reasons.append("multiple 3D assets")
    if network_signals.get("model_content_type_count", 0) > 0:
        interactive_score += 4
        interactive_reasons.append("model/* content-type")
    if dom_signals.get("webgl_canvas_count", 0) > 0:
        interactive_score += 3
        interactive_reasons.append("WebGL canvas")
    if network_signals.get("viewer_platform_count", 0) > 0:
        interactive_score += 2
        interactive_reasons.append("3D viewer resource")
    if dom_signals.get("iframe_count", 0) > 0 and network_signals.get("viewer_platform_count", 0) > 0:
        interactive_score += 2
        interactive_reasons.append("viewer iframe/resource combination")
    if dom_signals.get("visible_large_iframe_count", 0) > 0 and network_signals.get("iframe_configurator_count", 0) > 0:
        interactive_score += 2
        interactive_reasons.append("visible configurator iframe detected")
    if dom_signals.get("large_iframe_count", 0) > 0 and (network_signals.get("asset_3d_count", 0) > 0 or network_signals.get("viewer_platform_count", 0) > 0 or dom_signals.get("webgl_canvas_count", 0) > 0):
        interactive_score += 3
        interactive_reasons.append("large iframe with 3D evidence")
    if dom_signals.get("three_global", False) or dom_signals.get("babylon_global", False) or dom_signals.get("blend4web_global", False) or dom_signals.get("model_viewer_global", False):
        interactive_score += 2
        interactive_reasons.append("3D global available")
    if dom_signals.get("blend4web_global", False):
        interactive_score += 3
        interactive_reasons.append("Blend4Web global available")
    if has_3d_script_signal:
        interactive_score += 1
        interactive_reasons.append("3D library script hint")
    if dom_signals.get("webgl_canvas_count", 0) > 0 and (
        has_3d_script_signal
        or dom_signals.get("three_global", False)
        or dom_signals.get("babylon_global", False)
        or dom_signals.get("blend4web_global", False)
        or network_signals.get("viewer_platform_count", 0) > 0
    ):
        interactive_score += 4
        interactive_reasons.append("WebGL canvas with 3D engine hint")
    if explicit_3d_page_semantics and (
        dom_signals.get("webgl_canvas_count", 0) > 0
        or has_3d_script_signal
        or network_signals.get("viewer_platform_count", 0) > 0
        or dom_signals.get("large_iframe_count", 0) > 0
    ):
        interactive_score += 3
        interactive_reasons.append("explicit 3D configurator semantics")
    if len(dom_signals.get("rotate_text_hints", [])) > 0:
        interactive_score += 1
        interactive_reasons.append("rotation/3D text hint")

    strong_primary_3d_evidence = (
        dom_signals.get("model_viewer_count", 0) > 0
        or network_signals.get("asset_3d_count", 0) > 0
        or network_signals.get("model_content_type_count", 0) > 0
        or (dom_signals.get("webgl_canvas_count", 0) > 0 and (
            network_signals.get("viewer_platform_count", 0) > 0
            or has_3d_script_signal
            or dom_signals.get("three_global", False)
            or dom_signals.get("babylon_global", False)
            or dom_signals.get("blend4web_global", False)
        ) and (explicit_3d_page_semantics or dom_signals.get("canvas_count", 0) > 0))
        or (dom_signals.get("visible_large_iframe_count", 0) > 0 and (network_signals.get("viewer_platform_count", 0) > 0 or network_signals.get("asset_3d_count", 0) > 0 or network_signals.get("model_content_type_count", 0) > 0))
    )

    if dom_signals.get("model_viewer_count", 0) > 0:
        summary = {
            "dom_signals": dom_signals,
            "network_signals": network_signals,
            "interactive_score": interactive_score,
        }
        return (
            "Interactive 3D",
            "Deterministic 3D classification: model-viewer element present",
            100,
            json.dumps(summary, ensure_ascii=False),
            "",
            "deterministic_network_dom_3d",
        )

    if strong_primary_3d_evidence and interactive_score >= 8:
        summary = {
            "dom_signals": dom_signals,
            "network_signals": network_signals,
            "interactive_score": interactive_score,
        }
        return (
            "Interactive 3D",
            f"Deterministic 3D classification from: {', '.join(interactive_reasons[:4])}",
            96,
            json.dumps(summary, ensure_ascii=False),
            "",
            "deterministic_network_dom_3d",
        )

    strong_2d_configuration_signal = (
        dom_signals.get("img_count", 0) >= 1
        and (
            dom_signals.get("radio_count", 0) >= 2
            or dom_signals.get("checkbox_count", 0) >= 2
            or dom_signals.get("range_count", 0) >= 1
            or dom_signals.get("option_count", 0) >= 4
            or dom_signals.get("svg_count", 0) >= 4
        )
    )

    product_detail_like_static_page = (
        not strong_primary_3d_evidence
        and dom_signals.get("img_count", 0) >= 1
        and dom_signals.get("webgl_canvas_count", 0) == 0
        and network_signals.get("asset_3d_count", 0) == 0
        and network_signals.get("model_content_type_count", 0) == 0
        and dom_signals.get("model_viewer_count", 0) == 0
        and any(token in full_text for token in ["warenkorb", "paarpreis", "artikel-nr", "lieferzeit", "price", "add to cart", "cart", "sku", "product"])
    )

    static_reasons = []
    if strong_2d_configuration_signal:
        static_reasons.append("static previews with 2D controls")
    if product_detail_like_static_page:
        static_reasons.append("product-detail page with static imagery")
    if network_signals.get("asset_3d_count", 0) == 0:
        static_reasons.append("no 3D asset downloaded")
    if network_signals.get("model_content_type_count", 0) == 0:
        static_reasons.append("no model content-type")
    if dom_signals.get("model_viewer_count", 0) == 0:
        static_reasons.append("no model-viewer")
    if dom_signals.get("webgl_canvas_count", 0) == 0:
        static_reasons.append("no WebGL canvas")

    summary = {
        "dom_signals": dom_signals,
        "network_signals": network_signals,
        "interactive_score": interactive_score,
    }
    return (
        "Static 2D",
        f"Deterministic Static 2D classification from: {', '.join(static_reasons[:4])}",
        90 if strong_2d_configuration_signal else 82,
        json.dumps(summary, ensure_ascii=False),
        "",
        "deterministic_network_dom_static",
    )


# Legacy name kept for compatibility with the rest of the script.
def evaluate_visualization_type_with_ollama(page, resource_tracker=None):
    return evaluate_visualization_type_deterministic(page, resource_tracker=resource_tracker)



def domains_compatible(url_a, url_b):
    domain_a = extract_domain(url_a)
    domain_b = extract_domain(url_b)
    if not domain_a or not domain_b:
        return False
    return domain_a == domain_b or domain_a.endswith('.' + domain_b) or domain_b.endswith('.' + domain_a)


def is_promising_internal_configurator_link(url, text=''):
    url_l = (url or '').lower()
    text_l = normalize_space(text).lower()
    full = f"{url_l} {text_l}"

    positive_signals = [
        'configurator', 'configurateur', 'configurador', 'konfigurator',
        'custom', 'customizer', 'customiser',
        'personaliz', 'personnalis', 'personalis', 'konfigur',
        'design-your-own', 'design your own',
        'builder', 'designer', 'compose', 'build-your', 'build your',
        'create your', 'start customizing', 'start custom',
        'personnaliser', 'personnalisez', 'personalizar', 'personalizable',
    ]
    negative_signals = [
        '/blog', '/news', '/article', '/articles', '/journal', '/story', '/stories',
        '/review', '/reviews', '/test-', '/test/', 'i-trekkings', 'forum', 'press',
        'lookbook', 'campaign', 'editorial', 'about-us', 'contact', 'login', 'account',
    ]

    if any(sig in full for sig in negative_signals):
        return False

    return any(sig in full for sig in positive_signals)


def extract_promising_internal_links(page, base_url, max_links=MAX_INTERNAL_LINKS_TO_EXPLORE):
    try:
        raw_links = page.evaluate(
            r"""
            () => {
                const anchors = [...document.querySelectorAll('a[href]')];
                const out = [];
                const seen = new Set();
                for (const a of anchors) {
                    const href = (a.href || a.getAttribute('href') || '').trim();
                    if (!href) continue;
                    const text = ((a.innerText || a.textContent || a.getAttribute('aria-label') || '')).replace(/\\s+/g, ' ').trim();
                    const key = href.toLowerCase() + '||' + text.toLowerCase();
                    if (seen.has(key)) continue;
                    seen.add(key);
                    out.push({href, text});
                    if (out.length >= 300) break;
                }
                return out;
            }
            """
        )
    except Exception:
        return []

    scored = []
    seen_urls = set()
    base_domain = extract_domain(base_url)

    for item in raw_links:
        href = normalize_space(item.get('href', ''))
        text_value = normalize_space(item.get('text', ''))
        if not href:
            continue
        try:
            abs_url = urljoin(base_url, href)
        except Exception:
            abs_url = href

        abs_url = normalize_url_for_dedup(abs_url)
        if not abs_url.lower().startswith(('http://', 'https://')):
            continue
        if is_excluded_external_url(abs_url):
            continue
        if not domains_compatible(abs_url, base_url):
            continue
        if abs_url in seen_urls:
            continue

        score = 0
        full = f"{abs_url.lower()} {text_value.lower()}"

        if is_promising_internal_configurator_link(abs_url, text_value):
            score += 8

        positive_path_signals = [
            'configurator', 'configurateur', 'configurador', 'konfigurator',
            'custom', 'customizer', 'customiser', 'personaliz', 'personnalis',
            'builder', 'designer', 'design-your-own', 'design your own',
            'compose', 'build-your', 'build your', 'create your', 'start custom'
        ]
        negative_signals = [
            '/blog', '/news', '/article', '/articles', '/journal', '/story', '/stories',
            '/review', '/reviews', '/test', '/press', '/privacy', '/terms', '/contact',
            '/account', '/login', '/cart', '/checkout', '/wishlist'
        ]

        if any(sig in full for sig in negative_signals):
            continue

        for sig in positive_path_signals:
            if sig in full:
                score += 2

        if extract_domain(abs_url) == base_domain:
            score += 2

        if text_value:
            score += 1

        if score <= 0:
            continue

        seen_urls.add(abs_url)
        scored.append((score, abs_url, text_value))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [{'url': url, 'text': text_value, 'score': score} for score, url, text_value in scored[:max_links]]


def normalize_google_result_target(href):
    href = normalize_space(href)
    if not href:
        return ""

    try:
        parsed = urlparse(href)
        host = parsed.netloc.lower()

        if host.endswith("google.com") and parsed.path == "/url":
            query = parse_qs(parsed.query)
            q_val = query.get("q", [""])[0]
            return normalize_space(q_val)

        return href
    except Exception:
        return href


def is_excluded_google_result(url):
    url_l = (url or "").lower()
    excluded_fragments = [
        "google.com",
        "googleusercontent.com",
        "webcache.googleusercontent.com",
        "support.google.com",
        "accounts.google.com",
        "policies.google.com",
        "maps.google.com",
        "youtube.com",
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "pinterest.",
        "twitter.com",
        "x.com",
        "freelancer.com",
        "upwork.com",
        "fiverr.com",
        "peopleperhour.com",
        "guru.com",
        "indeed.com",
        "glassdoor.com",
    ]
    return any(fragment in url_l for fragment in excluded_fragments)


def extract_google_search_results(page, max_results=10):
    raw_results = page.evaluate(
        rf"""
        () => {{
            const out = [];
            const seen = new Set();

            function pushResult(title, url, snippet) {{
                title = (title || '').replace(/\\s+/g, ' ').trim();
                url = (url || '').trim();
                snippet = (snippet || '').replace(/\\s+/g, ' ').trim();
                if (!title || !url) return;
                const key = title.toLowerCase() + '||' + url;
                if (seen.has(key)) return;
                seen.add(key);
                out.push({{title, url, snippet}});
            }}

            const blocks = [...document.querySelectorAll('div.g, div.MjjYud, div[data-hveid]')];
            for (const block of blocks) {{
                const h3 = block.querySelector('h3');
                const a = h3 ? h3.closest('a') : block.querySelector('a[href]');
                if (!a || !h3) continue;
                const title = h3.innerText || a.innerText || '';
                const url = a.href || '';
                const snippetEl = block.querySelector('.VwiC3b, .yXK7lf, .MUxGbd, .lyLwlc');
                let snippet = snippetEl ? snippetEl.innerText : '';
                if (!snippet) {{
                    snippet = block.innerText || '';
                }}
                pushResult(title, url, snippet);
                if (out.length >= {max_results}) break;
            }}

            if (out.length < {max_results}) {{
                const anchors = [...document.querySelectorAll('a[href]')];
                for (const a of anchors) {{
                    const h3 = a.querySelector('h3');
                    if (!h3) continue;
                    const title = h3.innerText || a.innerText || '';
                    const url = a.href || '';
                    const snippet = (a.parentElement && a.parentElement.parentElement ? a.parentElement.parentElement.innerText : '') || '';
                    pushResult(title, url, snippet);
                    if (out.length >= {max_results}) break;
                }}
            }}

            return out.slice(0, {max_results});
        }}
        """
    )

    cleaned = []
    seen_urls = set()

    for item in raw_results:
        url = normalize_google_result_target(item.get("url", ""))
        title = normalize_space(item.get("title", ""))
        snippet = normalize_space(item.get("snippet", ""))

        if not url or not title:
            continue
        if is_excluded_google_result(url):
            continue
        if not url.lower().startswith(("http://", "https://")):
            continue
        if url in seen_urls:
            continue

        seen_urls.add(url)
        cleaned.append({"title": title, "url": url, "snippet": snippet})
        if len(cleaned) >= max_results:
            break

    return cleaned


def build_google_queries(company, product, country):
    """
    Build Google queries without quotation marks because, in this project,
    quoted searches often become too restrictive or distort the ranking.

    Agreed structure:
    product + company + country + final keyword
    but WITHOUT double quotes.
    """
    queries = []

    company = normalize_space(company)
    product = normalize_space(product)
    country = normalize_space(country)

    def join_parts(*parts):
        return normalize_space(" ".join([p for p in parts if normalize_space(p)]))

    keyword_variants = [
        "configurator",
        "customizer",
        "product builder",
        "design your own",
        "configurateur",
        "personnaliser",
        "configurador",
        "personalizar",
        "konfigurator",
    ]

    for keyword in keyword_variants:
        primary = join_parts(product, company, country, keyword)
        if primary:
            queries.append(primary)

    for keyword in keyword_variants:
        queries.append(join_parts(product, company, keyword))

    queries.append(join_parts(company, product, country))

    deduped = []
    seen = set()
    for q in queries:
        q = normalize_space(q)
        key = q.lower()
        if q and key not in seen:
            seen.add(key)
            deduped.append(q)

    return deduped


def google_search_candidates(context, company, product, country, max_results=GOOGLE_SEARCH_MAX_RESULTS):
    """Legacy helper kept only for compatibility. Not used by the current internal-discovery pipeline."""
    queries = build_google_queries(company, product, country)

    for query in queries:
        search_page = context.new_page()
        try:
            google_url = f"https://www.google.com/search?hl=en&num={max_results}&q={quote_plus(query)}"
            safe_page_goto(search_page, google_url, timeout_ms=PAGE_GOTO_TIMEOUT_MS, post_wait_ms=3500)
            try_accept_cookies(search_page)
            search_page.wait_for_timeout(1500)
            results = extract_google_search_results(search_page, max_results=max_results)
            if results:
                return query, results
        except Exception:
            pass
        finally:
            try:
                search_page.close()
            except Exception:
                pass

    return "", []


def select_best_candidate_urls_with_ollama(company, product, country, search_results):
    if not search_results:
        return [], "", "Nessun risultato Google disponibile"

    summarized_results = []
    for idx, result in enumerate(search_results, start=1):
        summarized_results.append(
            f"{idx}. TITLE: {result['title']}\nURL: {result['url']}\nSNIPPET: {result['snippet']}"
        )

    prompt = f"""
You are an assistant selecting promising Google results to find an alternative configurator.

Target instance:
- Company: {company}
- Product: {product}
- Country: {country}

Goal:
- Choose up to 3 URLs with the highest probability of leading to an ACTIVE configurator for the same company and the same product or product family.
- Prefer official manufacturer pages, dedicated product pages, configurators, customizers, builders, and designers.
- Avoid directories, articles, reviews, PDFs, generic marketplaces, social pages, third-party databases, and overly generic homepages.
- If no result looks promising, return an empty list.
- Return ONLY valid JSON on one line.

Exact format:
{{"selected_urls":["https://example1.com","https://example2.com"],"reason":"brief explanation"}}

GOOGLE RESULTS:
{chr(10).join(summarized_results)}
""".strip()

    raw_output = call_ollama(prompt)
    available_urls = [r["url"] for r in search_results]
    selected_urls = parse_ollama_selected_urls(raw_output, available_urls)
    motivo = regex_extract_field(raw_output, "motivo") or regex_extract_field(raw_output, "reason") or "Candidate selection completed"

    if not selected_urls:
        selected_urls = available_urls[:ALTERNATIVE_CANDIDATES_TO_OPEN]
        motivo = f"{motivo} | fallback: primi risultati organici"

    return selected_urls[:ALTERNATIVE_CANDIDATES_TO_OPEN], raw_output, motivo


def evaluate_candidate_alternative_page(page, company, product, country):
    try:
        final_url = page.url
    except Exception:
        final_url = ""

    try:
        title = page.title()
    except Exception:
        title = ""

    try:
        visible_text = page.locator("body").inner_text()
    except Exception:
        visible_text = ""

    dom_signals = get_page_dom_signals(page)

    hard_negative = detect_hard_negative_page(title, final_url, visible_text)
    if hard_negative is not None:
        attivo, motivo = hard_negative
        return "NO", attivo, 100, motivo, title, final_url, "", "", "hard_rule"

    context_negative = detect_non_tool_context_page(title, final_url, visible_text, dom_signals)
    if context_negative is not None:
        attivo, motivo = context_negative
        return "NO", attivo, 100, motivo, title, final_url, "", "", "hard_rule"

    hard_positive = detect_hard_positive_configurator(title, final_url, visible_text, dom_signals)

    visible_text_excerpt = compress_visible_text(visible_text, max_chars=6000)

    prompt = f"""
You are a web page classifier.

Evaluate a candidate page found through Google and decide whether it can be used as an ALTERNATIVE CONFIGURATOR for the target instance.

Target instance:
- Company: {company}
- Product: {product}
- Country: {country}

You must return two judgments:
1) product_match = SI if the page is clearly about the same company and the same product or product family as the target instance. Otherwise NO.
2) active = SI if the page shows an active product configurator. Otherwise NO.

Rules:
- A page may have active=SI but product_match=NO if it is about a different company or a different product.
- A homepage, article page, interview page, blog post, news page, job post, marketplace page, directory, database, generic reseller page, or page without a real configurator must have active=NO.
- A page that TALKS ABOUT a configurator but does not actually host it must have active=NO.
- An official landing page dedicated to the customization flow, where the first step is choosing the base model or product to personalize, may have active=SI even if it does not yet show every final control.
- If you are uncertain about product_match, use NO.
- If you are uncertain about active, use NO.
- Return ONLY valid JSON on one line.
- Use confidence as an integer from 0 to 100.

Exact format:
{{"product_match":"SI","active":"SI","confidence":85,"reason":"brief explanation"}}

PAGE DATA

TITLE:
{title}

FINAL URL:
{final_url}

VISIBLE PAGE TEXT:
{visible_text_excerpt}

DOM / INTERACTION SIGNALS:
{json.dumps(dom_signals, ensure_ascii=False)}
""".strip()

    raw_output = call_ollama(prompt)
    try:
        match_prodotto, attivo, confidence, motivo, parser_warning = parse_ollama_candidate_assessment(raw_output)
        if (
            match_prodotto == "SI"
            and attivo == "NO"
            and hard_positive is not None
        ):
            attivo = "SI"
            confidence = max(confidence or 0, 80)
            motivo = f"{motivo} | Correzione euristica: la pagina mostra una struttura da configuratore attivo"
            return match_prodotto, attivo, confidence, motivo, title, final_url, raw_output, parser_warning, "ollama_plus_heuristic_active"
        return match_prodotto, attivo, confidence, motivo, title, final_url, raw_output, parser_warning, "ollama"
    except Exception as exc:
        company_l = normalize_space(company).lower()
        product_l = normalize_space(product).lower()
        title_l = (title or "").lower()
        visible_l = (visible_text or "").lower()
        final_url_l = (final_url or "").lower()

        match_company = company_l and (company_l in visible_l or company_l in title_l or company_l in final_url_l)
        match_product = product_l and (product_l in visible_l or product_l in title_l or product_l in final_url_l)
        match_prodotto = "SI" if (match_company and match_product) else "NO"

        negative_context = detect_non_tool_context_page(title, final_url, visible_text, dom_signals)
        if hard_positive is not None and match_prodotto == "SI" and negative_context is None:
            confidence = 75
            motivo = f"Fallback euristico dopo risposta Ollama non interpretabile: {exc}"
            return match_prodotto, "SI", confidence, motivo, title, final_url, raw_output, "Fallback euristico candidato", "heuristic_candidate_active"

        confidence = 45 if match_prodotto == "SI" else 30
        motivo = f"Fallback prudente candidato: nessuna evidenza affidabile di configuratore attivo dopo errore Ollama ({exc})"
        return match_prodotto, "NO", confidence, motivo, title, final_url, raw_output, "Fallback prudente candidato", "heuristic_candidate_inactive"


def explore_internal_links_from_candidate(context, base_candidate_page, base_candidate_url, company, product, country, visited_urls, reusable_page=None):
    internal_links = extract_promising_internal_links(base_candidate_page, base_candidate_url, max_links=MAX_INTERNAL_LINKS_TO_EXPLORE)
    if not internal_links:
        return None, []

    notes = [
        f"Link interni promettenti trovati nella pagina ufficiale: {len(internal_links)}"
    ]

    internal_page = reusable_page
    created_local_page = False
    if internal_page is None:
        internal_page = context.new_page()
        created_local_page = True

    try:
        for item in internal_links:
            internal_url = item['url']
            internal_text = item.get('text', '')
            if internal_url in visited_urls:
                continue
            visited_urls.add(internal_url)
            try:
                safe_page_goto(internal_page, internal_url, timeout_ms=PAGE_GOTO_TIMEOUT_MS, post_wait_ms=POST_GOTO_WAIT_MS)
                try_accept_cookies(internal_page)
                internal_page.wait_for_timeout(1500)

                match_prodotto, attivo, confidence, motivo, title, final_url, raw_output, parser_warning, decision_source = evaluate_candidate_alternative_page(
                    internal_page, company, product, country
                )
                note = (
                    f"Link interno analizzato: {internal_url}"
                    f" | anchor_text={internal_text or '-'}"
                    f" | match_prodotto={match_prodotto} | attivo={attivo} | motivo={motivo}"
                )
                if parser_warning:
                    note += f" | {parser_warning}"
                notes.append(note)

                if match_prodotto == 'SI' and attivo == 'SI':
                    result = {
                        'found': True,
                        'alternative_url': final_url or internal_url,
                        'page_title': title,
                        'confidence': confidence,
                        'note': ' | '.join(notes + ['Configuratore alternativo trovato tramite link interno della pagina ufficiale']),
                        'raw_output': raw_output,
                        'decision_source': f"alt_search:internal_link_discovery|candidate:{decision_source}",
                    }
                    return result, notes
            except Exception as exc:
                notes.append(f"Link interno fallito: {internal_url} | errore={str(exc)}")
    finally:
        if created_local_page:
            try:
                internal_page.close()
            except Exception:
                pass

    return None, notes


def find_alternative_configurator(context, company, product, country, seed_urls):
    seed_urls = [normalize_url_for_dedup(url) for url in (seed_urls or []) if normalize_url_for_dedup(url)]

    if not seed_urls:
        return {
            "found": False,
            "alternative_url": "",
            "page_title": "",
            "confidence": "",
            "note": "Ricerca configuratore alternativo: nessun seed URL disponibile per la discovery interna",
            "raw_output": "",
            "decision_source": "alt_search:no_seed_urls",
        }

    candidate_notes = [
        f"Seed URL per discovery interna: {len(seed_urls)}",
        "Nessuna ricerca Google via browser: esplorazione interna del sito ufficiale e dei seed URL reali",
    ]
    raw_parts = []
    visited_urls = set()
    pages_visited = 0
    candidate_page = context.new_page()

    def open_and_evaluate(candidate_url, origin_label):
        nonlocal pages_visited
        if pages_visited >= MAX_INTERNAL_DISCOVERY_PAGES:
            return None

        normalized_url = normalize_url_for_dedup(candidate_url)
        if not normalized_url or normalized_url in visited_urls:
            return None

        visited_urls.add(normalized_url)
        try:
            pages_visited += 1
            safe_page_goto(candidate_page, normalized_url, timeout_ms=PAGE_GOTO_TIMEOUT_MS, post_wait_ms=POST_GOTO_WAIT_MS)
            try_accept_cookies(candidate_page)
            candidate_page.wait_for_timeout(1500)

            match_prodotto, attivo, confidence, motivo, title, final_url, raw_output, parser_warning, decision_source = evaluate_candidate_alternative_page(
                candidate_page, company, product, country
            )

            candidate_note = (
                f"Candidato interno analizzato: {normalized_url} | origine={origin_label} | "
                f"match_prodotto={match_prodotto} | attivo={attivo} | motivo={motivo}"
            )
            if parser_warning:
                candidate_note += f" | {parser_warning}"
            candidate_notes.append(candidate_note)
            if raw_output:
                raw_parts.append(f"[ALT_CANDIDATE]\nURL: {normalized_url}\n{raw_output}")

            if match_prodotto == "SI" and attivo == "SI":
                return {
                    "found": True,
                    "alternative_url": final_url or normalized_url,
                    "page_title": title,
                    "confidence": confidence,
                    "note": " | ".join(candidate_notes + ["Configuratore alternativo trovato e valido"]),
                    "raw_output": "\n\n".join(raw_parts),
                    "decision_source": f"alt_search:internal_seed_discovery|candidate:{decision_source}",
                }

            internal_result, internal_notes = explore_internal_links_from_candidate(
                context, candidate_page, final_url or normalized_url, company, product, country, visited_urls, reusable_page=candidate_page
            )
            for note in internal_notes:
                candidate_notes.append(note)
            if internal_result is not None:
                if internal_result.get("raw_output"):
                    raw_parts.append(f"[ALT_INTERNAL]\n{internal_result['raw_output']}")
                internal_result["note"] = " | ".join(candidate_notes + [internal_result["note"]])
                internal_result["raw_output"] = "\n\n".join([part for part in raw_parts if part])
                return internal_result

        except Exception as exc:
            candidate_notes.append(f"Candidato interno fallito: {normalized_url} | origine={origin_label} | errore={str(exc)}")
        return None

    try:
        queue = []
        seen_seed = set()
        for url in seed_urls:
            norm = normalize_url_for_dedup(url)
            if norm and norm not in seen_seed:
                seen_seed.add(norm)
                queue.append((norm, "seed"))
                root = normalize_url_for_dedup(get_site_root_url(norm))
                if root and root not in seen_seed:
                    seen_seed.add(root)
                    queue.append((root, "site_root"))

        for candidate_url, origin_label in queue:
            result = open_and_evaluate(candidate_url, origin_label)
            if result is not None:
                return result
            if pages_visited >= MAX_INTERNAL_DISCOVERY_PAGES:
                break

        return {
            "found": False,
            "alternative_url": "",
            "page_title": "",
            "confidence": "",
            "note": " | ".join(candidate_notes + ["No configuratori attivi"]),
            "raw_output": "\n\n".join(raw_parts),
            "decision_source": "alt_search:internal_seed_discovery_exhausted",
        }
    finally:
        try:
            candidate_page.close()
        except Exception:
            pass


# =========================
# RISOLUZIONE GUIDATA: GATEWAY -> CONFIGURATORE EFFETTIVO
# =========================
GATEWAY_PRIMARY_KEYWORDS = [
    "customize", "customise", "customization", "customisation", "custom",
    "personalize", "personalise", "configure", "configurator", "builder",
    "design your own", "build yours", "unique", "start", "begin"
]

GATEWAY_SECONDARY_KEYWORDS = [
    "select", "choose", "model", "product", "size", "colour", "color",
    "material", "collection", "cabin", "check-in", "finish", "apply",
    "personal touch", "suitcase", "luggage", "bag", "ring", "frame", "lens"
]

GATEWAY_NEGATIVE_KEYWORDS = [
    "login", "sign in", "search", "wishlist", "my account", "account",
    "discover", "blog", "faq", "help", "service", "services",
    "register", "store locator", "wishlist", "orders"
]

MAX_GATEWAY_NAVIGATION_STEPS = 5
MAX_GATEWAY_CANDIDATES_PER_STEP = 10


def get_gateway_dom_snapshot(page):
    try:
        return page.evaluate(
            r"""
            () => {
                function isVisible(el) {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style || style.visibility === 'hidden' || style.display === 'none' || parseFloat(style.opacity || '1') === 0) return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width >= 8 && rect.height >= 8;
                }

                const dialogs = [...document.querySelectorAll('dialog, [role="dialog"], [aria-modal="true"], .modal, .modal-dialog, .popup, .popin, .c-modal')];
                const visibleDialogs = dialogs.filter(isVisible);

                const clickables = [...document.querySelectorAll('a[href], button, [role="button"], input[type="button"], input[type="submit"]')];
                const visibleClickables = clickables.filter(isVisible);

                const productLikeCards = [...document.querySelectorAll('a[href], button, [role="button"], [data-pid], [data-product-id], [data-productid], .product, .product-tile, .tile, .card')].filter(el => {
                    if (!isVisible(el)) return false;
                    const txt = ((el.innerText || el.textContent || el.getAttribute('aria-label') || '')).replace(/\\s+/g, ' ').trim().toLowerCase();
                    const hasImage = !!el.querySelector('img, picture, svg, canvas');
                    return hasImage && txt.length >= 3;
                });

                const ctaTexts = visibleClickables
                    .map(el => ((el.innerText || el.textContent || el.getAttribute('aria-label') || el.value || '')).replace(/\\s+/g, ' ').trim())
                    .filter(Boolean)
                    .slice(0, 30);

                return {
                    dialog_count: dialogs.length,
                    visible_dialog_count: visibleDialogs.length,
                    visible_clickable_count: visibleClickables.length,
                    product_like_card_count: productLikeCards.length,
                    cta_texts: ctaTexts,
                };
            }
            """
        )
    except Exception:
        return {
            'dialog_count': 0,
            'visible_dialog_count': 0,
            'visible_clickable_count': 0,
            'product_like_card_count': 0,
            'cta_texts': [],
        }


def extract_gateway_click_candidates(page, max_candidates=MAX_GATEWAY_CANDIDATES_PER_STEP):
    try:
        candidates = page.evaluate(
            rf"""
            () => {{
                function isVisible(el) {{
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style || style.visibility === 'hidden' || style.display === 'none' || parseFloat(style.opacity || '1') === 0) return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width >= 10 && rect.height >= 10;
                }}

                function cssEscapeSimple(value) {{
                    try {{
                        return CSS.escape(value);
                    }} catch (e) {{
                        return value.replace(/([^a-zA-Z0-9_-])/g, '\\$1');
                    }}
                }}

                function buildSelector(el) {{
                    if (!el || !el.tagName) return '';
                    if (el.id) return '#' + cssEscapeSimple(el.id);
                    const parts = [];
                    let node = el;
                    while (node && node.nodeType === 1 && node !== document.body) {{
                        let part = node.tagName.toLowerCase();
                        if (node.classList && node.classList.length) {{
                            const useful = [...node.classList].filter(c => !/^js-|^is-|^has-|^u-|^m-|^a-|^c-/.test(c)).slice(0, 2);
                            if (useful.length) part += '.' + useful.map(cssEscapeSimple).join('.');
                        }}
                        const parent = node.parentElement;
                        if (parent) {{
                            const sameTag = [...parent.children].filter(ch => ch.tagName === node.tagName);
                            if (sameTag.length > 1) {{
                                const idx = sameTag.indexOf(node) + 1;
                                part += `:nth-of-type(${{idx}})`;
                            }}
                        }}
                        parts.unshift(part);
                        node = node.parentElement;
                    }}
                    return parts.join(' > ');
                }}

                function textOf(el) {{
                    return ((el.innerText || el.textContent || el.getAttribute('aria-label') || el.value || '') + '').replace(/\\s+/g, ' ').trim();
                }}

                const primaryKeywords = {json.dumps([k.lower() for k in ['customize','customise','customization','customisation','custom','personalize','personalise','configure','configurator','builder','design your own','build yours','unique','start','begin']])};
                const secondaryKeywords = {json.dumps([k.lower() for k in ['select','choose','model','product','size','colour','color','material','collection','cabin','check-in','finish','apply','personal touch','suitcase','luggage','bag','ring','frame','lens']])};
                const negativeKeywords = {json.dumps([k.lower() for k in ['login','sign in','search','wishlist','my account','account','discover','blog','faq','help','service','services','register','store locator','orders']])};

                const nodes = [...document.querySelectorAll('a[href], button, [role="button"], input[type="button"], input[type="submit"]')];
                const out = [];
                const seen = new Set();

                for (const el of nodes) {{
                    if (!isVisible(el)) continue;
                    const text = textOf(el);
                    const href = (el.getAttribute('href') || '').trim();
                    const aria = (el.getAttribute('aria-label') || '').trim();
                    const blob = (text + ' ' + aria + ' ' + href).toLowerCase();
                    const inDialog = !!el.closest('dialog, [role="dialog"], [aria-modal="true"], .modal, .modal-dialog, .popup, .popin, .c-modal');
                    const hasImage = !!el.querySelector('img, picture, svg, canvas');
                    const rect = el.getBoundingClientRect();
                    const selector = buildSelector(el);
                    if (!selector) continue;
                    const key = selector + '|' + blob;
                    if (seen.has(key)) continue;
                    seen.add(key);

                    let score = 0;
                    for (const kw of primaryKeywords) if (blob.includes(kw)) score += 8;
                    for (const kw of secondaryKeywords) if (blob.includes(kw)) score += 3;
                    for (const kw of negativeKeywords) if (blob.includes(kw)) score -= 8;
                    if (inDialog) score += 3;
                    if (hasImage) score += 2;
                    if (href && /custom|customize|customise|unique|builder|configurator|configure/i.test(href)) score += 8;
                    if (href && /search|login|account|wishlist|faq|blog|discover/i.test(href)) score -= 6;
                    if (text && text.length <= 80) score += 1;
                    if (rect.width >= 120 && rect.height >= 40) score += 1;
                    if (text && /^custom/i.test(text)) score += 4;
                    if (text && /(customize|customise now|select|choose)/i.test(text)) score += 4;

                    out.push({{
                        selector, text, href, in_dialog: inDialog, has_image: hasImage, score,
                        rect_w: Math.round(rect.width), rect_h: Math.round(rect.height)
                    }});
                }}

                out.sort((a, b) => b.score - a.score || (b.in_dialog - a.in_dialog) || (b.has_image - a.has_image));
                return out.slice(0, {max_candidates});
            }}
            """
        )
        return candidates or []
    except Exception:
        return []


def is_effective_configurator_page(page):
    try:
        current_url = page.url
    except Exception:
        current_url = ''

    dom_signals = get_page_dom_signals(page)
    snapshot = get_gateway_dom_snapshot(page)

    text_blob = ' '.join(
        clean_lines(' '.join(
            (dom_signals.get('heading_texts') or []) +
            (dom_signals.get('button_texts') or []) +
            (dom_signals.get('link_texts') or []) +
            (dom_signals.get('label_texts') or []) +
            (snapshot.get('cta_texts') or []) +
            [dom_signals.get('meta_description') or '', dom_signals.get('meta_og_description') or '', current_url]
        ))
    ).lower()

    controls_primary = (
        (dom_signals.get('select_count') or 0) +
        (dom_signals.get('radio_count') or 0) +
        (dom_signals.get('checkbox_count') or 0) +
        (dom_signals.get('range_count') or 0) +
        (dom_signals.get('number_input_count') or 0)
    )
    controls_total = controls_primary + (dom_signals.get('option_count') or 0) + (dom_signals.get('button_count') or 0)

    score = 0
    if re.search(r'custom|customi[sz]e|configurator|builder|unique|configure', current_url, flags=re.IGNORECASE):
        score += 2
    if any(kw in text_blob for kw in [
        'apply', 'finish customisation', 'finish customization', 'body colour', 'body color',
        'material', 'profile', 'engraving', 'colour', 'color', 'size', 'lens', 'frame',
        'wheel', 'handle', 'tag', 'model', 'step'
    ]):
        score += 3
    if controls_primary >= 2:
        score += 3
    elif controls_primary == 1:
        score += 1
    if controls_total >= 6:
        score += 2
    if (dom_signals.get('canvas_count') or 0) > 0 or (dom_signals.get('model_viewer_count') or 0) > 0 or (dom_signals.get('webgl_canvas_count') or 0) > 0:
        score += 1
    if any(kw in text_blob for kw in ['apply', 'finish', 'done', 'save', 'next step']):
        score += 2

    if snapshot.get('product_like_card_count', 0) >= 6 and controls_primary == 0 and 'apply' not in text_blob and 'finish' not in text_blob:
        score -= 3

    return score >= 5, score, dom_signals, snapshot


def is_gateway_configurator_page(page):
    effective, eff_score, dom_signals, snapshot = is_effective_configurator_page(page)
    if effective:
        return False, eff_score, dom_signals, snapshot

    try:
        current_url = page.url
    except Exception:
        current_url = ''

    text_blob = ' '.join(
        clean_lines(' '.join(
            (dom_signals.get('heading_texts') or []) +
            (dom_signals.get('button_texts') or []) +
            (dom_signals.get('link_texts') or []) +
            (snapshot.get('cta_texts') or []) +
            [dom_signals.get('meta_description') or '', dom_signals.get('meta_og_description') or '', current_url]
        ))
    ).lower()

    controls_primary = (
        (dom_signals.get('select_count') or 0) +
        (dom_signals.get('radio_count') or 0) +
        (dom_signals.get('checkbox_count') or 0) +
        (dom_signals.get('range_count') or 0) +
        (dom_signals.get('number_input_count') or 0)
    )

    score = 0
    if any(kw in text_blob for kw in GATEWAY_PRIMARY_KEYWORDS):
        score += 4
    if any(kw in text_blob for kw in ['select', 'choose', 'model', 'product', 'size', 'collection', 'cabin', 'check-in']):
        score += 2
    if snapshot.get('visible_dialog_count', 0) > 0:
        score += 3
    if snapshot.get('product_like_card_count', 0) >= 3:
        score += 2
    if snapshot.get('visible_clickable_count', 0) >= 6:
        score += 1
    if re.search(r'custom|customi[sz]e|unique|configurator|builder|configure', current_url, flags=re.IGNORECASE):
        score += 2
    if controls_primary >= 2:
        score -= 2
    if any(kw in text_blob for kw in ['login', 'account', 'wishlist', 'blog']) and score > 0:
        score -= 1

    return score >= 4, score, dom_signals, snapshot


def click_candidate_and_wait(page, selector):
    locator = page.locator(selector).first
    locator.scroll_into_view_if_needed(timeout=2500)
    try:
        locator.click(timeout=5000)
    except Exception:
        locator.click(timeout=5000, force=True)
    try:
        page.wait_for_load_state('networkidle', timeout=4000)
    except Exception:
        pass
    page.wait_for_timeout(1800)
    try_accept_cookies(page)
    page.wait_for_timeout(800)


def resolve_effective_configurator_url(context, start_url):
    if not start_url:
        return {
            'resolved_url': '',
            'page_title': '',
            'note': 'No active URL available for guided gateway resolution',
            'decision_source': 'effective:none',
            'resolved': False,
            'is_gateway_only': False,
            'generic_homepage_like': False,
        }

    page = context.new_page()
    notes = []
    tried_candidates = set()

    try:
        safe_page_goto(page, start_url, timeout_ms=PAGE_GOTO_TIMEOUT_MS, post_wait_ms=POST_GOTO_WAIT_MS)
        try_accept_cookies(page)
        page.wait_for_timeout(1500)

        try:
            initial_title = page.title()
        except Exception:
            initial_title = ''
        try:
            initial_visible_text = page.locator('body').inner_text()
        except Exception:
            initial_visible_text = ''
        initial_dom_signals = get_page_dom_signals(page)
        generic_homepage_like = looks_generic_homepage_like_page(initial_title, page.url, initial_visible_text, initial_dom_signals)

        effective, eff_score, _, _ = is_effective_configurator_page(page)
        if effective:
            return {
                'resolved_url': page.url,
                'page_title': initial_title,
                'note': f'Effective configurator already detected on the initial active page (score={eff_score})',
                'decision_source': 'effective:direct',
                'resolved': True,
                'is_gateway_only': False,
                'generic_homepage_like': False,
            }

        gateway, gateway_score, _, snapshot = is_gateway_configurator_page(page)
        if not gateway:
            note = 'Active page does not look like a gateway that requires guided navigation'
            if generic_homepage_like:
                note = 'Active page looks like a generic homepage/root page, not an effective configurator'
            return {
                'resolved_url': page.url,
                'page_title': initial_title,
                'note': note,
                'decision_source': 'effective:no_gateway',
                'resolved': False,
                'is_gateway_only': False,
                'generic_homepage_like': generic_homepage_like,
            }

        notes.append(f'Gateway page detected (score={gateway_score}, visible_dialogs={snapshot.get("visible_dialog_count", 0)}, product_cards={snapshot.get("product_like_card_count", 0)})')

        for step in range(1, MAX_GATEWAY_NAVIGATION_STEPS + 1):
            candidates = extract_gateway_click_candidates(page, max_candidates=MAX_GATEWAY_CANDIDATES_PER_STEP)
            if not candidates:
                notes.append(f'Gateway step {step}: no promising clickable candidates found')
                break

            progressed = False
            for cand in candidates:
                key = f"{cand.get('selector')}|{cand.get('text')}|{cand.get('href')}"
                if key in tried_candidates:
                    continue
                tried_candidates.add(key)

                before_url = page.url
                before_snapshot = get_gateway_dom_snapshot(page)
                try:
                    click_candidate_and_wait(page, cand['selector'])
                except Exception as exc:
                    notes.append(f"Gateway step {step}: candidate failed [{cand.get('text') or cand.get('href') or cand.get('selector')}] | error={str(exc)}")
                    continue

                after_url = page.url
                after_snapshot = get_gateway_dom_snapshot(page)
                changed = (after_url != before_url) or (after_snapshot.get('visible_dialog_count') != before_snapshot.get('visible_dialog_count')) or (after_snapshot.get('product_like_card_count') != before_snapshot.get('product_like_card_count'))
                notes.append(
                    f"Gateway step {step}: clicked [{cand.get('text') or cand.get('href') or cand.get('selector')}] "
                    f"score={cand.get('score')} changed={'YES' if changed else 'NO'} url={after_url}"
                )

                effective, eff_score, _, _ = is_effective_configurator_page(page)
                if effective:
                    try:
                        title = page.title()
                    except Exception:
                        title = ''
                    return {
                        'resolved_url': page.url,
                        'page_title': title,
                        'note': ' | '.join(notes + [f'Effective configurator reached after guided navigation (score={eff_score})']),
                        'decision_source': 'effective:guided_gateway_clicks',
                        'resolved': True,
                        'is_gateway_only': False,
                        'generic_homepage_like': False,
                    }

                if changed:
                    progressed = True
                    break

            if not progressed:
                notes.append(f'Gateway step {step}: no candidate produced a meaningful page state change')
                break

        try:
            title = page.title()
        except Exception:
            title = ''
        return {
            'resolved_url': page.url,
            'page_title': title,
            'note': ' | '.join(notes + ['Gateway detected, but effective configurator could not be reached automatically']),
            'decision_source': 'effective:gateway_unresolved',
            'resolved': False,
            'is_gateway_only': True,
            'generic_homepage_like': False,
        }
    finally:
        try:
            page.close()
        except Exception:
            pass


# =========================
# HELPER SULLA PAGINA ATTIVA SCELTA
# =========================

def resolve_effective_configurator_on_existing_page(page):
    notes = []
    tried_candidates = set()

    try:
        try_accept_cookies(page)
        page.wait_for_timeout(1500)

        try:
            initial_title = page.title()
        except Exception:
            initial_title = ''
        try:
            initial_visible_text = page.locator('body').inner_text()
        except Exception:
            initial_visible_text = ''
        initial_dom_signals = get_page_dom_signals(page)
        generic_homepage_like = looks_generic_homepage_like_page(initial_title, page.url, initial_visible_text, initial_dom_signals)

        effective, eff_score, _, _ = is_effective_configurator_page(page)
        if effective:
            return {
                'resolved_url': page.url,
                'page_title': initial_title,
                'note': f'Effective configurator already detected on the initial active page (score={eff_score})',
                'decision_source': 'effective:direct',
                'resolved': True,
                'is_gateway_only': False,
                'generic_homepage_like': False,
            }

        gateway, gateway_score, _, snapshot = is_gateway_configurator_page(page)
        if not gateway:
            note = 'Active page does not look like a gateway that requires guided navigation'
            if generic_homepage_like:
                note = 'Active page looks like a generic homepage/root page, not an effective configurator'
            return {
                'resolved_url': page.url,
                'page_title': initial_title,
                'note': note,
                'decision_source': 'effective:no_gateway',
                'resolved': False,
                'is_gateway_only': False,
                'generic_homepage_like': generic_homepage_like,
            }

        notes.append(f'Gateway page detected (score={gateway_score}, visible_dialogs={snapshot.get("visible_dialog_count", 0)}, product_cards={snapshot.get("product_like_card_count", 0)})')

        for step in range(1, MAX_GATEWAY_NAVIGATION_STEPS + 1):
            candidates = extract_gateway_click_candidates(page, max_candidates=MAX_GATEWAY_CANDIDATES_PER_STEP)
            if not candidates:
                notes.append(f'Gateway step {step}: no promising clickable candidates found')
                break

            progressed = False
            for cand in candidates:
                key = f"{cand.get('selector')}|{cand.get('text')}|{cand.get('href')}"
                if key in tried_candidates:
                    continue
                tried_candidates.add(key)

                before_url = page.url
                before_snapshot = get_gateway_dom_snapshot(page)
                try:
                    click_candidate_and_wait(page, cand['selector'])
                except Exception as exc:
                    notes.append(f"Gateway step {step}: candidate failed [{cand.get('text') or cand.get('href') or cand.get('selector')}] | error={str(exc)}")
                    continue

                after_url = page.url
                after_snapshot = get_gateway_dom_snapshot(page)
                changed = (after_url != before_url) or (after_snapshot.get('visible_dialog_count') != before_snapshot.get('visible_dialog_count')) or (after_snapshot.get('product_like_card_count') != before_snapshot.get('product_like_card_count'))
                notes.append(
                    f"Gateway step {step}: clicked [{cand.get('text') or cand.get('href') or cand.get('selector')}] "
                    f"score={cand.get('score')} changed={'YES' if changed else 'NO'} url={after_url}"
                )

                effective, eff_score, _, _ = is_effective_configurator_page(page)
                if effective:
                    try:
                        title = page.title()
                    except Exception:
                        title = ''
                    return {
                        'resolved_url': page.url,
                        'page_title': title,
                        'note': ' | '.join(notes + [f'Effective configurator reached after guided navigation (score={eff_score})']),
                        'decision_source': 'effective:guided_gateway_clicks',
                        'resolved': True,
                        'is_gateway_only': False,
                        'generic_homepage_like': False,
                    }

                if changed:
                    progressed = True
                    break

            if not progressed:
                notes.append(f'Gateway step {step}: no candidate produced a meaningful page state change')
                break

        try:
            title = page.title()
        except Exception:
            title = ''
        return {
            'resolved_url': page.url,
            'page_title': title,
            'note': ' | '.join(notes + ['Gateway detected, but effective configurator could not be reached automatically']),
            'decision_source': 'effective:gateway_unresolved',
            'resolved': False,
            'is_gateway_only': True,
            'generic_homepage_like': False,
        }
    except Exception as exc:
        return {
            'resolved_url': getattr(page, 'url', '') if hasattr(page, 'url') else '',
            'page_title': '',
            'note': f'Error while resolving effective configurator on existing page: {str(exc)}',
            'decision_source': 'effective:error',
            'resolved': False,
            'is_gateway_only': False,
            'generic_homepage_like': False,
        }


def classify_visualization_on_existing_page(page, resource_tracker=None):
    try:
        tipo_visualizzazione, vis_motivo, vis_confidence, raw_output_vis, vis_parser_warning, vis_source = evaluate_visualization_type_with_ollama(
            page,
            resource_tracker=resource_tracker,
        )
        return {
            "tipo_visualizzazione": tipo_visualizzazione,
            "note": f"Tipo visualizzazione: {tipo_visualizzazione} ({vis_motivo})",
            "confidence": vis_confidence,
            "raw_output": raw_output_vis,
            "parser_warning": vis_parser_warning,
            "decision_source": vis_source,
        }
    except Exception as exc:
        try:
            title = page.title()
        except Exception:
            title = ""

        try:
            visible_text = page.locator("body").inner_text()
        except Exception:
            visible_text = ""

        dom_signals = get_page_dom_signals(page)
        network_signals = get_network_resource_signals(page, resource_tracker=resource_tracker)

        hard_rule = detect_visualization_hard_rule(title, page.url, visible_text, dom_signals)
        if hard_rule is not None:
            tipo_visualizzazione, vis_motivo = hard_rule
            return {
                "tipo_visualizzazione": tipo_visualizzazione,
                "note": f"Tipo visualizzazione: {tipo_visualizzazione} ({vis_motivo})",
                "confidence": 100,
                "raw_output": json.dumps({"dom_signals": dom_signals, "network_signals": network_signals}, ensure_ascii=False),
                "parser_warning": f"Fallback dopo errore classificazione deterministica visualizzazione: {str(exc)}",
                "decision_source": "hard_rule_after_visualization_error",
            }

        return {
            "tipo_visualizzazione": "Static 2D",
            "note": "Tipo visualizzazione: Static 2D (fallback prudente dopo errore nella classificazione deterministica)",
            "confidence": 40,
            "raw_output": json.dumps({"dom_signals": dom_signals, "network_signals": network_signals}, ensure_ascii=False),
            "parser_warning": f"Fallback prudente su tipo visualizzazione dopo errore: {str(exc)}",
            "decision_source": "fallback_static_after_visualization_error",
        }


def classify_visualization_from_url(context, active_url):
    page = context.new_page()
    resource_tracker = attach_network_resource_tracker(page)

    try:
        safe_page_goto(page, active_url, timeout_ms=PAGE_GOTO_TIMEOUT_MS, post_wait_ms=POST_GOTO_WAIT_MS)
        try_accept_cookies(page)
        page.wait_for_timeout(2000)
        return classify_visualization_on_existing_page(page, resource_tracker=resource_tracker)
    finally:
        try:
            page.close()
        except Exception:
            pass


def collect_mobile_layout_metrics(page):
    try:
        return page.evaluate(
            r"""
            () => {
                const vw = window.innerWidth || document.documentElement.clientWidth || 0;
                const vh = window.innerHeight || document.documentElement.clientHeight || 0;
                const body = document.body;
                const doc = document.documentElement;

                function isVisible(el) {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity || '1') < 0.05) return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 1 && rect.height > 1;
                }

                const all = [...document.querySelectorAll('body *')];
                let totalControls = 0;
                let smallTapTargets = 0;
                let offscreenControls = 0;
                let textElements = 0;
                let tinyTextElements = 0;
                let largeFixedOverlays = 0;

                for (const el of all) {
                    if (!isVisible(el)) continue;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    const text = ((el.innerText || el.textContent || '') + '').trim();
                    const isControl = el.matches('a, button, input, select, textarea, summary, label, [role="button"], [role="link"], [role="tab"], [role="option"]');

                    if (isControl) {
                        totalControls += 1;
                        if (Math.min(rect.width, rect.height) < 32) smallTapTargets += 1;
                        if (rect.left < -4 || rect.right > vw + 4) offscreenControls += 1;
                    }

                    if (text && text.length > 0 && text.length <= 250) {
                        const fs = parseFloat(style.fontSize || '0');
                        if (fs > 0) {
                            textElements += 1;
                            if (fs < 12) tinyTextElements += 1;
                        }
                    }

                    if ((style.position === 'fixed' || style.position === 'sticky') && rect.width * rect.height >= vw * vh * 0.25) {
                        largeFixedOverlays += 1;
                    }
                }

                const forms = document.querySelectorAll('form').length;
                const inputs = document.querySelectorAll('input, select, textarea').length;
                const buttons = document.querySelectorAll('button, [role="button"]').length;
                const dialogs = document.querySelectorAll('dialog, [role="dialog"], .modal, .popup, .drawer').length;
                const viewportMeta = !!document.querySelector('meta[name="viewport"]');
                const scrollWidth = Math.max(body ? body.scrollWidth : 0, doc ? doc.scrollWidth : 0, body ? body.offsetWidth : 0, doc ? doc.offsetWidth : 0);
                const overflowRatio = vw > 0 ? scrollWidth / vw : 999;
                const ua = navigator.userAgent || '';
                const mobileUaSignals = /(iphone|android|mobile|ipad|ipod)/i.test(ua);
                const coarsePointer = window.matchMedia ? window.matchMedia('(pointer: coarse)').matches : false;
                const hoverNone = window.matchMedia ? window.matchMedia('(hover: none)').matches : false;
                const maxTouchPoints = navigator.maxTouchPoints || 0;
                const bodyClasses = (body && body.className) ? String(body.className) : '';

                return {
                    viewport_width: vw,
                    viewport_height: vh,
                    viewport_meta_present: viewportMeta,
                    scroll_width: scrollWidth,
                    overflow_ratio: overflowRatio,
                    total_controls: totalControls,
                    small_tap_targets: smallTapTargets,
                    offscreen_controls: offscreenControls,
                    text_elements: textElements,
                    tiny_text_elements: tinyTextElements,
                    large_fixed_overlays: largeFixedOverlays,
                    forms: forms,
                    inputs: inputs,
                    buttons: buttons,
                    dialogs: dialogs,
                    title: document.title || '',
                    final_url: window.location.href || '',
                    user_agent: ua,
                    mobile_user_agent_detected: mobileUaSignals,
                    coarse_pointer: coarsePointer,
                    hover_none: hoverNone,
                    max_touch_points: maxTouchPoints,
                    body_classes: bodyClasses,
                };
            }
            """
        )
    except Exception:
        return {
            "viewport_width": MOBILE_VIEWPORT_WIDTH,
            "viewport_height": MOBILE_VIEWPORT_HEIGHT,
            "viewport_meta_present": False,
            "scroll_width": 0,
            "overflow_ratio": 999,
            "total_controls": 0,
            "small_tap_targets": 0,
            "offscreen_controls": 0,
            "text_elements": 0,
            "tiny_text_elements": 0,
            "large_fixed_overlays": 0,
            "forms": 0,
            "inputs": 0,
            "buttons": 0,
            "dialogs": 0,
            "title": "",
            "final_url": "",
            "user_agent": "",
            "mobile_user_agent_detected": False,
            "coarse_pointer": False,
            "hover_none": False,
            "max_touch_points": 0,
            "body_classes": "",
        }


def collect_mobile_layout_metrics_with_scroll(page, steps=MOBILE_SCROLL_STEPS, wait_ms=MOBILE_SCROLL_WAIT_MS):
    snapshots = []

    try:
        page.wait_for_timeout(wait_ms)
        base = collect_mobile_layout_metrics(page)
        snapshots.append(base)

        total_height = page.evaluate(
            "() => Math.max(document.body ? document.body.scrollHeight : 0, document.documentElement ? document.documentElement.scrollHeight : 0, window.innerHeight || 0)"
        )
        viewport_height = int(base.get("viewport_height") or MOBILE_VIEWPORT_HEIGHT or 1)

        if total_height and total_height > viewport_height * 1.15:
            max_scroll = max(int(total_height) - viewport_height, 0)
            if max_scroll > 0:
                positions = sorted({int(round(max_scroll * i / max(steps - 1, 1))) for i in range(steps)})
                for pos in positions[1:]:
                    try:
                        page.evaluate("y => window.scrollTo(0, y)", pos)
                        page.wait_for_timeout(wait_ms)
                        snapshots.append(collect_mobile_layout_metrics(page))
                    except Exception:
                        pass

        try:
            page.evaluate("() => window.scrollTo(0, 0)")
            page.wait_for_timeout(200)
        except Exception:
            pass
    except Exception:
        pass

    if not snapshots:
        snapshots.append(collect_mobile_layout_metrics(page))

    first = snapshots[0]
    aggregate = dict(first)
    aggregate["snapshots_count"] = len(snapshots)
    aggregate["overflow_ratio"] = max(float(s.get("overflow_ratio") or 0) for s in snapshots)
    aggregate["total_controls"] = max(int(s.get("total_controls") or 0) for s in snapshots)
    aggregate["small_tap_targets"] = max(int(s.get("small_tap_targets") or 0) for s in snapshots)
    aggregate["offscreen_controls"] = max(int(s.get("offscreen_controls") or 0) for s in snapshots)
    aggregate["text_elements"] = max(int(s.get("text_elements") or 0) for s in snapshots)
    aggregate["tiny_text_elements"] = max(int(s.get("tiny_text_elements") or 0) for s in snapshots)
    aggregate["large_fixed_overlays"] = max(int(s.get("large_fixed_overlays") or 0) for s in snapshots)
    aggregate["forms"] = max(int(s.get("forms") or 0) for s in snapshots)
    aggregate["inputs"] = max(int(s.get("inputs") or 0) for s in snapshots)
    aggregate["buttons"] = max(int(s.get("buttons") or 0) for s in snapshots)
    aggregate["dialogs"] = max(int(s.get("dialogs") or 0) for s in snapshots)
    aggregate["mobile_user_agent_detected"] = any(bool(s.get("mobile_user_agent_detected")) for s in snapshots)
    aggregate["coarse_pointer"] = any(bool(s.get("coarse_pointer")) for s in snapshots)
    aggregate["hover_none"] = any(bool(s.get("hover_none")) for s in snapshots)
    aggregate["max_touch_points"] = max(int(s.get("max_touch_points") or 0) for s in snapshots)
    aggregate["max_small_tap_ratio"] = max(
        (float(s.get("small_tap_targets") or 0) / max(int(s.get("total_controls") or 0), 1))
        for s in snapshots
    )
    aggregate["max_offscreen_ratio"] = max(
        (float(s.get("offscreen_controls") or 0) / max(int(s.get("total_controls") or 0), 1))
        for s in snapshots
    )
    aggregate["max_tiny_text_ratio"] = max(
        (float(s.get("tiny_text_elements") or 0) / max(int(s.get("text_elements") or 0), 1))
        for s in snapshots
    )
    return aggregate


def mobile_score_to_summary(score):
    if score == 5:
        return "fully usable in a real mobile-emulation context"
    if score == 4:
        return "good mobile adaptation with limited issues"
    if score == 3:
        return "usable on mobile but with noticeable compromises"
    if score == 2:
        return "poor mobile adaptation"
    return "not mobile-friendly"


def evaluate_mobile_optimization_score_deterministic(page):
    metrics = collect_mobile_layout_metrics_with_scroll(page)

    overflow_ratio = float(metrics.get("overflow_ratio") or 999)
    total_controls = int(metrics.get("total_controls") or 0)
    small_tap_targets = int(metrics.get("small_tap_targets") or 0)
    offscreen_controls = int(metrics.get("offscreen_controls") or 0)
    text_elements = int(metrics.get("text_elements") or 0)
    tiny_text_elements = int(metrics.get("tiny_text_elements") or 0)
    large_fixed_overlays = int(metrics.get("large_fixed_overlays") or 0)
    viewport_meta_present = bool(metrics.get("viewport_meta_present"))

    small_tap_ratio = float(metrics.get("max_small_tap_ratio") or 0.0)
    offscreen_ratio = float(metrics.get("max_offscreen_ratio") or 0.0)
    tiny_text_ratio = float(metrics.get("max_tiny_text_ratio") or 0.0)

    reasons = []
    penalty = 0

    if viewport_meta_present:
        reasons.append("viewport meta present")
    else:
        penalty += 1
        reasons.append("viewport meta missing")

    if metrics.get("mobile_user_agent_detected"):
        reasons.append("mobile user-agent delivered")
    else:
        penalty += 1
        reasons.append("mobile user-agent not detected")

    max_touch_points = int(metrics.get("max_touch_points") or 0)
    if metrics.get("coarse_pointer") or metrics.get("hover_none") or max_touch_points >= 1:
        reasons.append("touch/mobile input signals detected")
    else:
        penalty += 1
        reasons.append("touch/mobile input signals missing")

    if overflow_ratio <= 1.03:
        reasons.append("no horizontal overflow")
    elif overflow_ratio <= 1.08:
        penalty += 1
        reasons.append("minor horizontal overflow")
    elif overflow_ratio <= 1.20:
        penalty += 2
        reasons.append("visible horizontal overflow")
    else:
        penalty += 4
        reasons.append("severe horizontal overflow")

    if total_controls >= 4:
        if small_tap_ratio > 0.60:
            penalty += 2
            reasons.append("many small tap targets")
        elif small_tap_ratio > 0.30:
            penalty += 1
            reasons.append("some small tap targets")
        else:
            reasons.append("tap targets mostly adequate")
    elif small_tap_targets >= 3:
        penalty += 1
        reasons.append("several small tap targets")

    if total_controls >= 4:
        if offscreen_ratio > 0.25:
            penalty += 2
            reasons.append("many controls overflow mobile viewport")
        elif offscreen_ratio > 0.10:
            penalty += 1
            reasons.append("some controls overflow mobile viewport")

    if text_elements >= 8:
        if tiny_text_ratio > 0.45:
            penalty += 2
            reasons.append("many text elements are too small")
        elif tiny_text_ratio > 0.20:
            penalty += 1
            reasons.append("some text elements are too small")
        else:
            reasons.append("text size mostly readable")
    elif tiny_text_elements >= 5:
        penalty += 1
        reasons.append("some text appears too small")

    if large_fixed_overlays >= 2:
        penalty += 1
        reasons.append("multiple large fixed overlays")

    score = MOBILE_MAX_SCORE - penalty
    if score < MOBILE_MIN_SCORE:
        score = MOBILE_MIN_SCORE
    if score > MOBILE_MAX_SCORE:
        score = MOBILE_MAX_SCORE

    summary = mobile_score_to_summary(score)
    metrics["summary_reasons"] = reasons
    metrics["deterministic_score"] = score
    metrics["deterministic_summary"] = summary
    return score, summary, metrics


def should_use_ollama_for_mobile_review(metrics, deterministic_score):
    if not ENABLE_MOBILE_OLLAMA_REVIEW:
        return False

    positives = 0
    negatives = 0

    if metrics.get("viewport_meta_present"):
        positives += 1
    else:
        negatives += 1

    if metrics.get("mobile_user_agent_detected"):
        positives += 1
    else:
        negatives += 1

    if metrics.get("coarse_pointer") or metrics.get("hover_none") or int(metrics.get("max_touch_points") or 0) >= 1:
        positives += 1
    else:
        negatives += 1

    overflow_ratio = float(metrics.get("overflow_ratio") or 999)
    if overflow_ratio <= 1.05:
        positives += 1
    elif overflow_ratio > 1.12:
        negatives += 1

    small_tap_ratio = float(metrics.get("max_small_tap_ratio") or 0.0)
    if small_tap_ratio <= 0.20:
        positives += 1
    elif small_tap_ratio >= 0.45:
        negatives += 1

    offscreen_ratio = float(metrics.get("max_offscreen_ratio") or 0.0)
    if offscreen_ratio <= 0.08:
        positives += 1
    elif offscreen_ratio >= 0.20:
        negatives += 1

    tiny_text_ratio = float(metrics.get("max_tiny_text_ratio") or 0.0)
    if tiny_text_ratio <= 0.12:
        positives += 1
    elif tiny_text_ratio >= 0.30:
        negatives += 1

    if int(metrics.get("large_fixed_overlays") or 0) >= 2:
        negatives += 1

    mixed_evidence = positives >= 2 and negatives >= 2

    if deterministic_score == 3:
        return True

    if deterministic_score in {2, 4} and mixed_evidence:
        return True

    if int(metrics.get("dialogs") or 0) >= 1 and mixed_evidence:
        return True

    return False


def evaluate_mobile_optimization_score_with_ollama(page):
    deterministic_score, deterministic_summary, metrics = evaluate_mobile_optimization_score_deterministic(page)

    metrics["ollama_review_triggered"] = False
    metrics["ollama_score"] = ""
    metrics["ollama_confidence"] = ""
    metrics["ollama_reason"] = ""

    if not should_use_ollama_for_mobile_review(metrics, deterministic_score):
        return deterministic_score, deterministic_summary, metrics, "", "", "deterministic_real_mobile_emulation"

    metrics["ollama_review_triggered"] = True

    try:
        title = page.title()
    except Exception:
        title = ""

    try:
        final_url = page.url
    except Exception:
        final_url = ""

    try:
        visible_text = page.locator("body").inner_text()
    except Exception:
        visible_text = ""

    visible_text_excerpt = compress_visible_text(visible_text, max_chars=4500)
    dom_signals = get_page_dom_signals(page)

    prompt = f"""
You are evaluating the MOBILE UX quality of a product configurator page.

Your job is to assign a score from 1 to 5, where:
1 = not mobile-friendly at all
2 = poor mobile experience
3 = usable on mobile but with noticeable compromises
4 = good mobile adaptation with limited issues
5 = excellent mobile adaptation

Important rules:
- The page has already been opened in a REAL mobile-emulation context (mobile user-agent, touch enabled, smartphone viewport).
- Use the structured metrics as the main evidence.
- Use visible text and DOM signals only as supporting context.
- Do not reward a page just because it looks premium or contains little content.
- Focus on usability on a smartphone: readability, fitting in viewport, tap targets, dialogs, controls, likely friction.
- Be conservative and avoid overrating.
- Return ONLY one valid JSON object on a single line.

Exact format:
{{"mobile_score":4,"confidence":82,"reason":"brief explanation"}}

PAGE TITLE:
{title}

FINAL URL:
{final_url}

MOBILE METRICS:
{json.dumps(metrics, ensure_ascii=False)}

DOM SIGNALS:
{json.dumps(dom_signals, ensure_ascii=False)}

VISIBLE TEXT EXCERPT:
{visible_text_excerpt}
""".strip()

    raw_output = ""
    parser_warning = ""
    try:
        raw_output = call_ollama(prompt)
        ollama_score, ollama_confidence, ollama_reason, parser_warning = parse_ollama_mobile_assessment(raw_output)
    except Exception as exc:
        metrics["ollama_error"] = str(exc)
        return deterministic_score, deterministic_summary, metrics, raw_output, str(exc), "deterministic_real_mobile_emulation_after_ollama_failure"

    metrics["ollama_score"] = ollama_score
    metrics["ollama_confidence"] = ollama_confidence
    metrics["ollama_reason"] = ollama_reason

    final_score = deterministic_score
    decision_source = "hybrid_mobile_det_plus_ollama"

    if ollama_confidence >= MOBILE_OLLAMA_MIN_CONFIDENCE:
        if ollama_score > deterministic_score:
            final_score = min(deterministic_score + 1, ollama_score, MOBILE_MAX_SCORE)
        elif ollama_score < deterministic_score:
            final_score = max(deterministic_score - 1, ollama_score, MOBILE_MIN_SCORE)
    else:
        decision_source = "hybrid_mobile_det_plus_ollama_low_confidence"

    metrics["final_mobile_score"] = final_score
    metrics["final_mobile_summary"] = mobile_score_to_summary(final_score)
    return final_score, mobile_score_to_summary(final_score), metrics, raw_output, parser_warning, decision_source


def classify_mobile_optimization_on_existing_page(page):
    if not ENABLE_MOBILE_OPTIMIZATION_SCORE:
        return {
            "mobile_score": "",
            "note": "Ottimizzato per Mobile?: non calcolato (feature disattivata)",
            "raw_output": "",
            "parser_warning": "",
            "decision_source": "disabled",
        }

    score, summary, metrics, raw_output, parser_warning, decision_source = evaluate_mobile_optimization_score_with_ollama(page)

    deterministic_score = metrics.get("deterministic_score", "")
    ollama_score = metrics.get("ollama_score", "")
    ollama_reason = normalize_space(metrics.get("ollama_reason", ""))

    note = f"Ottimizzato per Mobile?: {score}/5 ({summary})"
    if decision_source.startswith("hybrid_mobile"):
        ai_parts = []
        if deterministic_score != "":
            ai_parts.append(f"deterministic={deterministic_score}/5")
        if ollama_score != "":
            ai_parts.append(f"ollama={ollama_score}/5")
        if ollama_reason:
            ai_parts.append(ollama_reason)
        if ai_parts:
            note = note + " | Hybrid review: " + " | ".join(ai_parts)

    payload = {
        "metrics": metrics,
        "ollama_raw_output": raw_output,
    }

    return {
        "mobile_score": score,
        "note": note,
        "raw_output": json.dumps(payload, ensure_ascii=False),
        "parser_warning": parser_warning,
        "decision_source": decision_source,
    }


def classify_mobile_optimization_from_url(mobile_context, active_url):
    if not ENABLE_MOBILE_OPTIMIZATION_SCORE:
        return classify_mobile_optimization_on_existing_page(None)

    page = mobile_context.new_page()

    try:
        safe_page_goto(page, active_url, timeout_ms=PAGE_GOTO_TIMEOUT_MS, post_wait_ms=3500)
        try_accept_cookies(page)
        page.wait_for_timeout(1500)
        return classify_mobile_optimization_on_existing_page(page)
    finally:
        try:
            page.close()
        except Exception:
            pass


def build_mobile_emulation_context(browser, playwright_instance):
    device = playwright_instance.devices.get(MOBILE_DEVICE_PROFILE, {})
    context_kwargs = {
        "ignore_https_errors": True,
    }
    context_kwargs.update(device)
    context_kwargs.setdefault("viewport", {"width": MOBILE_VIEWPORT_WIDTH, "height": MOBILE_VIEWPORT_HEIGHT})
    context_kwargs.setdefault("screen", {"width": MOBILE_VIEWPORT_WIDTH, "height": MOBILE_VIEWPORT_HEIGHT})
    context_kwargs.setdefault("is_mobile", True)
    context_kwargs.setdefault("has_touch", True)
    context_kwargs.setdefault("device_scale_factor", 3)
    return browser.new_context(**context_kwargs)


def collect_compatibility_constraint_metrics(page):
    try:
        metrics = page.evaluate(
            """
            () => {
                function norm(t) {
                    return (t || '').replace(/\\s+/g, ' ').trim();
                }

                function isVisible(el) {
                    if (!el || !(el instanceof Element)) return false;
                    const style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }

                function collectTextHints(patterns, maxItems = 20) {
                    const text = norm(document.body ? document.body.innerText : '');
                    if (!text) return [];
                    const chunks = text.split(/(?<=[.!?])\\s+|\\n+/).map(norm).filter(Boolean);
                    const out = [];
                    const seen = new Set();
                    for (const chunk of chunks) {
                        const low = chunk.toLowerCase();
                        if (patterns.some(p => low.includes(p))) {
                            if (!seen.has(low)) {
                                seen.add(low);
                                out.push(chunk);
                            }
                        }
                        if (out.length >= maxItems) break;
                    }
                    return out;
                }

                const dependencyPatterns = [
                    'only with', 'only available with', 'available only with', 'not compatible', 'cannot be combined',
                    "can't be combined", 'requires', 'depends on', 'after selecting', 'once selected', 'compatible only',
                    'works only with', 'must choose', 'must select', 'select first', 'choose first', 'required before',
                    'nur mit', 'nur verfügbar mit', 'nicht kompatibel', 'kann nicht kombiniert werden', 'erfordert',
                    'abhängig von', 'wählen sie zuerst', 'zuerst wählen', 'erst nach auswahl',
                    'solo con', 'disponibile solo con', 'non compatibile', 'non può essere combinato', 'richiede',
                    'dipende da', 'seleziona prima', 'scegli prima', 'solo dopo aver selezionato',
                    'uniquement avec', 'disponible uniquement avec', 'incompatible', 'ne peut pas être combiné',
                    'nécessite', 'dépend de', 'choisissez d\'abord',
                    'disponible solo con', 'no se puede combinar', 'requiere', 'depende de', 'seleccione primero', 'elige primero'
                ];

                const validationPatterns = [
                    'please select', 'select first', 'choose first', 'required', 'must choose', 'must select',
                    'invalid combination', 'not valid', 'not compatible', 'available only with', 'requires',
                    'wählen sie', 'erforderlich', 'ungültige kombination', 'nicht kompatibel', 'nur verfügbar mit',
                    'seleziona', 'obbligatorio', 'combinazione non valida', 'non compatibile', 'solo con', 'richiede',
                    'choisissez', 'obligatoire', 'combinaison non valide', 'incompatible', 'uniquement avec', 'nécessite',
                    'seleccione', 'obligatorio', 'combinación no válida', 'incompatible', 'solo con', 'requiere'
                ];

                const disabledSelector = ':disabled, [disabled], [aria-disabled="true"], [data-disabled="true"], [data-available="false"], [data-unavailable="true"]';
                const disabledControls = [...document.querySelectorAll(`button${disabledSelector}, input${disabledSelector}, select${disabledSelector}, textarea${disabledSelector}, [role="button"][aria-disabled="true"], [role="option"][aria-disabled="true"], [role="radio"][aria-disabled="true"], [role="checkbox"][aria-disabled="true"]`)];
                const disabledOptions = [...document.querySelectorAll('option:disabled, option[disabled], option[aria-disabled="true"]')];

                const stateNodes = [...document.querySelectorAll('[class], [data-state], [data-status], [aria-disabled], [disabled]')];
                let unavailableStateCount = 0;
                const unavailableRegex = /(disabled|unavailable|sold-?out|out-?of-?stock|not-?available|inactive|locked|forbidden|blocked|hidden|ausverkauft|nicht-?verfugbar|nicht-?verfügbar|indisponible|agotado|esaurito|non-?disponibile)/i;
                for (const el of stateNodes) {
                    const blob = [el.className || '', el.getAttribute('data-state') || '', el.getAttribute('data-status') || '', el.getAttribute('aria-label') || ''].join(' ');
                    if (unavailableRegex.test(blob)) unavailableStateCount += 1;
                }

                const optionGroups = [...document.querySelectorAll('fieldset, select, [role="radiogroup"], [role="group"], [data-option], [data-attribute], [data-variant], [data-component*="option" i], .swatch, .product-option, .option-group')].filter(el => isVisible(el));
                const radios = [...document.querySelectorAll('input[type="radio"], [role="radio"]')].filter(el => isVisible(el)).length;
                const checkboxes = [...document.querySelectorAll('input[type="checkbox"], [role="checkbox"]')].filter(el => isVisible(el)).length;
                const selects = [...document.querySelectorAll('select')].filter(el => isVisible(el)).length;
                const visibleButtons = [...document.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"]')].filter(el => isVisible(el)).length;
                const steppers = [...document.querySelectorAll('[class*="step" i], [data-step], .step, .steps, .wizard, .progress-step, [role="tablist"] [role="tab"]')].filter(el => isVisible(el)).length;
                const forms = [...document.querySelectorAll('form')].filter(el => isVisible(el)).length;
                const dialogs = [...document.querySelectorAll('dialog, [role="dialog"], .modal, .popup')].filter(el => isVisible(el)).length;

                return {
                    compatibility_text_hints: collectTextHints(dependencyPatterns, 20),
                    validation_text_hints: collectTextHints(validationPatterns, 20),
                    disabled_controls: disabledControls.length,
                    disabled_options: disabledOptions.length,
                    unavailable_state_count: unavailableStateCount,
                    option_group_count: optionGroups.length,
                    radio_count: radios,
                    checkbox_count: checkboxes,
                    select_count: selects,
                    visible_button_count: visibleButtons,
                    stepper_count: steppers,
                    form_count: forms,
                    dialog_count: dialogs,
                    body_text_length: norm(document.body ? document.body.innerText : '').length
                };
            }
            """
        )
        return metrics
    except Exception:
        return {
            "compatibility_text_hints": [],
            "validation_text_hints": [],
            "disabled_controls": 0,
            "disabled_options": 0,
            "unavailable_state_count": 0,
            "option_group_count": 0,
            "radio_count": 0,
            "checkbox_count": 0,
            "select_count": 0,
            "visible_button_count": 0,
            "stepper_count": 0,
            "form_count": 0,
            "dialog_count": 0,
            "body_text_length": 0,
        }


def collect_compatibility_state_snapshot(page):
    try:
        snapshot = page.evaluate(
            """
            () => {
                function norm(t) {
                    return (t || '').replace(/\\s+/g, ' ').trim();
                }

                function isVisible(el) {
                    if (!el || !(el instanceof Element)) return false;
                    const style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }

                function textFromElement(el) {
                    if (!el) return '';
                    const direct = norm(el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '');
                    if (direct) return direct;
                    const forId = el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
                    if (forId) {
                        const txt = norm(forId.innerText || forId.textContent || '');
                        if (txt) return txt;
                    }
                    const closestLabel = el.closest('label');
                    if (closestLabel) {
                        const txt = norm(closestLabel.innerText || closestLabel.textContent || '');
                        if (txt) return txt;
                    }
                    return '';
                }

                function groupKeyFor(el) {
                    const fieldset = el.closest('fieldset');
                    if (fieldset) {
                        const legend = fieldset.querySelector('legend');
                        const legendText = norm(legend ? (legend.innerText || legend.textContent || '') : '');
                        if (legendText) return 'fieldset:' + legendText.toLowerCase().slice(0, 80);
                    }
                    const attributed = el.closest('[data-attribute], [data-option], [data-variant], .option-group, .product-option, .swatch, [role="radiogroup"], [role="group"]');
                    if (attributed) {
                        const attrBits = [
                            attributed.getAttribute('data-attribute') || '',
                            attributed.getAttribute('data-option') || '',
                            attributed.getAttribute('data-variant') || '',
                            attributed.getAttribute('aria-label') || '',
                            attributed.getAttribute('id') || '',
                            attributed.className || ''
                        ].map(norm).filter(Boolean);
                        if (attrBits.length) return 'group:' + attrBits.join('|').toLowerCase().slice(0, 100);
                    }
                    if (el.matches('select')) {
                        return 'select:' + norm(el.name || el.id || el.getAttribute('aria-label') || textFromElement(el)).toLowerCase().slice(0, 80);
                    }
                    if (el.matches('input[type="radio"], input[type="checkbox"]')) {
                        return 'input:' + norm(el.name || el.id || textFromElement(el)).toLowerCase().slice(0, 80);
                    }
                    const nameish = norm(el.getAttribute('name') || el.getAttribute('aria-label') || el.getAttribute('data-name') || '');
                    if (nameish) return 'misc:' + nameish.toLowerCase().slice(0, 80);
                    return 'misc:' + norm(textFromElement(el)).toLowerCase().slice(0, 80);
                }

                function isDisabledLike(el) {
                    const cls = String(el.className || '');
                    const blob = [
                        cls,
                        el.getAttribute('data-state') || '',
                        el.getAttribute('data-status') || '',
                        el.getAttribute('aria-disabled') || '',
                        el.getAttribute('disabled') || ''
                    ].join(' ').toLowerCase();
                    return el.disabled ||
                        el.getAttribute('disabled') !== null ||
                        el.getAttribute('aria-disabled') === 'true' ||
                        el.getAttribute('data-disabled') === 'true' ||
                        el.getAttribute('data-available') === 'false' ||
                        el.getAttribute('data-unavailable') === 'true' ||
                        /(disabled|unavailable|sold-?out|out-?of-?stock|inactive|locked|blocked|hidden|not-?available|not-?compatible|forbidden|ausverkauft|indisponible|agotado|esaurito)/.test(blob);
                }

                function isSelectedLike(el) {
                    const cls = String(el.className || '');
                    return !!(
                        el.selected || el.checked ||
                        el.getAttribute('aria-selected') === 'true' ||
                        el.getAttribute('aria-checked') === 'true' ||
                        el.getAttribute('data-selected') === 'true' ||
                        el.getAttribute('data-active') === 'true' ||
                        /(selected|active|current|checked|chosen)/i.test(cls)
                    );
                }

                function pushState(groupMap, groupKey, text, disabled, selected) {
                    if (!groupKey) return;
                    if (!groupMap[groupKey]) {
                        groupMap[groupKey] = { total: 0, disabled: 0, selected_count: 0, texts: [], selected_texts: [] };
                    }
                    const g = groupMap[groupKey];
                    g.total += 1;
                    if (disabled) g.disabled += 1;
                    if (selected) g.selected_count += 1;
                    if (text && g.texts.length < 12 && !g.texts.includes(text)) g.texts.push(text);
                    if (selected && text && g.selected_texts.length < 6 && !g.selected_texts.includes(text)) g.selected_texts.push(text);
                }

                const groupMap = {};
                let disabledTotal = 0;
                let optionLikeTotal = 0;

                const visibleSelects = [...document.querySelectorAll('select')].filter(el => isVisible(el));
                for (const select of visibleSelects) {
                    const groupKey = groupKeyFor(select);
                    const options = [...select.options || []];
                    for (const opt of options) {
                        const text = norm(opt.textContent || opt.label || opt.value || '');
                        const disabled = !!opt.disabled;
                        const selected = !!opt.selected;
                        pushState(groupMap, groupKey, text, disabled, selected);
                        optionLikeTotal += 1;
                        if (disabled) disabledTotal += 1;
                    }
                }

                const others = [...document.querySelectorAll('input[type="radio"], input[type="checkbox"], [role="option"], [role="radio"], [role="checkbox"], button, [role="button"], .swatch, [data-option], [data-attribute-value], [data-variant-value]')]
                    .filter(el => isVisible(el));

                for (const el of others) {
                    if (el.matches('button, [role="button"]')) {
                        const roleish = [el.type || '', el.getAttribute('data-action') || '', el.getAttribute('aria-label') || '', norm(el.innerText || el.textContent || '')].join(' ').toLowerCase();
                        if (/(add to cart|buy now|checkout|wishlist|search|menu|close|sign in|login|account|help|share)/.test(roleish)) continue;
                    }
                    const text = textFromElement(el);
                    if (!text) continue;
                    const disabled = isDisabledLike(el);
                    const selected = isSelectedLike(el);
                    const groupKey = groupKeyFor(el);
                    pushState(groupMap, groupKey, text, disabled, selected);
                    optionLikeTotal += 1;
                    if (disabled) disabledTotal += 1;
                }

                const groups = Object.entries(groupMap).map(([group_key, data]) => ({
                    group_key,
                    total: data.total,
                    disabled: data.disabled,
                    selected_count: data.selected_count,
                    text_fingerprint: data.texts.join(' | ').toLowerCase(),
                    selected_fingerprint: data.selected_texts.join(' | ').toLowerCase()
                }));

                return {
                    disabled_total: disabledTotal,
                    option_like_total: optionLikeTotal,
                    group_count: groups.length,
                    groups
                };
            }
            """
        )
        return snapshot
    except Exception:
        return {
            "disabled_total": 0,
            "option_like_total": 0,
            "group_count": 0,
            "groups": [],
        }


def collect_compatibility_probe_candidates(page, max_candidates=COMPATIBILITY_PROBE_MAX_CANDIDATES):
    try:
        candidates = page.evaluate(
            f"""
            () => {{
                const MAX_CANDIDATES = {int(COMPATIBILITY_PROBE_MAX_CANDIDATES)};
                function norm(t) {{
                    return (t || '').replace(/\\s+/g, ' ').trim();
                }}

                function isVisible(el) {{
                    if (!el || !(el instanceof Element)) return false;
                    const style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }}

                function textFromElement(el) {{
                    if (!el) return '';
                    const direct = norm(el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '');
                    if (direct) return direct;
                    const forId = el.id ? document.querySelector(`label[for="${{CSS.escape(el.id)}}"]`) : null;
                    if (forId) return norm(forId.innerText || forId.textContent || '');
                    const closestLabel = el.closest('label');
                    if (closestLabel) return norm(closestLabel.innerText || closestLabel.textContent || '');
                    return '';
                }}

                function groupKeyFor(el) {{
                    const fieldset = el.closest('fieldset');
                    if (fieldset) {{
                        const legend = fieldset.querySelector('legend');
                        const legendText = norm(legend ? (legend.innerText || legend.textContent || '') : '');
                        if (legendText) return 'fieldset:' + legendText.toLowerCase().slice(0, 80);
                    }}
                    const attributed = el.closest('[data-attribute], [data-option], [data-variant], .option-group, .product-option, .swatch, [role="radiogroup"], [role="group"]');
                    if (attributed) {{
                        const attrBits = [
                            attributed.getAttribute('data-attribute') || '',
                            attributed.getAttribute('data-option') || '',
                            attributed.getAttribute('data-variant') || '',
                            attributed.getAttribute('aria-label') || '',
                            attributed.getAttribute('id') || '',
                            attributed.className || ''
                        ].map(norm).filter(Boolean);
                        if (attrBits.length) return 'group:' + attrBits.join('|').toLowerCase().slice(0, 100);
                    }}
                    return 'misc:' + norm(el.getAttribute('name') || el.getAttribute('aria-label') || el.id || textFromElement(el)).toLowerCase().slice(0, 80);
                }}

                function isDisabledLike(el) {{
                    const cls = String(el.className || '');
                    const blob = [cls, el.getAttribute('data-state') || '', el.getAttribute('data-status') || '', el.getAttribute('aria-disabled') || ''].join(' ').toLowerCase();
                    return !!(
                        el.disabled ||
                        el.getAttribute('disabled') !== null ||
                        el.getAttribute('aria-disabled') === 'true' ||
                        el.getAttribute('data-disabled') === 'true' ||
                        el.getAttribute('data-available') === 'false' ||
                        el.getAttribute('data-unavailable') === 'true' ||
                        /(disabled|unavailable|sold-?out|out-?of-?stock|inactive|locked|blocked|hidden|forbidden|not-?available)/.test(blob)
                    );
                }}

                function isSelectedLike(el) {{
                    const cls = String(el.className || '');
                    return !!(
                        el.selected || el.checked ||
                        el.getAttribute('aria-selected') === 'true' ||
                        el.getAttribute('aria-checked') === 'true' ||
                        el.getAttribute('data-selected') === 'true' ||
                        el.getAttribute('data-active') === 'true' ||
                        /(selected|active|current|checked|chosen)/i.test(cls)
                    );
                }}

                const skipPattern = /(add to cart|buy now|checkout|wishlist|search|menu|close|sign in|login|account|help|share|continue|next|previous|back|submit|save|cart)/i;
                const groupCounts = new Map();
                const seen = new Set();
                const out = [];
                let probeCounter = 0;

                function maybePush(el, action, extra={{}}) {{
                    if (!el || !isVisible(el) || isDisabledLike(el)) return;
                    const text = textFromElement(el);
                    if (!text || text.length < 1) return;
                    if (skipPattern.test(text)) return;
                    const groupKey = groupKeyFor(el);
                    const dedupKey = [groupKey, action, text.toLowerCase()].join('|');
                    if (seen.has(dedupKey)) return;
                    const currentGroupCount = groupCounts.get(groupKey) || 0;
                    if (currentGroupCount >= 2) return;
                    probeCounter += 1;
                    const probeId = `compat-probe-${{Date.now()}}-${{probeCounter}}`;
                    el.setAttribute('data-compat-probe-id', probeId);
                    out.push({{
                        probe_id: probeId,
                        group_key: groupKey,
                        action,
                        label: text.slice(0, 120),
                        alt_value: extra.alt_value || '',
                        alt_label: extra.alt_label || ''
                    }});
                    seen.add(dedupKey);
                    groupCounts.set(groupKey, currentGroupCount + 1);
                }}

                const selects = [...document.querySelectorAll('select')].filter(el => isVisible(el) && !isDisabledLike(el));
                for (const select of selects) {{
                    const options = [...select.options || []].filter(opt => !opt.disabled);
                    const currentValue = select.value;
                    const alt = options.find(opt => String(opt.value || '') !== String(currentValue || '') && norm(opt.textContent || opt.label || opt.value || ''));
                    if (alt) {{
                        maybePush(select, 'select', {{ alt_value: String(alt.value || ''), alt_label: norm(alt.textContent || alt.label || alt.value || '') }});
                    }}
                    if (out.length >= MAX_CANDIDATES) return out;
                }}

                const clickable = [...document.querySelectorAll('input[type="radio"], input[type="checkbox"], label, [role="option"], [role="radio"], [role="checkbox"], button, [role="button"], .swatch, [data-option], [data-attribute-value], [data-variant-value]')]
                    .filter(el => isVisible(el));

                for (const el of clickable) {{
                    if (out.length >= MAX_CANDIDATES) break;
                    if (isSelectedLike(el)) continue;
                    if (el.matches('label')) {{
                        const input = el.querySelector('input[type="radio"], input[type="checkbox"]') || (el.getAttribute('for') ? document.getElementById(el.getAttribute('for')) : null);
                        if (input && !isSelectedLike(input) && !isDisabledLike(input)) {{
                            maybePush(el, 'click');
                        }}
                        continue;
                    }}
                    maybePush(el, 'click');
                }}

                return out.slice(0, MAX_CANDIDATES);
            }}
            """
        )
        return candidates[:max_candidates]
    except Exception:
        return []


def perform_compatibility_probe_action(page, candidate):
    probe_id = candidate.get("probe_id", "")
    if not probe_id:
        return False, "missing_probe_id"

    locator = page.locator(f'[data-compat-probe-id="{probe_id}"]').first

    try:
        locator.scroll_into_view_if_needed(timeout=2500)
    except Exception:
        pass

    action = candidate.get("action", "click")
    try:
        if action == "select":
            alt_value = candidate.get("alt_value", "")
            if alt_value == "":
                return False, "missing_alt_value"
            locator.select_option(value=alt_value, timeout=3000)
        else:
            locator.click(timeout=3000)
    except Exception as exc:
        return False, str(exc)

    try:
        page.wait_for_load_state("networkidle", timeout=2000)
    except Exception:
        pass
    page.wait_for_timeout(COMPATIBILITY_PROBE_WAIT_MS)
    return True, ""


def compare_compatibility_snapshots(before, after, acted_group_key=""):
    before_groups = {g.get("group_key", ""): g for g in (before.get("groups") or []) if g.get("group_key")}
    after_groups = {g.get("group_key", ""): g for g in (after.get("groups") or []) if g.get("group_key")}

    all_keys = set(before_groups.keys()) | set(after_groups.keys())
    group_changes = []
    external_group_changes = []
    disabled_delta_other = 0
    text_changes_other = 0
    selected_changes_other = 0
    total_delta_other = 0

    for key in all_keys:
        b = before_groups.get(key, {"total": 0, "disabled": 0, "selected_count": 0, "text_fingerprint": "", "selected_fingerprint": ""})
        a = after_groups.get(key, {"total": 0, "disabled": 0, "selected_count": 0, "text_fingerprint": "", "selected_fingerprint": ""})

        changed = (
            int(a.get("total") or 0) != int(b.get("total") or 0) or
            int(a.get("disabled") or 0) != int(b.get("disabled") or 0) or
            int(a.get("selected_count") or 0) != int(b.get("selected_count") or 0) or
            str(a.get("text_fingerprint") or "") != str(b.get("text_fingerprint") or "") or
            str(a.get("selected_fingerprint") or "") != str(b.get("selected_fingerprint") or "")
        )
        if not changed:
            continue

        group_changes.append(key)
        if acted_group_key and key == acted_group_key:
            continue

        external_group_changes.append(key)
        disabled_delta_other += max(0, int(a.get("disabled") or 0) - int(b.get("disabled") or 0))
        total_delta_other += abs(int(a.get("total") or 0) - int(b.get("total") or 0))
        if str(a.get("text_fingerprint") or "") != str(b.get("text_fingerprint") or ""):
            text_changes_other += 1
        if str(a.get("selected_fingerprint") or "") != str(b.get("selected_fingerprint") or "") or int(a.get("selected_count") or 0) != int(b.get("selected_count") or 0):
            selected_changes_other += 1

    comparison = {
        "any_change": bool(group_changes) or int(after.get("disabled_total") or 0) != int(before.get("disabled_total") or 0),
        "group_changes": group_changes,
        "external_group_changes": external_group_changes,
        "external_group_change_count": len(external_group_changes),
        "disabled_delta_other": disabled_delta_other,
        "text_changes_other": text_changes_other,
        "selected_changes_other": selected_changes_other,
        "total_delta_other": total_delta_other,
        "global_disabled_delta": int(after.get("disabled_total") or 0) - int(before.get("disabled_total") or 0),
        "global_option_like_delta": int(after.get("option_like_total") or 0) - int(before.get("option_like_total") or 0),
    }
    comparison["dependency_like_change"] = bool(
        comparison["external_group_change_count"] >= 1 or
        comparison["disabled_delta_other"] >= 1 or
        comparison["text_changes_other"] >= 1 or
        comparison["selected_changes_other"] >= 1 or
        comparison["total_delta_other"] >= 1
    )
    return comparison


def run_compatibility_dependency_probes(page):
    candidates = collect_compatibility_probe_candidates(page, max_candidates=COMPATIBILITY_PROBE_MAX_CANDIDATES)
    probe_metrics = {
        "probe_candidates_found": len(candidates),
        "probe_actions_attempted": 0,
        "probe_actions_successful": 0,
        "probe_any_change_events": 0,
        "probe_dependency_events": 0,
        "probe_disabled_increase_events": 0,
        "probe_max_external_group_changes": 0,
        "probe_max_disabled_delta_other": 0,
        "probe_max_text_changes_other": 0,
        "probe_max_selected_changes_other": 0,
        "probe_max_total_delta_other": 0,
        "probe_reasons": [],
        "probe_samples": [],
    }

    if not candidates:
        probe_metrics["probe_reasons"].append("no safe interactive candidates found for compatibility probing")
        return probe_metrics

    for candidate in candidates[:COMPATIBILITY_PROBE_MAX_ACTIONS]:
        probe_metrics["probe_actions_attempted"] += 1
        before = collect_compatibility_state_snapshot(page)
        success, error = perform_compatibility_probe_action(page, candidate)
        if not success:
            if error:
                probe_metrics["probe_samples"].append({"label": candidate.get("label", ""), "status": "failed", "error": error})
            continue

        probe_metrics["probe_actions_successful"] += 1
        after = collect_compatibility_state_snapshot(page)
        comparison = compare_compatibility_snapshots(before, after, acted_group_key=candidate.get("group_key", ""))

        if comparison["any_change"]:
            probe_metrics["probe_any_change_events"] += 1
        if comparison["dependency_like_change"]:
            probe_metrics["probe_dependency_events"] += 1
        if comparison["disabled_delta_other"] > 0:
            probe_metrics["probe_disabled_increase_events"] += 1

        probe_metrics["probe_max_external_group_changes"] = max(probe_metrics["probe_max_external_group_changes"], comparison["external_group_change_count"])
        probe_metrics["probe_max_disabled_delta_other"] = max(probe_metrics["probe_max_disabled_delta_other"], comparison["disabled_delta_other"])
        probe_metrics["probe_max_text_changes_other"] = max(probe_metrics["probe_max_text_changes_other"], comparison["text_changes_other"])
        probe_metrics["probe_max_selected_changes_other"] = max(probe_metrics["probe_max_selected_changes_other"], comparison["selected_changes_other"])
        probe_metrics["probe_max_total_delta_other"] = max(probe_metrics["probe_max_total_delta_other"], comparison["total_delta_other"])

        probe_metrics["probe_samples"].append({
            "label": candidate.get("label", ""),
            "action": candidate.get("action", ""),
            "group_key": candidate.get("group_key", ""),
            "dependency_like_change": comparison["dependency_like_change"],
            "external_group_change_count": comparison["external_group_change_count"],
            "disabled_delta_other": comparison["disabled_delta_other"],
            "text_changes_other": comparison["text_changes_other"],
            "selected_changes_other": comparison["selected_changes_other"],
            "total_delta_other": comparison["total_delta_other"],
        })

    if probe_metrics["probe_dependency_events"] >= 3 or probe_metrics["probe_max_external_group_changes"] >= 3:
        probe_metrics["probe_reasons"].append("multiple probes changed other option groups after a selection")
    elif probe_metrics["probe_dependency_events"] >= 1:
        probe_metrics["probe_reasons"].append("at least one probe changed options outside the selected group")
    elif probe_metrics["probe_any_change_events"] >= 1:
        probe_metrics["probe_reasons"].append("probes changed local selection state but not later options")
    else:
        probe_metrics["probe_reasons"].append("interactive probes did not reveal visible cross-option dependencies")

    return probe_metrics


def compatibility_score_to_summary(score):
    if score == 5:
        return "highly constrained configurator: early choices strongly limit later ones"
    if score == 4:
        return "strong dependencies between choices with several later options constrained"
    if score == 3:
        return "moderate dependency logic between configuration steps or option groups"
    if score == 2:
        return "limited compatibility constraints: some dependency is visible but remains light"
    return "little or no visible dependency between choices"


def evaluate_compatibility_constraints_score_deterministic(page):
    metrics = collect_compatibility_constraint_metrics(page)
    probe_metrics = run_compatibility_dependency_probes(page)
    metrics.update(probe_metrics)

    disabled_controls = int(metrics.get("disabled_controls") or 0)
    disabled_options = int(metrics.get("disabled_options") or 0)
    unavailable_state_count = int(metrics.get("unavailable_state_count") or 0)
    option_group_count = int(metrics.get("option_group_count") or 0)
    radio_count = int(metrics.get("radio_count") or 0)
    checkbox_count = int(metrics.get("checkbox_count") or 0)
    select_count = int(metrics.get("select_count") or 0)
    stepper_count = int(metrics.get("stepper_count") or 0)
    compatibility_text_hints = metrics.get("compatibility_text_hints") or []
    validation_text_hints = metrics.get("validation_text_hints") or []

    disabled_total = disabled_controls + disabled_options + unavailable_state_count
    option_density = option_group_count + select_count + radio_count + checkbox_count
    dependency_events = int(metrics.get("probe_dependency_events") or 0)
    any_change_events = int(metrics.get("probe_any_change_events") or 0)
    max_external_group_changes = int(metrics.get("probe_max_external_group_changes") or 0)
    max_disabled_delta_other = int(metrics.get("probe_max_disabled_delta_other") or 0)
    max_text_changes_other = int(metrics.get("probe_max_text_changes_other") or 0)
    max_selected_changes_other = int(metrics.get("probe_max_selected_changes_other") or 0)
    max_total_delta_other = int(metrics.get("probe_max_total_delta_other") or 0)

    evidence_points = 0
    reasons = []

    if dependency_events >= 3 or max_external_group_changes >= 3 or max_disabled_delta_other >= 4:
        evidence_points += 5
        reasons.append("interactive probes show strong cross-option dependencies")
    elif dependency_events >= 2 or max_external_group_changes >= 2 or max_disabled_delta_other >= 2:
        evidence_points += 4
        reasons.append("interactive probes show multiple later options changing after a selection")
    elif dependency_events >= 1:
        evidence_points += 2
        reasons.append("at least one interaction changed later option groups")
    elif any_change_events >= 1:
        reasons.append("interactions mainly changed the selected option itself")

    if max_text_changes_other >= 2 or max_selected_changes_other >= 2 or max_total_delta_other >= 3:
        evidence_points += 1
        reasons.append("later option sets visibly changed after interaction")

    compatibility_hint_count = len(compatibility_text_hints)
    if compatibility_hint_count >= 4:
        evidence_points += 2
        reasons.append("many textual hints mention dependencies between options")
    elif compatibility_hint_count >= 1:
        evidence_points += 1
        reasons.append("text mentions compatibility or prerequisite logic")

    validation_hint_count = len(validation_text_hints)
    if validation_hint_count >= 3:
        evidence_points += 1
        reasons.append("several prerequisite or validation messages are visible")
    elif validation_hint_count >= 1 and dependency_events == 0:
        reasons.append("some prerequisite messages are visible, but interaction evidence is weak")

    if disabled_total >= 12 and option_density >= 6:
        evidence_points += 1
        reasons.append("many option states are already visibly constrained")
    elif disabled_total >= 4 and option_density >= 4 and dependency_events >= 1:
        evidence_points += 1
        reasons.append("disabled options are coherent with dependency changes")

    if stepper_count >= 2 and dependency_events >= 1:
        evidence_points += 1
        reasons.append("multi-step configurator with dependencies across steps")

    if evidence_points <= 0:
        score = 1
    elif evidence_points <= 2:
        score = 2
    elif evidence_points <= 4:
        score = 3
    elif evidence_points <= 6:
        score = 4
    else:
        score = 5

    metrics["disabled_total"] = disabled_total
    metrics["compatibility_hint_count"] = compatibility_hint_count
    metrics["validation_hint_count"] = validation_hint_count
    metrics["option_density"] = option_density
    metrics["deterministic_score"] = score
    metrics["deterministic_summary"] = compatibility_score_to_summary(score)
    metrics["summary_reasons"] = reasons + (probe_metrics.get("probe_reasons") or [])
    return score, compatibility_score_to_summary(score), metrics


def should_use_ollama_for_compatibility_review(metrics, deterministic_score):
    if not ENABLE_COMPATIBILITY_OLLAMA_REVIEW:
        return False

    if deterministic_score == 3:
        return True

    dependency_events = int(metrics.get("probe_dependency_events") or 0)
    compatibility_hint_count = int(metrics.get("compatibility_hint_count") or 0)
    validation_hint_count = int(metrics.get("validation_hint_count") or 0)
    disabled_total = int(metrics.get("disabled_total") or 0)
    max_external_group_changes = int(metrics.get("probe_max_external_group_changes") or 0)

    mixed_evidence = (
        (dependency_events == 0 and compatibility_hint_count >= 1 and disabled_total >= 1) or
        (dependency_events >= 1 and compatibility_hint_count == 0 and validation_hint_count == 0) or
        (max_external_group_changes == 1 and deterministic_score in {2, 4})
    )

    if deterministic_score in {2, 4} and mixed_evidence:
        return True

    return False


def evaluate_compatibility_constraints_score_with_ollama(page):
    deterministic_score, deterministic_summary, metrics = evaluate_compatibility_constraints_score_deterministic(page)

    metrics["ollama_review_triggered"] = False
    metrics["ollama_score"] = ""
    metrics["ollama_confidence"] = ""
    metrics["ollama_reason"] = ""

    if not should_use_ollama_for_compatibility_review(metrics, deterministic_score):
        return deterministic_score, deterministic_summary, metrics, "", "", "deterministic_compatibility_interactive"

    metrics["ollama_review_triggered"] = True

    try:
        title = page.title()
    except Exception:
        title = ""

    try:
        final_url = page.url
    except Exception:
        final_url = ""

    try:
        visible_text = page.locator("body").inner_text()
    except Exception:
        visible_text = ""

    visible_text_excerpt = compress_visible_text(visible_text, max_chars=4500)
    dom_signals = get_page_dom_signals(page)

    prompt = f"""
You are evaluating how strongly a product configurator constrains later choices after an earlier choice is made.

Score from 1 to 5, where:
1 = choices are almost completely independent
2 = light constraints, only a few later options are affected
3 = moderate dependency logic
4 = strong dependency logic, many later options are filtered or disabled
5 = highly constrained configurator, early choices strongly determine later ones

Important rules:
- Focus ONLY on dependencies between choices.
- A field being merely required is weak evidence.
- Out-of-stock or commercial availability alone is weak evidence.
- The strongest evidence is when interacting with one option changes other groups later in the flow.
- Use interactive probe metrics as the main evidence.
- Be conservative and avoid overrating.
- Return ONLY one valid JSON object on a single line.

Exact format:
{{"compatibility_score":3,"confidence":80,"reason":"brief explanation"}}

PAGE TITLE:
{title}

FINAL URL:
{final_url}

COMPATIBILITY METRICS:
{json.dumps(metrics, ensure_ascii=False)}

DOM SIGNALS:
{json.dumps(dom_signals, ensure_ascii=False)}

VISIBLE TEXT EXCERPT:
{visible_text_excerpt}
""".strip()

    raw_output = ""
    parser_warning = ""
    try:
        raw_output = call_ollama(prompt)
        ollama_score, ollama_confidence, ollama_reason, parser_warning = parse_ollama_compatibility_assessment(raw_output)
    except Exception as exc:
        metrics["ollama_error"] = str(exc)
        return deterministic_score, deterministic_summary, metrics, raw_output, str(exc), "deterministic_compatibility_after_ollama_failure"

    metrics["ollama_score"] = ollama_score
    metrics["ollama_confidence"] = ollama_confidence
    metrics["ollama_reason"] = ollama_reason

    final_score = deterministic_score
    decision_source = "hybrid_compatibility_interactive_det_plus_ollama"

    if ollama_confidence >= COMPATIBILITY_OLLAMA_MIN_CONFIDENCE:
        if ollama_score > deterministic_score:
            final_score = min(deterministic_score + 1, ollama_score, 5)
        elif ollama_score < deterministic_score:
            final_score = max(deterministic_score - 1, ollama_score, 1)
    else:
        decision_source = "hybrid_compatibility_interactive_det_plus_ollama_low_confidence"

    metrics["final_compatibility_score"] = final_score
    metrics["final_compatibility_summary"] = compatibility_score_to_summary(final_score)
    return final_score, compatibility_score_to_summary(final_score), metrics, raw_output, parser_warning, decision_source


def classify_compatibility_constraints_on_existing_page(page):
    if not ENABLE_COMPATIBILITY_CONSTRAINT_SCORE:
        return {
            "compatibility_score": "",
            "note": "Presenza di regole/vincoli di compatibilità?: non calcolata (feature disattivata)",
            "raw_output": "",
            "parser_warning": "",
            "decision_source": "disabled",
        }

    score, summary, metrics, raw_output, parser_warning, decision_source = evaluate_compatibility_constraints_score_with_ollama(page)

    deterministic_score = metrics.get("deterministic_score", "")
    ollama_score = metrics.get("ollama_score", "")
    ollama_reason = normalize_space(metrics.get("ollama_reason", ""))

    note = f"Presenza di regole/vincoli di compatibilità?: {score}/5 ({summary})"
    note = note + f" | Probes: {metrics.get('probe_dependency_events', 0)} dependency events over {metrics.get('probe_actions_successful', 0)} successful interactions"
    if decision_source.startswith("hybrid_compatibility"):
        ai_parts = []
        if deterministic_score != "":
            ai_parts.append(f"deterministic={deterministic_score}/5")
        if ollama_score != "":
            ai_parts.append(f"ollama={ollama_score}/5")
        if ollama_reason:
            ai_parts.append(ollama_reason)
        if ai_parts:
            note = note + " | Hybrid review: " + " | ".join(ai_parts)

    payload = {
        "metrics": metrics,
        "ollama_raw_output": raw_output,
    }

    return {
        "compatibility_score": score,
        "note": note,
        "raw_output": json.dumps(payload, ensure_ascii=False),
        "parser_warning": parser_warning,
        "decision_source": decision_source,
    }


def analyze_active_configurator_on_existing_page(page, mobile_context, resource_tracker=None):
    effective_result = resolve_effective_configurator_on_existing_page(page)
    effective_url = effective_result.get("resolved_url") or page.url
    effective_title = effective_result.get("page_title", "")

    if effective_result.get("generic_homepage_like", False) and not effective_result.get("resolved", False):
        return {
            "effective_result": effective_result,
            "effective_url": effective_url,
            "effective_title": effective_title,
            "mobile_info": {"mobile_score": "", "note": "", "raw_output": "", "parser_warning": "", "decision_source": "skipped_generic_homepage"},
            "compat_info": {"compatibility_score": "", "note": "", "raw_output": "", "parser_warning": "", "decision_source": "skipped_generic_homepage"},
            "complexity_info": {"complexity_score": "", "note": "", "raw_output": "", "parser_warning": "", "decision_source": "skipped_generic_homepage"},
            "vis_info": {"tipo_visualizzazione": "", "note": "", "raw_output": "", "parser_warning": "", "decision_source": "skipped_generic_homepage"},
        }

    vis_info = classify_visualization_on_existing_page(page, resource_tracker=resource_tracker) if ENABLE_VISUALIZATION_TYPE else {
        "tipo_visualizzazione": "", "note": "Tipo visualizzazione: disattivato", "raw_output": "", "parser_warning": "", "decision_source": "disabled"
    }
    compat_info = classify_compatibility_constraints_on_existing_page(page) if ENABLE_COMPATIBILITY_CONSTRAINT_SCORE else {
        "compatibility_score": "", "note": "Presenza di regole/vincoli di compatibilità?: disattivato", "raw_output": "", "parser_warning": "", "decision_source": "disabled"
    }
    compat_metrics = {}
    if compat_info.get("raw_output"):
        try:
            compat_payload = json.loads(compat_info["raw_output"])
            compat_metrics = compat_payload.get("metrics", {}) if isinstance(compat_payload, dict) else {}
        except Exception:
            compat_metrics = {}
    complexity_info = classify_complexity_on_existing_page(page, compatibility_metrics=compat_metrics) if ENABLE_COMPLEXITY_SCORE else {
        "complexity_score": "", "note": "Livello di Complessità: disattivato", "raw_output": "", "parser_warning": "", "decision_source": "disabled"
    }
    mobile_info = classify_mobile_optimization_from_url(mobile_context, effective_url) if ENABLE_MOBILE_OPTIMIZATION_SCORE else {
        "mobile_score": "", "note": "Ottimizzato per Mobile?: disattivato", "raw_output": "", "parser_warning": "", "decision_source": "disabled"
    }

    return {
        "effective_result": effective_result,
        "effective_url": effective_url,
        "effective_title": effective_title,
        "mobile_info": mobile_info,
        "compat_info": compat_info,
        "complexity_info": complexity_info,
        "vis_info": vis_info,
    }


def classify_compatibility_constraints_from_url(context, active_url):
    if not ENABLE_COMPATIBILITY_CONSTRAINT_SCORE:
        return classify_compatibility_constraints_on_existing_page(None)

    page = context.new_page()

    try:
        safe_page_goto(page, active_url, timeout_ms=PAGE_GOTO_TIMEOUT_MS, post_wait_ms=3500)
        try_accept_cookies(page)
        page.wait_for_timeout(1500)
        return classify_compatibility_constraints_on_existing_page(page)
    finally:
        try:
            page.close()
        except Exception:
            pass


# =========================
# ELABORAZIONE SINGOLA RIGA
# =========================
def process_one_detail_url(context, mobile_context, detail_url):
    detail_page = context.new_page()

    company = ""
    product = ""
    industry = ""
    country = ""
    configurator_url = ""

    note_parts = []
    raw_parts = []

    try:
        safe_page_goto(detail_page, detail_url, timeout_ms=PAGE_GOTO_TIMEOUT_MS, post_wait_ms=3000)
        try_accept_cookies(detail_page)

        detail_data = extract_detail_data(detail_page)
        company = detail_data["company"]
        product = detail_data["product"]
        industry = detail_data["industry"]
        country = detail_data["country"]
        configurator_url = detail_data["configurator_url"]

        original_attivo = "NO"
        original_confidence = ""
        original_title = ""
        original_final_url = ""
        original_decision_source = "hard_rule"

        config_page = None
        config_resource_tracker = None
        if configurator_url:
            config_page = context.new_page()
            config_resource_tracker = attach_network_resource_tracker(config_page)
            try:
                safe_page_goto(config_page, configurator_url, timeout_ms=PAGE_GOTO_TIMEOUT_MS, post_wait_ms=POST_GOTO_WAIT_MS)
                try_accept_cookies(config_page)
                config_page.wait_for_timeout(2000)

                (
                    original_attivo,
                    original_motivo,
                    original_confidence,
                    original_title,
                    original_final_url,
                    raw_output_attivo,
                    parser_warning,
                    original_decision_source,
                ) = evaluate_configurator_page_with_ollama(config_page)

                note_parts.append(f"Link originale: {original_motivo}")
                if parser_warning:
                    note_parts.append(parser_warning)
                if raw_output_attivo:
                    raw_parts.append(f"[ORIGINAL_ATTIVO]\n{raw_output_attivo}")

            except Exception as exc:
                original_attivo = "NO"
                note_parts.append(f"Link originale: errore apertura/configurazione ({str(exc)})")
                original_decision_source = "original:error"
        else:
            note_parts.append("Link originale: TRY THE CONFIGURATOR non trovato")
            original_decision_source = "original:no_link"

        if original_attivo == "SI" and config_page is not None:
            analysis_bundle = analyze_active_configurator_on_existing_page(config_page, mobile_context, resource_tracker=config_resource_tracker)
            effective_result = analysis_bundle["effective_result"]
            effective_url = analysis_bundle["effective_url"]
            effective_title = analysis_bundle["effective_title"] or original_title
            effective_source = effective_result.get("decision_source", "effective:none")
            effective_note = effective_result.get("note", "")
            generic_homepage_like = effective_result.get("generic_homepage_like", False)
            mobile_info = analysis_bundle["mobile_info"]
            compat_info = analysis_bundle["compat_info"]
            complexity_info = analysis_bundle["complexity_info"]
            vis_info = analysis_bundle["vis_info"]

            if effective_note:
                note_parts.append(f"Effective resolver: {effective_note}")

            if generic_homepage_like and not effective_result.get("resolved"):
                note_parts.append("Original active verdict overridden: final page looks like a generic homepage/root page, not an effective configurator")
                original_attivo = "NO"
            else:
                note_parts.append(mobile_info["note"])
                note_parts.append(compat_info["note"])
                note_parts.append(complexity_info["note"])
                note_parts.append(vis_info["note"])
                if mobile_info["parser_warning"]:
                    note_parts.append(mobile_info["parser_warning"])
                if compat_info["parser_warning"]:
                    note_parts.append(compat_info["parser_warning"])
                if complexity_info["parser_warning"]:
                    note_parts.append(complexity_info["parser_warning"])
                if vis_info["parser_warning"]:
                    note_parts.append(vis_info["parser_warning"])
                if mobile_info["raw_output"]:
                    raw_parts.append(f"[MOBILE_OPTIMIZATION]\n{mobile_info['raw_output']}")
                if compat_info["raw_output"]:
                    raw_parts.append(f"[COMPATIBILITY_CONSTRAINTS]\n{compat_info['raw_output']}")
                if vis_info["raw_output"]:
                    raw_parts.append(f"[TIPO_VISUALIZZAZIONE]\n{vis_info['raw_output']}")

                alternative_effective_url = ""
                norm_original = normalize_url_for_dedup(original_final_url or configurator_url)
                norm_effective = normalize_url_for_dedup(effective_url)
                if norm_effective and norm_original and norm_effective != norm_original:
                    alternative_effective_url = effective_url

                return {
                    "Industry": industry,
                    "Country": country,
                    "Company": company,
                    "Product": product,
                    "Configurator URL": configurator_url,
                    "Attivo SI/NO": "SI",
                    "Configurator URL alternativa": alternative_effective_url,
                    "Tipo di visualizzazione": vis_info["tipo_visualizzazione"],
                    "Ottimizzato per Mobile?": mobile_info["mobile_score"],
                    "Presenza di regole/vincoli di compatibilità?": compat_info["compatibility_score"],
                    "Livello di Complessità": complexity_info["complexity_score"],
                    "Page title": effective_title,
                    "AI confidence": original_confidence,
                    "Note": " | ".join([part for part in note_parts if part]),
                    "Parser warning": " | ".join([p for p in [vis_info["parser_warning"], mobile_info["parser_warning"], compat_info["parser_warning"], complexity_info["parser_warning"]] if p]),
                    "Decision source": f"{original_decision_source}|{effective_source}|vis:{vis_info['decision_source']}|mob:{mobile_info['decision_source']}|comp:{compat_info['decision_source']}|cx:{complexity_info['decision_source']}",
                    "Database detail URL": detail_url,
                    "AI raw output": "\n\n".join(raw_parts),
                    "Row processing seconds": "",
                }

        if config_page is not None:
            try:
                config_page.close()
            except Exception:
                pass

        seed_urls = build_internal_discovery_seed_urls(
            detail_page=detail_page,
            configurator_url=configurator_url,
            original_final_url=original_final_url,
            company=company,
        )
        alt_result = find_alternative_configurator(context, company, product, country, seed_urls)
        note_parts.append(alt_result["note"])
        if alt_result["raw_output"]:
            raw_parts.append(alt_result["raw_output"])

        if alt_result["found"]:
            alt_page = context.new_page()
            alt_resource_tracker = attach_network_resource_tracker(alt_page)
            try:
                safe_page_goto(alt_page, alt_result["alternative_url"], timeout_ms=PAGE_GOTO_TIMEOUT_MS, post_wait_ms=POST_GOTO_WAIT_MS)
                try_accept_cookies(alt_page)
                alt_page.wait_for_timeout(1500)

                alt_bundle = analyze_active_configurator_on_existing_page(alt_page, mobile_context, resource_tracker=alt_resource_tracker)
                effective_alt = alt_bundle["effective_result"]
                effective_alt_url = alt_bundle["effective_url"] or alt_result["alternative_url"]
                effective_alt_title = alt_bundle["effective_title"] or alt_result["page_title"]
                effective_alt_source = effective_alt.get("decision_source", "effective:none")
                if effective_alt.get("note"):
                    note_parts.append(f"Alternative effective resolver: {effective_alt['note']}")

                mobile_info = alt_bundle["mobile_info"]
                compat_info = alt_bundle["compat_info"]
                complexity_info = alt_bundle["complexity_info"]
                vis_info = alt_bundle["vis_info"]
                note_parts.append(mobile_info["note"])
                note_parts.append(compat_info["note"])
                note_parts.append(vis_info["note"])
                if mobile_info["parser_warning"]:
                    note_parts.append(mobile_info["parser_warning"])
                if compat_info["parser_warning"]:
                    note_parts.append(compat_info["parser_warning"])
                if vis_info["parser_warning"]:
                    note_parts.append(vis_info["parser_warning"])
                if mobile_info["raw_output"]:
                    raw_parts.append(f"[MOBILE_OPTIMIZATION]\n{mobile_info['raw_output']}")
                if compat_info["raw_output"]:
                    raw_parts.append(f"[COMPATIBILITY_CONSTRAINTS]\n{compat_info['raw_output']}")
                if vis_info["raw_output"]:
                    raw_parts.append(f"[TIPO_VISUALIZZAZIONE]\n{vis_info['raw_output']}")

                return {
                    "Industry": industry,
                    "Country": country,
                    "Company": company,
                    "Product": product,
                    "Configurator URL": configurator_url,
                    "Attivo SI/NO": "SI",
                    "Configurator URL alternativa": effective_alt_url,
                    "Tipo di visualizzazione": vis_info["tipo_visualizzazione"],
                    "Ottimizzato per Mobile?": mobile_info["mobile_score"],
                    "Presenza di regole/vincoli di compatibilità?": compat_info["compatibility_score"],
                    "Livello di Complessità": complexity_info["complexity_score"],
                    "Page title": effective_alt_title,
                    "AI confidence": alt_result["confidence"],
                    "Note": " | ".join([part for part in note_parts if part]),
                    "Parser warning": " | ".join([p for p in [vis_info["parser_warning"], mobile_info["parser_warning"], compat_info["parser_warning"], complexity_info["parser_warning"]] if p]),
                    "Decision source": f"{original_decision_source}|{alt_result['decision_source']}|{effective_alt_source}|vis:{vis_info['decision_source']}|mob:{mobile_info['decision_source']}|comp:{compat_info['decision_source']}|cx:{complexity_info['decision_source']}",
                    "Database detail URL": detail_url,
                    "AI raw output": "\n\n".join(raw_parts),
                    "Row processing seconds": "",
                }
            finally:
                try:
                    alt_page.close()
                except Exception:
                    pass

        return {
            "Industry": industry,
            "Country": country,
            "Company": company,
            "Product": product,
            "Configurator URL": configurator_url,
            "Attivo SI/NO": "NO",
            "Configurator URL alternativa": "",
            "Tipo di visualizzazione": "",
            "Ottimizzato per Mobile?": "",
            "Presenza di regole/vincoli di compatibilità?": "",
            "Livello di Complessità": "",
            "Page title": "",
            "AI confidence": original_confidence,
            "Note": " | ".join([part for part in note_parts if part]),
            "Parser warning": "",
            "Decision source": f"{original_decision_source}|{alt_result['decision_source']}",
            "Database detail URL": detail_url,
            "AI raw output": "\n\n".join(raw_parts),
            "Row processing seconds": "",
        }

    except Exception as e:
        return {
            "Industry": industry,
            "Country": country,
            "Company": company,
            "Product": product,
            "Configurator URL": configurator_url,
            "Attivo SI/NO": "",
            "Configurator URL alternativa": "",
            "Tipo di visualizzazione": "",
            "Ottimizzato per Mobile?": "",
            "Presenza di regole/vincoli di compatibilità?": "",
            "Livello di Complessità": "",
            "Page title": "",
            "AI confidence": "",
            "Note": f"Errore: {str(e)}",
            "Parser warning": "",
            "Decision source": "error",
            "Database detail URL": detail_url,
            "AI raw output": "\n\n".join(raw_parts),
            "Row processing seconds": "",
        }

    finally:
        try:
            if 'config_page' in locals() and config_page is not None:
                config_page.close()
        except Exception:
            pass
        try:
            detail_page.close()
        except Exception:
            pass


# =========================
# RESUME
# =========================
def load_input_urls(input_file):
    df_links = pd.read_excel(input_file)

    if "Database detail URL" not in df_links.columns:
        raise ValueError("Nel file Excel manca la colonna 'Database detail URL'")

    urls = df_links["Database detail URL"].dropna().astype(str).tolist()

    seen = set()
    unique_urls = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)

    return unique_urls


def load_existing_output(output_file):
    if not os.path.exists(output_file):
        return pd.DataFrame()
    return pd.read_excel(output_file)


def get_processed_urls(existing_df):
    if existing_df.empty:
        return set()
    if "Database detail URL" not in existing_df.columns:
        return set()
    return set(existing_df["Database detail URL"].dropna().astype(str).tolist())



def normalize_compatibility_probe_indexes(value, max_count):
    out = []
    if isinstance(value, list):
        items = value
    else:
        items = [value]
    for item in items:
        try:
            idx = int(item)
        except Exception:
            continue
        if 1 <= idx <= max_count and idx not in out:
            out.append(idx)
    return out


def parse_ollama_compatibility_probe_plan(raw_output, max_count):
    parsed = try_parse_json_candidates(raw_output)
    if parsed is not None:
        for key in ["selected_indexes", "indexes", "selected_indices", "candidate_indexes", "candidate_indices"]:
            indexes = normalize_compatibility_probe_indexes(parsed.get(key, []), max_count)
            if indexes:
                reason = normalize_space(parsed.get("reason") or parsed.get("motivation") or parsed.get("why") or "")
                confidence = normalize_confidence(parsed.get("confidence", ""))
                return indexes, confidence, reason, ""
        single = normalize_compatibility_probe_indexes(parsed.get("selected_index", parsed.get("index", "")), max_count)
        if single:
            reason = normalize_space(parsed.get("reason") or parsed.get("motivation") or parsed.get("why") or "")
            confidence = normalize_confidence(parsed.get("confidence", ""))
            return single, confidence, reason, ""

    indexes = []
    text = strip_code_fences(raw_output)
    for field in ["selected_indexes", "indexes", "selected_index", "index"]:
        value = regex_extract_field(text, field)
        if value:
            nums = re.findall(r"\d+", value)
            indexes = normalize_compatibility_probe_indexes(nums, max_count)
            if indexes:
                break
    if not indexes:
        nums = re.findall(r"\b(\d+)\b", text)
        indexes = normalize_compatibility_probe_indexes(nums, max_count)
        if indexes:
            indexes = indexes[:1]

    if indexes:
        reason = normalize_space(
            regex_extract_field(text, "reason")
            or regex_extract_field(text, "motivation")
            or regex_extract_field(text, "why")
        )
        confidence = normalize_confidence(regex_extract_field(text, "confidence"))
        return indexes, confidence, reason, "Ollama compatibility probe plan response was recovered with a permissive parser"

    raise ValueError(f"Unable to interpret compatibility probe plan: {raw_output}")


def humanize_probe_group_key(group_key):
    group_key = normalize_space(group_key)
    if not group_key:
        return "unknown group"
    group_key = re.sub(r'^(fieldset:|group:|misc:)', '', group_key, flags=re.IGNORECASE)
    group_key = group_key.replace('|', ' / ').replace('_', ' ')
    return normalize_space(group_key)[:120]


def build_probe_candidate_summary(candidate, index):
    label = normalize_space(candidate.get("label", "")) or "unlabeled option"
    action = normalize_space(candidate.get("action", "click")) or "click"
    alt_label = normalize_space(candidate.get("alt_label", ""))
    group_label = humanize_probe_group_key(candidate.get("group_key", ""))
    description = f"{index}. group='{group_label}' | action={action} | option='{label}'"
    if alt_label:
        description += f" | alternative='{alt_label}'"
    return description


def fallback_pick_probe_candidate(candidates, used_group_keys):
    for idx, candidate in enumerate(candidates, start=1):
        group_key = candidate.get("group_key", "")
        if group_key and group_key in used_group_keys:
            continue
        return idx, "fallback: first plausible unused option group"
    if candidates:
        return 1, "fallback: first plausible option"
    return 0, "fallback: no candidate"



def collect_compatibility_view_state(page):
    try:
        url = page.url
    except Exception:
        url = ""
    try:
        title = page.title()
    except Exception:
        title = ""
    try:
        visible_text = page.locator("body").inner_text()
    except Exception:
        visible_text = ""
    excerpt = compress_visible_text(visible_text, max_chars=1200)
    try:
        dom_signals = get_page_dom_signals(page)
        heading_texts = [normalize_space(x) for x in (dom_signals.get("heading_texts") or []) if normalize_space(x)]
    except Exception:
        heading_texts = []
    fingerprint = " | ".join([
        normalize_space(url),
        normalize_space(title),
        normalize_space(" || ".join(heading_texts[:5])),
        normalize_space(excerpt[:500]),
    ])
    return {
        "url": url,
        "title": title,
        "heading_texts": heading_texts[:8],
        "visible_excerpt": excerpt,
        "fingerprint": fingerprint,
    }


def perform_compatibility_probe_action_with_transition(page, candidate):
    probe_id = candidate.get("probe_id", "")
    if not probe_id:
        return False, "missing_probe_id", {}

    before_state = collect_compatibility_view_state(page)
    locator = page.locator(f'[data-compat-probe-id="{probe_id}"]').first

    try:
        locator.scroll_into_view_if_needed(timeout=2500)
    except Exception:
        pass

    action = candidate.get("action", "click")
    nav_warning = ""
    try:
        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=COMPATIBILITY_NAVIGATION_TIMEOUT_MS):
                if action == "select":
                    alt_value = candidate.get("alt_value", "")
                    if alt_value == "":
                        return False, "missing_alt_value", {}
                    locator.select_option(value=alt_value, timeout=3000)
                else:
                    locator.click(timeout=3000)
        except Exception as exc:
            nav_warning = str(exc)
    except Exception as exc:
        return False, str(exc), {}

    try:
        page.wait_for_load_state("networkidle", timeout=3000)
    except Exception:
        pass
    page.wait_for_timeout(COMPATIBILITY_PROBE_WAIT_MS)

    after_state = collect_compatibility_view_state(page)
    url_changed = normalize_space(after_state.get("url")) != normalize_space(before_state.get("url"))
    title_changed = normalize_space(after_state.get("title")) != normalize_space(before_state.get("title"))
    heading_changed = normalize_space(" || ".join(after_state.get("heading_texts", [])[:5])) != normalize_space(" || ".join(before_state.get("heading_texts", [])[:5]))
    excerpt_changed = normalize_space(after_state.get("visible_excerpt", "")[:300]) != normalize_space(before_state.get("visible_excerpt", "")[:300])

    layer_advanced = bool(url_changed or title_changed or (heading_changed and excerpt_changed))
    transition = {
        "before_url": before_state.get("url", ""),
        "after_url": after_state.get("url", ""),
        "before_title": before_state.get("title", ""),
        "after_title": after_state.get("title", ""),
        "url_changed": url_changed,
        "title_changed": title_changed,
        "heading_changed": heading_changed,
        "excerpt_changed": excerpt_changed,
        "layer_advanced": layer_advanced,
        "nav_warning": nav_warning,
        "before_excerpt": before_state.get("visible_excerpt", "")[:300],
        "after_excerpt": after_state.get("visible_excerpt", "")[:300],
    }
    return True, "", transition


def choose_next_compatibility_probe_candidate_with_ollama(page, candidates, previous_steps, metrics, used_group_keys, current_layer=1):
    if not candidates:
        return 0, {"raw_output": "", "parser_warning": "", "reason": "", "confidence": "", "decision_source": "no_candidates"}

    try:
        title = page.title()
    except Exception:
        title = ""
    try:
        final_url = page.url
    except Exception:
        final_url = ""
    try:
        visible_text = page.locator("body").inner_text()
    except Exception:
        visible_text = ""

    visible_text_excerpt = compress_visible_text(visible_text, max_chars=2600)
    dom_signals = get_page_dom_signals(page)
    candidate_lines = [build_probe_candidate_summary(candidate, idx) for idx, candidate in enumerate(candidates, start=1)]
    previous_json = json.dumps(previous_steps[-4:], ensure_ascii=False)
    metrics_json = json.dumps({
        "option_group_count": metrics.get("option_group_count", 0),
        "radio_count": metrics.get("radio_count", 0),
        "checkbox_count": metrics.get("checkbox_count", 0),
        "select_count": metrics.get("select_count", 0),
        "stepper_count": metrics.get("stepper_count", 0),
        "disabled_controls": metrics.get("disabled_controls", 0),
        "disabled_options": metrics.get("disabled_options", 0),
        "compatibility_text_hints": metrics.get("compatibility_text_hints", []),
        "validation_text_hints": metrics.get("validation_text_hints", []),
    }, ensure_ascii=False)

    prompt = f"""
You are choosing the next product-personalization action to probe compatibility constraints in a configurator.

Goal:
- Choose ONE candidate action that is most likely to reveal whether selecting one category limits later categories.
- Prefer real personalization controls (materials, sizes, variants, finishes, components, accessories, engraving options, model choices, etc.).
- Avoid navigation, cart, checkout, login, help, generic CTA, or obvious non-customization buttons.
- Avoid repeating the same option group unless the configurator appears strictly sequential.
- Same-group exclusivity does NOT count as a compatibility constraint. Example: selecting one color naturally deselects the other colors in that same color group. That is normal and should not be the focus.
- Prefer actions that could affect DIFFERENT groups later in the flow.
- If the configurator appears ordered, prefer the earliest sensible next choice in that order.

Return ONLY one JSON object on one line.
Exact format:
{{"selected_index": 2, "confidence": 82, "reason": "brief explanation"}}

PAGE TITLE:
{title}

FINAL URL:
{final_url}

CURRENT METRICS:
{metrics_json}

USED GROUP KEYS:
{json.dumps(sorted(list(used_group_keys)), ensure_ascii=False)}

CURRENT LAYER:
{current_layer}

PREVIOUS PROBE STEPS:
{previous_json}

CANDIDATE ACTIONS:
{chr(10).join(candidate_lines)}

DOM SIGNALS:
{json.dumps(dom_signals, ensure_ascii=False)}

VISIBLE TEXT EXCERPT:
{visible_text_excerpt}
""".strip()

    raw_output = ""
    try:
        raw_output = call_ollama(prompt)
        indexes, confidence, reason, parser_warning = parse_ollama_compatibility_probe_plan(raw_output, len(candidates))
        if indexes:
            return indexes[0], {
                "raw_output": raw_output,
                "parser_warning": parser_warning,
                "reason": reason,
                "confidence": confidence,
                "decision_source": "ollama_guided_probe_selection",
            }
    except Exception as exc:
        fallback_idx, fallback_reason = fallback_pick_probe_candidate(candidates, used_group_keys)
        return fallback_idx, {
            "raw_output": raw_output,
            "parser_warning": str(exc),
            "reason": fallback_reason,
            "confidence": "",
            "decision_source": "fallback_probe_selection_after_ollama_failure",
        }

    fallback_idx, fallback_reason = fallback_pick_probe_candidate(candidates, used_group_keys)
    return fallback_idx, {
        "raw_output": raw_output,
        "parser_warning": "",
        "reason": fallback_reason,
        "confidence": "",
        "decision_source": "fallback_probe_selection_after_empty_ollama",
    }


def run_ai_guided_compatibility_dependency_probes(page, base_metrics):
    probe_metrics = {
        "probe_candidates_found": 0,
        "probe_actions_attempted": 0,
        "probe_actions_successful": 0,
        "probe_any_change_events": 0,
        "probe_dependency_events": 0,
        "probe_disabled_increase_events": 0,
        "probe_max_external_group_changes": 0,
        "probe_max_disabled_delta_other": 0,
        "probe_max_text_changes_other": 0,
        "probe_max_selected_changes_other": 0,
        "probe_max_total_delta_other": 0,
        "probe_reasons": [],
        "probe_samples": [],
        "probe_selection_trace": [],
        "probe_selection_raw_outputs": [],
        "probe_selection_parser_warnings": [],
        "probe_navigation_events": 0,
        "probe_layer_advances": 0,
        "probe_layers_visited": 1,
    }

    previous_steps = []
    used_group_keys = set()
    current_layer = 1

    for step_idx in range(COMPATIBILITY_PROBE_MAX_ACTIONS):
        candidates = collect_compatibility_probe_candidates(page, max_candidates=max(COMPATIBILITY_PROBE_MAX_CANDIDATES, 8))
        if step_idx == 0:
            probe_metrics["probe_candidates_found"] = len(candidates)
        if not candidates:
            probe_metrics["probe_reasons"].append("no safe personalization candidates found for AI-guided compatibility probing")
            break

        selected_index, selection_meta = choose_next_compatibility_probe_candidate_with_ollama(
            page, candidates, previous_steps, base_metrics, used_group_keys, current_layer=current_layer
        )
        if not selected_index or selected_index > len(candidates):
            probe_metrics["probe_reasons"].append("AI-guided probing could not select a valid candidate")
            break

        candidate = candidates[selected_index - 1]
        used_group_keys.add(candidate.get("group_key", ""))
        probe_metrics["probe_actions_attempted"] += 1
        probe_metrics["probe_selection_trace"].append({
            "step": step_idx + 1,
            "layer": current_layer,
            "selected_index": selected_index,
            "label": candidate.get("label", ""),
            "group_key": candidate.get("group_key", ""),
            "decision_source": selection_meta.get("decision_source", ""),
            "confidence": selection_meta.get("confidence", ""),
            "reason": selection_meta.get("reason", ""),
        })
        if selection_meta.get("raw_output"):
            probe_metrics["probe_selection_raw_outputs"].append(selection_meta.get("raw_output", ""))
        if selection_meta.get("parser_warning"):
            probe_metrics["probe_selection_parser_warnings"].append(selection_meta.get("parser_warning", ""))

        before = collect_compatibility_state_snapshot(page)
        success, error, transition = perform_compatibility_probe_action_with_transition(page, candidate)
        if not success:
            previous_steps.append({
                "step": step_idx + 1,
                "layer": current_layer,
                "candidate": build_probe_candidate_summary(candidate, selected_index),
                "status": "failed",
                "error": error,
            })
            probe_metrics["probe_samples"].append({
                "step": step_idx + 1,
                "layer": current_layer,
                "label": candidate.get("label", ""),
                "group_key": candidate.get("group_key", ""),
                "status": "failed",
                "error": error,
            })
            continue

        probe_metrics["probe_actions_successful"] += 1
        after = collect_compatibility_state_snapshot(page)
        comparison = compare_compatibility_snapshots(before, after, acted_group_key=candidate.get("group_key", ""))

        if comparison["any_change"]:
            probe_metrics["probe_any_change_events"] += 1
        if comparison["dependency_like_change"]:
            probe_metrics["probe_dependency_events"] += 1
        if comparison["disabled_delta_other"] > 0:
            probe_metrics["probe_disabled_increase_events"] += 1

        if transition.get("url_changed"):
            probe_metrics["probe_navigation_events"] += 1
        if transition.get("layer_advanced"):
            probe_metrics["probe_layer_advances"] += 1

        probe_metrics["probe_max_external_group_changes"] = max(probe_metrics["probe_max_external_group_changes"], comparison["external_group_change_count"])
        probe_metrics["probe_max_disabled_delta_other"] = max(probe_metrics["probe_max_disabled_delta_other"], comparison["disabled_delta_other"])
        probe_metrics["probe_max_text_changes_other"] = max(probe_metrics["probe_max_text_changes_other"], comparison["text_changes_other"])
        probe_metrics["probe_max_selected_changes_other"] = max(probe_metrics["probe_max_selected_changes_other"], comparison["selected_changes_other"])
        probe_metrics["probe_max_total_delta_other"] = max(probe_metrics["probe_max_total_delta_other"], comparison["total_delta_other"])

        sample = {
            "step": step_idx + 1,
            "layer": current_layer,
            "label": candidate.get("label", ""),
            "action": candidate.get("action", ""),
            "group_key": candidate.get("group_key", ""),
            "selection_reason": selection_meta.get("reason", ""),
            "dependency_like_change": comparison["dependency_like_change"],
            "external_group_change_count": comparison["external_group_change_count"],
            "disabled_delta_other": comparison["disabled_delta_other"],
            "text_changes_other": comparison["text_changes_other"],
            "selected_changes_other": comparison["selected_changes_other"],
            "total_delta_other": comparison["total_delta_other"],
            "transition": transition,
        }
        probe_metrics["probe_samples"].append(sample)
        previous_steps.append({
            "step": step_idx + 1,
            "layer": current_layer,
            "candidate": build_probe_candidate_summary(candidate, selected_index),
            "status": "success",
            "comparison": sample,
        })

        if transition.get("layer_advanced") and current_layer < COMPATIBILITY_MULTILAYER_MAX_LAYERS:
            current_layer += 1
            probe_metrics["probe_layers_visited"] = max(probe_metrics["probe_layers_visited"], current_layer)
            used_group_keys = set()

    if probe_metrics["probe_dependency_events"] >= 3 or probe_metrics["probe_max_external_group_changes"] >= 3:
        probe_metrics["probe_reasons"].append("AI-guided probes revealed strong cross-category dependencies")
    elif probe_metrics["probe_dependency_events"] >= 1:
        probe_metrics["probe_reasons"].append("AI-guided probes revealed at least one dependency between different option groups")
    elif probe_metrics["probe_layer_advances"] >= 1 and probe_metrics["probe_actions_successful"] >= 1:
        probe_metrics["probe_reasons"].append("AI-guided probes followed a multi-layer configuration path but revealed little evidence of cross-category restrictions")
    elif probe_metrics["probe_any_change_events"] >= 1:
        probe_metrics["probe_reasons"].append("AI-guided probes changed local state but revealed little evidence of cross-category dependency")
    elif not probe_metrics["probe_reasons"]:
        probe_metrics["probe_reasons"].append("AI-guided probes did not reveal visible dependency effects")

    return probe_metrics


def evaluate_compatibility_constraints_score_with_ollama(page):
    deterministic_score, deterministic_summary, base_metrics = evaluate_compatibility_constraints_score_deterministic(page)
    ai_probe_metrics = run_ai_guided_compatibility_dependency_probes(page, base_metrics)

    metrics = dict(base_metrics)
    metrics.update(ai_probe_metrics)
    metrics["legacy_deterministic_score"] = deterministic_score
    metrics["legacy_deterministic_summary"] = deterministic_summary

    try:
        title = page.title()
    except Exception:
        title = ""
    try:
        final_url = page.url
    except Exception:
        final_url = ""
    try:
        visible_text = page.locator("body").inner_text()
    except Exception:
        visible_text = ""

    visible_text_excerpt = compress_visible_text(visible_text, max_chars=4500)
    dom_signals = get_page_dom_signals(page)

    prompt = f"""
You are evaluating compatibility constraints in a product configurator.

Definition:
- We want to measure how much choosing one characteristic restricts, disables, filters, or changes OTHER characteristics later in the configuration.
- Same-group exclusivity does NOT count as a compatibility constraint. Example: after choosing one color, the other colors of that same color group becoming unselectable is normal and should not be counted.
- The strongest evidence is when a choice in one category changes availability or options in other categories later in the flow.
- Sequential order alone is weak evidence unless it truly narrows later categories.

Score from 1 to 5:
1 = choices are almost completely independent
2 = light constraints
3 = moderate constraints
4 = strong dependency logic
5 = highly constrained configurator, early choices strongly determine later ones

Use the AI-guided probe results as the MAIN evidence. The deterministic metrics are secondary support.
Be conservative. Return ONLY one valid JSON object on a single line.

Exact format:
{{"compatibility_score":3,"confidence":80,"reason":"brief explanation"}}

PAGE TITLE:
{title}

FINAL URL:
{final_url}

LEGACY DETERMINISTIC METRICS:
{json.dumps(base_metrics, ensure_ascii=False)}

AI-GUIDED PROBE RESULTS:
{json.dumps(ai_probe_metrics, ensure_ascii=False)}

DOM SIGNALS:
{json.dumps(dom_signals, ensure_ascii=False)}

VISIBLE TEXT EXCERPT:
{visible_text_excerpt}
""".strip()

    raw_output = ""
    parser_warning = ""
    try:
        raw_output = call_ollama(prompt)
        ollama_score, ollama_confidence, ollama_reason, parser_warning = parse_ollama_compatibility_assessment(raw_output)
    except Exception as exc:
        metrics["ollama_error"] = str(exc)
        metrics["final_compatibility_score"] = deterministic_score
        metrics["final_compatibility_summary"] = compatibility_score_to_summary(deterministic_score)
        return deterministic_score, compatibility_score_to_summary(deterministic_score), metrics, raw_output, str(exc), "compatibility_ai_guided_fallback_to_deterministic"

    metrics["ollama_score"] = ollama_score
    metrics["ollama_confidence"] = ollama_confidence
    metrics["ollama_reason"] = ollama_reason

    if ollama_confidence >= COMPATIBILITY_OLLAMA_MIN_CONFIDENCE:
        final_score = ollama_score
        decision_source = "compatibility_ai_guided_ollama_primary"
    else:
        final_score = deterministic_score
        decision_source = "compatibility_ai_guided_ollama_low_confidence_fallback_deterministic"

    metrics["final_compatibility_score"] = final_score
    metrics["final_compatibility_summary"] = compatibility_score_to_summary(final_score)
    return final_score, compatibility_score_to_summary(final_score), metrics, raw_output, parser_warning, decision_source


def classify_compatibility_constraints_on_existing_page(page):
    if not ENABLE_COMPATIBILITY_CONSTRAINT_SCORE:
        return {
            "compatibility_score": "",
            "note": "Presenza di regole/vincoli di compatibilità?: non calcolata (feature disattivata)",
            "raw_output": "",
            "parser_warning": "",
            "decision_source": "disabled",
        }

    score, summary, metrics, raw_output, parser_warning, decision_source = evaluate_compatibility_constraints_score_with_ollama(page)

    legacy_score = metrics.get("legacy_deterministic_score", "")
    ollama_score = metrics.get("ollama_score", "")
    ollama_reason = normalize_space(metrics.get("ollama_reason", ""))
    dependency_events = metrics.get("probe_dependency_events", 0)
    successful_actions = metrics.get("probe_actions_successful", 0)

    note = f"Presenza di regole/vincoli di compatibilità?: {score}/5 ({summary})"
    note += f" | AI-guided probes: {dependency_events} dependency events over {successful_actions} successful interactions"
    note += f" | layers visited={metrics.get('probe_layers_visited', 1)} | transitions={metrics.get('probe_layer_advances', 0)}"
    if legacy_score != "":
        note += f" | deterministic_baseline={legacy_score}/5"
    if ollama_score != "":
        note += f" | ollama={ollama_score}/5"
    if ollama_reason:
        note += f" | {ollama_reason}"

    payload = {
        "metrics": metrics,
        "ollama_raw_output": raw_output,
        "probe_selection_raw_outputs": metrics.get("probe_selection_raw_outputs", []),
    }

    return {
        "compatibility_score": score,
        "note": note,
        "raw_output": json.dumps(payload, ensure_ascii=False),
        "parser_warning": parser_warning,
        "decision_source": decision_source,
    }



def parse_ollama_complexity_assessment(raw_output):
    parsed = try_parse_json_candidates(raw_output)

    if parsed is not None:
        score = parsed.get("complexity_score", parsed.get("score", ""))
        confidence = normalize_confidence(parsed.get("confidence", ""))
        reason = str(parsed.get("reason", parsed.get("motivo", ""))).strip()
        try:
            score = int(str(score).strip())
        except Exception:
            score = ""
        if score in {1, 2, 3, 4, 5}:
            return score, confidence, reason or "Reason not provided", ""

    text = strip_code_fences(raw_output)
    m = re.search(r'"?(complexity_score|score)"?\s*:\s*([1-5])', text, flags=re.IGNORECASE)
    if m:
        score = int(m.group(2))
        confidence = normalize_confidence(regex_extract_field(raw_output, "confidence"))
        reason = regex_extract_field(raw_output, "reason") or regex_extract_field(raw_output, "motivo") or "Reason recovered partially"
        return score, confidence, reason, "Permissive parser used for complexity score"

    raise ValueError(f"Unable to parse Ollama complexity assessment: {raw_output}")


def complexity_score_to_summary(score):
    if score == 5:
        return "very high complexity"
    if score == 4:
        return "high complexity"
    if score == 3:
        return "moderate complexity"
    if score == 2:
        return "limited complexity"
    return "very low complexity"


def collect_complexity_structural_metrics(page):
    state = collect_compatibility_state_snapshot(page)
    group_states = state.get("group_states", {}) or {}
    groups = list(group_states.values())
    substantial_groups = [g for g in groups if int(g.get("total") or 0) >= 2]
    multi_option_groups = [g for g in groups if int(g.get("total") or 0) >= 3]
    max_options_per_group = max([int(g.get("total") or 0) for g in groups], default=0)
    selected_groups = sum(1 for g in groups if int(g.get("selected_count") or 0) >= 1)

    try:
        extra = page.evaluate(
            """
            () => {
                function norm(t) { return (t || '').replace(/\\s+/g, ' ').trim(); }
                function isVisible(el) {
                    if (!el || !(el instanceof Element)) return false;
                    const style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }
                const visibleTexts = [...document.querySelectorAll('h1,h2,h3,h4,legend,label,.step,.steps,[class*=step],[class*=wizard],[class*=progress],button,a')].filter(isVisible).map(el => norm(el.innerText || el.textContent || '')).filter(Boolean);
                const stepLikeMarkers = visibleTexts.filter(t => /(step|phase|stage|configure|configuration|customi[sz]e|personaliz|personnalis|konfig|builder|wizard|choose|select|modell|modello|modelo|material|size|dimension|engrave|text|finish|component)/i.test(t)).length;
                const numberedStepMarkers = visibleTexts.filter(t => /(^|\\s)(step\\s*\\d+|\\d+\\s*[.)-])/i.test(t)).length;
                const textInputs = [...document.querySelectorAll('input[type="text"], input:not([type]), textarea')].filter(isVisible).length;
                const fileUploads = [...document.querySelectorAll('input[type="file"]')].filter(isVisible).length;
                const rangeSliders = [...document.querySelectorAll('input[type="range"], [role="slider"]')].filter(isVisible).length;
                const selects = [...document.querySelectorAll('select')].filter(isVisible).length;
                const radios = [...document.querySelectorAll('input[type="radio"], input[type="checkbox"], [role="radio"], [role="checkbox"]')].filter(isVisible).length;
                const dialogs = [...document.querySelectorAll('dialog, [role="dialog"], .modal, .popup, .drawer')].filter(isVisible).length;
                const tabs = [...document.querySelectorAll('[role="tab"], .tab, .tabs button, .accordion button, details summary')].filter(isVisible).length;
                return {
                    step_like_markers: stepLikeMarkers,
                    numbered_step_markers: numberedStepMarkers,
                    text_input_like_count: textInputs,
                    file_upload_count: fileUploads,
                    range_slider_count: rangeSliders,
                    visible_select_count: selects,
                    visible_radio_checkbox_count: radios,
                    visible_dialog_count: dialogs,
                    visible_tab_like_count: tabs,
                };
            }
            """
        )
    except Exception:
        extra = {
            "step_like_markers": 0,
            "numbered_step_markers": 0,
            "text_input_like_count": 0,
            "file_upload_count": 0,
            "range_slider_count": 0,
            "visible_select_count": 0,
            "visible_radio_checkbox_count": 0,
            "visible_dialog_count": 0,
            "visible_tab_like_count": 0,
        }

    metrics = {
        "group_count": len(groups),
        "substantial_group_count": len(substantial_groups),
        "multi_option_group_count": len(multi_option_groups),
        "max_options_per_group": max_options_per_group,
        "selected_group_count": selected_groups,
        "total_option_like": int(state.get("option_like_total") or 0),
        "disabled_total": int(state.get("disabled_total") or 0),
    }
    metrics.update(extra)
    return metrics


def evaluate_complexity_score_deterministic(page, compatibility_metrics=None):
    metrics = collect_complexity_structural_metrics(page)
    compatibility_metrics = compatibility_metrics or {}

    probe_layers_visited = int(compatibility_metrics.get("probe_layers_visited") or 1)
    probe_layer_advances = int(compatibility_metrics.get("probe_layer_advances") or 0)
    probe_actions_successful = int(compatibility_metrics.get("probe_actions_successful") or 0)
    probe_candidates_found = int(compatibility_metrics.get("probe_candidates_found") or 0)
    probe_trace = compatibility_metrics.get("probe_selection_trace") or []
    unique_probe_groups = len({normalize_space((item or {}).get("group_key", "")) for item in probe_trace if normalize_space((item or {}).get("group_key", ""))})

    substantial_groups = int(metrics.get("substantial_group_count") or 0)
    total_option_like = int(metrics.get("total_option_like") or 0)
    max_options_per_group = int(metrics.get("max_options_per_group") or 0)
    step_like_markers = int(metrics.get("step_like_markers") or 0)
    numbered_step_markers = int(metrics.get("numbered_step_markers") or 0)
    text_input_like = int(metrics.get("text_input_like_count") or 0)
    file_upload_count = int(metrics.get("file_upload_count") or 0)
    range_slider_count = int(metrics.get("range_slider_count") or 0)
    visible_dialog_count = int(metrics.get("visible_dialog_count") or 0)
    visible_tab_like_count = int(metrics.get("visible_tab_like_count") or 0)

    reasons = []
    score = 1

    if substantial_groups >= 2 or total_option_like >= 6 or probe_candidates_found >= 2:
        score = 2
        reasons.append("more than minimal personalization options detected")

    if substantial_groups >= 4 or total_option_like >= 14 or (step_like_markers + numbered_step_markers) >= 2 or unique_probe_groups >= 3:
        score = max(score, 3)
        reasons.append("multiple personalization categories or intermediate multi-step structure")

    if substantial_groups >= 6 or total_option_like >= 28 or probe_layers_visited >= 2 or unique_probe_groups >= 4 or visible_dialog_count >= 1:
        score = max(score, 4)
        reasons.append("rich configuration structure with several categories or multiple layers")

    if substantial_groups >= 8 or total_option_like >= 45 or probe_layers_visited >= 3 or unique_probe_groups >= 6 or ((text_input_like + file_upload_count + range_slider_count) >= 2 and substantial_groups >= 4):
        score = max(score, 5)
        reasons.append("very articulated configurator with many decisions or advanced customization features")

    if max_options_per_group >= 10 and score < 5:
        score = min(5, score + 1)
        reasons.append("at least one category contains many alternatives")

    if visible_tab_like_count >= 4 and score < 5:
        score = min(5, score + 1)
        reasons.append("interface exposes several sections/tabs/accordions")

    if probe_actions_successful >= 3 and probe_layer_advances >= 1 and score < 5:
        score = min(5, score + 1)
        reasons.append("probing confirms a non-trivial multi-step flow")

    score = max(COMPLEXITY_MIN_SCORE, min(COMPLEXITY_MAX_SCORE, score))

    metrics.update({
        "probe_layers_visited": probe_layers_visited,
        "probe_layer_advances": probe_layer_advances,
        "probe_actions_successful": probe_actions_successful,
        "probe_candidates_found": probe_candidates_found,
        "unique_probe_groups": unique_probe_groups,
        "deterministic_score": score,
        "deterministic_summary": complexity_score_to_summary(score),
        "summary_reasons": reasons,
    })
    return score, complexity_score_to_summary(score), metrics


def should_use_ollama_for_complexity(metrics, deterministic_score):
    if not ENABLE_COMPLEXITY_OLLAMA_REVIEW:
        return False
    if deterministic_score in {2, 3, 4}:
        return True
    if int(metrics.get("probe_layers_visited") or 1) >= 2:
        return True
    if int(metrics.get("substantial_group_count") or 0) >= 4:
        return True
    return False


def evaluate_complexity_score_with_ollama(page, compatibility_metrics=None):
    deterministic_score, deterministic_summary, metrics = evaluate_complexity_score_deterministic(page, compatibility_metrics=compatibility_metrics)

    metrics["ollama_score"] = ""
    metrics["ollama_confidence"] = ""
    metrics["ollama_reason"] = ""

    if not should_use_ollama_for_complexity(metrics, deterministic_score):
        return deterministic_score, deterministic_summary, metrics, "", "", "deterministic_complexity"

    try:
        title = page.title()
    except Exception:
        title = ""
    try:
        final_url = page.url
    except Exception:
        final_url = ""
    try:
        visible_text = page.locator("body").inner_text()
    except Exception:
        visible_text = ""

    visible_text_excerpt = compress_visible_text(visible_text, max_chars=5000)
    dom_signals = get_page_dom_signals(page)

    prompt = f"""
You are evaluating the overall COMPLEXITY of a product configurator.

Definition:
- Complexity means how articulated the configurator is in terms of number of decisions required, number of customizable categories, and depth of the configuration flow.
- Consider both the richness of personalization and the procedural depth of the path.
- Do NOT confuse complexity with compatibility constraints: a configurator can be complex but not strongly constrained.
- Same-group exclusivity is normal and does not automatically imply complexity.

Score from 1 to 5:
1 = very low complexity, minimal personalization
2 = limited complexity
3 = moderate complexity
4 = high complexity
5 = very high complexity, many categories and/or multi-layer articulated flow

Use the structured metrics as the main evidence. Use visible text and DOM signals as supporting context.
Be conservative. Return ONLY one valid JSON object on a single line.

Exact format:
{{"complexity_score":4,"confidence":82,"reason":"brief explanation"}}

PAGE TITLE:
{title}

FINAL URL:
{final_url}

STRUCTURAL COMPLEXITY METRICS:
{json.dumps(metrics, ensure_ascii=False)}

DOM SIGNALS:
{json.dumps(dom_signals, ensure_ascii=False)}

VISIBLE TEXT EXCERPT:
{visible_text_excerpt}
""".strip()

    raw_output = ""
    parser_warning = ""
    try:
        raw_output = call_ollama(prompt)
        ollama_score, ollama_confidence, ollama_reason, parser_warning = parse_ollama_complexity_assessment(raw_output)
    except Exception as exc:
        metrics["ollama_error"] = str(exc)
        metrics["final_complexity_score"] = deterministic_score
        metrics["final_complexity_summary"] = deterministic_summary
        return deterministic_score, deterministic_summary, metrics, raw_output, str(exc), "complexity_fallback_after_ollama_failure"

    metrics["ollama_score"] = ollama_score
    metrics["ollama_confidence"] = ollama_confidence
    metrics["ollama_reason"] = ollama_reason

    if ollama_confidence >= COMPLEXITY_OLLAMA_MIN_CONFIDENCE:
        final_score = ollama_score
        decision_source = "complexity_ollama_primary"
    else:
        final_score = deterministic_score
        decision_source = "complexity_ollama_low_confidence_fallback_deterministic"

    metrics["final_complexity_score"] = final_score
    metrics["final_complexity_summary"] = complexity_score_to_summary(final_score)
    return final_score, complexity_score_to_summary(final_score), metrics, raw_output, parser_warning, decision_source


def classify_complexity_on_existing_page(page, compatibility_metrics=None):
    if not ENABLE_COMPLEXITY_SCORE:
        return {
            "complexity_score": "",
            "note": "Livello di Complessità: non calcolato (feature disattivata)",
            "raw_output": "",
            "parser_warning": "",
            "decision_source": "disabled",
        }

    score, summary, metrics, raw_output, parser_warning, decision_source = evaluate_complexity_score_with_ollama(page, compatibility_metrics=compatibility_metrics)

    note = f"Livello di Complessità: {score}/5 ({summary})"
    note += f" | categories={metrics.get('substantial_group_count', 0)} | option-like={metrics.get('total_option_like', 0)} | layers={metrics.get('probe_layers_visited', 1)}"
    if metrics.get("deterministic_score", "") != "":
        note += f" | deterministic_baseline={metrics.get('deterministic_score')}/5"
    if metrics.get("ollama_score", "") != "":
        note += f" | ollama={metrics.get('ollama_score')}/5"
    if normalize_space(metrics.get("ollama_reason", "")):
        note += f" | {normalize_space(metrics.get('ollama_reason', ''))}"

    payload = {
        "metrics": metrics,
        "ollama_raw_output": raw_output,
    }

    return {
        "complexity_score": score,
        "note": note,
        "raw_output": json.dumps(payload, ensure_ascii=False),
        "parser_warning": parser_warning,
        "decision_source": decision_source,
    }


# =========================
# MAIN
# =========================
def main():
    all_detail_urls = load_input_urls(INPUT_FILE)

    if MAX_ROWS is not None:
        all_detail_urls = all_detail_urls[:MAX_ROWS]

    total_urls = len(all_detail_urls)

    existing_df = load_existing_output(OUTPUT_FILE)
    processed_urls = get_processed_urls(existing_df)
    remaining_urls = [url for url in all_detail_urls if url not in processed_urls]

    print(f"Totale link da input: {total_urls}")
    print(f"Già processati in output esistente: {len(processed_urls.intersection(set(all_detail_urls)))}")
    print(f"Link rimanenti da processare: {len(remaining_urls)}")
    print(f"Modello Ollama usato: {OLLAMA_MODEL}")
    print(f"Browser headless: {HEADLESS}")
    print(f"Pausa tra righe: {SLEEP_BETWEEN_ROWS} secondi")
    print("Step corrente: Tipo di visualizzazione + Ottimizzato per Mobile? + vincoli di compatibilità + livello di complessità + ricerca URL alternativa se il link originale non è attivo")
    print("Fix corrente: euristiche positive per riconoscere sia configuratori multi-step sia landing page custom con scelta iniziale del prodotto")

    if len(remaining_urls) == 0:
        print("Non ci sono link da processare. Hai già finito.")
        return

    results_df = existing_df.copy() if not existing_df.empty else pd.DataFrame()

    test_start = time.perf_counter()
    row_times = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(ignore_https_errors=True)
        mobile_context = build_mobile_emulation_context(browser, p)

        for index, detail_url in enumerate(remaining_urls, start=1):
            row_start = time.perf_counter()
            absolute_done = len(results_df) + 1

            print("\n" + "=" * 80)
            print(f"Configuratore corrente: {absolute_done}/{total_urls}")
            print(f"Batch corrente: {index}/{len(remaining_urls)}")
            print(detail_url)

            row = process_one_detail_url(context, mobile_context, detail_url)

            row_elapsed = time.perf_counter() - row_start
            row["Row processing seconds"] = round(row_elapsed, 2)
            row_times.append(row_elapsed)

            results_df = pd.concat([results_df, pd.DataFrame([row])], ignore_index=True)

            if index % SAVE_EVERY == 0:
                safe_to_excel(results_df, OUTPUT_FILE)

            elapsed_total = time.perf_counter() - test_start
            avg_time_current_run = sum(row_times) / len(row_times)
            already_done_total = len(results_df)
            estimated_total_seconds = avg_time_current_run * total_urls
            estimated_remaining_seconds = max((total_urls - already_done_total) * avg_time_current_run, 0)

            print("Risultato:")
            print(f"Company: {row['Company']}")
            print(f"Product: {row['Product']}")
            print(f"Attivo SI/NO: {row['Attivo SI/NO']}")
            print(f"Configurator URL alternativa: {row['Configurator URL alternativa']}")
            print(f"Tipo di visualizzazione: {row['Tipo di visualizzazione']}")
            print(f"Ottimizzato per Mobile?: {row['Ottimizzato per Mobile?']}")
            print(f"Presenza di regole/vincoli di compatibilità?: {row['Presenza di regole/vincoli di compatibilità?']}")
            print(f"Livello di Complessità: {row['Livello di Complessità']}")
            print(f"AI confidence: {row['AI confidence']}")
            print(f"Decision source: {row['Decision source']}")
            print(f"Note: {row['Note']}")
            print(f"Tempo riga: {row_elapsed:.2f} secondi")
            print(f"Tempo medio sessione corrente: {avg_time_current_run:.2f} secondi")
            print(f"Tempo totale trascorso: {format_seconds(elapsed_total)}")
            print(f"Stimato totale completo: {format_seconds(estimated_total_seconds)}")
            print(f"Stimato rimanente: {format_seconds(estimated_remaining_seconds)}")
            print(f"Progresso salvato in: {OUTPUT_FILE}")

            if SLEEP_BETWEEN_ROWS > 0:
                time.sleep(SLEEP_BETWEEN_ROWS)

        mobile_context.close()
        context.close()
        browser.close()

    safe_to_excel(results_df, OUTPUT_FILE)

    total_elapsed = time.perf_counter() - test_start
    avg_time = sum(row_times) / len(row_times) if row_times else 0
    estimated_total_full = avg_time * total_urls if avg_time else 0

    print("\n" + "=" * 80)
    print("ELABORAZIONE COMPLETATA")
    print(f"File finale creato/aggiornato: {OUTPUT_FILE}")
    print(f"Tempo totale sessione: {format_seconds(total_elapsed)}")
    print(f"Tempo medio per configuratore in questa sessione: {avg_time:.2f} secondi")
    print(f"Stima totale completa: {format_seconds(estimated_total_full)}")
    print("=" * 80)


if __name__ == "__main__":
    main()
