import argparse
import hashlib
import random
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup


DEFAULT_CONFIGURATOR_DATASET = Path("Dataset_Enhanced_LEME_Paolo_Rubino.xlsx")
DEFAULT_OUTPUT_DIR = Path("data") / "certifications" / "supplier_discovery"

EXCEL_ILLEGAL_CHARACTERS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


CONFIGURATOR_COLUMN_CANDIDATES = {
    "industry": ["Industry", "industry"],
    "country": ["Country", "country"],
    "company": ["Company", "company", "azienda"],
    "product": ["Product", "product", "prodotto"],
    "configurator_url": [
        "Configurator URL",
        "configurator_url",
        "ConfiguratorURL",
        "url",
    ],
    "alternative_url": [
        "Configurator URL alternativa",
        "Configurator URL alternativa ",
        "alternative_url",
        "Configurator URL alternative",
    ],
    "database_detail_url": [
        "Database detail URL",
        "database_detail_url",
        "detail_url",
    ],
}


SEARCH_QUERY_TEMPLATES = [
    '"{company}" "supplier list"',
    '"{company}" "factory list"',
    '"{company}" "supplier disclosure"',
    '"{company}" "supply chain disclosure"',
    '"{company}" "modern slavery statement"',
    '"{company}" "sustainability report" suppliers',
    '"{company}" "responsible sourcing report"',
    '"{company}" "manufacturing partners"',
    '"{company}" "supplier code of conduct"',
    '"{company}" "sourcing" "suppliers"',
    'site:opensupplyhub.org "{company}"',
]


SOURCE_TYPE_KEYWORDS = {
    "supplier_list": [
        "supplier list",
        "suppliers list",
        "list of suppliers",
        "supplier disclosure",
        "supply chain disclosure",
        "supplier directory",
        "supplier database",
    ],
    "factory_list": [
        "factory list",
        "factory disclosure",
        "manufacturing sites",
        "manufacturing facilities",
        "factory disclosure list",
        "facility list",
        "facilities list",
        "production sites",
        "production facilities",
    ],
    "modern_slavery_statement": [
        "modern slavery statement",
        "slavery statement",
        "human trafficking statement",
    ],
    "sustainability_report": [
        "sustainability report",
        "esg report",
        "annual report",
        "impact report",
        "responsibility report",
        "corporate responsibility report",
        "csr report",
        "sustainability",
    ],
    "responsible_sourcing": [
        "responsible sourcing",
        "responsible procurement",
        "supplier code of conduct",
        "supplier standards",
        "sourcing policy",
        "ethical sourcing",
        "procurement policy",
    ],
    "open_supply_hub": [
        "opensupplyhub",
        "open supply hub",
    ],
    "supply_chain_page": [
        "supply chain",
        "sourcing",
        "suppliers",
        "manufacturing partners",
        "responsible supply chain",
        "traceability",
    ],
}


HIGH_VALUE_KEYWORDS = [
    "supplier list",
    "factory list",
    "supply chain disclosure",
    "supplier disclosure",
    "modern slavery statement",
    "manufacturing facilities",
    "manufacturing partners",
    "supplier code of conduct",
    "responsible sourcing",
    "ethical sourcing",
    "open supply hub",
]


OFFICIAL_COMMON_PATHS = [
    "/sustainability",
    "/en/sustainability",
    "/sustainability/",
    "/en/sustainability/",
    "/responsibility",
    "/en/responsibility",
    "/corporate-responsibility",
    "/social-responsibility",
    "/csr",
    "/esg",
    "/impact",
    "/supply-chain",
    "/en/supply-chain",
    "/suppliers",
    "/en/suppliers",
    "/supplier",
    "/supplier-list",
    "/factory-list",
    "/factory-disclosure",
    "/manufacturing",
    "/manufacturing-partners",
    "/responsible-sourcing",
    "/ethical-sourcing",
    "/sourcing",
    "/procurement",
    "/supplier-code-of-conduct",
    "/code-of-conduct",
    "/modern-slavery-statement",
    "/modern-slavery",
    "/downloads",
    "/download",
    "/reports",
    "/annual-report",
    "/sustainability-report",
    "/investors",
    "/investor-relations",
    "/about/sustainability",
    "/about-us/sustainability",
    "/company/sustainability",
    "/corporate/sustainability",
]


NEGATIVE_DOMAINS = [
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "x.com",
    "twitter.com",
    "tiktok.com",
    "pinterest.com",
    "glassdoor.com",
    "indeed.com",
    "wikipedia.org",
    "bloomberg.com",
    "crunchbase.com",
    "zoominfo.com",
]


NEGATIVE_KEYWORDS = [
    "jobs",
    "careers",
    "hiring",
    "coupon",
    "discount",
    "sale",
    "stock price",
    "press release",
    "newsroom",
    "facebook",
    "instagram",
    "linkedin",
    "youtube",
]


GENERIC_OR_UNHELPFUL_DOMAINS = [
    "configurators.com",
    "mconfigurators.com",
    "lemanoosh.com",
    "wikipedia.org",
    "google.com",
    "bing.com",
    "duckduckgo.com",
]


def strip_excel_illegal_characters(value: object) -> str:
    if value is None:
        return ""

    text = str(value)
    text = EXCEL_ILLEGAL_CHARACTERS_RE.sub("", text)
    return text


def clean_text(value: object) -> str:
    if value is None:
        return ""

    if isinstance(value, float) and pd.isna(value):
        return ""

    text = strip_excel_illegal_characters(value)
    text = text.replace("\u00a0", " ")
    text = text.replace("\ufeff", "")
    text = text.replace("☻", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def truncate_for_excel(value: object, max_length: int = 3000) -> str:
    text = clean_text(value)

    if len(text) <= max_length:
        return text

    return text[:max_length] + " [...]"


def sanitize_dataframe_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    sanitized_df = df.copy()

    for column in sanitized_df.columns:
        if sanitized_df[column].dtype == "object":
            sanitized_df[column] = sanitized_df[column].apply(truncate_for_excel)

    return sanitized_df


def normalize_column_name(value: object) -> str:
    text = clean_text(value).casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text.strip()


def normalize_for_matching(value: object) -> str:
    text = clean_text(value).casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def make_hash_key(*values: object) -> str:
    raw_key = "|".join(clean_text(value) for value in values)
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def choose_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    lookup = {}

    for column in df.columns:
        normalized = normalize_column_name(column)

        if normalized and normalized not in lookup:
            lookup[normalized] = column

    for candidate in candidates:
        normalized_candidate = normalize_column_name(candidate)

        if normalized_candidate in lookup:
            return lookup[normalized_candidate]

    for candidate in candidates:
        normalized_candidate = normalize_column_name(candidate)

        for normalized_column, original_column in lookup.items():
            if normalized_candidate and normalized_candidate in normalized_column:
                return original_column

    return None


def get_row_value(row: pd.Series, column: Optional[str]) -> str:
    if not column:
        return ""

    if column not in row:
        return ""

    return clean_text(row[column])


def find_configurator_dataset(default_path: Path) -> Path:
    if default_path.exists():
        return default_path

    candidates = sorted(Path(".").glob("*Dataset*Enhanced*LEME*Paolo*Rubino*.xlsx"))

    if candidates:
        return candidates[0]

    candidates = sorted(Path(".").glob("*.xlsx"))

    for candidate in candidates:
        if "Dataset" in candidate.name:
            return candidate

    raise FileNotFoundError(
        "Configurator dataset not found. Pass --configurator-dataset explicitly."
    )


def read_configurator_dataset(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, dtype=str)
    df.columns = [clean_text(column) for column in df.columns]
    return df


def safe_url_for_parsing(url: str) -> str:
    url = clean_text(url)

    if not url:
        return ""

    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        return "https://" + url

    return url


def extract_domain(url: str) -> str:
    url = clean_text(url)

    if not url:
        return ""

    try:
        parsed = urlparse(safe_url_for_parsing(url))
        domain = clean_text(parsed.netloc).casefold()
    except Exception:
        domain = ""

    domain = re.sub(r"^www\.", "", domain, flags=re.IGNORECASE)
    domain = domain.split(":")[0]

    return domain


def extract_url_path(url: str) -> str:
    try:
        parsed = urlparse(safe_url_for_parsing(url))
        return clean_text(parsed.path)
    except Exception:
        return ""


def is_generic_or_unhelpful_domain(domain: str) -> bool:
    domain = clean_text(domain).casefold()
    domain = re.sub(r"^www\.", "", domain)

    if not domain:
        return True

    for bad_domain in GENERIC_OR_UNHELPFUL_DOMAINS:
        bad_domain = bad_domain.casefold()
        bad_domain = re.sub(r"^www\.", "", bad_domain)

        if domain == bad_domain or domain.endswith("." + bad_domain):
            return True

    return False


def domain_matches_company_domain(result_domain: str, company_domains: List[str]) -> bool:
    result_domain = clean_text(result_domain).casefold()
    result_domain = re.sub(r"^www\.", "", result_domain)

    if not result_domain:
        return False

    for company_domain in company_domains:
        company_domain = clean_text(company_domain).casefold()
        company_domain = re.sub(r"^www\.", "", company_domain)

        if not company_domain:
            continue

        if result_domain == company_domain:
            return True

        if result_domain.endswith("." + company_domain):
            return True

    return False


def normalize_company_name_for_search(company_name: str) -> str:
    company_name = clean_text(company_name)

    company_name = re.sub(r"\.(com|de|it|fr|co|uk|nl|ch|eu)$", "", company_name, flags=re.IGNORECASE)
    company_name = company_name.replace("+", " ")
    company_name = re.sub(r"\s+", " ", company_name)

    return company_name.strip()


def decode_duckduckgo_url(url: str) -> str:
    url = clean_text(url)

    if not url:
        return ""

    if url.startswith("//"):
        url = "https:" + url

    if "duckduckgo.com/l/" in url or url.startswith("/l/"):
        parsed = urlparse(safe_url_for_parsing(url))
        params = parse_qs(parsed.query)
        uddg = params.get("uddg", [""])[0]

        if uddg:
            return unquote(uddg)

    return url


def build_http_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.8,*/*;q=0.7",
        }
    )
    return session


def fetch_url(
    session: requests.Session,
    url: str,
    timeout: int,
    max_bytes: int = 1_500_000,
) -> Dict[str, object]:
    url = clean_text(url)

    if not url:
        return {
            "ok": False,
            "status_code": "",
            "final_url": "",
            "content_type": "",
            "text": "",
            "error": "empty_url",
        }

    try:
        response = session.get(
            safe_url_for_parsing(url),
            timeout=timeout,
            allow_redirects=True,
            stream=True,
        )

        content_type = clean_text(response.headers.get("Content-Type", ""))
        content = b""

        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue

            content += chunk

            if len(content) >= max_bytes:
                break

        if "pdf" in content_type.lower() or response.url.lower().endswith(".pdf"):
            text = ""
        else:
            encoding = response.encoding or "utf-8"
            text = content.decode(encoding, errors="ignore")

        return {
            "ok": response.status_code < 400,
            "status_code": response.status_code,
            "final_url": response.url,
            "content_type": content_type,
            "text": text,
            "error": "",
        }

    except Exception as error:
        return {
            "ok": False,
            "status_code": "",
            "final_url": "",
            "content_type": "",
            "text": "",
            "error": str(error),
        }


def get_html_title(html: str) -> str:
    html = clean_text(html)

    if not html:
        return ""

    try:
        soup = BeautifulSoup(html, "lxml")
        title_node = soup.find("title")

        if title_node:
            return clean_text(title_node.get_text(" ", strip=True))
    except Exception:
        return ""

    return ""


def extract_visible_text_snippet(html: str, max_length: int = 500) -> str:
    html = clean_text(html)

    if not html:
        return ""

    try:
        soup = BeautifulSoup(html, "lxml")

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        text = clean_text(soup.get_text(" ", strip=True))

        return text[:max_length]
    except Exception:
        return ""


def source_keyword_found(text: str) -> bool:
    normalized_text = normalize_for_matching(text)

    if not normalized_text:
        return False

    for keyword in HIGH_VALUE_KEYWORDS:
        normalized_keyword = normalize_for_matching(keyword)

        if normalized_keyword and normalized_keyword in normalized_text:
            return True

    for keywords in SOURCE_TYPE_KEYWORDS.values():
        for keyword in keywords:
            normalized_keyword = normalize_for_matching(keyword)

            if normalized_keyword and normalized_keyword in normalized_text:
                return True

    return False


def infer_source_type(title: str, url: str, snippet: str) -> str:
    haystack = normalize_for_matching(f"{title} {url} {snippet}")

    best_type = "other_possible_source"
    best_hits = 0

    for source_type, keywords in SOURCE_TYPE_KEYWORDS.items():
        hits = 0

        for keyword in keywords:
            normalized_keyword = normalize_for_matching(keyword)

            if normalized_keyword and normalized_keyword in haystack:
                hits += 1

        if hits > best_hits:
            best_hits = hits
            best_type = source_type

    return best_type


def score_source_candidate(
    company_name: str,
    company_domains: List[str],
    title: str,
    url: str,
    snippet: str,
    discovery_method: str,
    http_status: object = "",
) -> Dict[str, object]:
    result_domain = extract_domain(url)
    result_path = extract_url_path(url)

    normalized_company = normalize_for_matching(company_name)
    normalized_title = normalize_for_matching(title)
    normalized_url = normalize_for_matching(url)
    normalized_snippet = normalize_for_matching(snippet)

    haystack = f"{normalized_title} {normalized_url} {normalized_snippet}"

    score = 0
    reasons = []

    if discovery_method.startswith("official"):
        score += 30
        reasons.append("official_domain_discovery")

    if normalized_company and normalized_company in haystack:
        score += 18
        reasons.append("company_name_found_in_source")

    company_tokens = [
        token for token in normalized_company.split()
        if len(token) >= 4
    ]

    token_hits = sum(1 for token in company_tokens if token in haystack)

    if company_tokens:
        token_ratio = token_hits / len(company_tokens)

        if token_ratio >= 0.8:
            score += 12
            reasons.append("most_company_tokens_found")
        elif token_ratio >= 0.5:
            score += 7
            reasons.append("some_company_tokens_found")

    if domain_matches_company_domain(result_domain, company_domains):
        score += 35
        reasons.append("official_or_company_domain_match")

    if result_domain in NEGATIVE_DOMAINS or any(result_domain.endswith("." + domain) for domain in NEGATIVE_DOMAINS):
        score -= 35
        reasons.append("negative_domain")

    if url.lower().endswith(".pdf") or ".pdf" in url.lower():
        score += 12
        reasons.append("pdf_source")

    if any(normalize_for_matching(keyword) in haystack for keyword in HIGH_VALUE_KEYWORDS):
        score += 24
        reasons.append("high_value_supplier_keyword")

    source_type = infer_source_type(title, url, snippet)

    if source_type in {"supplier_list", "factory_list", "modern_slavery_statement"}:
        score += 22
        reasons.append(f"strong_source_type_{source_type}")
    elif source_type in {"sustainability_report", "responsible_sourcing", "open_supply_hub"}:
        score += 14
        reasons.append(f"useful_source_type_{source_type}")
    elif source_type == "supply_chain_page":
        score += 12
        reasons.append("supply_chain_page")

    for negative_keyword in NEGATIVE_KEYWORDS:
        normalized_negative_keyword = normalize_for_matching(negative_keyword)

        if normalized_negative_keyword in haystack:
            score -= 8
            reasons.append(f"negative_keyword_{negative_keyword}")

    if clean_text(http_status) and str(http_status).isdigit():
        status_code = int(http_status)

        if status_code < 400:
            score += 5
            reasons.append("url_fetch_success")
        elif status_code >= 400:
            score -= 12
            reasons.append(f"http_status_{status_code}")

    if "opensupplyhub" in result_domain:
        score += 18
        reasons.append("open_supply_hub_result")

    score = max(0, min(100, score))

    if score >= 75:
        confidence = "High"
    elif score >= 50:
        confidence = "Medium"
    elif score >= 30:
        confidence = "Low"
    else:
        confidence = "Very Low"

    return {
        "source_type": source_type,
        "source_score": score,
        "source_confidence": confidence,
        "score_reasons": " | ".join(reasons),
        "result_domain": result_domain,
        "result_path": result_path,
    }


def build_configurator_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    columns = {}

    for canonical_name, candidates in CONFIGURATOR_COLUMN_CANDIDATES.items():
        columns[canonical_name] = choose_column(df, candidates)

    if not columns.get("company"):
        raise ValueError("Could not identify Company column in configurator dataset.")

    return columns


def get_company_domains_for_row(row: pd.Series, columns: Dict[str, Optional[str]]) -> List[str]:
    urls = [
        get_row_value(row, columns.get("configurator_url")),
        get_row_value(row, columns.get("alternative_url")),
    ]

    domains = []

    for url in urls:
        domain = extract_domain(url)

        if not domain:
            continue

        if is_generic_or_unhelpful_domain(domain):
            continue

        if domain not in domains:
            domains.append(domain)

    return domains


def get_company_urls_for_row(row: pd.Series, columns: Dict[str, Optional[str]]) -> List[str]:
    urls = [
        get_row_value(row, columns.get("configurator_url")),
        get_row_value(row, columns.get("alternative_url")),
    ]

    cleaned_urls = []

    for url in urls:
        url = clean_text(url)

        if not url:
            continue

        domain = extract_domain(url)

        if not domain or is_generic_or_unhelpful_domain(domain):
            continue

        safe_url = safe_url_for_parsing(url)

        if safe_url not in cleaned_urls:
            cleaned_urls.append(safe_url)

    return cleaned_urls


def prepare_unique_companies(configurators_df: pd.DataFrame) -> pd.DataFrame:
    columns = build_configurator_columns(configurators_df)

    company_rows = []

    for index, row in configurators_df.iterrows():
        company_name = get_row_value(row, columns.get("company"))

        if not company_name:
            continue

        product = get_row_value(row, columns.get("product"))
        industry = get_row_value(row, columns.get("industry"))
        country = get_row_value(row, columns.get("country"))
        domains = get_company_domains_for_row(row, columns)
        urls = get_company_urls_for_row(row, columns)

        company_rows.append(
            {
                "configurator_row_number": index + 2,
                "company_name": company_name,
                "company_name_normalized": normalize_for_matching(company_name),
                "product": product,
                "industry": industry,
                "country": country,
                "company_domains": " | ".join(domains),
                "company_urls": " | ".join(urls),
            }
        )

    raw_company_df = pd.DataFrame(company_rows)

    if raw_company_df.empty:
        return raw_company_df

    grouped_df = (
        raw_company_df.groupby(
            [
                "company_name",
                "company_name_normalized",
            ],
            dropna=False,
        )
        .agg(
            configurator_rows=("configurator_row_number", "count"),
            configurator_row_numbers=(
                "configurator_row_number",
                lambda values: " | ".join(str(value) for value in sorted(set(values))),
            ),
            products=(
                "product",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:80]
                ),
            ),
            industries=(
                "industry",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:30]
                ),
            ),
            countries=(
                "country",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:30]
                ),
            ),
            company_domains=(
                "company_domains",
                lambda values: " | ".join(
                    sorted(
                        set(
                            domain
                            for value in values
                            for domain in clean_text(value).split(" | ")
                            if clean_text(domain)
                        )
                    )
                ),
            ),
            company_urls=(
                "company_urls",
                lambda values: " | ".join(
                    sorted(
                        set(
                            url
                            for value in values
                            for url in clean_text(value).split(" | ")
                            if clean_text(url)
                        )
                    )
                ),
            ),
        )
        .reset_index()
    )

    return grouped_df.sort_values("company_name_normalized").reset_index(drop=True)


def build_queries_for_company(company_name: str) -> List[str]:
    company_name = normalize_company_name_for_search(company_name)

    queries = []

    for template in SEARCH_QUERY_TEMPLATES:
        query = template.format(company=company_name)
        query = clean_text(query)

        if query and query not in queries:
            queries.append(query)

    return queries


def search_bing(
    session: requests.Session,
    query: str,
    max_results: int,
    timeout: int,
) -> Tuple[List[Dict[str, object]], str]:
    url = f"https://www.bing.com/search?q={quote_plus(query)}"

    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
    except Exception as error:
        return [], str(error)

    soup = BeautifulSoup(response.text, "lxml")
    results = []

    result_nodes = soup.select("li.b_algo")

    for position, node in enumerate(result_nodes, start=1):
        title_node = node.select_one("h2 a")
        snippet_node = node.select_one(".b_caption p")

        if not title_node:
            continue

        title = clean_text(title_node.get_text(" ", strip=True))
        href = clean_text(title_node.get("href", ""))
        snippet = clean_text(snippet_node.get_text(" ", strip=True)) if snippet_node else ""

        if not href:
            continue

        results.append(
            {
                "search_engine": "bing",
                "position": position,
                "title": title,
                "url": href,
                "display_url": href,
                "snippet": snippet,
            }
        )

        if len(results) >= max_results:
            break

    return results, ""


def search_duckduckgo(
    session: requests.Session,
    query: str,
    max_results: int,
    timeout: int,
) -> Tuple[List[Dict[str, object]], str]:
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"

    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
    except Exception as error:
        return [], str(error)

    soup = BeautifulSoup(response.text, "lxml")
    results = []

    result_nodes = soup.select(".result")

    for position, node in enumerate(result_nodes, start=1):
        title_node = node.select_one(".result__title a")
        snippet_node = node.select_one(".result__snippet")
        url_node = node.select_one(".result__url")

        if not title_node:
            continue

        title = clean_text(title_node.get_text(" ", strip=True))
        href = decode_duckduckgo_url(title_node.get("href", ""))
        snippet = clean_text(snippet_node.get_text(" ", strip=True)) if snippet_node else ""
        display_url = clean_text(url_node.get_text(" ", strip=True)) if url_node else ""

        if not href:
            continue

        results.append(
            {
                "search_engine": "duckduckgo",
                "position": position,
                "title": title,
                "url": href,
                "display_url": display_url,
                "snippet": snippet,
            }
        )

        if len(results) >= max_results:
            break

    return results, ""


def execute_search(
    session: requests.Session,
    query: str,
    search_engine: str,
    max_results_per_query: int,
    timeout: int,
) -> Tuple[List[Dict[str, object]], str]:
    if search_engine == "bing":
        return search_bing(
            session=session,
            query=query,
            max_results=max_results_per_query,
            timeout=timeout,
        )

    if search_engine == "duckduckgo":
        return search_duckduckgo(
            session=session,
            query=query,
            max_results=max_results_per_query,
            timeout=timeout,
        )

    raise ValueError(f"Unsupported search engine: {search_engine}")


def add_source_candidate(
    source_rows: List[Dict[str, object]],
    company_row: pd.Series,
    company_name: str,
    company_domains: List[str],
    discovery_method: str,
    title: str,
    url: str,
    snippet: str,
    query: str = "",
    search_engine: str = "",
    search_position: object = "",
    http_status: object = "",
    content_type: str = "",
    fetch_error: str = "",
) -> None:
    url = clean_text(url)

    if not url:
        return

    scoring = score_source_candidate(
        company_name=company_name,
        company_domains=company_domains,
        title=title,
        url=url,
        snippet=snippet,
        discovery_method=discovery_method,
        http_status=http_status,
    )

    source_rows.append(
        {
            "source_candidate_id": make_hash_key(
                company_name,
                discovery_method,
                query,
                search_engine,
                url,
            ),
            "company_name": company_name,
            "company_name_normalized": normalize_for_matching(company_name),
            "configurator_rows": clean_text(company_row.get("configurator_row_numbers", "")),
            "configurator_products": clean_text(company_row.get("products", "")),
            "industries": clean_text(company_row.get("industries", "")),
            "countries": clean_text(company_row.get("countries", "")),
            "company_domains": " | ".join(company_domains),
            "discovery_method": discovery_method,
            "query": query,
            "search_engine": search_engine,
            "search_position": search_position,
            "source_type": scoring["source_type"],
            "source_score": scoring["source_score"],
            "source_confidence": scoring["source_confidence"],
            "score_reasons": scoring["score_reasons"],
            "title": clean_text(title),
            "url": url,
            "result_domain": scoring["result_domain"],
            "result_path": scoring["result_path"],
            "display_url": url,
            "snippet": clean_text(snippet),
            "is_official_domain_match": domain_matches_company_domain(
                scoring["result_domain"],
                company_domains,
            ),
            "is_pdf": ".pdf" in url.lower() or url.lower().endswith(".pdf"),
            "http_status": http_status,
            "content_type": clean_text(content_type),
            "fetch_error": clean_text(fetch_error),
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    )


def discover_links_from_html(base_url: str, html: str, max_links: int) -> List[Dict[str, str]]:
    links = []

    if not html:
        return links

    try:
        soup = BeautifulSoup(html, "lxml")

        for anchor in soup.find_all("a", href=True):
            href = clean_text(anchor.get("href", ""))
            text = clean_text(anchor.get_text(" ", strip=True))
            title = clean_text(anchor.get("title", ""))

            absolute = urljoin(base_url, href)

            combined = f"{text} {title} {absolute}"

            if not source_keyword_found(combined):
                continue

            links.append(
                {
                    "url": absolute,
                    "link_text": text,
                    "title": title,
                }
            )

            if len(links) >= max_links:
                break

    except Exception:
        return links

    unique_links = []
    seen = set()

    for link in links:
        url = clean_text(link["url"])

        if url in seen:
            continue

        seen.add(url)
        unique_links.append(link)

    return unique_links


def parse_sitemap_urls(xml_text: str, base_url: str, max_urls: int) -> List[str]:
    urls = []

    if not xml_text:
        return urls

    loc_matches = re.findall(r"<loc>\s*(.*?)\s*</loc>", xml_text, flags=re.IGNORECASE)

    if loc_matches:
        for loc in loc_matches:
            loc = clean_text(loc)

            if not loc:
                continue

            if source_keyword_found(loc):
                urls.append(loc)

            if len(urls) >= max_urls:
                break
    else:
        url_matches = re.findall(r"https?://[^\s<>\"]+", xml_text)

        for url in url_matches:
            url = clean_text(url)

            if source_keyword_found(url):
                urls.append(url)

            if len(urls) >= max_urls:
                break

    unique_urls = []
    seen = set()

    for url in urls:
        url = urljoin(base_url, url)

        if url in seen:
            continue

        seen.add(url)
        unique_urls.append(url)

    return unique_urls


def homepage_urls_for_domain(domain: str) -> List[str]:
    domain = clean_text(domain)

    if not domain:
        return []

    candidates = [
        f"https://{domain}/",
        f"https://www.{domain}/",
        f"http://{domain}/",
        f"http://www.{domain}/",
    ]

    unique = []

    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)

    return unique


def discover_official_sources_for_company(
    session: requests.Session,
    company_row: pd.Series,
    args: argparse.Namespace,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    source_rows = []
    log_rows = []

    company_name = clean_text(company_row["company_name"])
    company_domains = [
        clean_text(domain)
        for domain in clean_text(company_row.get("company_domains", "")).split(" | ")
        if clean_text(domain)
    ]
    company_urls = [
        clean_text(url)
        for url in clean_text(company_row.get("company_urls", "")).split(" | ")
        if clean_text(url)
    ]

    if not company_domains:
        return source_rows, log_rows

    processed_urls = set()

    for domain in company_domains[: args.max_domains_per_company]:
        homepage_candidates = homepage_urls_for_domain(domain)

        for company_url in company_urls:
            if extract_domain(company_url) == domain and company_url not in homepage_candidates:
                homepage_candidates.insert(0, company_url)

        homepage_fetch = None
        homepage_url_used = ""

        for homepage_url in homepage_candidates:
            fetch_result = fetch_url(
                session=session,
                url=homepage_url,
                timeout=args.timeout,
            )

            log_rows.append(
                {
                    "company_name": company_name,
                    "method": "official_homepage_fetch",
                    "url": homepage_url,
                    "status_code": fetch_result.get("status_code", ""),
                    "content_type": fetch_result.get("content_type", ""),
                    "error_message": fetch_result.get("error", ""),
                    "created_at_utc": datetime.now(timezone.utc).isoformat(),
                }
            )

            if fetch_result["ok"]:
                homepage_fetch = fetch_result
                homepage_url_used = clean_text(fetch_result.get("final_url", homepage_url))
                break

        if homepage_fetch and homepage_fetch.get("text"):
            html = clean_text(homepage_fetch.get("text", ""))
            title = get_html_title(html)
            snippet = extract_visible_text_snippet(html)

            if source_keyword_found(f"{title} {homepage_url_used} {snippet}"):
                add_source_candidate(
                    source_rows=source_rows,
                    company_row=company_row,
                    company_name=company_name,
                    company_domains=company_domains,
                    discovery_method="official_homepage_keyword_match",
                    title=title or company_name,
                    url=homepage_url_used,
                    snippet=snippet,
                    http_status=homepage_fetch.get("status_code", ""),
                    content_type=homepage_fetch.get("content_type", ""),
                    fetch_error=homepage_fetch.get("error", ""),
                )

            discovered_links = discover_links_from_html(
                base_url=homepage_url_used,
                html=html,
                max_links=args.max_official_links_per_domain,
            )

            for link in discovered_links:
                candidate_url = clean_text(link["url"])

                if candidate_url in processed_urls:
                    continue

                processed_urls.add(candidate_url)

                add_source_candidate(
                    source_rows=source_rows,
                    company_row=company_row,
                    company_name=company_name,
                    company_domains=company_domains,
                    discovery_method="official_homepage_link",
                    title=link.get("link_text", "") or link.get("title", "") or candidate_url,
                    url=candidate_url,
                    snippet=link.get("title", ""),
                    http_status="",
                    content_type="",
                    fetch_error="",
                )

        for path in OFFICIAL_COMMON_PATHS[: args.max_common_paths_per_domain]:
            candidate_url = f"https://{domain}{path}"

            if candidate_url in processed_urls:
                continue

            processed_urls.add(candidate_url)

            fetch_result = fetch_url(
                session=session,
                url=candidate_url,
                timeout=args.timeout,
                max_bytes=500_000,
            )

            log_rows.append(
                {
                    "company_name": company_name,
                    "method": "official_common_path_fetch",
                    "url": candidate_url,
                    "status_code": fetch_result.get("status_code", ""),
                    "content_type": fetch_result.get("content_type", ""),
                    "error_message": fetch_result.get("error", ""),
                    "created_at_utc": datetime.now(timezone.utc).isoformat(),
                }
            )

            if not fetch_result["ok"]:
                continue

            final_url = clean_text(fetch_result.get("final_url", candidate_url))
            html = clean_text(fetch_result.get("text", ""))
            title = get_html_title(html) or candidate_url
            snippet = extract_visible_text_snippet(html)

            if source_keyword_found(f"{title} {final_url} {snippet}"):
                add_source_candidate(
                    source_rows=source_rows,
                    company_row=company_row,
                    company_name=company_name,
                    company_domains=company_domains,
                    discovery_method="official_common_path",
                    title=title,
                    url=final_url,
                    snippet=snippet,
                    http_status=fetch_result.get("status_code", ""),
                    content_type=fetch_result.get("content_type", ""),
                    fetch_error=fetch_result.get("error", ""),
                )

        for sitemap_url in [
            f"https://{domain}/sitemap.xml",
            f"https://www.{domain}/sitemap.xml",
        ][: args.max_sitemaps_per_domain]:
            fetch_result = fetch_url(
                session=session,
                url=sitemap_url,
                timeout=args.timeout,
                max_bytes=2_500_000,
            )

            log_rows.append(
                {
                    "company_name": company_name,
                    "method": "official_sitemap_fetch",
                    "url": sitemap_url,
                    "status_code": fetch_result.get("status_code", ""),
                    "content_type": fetch_result.get("content_type", ""),
                    "error_message": fetch_result.get("error", ""),
                    "created_at_utc": datetime.now(timezone.utc).isoformat(),
                }
            )

            if not fetch_result["ok"]:
                continue

            sitemap_urls = parse_sitemap_urls(
                xml_text=clean_text(fetch_result.get("text", "")),
                base_url=sitemap_url,
                max_urls=args.max_sitemap_urls_per_domain,
            )

            for sitemap_candidate_url in sitemap_urls:
                if sitemap_candidate_url in processed_urls:
                    continue

                processed_urls.add(sitemap_candidate_url)

                add_source_candidate(
                    source_rows=source_rows,
                    company_row=company_row,
                    company_name=company_name,
                    company_domains=company_domains,
                    discovery_method="official_sitemap_url",
                    title=sitemap_candidate_url,
                    url=sitemap_candidate_url,
                    snippet=sitemap_candidate_url,
                    http_status=fetch_result.get("status_code", ""),
                    content_type=fetch_result.get("content_type", ""),
                    fetch_error=fetch_result.get("error", ""),
                )

    return source_rows, log_rows


def discover_search_sources_for_company(
    session: requests.Session,
    company_row: pd.Series,
    args: argparse.Namespace,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    source_rows = []
    query_log_rows = []

    company_name = clean_text(company_row["company_name"])
    company_domains = [
        clean_text(domain)
        for domain in clean_text(company_row.get("company_domains", "")).split(" | ")
        if clean_text(domain)
    ]

    queries = build_queries_for_company(company_name)

    if args.max_queries_per_company is not None:
        queries = queries[: args.max_queries_per_company]

    search_engines = [
        clean_text(engine)
        for engine in args.search_engines.split(",")
        if clean_text(engine)
    ]

    duckduckgo_error_count = 0

    for query in queries:
        for search_engine in search_engines:
            if search_engine == "duckduckgo" and duckduckgo_error_count >= args.disable_duckduckgo_after_errors:
                query_log_rows.append(
                    {
                        "company_name": company_name,
                        "query": query,
                        "search_engine": search_engine,
                        "results_found": 0,
                        "error_message": "duckduckgo_disabled_after_repeated_errors",
                        "created_at_utc": datetime.now(timezone.utc).isoformat(),
                    }
                )
                continue

            started_at = datetime.now(timezone.utc).isoformat()

            results, error_message = execute_search(
                session=session,
                query=query,
                search_engine=search_engine,
                max_results_per_query=args.max_results_per_query,
                timeout=args.timeout,
            )

            if search_engine == "duckduckgo" and error_message:
                duckduckgo_error_count += 1

            query_log_rows.append(
                {
                    "company_name": company_name,
                    "query": query,
                    "search_engine": search_engine,
                    "results_found": len(results),
                    "error_message": error_message,
                    "started_at_utc": started_at,
                    "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                }
            )

            if error_message:
                print(f"  {search_engine} error for query {query}: {error_message}")
            else:
                print(f"  {search_engine}: {len(results)} results for query: {query}")

            for result in results:
                url = clean_text(result.get("url", ""))

                if not url:
                    continue

                title = clean_text(result.get("title", ""))
                snippet = clean_text(result.get("snippet", ""))

                scoring = score_source_candidate(
                    company_name=company_name,
                    company_domains=company_domains,
                    title=title,
                    url=url,
                    snippet=snippet,
                    discovery_method=f"search_{search_engine}",
                )

                if scoring["source_score"] < args.min_source_score:
                    continue

                add_source_candidate(
                    source_rows=source_rows,
                    company_row=company_row,
                    company_name=company_name,
                    company_domains=company_domains,
                    discovery_method=f"search_{search_engine}",
                    title=title,
                    url=url,
                    snippet=snippet,
                    query=query,
                    search_engine=search_engine,
                    search_position=result.get("position", ""),
                )

            sleep_time = args.delay + random.uniform(0, args.delay_jitter)
            time.sleep(sleep_time)

    return source_rows, query_log_rows


def discover_supplier_sources(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    configurator_dataset_path = find_configurator_dataset(
        Path(args.configurator_dataset)
    )

    print("Supplier source discovery started.")
    print(f"Configurator dataset: {configurator_dataset_path}")
    print(f"Output directory: {output_dir}")
    print(f"Discovery mode: {args.discovery_mode}")
    print(f"Search engines: {args.search_engines}")
    print("")

    configurators_df = read_configurator_dataset(configurator_dataset_path)
    unique_companies_df = prepare_unique_companies(configurators_df)

    if args.max_companies is not None:
        unique_companies_df = unique_companies_df.head(args.max_companies).copy()

    print(f"Configurator rows: {len(configurators_df)}")
    print(f"Unique companies to process: {len(unique_companies_df)}")
    print("")

    session = build_http_session()

    all_source_rows = []
    all_log_rows = []

    discovery_modes = [
        clean_text(mode)
        for mode in args.discovery_mode.split(",")
        if clean_text(mode)
    ]

    for company_index, company_row in unique_companies_df.iterrows():
        company_name = clean_text(company_row["company_name"])

        print(f"[{company_index + 1}/{len(unique_companies_df)}] {company_name}")

        if "official" in discovery_modes:
            official_rows, official_logs = discover_official_sources_for_company(
                session=session,
                company_row=company_row,
                args=args,
            )

            print(f"  official discovery: {len(official_rows)} candidates")

            all_source_rows.extend(official_rows)
            all_log_rows.extend(official_logs)

            time.sleep(args.delay + random.uniform(0, args.delay_jitter))

        if "search" in discovery_modes:
            search_rows, search_logs = discover_search_sources_for_company(
                session=session,
                company_row=company_row,
                args=args,
            )

            print(f"  search discovery: {len(search_rows)} candidates")

            all_source_rows.extend(search_rows)
            all_log_rows.extend(search_logs)

    sources_df = pd.DataFrame(all_source_rows)
    query_log_df = pd.DataFrame(all_log_rows)

    if not sources_df.empty:
        sources_df = sources_df[sources_df["source_score"].astype(float) >= args.min_source_score].copy()

        sources_df = sources_df.drop_duplicates(
            subset=[
                "company_name_normalized",
                "url",
            ],
            keep="first",
        ).reset_index(drop=True)

        sources_df = sources_df.sort_values(
            [
                "company_name_normalized",
                "source_score",
                "source_confidence",
            ],
            ascending=[True, False, True],
        ).reset_index(drop=True)

    company_summary_df = build_company_summary(
        unique_companies_df=unique_companies_df,
        sources_df=sources_df,
    )

    settings_df = pd.DataFrame(
        [
            {
                "setting": "configurator_dataset",
                "value": str(configurator_dataset_path),
            },
            {
                "setting": "discovery_mode",
                "value": args.discovery_mode,
            },
            {
                "setting": "search_engines",
                "value": args.search_engines,
            },
            {
                "setting": "max_companies",
                "value": args.max_companies,
            },
            {
                "setting": "max_queries_per_company",
                "value": args.max_queries_per_company,
            },
            {
                "setting": "max_results_per_query",
                "value": args.max_results_per_query,
            },
            {
                "setting": "min_source_score",
                "value": args.min_source_score,
            },
            {
                "setting": "created_at_utc",
                "value": datetime.now(timezone.utc).isoformat(),
            },
        ]
    )

    save_outputs(
        output_dir=output_dir,
        sources_df=sources_df,
        company_summary_df=company_summary_df,
        query_log_df=query_log_df,
        settings_df=settings_df,
    )

    print("")
    print("Supplier source discovery completed.")
    print(f"Sources kept: {len(sources_df)}")
    print(
        "Companies with at least one source: "
        f"{company_summary_df['sources_found'].astype(int).gt(0).sum() if not company_summary_df.empty else 0}"
    )


def build_company_summary(
    unique_companies_df: pd.DataFrame,
    sources_df: pd.DataFrame,
) -> pd.DataFrame:
    if unique_companies_df.empty:
        return pd.DataFrame()

    if sources_df.empty:
        summary_df = unique_companies_df.copy()
        summary_df["sources_found"] = 0
        summary_df["high_confidence_sources"] = 0
        summary_df["medium_confidence_sources"] = 0
        summary_df["best_source_score"] = 0
        summary_df["best_source_url"] = ""
        summary_df["best_source_title"] = ""
        summary_df["best_source_type"] = ""
        return summary_df

    source_summary = (
        sources_df.groupby(
            [
                "company_name",
                "company_name_normalized",
            ],
            dropna=False,
        )
        .agg(
            sources_found=("source_candidate_id", "count"),
            high_confidence_sources=(
                "source_confidence",
                lambda values: sum(1 for value in values if clean_text(value) == "High"),
            ),
            medium_confidence_sources=(
                "source_confidence",
                lambda values: sum(1 for value in values if clean_text(value) == "Medium"),
            ),
            best_source_score=("source_score", "max"),
        )
        .reset_index()
    )

    best_sources = []

    for _, group in sources_df.groupby("company_name_normalized"):
        best_row = group.sort_values(
            [
                "source_score",
            ],
            ascending=[False],
        ).iloc[0]

        best_sources.append(
            {
                "company_name_normalized": best_row["company_name_normalized"],
                "best_source_url": best_row["url"],
                "best_source_title": best_row["title"],
                "best_source_type": best_row["source_type"],
            }
        )

    best_sources_df = pd.DataFrame(best_sources)

    summary_df = unique_companies_df.merge(
        source_summary,
        on=[
            "company_name",
            "company_name_normalized",
        ],
        how="left",
    )

    summary_df = summary_df.merge(
        best_sources_df,
        on="company_name_normalized",
        how="left",
    )

    for column in [
        "sources_found",
        "high_confidence_sources",
        "medium_confidence_sources",
        "best_source_score",
    ]:
        summary_df[column] = summary_df[column].fillna(0).astype(int)

    for column in [
        "best_source_url",
        "best_source_title",
        "best_source_type",
    ]:
        summary_df[column] = summary_df[column].fillna("")

    return summary_df.sort_values(
        [
            "sources_found",
            "best_source_score",
            "company_name_normalized",
        ],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def save_outputs(
    output_dir: Path,
    sources_df: pd.DataFrame,
    company_summary_df: pd.DataFrame,
    query_log_df: pd.DataFrame,
    settings_df: pd.DataFrame,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    sources_df = sanitize_dataframe_for_excel(sources_df)
    company_summary_df = sanitize_dataframe_for_excel(company_summary_df)
    query_log_df = sanitize_dataframe_for_excel(query_log_df)
    settings_df = sanitize_dataframe_for_excel(settings_df)

    sources_csv = output_dir / "company_supplier_source_candidates.csv"
    company_summary_csv = output_dir / "company_supplier_source_summary.csv"
    query_log_csv = output_dir / "company_supplier_source_query_log.csv"
    settings_csv = output_dir / "company_supplier_source_settings.csv"
    excel_path = output_dir / "company_supplier_source_candidates.xlsx"

    sources_df.to_csv(sources_csv, index=False, encoding="utf-8-sig")
    company_summary_df.to_csv(company_summary_csv, index=False, encoding="utf-8-sig")
    query_log_df.to_csv(query_log_csv, index=False, encoding="utf-8-sig")
    settings_df.to_csv(settings_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        sources_df.to_excel(writer, sheet_name="source_candidates", index=False)
        company_summary_df.to_excel(writer, sheet_name="company_summary", index=False)
        query_log_df.to_excel(writer, sheet_name="query_log", index=False)
        settings_df.to_excel(writer, sheet_name="settings", index=False)

    print("")
    print("Saved files:")
    print(f"- {sources_csv}")
    print(f"- {company_summary_csv}")
    print(f"- {query_log_csv}")
    print(f"- {settings_csv}")
    print(f"- {excel_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Discover public supplier/factory/supply-chain sources for companies in the configurator dataset."
        )
    )

    parser.add_argument(
        "--configurator-dataset",
        default=str(DEFAULT_CONFIGURATOR_DATASET),
        help=f"Configurator dataset path. Default: {DEFAULT_CONFIGURATOR_DATASET}",
    )

    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory. Default: {DEFAULT_OUTPUT_DIR}",
    )

    parser.add_argument(
        "--discovery-mode",
        default="official",
        help="Comma-separated modes: official,search. Default: official.",
    )

    parser.add_argument(
        "--search-engines",
        default="bing",
        help="Comma-separated search engines: bing,duckduckgo. Default: bing.",
    )

    parser.add_argument(
        "--max-companies",
        type=int,
        default=None,
        help="Maximum companies to process. Default: all.",
    )

    parser.add_argument(
        "--max-domains-per-company",
        type=int,
        default=2,
        help="Maximum official domains per company. Default: 2.",
    )

    parser.add_argument(
        "--max-official-links-per-domain",
        type=int,
        default=35,
        help="Maximum relevant links extracted from official homepage. Default: 35.",
    )

    parser.add_argument(
        "--max-common-paths-per-domain",
        type=int,
        default=35,
        help="Maximum common official paths to test per domain. Default: 35.",
    )

    parser.add_argument(
        "--max-sitemaps-per-domain",
        type=int,
        default=2,
        help="Maximum sitemap URLs to test per domain. Default: 2.",
    )

    parser.add_argument(
        "--max-sitemap-urls-per-domain",
        type=int,
        default=50,
        help="Maximum relevant sitemap URLs kept per domain. Default: 50.",
    )

    parser.add_argument(
        "--max-queries-per-company",
        type=int,
        default=4,
        help="Maximum search queries per company when discovery-mode includes search. Default: 4.",
    )

    parser.add_argument(
        "--max-results-per-query",
        type=int,
        default=5,
        help="Maximum search results per query/search engine. Default: 5.",
    )

    parser.add_argument(
        "--min-source-score",
        type=int,
        default=35,
        help="Minimum source score to keep. Default: 35.",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="HTTP timeout in seconds. Default: 15.",
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=0.8,
        help="Base delay between companies/searches in seconds. Default: 0.8.",
    )

    parser.add_argument(
        "--delay-jitter",
        type=float,
        default=0.6,
        help="Random delay jitter in seconds. Default: 0.6.",
    )

    parser.add_argument(
        "--disable-duckduckgo-after-errors",
        type=int,
        default=3,
        help="Disable DuckDuckGo after N errors in the same company. Default: 3.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    discover_supplier_sources(args)


if __name__ == "__main__":
    main()