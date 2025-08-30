# ink_validator.py
import re
from typing import List, Dict, Tuple, Set, Any

# --------- Имена и заголовки ---------
NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')  # только латиница/цифры/_
RESERVED = {'END', 'DONE'}

# Строго: узел — ровно три "=", стежок — ровно два "="
KNOT_HDR_RE   = re.compile(r'^\s*===\s*([A-Za-z_][A-Za-z0-9_]*)\s*===\s*$')
STITCH_HDR_RE = re.compile(r'^\s*==\s*([A-Za-z_][A-Za-z0-9_]*)\s*==\s*$')

# Для ловли "похожих" заголовков с неправильным именем (например seat.one)
KNOT_LOOKS_LIKE_RE   = re.compile(r'^\s*===\s*(.+?)\s*===\s*$')
STITCH_LOOKS_LIKE_RE = re.compile(r'^\s*==\s*(.+?)\s*==\s*$')

# --------- Остальные конструкции ---------
# choice: требуем → target, цель может быть узлом или стежком; END/DONE допустимы
RE_CHOICE = re.compile(r'^([+*])\s*(.*?)\s*(?:->\s*((?:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)|END|DONE))\s*$')
RE_DIVERT = re.compile(r'^->\s*((?:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)|END|DONE)\s*$')

RE_VAR = re.compile(r'^VAR\s+([A-Za-z_]\w*)\s*=\s*(.+?)\s*$')
RE_SET = re.compile(r'^~\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*$')

RE_EXTERNAL = re.compile(r'^EXTERNAL\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*$')
RE_CALL = re.compile(r'^~\s*([A-Za-z_]\w*)\s*\((.*?)\)\s*$')

RE_LIST = re.compile(r'^LIST\s+([A-Za-z_]\w*)\s*=\s*(.+?)\s*$')

RE_INLINE_VAR = re.compile(r'\{([A-Za-z_]\w*)\}')
RE_INLINE_TERNARY = re.compile(r'\{([^{}?:|]+?)\?\s*([^{}|]+?)\s*\|\s*([^{}]+?)\}')

def _strip_comments(line: str) -> str:
    pos = line.find('//')
    return line if pos == -1 else line[:pos]

class InkValidator:
    def __init__(self, text: str):
        self.text = text
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.infos: List[str] = []

        self.knots: Set[str] = set()
        self.stitches: Set[str] = set()  # полные имена knot.stitch
        self.vars: Set[str] = set()
        self.externals: Dict[str, int] = {}
        self.lists: Set[str] = set()

        self.links: List[Tuple[str, str, int]] = []  # (src_knot, target, line)

    def add_error(self, ln: int, msg: str): self.errors.append(f"[{ln}] {msg}")
    def add_warn(self, ln: int, msg: str):  self.warnings.append(f"[{ln}] {msg}")
    def add_info(self, ln: int, msg: str):  self.infos.append(f"[{ln}] {msg}")

    # --- проверка существования цели ---
    def _target_exists(self, src_knot: str, tgt: str) -> bool:
        t = (tgt or '').strip()
        if not t:
            return False
        if t.upper() in RESERVED:
            return True
        if '.' in t:
            # абсолютный стежок
            return (t in self.stitches) or (t in self.knots)
        # без точки: либо узел, либо относительный стежок текущего узла
        if t in self.knots:
            return True
        if src_knot:
            rel = f"{src_knot}.{t}"
            return rel in self.stitches
        return False

    def validate(self) -> Dict[str, Any]:
        current_knot: str | None = None

        lines = [_strip_comments(l).rstrip() for l in self.text.splitlines()]

        for ln, raw in enumerate(lines, start=1):
            line = raw.strip()
            if not line:
                continue

            # --- заголовок узла ---
            m = KNOT_HDR_RE.match(line)
            if m:
                name = m.group(1)
                if name.upper() in RESERVED:
                    self.add_error(ln, f"Имя узла '{name}' зарезервировано. Используйте '-> {name}' вместо '=== {name} ==='.")
                self.knots.add(name)
                current_knot = name
                continue
            # Похоже на узел, но имя неверное (например seat.one)
            m = KNOT_LOOKS_LIKE_RE.match(line)
            if m:
                bad = m.group(1).strip()
                if '.' in bad:
                    self.add_error(ln, f"Недопустимая точка в имени узла '{bad}'. Правильно: '=== seat ===' и внутри '== one ==', а переходы — '-> seat.one'.")
                elif not NAME_RE.match(bad):
                    self.add_error(ln, f"Некорректное имя узла '{bad}'. Разрешено: [A-Za-z_][A-Za-z0-9_]*.")
                else:
                    # сюда почти не попадём, но на всякий случай
                    self.add_error(ln, f"Некорректный заголовок узла: '{line}'")
                # не переключаем current_knot
                continue

            # --- заголовок стежка ---
            m = STITCH_HDR_RE.match(line)
            if m:
                st = m.group(1)
                if current_knot is None:
                    self.add_error(ln, f"Стежок '{st}' объявлен вне узла. Стежки допустимы только внутри узла.")
                else:
                    self.stitches.add(f"{current_knot}.{st}")
                continue
            # Похоже на стежок, но имя неверное
            m = STITCH_LOOKS_LIKE_RE.match(line)
            if m:
                bad = m.group(1).strip()
                if current_knot is None:
                    self.add_error(ln, f"Стежок '{bad}' объявлен вне узла.")
                elif not NAME_RE.match(bad):
                    self.add_error(ln, f"Некорректное имя стежка '{bad}'. Разрешено: [A-Za-z_][A-Za-z0-9_]*.")
                else:
                    self.add_error(ln, f"Некорректный заголовок стежка: '{line}'")
                continue

            # --- декларации VAR/LIST/EXTERNAL ---
            m = RE_VAR.match(line)
            if m:
                name = m.group(1)
                if name in self.vars:
                    self.add_error(ln, f"Повторное объявление переменной '{name}'.")
                self.vars.add(name)
                continue

            m = RE_LIST.match(line)
            if m:
                list_name = m.group(1)
                items = [x.strip() for x in m.group(2).split(",") if x.strip()]
                if not items:
                    self.add_error(ln, f"Пустой LIST '{list_name}'.")
                continue

            m = RE_EXTERNAL.match(line)
            if m:
                fn = m.group(1)
                args = m.group(2)
                argc = 0 if not args.strip() else len([a.strip() for a in args.split(",") if a.strip()])
                prev = getattr(self, "externals", {})
                if fn in prev and prev[fn] != argc:
                    self.add_error(ln, f"EXTERNAL '{fn}' объявлен с другим числом аргументов (было {prev[fn]}, теперь {argc}).")
                self.externals[fn] = argc
                continue

            # --- вне узла нельзя делать переходы/варианты/действия ---
            if current_knot is None:
                if RE_CHOICE.match(line) or RE_DIVERT.match(line) or RE_SET.match(line) or RE_CALL.match(line):
                    self.add_error(ln, "Конструкция допустима только внутри узла (обнаружено вне узла).")
                # остальной текст вне узла допустим (например, шапка сценария)
                continue

            # --- внутри узла: варианты, диверты, действия, инлайны ---
            m = RE_CHOICE.match(line)
            if m:
                mark, body, tgt = m.groups()
                if tgt is None or not tgt.strip():
                    self.add_error(ln, "Вариант без '-> target'.")
                else:
                    self.links.append((current_knot, tgt.strip(), ln))
                continue

            m = RE_DIVERT.match(line)
            if m:
                tgt = m.group(1).strip()
                if tgt.upper() not in RESERVED:
                    self.links.append((current_knot, tgt, ln))
                continue

            m = RE_SET.match(line)
            if m:
                var = m.group(1)
                if var not in self.vars:
                    self.add_error(ln, f"Присваивание в необъявленную переменную '{var}' (объявите через VAR).")
                continue

            m = RE_CALL.match(line)
            if m:
                fn = m.group(1)
                args = m.group(2)
                argc = 0 if not args.strip() else len([a.strip() for a in args.split(",") if a.strip()])
                if fn not in self.externals:
                    self.add_error(ln, f"Вызов внешней функции '{fn}' без EXTERNAL.")
                else:
                    declared = self.externals[fn]
                    if declared != argc:
                        self.add_error(ln, f"Неверное число аргументов в '{fn}': {argc}, ожидалось {declared}.")
                continue

            if "{" in line and "}" in line:
                for name in RE_INLINE_VAR.findall(line):
                    if name not in self.vars:
                        self.add_error(ln, f"Подстановка '{{{name}}}' без VAR-объявления.")
                for _cond, _yes, _no in RE_INLINE_TERNARY.findall(line):
                    for ident in re.findall(r"\b([A-Za-z_]\w*)\b", _cond):
                        if ident in ("true", "false", "null"):
                            continue
                        if ident not in self.vars:
                            self.add_error(ln, f"Условие использует необъявленную переменную '{ident}'.")
                continue

            # Glue считаем информацией
            if "<>" in line:
                self.add_info(ln, "Используется glue '<>'.")
                continue

        # --- постпроверки ---
        if "start" not in self.knots:
            self.errors.append("Отсутствует обязательный узел 'start'.")

        for src, tgt, ln in self.links:
            if not self._target_exists(src, tgt):
                self.add_error(ln, f"Переход из '{src}' в несуществующую цель '{tgt}'.")

        return {
            "errors": self.errors,
            "warnings": self.warnings,
            "infos": self.infos,
            "blocks": sorted(self.knots),
            "stitches": sorted(self.stitches),
            "vars": sorted(self.vars),
            "externals": sorted([f"{k}/{v}" for k, v in self.externals.items()]),
            "lists": sorted(self.lists),
        }

# Внешняя точка входа
def validate_ink(ink_text: str) -> Dict[str, Any]:
    v = InkValidator(ink_text)
    return v.validate()
