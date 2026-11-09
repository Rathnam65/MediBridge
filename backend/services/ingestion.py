"""Bounded text extraction for supported clinical document formats."""
from io import BytesIO
import json
from pathlib import Path
import zipfile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from lxml.etree import XMLSyntaxError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_DOCUMENT_BYTES = 10_000_000
MAX_DOCX_UNCOMPRESSED_BYTES = 40_000_000


def _text_locations(parts, locator_name):
    text_parts = []
    locations = []
    offset = 0
    for locator, value in parts:
        value = value.strip()
        if not value:
            continue
        if text_parts:
            offset += 1
        start = offset
        text_parts.append(value)
        offset += len(value)
        locations.append({
            locator_name: locator,
            "start": start,
            "end": offset,
        })
    return "\n".join(text_parts), locations


def _extract_pdf(content):
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise ValueError("Password-protected PDF files are not supported.")
        pages = []
        for page_number, page in enumerate(reader.pages, start=1):
            pages.append((page_number, page.extract_text() or ""))
    except ValueError:
        raise
    except (OSError, PdfReadError) as error:
        raise ValueError(f"Unable to read PDF document: {error}") from error
    text, locations = _text_locations(pages, "page")
    return text, locations


def _extract_docx(content):
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise ValueError("Expanded DOCX document exceeds the 40 MB safety limit.")
            if "word/document.xml" not in archive.namelist():
                raise ValueError("File is not a valid DOCX document.")
            if archive.testzip() is not None:
                raise ValueError("DOCX archive contains a corrupt member.")
        document = Document(BytesIO(content))
        paragraphs = [
            (index, paragraph.text)
            for index, paragraph in enumerate(document.paragraphs, start=1)
        ]
    except (zipfile.BadZipFile, PackageNotFoundError, XMLSyntaxError, KeyError) as error:
        raise ValueError("File is not a valid DOCX document.") from error
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"Unable to read DOCX document: {error}") from error
    text, locations = _text_locations(paragraphs, "paragraph")
    return text, locations


def extract_document_text(filename, content):
    """Extract plain text and original source locations from an upload."""
    suffix = Path(filename).suffix.lower()
    if len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError("Files must be 10 MB or smaller.")
    if suffix == ".pdf":
        text, locations = _extract_pdf(content)
    elif suffix == ".docx":
        text, locations = _extract_docx(content)
    elif suffix == ".json":
        try:
            text = json.dumps(json.loads(content.decode("utf-8")), indent=2)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("The uploaded JSON file is not valid UTF-8 JSON.") from error
        locations = [{"document": filename, "start": 0, "end": len(text)}] if text else []
    elif suffix in {".txt", ".md", ".csv", ".log"}:
        text = content.decode("utf-8", errors="ignore")
        locations = [{"document": filename, "start": 0, "end": len(text)}] if text else []
    else:
        raise ValueError(
            "Upload TXT, JSON, Markdown, CSV, LOG, PDF, or DOCX files."
        )
    if len(text.strip()) < 10:
        raise ValueError("The uploaded document must contain at least 10 characters of text.")
    return text, locations
