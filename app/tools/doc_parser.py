"""文档解析工具：支持 TXT / MD / PDF / DOCX / IPYNB 等格式。"""

from pathlib import Path


def parse_document(file_path: str) -> dict:
    """解析文档，返回 title, content, file_type。"""
    fp = Path(file_path)
    if not fp.exists():
        return {"title": "", "content": "", "file_type": "", "error": f"文件不存在: {file_path}"}

    suffix = fp.suffix.lower()
    title = fp.stem
    try:
        if suffix in (".txt", ".md", ".py", ".java", ".cpp", ".c", ".h", ".js", ".ts", ".html", ".css", ".xml", ".json", ".yaml", ".yml"):
            content = fp.read_text(encoding="utf-8")
            return {"title": title, "content": content, "file_type": suffix}

        elif suffix == ".pdf":
            return _parse_pdf(fp)

        elif suffix == ".docx":
            return _parse_docx(fp)

        elif suffix == ".ipynb":
            return _parse_ipynb(fp)

        else:
            try:
                content = fp.read_text(encoding="utf-8")
                return {"title": title, "content": content, "file_type": suffix}
            except Exception:
                return {"title": title, "content": "", "file_type": suffix,
                        "error": f"不支持的文件格式: {suffix}"}
    except Exception as e:
        return {"title": title, "content": "", "file_type": suffix, "error": str(e)}


def _parse_pdf(fp: Path) -> dict:
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        return {"title": fp.stem, "content": "", "file_type": ".pdf",
                "error": "PyPDF2 未安装"}
    reader = PdfReader(str(fp))
    content = "\n".join(page.extract_text() or "" for page in reader.pages)
    return {"title": fp.stem, "content": content, "file_type": ".pdf"}


def _parse_docx(fp: Path) -> dict:
    try:
        from docx import Document
    except ImportError:
        return {"title": fp.stem, "content": "", "file_type": ".docx",
                "error": "python-docx 未安装"}
    doc = Document(str(fp))
    content = "\n".join(p.text for p in doc.paragraphs)
    return {"title": fp.stem, "content": content, "file_type": ".docx"}


def _parse_ipynb(fp: Path) -> dict:
    import json
    raw = json.loads(fp.read_text(encoding="utf-8"))
    cells = raw.get("cells", [])
    lines = []
    for cell in cells:
        source = cell.get("source", [])
        if isinstance(source, list):
            lines.extend(source)
        else:
            lines.append(str(source))
    content = "\n".join(lines)
    return {"title": fp.stem, "content": content, "file_type": ".ipynb"}
