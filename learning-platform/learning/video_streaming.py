"""Bounded private video streaming, including browser seeking with byte ranges."""
import re

from django.http import HttpResponse, StreamingHttpResponse


def _byte_range(header, size):
    """None means full response; False means a valid but unsatisfiable range."""
    if not header or len(header) > 128:
        return None
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', header.strip())
    if not match or not any(match.groups()):
        # Unsupported units, malformed ranges and multipart ranges are ignored.
        return None
    first, last = match.groups()
    if first:
        start = int(first)
        end = int(last) if last else size - 1
        if last and end < start:
            return None
        if start >= size:
            return False
        return start, min(end, size - 1)
    suffix = int(last)
    if not suffix or not size:
        return False
    return max(0, size - suffix), size - 1


def _chunks(path, start, length):
    # Opening lazily avoids holding a file for HEAD or unconsumed responses.
    # Closing the response closes this generator and its file as well.
    with path.open('rb') as stream:
        stream.seek(start)
        remaining = length
        while remaining:
            chunk = stream.read(min(64 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def video_response(request, path):
    stat = path.stat()
    size = stat.st_size
    etag = f'"{stat.st_mtime_ns:x}-{size:x}"'
    mime = 'video/mp4' if path.suffix.lower() == '.mp4' else 'video/webm'
    headers = {'Accept-Ranges': 'bytes', 'Cache-Control': 'private, no-store',
               'X-Content-Type-Options': 'nosniff', 'Content-Disposition': 'inline', 'ETag': etag}
    selection = None
    if request.method == 'GET' and request.headers.get('If-Range', etag) == etag:
        selection = _byte_range(request.headers.get('Range'), size)
    if selection is False:
        headers.update({'Content-Range': f'bytes */{size}', 'Content-Length': '0'})
        return HttpResponse(status=416, content_type=mime, headers=headers)
    start, end = selection if selection is not None else (0, size - 1)
    length = end - start + 1
    headers['Content-Length'] = str(length)
    status = 206 if selection is not None else 200
    if status == 206:
        headers['Content-Range'] = f'bytes {start}-{end}/{size}'
    if request.method == 'HEAD':
        return HttpResponse(content_type=mime, headers=headers)
    return StreamingHttpResponse(_chunks(path, start, length), status=status, content_type=mime, headers=headers)
