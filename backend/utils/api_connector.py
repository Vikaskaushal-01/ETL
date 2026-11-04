"""
REST API connector: pull records from a JSON API and turn them into a table, the way Fivetran's connector SDK
and Airbyte's Connector Builder do for HTTP sources.

  * Finds the records in the response on its own ("data", "results", "items", ... or any list of objects),
    or uses an explicit dot path such as "data.items".
  * Follows pagination: Link headers, "next" URLs / cursors in the body, or page / offset parameters.
  * Flattens nested objects into columns ("address.city") and keeps nested lists as JSON text.

Every request goes through the same public-URL guard as file downloads, and credentials are only sent to the
API's own host.
"""
import json
import logging
import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import pandas as pd

logger = logging.getLogger("etl_api_connector")

PAGINATION_TYPES = ("auto", "none", "page", "offset", "cursor", "link")
MAX_PAGES_LIMIT = 200
MAX_RECORDS = 500_000
RECORD_KEYS = ("data", "results", "items", "records", "rows", "entries", "objects", "value", "hits", "list", "elements")
NEXT_URL_PATHS = ("next", "next_url", "nextUrl", "links.next", "links.next.href", "_links.next.href", "paging.next",
                  "pagination.next", "pagination.next_url", "meta.next", "@odata.nextLink", "odata.nextLink")
CURSOR_PATHS = ("next_cursor", "nextCursor", "cursor", "meta.next_cursor", "pagination.next_cursor",
                "response_metadata.next_cursor", "paging.cursors.after", "next_page_token", "nextPageToken")
ALLOWED_HEADERS = {"authorization", "accept", "x-api-key", "api-key", "apikey", "x-auth-token", "user-agent"}


class ApiConnectorError(ValueError):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def _dig(obj, path: str):
    """Value at a dot path ('data.items'), or None."""
    for part in path.split("."):
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        elif isinstance(obj, list) and part.isdigit() and int(part) < len(obj):
            obj = obj[int(part)]
        else:
            return None
    return obj


def find_records(body, records_path: Optional[str] = None) -> tuple:
    """(records, path used). Records are a list of objects (scalars are wrapped as {'value': ...})."""
    if records_path:
        found = _dig(body, records_path.strip())
        if not isinstance(found, list):
            raise ApiConnectorError(f"'{records_path}' is not a list in the response.")
        return _as_rows(found), records_path.strip()
    if isinstance(body, list):
        return _as_rows(body), ""
    if not isinstance(body, dict):
        raise ApiConnectorError("The API did not return JSON objects.")
    for key in RECORD_KEYS:
        value = body.get(key)
        if isinstance(value, list):
            return _as_rows(value), key
        if isinstance(value, dict):  # e.g. {"data": {"items": [...]}}
            for inner in RECORD_KEYS:
                if isinstance(value.get(inner), list):
                    return _as_rows(value[inner]), f"{key}.{inner}"
    # Otherwise the largest list of objects anywhere at the first two levels
    best, best_path = None, None
    for key, value in body.items():
        candidates = [(key, value)] + ([(f"{key}.{k}", v) for k, v in value.items()] if isinstance(value, dict) else [])
        for path, candidate in candidates:
            if isinstance(candidate, list) and candidate and isinstance(candidate[0], dict):
                if best is None or len(candidate) > len(best):
                    best, best_path = candidate, path
    if best is not None:
        return _as_rows(best), best_path
    return [body], ""  # a single object is one record


def _as_rows(items: list) -> list:
    return [i if isinstance(i, dict) else {"value": i} for i in items]


def _with_params(url: str, **params) -> str:
    parts = urlparse(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({k: str(v) for k, v in params.items() if v is not None})
    return urlunparse(parts._replace(query=urlencode(query)))


def _link_next(header: str) -> Optional[str]:
    for part in (header or "").split(","):
        match = re.match(r'\s*<([^>]+)>\s*;(.*)', part)
        if match and re.search(r'rel="?next"?', match.group(2)):
            return match.group(1)
    return None


def _next_url_in_body(body, current: str) -> Optional[str]:
    if not isinstance(body, dict):
        return None
    for path in NEXT_URL_PATHS:
        value = _dig(body, path)
        if isinstance(value, str) and value.strip():
            value = value.strip()
            if value.startswith(("http://", "https://", "/", "?")):
                return urljoin(current, value)
    return None


def _cursor_in_body(body, cursor_path: Optional[str]) -> Optional[str]:
    if not isinstance(body, dict):
        return None
    for path in ([cursor_path] if cursor_path else CURSOR_PATHS):
        value = _dig(body, path)
        if isinstance(value, (str, int)) and str(value).strip() and not str(value).startswith(("http://", "https://")):
            return str(value)
    return None


def clean_headers(headers: Optional[dict]) -> dict:
    """Only well-known request headers (auth and accept) may be set by the caller."""
    out = {}
    for name, value in (headers or {}).items():
        name = str(name).strip()
        if name.lower() not in ALLOWED_HEADERS:
            raise ApiConnectorError(f"Header '{name}' is not allowed. Use one of: Authorization, Accept, X-API-Key.")
        if value is None or "\n" in str(value) or "\r" in str(value):
            raise ApiConnectorError(f"Header '{name}' has an invalid value.")
        out[name] = str(value)
    return out


def fetch_records(url: str, records_path: Optional[str] = None, pagination: Optional[dict] = None,
                  max_pages: int = 20, headers: Optional[dict] = None, get=None) -> dict:
    """
    Downloads every page (up to max_pages). `get(url, headers)` performs one request and returns an
    httpx-like response; it defaults to the redirect-safe public GET used for dataset downloads.
    """
    if get is None:
        from backend.api.upload import _get_public
        get = _get_public
    pagination = dict(pagination or {})
    ptype = (pagination.get("type") or "auto").lower()
    if ptype not in PAGINATION_TYPES:
        raise ApiConnectorError(f"Unknown pagination '{ptype}'. Use one of: {', '.join(PAGINATION_TYPES)}.")
    max_pages = max(1, min(int(max_pages or 1), MAX_PAGES_LIMIT))
    headers = clean_headers(headers)
    headers.setdefault("Accept", "application/json")

    page_param = pagination.get("page_param") or "page"
    offset_param = pagination.get("offset_param") or "offset"
    size_param = pagination.get("size_param") or ("limit" if ptype == "offset" else None)
    page_size = pagination.get("page_size")
    cursor_param = pagination.get("cursor_param") or "cursor"
    start_page = int(pagination.get("start_page", 1) or 1)

    first = url
    if ptype == "page":
        first = _with_params(url, **{page_param: start_page, **({size_param: page_size} if size_param and page_size else {})})
    elif ptype == "offset":
        first = _with_params(url, **{offset_param: 0, **({size_param: page_size} if size_param and page_size else {})})

    records, pages, used_path, seen, next_url, strategy = [], 0, None, set(), first, ptype
    page_no, offset = start_page, 0
    while next_url and pages < max_pages:
        if next_url in seen:
            break  # an API that keeps returning the same "next" link
        seen.add(next_url)
        try:
            response = get(next_url, headers)
        except ValueError as e:
            raise ApiConnectorError(str(e))
        except Exception as e:
            raise ApiConnectorError(f"Could not reach the API: {e}", retryable=True)
        if response.status_code != 200:
            retry = response.status_code in (408, 429) or response.status_code >= 500
            hint = " Check the Authorization header." if response.status_code in (401, 403) else ""
            raise ApiConnectorError(f"The API answered HTTP {response.status_code} on page {pages + 1}.{hint}", retryable=retry)
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            raise ApiConnectorError("The API did not return JSON. Use 'From URL' for CSV, Excel or XML files.")
        page_records, path = find_records(body, records_path)
        used_path = path if used_path is None else used_path
        pages += 1
        records.extend(page_records)
        if len(records) > MAX_RECORDS:
            raise ApiConnectorError(f"The API returned more than {MAX_RECORDS:,} records; lower max pages.")
        if not page_records or ptype == "none":
            break

        current = next_url
        next_url = None
        link = _link_next(response.headers.get("link", "")) if hasattr(response, "headers") else None
        if ptype in ("auto", "link") and link:
            next_url, strategy = urljoin(current, link), "link"
        elif ptype in ("auto", "cursor") and _next_url_in_body(body, current):
            next_url, strategy = _next_url_in_body(body, current), "next_url"
        elif ptype in ("auto", "cursor") and _cursor_in_body(body, pagination.get("cursor_path")):
            next_url, strategy = _with_params(url, **{cursor_param: _cursor_in_body(body, pagination.get("cursor_path"))}), "cursor"
        elif ptype == "page":
            if page_size and len(page_records) < int(page_size):
                break
            page_no += 1
            next_url = _with_params(current, **{page_param: page_no})
        elif ptype == "offset":
            if page_size and len(page_records) < int(page_size):
                break
            offset += len(page_records)
            next_url = _with_params(current, **{offset_param: offset})
        elif ptype == "auto":
            strategy = "none" if pages == 1 else strategy

    return {
        "records": records,
        "pages": pages,
        "records_path": used_path or "",
        "pagination": strategy,
        "truncated": bool(next_url) and pages >= max_pages,
    }


def to_frame(records: list) -> pd.DataFrame:
    """Nested objects become 'parent.child' columns; nested lists are kept as JSON text."""
    if not records:
        return pd.DataFrame()
    df = pd.json_normalize(records, sep=".", max_level=4)
    for col in df.columns:
        if df[col].map(lambda v: isinstance(v, (list, dict))).any():
            df[col] = df[col].map(lambda v: json.dumps(v, default=str) if isinstance(v, (list, dict)) else v)
    return df


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def file_name_for(url: str, name: Optional[str] = None) -> str:
    base = name or (urlparse(url).path.rstrip("/").rsplit("/", 1)[-1] or urlparse(url).hostname or "api")
    stem = re.sub(r"[^A-Za-z0-9_\-]+", "_", base.rsplit(".", 1)[0]).strip("_") or "api_data"
    return f"{stem[:80]}.csv"
