# -*- coding: utf-8 -*-
"""Документы Word/Excel, чтение форматов и безопасность интернет-инструментов."""
import pathlib
import unittest
import xml.etree.ElementTree as ET
import zipfile

from pcagent import docs, state, webtools
from tests.unit_base import UnitCase

MD = "# Отчёт\n\nПривет, **мир**!\n\n## Список\n- пункт один\n- пункт **два**\n1. первый\n\n| Имя | Цена |\n|---|---|\n| Эвакуатор | 5000 |\n| Самосвал | 7000 |\n\nКонец."


class Documents(UnitCase):
    def setUp(self):
        super().setUp()
        state.AUTO = True            # без подтверждений

    def test_docx_roundtrip_and_validity(self):
        self.assertIn("Создан", docs.t_create_docx("report.docx", MD))
        text = docs.t_read_document("report.docx")
        for part in ("# Отчёт", "Привет, мир!", "## Список", "пункт два", "Эвакуатор | 5000"):
            self.assertIn(part, text)
        z = zipfile.ZipFile(self.ws / "report.docx")
        for name in z.namelist():
            ET.fromstring(z.read(name))                        # весь XML корректен
        try:
            import docx                                         # необязательная проверка настоящей библиотекой
        except ImportError:
            return
        d = docx.Document(str(self.ws / "report.docx"))
        self.assertEqual(d.paragraphs[0].text, "Отчёт")
        self.assertEqual(len(d.tables), 1)

    def test_xlsx_roundtrip_formulas_and_validity(self):
        sheets = {"Цены": [["Имя", "Цена", "Итого"], ["Эвакуатор", 5000, "=B2*2"], ["Всего", "", "=SUM(C2:C2)"]], "Пусто": [["a"]]}
        self.assertIn("Создан", docs.t_create_xlsx("price.xlsx", sheets))
        text = docs.t_read_document("price.xlsx")
        self.assertIn("Лист: Цены", text)
        self.assertIn("A2=Эвакуатор", text)
        self.assertIn("=B2*2", text)
        z = zipfile.ZipFile(self.ws / "price.xlsx")
        for name in z.namelist():
            ET.fromstring(z.read(name))
        try:
            import openpyxl
        except ImportError:
            return
        wb = openpyxl.load_workbook(str(self.ws / "price.xlsx"))
        self.assertEqual(wb.sheetnames, ["Цены", "Пусто"])
        self.assertEqual(wb["Цены"]["C2"].value, "=B2*2")

    def test_bad_xlsx_arguments_are_reported_not_crashed(self):
        self.assertIn("Ошибка", docs.t_create_xlsx("x.xlsx", "не json"))
        self.assertIn("Ошибка", docs.t_create_xlsx("x.xlsx", {}))

    def test_read_file_routes_office_documents(self):
        from pcagent import fileops
        docs.t_create_docx("a.docx", "# Заголовок\nтекст")
        self.assertIn("# Заголовок", fileops.t_read_file("a.docx"))

    def test_creation_can_be_declined(self):
        state.AUTO = False
        from pcagent import fileops
        from unittest import mock
        with mock.patch.object(fileops, "confirm", return_value=False):
            self.assertIn("отклонил", docs.t_create_docx("no.docx", "x"))
        self.assertFalse((self.ws / "no.docx").exists())


class WebSafety(UnitCase):
    def test_private_addresses_are_blocked(self):
        for url in ("http://127.0.0.1:8765/", "http://localhost/", "http://192.168.1.1/",
                    "http://169.254.169.254/latest/meta-data", "file:///etc/passwd", "ftp://example.com/"):
            self.assertFalse(webtools.is_public_url(url), url)
            self.assertIn("Не удалось", webtools.t_fetch_url(url))

    def test_html_to_text_strips_scripts(self):
        out = webtools.html_to_text("<html><head><title>x</title></head><body><h1>Привет</h1><p>мир &amp; все</p><script>bad()</script></body></html>")
        self.assertIn("Привет", out)
        self.assertIn("мир & все", out)
        self.assertNotIn("bad()", out)


if __name__ == "__main__":
    unittest.main()
