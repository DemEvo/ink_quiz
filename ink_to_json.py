
# ink_to_json.py — расширенный парсер Ink-подмножества с поддержкой стежков и относительных/полных переходов.

import json
import re
import sys
from typing import List, Dict, Any, Optional

RE_KNOT    = re.compile(r"^===\s*([A-Za-z_]\w*)\s*===$")
RE_STITCH  = re.compile(r"^==\s*([A-Za-z_]\w*)\s*==$")
RE_CHOICE  = re.compile(r"^([+*])\s*(.*?)\s*(?:->\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?))?\s*$")
RE_DIVERT  = re.compile(r"^->\s*(END|DONE|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*$")
RE_VAR     = re.compile(r"^VAR\s+([A-Za-z_]\w*)\s*=\s*(.+?)\s*$")
RE_SET     = re.compile(r"^~\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*$")
RE_CALL    = re.compile(r"^~\s*([A-Za-z_]\w*)\s*\((.*?)\)\s*$")
RE_LIST    = re.compile(r"^LIST\s+([A-Za-z_]\w*)\s*=\s*(.+?)\s*$")
RE_EXTERNAL= re.compile(r"^EXTERNAL\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*$")

def _strip_comments(line: str) -> str:
    pos = line.find("//")
    return line if pos == -1 else line[:pos]

def _apply_glue(lines: List[str]) -> List[str]:
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
            buf += line[:-2]
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
    return expr

def _normalize_target(tgt: Optional[str], current_knot: Optional[str]) -> Optional[str]:
    if not tgt:
        return None
    if tgt in ("END","DONE"):
        return tgt
    if "." in tgt:
        return tgt
    return f"{current_knot}.{tgt}" if current_knot else tgt

def parse_ink_to_json(ink_text: str) -> Dict[str, Any]:
    raw_lines = [_strip_comments(l) for l in ink_text.splitlines()]
    lines = _apply_glue(raw_lines)

    vars_init: Dict[str, Any] = {}
    lists: Dict[str, List[str]] = {}
    externals: List[str] = []

    steps: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []

    current_knot: Optional[str] = None
    current_id: Optional[str] = None
    text_buf: List[str] = []
    choices: List[Dict[str, Any]] = []
    actions: List[Dict[str, Any]] = []
    direct_divert: Optional[str] = None

    def flush_step():
        nonlocal current_id, text_buf, choices, actions, direct_divert
        if current_id is None:
            return
        raw_text = "\n".join([t for t in text_buf if t.strip() != ""])
        step: Dict[str, Any] = {"id": current_id}
        if raw_text:
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
            if direct_divert in ("END","DONE"):
                step["end"] = True
        if actions:
            step["actions"] = actions[:]

        steps[current_id] = step
        if current_id not in order:
            order.append(current_id)
        text_buf.clear(); choices.clear(); actions.clear(); direct_divert = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Топ-уровень директив
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

        # Узлы / стежки
        m = RE_KNOT.match(line)
        if m:
            flush_step()
            current_knot = m.group(1)
            current_id = current_knot
            continue
        m = RE_STITCH.match(line)
        if m:
            flush_step()
            st = m.group(1)
            current_id = f"{current_knot}.{st}" if current_knot else st
            continue

        # Внутри блока
        m = RE_CHOICE.match(line)
        if m:
            mark, body, target = m.groups()
            choices.append({
                "id": f"opt_{len(choices)+1}",
                "text": body.strip(),
                "next": _normalize_target(target, current_knot),
                "repeatable": (mark == "*"),
            })
            continue

        m = RE_DIVERT.match(line)
        if m:
            direct_divert = _normalize_target(m.group(1), current_knot)
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

    # --- Post: auto-divert empty knots to first child stitch (Ink-like entry) ---
    steps_by_id = { s["id"]: s for s in steps.values() }
    def _is_empty(step: dict) -> bool:
        if not step: return True
        return not any([
            step.get("text") or step.get("text_raw") or step.get("speaker"),
            step.get("options"),
            step.get("divert"),
            step.get("end"),
            step.get("actions"),
            step.get("audio"),
        ])
    def _first_child_stitch(knot_id: str):
        prefix = knot_id + "."
        if steps_by_id.get(prefix + "start"): return prefix + "start"
        # use 'order' to pick first child
        try:
            idx = order.index(knot_id)
            for j in range(idx+1, len(order)):
                cid = order[j]
                if cid and cid.startswith(prefix): return cid
                if cid and "." not in cid: break
        except ValueError:
            pass
        # fallback: alphabetical
        kids = sorted([sid for sid in steps_by_id.keys() if sid.startswith(prefix)])
        return kids[0] if kids else None

    for sid, step in list(steps_by_id.items()):
        if "." in sid:
            continue  # only knots (no dot)
        if _is_empty(step):
            child = _first_child_stitch(sid)
            if child:
                step["divert"] = child
                steps_by_id[sid] = step
                steps[sid] = step
    # --- Post: resolve targets using known knots/stitches ---
    knot_names = { sid for sid in steps_by_id.keys() if '.' not in sid }
    def _src_knot_of(step_id: str) -> str:
        return step_id.split('.')[0] if '.' in step_id else step_id
    def _resolve_target_late(src_step_id: str, tgt: str) -> str:
        if not tgt or tgt in ('END','DONE'): return tgt
        # exact id
        if tgt in steps_by_id: return tgt
        # if dotted but missing -> maybe right part is a knot id
        if '.' in tgt:
            left, right = tgt.split('.', 1)
            if right in steps_by_id and '.' not in right:
                return right
        # no dot: prefer knot if exists
        if '.' not in tgt and tgt in knot_names:
            return tgt
        # else, try relative stitch under source knot
        sk = _src_knot_of(src_step_id)
        cand = f"{sk}.{tgt}"
        if cand in steps_by_id: return cand
        return tgt  # leave as-is (will show runtime 'Нет шага' if wrong)
    # apply to all steps
    for sid, step in list(steps_by_id.items()):
        if 'options' in step and isinstance(step['options'], list):
            for opt in step['options']:
                opt['next'] = _resolve_target_late(sid, opt.get('next'))
        if 'divert' in step:
            step['divert'] = _resolve_target_late(sid, step.get('divert'))


    return {
        "format": "ink-json/v3",
        "vars": vars_init,
        "lists": lists,
        "externals": externals,
        "order": order,
        "steps": list(steps.values()),
    }

def _main():
    ink_text = sys.stdin.read()
    data = parse_ink_to_json(ink_text)
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    _main()
