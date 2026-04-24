"""
文本/代码分块模块。

文件类型 → 分块策略：
  PDF/DOCX/TXT  : 段落 + 句子边界滑窗
  MD            : 按 ## 标题级别分节
  INI/CFG       : 按 [section] 分块
  C/CPP         : 花括号深度状态机（含函数前注释回溯）
  H/HPP         : 专用头文件分块（struct/enum/typedef/宏/函数声明）
  Python        : ast 模块提取函数/类
  其他代码       : 空行分隔逻辑块
"""

from __future__ import annotations

import ast
import re
from typing import Optional

from config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    CODE_CHUNK_SIZE,
    CODE_EXTENSIONS,
    MIN_CHUNK_LENGTH,
)

# ── 句子边界（用于文本分块）─────────────────────────────────────────────────
_SENTENCE_END = re.compile(
    r"[\u3002\uff01\uff1f\u2026\.!\?][\u201d\u300d\u300f]?"
)
_PARA_SEP = re.compile(r"\n{2,}|\n---+\n|\n===+\n")

# Markdown 标题（最多三级）
_MD_HEADING = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)

# INI section 行
_INI_SECTION = re.compile(r"^\[([^\]]+)\]", re.MULTILINE)

# 头文件分块用正则
_H_TYPEDEF_STRUCT = re.compile(
    r"typedef\s+struct\s*\w*\s*\{[^}]*\}\s*\w+\s*;", re.DOTALL
)
_H_TYPEDEF_ENUM = re.compile(
    r"typedef\s+enum\s*\w*\s*\{[^}]*\}\s*\w+\s*;", re.DOTALL
)
_H_DEFINE_LINE = re.compile(r"^#define\s+\S+", re.MULTILINE)
_H_FUNC_DECL = re.compile(
    r"^[\w\s\*\[\]]+\s+\w+\s*\([^;{]*\)\s*;", re.MULTILINE
)


# ── 公共入口 ─────────────────────────────────────────────────────────────────

def chunk_document(
    text: str,
    language: Optional[str] = None,
    file_name: str = "",
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
    min_length: int = MIN_CHUNK_LENGTH,
) -> list[str]:
    """
    根据语言/文件类型选择分块策略。

    Args:
        text:          原始文本内容
        language:      文件扩展名（不含点），None 或空字符串表示纯文本
        file_name:     文件名，注入到 chunk 头部
        chunk_size:    文本分块最大字符数
        chunk_overlap: 文本分块重叠字符数
        min_length:    丢弃短于此长度的 chunk
    """
    if not text or not text.strip():
        return []

    ext = (language or "").lower().lstrip(".")

    # 头文件专用策略
    if ext in ("h", "hpp", "hh"):
        chunks = _chunk_header_file(text, file_name)

    # C/C++ 源文件（花括号 + 注释回溯）
    elif ext in ("c", "cpp", "cc", "cxx"):
        chunks = _chunk_c_cpp(text, file_name)

    # Python（AST）
    elif ext in ("py", "pyw"):
        chunks = _chunk_python(text, file_name)

    # Markdown（按标题分节）
    elif ext == "md":
        chunks = _chunk_markdown(text, file_name, chunk_size, chunk_overlap)

    # INI/CFG（按 section 分块）
    elif ext in ("ini", "cfg"):
        chunks = _chunk_ini(text, file_name)

    # 其余代码文件（空行分隔）
    elif ext in {e.lstrip(".") for e in CODE_EXTENSIONS} - {
        "h", "hpp", "hh", "c", "cpp", "cc", "cxx", "py", "pyw"
    }:
        chunks = _chunk_generic_code(text, file_name, CODE_CHUNK_SIZE)

    # 纯文本/文档
    else:
        chunks = chunk_text(text, chunk_size, chunk_overlap, min_length)
        return chunks

    return [c for c in chunks if len(c.strip()) >= min_length]


# ── 文本分块（对外保留兼容）────────────────────────────────────────────────

def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
    min_length: int = MIN_CHUNK_LENGTH,
) -> list[str]:
    """按段落边界 + 句子边界滑窗切割纯文本。"""
    if not text or not text.strip():
        return []

    paragraphs = _PARA_SEP.split(text)
    raw_chunks: list[str] = []

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) <= chunk_size:
            raw_chunks.append(para)
        else:
            raw_chunks.extend(_sliding_window(para, chunk_size, chunk_overlap))

    return [c for c in raw_chunks if len(c) >= min_length]


# ── Markdown 分块 ─────────────────────────────────────────────────────────

def _chunk_markdown(
    text: str,
    file_name: str,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """
    按 #/##/### 标题级别分节，每节作为一个 chunk。
    超长节再做二次滑窗切割。
    """
    lines = text.splitlines(keepends=True)
    chunks: list[str] = []
    current_heading = f"# File: {file_name}"
    current_lines: list[str] = []

    def flush() -> None:
        if not current_lines:
            return
        body = "".join(current_lines).strip()
        if not body:
            return
        full = current_heading + "\n" + body
        if len(full) > chunk_size:
            for sub in _sliding_window(full, chunk_size, chunk_overlap):
                chunks.append(sub)
        else:
            chunks.append(full)

    for line in lines:
        m = _MD_HEADING.match(line.rstrip())
        if m:
            flush()
            current_lines = []
            level_prefix = "#" * len(m.group(1))
            current_heading = f"# File: {file_name} | {level_prefix} {m.group(2)}"
            current_lines.append(line)
        else:
            current_lines.append(line)

    flush()
    return chunks if chunks else [text]


# ── INI/CFG 分块 ──────────────────────────────────────────────────────────

def _chunk_ini(text: str, file_name: str, max_section_size: int = 2000) -> list[str]:
    """
    按 [section] 边界分块，每节作为一个独立 chunk。
    超长节二次切割，保留 section 名作为上下文。
    """
    lines = text.splitlines(keepends=True)
    chunks: list[str] = []
    current_section = ""
    current_lines: list[str] = []

    def flush(section: str, sec_lines: list[str]) -> None:
        body = "".join(sec_lines).strip()
        if not body:
            return
        hdr = (f"# File: {file_name} | [{section}]\n" if section
               else f"# File: {file_name}\n")
        full = hdr + body
        if len(full) <= max_section_size:
            chunks.append(full)
            return
        batch: list[str] = []
        batch_len = 0
        for sl in body.splitlines(keepends=True):
            batch.append(sl)
            batch_len += len(sl)
            if batch_len >= max_section_size - len(hdr):
                chunks.append(hdr + "".join(batch).strip())
                batch, batch_len = [], 0
        if batch:
            chunks.append(hdr + "".join(batch).strip())

    for line in lines:
        m = _INI_SECTION.match(line)
        if m:
            flush(current_section, current_lines)
            current_section = m.group(1)
            current_lines = [line]
        else:
            current_lines.append(line)

    flush(current_section, current_lines)
    return chunks if chunks else [text]


# ── 头文件（.h/.hpp）专用分块 ─────────────────────────────────────────────

def _chunk_header_file(text: str, file_name: str) -> list[str]:
    """
    专用头文件分块：
      1. typedef struct { ... } Name;
      2. typedef enum { ... } Name;
      3. 函数声明行按最多 20 行一组
      4. #define 宏连续块（>=2 行）
      5. 文件头部（include/pragma/注释）
    """
    chunks: list[str] = []
    file_hdr = f"// File: {file_name}"
    covered: set[int] = set()

    for m in _H_TYPEDEF_STRUCT.finditer(text):
        block = m.group(0).strip()
        name_m = re.search(r"}\s*(\w+)\s*;$", block)
        name = name_m.group(1) if name_m else "struct"
        chunks.append(f"{file_hdr} | typedef struct {name}\n{block}")
        covered.update(range(m.start(), m.end()))

    for m in _H_TYPEDEF_ENUM.finditer(text):
        if any(i in covered for i in range(m.start(), m.end())):
            continue
        block = m.group(0).strip()
        name_m = re.search(r"}\s*(\w+)\s*;$", block)
        name = name_m.group(1) if name_m else "enum"
        chunks.append(f"{file_hdr} | typedef enum {name}\n{block}")
        covered.update(range(m.start(), m.end()))

    lines = text.splitlines()
    decl_lines: list[str] = []
    for line in lines:
        if _H_FUNC_DECL.match(line.strip()):
            decl_lines.append(line)

    GROUP = 20
    for i in range(0, len(decl_lines), GROUP):
        body = "\n".join(decl_lines[i:i + GROUP])
        chunks.append(f"{file_hdr} | function declarations\n{body}")

    define_groups: list[list[str]] = []
    current_def: list[str] = []
    for line in lines:
        if _H_DEFINE_LINE.match(line.strip()):
            current_def.append(line)
        else:
            if current_def:
                define_groups.append(current_def)
                current_def = []
    if current_def:
        define_groups.append(current_def)

    for grp in define_groups:
        if len(grp) >= 2:
            chunks.append(f"{file_hdr} | #define macros\n" + "\n".join(grp))

    head_lines = [
        l for l in lines
        if l.strip().startswith(("#include", "#pragma", "#ifndef", "#ifdef",
                                  "#endif", "extern", "//", "/*", "*"))
    ]
    if head_lines:
        chunks.insert(0, f"{file_hdr} | file header\n" + "\n".join(head_lines))

    return chunks if chunks else [text]


# ── C/C++ 源文件分块 ──────────────────────────────────────────────────────

def _extract_c_func_name(block_lines: list[str]) -> str:
    """从块的非注释行中提取函数名（'(' 前的最后一个标识符）。"""
    for line in block_lines:
        s = line.strip()
        if not s or s.startswith(("#", "//", "/*", "*")):
            continue
        m = re.search(r"\b([A-Za-z_]\w*)\s*\(", s)
        if m:
            return m.group(1)
    return ""


def _chunk_c_cpp(text: str, file_name: str) -> list[str]:
    """
    按函数/结构体/枚举边界分块，函数体前的注释块一并纳入同一 chunk。
    """
    lines = text.splitlines(keepends=True)
    chunks: list[str] = []
    header_lines: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith(("#include", "#define", "#ifndef", "#ifdef",
                                 "#endif", "#pragma", "typedef", "//", "/*", "*")):
            header_lines.append(line)
            i += 1
        else:
            break

    if header_lines:
        chunks.append(
            f"/* File: {file_name} — 头部声明 */\n" + "".join(header_lines).strip()
        )

    block_start = i
    block_lines: list[str] = []
    depth = 0
    in_block = False

    while i < len(lines):
        line = lines[i]
        block_lines.append(line)

        for ch in line:
            if ch == "{":
                depth += 1
                in_block = True
            elif ch == "}":
                depth -= 1

        if in_block and depth == 0:
            # 回溯函数前注释
            comment_prefix: list[str] = []
            j = block_start - 1
            while j >= len(header_lines):
                prev = lines[j].strip()
                if prev.startswith(("//", "/*", "*")) or prev == "*/":
                    comment_prefix.insert(0, lines[j])
                    j -= 1
                else:
                    break

            block_text = ("".join(comment_prefix) + "".join(block_lines)).strip()
            if block_text:
                func_name = _extract_c_func_name(block_lines)
                suffix = f" | Func: {func_name}" if func_name else ""
                full = f"/* File: {file_name}{suffix} */\n" + block_text
                if len(full) > 3000:
                    chunks.extend(_split_large_block(full))
                else:
                    chunks.append(full)

            block_start = i + 1
            block_lines = []
            in_block = False

        i += 1

    if block_lines:
        tail = "".join(block_lines).strip()
        if tail:
            chunks.append(f"/* File: {file_name} */\n" + tail)

    return chunks if chunks else [text]


def _split_large_block(text: str, size: int = 2000, overlap: int = 200) -> list[str]:
    """对超长函数体做行级滑窗二次切割，保持行完整性。"""
    lines = text.splitlines(keepends=True)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        current.append(line)
        current_len += len(line)
        if current_len >= size:
            chunks.append("".join(current).strip())
            overlap_lines: list[str] = []
            acc = 0
            for ol in reversed(current):
                if acc >= overlap:
                    break
                overlap_lines.insert(0, ol)
                acc += len(ol)
            current = overlap_lines
            current_len = sum(len(l) for l in current)

    if current:
        tail = "".join(current).strip()
        if tail:
            chunks.append(tail)

    return chunks


# ── Python 代码分块 ───────────────────────────────────────────────────────

def _chunk_python(text: str, file_name: str) -> list[str]:
    """用 ast 模块提取顶层函数和类，每个定义为一个 chunk。"""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _chunk_generic_code(text, file_name)

    lines = text.splitlines()
    chunks: list[str] = []
    covered_lines: set[int] = set()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if getattr(node, "col_offset", 0) != 0:
            continue

        start = node.lineno - 1
        end = getattr(node, "end_lineno", start + 1)
        block = "\n".join(lines[start:end])
        kind = "class" if isinstance(node, ast.ClassDef) else "def"
        header = f"# File: {file_name} | {kind} {node.name} (L{node.lineno}-{end})\n"
        chunks.append(header + block)
        covered_lines.update(range(start, end))

    module_lines = [l for idx, l in enumerate(lines) if idx not in covered_lines]
    module_text = "\n".join(module_lines).strip()
    if module_text:
        chunks.insert(0, f"# File: {file_name} | module-level\n" + module_text)

    return chunks if chunks else [text]


# ── 通用代码分块（Shell/YAML/JSON/Makefile 等）──────────────────────────────

def _chunk_generic_code(
    text: str, file_name: str, max_size: int = CODE_CHUNK_SIZE
) -> list[str]:
    """按空行分隔的逻辑块切割，超长块再二次切割。"""
    header = f"# File: {file_name}\n"
    blocks = re.split(r"\n{2,}", text)
    chunks: list[str] = []
    current_lines: list[str] = []
    current_len = 0

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if current_len + len(block) > max_size and current_lines:
            chunks.append(header + "\n\n".join(current_lines))
            current_lines = []
            current_len = 0
        current_lines.append(block)
        current_len += len(block)

    if current_lines:
        chunks.append(header + "\n\n".join(current_lines))

    return chunks if chunks else [text]


# ── 内部滑窗工具 ─────────────────────────────────────────────────────────────

def _sliding_window(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            end = _snap_to_sentence_end(text, end, window=50)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = max(end - chunk_overlap, start + 1)
    return chunks


def _snap_to_sentence_end(text: str, pos: int, window: int = 50) -> int:
    length = len(text)
    for i in range(pos, min(pos + window, length)):
        if _SENTENCE_END.match(text, i):
            return i + 1
    for i in range(pos - 1, max(pos - window, 0) - 1, -1):
        if _SENTENCE_END.match(text, i):
            return i + 1
    return pos
