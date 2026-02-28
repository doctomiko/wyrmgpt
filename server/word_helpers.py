
from io import BytesIO
from typing import List

from docx import Document


def _wrap_run_text(text: str, bold: bool, italic: bool) -> str:
    if not text:
        return ''
    if bold and italic:
        return f"***{text}***"
    if bold:
        return f"**{text}**"
    if italic:
        return f"*{text}*"
    return text

def extract_text_bytes(data: bytes, text_inject_max_chars: int) -> tuple[str, bool]:
    # Decode bytes as text for injection. Returns (text, was_truncated).
    if data.count(b'\x00') > max(8, len(data) // 100):
        raise ValueError('binary-like payload (NUL bytes)')

    try:
        txt = data.decode('utf-8')
    except UnicodeDecodeError:
        txt = data.decode('utf-8', errors='replace')

    truncated = False
    if len(txt) > text_inject_max_chars:
        txt = txt[:text_inject_max_chars] + f"\n\n[...truncated; exceeded text_inject_max_chars={text_inject_max_chars}]"
        truncated = True
    return txt, truncated


def extract_docx_markdown(data: bytes, text_inject_max_chars: int) -> str:
    # Best-effort DOCX -> markdown-ish text + JSON-ish table blocks + image annotations.
    if Document is None:
        raise RuntimeError('python-docx is not installed (Document import failed)')

    import json as _json
    import re as _re

    doc = Document(BytesIO(data))
    out_lines: List[str] = []

    for p in doc.paragraphs:
        style_name = (getattr(getattr(p, 'style', None), 'name', '') or '').lower()
        prefix = ''
        if style_name.startswith('heading'):
            m = _re.search(r'(\d+)', style_name)
            level = int(m.group(1)) if m else 1
            level = max(1, min(level, 6))
            prefix = '#' * level + ' '

        parts: List[str] = []
        for r in p.runs:
            t = r.text or ''
            if not t:
                continue
            parts.append(_wrap_run_text(t, bool(getattr(r, 'bold', False)), bool(getattr(r, 'italic', False))))
        line = (prefix + ''.join(parts)).rstrip()

        # Images in this paragraph (best-effort)
        try:
            drawings = p._p.xpath('.//w:drawing')
            if drawings:
                for d in drawings:
                    alt = ''
                    name = ''
                    try:
                        docPr = d.xpath('.//wp:docPr')
                        if docPr:
                            alt = docPr[0].get('descr') or docPr[0].get('title') or ''
                            name = docPr[0].get('name') or ''
                    except Exception:
                        pass

                    rel_id = ''
                    try:
                        blips = d.xpath('.//a:blip')
                        if blips:
                            rel_id = blips[0].get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed') or ''
                    except Exception:
                        pass

                    img_name = (name or '').strip()
                    if rel_id:
                        try:
                            part = doc.part.related_parts[rel_id]
                            img_name = str(getattr(part, 'partname', img_name)).split('/')[-1] or img_name
                        except Exception:
                            pass
                    if not img_name:
                        img_name = 'image'

                    marker = '{ image: ' + _json.dumps(img_name) + ', alt: ' + _json.dumps(alt) + ' }'
                    line = (line + ' ' + marker).strip() if line else marker
        except Exception:
            pass

        if line:
            out_lines.append(line)

    # Tables
    table_blocks: List[str] = []
    try:
        for ti, table in enumerate(doc.tables, start=1):
            rows = [[(cell.text or '').strip() for cell in row.cells] for row in table.rows]
            headers = rows[0] if rows else []
            header_ok = bool(headers) and all(h.strip() for h in headers) and (len(set(headers)) == len(headers))

            if header_ok and len(rows) > 1:
                objs = []
                for r in rows[1:]:
                    objs.append({headers[i]: (r[i] if i < len(r) else '') for i in range(len(headers))})
                payload = {f'table_{ti}': objs}
            else:
                payload = {f'table_{ti}': rows}

            table_blocks.append(_json.dumps(payload, ensure_ascii=False, indent=2))
    except Exception:
        pass

    if table_blocks:
        out_lines.append('')
        out_lines.append('Attachment tables (JSON-ish):')
        out_lines.extend(table_blocks)

    txt = '\n'.join(out_lines).strip()
    if len(txt) > text_inject_max_chars:
        txt = txt[:text_inject_max_chars] + f"\n\n[...truncated; exceeded text_inject_max_chars={text_inject_max_chars}]"
    return txt
