import argparse
import hashlib
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
from playwright.sync_api import Browser, BrowserContext, Frame, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from tqdm import tqdm


CERTIFICATION_NAME = "Forest Stewardship Council"
CERTIFICATION_SHORT_NAME = "FSC"
REGISTRY_SECTION = "FSC Certificates Public Dashboard"

START_URL = (
    "https://app.powerbi.com/view?"
    "r=eyJrIjoiN2U3NGMyNWEtZTAxNS00MzVhLWExNmMtOThhZjdiYjQ4MWNkIiwidCI6IjEyNGU2OWRiLWVmNjUtNDk2Yi05NmE5LTVkNTZiZWMxZDI5MSIsImMiOjl9"
)

OUTPUT_DIR = Path("data") / "certifications" / "fsc"
DEBUG_DIR = OUTPUT_DIR / "debug"

DEFAULT_MAX_SCROLLS = 2500
DEFAULT_STABLE_ROUNDS = 35
DEFAULT_SCROLL_PIXELS = 850

EXCEL_ILLEGAL_CHARACTERS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")

STATUS_PATTERN = (
    r"Valid|Suspended and blocked|Suspended|Terminated and blocked|Terminated"
)

ROLE_PATTERN = (
    r"Certificate holder|Participating site|Group member|Outsourcing contractor|Site"
)

COUNTRY_NAMES = [
    "United Kingdom of Great Britain and Northern Ireland",
    "United States of America",
    "Russian Federation",
    "Korea, Republic of",
    "Korea, Democratic People's Republic of",
    "Iran, Islamic Republic of",
    "Tanzania, United Republic of",
    "Moldova, Republic of",
    "Venezuela, Bolivarian Republic of",
    "Bolivia, Plurinational State of",
    "Lao People's Democratic Republic",
    "Syrian Arab Republic",
    "Viet Nam",
    "Czech Republic",
    "Dominican Republic",
    "Central African Republic",
    "Bosnia and Herzegovina",
    "North Macedonia",
    "South Africa",
    "New Zealand",
    "Saudi Arabia",
    "United Arab Emirates",
    "Costa Rica",
    "Sri Lanka",
    "El Salvador",
    "Puerto Rico",
    "Hong Kong",
    "Taiwan",
    "Palestine",
    "Côte d'Ivoire",
    "Ivory Coast",
    "Afghanistan",
    "Albania",
    "Algeria",
    "Andorra",
    "Angola",
    "Argentina",
    "Armenia",
    "Australia",
    "Austria",
    "Azerbaijan",
    "Bangladesh",
    "Belarus",
    "Belgium",
    "Brazil",
    "Bulgaria",
    "Cambodia",
    "Cameroon",
    "Canada",
    "Chile",
    "China",
    "Colombia",
    "Croatia",
    "Cyprus",
    "Denmark",
    "Ecuador",
    "Egypt",
    "Estonia",
    "Ethiopia",
    "Finland",
    "France",
    "Georgia",
    "Germany",
    "Ghana",
    "Greece",
    "Guatemala",
    "Honduras",
    "Hungary",
    "India",
    "Indonesia",
    "Ireland",
    "Israel",
    "Italy",
    "Japan",
    "Kenya",
    "Latvia",
    "Lebanon",
    "Lithuania",
    "Luxembourg",
    "Malaysia",
    "Mexico",
    "Morocco",
    "Myanmar",
    "Nepal",
    "Netherlands",
    "Nigeria",
    "Norway",
    "Pakistan",
    "Panama",
    "Paraguay",
    "Peru",
    "Philippines",
    "Poland",
    "Portugal",
    "Romania",
    "Serbia",
    "Singapore",
    "Slovakia",
    "Slovenia",
    "Solomon Islands",
    "Spain",
    "Sweden",
    "Switzerland",
    "Thailand",
    "Tunisia",
    "Türkiye",
    "Turkey",
    "Ukraine",
    "Uruguay",
    "Uzbekistan",
    "Zimbabwe",
]

COUNTRY_NAMES_SORTED = sorted(COUNTRY_NAMES, key=len, reverse=True)


def strip_excel_illegal_characters(value: object) -> str:
    if value is None:
        return ""

    text = str(value)
    text = EXCEL_ILLEGAL_CHARACTERS_RE.sub("", text)
    return text


def clean_text(value: object) -> str:
    if value is None:
        return ""

    text = strip_excel_illegal_characters(value)
    text = text.replace("\u00a0", " ")
    text = text.replace("\ufeff", "")
    text = text.replace("\u25ba", " ")
    text = text.replace("☻", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def sanitize_dataframe_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    sanitized_df = df.copy()

    for column in sanitized_df.columns:
        if sanitized_df[column].dtype == "object":
            sanitized_df[column] = sanitized_df[column].apply(clean_text)

    return sanitized_df


def normalize_for_matching(value: object) -> str:
    text = clean_text(value).casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        character for character in text if not unicodedata.combining(character)
    )
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def make_hash_key(*values: object) -> str:
    raw_key = "|".join(clean_text(value) for value in values)
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def save_debug_page(page: Page, frame: Optional[Frame], reason: str) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_reason = re.sub(r"[^a-zA-Z0-9_-]+", "_", reason)

    screenshot_path = DEBUG_DIR / f"{safe_reason}_{timestamp}.png"
    page_text_path = DEBUG_DIR / f"{safe_reason}_{timestamp}_page.txt"
    frame_text_path = DEBUG_DIR / f"{safe_reason}_{timestamp}_frame.txt"
    frame_html_path = DEBUG_DIR / f"{safe_reason}_{timestamp}_frame.html"

    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception:
        pass

    try:
        body_text = page.locator("body").inner_text(timeout=5000)
        page_text_path.write_text(clean_text(body_text), encoding="utf-8", errors="ignore")
    except Exception:
        pass

    if frame is not None:
        try:
            frame_text = frame.locator("body").inner_text(timeout=5000)
            frame_text_path.write_text(clean_text(frame_text), encoding="utf-8", errors="ignore")
        except Exception:
            pass

        try:
            html = frame.content()
            frame_html_path.write_text(html, encoding="utf-8", errors="ignore")
        except Exception:
            pass


def select_powerbi_frame(page: Page, timeout_ms: int) -> Frame:
    deadline = time.time() + timeout_ms / 1000
    best_frame = page.main_frame

    while time.time() < deadline:
        for frame in page.frames:
            try:
                body_text = frame.locator("body").inner_text(timeout=1500)
                normalized = clean_text(body_text)

                if (
                    "FSC CERTIFICATES PUBLIC DASHBOARD" in normalized
                    or (
                        "Licence" in normalized
                        and "Certificate Code" in normalized
                        and "Organization Name" in normalized
                    )
                    or (
                        "FSC-C" in normalized
                        and "Certificate holder" in normalized
                    )
                ):
                    return frame

                if len(normalized) > 500:
                    best_frame = frame

            except Exception:
                continue

        time.sleep(1)

    return best_frame


def wait_for_fsc_table(page: Page, frame: Frame, timeout_ms: int) -> None:
    try:
        frame.wait_for_function(
            """
            () => {
              const text = document.body.innerText || "";
              const hasDashboardTitle = /FSC\\s+CERTIFICATES\\s+PUBLIC\\s+DASHBOARD/i.test(text);
              const hasHeaders =
                /Licence/i.test(text) &&
                /Certificate\\s+Code/i.test(text) &&
                /Organization\\s+Name/i.test(text);

              const hasFscRows = /FSC-[A-Z0-9]+/i.test(text);

              return (hasDashboardTitle || hasHeaders) && hasFscRows;
            }
            """,
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        save_debug_page(page, frame, "wait_for_fsc_table_timeout")
        raise


def extract_report_timestamp(frame: Frame) -> str:
    try:
        return clean_text(
            frame.evaluate(
                """
                () => {
                  const text = document.body.innerText || "";
                  const match = text.match(/20\\d{2}-\\d{2}-\\d{2}\\s+\\d{2}:\\d{2}:\\d{2}/);
                  return match ? match[0] : "";
                }
                """
            )
        )
    except Exception:
        return ""


def split_geo_into_state_and_country(geo_text: str) -> Tuple[str, str]:
    geo_text = clean_text(geo_text)

    if not geo_text:
        return "", ""

    for country in COUNTRY_NAMES_SORTED:
        if geo_text.casefold() == country.casefold():
            return "", country

        suffix_pattern = re.compile(
            rf"^(?P<state>.+?)\s+(?P<country>{re.escape(country)})$",
            flags=re.IGNORECASE,
        )
        match = suffix_pattern.match(geo_text)

        if match:
            return clean_text(match.group("state")), clean_text(match.group("country"))

    return "", geo_text


def remove_common_powerbi_noise(text: str) -> str:
    text = clean_text(text)

    text = re.sub(r"^\d+\s*of\s*\d+\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\d+of\d+\s+\d+\s+of\s+\d+\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^Select all(?:\s+FSC\s+100%)?\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^Select Row\s+", "", text, flags=re.IGNORECASE)

    return clean_text(text)


def split_candidate_text_into_segments(candidate_text: str) -> List[str]:
    text = clean_text(candidate_text)

    if "FSC-" not in text:
        return []

    start_matches = list(
        re.finditer(
            r"(?:Select Row\s+)?FSC-[A-Z0-9]+",
            text,
            flags=re.IGNORECASE,
        )
    )

    if not start_matches:
        return []

    segments = []

    for index, match in enumerate(start_matches):
        start = match.start()
        end = start_matches[index + 1].start() if index + 1 < len(start_matches) else len(text)
        segment = clean_text(text[start:end])

        if segment:
            segments.append(segment)

    return segments


def parse_fsc_row_segment(segment: str, scroll_number: int) -> Optional[Dict[str, object]]:
    segment = remove_common_powerbi_noise(segment)

    main_pattern = re.compile(
        rf"^(?P<licence>FSC-[A-Z0-9]+)\s+"
        rf"(?P<certificate_code>[A-Z0-9]+(?:-[A-Z0-9/]+)+)\s+"
        rf"(?P<cert_status>{STATUS_PATTERN})\s+"
        rf"(?P<cw_dds>Yes|No)\s+"
        rf"(?P<date_from>\d{{4}}-\d{{2}}-\d{{2}})\s+"
        rf"(?P<valid_to>\d{{4}}-\d{{2}}-\d{{2}})\s+"
        rf"(?P<tail>.+)$",
        flags=re.IGNORECASE,
    )

    main_match = main_pattern.match(segment)

    if not main_match:
        return None

    licence = clean_text(main_match.group("licence"))
    certificate_code = clean_text(main_match.group("certificate_code"))
    cert_status = clean_text(main_match.group("cert_status"))
    cw_dds = clean_text(main_match.group("cw_dds"))
    date_from = clean_text(main_match.group("date_from"))
    valid_to = clean_text(main_match.group("valid_to"))
    tail = clean_text(main_match.group("tail"))

    tail_without_duplicate = re.sub(
        r"\s+Select Row\s+.*$",
        "",
        tail,
        flags=re.IGNORECASE,
    )
    tail_without_duplicate = clean_text(tail_without_duplicate)

    detail_pattern = re.compile(
        rf"^(?P<organization_name>.+?)\s+"
        rf"(?P<role>{ROLE_PATTERN})\s+"
        rf"(?P<site_status>{STATUS_PATTERN})"
        rf"(?:\s+(?P<geo>.*))?$",
        flags=re.IGNORECASE,
    )

    detail_match = detail_pattern.match(tail_without_duplicate)

    if not detail_match:
        return None

    organization_name = clean_text(detail_match.group("organization_name"))
    role = clean_text(detail_match.group("role"))
    site_status = clean_text(detail_match.group("site_status"))
    geo_text = clean_text(detail_match.group("geo") or "")

    state_province, country_area = split_geo_into_state_and_country(geo_text)

    if not organization_name:
        return None

    row = {
        "certification": CERTIFICATION_SHORT_NAME,
        "certification_full_name": CERTIFICATION_NAME,
        "registry_section": REGISTRY_SECTION,
        "registry_source": "FSC Certificates Public Dashboard Power BI",
        "registry_match_level": "organization_certificate",
        "scroll_number": scroll_number,
        "licence": licence,
        "licence_normalized": normalize_for_matching(licence),
        "certificate_code": certificate_code,
        "certificate_code_normalized": normalize_for_matching(certificate_code),
        "cert_status": cert_status,
        "cw_dds": cw_dds,
        "date_from": date_from,
        "valid_to": valid_to,
        "organization_name": organization_name,
        "organization_name_normalized": normalize_for_matching(organization_name),
        "role": role,
        "site_status": site_status,
        "state_province": state_province,
        "state_province_normalized": normalize_for_matching(state_province),
        "country_area": country_area,
        "country_area_normalized": normalize_for_matching(country_area),
        "raw_geo_text": geo_text,
        "source_url": START_URL,
        "evidence_text": segment,
        "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    row["record_key"] = make_hash_key(
        row["licence"],
        row["certificate_code"],
        row["organization_name"],
        row["role"],
        row["site_status"],
        row["state_province"],
        row["country_area"],
    )

    return row


def extract_candidate_texts(frame: Frame) -> List[str]:
    candidate_texts = frame.evaluate(
        """
        () => {
          function cleanText(text) {
            return (text || "")
              .replace(/\\u00a0/g, " ")
              .replace(/\\s+/g, " ")
              .trim();
          }

          function isVisible(element) {
            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();

            return (
              style &&
              style.display !== "none" &&
              style.visibility !== "hidden" &&
              rect.width > 0 &&
              rect.height > 0
            );
          }

          const results = [];
          const seen = new Set();

          function pushCandidate(text) {
            text = cleanText(text);

            if (!text) {
              return;
            }

            if (!/FSC-[A-Z0-9]+/i.test(text)) {
              return;
            }

            if (!/\\d{4}-\\d{2}-\\d{2}/.test(text)) {
              return;
            }

            if (text.length < 35) {
              return;
            }

            if (text.length > 12000) {
              text = text.slice(0, 12000);
            }

            if (seen.has(text)) {
              return;
            }

            seen.add(text);
            results.push(text);
          }

          const bodyText = cleanText(document.body.innerText || "");
          pushCandidate(bodyText);

          const selectors = [
            "div",
            "span",
            "p",
            "text",
            "tspan",
            "[aria-label]",
            "[title]",
            "[role='row']",
            "[role='gridcell']"
          ].join(",");

          const elements = Array.from(document.querySelectorAll(selectors));

          for (const element of elements) {
            if (!isVisible(element)) {
              continue;
            }

            const innerText = cleanText(element.innerText || element.textContent || "");
            const ariaLabel = cleanText(element.getAttribute("aria-label") || "");
            const title = cleanText(element.getAttribute("title") || "");

            pushCandidate(innerText);
            pushCandidate(ariaLabel);
            pushCandidate(title);
          }

          return results;
        }
        """
    )

    return [clean_text(text) for text in candidate_texts if clean_text(text)]


def extract_visible_fsc_rows(frame: Frame, scroll_number: int) -> List[Dict[str, object]]:
    candidate_texts = extract_candidate_texts(frame)
    rows = []

    for candidate_text in candidate_texts:
        segments = split_candidate_text_into_segments(candidate_text)

        for segment in segments:
            row = parse_fsc_row_segment(
                segment=segment,
                scroll_number=scroll_number,
            )

            if row is not None:
                rows.append(row)

    return deduplicate_rows(rows)


def deduplicate_rows(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    seen = set()
    deduped = []

    for row in rows:
        key = clean_text(row.get("record_key", ""))

        if not key:
            key = make_hash_key(
                row.get("licence", ""),
                row.get("certificate_code", ""),
                row.get("organization_name", ""),
                row.get("role", ""),
                row.get("site_status", ""),
                row.get("state_province", ""),
                row.get("country_area", ""),
            )

        if key in seen:
            continue

        seen.add(key)
        deduped.append(row)

    return deduped


def get_visible_signature(frame: Frame) -> str:
    try:
        rows = extract_visible_fsc_rows(frame=frame, scroll_number=-1)

        if not rows:
            return ""

        first = rows[0]
        last = rows[-1]

        return clean_text(
            f"{first.get('record_key', '')}|{last.get('record_key', '')}|{len(rows)}"
        )
    except Exception:
        return ""


def scroll_fsc_table(frame: Frame, scroll_pixels: int) -> Dict[str, object]:
    return frame.evaluate(
        """
        ([scrollPixels]) => {
          function cleanText(text) {
            return (text || "")
              .replace(/\\u00a0/g, " ")
              .replace(/\\s+/g, " ")
              .trim();
          }

          function isVisible(element) {
            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();

            return (
              style &&
              style.display !== "none" &&
              style.visibility !== "hidden" &&
              rect.width > 0 &&
              rect.height > 0
            );
          }

          function scoreScrollable(element) {
            const rect = element.getBoundingClientRect();
            const text = cleanText(element.innerText || element.textContent || "");
            const className = (element.className || "").toString();

            let score = 0;

            if (element.scrollHeight <= element.clientHeight + 10) {
              return -9999;
            }

            if (!isVisible(element)) {
              return -9999;
            }

            if (/FSC-[A-Z0-9]+/i.test(text)) score += 220;
            if (/Licence/i.test(text) && /Organization\\s+Name/i.test(text)) score += 140;
            if (/Certificate\\s+Code/i.test(text)) score += 70;
            if (/scroll|table|grid|visual|body|viewport/i.test(className)) score += 25;
            if (rect.width > 800) score += 30;
            if (rect.height > 200) score += 30;
            if (rect.y > window.innerHeight * 0.25) score += 10;

            if (/Search by Licence Code|Certificate Type|Output Category|Tree Species|Regulatory Module/i.test(text)) {
              score -= 90;
            }

            return score;
          }

          const candidates = Array.from(document.querySelectorAll("*"))
            .map((element) => {
              const rect = element.getBoundingClientRect();

              return {
                element,
                score: scoreScrollable(element),
                previousScrollTop: element.scrollTop,
                scrollHeight: element.scrollHeight,
                clientHeight: element.clientHeight,
                x: rect.x,
                y: rect.y,
                width: rect.width,
                height: rect.height,
                className: (element.className || "").toString(),
                textExcerpt: cleanText(element.innerText || element.textContent || "").slice(0, 250)
              };
            })
            .filter((item) => item.score > 0)
            .sort((a, b) => b.score - a.score);

          if (candidates.length > 0) {
            const chosen = candidates[0];

            chosen.element.scrollTop = Math.min(
              chosen.element.scrollTop + scrollPixels,
              chosen.element.scrollHeight
            );

            chosen.element.dispatchEvent(new Event("scroll", { bubbles: true }));

            chosen.element.dispatchEvent(
              new WheelEvent("wheel", {
                bubbles: true,
                cancelable: true,
                deltaY: scrollPixels,
                deltaMode: 0,
                clientX: chosen.x + chosen.width / 2,
                clientY: chosen.y + chosen.height / 2
              })
            );

            return {
              method: "scrollable_element",
              scrolled: chosen.element.scrollTop !== chosen.previousScrollTop,
              previous_scroll_top: chosen.previousScrollTop,
              new_scroll_top: chosen.element.scrollTop,
              scroll_height: chosen.scrollHeight,
              client_height: chosen.clientHeight,
              score: chosen.score,
              class_name: chosen.className,
              text_excerpt: chosen.textExcerpt
            };
          }

          const textItems = Array.from(document.querySelectorAll("div, span, text, tspan"))
            .map((element) => {
              const rect = element.getBoundingClientRect();
              const text = cleanText(element.innerText || element.textContent || "");

              return {
                element,
                text,
                rect
              };
            })
            .filter((item) => {
              return (
                item.text &&
                /^FSC-[A-Z0-9]+/i.test(item.text) &&
                item.rect.width > 0 &&
                item.rect.height > 0
              );
            });

          if (textItems.length > 0) {
            textItems.sort((a, b) => a.rect.y - b.rect.y);
            const target = textItems[Math.min(textItems.length - 1, Math.floor(textItems.length / 2))];
            const elementAtPoint = document.elementFromPoint(
              target.rect.x + target.rect.width / 2,
              target.rect.y + target.rect.height / 2
            );

            if (elementAtPoint) {
              elementAtPoint.dispatchEvent(
                new WheelEvent("wheel", {
                  bubbles: true,
                  cancelable: true,
                  deltaY: scrollPixels,
                  deltaMode: 0,
                  clientX: target.rect.x + target.rect.width / 2,
                  clientY: target.rect.y + target.rect.height / 2
                })
              );

              return {
                method: "wheel_event",
                scrolled: true,
                previous_scroll_top: null,
                new_scroll_top: null,
                scroll_height: null,
                client_height: null,
                score: null,
                class_name: "",
                text_excerpt: "wheel dispatched on row area"
              };
            }
          }

          const previousY = window.scrollY;
          window.scrollBy(0, scrollPixels);

          return {
            method: "window_scroll",
            scrolled: window.scrollY !== previousY,
            previous_scroll_top: previousY,
            new_scroll_top: window.scrollY,
            scroll_height: document.documentElement.scrollHeight,
            client_height: window.innerHeight,
            score: null,
            class_name: "",
            text_excerpt: ""
          };
        }
        """,
        [scroll_pixels],
    )


def save_checkpoint(
    rows: List[Dict[str, object]],
    scrape_log: List[Dict[str, object]],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    rows_df = sanitize_dataframe_for_excel(pd.DataFrame(deduplicate_rows(rows)))
    scrape_log_df = sanitize_dataframe_for_excel(pd.DataFrame(scrape_log))

    checkpoint_path = output_dir / "fsc_registry_CHECKPOINT.xlsx"

    with pd.ExcelWriter(checkpoint_path, engine="openpyxl") as writer:
        rows_df.to_excel(writer, sheet_name="certificate_rows", index=False)
        scrape_log_df.to_excel(writer, sheet_name="scrape_log", index=False)

    print(f"Checkpoint saved: {checkpoint_path}")


def build_organization_summary(rows_df: pd.DataFrame) -> pd.DataFrame:
    if rows_df.empty:
        return pd.DataFrame()

    summary_df = (
        rows_df.groupby(
            [
                "organization_name",
                "organization_name_normalized",
                "country_area",
                "country_area_normalized",
            ],
            dropna=False,
        )
        .agg(
            fsc_rows=("record_key", "count"),
            unique_licences=("licence_normalized", "nunique"),
            unique_certificate_codes=("certificate_code_normalized", "nunique"),
            licence_codes=(
                "licence",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:80]
                ),
            ),
            certificate_codes=(
                "certificate_code",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:80]
                ),
            ),
            roles=(
                "role",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:30]
                ),
            ),
            site_statuses=(
                "site_status",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:30]
                ),
            ),
            states_provinces=(
                "state_province",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:80]
                ),
            ),
            valid_to_values=(
                "valid_to",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:80]
                ),
            ),
            source_url=("source_url", "first"),
        )
        .reset_index()
    )

    summary_df["certification"] = CERTIFICATION_SHORT_NAME
    summary_df["certification_full_name"] = CERTIFICATION_NAME
    summary_df["registry_section"] = "Organization Summary"
    summary_df["registry_match_level"] = "organization"

    summary_df["evidence_text"] = summary_df.apply(
        lambda row: (
            f"{row['organization_name']} appears in {row['fsc_rows']} FSC row(s), "
            f"with {row['unique_licences']} licence(s) and "
            f"{row['unique_certificate_codes']} certificate code(s)."
        ),
        axis=1,
    )

    summary_df = summary_df[
        [
            "certification",
            "certification_full_name",
            "registry_section",
            "registry_match_level",
            "organization_name",
            "organization_name_normalized",
            "country_area",
            "country_area_normalized",
            "fsc_rows",
            "unique_licences",
            "unique_certificate_codes",
            "licence_codes",
            "certificate_codes",
            "roles",
            "site_statuses",
            "states_provinces",
            "valid_to_values",
            "source_url",
            "evidence_text",
        ]
    ]

    return summary_df.sort_values(
        [
            "organization_name_normalized",
            "country_area_normalized",
        ]
    ).reset_index(drop=True)


def build_country_summary(rows_df: pd.DataFrame) -> pd.DataFrame:
    if rows_df.empty:
        return pd.DataFrame()

    country_df = (
        rows_df.groupby(
            [
                "country_area",
                "country_area_normalized",
            ],
            dropna=False,
        )
        .agg(
            fsc_rows=("record_key", "count"),
            unique_organizations=("organization_name_normalized", "nunique"),
            unique_licences=("licence_normalized", "nunique"),
            organization_names=(
                "organization_name",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:100]
                ),
            ),
            source_url=("source_url", "first"),
        )
        .reset_index()
    )

    country_df["certification"] = CERTIFICATION_SHORT_NAME
    country_df["certification_full_name"] = CERTIFICATION_NAME
    country_df["registry_section"] = "Country Summary"
    country_df["registry_match_level"] = "country_summary"

    country_df["evidence_text"] = country_df.apply(
        lambda row: (
            f"{row['country_area']} has {row['fsc_rows']} FSC row(s), "
            f"{row['unique_organizations']} organization(s) and "
            f"{row['unique_licences']} licence(s)."
        ),
        axis=1,
    )

    country_df = country_df[
        [
            "certification",
            "certification_full_name",
            "registry_section",
            "registry_match_level",
            "country_area",
            "country_area_normalized",
            "fsc_rows",
            "unique_organizations",
            "unique_licences",
            "organization_names",
            "source_url",
            "evidence_text",
        ]
    ]

    return country_df.sort_values(["country_area_normalized"]).reset_index(drop=True)


def build_metadata(
    rows_df: pd.DataFrame,
    organizations_df: pd.DataFrame,
    countries_df: pd.DataFrame,
    scrape_log_df: pd.DataFrame,
    report_timestamp: str,
    args: argparse.Namespace,
) -> pd.DataFrame:
    metadata = [
        {
            "certification": CERTIFICATION_SHORT_NAME,
            "certification_full_name": CERTIFICATION_NAME,
            "registry_section": REGISTRY_SECTION,
            "source_type": "Power BI dashboard scraped with Playwright by parsing visible row texts",
            "source_url": START_URL,
            "report_timestamp_or_data_last_updated": report_timestamp,
            "certificate_rows_extracted": len(rows_df),
            "organization_summary_rows": len(organizations_df),
            "country_summary_rows": len(countries_df),
            "scrolls_executed": int(scrape_log_df["scroll_number"].max())
            if not scrape_log_df.empty and "scroll_number" in scrape_log_df.columns
            else 0,
            "max_scrolls_requested": args.max_scrolls,
            "stable_rounds_requested": args.stable_rounds,
            "scroll_pixels": args.scroll_pixels,
            "headless": args.headless,
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "note": (
                "This FSC registry is organization/certificate-level. It is built from the public "
                "FSC Certificates Public Dashboard. Because the Power BI table is virtualized, "
                "the script collects visible row texts while scrolling, parses FSC row patterns, "
                "and deduplicates them."
            ),
        }
    ]

    return pd.DataFrame(metadata)


def save_outputs(
    rows_df: pd.DataFrame,
    organizations_df: pd.DataFrame,
    countries_df: pd.DataFrame,
    scrape_log_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    rows_df = sanitize_dataframe_for_excel(rows_df)
    organizations_df = sanitize_dataframe_for_excel(organizations_df)
    countries_df = sanitize_dataframe_for_excel(countries_df)
    scrape_log_df = sanitize_dataframe_for_excel(scrape_log_df)
    metadata_df = sanitize_dataframe_for_excel(metadata_df)

    rows_csv = output_dir / "fsc_certificate_rows.csv"
    organizations_csv = output_dir / "fsc_organizations.csv"
    countries_csv = output_dir / "fsc_countries.csv"
    scrape_log_csv = output_dir / "fsc_scrape_log.csv"
    metadata_csv = output_dir / "fsc_metadata.csv"
    excel_path = output_dir / "fsc_registry.xlsx"

    rows_df.to_csv(rows_csv, index=False, encoding="utf-8-sig")
    organizations_df.to_csv(organizations_csv, index=False, encoding="utf-8-sig")
    countries_df.to_csv(countries_csv, index=False, encoding="utf-8-sig")
    scrape_log_df.to_csv(scrape_log_csv, index=False, encoding="utf-8-sig")
    metadata_df.to_csv(metadata_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        rows_df.to_excel(writer, sheet_name="certificate_rows", index=False)
        organizations_df.to_excel(writer, sheet_name="organizations", index=False)
        countries_df.to_excel(writer, sheet_name="countries", index=False)
        metadata_df.to_excel(writer, sheet_name="metadata", index=False)
        scrape_log_df.to_excel(writer, sheet_name="scrape_log", index=False)

    print("")
    print("Saved files:")
    print(f"- {rows_csv}")
    print(f"- {organizations_csv}")
    print(f"- {countries_csv}")
    print(f"- {metadata_csv}")
    print(f"- {scrape_log_csv}")
    print(f"- {excel_path}")


def build_fsc_registry(args: argparse.Namespace) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    all_rows: List[Dict[str, object]] = []
    scrape_log: List[Dict[str, object]] = []

    report_timestamp = ""

    with sync_playwright() as playwright:
        browser: Browser = playwright.chromium.launch(
            headless=args.headless,
            slow_mo=args.slow_mo,
        )

        context: BrowserContext = browser.new_context(
            viewport={
                "width": args.viewport_width,
                "height": args.viewport_height,
            },
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            locale="en-US",
        )

        page: Page = context.new_page()

        print("Opening FSC Certificates Public Dashboard...")
        print(f"Start URL: {START_URL}")
        print(f"Headless: {args.headless}")
        print("")

        page.goto(START_URL, wait_until="domcontentloaded", timeout=args.timeout_ms)

        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass

        frame = select_powerbi_frame(page=page, timeout_ms=args.timeout_ms)

        wait_for_fsc_table(
            page=page,
            frame=frame,
            timeout_ms=args.timeout_ms,
        )

        report_timestamp = extract_report_timestamp(frame)

        initial_rows = extract_visible_fsc_rows(
            frame=frame,
            scroll_number=0,
        )

        all_rows.extend(initial_rows)
        all_rows = deduplicate_rows(all_rows)

        initial_signature = get_visible_signature(frame)

        scrape_log.append(
            {
                "certification": CERTIFICATION_SHORT_NAME,
                "registry_section": REGISTRY_SECTION,
                "event": "initial",
                "scroll_number": 0,
                "visible_rows_extracted": len(initial_rows),
                "unique_rows_collected": len(all_rows),
                "visible_signature": initial_signature,
                "scroll_method": "",
                "scrolled": "",
                "report_timestamp": report_timestamp,
                "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )

        print(
            f"Initial visible rows: {len(initial_rows)}, "
            f"unique rows collected: {len(all_rows)}, "
            f"report timestamp: {report_timestamp or 'not detected'}"
        )

        stable_rounds = 0
        previous_signature = initial_signature

        for scroll_number in tqdm(
            range(1, args.max_scrolls + 1),
            desc="Scrolling FSC table",
        ):
            before_count = len(all_rows)

            scroll_info = scroll_fsc_table(
                frame=frame,
                scroll_pixels=args.scroll_pixels,
            )

            time.sleep(args.scroll_delay)

            visible_rows = extract_visible_fsc_rows(
                frame=frame,
                scroll_number=scroll_number,
            )

            all_rows.extend(visible_rows)
            all_rows = deduplicate_rows(all_rows)

            after_count = len(all_rows)
            new_rows = after_count - before_count

            current_signature = get_visible_signature(frame)

            scrape_log.append(
                {
                    "certification": CERTIFICATION_SHORT_NAME,
                    "registry_section": REGISTRY_SECTION,
                    "event": "scroll",
                    "scroll_number": scroll_number,
                    "visible_rows_extracted": len(visible_rows),
                    "unique_rows_collected": after_count,
                    "new_rows_collected": new_rows,
                    "visible_signature": current_signature,
                    "previous_signature": previous_signature,
                    "signature_changed": current_signature != previous_signature,
                    "scroll_method": scroll_info.get("method", ""),
                    "scrolled": scroll_info.get("scrolled", ""),
                    "previous_scroll_top": scroll_info.get("previous_scroll_top", ""),
                    "new_scroll_top": scroll_info.get("new_scroll_top", ""),
                    "scroll_height": scroll_info.get("scroll_height", ""),
                    "client_height": scroll_info.get("client_height", ""),
                    "scroll_target_score": scroll_info.get("score", ""),
                    "report_timestamp": report_timestamp,
                    "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
                }
            )

            print(
                f"Scroll {scroll_number}: visible rows {len(visible_rows)}, "
                f"new {new_rows}, unique collected {after_count}"
            )

            if args.checkpoint_every > 0 and scroll_number % args.checkpoint_every == 0:
                try:
                    save_checkpoint(
                        rows=all_rows,
                        scrape_log=scrape_log,
                        output_dir=OUTPUT_DIR,
                    )
                except Exception as checkpoint_error:
                    print(f"Checkpoint warning: {checkpoint_error}")

            if new_rows <= 0 and current_signature == previous_signature:
                stable_rounds += 1
            else:
                stable_rounds = 0

            previous_signature = current_signature

            if stable_rounds >= args.stable_rounds:
                print(
                    f"No new rows/signature change for {stable_rounds} consecutive scrolls. Stopping."
                )
                break

        context.close()
        browser.close()

    rows_df = pd.DataFrame(deduplicate_rows(all_rows))

    if not rows_df.empty:
        rows_df = rows_df.sort_values(
            [
                "organization_name_normalized",
                "licence_normalized",
                "certificate_code_normalized",
                "role",
                "site_status",
            ]
        ).reset_index(drop=True)

    organizations_df = build_organization_summary(rows_df)
    countries_df = build_country_summary(rows_df)
    scrape_log_df = pd.DataFrame(scrape_log)

    metadata_df = build_metadata(
        rows_df=rows_df,
        organizations_df=organizations_df,
        countries_df=countries_df,
        scrape_log_df=scrape_log_df,
        report_timestamp=report_timestamp,
        args=args,
    )

    print("")
    print("Registry summary:")
    print(f"  Certificate rows extracted: {len(rows_df)}")
    print(f"  Organization summary rows: {len(organizations_df)}")
    print(f"  Country summary rows: {len(countries_df)}")
    print(f"  Report timestamp/data updated: {report_timestamp or 'not detected'}")

    if rows_df.empty:
        print("")
        print("WARNING: No FSC rows were extracted.")
        print(f"Debug files are available in: {DEBUG_DIR}")

    save_outputs(
        rows_df=rows_df,
        organizations_df=organizations_df,
        countries_df=countries_df,
        scrape_log_df=scrape_log_df,
        metadata_df=metadata_df,
        output_dir=OUTPUT_DIR,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a local FSC registry by scraping the FSC Certificates Public Dashboard "
            "Power BI table through Playwright scrolling."
        )
    )

    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chromium in headless mode. Default: visible browser.",
    )

    parser.add_argument(
        "--max-scrolls",
        type=int,
        default=DEFAULT_MAX_SCROLLS,
        help=f"Maximum table scrolls. Default: {DEFAULT_MAX_SCROLLS}.",
    )

    parser.add_argument(
        "--stable-rounds",
        type=int,
        default=DEFAULT_STABLE_ROUNDS,
        help=(
            "Stop after this many consecutive scrolls without new rows and without visible signature change. "
            f"Default: {DEFAULT_STABLE_ROUNDS}."
        ),
    )

    parser.add_argument(
        "--scroll-pixels",
        type=int,
        default=DEFAULT_SCROLL_PIXELS,
        help=f"Pixels to scroll at each step. Default: {DEFAULT_SCROLL_PIXELS}.",
    )

    parser.add_argument(
        "--scroll-delay",
        type=float,
        default=0.65,
        help="Delay after each scroll, in seconds. Default: 0.65.",
    )

    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=60000,
        help="Timeout in milliseconds. Default: 60000.",
    )

    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=100,
        help="Save checkpoint every N scrolls. Default: 100.",
    )

    parser.add_argument(
        "--slow-mo",
        type=int,
        default=0,
        help="Playwright slow motion in milliseconds. Default: 0.",
    )

    parser.add_argument(
        "--viewport-width",
        type=int,
        default=1800,
        help="Browser viewport width. Default: 1800.",
    )

    parser.add_argument(
        "--viewport-height",
        type=int,
        default=950,
        help="Browser viewport height. Default: 950.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_fsc_registry(args)


if __name__ == "__main__":
    main()