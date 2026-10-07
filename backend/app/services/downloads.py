"""Bounded public HTTP acquisition with redirect checks and DNS-pinned connections."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from pathlib import PurePosixPath
import re
import socket
import time
from typing import Callable
from urllib.parse import unquote, urljoin

from fastapi import HTTPException
import httpx

MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_REDIRECTS = 5
ARXIV_ID = re.compile(r'(?P<base>(?:\d{4}\.\d{4,5}|[a-z][a-z.\-]+/\d{7}))(?P<version>v[1-9]\d*)?', re.I)
ARXIV_HOSTS = {'arxiv.org', 'www.arxiv.org', 'export.arxiv.org'}
Resolver = Callable[[str, int], list[str]]


@dataclass(frozen=True)
class DownloadedPDF:
    data: bytes
    filename: str
    source_url: str
    download_url: str
    arxiv_id: str | None = None


@dataclass(frozen=True)
class PublicResponse:
    data: bytes
    url: str
    content_type: str


def normalize_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if candidate.lower().startswith('arxiv:'):
        candidate = candidate[6:].strip()
    if '://' in candidate:
        try:
            url = httpx.URL(candidate)
        except httpx.InvalidURL:
            return None
        if url.host not in ARXIV_HOSTS:
            return None
        match = re.fullmatch(r'/(?:abs|pdf|html)/(.+?)(?:\.pdf)?/?', url.path)
        if not match:
            return None
        candidate = unquote(match.group(1))
    if candidate.lower().endswith('.pdf'):
        candidate = candidate[:-4]
    match = ARXIV_ID.fullmatch(candidate)
    return match.group('base').lower() if match else None


def resolve_addresses(host: str, port: int) -> list[str]:
    try:
        return list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
    except OSError:
        raise HTTPException(502, '无法解析论文链接的域名，请检查地址或网络') from None


def _global_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return address.is_global
    except ValueError:
        return False


def validate_public_url(value: str, resolver: Resolver | None = None) -> tuple[httpx.URL, list[str]]:
    try:
        url = httpx.URL(value.strip())
        port = url.port or (443 if url.scheme == 'https' else 80)
    except (httpx.InvalidURL, ValueError):
        raise HTTPException(422, '请输入有效的公开 HTTP(S) 论文链接') from None
    if url.scheme not in {'http', 'https'} or not url.host or url.userinfo or port < 1 or port > 65535:
        raise HTTPException(422, '只支持不含账号密码的公开 HTTP(S) 论文链接')
    hostname = url.host.rstrip('.').lower()
    if hostname == 'localhost' or hostname.endswith('.localhost') or hostname.endswith('.local'):
        raise HTTPException(422, '不能导入本机或内网地址，请使用公开论文链接')
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        addresses = (resolver or resolve_addresses)(hostname, port)
    else:
        addresses = [hostname]
    if not addresses or not all(_global_address(address) for address in addresses):
        raise HTTPException(422, '论文链接解析到本机、内网或保留地址，无法下载')
    return url.copy_with(fragment=None), addresses


class PublicHTTPTransport(httpx.BaseTransport):
    """Connect to the validated IP; preserve HTTP Host and TLS SNI/cert validation."""
    def __init__(self) -> None:
        self._transport = httpx.HTTPTransport(retries=0, trust_env=False)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        pinned_ip = request.extensions['validated_ip']
        extensions = dict(request.extensions)
        extensions['sni_hostname'] = request.url.host
        pinned = httpx.Request(request.method, request.url.copy_with(host=pinned_ip), headers=request.headers, stream=request.stream, extensions=extensions)
        return self._transport.handle_request(pinned)

    def close(self) -> None:
        self._transport.close()


def fetch_public(value: str, *, max_bytes: int, timeout: float = 15.0, deadline: float = 60.0, transport: httpx.BaseTransport | None = None, resolver: Resolver | None = None) -> PublicResponse:
    started = time.monotonic()
    current = value
    try:
        with httpx.Client(transport=transport or PublicHTTPTransport(), timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0)), follow_redirects=False, trust_env=False, headers={'User-Agent': 'ResearchIntelligenceWorkspace/0.3 (local paper reader)', 'Accept-Encoding': 'identity'}) as client:
            for redirect in range(MAX_REDIRECTS + 1):
                url, addresses = validate_public_url(current, resolver)
                remaining = deadline - (time.monotonic() - started)
                if remaining <= 0:
                    raise HTTPException(504, '论文下载超时，请稍后重试')
                with client.stream('GET', url, extensions={'validated_ip': addresses[0]}, timeout=min(timeout, remaining)) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get('location')
                        if not location or redirect == MAX_REDIRECTS:
                            raise HTTPException(502, '论文链接重定向过多或目标无效')
                        current = urljoin(str(url), location)
                        continue
                    if response.status_code == 404:
                        raise HTTPException(404, '论文链接未找到，请检查论文编号或 PDF 地址')
                    if response.status_code in {401, 403}:
                        raise HTTPException(403, '论文链接拒绝访问，请使用可公开下载的 PDF 链接')
                    if not response.is_success:
                        raise HTTPException(502, '论文来源暂不可用，请稍后重试或上传 PDF 文件')
                    length = response.headers.get('content-length', '')
                    if length.isdigit() and int(length) > max_bytes:
                        raise HTTPException(413, '下载内容超过大小上限；PDF 最大为 50 MB')
                    pieces: list[bytes] = []
                    size = 0
                    for piece in response.iter_bytes():
                        size += len(piece)
                        if size > max_bytes:
                            raise HTTPException(413, '下载内容超过大小上限；PDF 最大为 50 MB')
                        if time.monotonic() - started > deadline:
                            raise HTTPException(504, '论文下载超时，请稍后重试')
                        pieces.append(piece)
                    return PublicResponse(b''.join(pieces), str(url), response.headers.get('content-type', '').lower())
    except httpx.TimeoutException:
        raise HTTPException(504, '论文下载超时，请稍后重试或上传本地 PDF') from None
    except (httpx.HTTPError, OSError):
        raise HTTPException(502, '无法连接论文来源，请检查网络或上传本地 PDF') from None
    raise HTTPException(502, '论文下载失败，请检查链接')


def download_pdf(value: str, *, transport: httpx.BaseTransport | None = None, resolver: Resolver | None = None) -> DownloadedPDF:
    # URL syntax is checked here; public-address resolution occurs at each request.
    try:
        url = httpx.URL(value.strip())
    except httpx.InvalidURL:
        raise HTTPException(422, '请输入有效的公开论文链接') from None
    if url.scheme not in {'http', 'https'} or not url.host or url.userinfo:
        raise HTTPException(422, '只支持不含账号密码的公开 HTTP(S) 论文链接')
    source_url = str(url.copy_with(fragment=None))
    arxiv_id = normalize_arxiv_id(source_url)
    download_url = source_url
    if arxiv_id and url.host in ARXIV_HOSTS:
        identifier = re.sub(r'^/(?:abs|pdf|html)/', '', url.path).removesuffix('.pdf').rstrip('/')
        download_url = 'https://arxiv.org/pdf/' + identifier
    result = fetch_public(download_url, max_bytes=MAX_PDF_BYTES, transport=transport, resolver=resolver)
    if not result.data.startswith(b'%PDF-'):
        raise HTTPException(415, '链接返回的内容不是 PDF；请提供 arXiv abs/pdf 链接或公开 PDF 直链')
    name = PurePosixPath(httpx.URL(result.url).path).name or 'linked-paper.pdf'
    if not name.lower().endswith('.pdf'):
        name += '.pdf'
    return DownloadedPDF(result.data, name, source_url, result.url, arxiv_id)
