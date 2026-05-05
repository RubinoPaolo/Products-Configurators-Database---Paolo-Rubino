import argparse
import hashlib
import re
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm


BASE_URL = "https://www.blauer-engel.de"
PRODUCTS_AZ_URL = "https://www.blauer-engel.de/en/products/products-list-a-z"
COMPANIES_AZ_URL = "https://www.blauer-engel.de/en/products/companies"
BRANDS_AZ_URL = "https://www.blauer-engel.de/en/brands"

OUTPUT_DIR = Path("data") / "certifications" / "blue_angel"
CACHE_DIR = OUTPUT_DIR / ".cache"

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
}

COUNT_AT_END_RE = re.compile(r"\((\d+)\)\s*$")
CRITERION_RE = re.compile(r"\bDE-UZ\s*\d+[a-zA-Z]?\b", re.IGNORECASE)


def clean_text(value: object) -> str:
    if value is None:
        return ""

    text = str(value)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_multiline_text(value: object) -> str:
    if value is None:
        return ""

    text = str(value)
    text = text.replace("\u00a0", " ")
    lines = [clean_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def absolute_url(href: str, base_url: str = BASE_URL) -> str:
    return urljoin(base_url, href)


def url_path(url: str) -> str:
    return urlparse(url).path.rstrip("/")


def make_cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest() + ".html"


def get_cached_html(url: str) -> Optional[str]:
    cache_path = CACHE_DIR / make_cache_key(url)

    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="ignore")

    return None


def set_cached_html(url: str, html: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / make_cache_key(url)
    cache_path.write_text(html, encoding="utf-8", errors="ignore")


def fetch_html(
    session: requests.Session,
    url: str,
    sleep_seconds: float,
    timeout: int,
    use_cache: bool,
) -> str:
    if use_cache:
        cached = get_cached_html(url)

        if cached:
            return cached

    response = session.get(
        url,
        headers=REQUEST_HEADERS,
        timeout=timeout,
        allow_redirects=True,
    )

    time.sleep(sleep_seconds)

    response.raise_for_status()

    html = response.text

    if use_cache:
        set_cached_html(url, html)

    return html


def get_soup(
    session: requests.Session,
    url: str,
    sleep_seconds: float,
    timeout: int,
    use_cache: bool,
) -> BeautifulSoup:
    html = fetch_html(
        session=session,
        url=url,
        sleep_seconds=sleep_seconds,
        timeout=timeout,
        use_cache=use_cache,
    )

    return BeautifulSoup(html, "html.parser")


def parse_counted_label(text: str) -> Optional[Dict[str, object]]:
    text = clean_text(text)
    match = COUNT_AT_END_RE.search(text)

    if not match:
        return None

    count = int(match.group(1))
    name = COUNT_AT_END_RE.sub("", text).strip()

    if not name:
        return None

    return {
        "name": name,
        "count": count,
        "raw_text": text,
    }


def get_h1(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")

    if h1:
        return clean_text(h1.get_text(" "))

    return ""


def find_criterion(text: str) -> str:
    match = CRITERION_RE.search(text)

    if not match:
        return ""

    return clean_text(match.group(0)).upper().replace(" ", "-")


def extract_counted_links(
    soup: BeautifulSoup,
    required_path_prefixes: List[str],
    source_url: str,
) -> pd.DataFrame:
    rows = []
    seen_urls = set()

    for link in soup.find_all("a", href=True):
        href = clean_text(link.get("href"))
        full_url = absolute_url(href, source_url)
        path = url_path(full_url)

        if not any(path.startswith(prefix) for prefix in required_path_prefixes):
            continue

        parsed = parse_counted_label(link.get_text(" "))

        if parsed is None:
            continue

        if full_url in seen_urls:
            continue

        seen_urls.add(full_url)

        rows.append(
            {
                "name": parsed["name"],
                "count": parsed["count"],
                "source_list_text": parsed["raw_text"],
                "url": full_url,
                "source_index_url": source_url,
            }
        )

    return pd.DataFrame(rows)


def scrape_product_categories(
    session: requests.Session,
    sleep_seconds: float,
    timeout: int,
    use_cache: bool,
) -> pd.DataFrame:
    soup = get_soup(
        session=session,
        url=PRODUCTS_AZ_URL,
        sleep_seconds=sleep_seconds,
        timeout=timeout,
        use_cache=use_cache,
    )

    categories_df = extract_counted_links(
        soup=soup,
        required_path_prefixes=["/en/productworld/"],
        source_url=PRODUCTS_AZ_URL,
    )

    if categories_df.empty:
        return categories_df

    categories_df = categories_df.rename(
        columns={
            "name": "category_name",
            "count": "category_count",
            "url": "category_url",
        }
    )

    categories_df["certification"] = "Blue Angel"
    categories_df["registry_section"] = "Products A-Z"

    categories_df = categories_df[
        [
            "certification",
            "registry_section",
            "category_name",
            "category_count",
            "category_url",
            "source_index_url",
            "source_list_text",
        ]
    ]

    return categories_df.sort_values(["category_name", "category_url"]).reset_index(drop=True)


def parse_items_count_from_page_text(page_text: str) -> Optional[int]:
    match = re.search(r"\bItems:\s*([0-9]+)\b", page_text, re.IGNORECASE)

    if not match:
        return None

    return int(match.group(1))


def extract_filter_values_from_lines(lines: List[str], section_name: str) -> List[str]:
    values = []
    inside = False

    stop_sections = {
        "category",
        "manufacturer",
        "brand",
        "commercial/private use",
        "basic award criteria",
        "save list:",
        "items:",
        "benefits to the environment",
    }

    for line in lines:
        line_clean = clean_text(line)
        line_key = line_clean.lower()

        if not line_clean:
            continue

        if line_key == section_name.lower():
            inside = True
            continue

        if inside:
            if any(line_key == stop for stop in stop_sections if stop != section_name.lower()):
                break

            if line_key.startswith("items:"):
                break

            if line_key.startswith("save list"):
                break

            if line_clean not in values:
                values.append(line_clean)

    return values


def parse_category_page_products(
    session: requests.Session,
    category_row: pd.Series,
    sleep_seconds: float,
    timeout: int,
    use_cache: bool,
) -> Dict[str, object]:
    category_url = str(category_row["category_url"])

    soup = get_soup(
        session=session,
        url=category_url,
        sleep_seconds=sleep_seconds,
        timeout=timeout,
        use_cache=use_cache,
    )

    page_title = get_h1(soup)
    page_text_multiline = clean_multiline_text(soup.get_text("\n"))
    page_text_single_line = clean_text(soup.get_text(" "))

    page_lines = [line.strip() for line in page_text_multiline.splitlines() if line.strip()]

    criterion = find_criterion(page_title) or find_criterion(page_text_single_line)
    items_count = parse_items_count_from_page_text(page_text_single_line)

    category_filter_values = extract_filter_values_from_lines(page_lines, "Category")
    manufacturer_filter_values = extract_filter_values_from_lines(page_lines, "Manufacturer")

    products = []
    seen_product_urls = set()

    for link in soup.find_all("a", href=True):
        href = clean_text(link.get("href"))
        product_url = absolute_url(href, category_url)
        path = url_path(product_url)

        if not path.startswith("/en/products/"):
            continue

        raw_listing_text = clean_text(link.get_text(" "))

        if not raw_listing_text:
            continue

        if product_url in seen_product_urls:
            continue

        seen_product_urls.add(product_url)

        products.append(
            {
                "certification": "Blue Angel",
                "registry_source": "Blue Angel product category page",
                "category_name": category_row["category_name"],
                "category_url": category_url,
                "category_page_title": page_title,
                "category_expected_count": category_row["category_count"],
                "category_items_count_on_page": items_count,
                "criterion": criterion,
                "category_filters": " | ".join(category_filter_values),
                "manufacturer_filters": " | ".join(manufacturer_filter_values),
                "product_listing_text": raw_listing_text,
                "product_url": product_url,
            }
        )

    return {
        "products": products,
        "category_metadata": {
            "certification": "Blue Angel",
            "category_name": category_row["category_name"],
            "category_url": category_url,
            "category_page_title": page_title,
            "category_expected_count": category_row["category_count"],
            "category_items_count_on_page": items_count,
            "criterion": criterion,
            "category_filters": " | ".join(category_filter_values),
            "manufacturer_filters": " | ".join(manufacturer_filter_values),
            "product_links_extracted": len(products),
        },
    }


def scrape_products_from_categories(
    session: requests.Session,
    categories_df: pd.DataFrame,
    sleep_seconds: float,
    timeout: int,
    use_cache: bool,
    max_categories: Optional[int],
) -> Dict[str, pd.DataFrame]:
    products = []
    category_metadata = []

    if max_categories is not None:
        categories_to_process = categories_df.head(max_categories)
    else:
        categories_to_process = categories_df

    for _, category_row in tqdm(
        categories_to_process.iterrows(),
        total=len(categories_to_process),
        desc="Scraping Blue Angel product categories",
    ):
        try:
            parsed = parse_category_page_products(
                session=session,
                category_row=category_row,
                sleep_seconds=sleep_seconds,
                timeout=timeout,
                use_cache=use_cache,
            )

            products.extend(parsed["products"])
            category_metadata.append(parsed["category_metadata"])

        except requests.RequestException as error:
            category_metadata.append(
                {
                    "certification": "Blue Angel",
                    "category_name": category_row["category_name"],
                    "category_url": category_row["category_url"],
                    "category_page_title": "",
                    "category_expected_count": category_row["category_count"],
                    "category_items_count_on_page": None,
                    "criterion": "",
                    "category_filters": "",
                    "manufacturer_filters": "",
                    "product_links_extracted": 0,
                    "error": str(error),
                }
            )

    products_df = pd.DataFrame(products)
    category_metadata_df = pd.DataFrame(category_metadata)

    if not products_df.empty:
        products_df = products_df.drop_duplicates(
            subset=["product_url", "category_name"],
            keep="first",
        ).reset_index(drop=True)

        products_df["product_slug"] = products_df["product_url"].apply(
            lambda value: url_path(str(value)).split("/")[-1]
        )

    return {
        "products": products_df,
        "category_metadata": category_metadata_df,
    }


def scrape_companies(
    session: requests.Session,
    sleep_seconds: float,
    timeout: int,
    use_cache: bool,
) -> pd.DataFrame:
    soup = get_soup(
        session=session,
        url=COMPANIES_AZ_URL,
        sleep_seconds=sleep_seconds,
        timeout=timeout,
        use_cache=use_cache,
    )

    companies_df = extract_counted_links(
        soup=soup,
        required_path_prefixes=["/en/companies/"],
        source_url=COMPANIES_AZ_URL,
    )

    if companies_df.empty:
        return companies_df

    companies_df = companies_df.rename(
        columns={
            "name": "company_name",
            "count": "company_product_count",
            "url": "company_url",
        }
    )

    companies_df["certification"] = "Blue Angel"
    companies_df["registry_section"] = "Companies A-Z"

    companies_df = companies_df[
        [
            "certification",
            "registry_section",
            "company_name",
            "company_product_count",
            "company_url",
            "source_index_url",
            "source_list_text",
        ]
    ]

    return companies_df.sort_values(["company_name", "company_url"]).reset_index(drop=True)


def scrape_brands(
    session: requests.Session,
    sleep_seconds: float,
    timeout: int,
    use_cache: bool,
) -> pd.DataFrame:
    soup = get_soup(
        session=session,
        url=BRANDS_AZ_URL,
        sleep_seconds=sleep_seconds,
        timeout=timeout,
        use_cache=use_cache,
    )

    brands_df = extract_counted_links(
        soup=soup,
        required_path_prefixes=["/en/brand/"],
        source_url=BRANDS_AZ_URL,
    )

    if brands_df.empty:
        return brands_df

    brands_df = brands_df.rename(
        columns={
            "name": "brand_name",
            "count": "brand_product_count",
            "url": "brand_url",
        }
    )

    brands_df["certification"] = "Blue Angel"
    brands_df["registry_section"] = "Brands A-Z"

    brands_df = brands_df[
        [
            "certification",
            "registry_section",
            "brand_name",
            "brand_product_count",
            "brand_url",
            "source_index_url",
            "source_list_text",
        ]
    ]

    return brands_df.sort_values(["brand_name", "brand_url"]).reset_index(drop=True)


def extract_brand_from_product_detail_lines(lines: List[str]) -> str:
    for line in lines:
        line_clean = clean_text(line)

        if line_clean.lower().startswith("brand:"):
            return clean_text(line_clean.split(":", 1)[1])

    return ""


def extract_company_from_product_detail_lines(lines: List[str], brand: str) -> str:
    if not brand:
        return ""

    for index, line in enumerate(lines):
        line_clean = clean_text(line)

        if line_clean.lower().startswith("brand:"):
            for next_line in lines[index + 1 : index + 8]:
                next_clean = clean_text(next_line)

                if not next_clean:
                    continue

                if next_clean.lower().startswith("image"):
                    continue

                if next_clean == brand:
                    continue

                if next_clean.lower().startswith("more products"):
                    break

                return next_clean

    return ""


def extract_product_information(lines: List[str]) -> str:
    start_index = None
    end_index = None

    for index, line in enumerate(lines):
        if clean_text(line).lower() == "product information of the company:":
            start_index = index + 1
            break

    if start_index is None:
        return ""

    end_markers = [
        "product information (pdf)",
        "more information about the product",
        "brand:",
        "more products for current selection",
        "good for me. good for the environment.",
    ]

    for index in range(start_index, len(lines)):
        line_key = clean_text(lines[index]).lower()

        if any(marker in line_key for marker in end_markers):
            end_index = index
            break

    if end_index is None:
        end_index = min(len(lines), start_index + 20)

    info_lines = [clean_text(line) for line in lines[start_index:end_index]]
    info_lines = [line for line in info_lines if line]

    return " ".join(info_lines)


def scrape_product_detail(
    session: requests.Session,
    product_url: str,
    sleep_seconds: float,
    timeout: int,
    use_cache: bool,
) -> Dict[str, object]:
    soup = get_soup(
        session=session,
        url=product_url,
        sleep_seconds=sleep_seconds,
        timeout=timeout,
        use_cache=use_cache,
    )

    title = get_h1(soup)
    text_multiline = clean_multiline_text(soup.get_text("\n"))
    lines = [line.strip() for line in text_multiline.splitlines() if line.strip()]
    full_text = clean_text(soup.get_text(" "))

    brand = extract_brand_from_product_detail_lines(lines)
    company = extract_company_from_product_detail_lines(lines, brand)
    product_information = extract_product_information(lines)

    criterion = find_criterion(full_text)
    country = ""

    for index, line in enumerate(lines):
        if company and clean_text(line) == company:
            possible_address_lines = lines[index + 1 : index + 6]

            for possible_line in possible_address_lines:
                possible_clean = clean_text(possible_line)

                if possible_clean in {"Germany", "Switzerland", "Austria", "China", "Netherlands", "France", "Italy", "United Kingdom", "United States"}:
                    country = possible_clean
                    break

            break

    return {
        "product_url": product_url,
        "product_title_detail": title,
        "brand_detail": brand,
        "company_detail": company,
        "company_country_detail": country,
        "criterion_detail": criterion,
        "product_information_detail": product_information,
    }


def enrich_products_with_details(
    session: requests.Session,
    products_df: pd.DataFrame,
    sleep_seconds: float,
    timeout: int,
    use_cache: bool,
    max_product_details: Optional[int],
) -> pd.DataFrame:
    if products_df.empty:
        return products_df

    unique_product_urls = products_df["product_url"].dropna().drop_duplicates().tolist()

    if max_product_details is not None:
        unique_product_urls = unique_product_urls[:max_product_details]

    detail_rows = []

    for product_url in tqdm(unique_product_urls, desc="Scraping Blue Angel product details"):
        try:
            detail_rows.append(
                scrape_product_detail(
                    session=session,
                    product_url=product_url,
                    sleep_seconds=sleep_seconds,
                    timeout=timeout,
                    use_cache=use_cache,
                )
            )
        except requests.RequestException as error:
            detail_rows.append(
                {
                    "product_url": product_url,
                    "product_title_detail": "",
                    "brand_detail": "",
                    "company_detail": "",
                    "company_country_detail": "",
                    "criterion_detail": "",
                    "product_information_detail": "",
                    "detail_error": str(error),
                }
            )

    details_df = pd.DataFrame(detail_rows)

    return products_df.merge(details_df, on="product_url", how="left")


def save_outputs(
    categories_df: pd.DataFrame,
    category_metadata_df: pd.DataFrame,
    products_df: pd.DataFrame,
    companies_df: pd.DataFrame,
    brands_df: pd.DataFrame,
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    categories_csv = OUTPUT_DIR / "blue_angel_product_categories.csv"
    category_metadata_csv = OUTPUT_DIR / "blue_angel_category_metadata.csv"
    products_csv = OUTPUT_DIR / "blue_angel_products.csv"
    companies_csv = OUTPUT_DIR / "blue_angel_companies.csv"
    brands_csv = OUTPUT_DIR / "blue_angel_brands.csv"
    excel_path = OUTPUT_DIR / "blue_angel_registry.xlsx"

    categories_df.to_csv(categories_csv, index=False, encoding="utf-8-sig")
    category_metadata_df.to_csv(category_metadata_csv, index=False, encoding="utf-8-sig")
    products_df.to_csv(products_csv, index=False, encoding="utf-8-sig")
    companies_df.to_csv(companies_csv, index=False, encoding="utf-8-sig")
    brands_df.to_csv(brands_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        categories_df.to_excel(writer, sheet_name="product_categories", index=False)
        category_metadata_df.to_excel(writer, sheet_name="category_metadata", index=False)
        products_df.to_excel(writer, sheet_name="products", index=False)
        companies_df.to_excel(writer, sheet_name="companies", index=False)
        brands_df.to_excel(writer, sheet_name="brands", index=False)

    print("")
    print("Saved files:")
    print(f"- {categories_csv}")
    print(f"- {category_metadata_csv}")
    print(f"- {products_csv}")
    print(f"- {companies_csv}")
    print(f"- {brands_csv}")
    print(f"- {excel_path}")


def build_registry(
    sleep_seconds: float,
    timeout: int,
    use_cache: bool,
    max_categories: Optional[int],
    include_product_details: bool,
    max_product_details: Optional[int],
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    print("Scraping Blue Angel official registry...")
    print(f"Products A-Z: {PRODUCTS_AZ_URL}")
    print(f"Companies A-Z: {COMPANIES_AZ_URL}")
    print(f"Brands A-Z: {BRANDS_AZ_URL}")
    print("")

    categories_df = scrape_product_categories(
        session=session,
        sleep_seconds=sleep_seconds,
        timeout=timeout,
        use_cache=use_cache,
    )

    print(f"Product categories found: {len(categories_df)}")

    product_results = scrape_products_from_categories(
        session=session,
        categories_df=categories_df,
        sleep_seconds=sleep_seconds,
        timeout=timeout,
        use_cache=use_cache,
        max_categories=max_categories,
    )

    products_df = product_results["products"]
    category_metadata_df = product_results["category_metadata"]

    print(f"Product listing rows extracted: {len(products_df)}")

    if not products_df.empty:
        print(f"Unique product URLs extracted: {products_df['product_url'].nunique()}")

    if include_product_details:
        products_df = enrich_products_with_details(
            session=session,
            products_df=products_df,
            sleep_seconds=sleep_seconds,
            timeout=timeout,
            use_cache=use_cache,
            max_product_details=max_product_details,
        )

        print("Product detail enrichment completed.")

    companies_df = scrape_companies(
        session=session,
        sleep_seconds=sleep_seconds,
        timeout=timeout,
        use_cache=use_cache,
    )

    print(f"Companies found: {len(companies_df)}")

    brands_df = scrape_brands(
        session=session,
        sleep_seconds=sleep_seconds,
        timeout=timeout,
        use_cache=use_cache,
    )

    print(f"Brands found: {len(brands_df)}")

    save_outputs(
        categories_df=categories_df,
        category_metadata_df=category_metadata_df,
        products_df=products_df,
        companies_df=companies_df,
        brands_df=brands_df,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a local Blue Angel registry dataset from official Blue Angel public pages."
    )

    parser.add_argument(
        "--sleep",
        type=float,
        default=0.4,
        help="Delay between HTTP requests in seconds. Default: 0.4",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="HTTP timeout in seconds. Default: 20",
    )

    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable local HTML cache.",
    )

    parser.add_argument(
        "--max-categories",
        type=int,
        default=None,
        help="Optional maximum number of product categories to scrape. Useful for testing.",
    )

    parser.add_argument(
        "--include-product-details",
        action="store_true",
        help="Also visit individual product detail pages. This can be slow on the full registry.",
    )

    parser.add_argument(
        "--max-product-details",
        type=int,
        default=None,
        help="Optional maximum number of product detail pages to scrape. Useful for testing.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    build_registry(
        sleep_seconds=args.sleep,
        timeout=args.timeout,
        use_cache=not args.no_cache,
        max_categories=args.max_categories,
        include_product_details=args.include_product_details,
        max_product_details=args.max_product_details,
    )


if __name__ == "__main__":
    main()