import argparse
import hashlib
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from playwright.sync_api import Browser, BrowserContext, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from tqdm import tqdm


CERTIFICATION_NAME = "Fair for Life"
REGISTRY_SECTION = "Certified Partners"

START_URL = "https://www.fairforlife.org/en/our-partners/certified-partners/"

OUTPUT_DIR = Path("data") / "certifications" / "fair_for_life"
DEBUG_DIR = OUTPUT_DIR / "debug"

DEFAULT_MAX_SCROLLS = 180
DEFAULT_STABLE_ROUNDS = 8


def clean_text(value: object) -> str:
    if value is None:
        return ""

    text = str(value)
    text = text.replace("\u00a0", " ")
    text = text.replace("\ufeff", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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


def make_partner_key(partner_name: str, location_text: str, partner_url: str) -> str:
    raw_key = (
        f"{normalize_for_matching(partner_name)}|"
        f"{normalize_for_matching(location_text)}|"
        f"{clean_text(partner_url)}"
    )
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def extract_total_count(text: str) -> Optional[int]:
    patterns = [
        r"([0-9,]+)\s+certified\s+partners",
        r"([0-9,]+)\s+result\(s\)",
        r"([0-9,]+)\s+results",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)

        if match:
            return int(match.group(1).replace(",", ""))

    return None


def parse_labels(label_text: str) -> str:
    label_text = clean_text(label_text)

    labels = []

    if re.search(r"\bFair\s+for\s+Life\b", label_text, flags=re.IGNORECASE):
        labels.append("Fair for Life")

    label_without_fair_for_life = re.sub(
        r"\bFair\s+for\s+Life\b",
        "",
        label_text,
        flags=re.IGNORECASE,
    )

    if re.search(r"\bFor\s+Life\b", label_without_fair_for_life, flags=re.IGNORECASE):
        labels.append("For Life")

    return " | ".join(dict.fromkeys(labels))


def parse_location(location_text: str) -> Dict[str, str]:
    location_text = clean_text(location_text)

    if not location_text:
        return {
            "city_or_place": "",
            "country_or_region": "",
            "country_code_or_name": "",
        }

    if "," in location_text:
        parts = [clean_text(part) for part in location_text.split(",")]
        parts = [part for part in parts if part]

        if len(parts) >= 2:
            return {
                "city_or_place": ", ".join(parts[:-1]),
                "country_or_region": parts[-1],
                "country_code_or_name": parts[-1],
            }

    tokens = location_text.split()

    if tokens:
        return {
            "city_or_place": location_text,
            "country_or_region": tokens[-1],
            "country_code_or_name": tokens[-1],
        }

    return {
        "city_or_place": location_text,
        "country_or_region": "",
        "country_code_or_name": "",
    }


def save_debug_page(page: Page, reason: str) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_reason = re.sub(r"[^a-zA-Z0-9_-]+", "_", reason)

    screenshot_path = DEBUG_DIR / f"{safe_reason}_{timestamp}.png"
    text_path = DEBUG_DIR / f"{safe_reason}_{timestamp}.txt"
    html_path = DEBUG_DIR / f"{safe_reason}_{timestamp}.html"

    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception:
        pass

    try:
        body_text = page.locator("body").inner_text(timeout=5000)
        text_path.write_text(body_text, encoding="utf-8", errors="ignore")
    except Exception:
        pass

    try:
        html_path.write_text(page.content(), encoding="utf-8", errors="ignore")
    except Exception:
        pass


def accept_cookies_if_present(page: Page) -> None:
    cookie_patterns = [
        re.compile(r"accept", flags=re.IGNORECASE),
        re.compile(r"agree", flags=re.IGNORECASE),
        re.compile(r"allow", flags=re.IGNORECASE),
        re.compile(r"ok", flags=re.IGNORECASE),
        re.compile(r"reject", flags=re.IGNORECASE),
        re.compile(r"continue", flags=re.IGNORECASE),
    ]

    for pattern in cookie_patterns:
        try:
            button = page.get_by_role("button", name=pattern).first

            if button.is_visible(timeout=1000):
                button.click(timeout=3000)
                time.sleep(0.6)
                return
        except Exception:
            continue


def wait_for_partner_listing(page: Page, timeout_ms: int) -> None:
    try:
        page.wait_for_function(
            """
            () => {
              const text = document.body.innerText || "";
              const hasCount =
                /\\b[0-9,]+\\s+certified\\s+partners\\b/i.test(text) ||
                /\\b[0-9,]+\\s+result\\(s\\)/i.test(text) ||
                /\\b[0-9,]+\\s+results\\b/i.test(text);

              const hasPartnerCard = /View\\s+partner/i.test(text);

              return hasCount && hasPartnerCard;
            }
            """,
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        save_debug_page(page, "wait_for_partner_listing_timeout")
        raise


def extract_visible_partners(page: Page) -> List[Dict[str, object]]:
    raw_partners = page.evaluate(
        """
        () => {
          function cleanText(text) {
            return (text || "")
              .replace(/\\u00a0/g, " ")
              .replace(/[ \\t]+/g, " ")
              .replace(/\\n\\s+/g, "\\n")
              .trim();
          }

          function absoluteUrl(url) {
            if (!url) return "";

            try {
              return new URL(url, window.location.href).href;
            } catch {
              return "";
            }
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

          function textLines(element) {
            const rawText = cleanText(element.innerText || element.textContent || "");

            return rawText
              .split("\\n")
              .map((line) => cleanText(line))
              .filter(Boolean);
          }

          function hasPartnerSignals(element) {
            const text = cleanText(element.innerText || element.textContent || "");
            const lines = textLines(element);

            const hasViewPartner = /View\\s+partner/i.test(text);
            const hasLabel = /Fair\\s+for\\s+Life|For\\s+Life/i.test(text);
            const hasEnoughLines = lines.length >= 3;

            return hasViewPartner && hasLabel && hasEnoughLines;
          }

          const allElements = Array.from(
            document.querySelectorAll(
              "article, li, section, div, a"
            )
          ).filter(isVisible);

          const candidateCards = allElements.filter((element) => {
            const text = cleanText(element.innerText || element.textContent || "");

            if (text.length < 20 || text.length > 1500) {
              return false;
            }

            if (!hasPartnerSignals(element)) {
              return false;
            }

            if (
              /Filter by|All countries|All labels|All sectors|All roles|Search for partners|Reset filters/i.test(text) &&
              text.length > 250
            ) {
              return false;
            }

            return true;
          });

          const smallestCards = candidateCards.filter((candidate) => {
            return !candidateCards.some((other) => {
              return (
                other !== candidate &&
                candidate.contains(other) &&
                hasPartnerSignals(other)
              );
            });
          });

          const rows = [];

          for (const card of smallestCards) {
            const lines = textLines(card);

            const partnerUrlCandidates = Array.from(card.querySelectorAll("a[href]"))
              .map((link) => {
                return {
                  text: cleanText(link.innerText || link.textContent || ""),
                  href: absoluteUrl(link.getAttribute("href") || "")
                };
              });

            let partnerUrl = "";

            const viewPartnerLink = partnerUrlCandidates.find((item) => {
              return /View\\s+partner/i.test(item.text);
            });

            if (viewPartnerLink) {
              partnerUrl = viewPartnerLink.href;
            } else if (partnerUrlCandidates.length > 0) {
              partnerUrl = partnerUrlCandidates[0].href;
            }

            const rect = card.getBoundingClientRect();

            rows.push({
              lines,
              partner_url: partnerUrl,
              evidence_text: lines.join(" | "),
              card_x: rect.x,
              card_y: rect.y,
              card_width: rect.width,
              card_height: rect.height
            });
          }

          return rows;
        }
        """
    )

    partners = []

    for raw_partner in raw_partners:
        lines = raw_partner.get("lines", [])

        if not isinstance(lines, list):
            continue

        cleaned_lines = [clean_text(line) for line in lines]
        cleaned_lines = [line for line in cleaned_lines if line]

        filtered_lines = []

        for line in cleaned_lines:
            if re.fullmatch(r"\+", line):
                continue

            if re.search(r"^View\s+partner$", line, flags=re.IGNORECASE):
                continue

            filtered_lines.append(line)

        if len(filtered_lines) < 2:
            continue

        label_line_index = None

        for index, line in enumerate(filtered_lines):
            if re.search(r"\bFair\s+for\s+Life\b|\bFor\s+Life\b", line, flags=re.IGNORECASE):
                label_line_index = index
                break

        if label_line_index is None:
            continue

        partner_name = ""

        for line in filtered_lines[:label_line_index]:
            if not re.search(r"\bFair\s+for\s+Life\b|\bFor\s+Life\b", line, flags=re.IGNORECASE):
                partner_name = line
                break

        if not partner_name:
            partner_name = filtered_lines[0]

        label_text = filtered_lines[label_line_index]
        labels = parse_labels(label_text)

        location_text = ""

        if label_line_index + 1 < len(filtered_lines):
            location_text = filtered_lines[label_line_index + 1]

        location_parts = parse_location(location_text)
        partner_url = clean_text(raw_partner.get("partner_url", ""))

        partner_key = make_partner_key(
            partner_name=partner_name,
            location_text=location_text,
            partner_url=partner_url,
        )

        partners.append(
            {
                "certification": CERTIFICATION_NAME,
                "registry_section": REGISTRY_SECTION,
                "registry_source": "Fair for Life certified partners listing",
                "partner_key": partner_key,
                "partner_name": partner_name,
                "partner_name_normalized": normalize_for_matching(partner_name),
                "labels": labels,
                "raw_label_text": label_text,
                "location_text": location_text,
                "city_or_place": location_parts["city_or_place"],
                "country_or_region": location_parts["country_or_region"],
                "country_code_or_name": location_parts["country_code_or_name"],
                "partner_url": partner_url,
                "evidence_text": clean_text(raw_partner.get("evidence_text", "")),
                "card_x": raw_partner.get("card_x"),
                "card_y": raw_partner.get("card_y"),
                "card_width": raw_partner.get("card_width"),
                "card_height": raw_partner.get("card_height"),
                "source_url": START_URL,
                "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )

    return partners


def deduplicate_partners(partners: List[Dict[str, object]]) -> List[Dict[str, object]]:
    seen = set()
    deduped = []

    for partner in partners:
        partner_key = clean_text(partner.get("partner_key", ""))

        if not partner_key:
            partner_key = make_partner_key(
                partner_name=str(partner.get("partner_name", "")),
                location_text=str(partner.get("location_text", "")),
                partner_url=str(partner.get("partner_url", "")),
            )

        if partner_key in seen:
            continue

        seen.add(partner_key)
        deduped.append(partner)

    return deduped


def get_unique_partner_count(page: Page) -> int:
    return len(deduplicate_partners(extract_visible_partners(page)))


def scroll_partner_listing(page: Page, scroll_pixels: int) -> Dict[str, object]:
    return page.evaluate(
        """
        ([scrollPixels]) => {
          function isScrollable(element) {
            if (!element) return false;

            const style = window.getComputedStyle(element);
            const overflowY = style.overflowY;
            const canScroll = element.scrollHeight > element.clientHeight + 20;

            return (
              canScroll &&
              ["auto", "scroll", "overlay", "visible"].includes(overflowY)
            );
          }

          function cleanText(text) {
            return (text || "").replace(/\\s+/g, " ").trim();
          }

          const candidates = Array.from(document.querySelectorAll("body, main, section, div"))
            .filter(isScrollable)
            .map((element) => {
              const text = cleanText(element.innerText || element.textContent || "");
              const rect = element.getBoundingClientRect();

              let score = 0;

              if (/View\\s+partner/i.test(text)) {
                score += 150;
              }

              if (/result\\(s\\)|certified\\s+partners/i.test(text)) {
                score += 60;
              }

              if (rect.width >= 250 && rect.height >= 250) {
                score += 30;
              }

              if (element.scrollHeight > 1000) {
                score += 20;
              }

              if (/Filter by|All countries|All labels|All sectors|All roles/i.test(text)) {
                score -= 20;
              }

              return {
                element,
                score,
                previousScrollTop: element.scrollTop,
                scrollHeight: element.scrollHeight,
                clientHeight: element.clientHeight,
                textExcerpt: text.slice(0, 200)
              };
            })
            .sort((a, b) => b.score - a.score);

          let target = candidates.length > 0 ? candidates[0] : null;

          if (target) {
            target.element.scrollTop = Math.min(
              target.element.scrollTop + scrollPixels,
              target.element.scrollHeight
            );

            return {
              scrolled: target.element.scrollTop !== target.previousScrollTop,
              target_type: "element",
              score: target.score,
              previous_scroll_top: target.previousScrollTop,
              new_scroll_top: target.element.scrollTop,
              scroll_height: target.scrollHeight,
              client_height: target.clientHeight,
              text_excerpt: target.textExcerpt
            };
          }

          const previousWindowY = window.scrollY;
          window.scrollBy(0, scrollPixels);

          return {
            scrolled: window.scrollY !== previousWindowY,
            target_type: "window",
            previous_scroll_top: previousWindowY,
            new_scroll_top: window.scrollY,
            scroll_height: document.documentElement.scrollHeight,
            client_height: window.innerHeight,
            text_excerpt: ""
          };
        }
        """,
        [scroll_pixels],
    )


def save_checkpoint(
    partners: List[Dict[str, object]],
    scrape_log: List[Dict[str, object]],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    partners_df = pd.DataFrame(deduplicate_partners(partners))
    scrape_log_df = pd.DataFrame(scrape_log)

    checkpoint_path = output_dir / "fair_for_life_registry_CHECKPOINT.xlsx"

    with pd.ExcelWriter(checkpoint_path, engine="openpyxl") as writer:
        partners_df.to_excel(writer, sheet_name="partners", index=False)
        scrape_log_df.to_excel(writer, sheet_name="scrape_log", index=False)

    print(f"Checkpoint saved: {checkpoint_path}")


def build_labels_registry(partners_df: pd.DataFrame) -> pd.DataFrame:
    if partners_df.empty:
        return pd.DataFrame()

    rows = []

    for _, row in partners_df.iterrows():
        labels = clean_text(row.get("labels", ""))

        if not labels:
            continue

        for label in labels.split("|"):
            label = clean_text(label)

            if not label:
                continue

            rows.append(
                {
                    "certification": CERTIFICATION_NAME,
                    "registry_section": "Partner Labels",
                    "label": label,
                    "partner_name": row.get("partner_name", ""),
                    "partner_name_normalized": row.get("partner_name_normalized", ""),
                    "location_text": row.get("location_text", ""),
                    "country_or_region": row.get("country_or_region", ""),
                    "partner_url": row.get("partner_url", ""),
                    "source_url": row.get("source_url", START_URL),
                    "evidence_text": row.get("evidence_text", ""),
                }
            )

    labels_df = pd.DataFrame(rows)

    if labels_df.empty:
        return labels_df

    labels_df = labels_df.drop_duplicates(
        subset=["label", "partner_name_normalized", "location_text"],
        keep="first",
    ).reset_index(drop=True)

    return labels_df


def build_country_registry(partners_df: pd.DataFrame) -> pd.DataFrame:
    if partners_df.empty:
        return pd.DataFrame()

    country_df = (
        partners_df.groupby(["country_or_region"], dropna=False)
        .agg(
            partner_rows=("partner_name", "count"),
            unique_partners=("partner_name_normalized", "nunique"),
            labels=("labels", lambda values: " | ".join(sorted(set(v for v in values if v)))),
            partner_names=("partner_name", lambda values: " | ".join(sorted(set(values))[:50])),
            source_url=("source_url", "first"),
        )
        .reset_index()
    )

    country_df["certification"] = CERTIFICATION_NAME
    country_df["registry_section"] = "Countries / Regions"
    country_df["registry_match_level"] = "country_summary"

    country_df["evidence_text"] = country_df.apply(
        lambda row: (
            f"{row['country_or_region']} has {row['partner_rows']} Fair for Life / For Life partner row(s)."
        ),
        axis=1,
    )

    country_df = country_df[
        [
            "certification",
            "registry_section",
            "registry_match_level",
            "country_or_region",
            "partner_rows",
            "unique_partners",
            "labels",
            "partner_names",
            "source_url",
            "evidence_text",
        ]
    ]

    country_df = country_df.sort_values(["country_or_region"]).reset_index(drop=True)

    return country_df


def build_metadata(
    partners_df: pd.DataFrame,
    labels_df: pd.DataFrame,
    country_df: pd.DataFrame,
    scrape_log_df: pd.DataFrame,
    reported_total_count: Optional[int],
    args: argparse.Namespace,
) -> pd.DataFrame:
    metadata = [
        {
            "certification": CERTIFICATION_NAME,
            "registry_section": REGISTRY_SECTION,
            "source_url": START_URL,
            "source_type": "Dynamic website scraped with Playwright",
            "reported_total_count": reported_total_count,
            "partner_rows_extracted": len(partners_df),
            "unique_partners": partners_df["partner_name_normalized"].nunique()
            if not partners_df.empty
            else 0,
            "label_rows": len(labels_df),
            "country_rows": len(country_df),
            "scrolls_executed": int(scrape_log_df["scroll_number"].max())
            if not scrape_log_df.empty and "scroll_number" in scrape_log_df.columns
            else 0,
            "max_scrolls_requested": args.max_scrolls,
            "headless": args.headless,
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "note": (
                "Registry built from the Fair for Life certified partners public listing. "
                "This is a partner-level registry, not a product-level registry."
            ),
        }
    ]

    return pd.DataFrame(metadata)


def save_outputs(
    partners_df: pd.DataFrame,
    labels_df: pd.DataFrame,
    country_df: pd.DataFrame,
    scrape_log_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    partners_csv = output_dir / "fair_for_life_partners.csv"
    labels_csv = output_dir / "fair_for_life_partner_labels.csv"
    countries_csv = output_dir / "fair_for_life_countries.csv"
    scrape_log_csv = output_dir / "fair_for_life_scrape_log.csv"
    metadata_csv = output_dir / "fair_for_life_metadata.csv"
    excel_path = output_dir / "fair_for_life_registry.xlsx"

    partners_df.to_csv(partners_csv, index=False, encoding="utf-8-sig")
    labels_df.to_csv(labels_csv, index=False, encoding="utf-8-sig")
    country_df.to_csv(countries_csv, index=False, encoding="utf-8-sig")
    scrape_log_df.to_csv(scrape_log_csv, index=False, encoding="utf-8-sig")
    metadata_df.to_csv(metadata_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        partners_df.to_excel(writer, sheet_name="partners", index=False)
        labels_df.to_excel(writer, sheet_name="partner_labels", index=False)
        country_df.to_excel(writer, sheet_name="countries", index=False)
        metadata_df.to_excel(writer, sheet_name="metadata", index=False)
        scrape_log_df.to_excel(writer, sheet_name="scrape_log", index=False)

    print("")
    print("Saved files:")
    print(f"- {partners_csv}")
    print(f"- {labels_csv}")
    print(f"- {countries_csv}")
    print(f"- {metadata_csv}")
    print(f"- {scrape_log_csv}")
    print(f"- {excel_path}")


def build_fair_for_life_registry(args: argparse.Namespace) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    all_partners: List[Dict[str, object]] = []
    scrape_log: List[Dict[str, object]] = []
    reported_total_count: Optional[int] = None

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

        print("Opening Fair for Life certified partners listing...")
        print(f"Start URL: {START_URL}")
        print(f"Max scrolls: {args.max_scrolls}")
        print(f"Headless: {args.headless}")
        print("")

        page.goto(START_URL, wait_until="domcontentloaded", timeout=args.timeout_ms)

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        accept_cookies_if_present(page)
        wait_for_partner_listing(page, timeout_ms=args.timeout_ms)

        body_text = page.locator("body").inner_text(timeout=args.timeout_ms)
        reported_total_count = extract_total_count(body_text)

        initial_partners = extract_visible_partners(page)
        all_partners.extend(initial_partners)
        all_partners = deduplicate_partners(all_partners)

        visible_count = get_unique_partner_count(page)

        scrape_log.append(
            {
                "certification": CERTIFICATION_NAME,
                "event": "initial_page",
                "scroll_number": 0,
                "visible_partner_count": visible_count,
                "unique_partners_collected": len(all_partners),
                "reported_total_count": reported_total_count,
                "page_url": page.url,
                "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )

        print(
            f"Initial page: visible partners {visible_count}, "
            f"unique partners collected {len(all_partners)}, "
            f"reported total {reported_total_count}"
        )

        stable_rounds = 0

        for scroll_number in tqdm(
            range(1, args.max_scrolls + 1),
            desc="Scrolling partner list",
        ):
            if reported_total_count is not None and len(all_partners) >= reported_total_count:
                print("Reported total reached. Stopping.")
                break

            before_count = len(all_partners)

            scroll_info = scroll_partner_listing(
                page=page,
                scroll_pixels=args.scroll_pixels,
            )

            time.sleep(args.scroll_delay)

            current_partners = extract_visible_partners(page)
            all_partners.extend(current_partners)
            all_partners = deduplicate_partners(all_partners)

            after_count = len(all_partners)
            visible_count = get_unique_partner_count(page)
            new_items = after_count - before_count

            scrape_log.append(
                {
                    "certification": CERTIFICATION_NAME,
                    "event": "scroll",
                    "scroll_number": scroll_number,
                    "visible_partner_count": visible_count,
                    "unique_partners_collected": after_count,
                    "new_partners_collected": new_items,
                    "reported_total_count": reported_total_count,
                    "scrolled": scroll_info.get("scrolled"),
                    "scroll_target_type": scroll_info.get("target_type"),
                    "previous_scroll_top": scroll_info.get("previous_scroll_top"),
                    "new_scroll_top": scroll_info.get("new_scroll_top"),
                    "scroll_height": scroll_info.get("scroll_height"),
                    "client_height": scroll_info.get("client_height"),
                    "page_url": page.url,
                    "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
                }
            )

            print(
                f"Scroll {scroll_number}: visible partners {visible_count}, "
                f"unique partners collected {after_count}, new {new_items}"
            )

            if new_items <= 0:
                stable_rounds += 1
            else:
                stable_rounds = 0

            if args.checkpoint_every > 0 and scroll_number % args.checkpoint_every == 0:
                save_checkpoint(
                    partners=all_partners,
                    scrape_log=scrape_log,
                    output_dir=OUTPUT_DIR,
                )

            if stable_rounds >= args.stable_rounds:
                print(
                    f"No new partners collected for {stable_rounds} consecutive scrolls. Stopping."
                )
                break

            if not bool(scroll_info.get("scrolled")) and new_items <= 0:
                stable_rounds += 1

        partners_df = pd.DataFrame(deduplicate_partners(all_partners))

        if not partners_df.empty:
            partners_df = partners_df.sort_values(
                ["partner_name_normalized", "location_text", "partner_url"]
            ).reset_index(drop=True)

        labels_df = build_labels_registry(partners_df)
        country_df = build_country_registry(partners_df)
        scrape_log_df = pd.DataFrame(scrape_log)

        metadata_df = build_metadata(
            partners_df=partners_df,
            labels_df=labels_df,
            country_df=country_df,
            scrape_log_df=scrape_log_df,
            reported_total_count=reported_total_count,
            args=args,
        )

        save_outputs(
            partners_df=partners_df,
            labels_df=labels_df,
            country_df=country_df,
            scrape_log_df=scrape_log_df,
            metadata_df=metadata_df,
            output_dir=OUTPUT_DIR,
        )

        context.close()
        browser.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a local Fair for Life partner registry by scraping the public "
            "certified partners listing and scrolling through the complete list."
        )
    )

    parser.add_argument(
        "--max-scrolls",
        type=int,
        default=DEFAULT_MAX_SCROLLS,
        help=f"Maximum number of scroll steps. Default: {DEFAULT_MAX_SCROLLS}",
    )

    parser.add_argument(
        "--stable-rounds",
        type=int,
        default=DEFAULT_STABLE_ROUNDS,
        help=(
            "Stop after this many consecutive scrolls without new partners. "
            f"Default: {DEFAULT_STABLE_ROUNDS}"
        ),
    )

    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode. Default is visible browser for easier debugging.",
    )

    parser.add_argument(
        "--slow-mo",
        type=int,
        default=0,
        help="Playwright slow motion in milliseconds. Useful for debugging. Default: 0",
    )

    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        help="Timeout in milliseconds. Default: 30000",
    )

    parser.add_argument(
        "--scroll-delay",
        type=float,
        default=0.8,
        help="Delay after each scroll step, in seconds. Default: 0.8",
    )

    parser.add_argument(
        "--scroll-pixels",
        type=int,
        default=700,
        help="Pixels to scroll at each step. Default: 700",
    )

    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=25,
        help="Save checkpoint every N scrolls. Default: 25",
    )

    parser.add_argument(
        "--viewport-width",
        type=int,
        default=1600,
        help="Browser viewport width. Default: 1600",
    )

    parser.add_argument(
        "--viewport-height",
        type=int,
        default=1000,
        help="Browser viewport height. Default: 1000",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_fair_for_life_registry(args)


if __name__ == "__main__":
    main()