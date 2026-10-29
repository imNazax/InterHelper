"""Regression tests for arbitrary guides. Run: python -m unittest -v test_guias"""
import json
from pathlib import Path
import queue
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile
from xml.sax.saxutils import escape

from pdf_parser import load_guide, parse_qa_text
from matcher import QuestionMatcher, search_questions



def write_docx(path, paragraphs, table=''):
    body = ''.join('<w:p><w:pPr>' + (f'<w:outlineLvl w:val="{level}"/>' if level is not None else '') + '</w:pPr><w:r><w:t>' + escape(text) + '</w:t></w:r></w:p>' for text, level in paragraphs)
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + body + table + '</w:body></w:document>')


class GuideTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_real_pdf_reader_roundtrip(self):
        from pdf_parser import check_pdf_support
        check_pdf_support()

    def test_pdf_wrapped_questions_remain_searchable(self):
        import pymupdf
        path = self.folder / 'wrapped.pdf'
        headings = [
            ('Why should we hire you? | What can you bring to the role? What can you bring to the\njob?', 'hire'),
            ('What is your greatest weakness? | What would you like to\nimprove?', 'weakness'),
            ('You have not used these tools. How would you approach\nthat? | How do you learn unfamiliar technologies?', 'tools'),
            ('How do you verify a process before running it in\nproduction?', 'production'),
            ('How do you document observations? |\nWhat details do you record?', 'details'),
            ('How can you tell\nwhen a measurement is unreliable?', 'unreliable'),
        ]
        with pymupdf.open() as doc:
            page = doc.new_page()
            for index, (header, _) in enumerate(headings):
                y = 60 + index * 120
                page.insert_text((50, y), header, fontname='hebo', fontsize=10)
                page.insert_text((50, y + 40), f'Answer {index}.', fontsize=10)
            doc.save(path)
        data = load_guide(path)
        self.assertEqual(len(data), len(headings))
        for index, (header, query) in enumerate(headings):
            variants = [part.strip() for part in header.replace('\n', ' ').split('|')]
            self.assertEqual(data[index]['question'], variants[0])
            self.assertEqual(data[index]['aliases'], variants[1:])
            self.assertEqual(data[index]['answer'], f'Answer {index}.')
            self.assertEqual(search_questions(query.upper(), data), [data[index]])

    def test_pdf_separate_bold_blocks_are_not_joined(self):
        import pymupdf
        path = self.folder / 'separate.pdf'
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((50, 60), 'Describe calibration', fontname='hebo')
            page.insert_text((50, 90), 'How do you measure radiation?', fontname='hebo')
            page.insert_text((50, 120), 'Use a detector.')
            doc.save(path)
        data = load_guide(path)
        self.assertEqual([item['question'] for item in data], ['How do you measure radiation?'])
        self.assertEqual(data[0]['answer'], 'Use a detector.')

    def test_arbitrary_heading_level_and_nested_answer(self):
        path = self.folder / 'Nueva empresa.docx'
        write_docx(path, [('Sección', 0), ('Contexto', 1), ('¿Cómo calibrás un espectrómetro?', 3), ('Uso un patrón.', None), ('Pasos detallados', 4), ('Verifico la medición.', None), ('¿Qué es una órbita?', 3), ('Una trayectoria.', None)])
        data = load_guide(path)
        self.assertEqual(len(data), 2)
        self.assertIn('Pasos detallados', data[0]['answer'])
        self.assertEqual(data[1]['answer'], 'Una trayectoria.')
        self.assertIs(QuestionMatcher(data).match('espectrómetro')[0], data[0])

    def test_declarative_headings_need_no_question_vocabulary(self):
        path = self.folder/'topics.docx'
        write_docx(path, [('Astronomía', 2), ('La ciencia de los astros.', None), ('Biología', 2), ('La ciencia de la vida.', None)])
        data = load_guide(path)
        self.assertEqual([item['question'] for item in data], ['Astronomía', 'Biología'])

    def test_renaming_has_no_effect(self):
        first, second = self.folder/'guia.docx', self.folder/'unrelated.docx'
        write_docx(first, [('How do you calibrate a telescope?', 2), ('Use a reference star.', None)])
        second.write_bytes(first.read_bytes())
        self.assertEqual(load_guide(first), load_guide(second))

    def test_plain_docx_without_headings(self):
        path = self.folder/'plain.docx'
        write_docx(path, [('1. ¿Cómo funciona un telescopio?', None), ('Con lentes.', None)])
        self.assertEqual(load_guide(path)[0]['answer'], 'Con lentes.')

    def test_docx_table(self):
        path = self.folder/'tabla.docx'
        table = '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>¿Qué es una órbita?</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Una trayectoria.</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
        write_docx(path, [], table)
        self.assertEqual(load_guide(path)[0]['answer'], 'Una trayectoria.')

    def test_explicit_labels_protect_quoted_questions(self):
        data = parse_qa_text('Pregunta: Astronomía\nRespuesta: Primera línea.\nWhat would you do?\nEsa es una cita.\nPregunta: Biología\nRespuesta: Segunda respuesta.')
        self.assertEqual(len(data), 2)
        self.assertIn('What would you do?', data[0]['answer'])

    def test_txt_numbered_bilingual(self):
        path = self.folder/'new.txt'
        path.write_text('1. ¿Cómo calibrás un telescopio?\nCon un patrón.\n2. Why measure radiation?\nFor safety.', encoding='utf-8-sig')
        self.assertEqual(len(load_guide(path)), 2)

    def test_json_preserves_metadata_and_aliases(self):
        path = self.folder/'new.json'
        path.write_text(json.dumps([{'question':'Orbital mechanics', 'answer':'Gravity.', 'aliases':['How does gravity work?'], 'tags':['astronomy']}]), encoding='utf-8')
        data = load_guide(path)
        matcher = QuestionMatcher(data)
        self.assertEqual(data[0]['tags'], ['astronomy'])
        self.assertIs(matcher.match('How does gravity work?')[0], data[0])
        self.assertTrue(search_questions('astronomy', data))

    def test_bad_json_and_empty_document(self):
        path = self.folder/'bad.json'
        for value in ({}, [], [{'question':'x','answer':'y','tags':'bad'}], [{'question':'x','answer':''}]):
            path.write_text(json.dumps(value), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_guide(path)
        path = self.folder/'empty.txt'
        path.write_text('No question and answer pairs.', encoding='utf-8')
        with self.assertRaises(ValueError):
            load_guide(path)

    def test_matching_uses_current_catalog_and_rejects_ambiguity(self):
        data = parse_qa_text('How do you calibrate a telescope?\nUse a star.\nHow do you calibrate a microscope?\nUse a slide.')
        matcher = QuestionMatcher(data)
        self.assertIsNone(matcher.match('calibrate'))
        self.assertIs(matcher.match('microscope')[0], data[1])
        self.assertIsNone(matcher.match('salary expectations'))
        self.assertEqual(search_questions('hire', data), [])


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        audio = types.ModuleType('audio_capture')
        for name in ('list_audio_devices', 'get_running_relevant_apps', 'AudioStreamRecorder', 'shutdown_audio'):
            setattr(audio, name, lambda *a, **k: None)
        transcriber = types.ModuleType('transcriber')
        transcriber.AudioTranscriber = object
        with patch.dict(sys.modules, {'audio_capture': audio, 'transcriber': transcriber}):
            import main
        cls.main = main

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.settings = patch.object(self.main, 'SETTINGS_PATH', str(self.folder/'settings.json'))
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.errors = patch.object(self.main.messagebox, 'showerror')
        self.error = self.errors.start()
        self.addCleanup(self.errors.stop)
        self.warnings = patch.object(self.main.messagebox, 'showwarning')
        self.warning = self.warnings.start()
        self.addCleanup(self.warnings.stop)
        self.root = self.main.tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = self.main.InterHelperApp.__new__(self.main.InterHelperApp)
        self.app.root = self.root
        self.app.state = 'STOPPED'
        self.app.questions = []
        self.app.active_guide = None
        self.app.matcher = None
        self.app.ui_queue = queue.Queue()
        self.app._build_ui()

    def guide(self, name, question):
        path = self.folder/name
        path.write_text(json.dumps([{'question':question, 'answer':'An answer.'}]), encoding='utf-8')
        return str(path)

    def test_switch_reset_restore_and_failed_load(self):
        first = self.guide('first.json', 'How do telescopes work?')
        second = self.guide('second.json', 'How do microscopes work?')
        self.assertTrue(self.app._load_pdf(first))
        self.app.search_var.set('telescopes')
        self.app.ui_queue.put(('match', ('old', 100, 'interview')))
        self.assertTrue(self.app._load_pdf(second))
        self.assertEqual(self.app.search_var.get(), '')
        self.assertEqual(self.app.answer_text.get('1.0', 'end').strip(), '')
        self.assertTrue(self.app.ui_queue.empty())
        self.assertEqual(len(self.app.questions), 1)
        self.assertEqual(self.app.active_guide, second)
        self.assertEqual(json.loads((self.folder/'settings.json').read_text())['last_guide'], second)
        matcher = self.app.matcher
        bad = self.folder/'bad.json'
        bad.write_text('{}')
        self.assertFalse(self.app._load_pdf(str(bad)))
        self.assertIs(self.app.matcher, matcher)
        self.assertEqual(self.app.pdf_path_var.get(), second)
        self.app._restore_last_guide()
        self.assertEqual(self.app.active_guide, second)
        self.app.state = 'LISTENING'
        self.assertFalse(self.app._load_pdf(first))
        self.assertEqual(self.app.active_guide, second)

    def test_only_document_sidecar_is_applied(self):
        path = self.guide('guia_nueva.json', 'Why should we hire you?')
        data = self.main._apply_tags(load_guide(path), path)
        self.assertEqual(data[0]['tags'], [])
        (self.folder/'guia_nueva.tags.json').write_text(json.dumps({'Why should we hire you?':['custom']}))
        self.assertEqual(self.main._apply_tags(load_guide(path), path)[0]['tags'], ['custom'])
        (self.folder/'guia_nueva.tags.json').write_text('{"x":"bad"}')
        with self.assertRaises(ValueError):
            self.main._apply_tags(load_guide(path), path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
