"""Prepare versioned coding catalogs from supplied official source files."""
import json
import hashlib
from pathlib import Path
import posixpath
import re
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile
from lxml import etree

BASE = Path(__file__).resolve().parent.parent
ICD10CM_TARGET = BASE / "data" / "coding" / "ICD10CM" / "2027" / "codes.json"
ICD10CM_SOURCE = "icd10cm_codes_2027.txt"
ARCHIVES = {
    "icd10cm-code-descriptions-2027.zip": BASE / "data" / "coding" / "ICD10CM" / "2027",
    "icd10cm-table-and-index-2027.zip": BASE / "data" / "coding" / "ICD10CM" / "2027",
    "hcpcs.zip": BASE / "data" / "coding" / "HCPCS" / "2026_Q4",
}
HCPCS_WORKBOOK = "HCPC2026_OCT_ANWEB.xlsx"
NOC_WORKBOOK = "NOC codes_OCT2026.xlsx"
HCPCS_TARGET = BASE / "data" / "coding" / "HCPCS" / "2026_Q4" / "codes.json"
ICD10CM_TABULAR_TARGET = BASE / "data" / "coding" / "ICD10CM" / "2027" / "tabular.json"
ICD10CM_INDEX_TARGET = BASE / "data" / "coding" / "ICD10CM" / "2027" / "index.json"
NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "officeRel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "packageRel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def _column_index(reference):
    letters = re.match(r"[A-Z]+", reference.upper()).group()
    index = 0
    for letter in letters:
        index = index * 26 + ord(letter) - ord("A") + 1
    return index - 1


def read_xlsx_rows(path):
    """Read the first worksheet using the XLSX standard library container format."""
    with zipfile.ZipFile(path) as workbook:
        shared_strings = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            shared_root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            shared_strings = [
                "".join(node.text or "" for node in item.findall(".//main:t", NS))
                for item in shared_root.findall("main:si", NS)
            ]

        workbook_root = ET.fromstring(workbook.read("xl/workbook.xml"))
        relationships = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
        targets = {
            item.attrib["Id"]: item.attrib["Target"]
            for item in relationships.findall("packageRel:Relationship", NS)
        }
        sheet = workbook_root.find(".//main:sheet", NS)
        if sheet is None:
            return []
        target = targets[sheet.attrib[f"{{{NS['officeRel']}}}id"]]
        sheet_path = target.lstrip("/")
        if not sheet_path.startswith("xl/"):
            sheet_path = posixpath.normpath(posixpath.join("xl", sheet_path))
        sheet_root = ET.fromstring(workbook.read(sheet_path))

        rows = []
        for row in sheet_root.findall(".//main:sheetData/main:row", NS):
            values = {}
            for cell in row.findall("main:c", NS):
                value = cell.find("main:v", NS)
                if value is not None:
                    text = value.text or ""
                    if cell.attrib.get("t") == "s" and text:
                        text = shared_strings[int(text)]
                else:
                    text = "".join(
                        node.text or "" for node in cell.findall(".//main:t", NS)
                    )
                values[_column_index(cell.attrib["r"])] = text.strip()
            rows.append(values)

    header_row = next(
        (
            row for row in rows
            if "HCPC" in {value.upper() for value in row.values()}
            and "LONG DESCRIPTION" in {value.upper() for value in row.values()}
        ),
        None,
    )
    if header_row is None:
        return []
    headers = {column: value.upper() for column, value in header_row.items()}
    return [
        {headers[column]: value for column, value in row.items() if column in headers}
        for row in rows
        if row is not header_row
    ]


def extract_hcpcs_records(rows, procedures_only=True):
    """Keep HCPCS Level II procedure codes, excluding CPT and modifier records."""
    records = {}
    for row in rows:
        code = row.get("HCPC", "").strip().upper()
        if not re.fullmatch(r"[A-CE-Z][0-9]{4}", code):
            continue
        if procedures_only and row.get("RECID", "").strip() != "3":
            continue
        description = row.get("LONG DESCRIPTION", "").strip()
        if not description:
            continue
        short_description = row.get("SHORT DESCRIPTION", "").strip()
        terms = description
        if short_description and short_description.casefold() != description.casefold():
            terms = f"{description}|{short_description}"
        records[code] = {
            "type": "HCPCS",
            "code": code,
            "description": description,
            "terms": terms,
        }
    return records


def extract_icd10cm_records(path):
    """Normalize CMS's 2027 ICD-10-CM code-description text file."""
    records = {}
    with path.open(encoding="utf-8-sig") as source_file:
        for line_number, line in enumerate(source_file, start=1):
            fields = line.split(maxsplit=1)
            if (
                len(fields) != 2
                or not re.fullmatch(r"[A-Z][0-9A-Z]{2,6}", fields[0])
                or not fields[1].strip()
            ):
                raise ValueError(
                    f"Invalid ICD-10-CM record on line {line_number} of {path}"
                )
            code, description = fields[0], fields[1].strip()
            if code in records:
                raise ValueError(f"Duplicate ICD-10-CM code {code} in {path}")
            records[code] = {
                "type": "ICD-10-CM",
                "code": code,
                "description": description,
                "terms": description,
            }
    if not records:
        raise ValueError(f"No ICD-10-CM code descriptions found in {path}")
    return records


TABULAR_NOTE_TAGS = {
    "includes": "includes",
    "excludes1": "excludes1",
    "excludes2": "excludes2",
    "useAdditionalCode": "use_additional_code",
    "codeFirst": "code_first",
    "codeAlso": "code_also",
    "sevenChrDef": "seventh_character",
}


def _xml_tree(source, schema_path=None):
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    tree = etree.parse(str(source), parser)
    if schema_path and Path(schema_path).is_file():
        schema = etree.XMLSchema(etree.parse(str(schema_path), parser))
        schema.assertValid(tree)
    return tree


def _instruction_records(node, source_file, location):
    records = []
    for child in list(node):
        instruction = TABULAR_NOTE_TAGS.get(child.tag)
        if not instruction:
            continue
        texts = [
            " ".join("".join(note.itertext()).split())
            for note in child.findall("note")
        ]
        if not texts:
            texts = [" ".join("".join(child.itertext()).split())]
        records.extend(
            {
                "type": instruction,
                "text": text,
                "source_file": source_file,
                "source_location": location,
            }
            for text in texts if text
        )
    return records


def extract_icd10cm_tabular(path, schema_path=None):
    """Parse hierarchy, billable leaf heuristics, instructions and source paths."""
    path = Path(path)
    tree = _xml_tree(path, schema_path)
    root = tree.getroot()
    records = []
    instructions_by_id = {}

    def intern_instructions(items):
        refs = []
        for item in items:
            identity = json.dumps(item, sort_keys=True, ensure_ascii=False)
            instruction_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
            instructions_by_id[instruction_id] = item
            refs.append(instruction_id)
        return refs

    def visit(node, parents, inherited_refs, chapter, section):
        code = (node.findtext("name") or "").strip() if node.tag == "diag" else ""
        description = " ".join((node.findtext("desc") or "").split())
        local = []
        if node.tag == "diag":
            location = f"diag:{code}"
            local = _instruction_records(node, path.name, location)
        elif node.tag == "chapter":
            chapter = (node.findtext("name") or "").strip()
            local = _instruction_records(node, path.name, f"chapter:{chapter}")
        elif node.tag == "section":
            section = node.attrib.get("id", "")
            local = _instruction_records(node, path.name, f"section:{section}")
        local_refs = intern_instructions(local)
        if node.tag == "diag" and code and description:
            children = node.findall("diag")
            records.append({
                "type": "ICD-10-CM",
                "code": code,
                "description": description,
                "catalog_version": "2027",
                "effective_year": 2027,
                "parent_code": parents[-1] if parents else None,
                "hierarchy": parents + [code],
                "chapter": chapter,
                "section": section,
                "billable": not children,
                "billable_rule": "leaf-entry heuristic",
                "instructions": local,
                "instruction_refs": inherited_refs + local_refs,
                "source_file": path.name,
                "source_location": location,
            })
            parents = parents + [code]
        for child in list(node):
            if child.tag in {"diag", "section"}:
                visit(child, parents, inherited_refs + local_refs, chapter, section)

    for chapter in root.findall("chapter"):
        visit(chapter, [], [], "", "")
    if not records:
        raise ValueError(f"No ICD-10-CM tabular entries found in {path}")
    return {
        "catalog_version": "2027",
        "source_file": path.name,
        "instruction_records": instructions_by_id,
        "codes": records,
    }


def extract_icd10cm_index(path, schema_path=None):
    """Normalize alphabetical, external-cause, drug, and neoplasm index terms."""
    path = Path(path)
    root = _xml_tree(path, schema_path).getroot()
    version = next((item.text for item in root.iter("version") if item.text), "2027")
    records = []

    def walk(node, trail):
        title = " ".join((node.findtext("title") or "").split())
        current = trail + ([title] if title else [])
        codes = []
        direct = node.findtext("code")
        if direct:
            codes.append(direct.strip())
        for cell in node.findall("cell"):
            value = " ".join((cell.text or "").split())
            if value and value not in {"-", "--"}:
                codes.append(value)
        see = [" ".join((item.text or "").split()) for item in node.findall("see")]
        see_also = [" ".join((item.text or "").split()) for item in node.findall("seeAlso")]
        if title or codes or see or see_also:
            records.append({
                "term": " > ".join(current),
                "title": title,
                "codes": list(dict.fromkeys(codes)),
                "see": [item for item in see if item],
                "see_also": [item for item in see_also if item],
                "catalog_version": version,
                "source_file": path.name,
                "source_location": f"entry:{len(records) + 1}",
            })
        for child in list(node):
            if child.tag in {"term", "mainTerm"}:
                walk(child, current)

    for letter in root.findall("letter"):
        for entry in letter.findall("mainTerm"):
            walk(entry, [])
    if not records:
        raise ValueError(f"No ICD-10-CM index entries found in {path}")
    return records


def import_icd10cm_tabular(source):
    source = Path(source)
    tabular = next(iter(source.rglob("icd10cm_tabular_2027.xml")), None)
    if tabular is None:
        return 0
    schema = tabular.with_name("icd10cm_tabular.xsd")
    tabular_catalog = extract_icd10cm_tabular(
        tabular, schema if schema.is_file() else None
    )
    ICD10CM_TABULAR_TARGET.parent.mkdir(parents=True, exist_ok=True)
    ICD10CM_TABULAR_TARGET.write_text(
        json.dumps(tabular_catalog, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    index_files = (
        "icd10cm_index_2027.xml",
        "icd10cm_eindex_2027.xml",
        "icd10cm_drug_2027.xml",
        "icd10cm_neoplasm_2027.xml",
    )
    index_records = []
    for filename in index_files:
        index_path = next(iter(source.rglob(filename)), None)
        if index_path is None:
            continue
        related_schema = index_path.with_name(
            "icd10cm_index.xsd" if "index" in filename else "icd10cm_drug_neoplasm.xsd"
        )
        index_records.extend(extract_icd10cm_index(
            index_path, related_schema if related_schema.is_file() else None
        ))
    if index_records:
        ICD10CM_INDEX_TARGET.parent.mkdir(parents=True, exist_ok=True)
        ICD10CM_INDEX_TARGET.write_text(
            json.dumps(index_records, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    return len(tabular_catalog["codes"])


def import_icd10cm_data(source):
    source_files = sorted(source.rglob(ICD10CM_SOURCE))
    if not source_files:
        return 0

    records = extract_icd10cm_records(source_files[0])
    ICD10CM_TARGET.parent.mkdir(parents=True, exist_ok=True)
    ICD10CM_TARGET.write_text(
        json.dumps(sorted(records.values(), key=lambda item: item["code"]), indent=2),
        encoding="utf-8",
    )
    return len(records)


def import_hcpcs_data(source):
    workbook = source / HCPCS_WORKBOOK
    noc_workbook = source / NOC_WORKBOOK
    records = {}
    if workbook.is_file():
        records.update(extract_hcpcs_records(read_xlsx_rows(workbook)))
    if noc_workbook.is_file():
        records.update(
            extract_hcpcs_records(read_xlsx_rows(noc_workbook), procedures_only=False)
        )
    if not records:
        return 0

    HCPCS_TARGET.parent.mkdir(parents=True, exist_ok=True)
    HCPCS_TARGET.write_text(
        json.dumps(sorted(records.values(), key=lambda item: item["code"]), indent=2),
        encoding="utf-8",
    )
    return len(records)


def main() -> int:
    source = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None
    for target in ARCHIVES.values():
        target.mkdir(parents=True, exist_ok=True)

    if source is None:
        print("Coding-data directories are ready.")
        print("Pass a folder containing the official ZIP archives to copy them in:")
        print("  python scripts/prepare_data.py <archive-folder>")
        return 0

    if not source.is_dir():
        print(f"Archive folder not found: {source}", file=sys.stderr)
        return 1

    copied = 0
    for filename, target in ARCHIVES.items():
        archive = source / filename
        if archive.is_file():
            shutil.copy2(archive, target / filename)
            copied += 1
            print(f"Copied {filename} -> {target.relative_to(BASE)}")

    hcpcs_imported = import_hcpcs_data(source)
    if hcpcs_imported:
        print(f"Prepared {hcpcs_imported} HCPCS Level II procedure codes -> {HCPCS_TARGET.relative_to(BASE)}")
    icd10cm_imported = import_icd10cm_data(source)
    if icd10cm_imported:
        print(f"Prepared {icd10cm_imported} ICD-10-CM codes -> {ICD10CM_TARGET.relative_to(BASE)}")
    tabular_imported = import_icd10cm_tabular(source)
    if tabular_imported:
        print(
            f"Prepared {tabular_imported} ICD-10-CM tabular records and index -> "
            f"{ICD10CM_TABULAR_TARGET.relative_to(BASE)}"
        )
    if not copied and not hcpcs_imported and not icd10cm_imported and not tabular_imported:
        print(f"No supported coding files found in: {source}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
