"""Document-driven question/answer extraction. No company-specific rules."""
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from matcher import extract_question_keywords, normalize_text

INTERROGATIVE_STARTS = (
    'what', 'why', 'how', 'when', 'where', 'who', 'which', 'do', 'does',
    'did', 'have', 'has', 'are', 'is', 'can', 'could', 'would', 'will',
    'tell me', 'describe', 'give me', 'explain', 'walk me through',
    'qué', 'que', 'cómo', 'como', 'cuándo', 'cuando', 'dónde', 'donde',
    'quién', 'quien', 'cuál', 'cual', 'por qué', 'por que', 'puedes',
    'podrías', 'cuéntame', 'contame', 'describí', 'describe', 'explica', 'explicá',
)


def _clean_header(text):
    text = re.sub(r'^\s*(?:[-•]\s+|\d+[.)]\s+|#{1,6}\s+)', '', text.strip())
    return re.sub(r'^(?:Q|P|Question|Pregunta)\s*:\s*', '', text, flags=re.I).strip()


def is_probable_question(line):
    clean = _clean_header(line)
    if not 3 <= len(clean) <= 500 or re.search(r'\.{3,}\s*\d*\s*$', clean):
        return False
    return clean.startswith('¿') or clean.endswith('?') or any(
        re.match(r'^' + re.escape(w) + r'\b', clean, re.I) for w in INTERROGATIVE_STARTS)


def extract_keywords(text):
    return extract_question_keywords(text)


def _make_item(header, answer):
    variants = [_clean_header(q) for q in header.split('|') if q.strip()]
    return {'question': variants[0], 'aliases': variants[1:], 'answer': answer.strip(),
            'tags': [], 'keywords': list(dict.fromkeys(
                k for q in variants for k in extract_keywords(q)))}


def _deduplicate(items):
    output = {}
    for item in items:
        if not item['answer'].strip():
            continue
        key = normalize_text(item['question'])
        if key not in output or len(item['answer']) > len(output[key]['answer']):
            output[key] = item
    return list(output.values())


def _parse_records(records):
    """Infer the question heading level from the document's own headings."""
    records = [(text, level) for text, level in records
               if text.strip() and not re.search(r'\.{3,}\s*\d*\s*$', text)]
    counts = Counter(level for text, level in records
                     if level is not None and is_probable_question(text))
    if not counts:
        # Declarative question headings (e.g. topic names) need no fixed vocabulary.
        counts = Counter(level for index, (_, level) in enumerate(records[:-1])
                         if level is not None and records[index + 1][1] is None)
    if not counts:
        return parse_qa_text('\n'.join(text for text, _ in records))
    question_level = max(counts, key=lambda level: (counts[level], level))
    items, current, section = [], None, ''
    for value, level in records:
        if level is not None and level < question_level:
            section, current = value, None
        elif level == question_level:
            current = _make_item(value, '')
            current['section'] = section
            items.append(current)
        elif current is not None:
            current['answer'] += ('\n\n' if current['answer'] else '') + value
    return _deduplicate(items)


def parse_qa_text(text):
    """Plain questions followed by answers; explicit Q:/A: labels take priority."""
    lines = text.splitlines()
    explicit = any(re.match(r'^\s*(?:Q|P|Question|Pregunta)\s*:', line, re.I) for line in lines)
    items, header, body = [], None, []
    for line in lines:
        line = line.strip()
        if not line or re.search(r'\.{3,}\s*\d*\s*$', line):
            continue
        new_question = bool(re.match(r'^(?:Q|P|Question|Pregunta)\s*:', line, re.I)) if explicit else is_probable_question(line)
        if new_question:
            if header and body:
                items.append(_make_item(header, '\n'.join(body)))
            header, body = _clean_header(line), []
        elif header:
            body.append(re.sub(r'^(?:A|R|Answer|Respuesta)\s*:\s*', '', line, flags=re.I))
    if header and body:
        items.append(_make_item(header, '\n'.join(body)))
    return _deduplicate(items)


def _extract_pdf_only(path):
    try:
        import pymupdf
    except ImportError as error:
        raise ValueError('Para abrir PDF, instalá las dependencias de requirements.txt (PyMuPDF).') from error
    records = []
    with pymupdf.open(path) as doc:
        for page in doc:
            for block in page.get_text('dict')['blocks']:
                previous = None
                for line in block.get('lines', []):
                    spans = [s for s in line['spans'] if s['text'].strip()]
                    if not spans:
                        continue
                    text = ''.join(s['text'] for s in spans).strip()
                    bold = all((s.get('flags', 0) & 16) or 'bold' in s.get('font', '').lower() for s in spans)
                    style = {(s.get('font'), round(s.get('size', 0), 1)) for s in spans}
                    bbox = line['bbox']
                    # A wrapped heading's last line may itself end in '?' or
                    # begin with an interrogative. Reassemble it using layout
                    # before deciding which records are question headings.
                    wrapped = False
                    if previous is not None and bold and records[-1][1] == 0:
                        prev_bbox, prev_style = previous
                        height = max(prev_bbox[3] - prev_bbox[1], bbox[3] - bbox[1])
                        gap = bbox[1] - prev_bbox[3]
                        unfinished = not records[-1][0].endswith('?')
                        alias = records[-1][0].endswith('|') or text.startswith('|')
                        wrapped = (style == prev_style and -1 <= gap <= height * .6
                                   and abs(bbox[0] - prev_bbox[0]) <= height
                                   and (unfinished or alias))
                    if wrapped:
                        records[-1] = (records[-1][0] + ' ' + text, 0)
                    else:
                        records.append((text, 0 if bold else None))
                    previous = (bbox, style)
    if any(level == 0 and is_probable_question(text) for text, level in records):
        records = [(text, level if is_probable_question(text) else None) for text, level in records]
    return _parse_records(records)


def extract_qa_from_docx(path):
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    attr = '{' + ns['w'] + '}'
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
        styles = ET.fromstring(archive.read('word/styles.xml')) if 'word/styles.xml' in archive.namelist() else None
    style_map = {} if styles is None else {s.get(attr+'styleId'): s for s in styles.findall('w:style', ns)}

    def style_level(sid, seen=None):
        seen = set() if seen is None else seen
        if sid in seen or sid not in style_map:
            return None
        seen.add(sid)
        style = style_map[sid]
        outline = style.find('w:pPr/w:outlineLvl', ns)
        if outline is not None:
            value = int(outline.get(attr+'val'))
            return value if value < 9 else None
        parent = style.find('w:basedOn', ns)
        return style_level(parent.get(attr+'val'), seen) if parent is not None else None

    def paragraph_record(paragraph):
        # Exclude table of contents fields, including their cached text.
        if paragraph.find('.//w:instrText', ns) is not None:
            return None
        value = ''.join(t.text or '' for t in paragraph.findall('.//w:t', ns)).strip()
        style = paragraph.find('w:pPr/w:pStyle', ns)
        sid = style.get(attr+'val') if style is not None else ''
        if sid.lower().startswith(('toc', 'tableofcontents')):
            return None
        outline = paragraph.find('w:pPr/w:outlineLvl', ns)
        level = int(outline.get(attr+'val')) if outline is not None else style_level(sid)
        return value, level if level is not None and level < 9 else None

    records, table_items, bold_records = [], [], []
    for node in root.find('w:body', ns):
        if node.tag == attr+'p':
            record = paragraph_record(node)
            if record:
                records.append(record)
                runs = [r for r in node.findall('w:r', ns) if r.find('w:t', ns) is not None]
                bold = bool(runs) and all(r.find('w:rPr/w:b', ns) is not None and r.find('w:rPr/w:b', ns).get(attr+'val', '1') not in ('0', 'false', 'off') for r in runs)
                bold_records.append((record[0], 0 if bold else None))
        elif node.tag == attr+'tbl':
            for row in node.findall('w:tr', ns):
                cells = ['\n'.join(''.join(t.text or '' for t in p.findall('.//w:t', ns))
                                   for p in cell.findall('.//w:p', ns)).strip()
                         for cell in row.findall('w:tc', ns)]
                if len(cells) == 2 and is_probable_question(cells[0]) and cells[1]:
                    table_items.append(_make_item(cells[0], cells[1]))
                elif any(cells):
                    records.append((' | '.join(cells), None))
                    bold_records.append((' | '.join(cells), None))
    if not any(level is not None for _, level in records):
        records = [(text, level if is_probable_question(text) else None) for text, level in bold_records]
    return _deduplicate(_parse_records(records) + table_items)


def load_guide(path):
    """Load a guide without using its filename to infer content or company."""
    suffix = os.path.splitext(os.fspath(path))[1].lower()
    if suffix == '.docx':
        items = extract_qa_from_docx(path)
    elif suffix == '.txt':
        with open(path, encoding='utf-8-sig') as handle:
            items = parse_qa_text(handle.read())
    elif suffix == '.pdf':
        items = _extract_pdf_only(path)
    elif suffix == '.json':
        with open(path, encoding='utf-8-sig') as handle:
            items = json.load(handle)
        if not isinstance(items, list):
            raise ValueError('El catálogo debe ser una lista de preguntas.')
        for item in items:
            if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip() for k in ('question', 'answer')):
                raise ValueError('Cada entrada necesita una pregunta y una respuesta completas.')
            for key in ('aliases', 'tags', 'keywords'):
                if key in item and (not isinstance(item[key], list) or not all(isinstance(v, str) for v in item[key])):
                    raise ValueError(f'{key} debe ser una lista de textos.')
                item.setdefault(key, [])
            item['keywords'] = list(dict.fromkeys(item['keywords'] + [k for q in [item['question']] + item['aliases'] for k in extract_keywords(q)]))
    else:
        raise ValueError('Seleccioná un PDF, DOCX, JSON o TXT.')
    if not items:
        raise ValueError('No se encontraron preguntas con respuestas. Usá títulos para las preguntas en Word, o pares Pregunta: / Respuesta: en TXT. Los PDF deben contener texto seleccionable.')
    return items


# Compatibility for integrations using the original name.
extract_qa_from_pdf = load_guide


def check_pdf_support():
    """Exercise the actual PDF reader, also inside the frozen executable."""
    import tempfile
    import pymupdf
    with tempfile.TemporaryDirectory(prefix='interhelper-pdf-') as folder:
        path = os.path.join(folder, 'check.pdf')
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((72, 72), 'How do you verify a measurement?', fontname='hebo')
            page.insert_text((72, 96), 'Compare it against a reference.', fontname='helv')
            doc.save(path)
        items = load_guide(path)
        if len(items) != 1 or items[0]['question'] != 'How do you verify a measurement?' or items[0]['answer'] != 'Compare it against a reference.':
            raise RuntimeError('Falló la comprobación de lectura PDF del paquete.')
