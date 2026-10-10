"""Small video-container checks and safe, fetch-free player URL selection."""
from pathlib import PurePosixPath
import re
from urllib.parse import parse_qs, urlsplit


def _mp4_boxes(stream, start, end):
    """Walk bounded ISO BMFF boxes without reading the video payload."""
    position = start
    for _ in range(10000):
        if position == end:
            return
        if end - position < 8:
            raise ValueError('Truncated MP4 box.')
        stream.seek(position)
        header = stream.read(8)
        size, kind = int.from_bytes(header[:4], 'big'), header[4:8]
        header_size = 8
        if size == 1:
            extra = stream.read(8)
            if len(extra) != 8:
                raise ValueError('Truncated MP4 box length.')
            size, header_size = int.from_bytes(extra, 'big'), 16
        elif size == 0:
            size = end - position
        if size < header_size or position + size > end:
            raise ValueError('Invalid MP4 box length.')
        yield kind, position + header_size, position + size
        position += size
    raise ValueError('Too many MP4 boxes.')


def _valid_mp4(stream, size):
    found = set()
    for kind, start, end in _mp4_boxes(stream, 0, size):
        if kind == b'ftyp':
            if end - start < 8 or end - start > 4096 or (end - start) % 4:
                return False
            stream.seek(start)
            brands = stream.read(end - start)
            supported = {b'isom', b'iso2', b'iso3', b'iso4', b'iso5', b'iso6', b'iso8', b'iso9',
                         b'mp41', b'mp42', b'avc1', b'dash', b'M4V ', b'M4VH', b'M4VP', b'MSNV'}
            if not ({brands[:4]} | {brands[i:i + 4] for i in range(8, len(brands), 4)}) & supported:
                return False
            found.add(kind)
        elif kind == b'moov':
            if any(child == b'trak' and child_end > child_start
                   for child, child_start, child_end in _mp4_boxes(stream, start, end)):
                found.add(kind)
        elif kind == b'mdat' and end > start:
            found.add(kind)
    return {b'ftyp', b'moov', b'mdat'} <= found


def _ebml_integer(stream, *, element_id=False):
    first = stream.read(1)
    if not first or not first[0]:
        raise ValueError('Invalid EBML integer.')
    length = 9 - first[0].bit_length()
    if length > (4 if element_id else 8):
        raise ValueError('Invalid EBML integer length.')
    tail = stream.read(length - 1)
    if len(tail) != length - 1:
        raise ValueError('Truncated EBML integer.')
    value = int.from_bytes(first + tail, 'big')
    if element_id:
        return value
    value &= (1 << (7 * length)) - 1
    return None if value == (1 << (7 * length)) - 1 else value


def _ebml_element(stream, end):
    kind = _ebml_integer(stream, element_id=True)
    length = _ebml_integer(stream)
    start = stream.tell()
    stop = end if length is None else start + length
    if stop > end or start > stop:
        raise ValueError('Truncated WebM element.')
    return kind, start, stop, length is None


def _valid_webm(stream, size):
    stream.seek(0)
    kind, start, end, unknown = _ebml_element(stream, size)
    if kind != 0x1A45DFA3 or unknown or end - start > 4096:
        return False
    document_type = None
    while stream.tell() < end:
        child, child_start, child_end, child_unknown = _ebml_element(stream, end)
        if child_unknown:
            return False
        if child == 0x4282:
            document_type = stream.read(child_end - child_start)
        stream.seek(child_end)
    if document_type != b'webm':
        return False
    kind, start, end, _ = _ebml_element(stream, size)
    if kind != 0x18538067:
        return False
    found = set()
    for _ in range(10000):
        if stream.tell() >= end:
            return False
        child, child_start, child_end, child_unknown = _ebml_element(stream, end)
        if child in {0x1654AE6B, 0x1F43B675} and child_end > child_start:
            found.add(child)
        if {0x1654AE6B, 0x1F43B675} <= found:
            return True
        if child_unknown:
            return False
        stream.seek(child_end)
    return False


def valid_video_container(stream, extension):
    """Check container structure, not codec support or the contents of each frame."""
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(0)
    if extension == '.mp4':
        return _valid_mp4(stream, size)
    if extension == '.webm':
        return _valid_webm(stream, size)
    return False


def video_embed(url):
    """Return a safe player choice. Unknown sites remain ordinary external links."""
    fallback = {'kind': 'external', 'url': url, 'mime_type': '', 'provider': 'Video website'}
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            return {**fallback, 'url': ''}
        host = parsed.hostname.lower()
        path = parsed.path.rstrip('/')
        video_id = None
        if host in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com'}:
            if path == '/watch':
                video_id = parse_qs(parsed.query, max_num_fields=100).get('v', [''])[0]
            elif re.fullmatch(r'/(?:embed|shorts|live)/[A-Za-z0-9_-]{11}', path):
                video_id = path.rsplit('/', 1)[-1]
        elif host == 'youtu.be':
            video_id = path.lstrip('/')
        if video_id and re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            return {'kind': 'embed', 'url': f'https://www.youtube-nocookie.com/embed/{video_id}', 'mime_type': '', 'provider': 'YouTube'}
        if host in {'vimeo.com', 'www.vimeo.com', 'player.vimeo.com'}:
            match = re.fullmatch(r'/(?:video/)?([0-9]{1,15})', path)
            if match:
                return {'kind': 'embed', 'url': f'https://player.vimeo.com/video/{match[1]}', 'mime_type': '', 'provider': 'Vimeo'}
        extension = PurePosixPath(parsed.path).suffix.lower()
        if extension in {'.mp4', '.webm'}:
            return {'kind': 'direct', 'url': url, 'mime_type': 'video/mp4' if extension == '.mp4' else 'video/webm', 'provider': 'Video file'}
    except ValueError:
        return {**fallback, 'url': ''}
    return fallback
