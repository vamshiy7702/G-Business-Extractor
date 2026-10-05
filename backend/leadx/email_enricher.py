from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections import defaultdict
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib import robotparser

import httpx

from .config import settings
from .models import PlaceDTO

EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
# Only BRACKETED obfuscation ("name [at] site [dot] com"). A bare " at " is ordinary English: matching it
# turned "Visit us at acme.com" into the fake address us@acme.com.
OBFUSCATED_RE = re.compile(r"([A-Z0-9._%+\-]+)\s*(?:\[at\]|\(at\))\s*([A-Z0-9-]+)\s*(?:\[dot\]|\(dot\)|\.)\s*([A-Z]{2,})", re.I)
JUNK_SUBSTRINGS = ("example@", "sentry", "wixpress", "wordpress", "noreply@", "no-reply@")
EMAIL_ASSET_RE = re.compile(r"\.(?:png|jpe?g|gif|svg|webp|ico)(?:$|[?#])", re.I)


ALLOWED_PORTS = (None, 80, 443)
MAX_REDIRECTS = 3
MAX_BODY_BYTES = 2_000_000


async def is_public_url(url: str) -> bool:
    """SSRF guard. Website URLs come from public map data (untrusted). Only http(s) on standard ports
    to hosts that resolve exclusively to globally-routable IPs may be fetched, so a crafted listing
    cannot make this server call localhost, a private network or a cloud metadata endpoint."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    try:
        if u.port not in ALLOWED_PORTS:
            return False
    except ValueError:
        return False
    try:
        ips = [ipaddress.ip_address(u.hostname)]
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(u.hostname, None, type=socket.SOCK_STREAM)
        except OSError:
            return False
        ips = [ipaddress.ip_address(i[4][0]) for i in infos]
    ips = [ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped else ip for ip in ips]
    return bool(ips) and all(ip.is_global for ip in ips)


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_data(self, data):
        if data:
            self.text_parts.append(data)


class EmailEnricher:
    """Best-effort public-email enrichment with robots.txt and polite throttling."""

    def __init__(self, client: httpx.AsyncClient, concurrency: int | None = None,
                 per_domain_delay: float | None = None, timeout: float | None = None):
        self.client = client
        self.concurrency = max(1, concurrency or settings.email_max_concurrency)
        self.per_domain_delay = max(0.0, per_domain_delay if per_domain_delay is not None else settings.email_per_domain_delay)
        self.timeout = timeout or settings.email_timeout
        self._sem = asyncio.Semaphore(self.concurrency)
        self._domain_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last_fetch: dict[str, float] = {}
        self._robots_cache: dict[str, robotparser.RobotFileParser | None] = {}
        self._robots_lock = asyncio.Lock()

    @staticmethod
    def _clean_url(url: str) -> str:
        value = (url or "").strip()
        if not value:
            return ""
        if not re.match(r"^https?://", value, re.I):
            value = "https://" + value
        return value

    @staticmethod
    def _domain(url: str) -> str:
        return (urlparse(url).hostname or "").lower().split(":", 1)[0]

    async def _robots(self, domain: str) -> robotparser.RobotFileParser | None:
        if not domain:
            return None
        if domain in self._robots_cache:
            return self._robots_cache[domain]
        async with self._robots_lock:
            if domain in self._robots_cache:
                return self._robots_cache[domain]
            robots_url = f"https://{domain}/robots.txt"
            try:
                if not await is_public_url(robots_url):
                    self._robots_cache[domain] = None
                    return None
                r = await self.client.get(robots_url, timeout=self.timeout, follow_redirects=False)
                if r.status_code >= 300:
                    parser = None
                else:
                    parser = robotparser.RobotFileParser()
                    parser.set_url(robots_url)
                    parser.parse(r.text.splitlines())
            except httpx.HTTPError:
                parser = None
            self._robots_cache[domain] = parser
            return parser

    async def _allowed(self, url: str) -> bool:
        domain = self._domain(url)
        parser = await self._robots(domain)
        if parser is None:
            return True
        return parser.can_fetch("LeadExtractor/1.0", url)

    async def _fetch(self, url: str) -> str | None:
        domain = self._domain(url)
        if not domain or not await self._allowed(url):
            return None
        lock = self._domain_locks[domain]
        async with self._sem:
            async with lock:
                loop = asyncio.get_running_loop()
                now = loop.time()
                last = self._last_fetch.get(domain, 0.0)
                wait = self.per_domain_delay - (now - last)
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    current = url
                    for _hop in range(MAX_REDIRECTS + 1):
                        if not await is_public_url(current):
                            self._last_fetch[domain] = asyncio.get_running_loop().time()
                            return None
                        response = await self.client.get(
                            current,
                            timeout=self.timeout,
                            follow_redirects=False,         # every hop is re-checked by is_public_url
                            headers={"Accept": "text/html,application/xhtml+xml"},
                        )
                        if response.status_code in (301, 302, 303, 307, 308):
                            target = response.headers.get("location")
                            if not target:
                                break
                            current = urljoin(current, target)
                            continue
                        self._last_fetch[domain] = asyncio.get_running_loop().time()
                        if response.status_code >= 400:
                            return None
                        ctype = response.headers.get("content-type", "")
                        if "html" not in ctype and "xhtml" not in ctype:
                            return None
                        if int(response.headers.get("content-length", "0") or 0) > MAX_BODY_BYTES:
                            return None
                        return response.text[:1_000_000]
                    self._last_fetch[domain] = asyncio.get_running_loop().time()
                    return None
                except (httpx.HTTPError, UnicodeError, ValueError):
                    self._last_fetch[domain] = asyncio.get_running_loop().time()
                    return None

    @staticmethod
    def _emails(text: str, base_url: str) -> list[str]:
        normalized = text.replace("&#64;", "@").replace("&#46;", ".")
        candidates = set(x.lower() for x in EMAIL_RE.findall(normalized))
        for local, domain, tld in OBFUSCATED_RE.findall(normalized):
            candidates.add(f"{local}@{domain}.{tld}".lower())
        parser = _LinkParser()
        try:
            parser.feed(text)
        except Exception:
            pass
        for href in parser.links:
            if href.lower().startswith("mailto:"):
                raw = href[7:].split("?", 1)[0].strip()
                if EMAIL_RE.fullmatch(raw):
                    candidates.add(raw.lower())
        out = []
        for email in candidates:
            if any(bad in email for bad in JUNK_SUBSTRINGS):
                continue
            if EMAIL_ASSET_RE.search(email):
                continue
            if "@" not in email or email.count("@") != 1:
                continue
            out.append(email)
        return sorted(out)

    async def enrich(self, place: PlaceDTO) -> tuple[str, str]:
        if place.email:
            return place.email.lower().strip(), "found"
        if not place.website:
            return "", "none"
        base = self._clean_url(place.website)
        if not base:
            return "", "none"
        parsed = urlparse(base)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return "", "error"
        candidates = [
            base,
            urljoin(base.rstrip("/") + "/", "contact"),
            urljoin(base.rstrip("/") + "/", "contact-us"),
            urljoin(base.rstrip("/") + "/", "about"),
        ]
        seen = set()
        html_pages: list[tuple[str, str]] = []
        try:
            for url in candidates:
                if url in seen:
                    continue
                seen.add(url)
                html = await self._fetch(url)
                if not html:
                    continue
                html_pages.append((url, html))
                parser = _LinkParser()
                try:
                    parser.feed(html)
                except Exception:
                    parser.links = []
                base_domain = (parsed.hostname or "").lower()
                for href in parser.links:
                    full = urljoin(url, href)
                    host = (urlparse(full).hostname or "").lower()
                    path = (urlparse(full).path or "").lower()
                    if host == base_domain and any(token in path for token in ("contact", "about")):
                        if full not in seen:
                            candidates.append(full)
                if len(html_pages) >= 4:
                    break
            emails: list[str] = []
            for url, html in html_pages:
                emails.extend(self._emails(html, url))
            if not emails:
                return "", "none"
            domain = (parsed.hostname or "").lower().replace("www.", "")
            emails.sort(key=lambda e: (0 if e.split("@", 1)[1].replace("www.", "") == domain else 1, len(e)))
            return emails[0], "found"
        except Exception:
            return "", "error"

    async def enrich_many(self, places: list[PlaceDTO]) -> dict[str, tuple[str, str]]:
        tasks = [asyncio.create_task(self.enrich(place)) for place in places]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: dict[str, tuple[str, str]] = {}
        for place, result in zip(places, results):
            if isinstance(result, Exception):
                out[place.dedup_key] = ("", "error")
            else:
                out[place.dedup_key] = result
        return out
