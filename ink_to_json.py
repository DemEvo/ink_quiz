# ink_to_json.py
# Чистый парсер подмножества Ink → JSON-структуры.
# API:
#   parse_ink_to_json(ink_text: str) -> dict
#
# CLI (без файлов):  cat story.ink | python -m ink_to_json > story.json

import json
import re
import sys
from typing import List, Dict, Any

RE_KNOT = re.compile(r"^===\s*([A-Za-z_]\w*)\s*===$")
RE_CHOICE = re.compile(r"^([+*])\s*(.*?)\s*(?:->\s*([A-Za-z_]\w*))?\s*$")
RE_DIVERT = re.compile(r"^->\s*(END|DONE|[A-Za-z_]\w*)\s*$")
RE_VAR = re.compile(r"^VAR\s+([A-Za-z_]\w*)\s*=\s*(.+?)\s*$")
RE_SET = re.compile(r"^~\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*$")
RE_CALL = re.compile(r"^~\s*([A-Za-z_]\w*)\s*\((.*?)\)\s*$")
RE_LIST = re.compile(r"^LIST\s+([A-Za-z_]\w*)\s*=\s*(.+?)\s*$")
RE_EXTERNAL = re.compile(r"^EXTERNAL\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*$")

def _strip_comments(line: str) -> str:
    pos = line.find("//")
    return line if pos == -1 else line[:pos]

def _apply_glue(lines: List[str]) -> List[str]:
    """Склеивает строки с <> (glue)."""
    out, buf = [], ""
    for raw in lines:
        line = raw.rstrip()
        if not line:
            if buf:
                out.append(buf)
                buf = ""
            out.append("")
            continue
        if line.endswith("<>"):
            buf += line[:-2]  # без переноса
        else:
            buf += line
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out

def _parse_value(expr: str):
    expr = expr.strip()
    if re.fullmatch(r"-?\d+", expr): return int(expr)
    if re.fullmatch(r"-?\d+\.\d+", expr): return float(expr)
    m = re.match(r'^"(.*)"$', expr) or re.match(r"^'(.*)'$", expr)
    if m: return m.group(1)
    if expr.lower() in ("true", "false"): return expr.lower() == "true"
    return expr  # идентификатор/выражение

def parse_ink_to_json(ink_text: str) -> Dict[str, Any]:
    """Главная функция: на вход — текст Ink, на выход — JSON-модель (dict)."""
    raw_lines = [_strip_comments(l) for l in ink_text.splitlines()]
    lines = _apply_glue(raw_lines)

    vars_init: Dict[str, Any] = {}
    lists: Dict[str, List[str]] = {}
    externals: List[str] = []

    steps: Dict[str, Dict[str, Any]] = {}
    current_id = None
    text_buf: List[str] = []
    choices: List[Dict[str, Any]] = []
    actions: List[Dict[str, Any]] = []
    direct_divert = None

    def flush_step():
        nonlocal current_id, text_buf, choices, actions, direct_divert
        if current_id is None:
            return
        raw_text = "\n".join([t for t in text_buf if t.strip() != ""])
        step: Dict[str, Any] = {"id": current_id}
        if raw_text:
            # извлечём speaker: "Имя: текст" (многострочно)
            m = re.match(r"^\s*([^:\n]+):\s*(.*)$", raw_text, flags=re.DOTALL)
            if m:
                step["speaker"] = m.group(1).strip()
                step["text"] = m.group(2).strip()
            else:
                step["text"] = raw_text
            step["text_raw"] = raw_text

        if choices:
            step["options"] = choices[:]
        if direct_divert:
            step["divert"] = direct_divert
            if direct_divert in ("END", "DONE"):
                step["end"] = True
        if actions:
            step["actions"] = actions[:]

        steps[current_id] = step
        text_buf.clear(); choices.clear(); actions.clear(); direct_divert = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # верхнеуровневые директивы
        m = RE_VAR.match(line)
        if m:
            vars_init[m.group(1)] = _parse_value(m.group(2)); continue
        m = RE_LIST.match(line)
        if m:
            lists[m.group(1)] = [s.strip() for s in m.group(2).split(",") if s.strip()]; continue
        m = RE_EXTERNAL.match(line)
        if m:
            fn = m.group(1)
            if fn not in externals: externals.append(fn)
            continue

        # блок
        m = RE_KNOT.match(line)
        if m:
            flush_step()
            current_id = m.group(1)
            continue

        # строки внутри блока
        m = RE_CHOICE.match(line)
        if m:
            mark, body, target = m.groups()
            choices.append({
                "id": f"opt_{len(choices)+1}",
                "text": body.strip(),
                "next": target if target else None,
                "repeatable": (mark == "*"),
            })
            continue

        m = RE_DIVERT.match(line)
        if m:
            direct_divert = m.group(1)
            continue

        m = RE_SET.match(line)
        if m:
            actions.append({"type": "set", "var": m.group(1), "expr": m.group(2).strip()})
            continue
        m = RE_CALL.match(line)
        if m:
            actions.append({"type": "call", "fn": m.group(1), "args": m.group(2).strip()})
            continue

        # обычный текст
        text_buf.append(line)

    flush_step()

    return {
        "format": "ink-subset-json/v2",
        "vars": vars_init,
        "lists": lists,
        "externals": externals,
        "steps": list(steps.values()),
    }

# --- CLI: читает Ink из stdin, пишет JSON в stdout ---
def _main():
    ink_text = sys.stdin.read()
    data = parse_ink_to_json(ink_text)
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    _main()

# from ink_to_json import parse_ink_to_json
# json_obj = parse_ink_to_json(ink_text)  # ink_text: str

# cat test.ink | python -m ink_to_json > out.json