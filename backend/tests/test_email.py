import asyncio

import httpx

from leadx.email_enricher import EmailEnricher
from leadx.models import PlaceDTO


def place(website: str) -> PlaceDTO:
    return PlaceDTO(source="osm", source_place_id="1", name="Acme", website=website)


def test_extract_public_email_with_obfuscation():
    html = '<html><a href="mailto:sales@example-business.com">Email</a><p>info [at] example-business [dot] com</p></html>'
    assert "sales@example-business.com" in EmailEnricher._emails(html, "https://example-business.com")
    assert "info@example-business.com" in EmailEnricher._emails(html, "https://example-business.com")


def _allow_fake_hosts(monkeypatch):
    """The real SSRF guard (tested below) resolves DNS; these tests use a fake '.test' host."""
    import leadx.email_enricher as ee
    real = ee.is_public_url

    async def fake(url):
        host = httpx.URL(url).host
        return True if host.endswith(".test") else await real(url)
    monkeypatch.setattr(ee, "is_public_url", fake)


def test_enricher_fetches_contact_pages(monkeypatch):
    _allow_fake_hosts(monkeypatch)
    pages = {
        "https://acme.test/robots.txt": "User-agent: *\nAllow: /",
        "https://acme.test/": '<a href="/contact">Contact</a>',
        "https://acme.test/contact": '<a href="mailto:hello@acme.test">hello</a>',
    }
    async def handler(request: httpx.Request):
        return httpx.Response(200, headers={"content-type": "text/html"}, text=pages.get(str(request.url), ""))
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    enricher = EmailEnricher(client, concurrency=2, per_domain_delay=0)
    async def run():
        try:
            return await enricher.enrich(place("https://acme.test"))
        finally:
            await client.aclose()
    email, status = asyncio.run(run())
    assert email == "hello@acme.test" and status == "found"


import pytest

from leadx.email_enricher import is_public_url


@pytest.mark.parametrize("url,ok", [
    ("http://127.0.0.1/", False), ("http://localhost/", False), ("http://10.0.0.5/", False),
    ("http://169.254.169.254/latest/meta-data/", False), ("http://192.168.1.1/", False),
    ("http://[::1]/", False), ("file:///etc/passwd", False), ("ftp://8.8.8.8/", False),
    ("http://8.8.8.8:6379/", False), ("http://8.8.8.8/", True), ("https://1.1.1.1/", True)])
def test_ssrf_guard(url, ok):
    assert asyncio.run(is_public_url(url)) is ok


def test_redirect_to_internal_address_is_never_followed():
    seen = []

    async def handler(request: httpx.Request):
        seen.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    enricher = EmailEnricher(client, concurrency=1, per_domain_delay=0)

    async def run():
        try:
            return await enricher.enrich(place("http://8.8.8.8"))
        finally:
            await client.aclose()
    email, status = asyncio.run(run())
    assert email == "" and status == "none"
    assert not any("169.254" in u for u in seen)      # the internal address was never requested
