# -*- coding: utf-8 -*-
"""Интернет для агента: поиск и чтение страниц (только публичные адреса)."""
import html as htmlmod
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request


# ---------- интернет ----------
UA = "Mozilla/5.0 (compatible; PC-Agent/1.0)"


def is_public_url(url):
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    try:
        for info in socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80)):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
    except Exception:
        return False
    return True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def http_get(url, max_bytes=2_000_000):
    opener = urllib.request.build_opener(_NoRedirect)
    for _ in range(5):
        if not is_public_url(url):
            raise ValueError("Адрес недоступен: только публичные сайты (локальные адреса запрещены).")
        try:
            resp = opener.open(urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"}), timeout=20)
            raw = resp.read(max_bytes)
            return raw, resp.headers
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url = urllib.parse.urljoin(url, e.headers["Location"])
                continue
            raise
    raise ValueError("Слишком много перенаправлений.")


def html_to_text(h):
    h = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|tr|section|article)>", "\n", h)
    h = htmlmod.unescape(re.sub(r"(?s)<[^>]+>", " ", h))
    h = re.sub(r"[ \t\r\f\v]+", " ", h)
    return re.sub(r"\n\s*\n+", "\n\n", h).strip()


def t_fetch_url(url):
    try:
        raw, headers = http_get(url)
    except Exception as e:
        return f"Не удалось открыть страницу: {e}"
    ctype = headers.get("Content-Type", "")
    if not (ctype.startswith("text/") or "json" in ctype or "xml" in ctype):
        return f"Тип содержимого не поддерживается: {ctype}"
    m = re.search(r"charset=([\w-]+)", ctype)
    try:
        text = raw.decode(m.group(1) if m else "utf-8", errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")
    if "html" in ctype:
        text = html_to_text(text)
    return (text[:15000] + ("\n...[обрезано]" if len(text) > 15000 else "")) or "(пусто)"


def t_web_search(query):
    try:
        raw, _ = http_get("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query), 600_000)
    except Exception as e:
        return f"Поиск не сработал: {e}"
    page = raw.decode("utf-8", errors="replace")
    links = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S)
    snips = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', page, re.S)
    if not links:
        return "Ничего не найдено (поисковик мог временно заблокировать запрос). Попробуй позже или открой нужный сайт через fetch_url."
    out = []
    for i, (href, title) in enumerate(links[:8]):
        if "uddg=" in href:
            href = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [href])[0]
        elif href.startswith("//"):
            href = "https:" + href
        clean = lambda t: htmlmod.unescape(re.sub(r"<[^>]+>", "", t)).strip()
        out.append(f"{i + 1}. {clean(title)}\n   {href}\n   {clean(snips[i]) if i < len(snips) else ''}")
    return "\n".join(out)
