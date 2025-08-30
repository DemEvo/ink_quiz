# ink_validator_v3.py
import re
from typing import List, Dict, Tuple, Set, Any

# Узлы: >=2 '=' слева; справа '=' опциональны
RE_KNOT = re.compile(r"^(=+)\s*([A-Za-z_]\w*)\s*(=+)?\s*$")

RE_CHOICE = re.compile(r"^([+*])\s*(.*?)\s*(?:->\s*([A-Za-z_]\w*))\s*$")  # требуем -> target
RE_DIVERT = re.compile(r"^->\s*(END|DONE|[A-Za-z_]\w*)\s*$")

RE_VAR = re.compile(r"^VAR\s+([A-Za-z_]\w*)\s*=\s*(.+?)\s*$")
RE_SET = re.compile(r"^~\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*$")

RE_EXTERNAL = re.compile(r"^EXTERNAL\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*$")
RE_CALL = re.compile(r"^~\s*([A-Za-z_]\w*)\s*\((.*?)\)\s*$")

RE_LIST = re.compile(r"^LIST\s+([A-Za-z_]\w*)\s*=\s*(.+?)\s*$")

RE_INLINE_VAR = re.compile(r"\{([A-Za-z_]\w*)\}")
RE_INLINE_TERNARY = re.compile(r"\{([^{}?:|]+?)\?\s*([^{}|]+?)\s*\|\s*([^{}]+?)\}")

def _strip_comments(line: str) -> str:
    pos = line.find("//")
    return line if pos == -1 else line[:pos]

class InkValidator:
    def __init__(self, text: str):
        self.text = text
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.infos: List[str] = []

        self.blocks: Set[str] = set()
        self.vars: Set[str] = set()
        self.externals: Dict[str, int] = {}  # fn -> argc
        self.lists: Set[str] = set()

        self.links: List[Tuple[str, str, int]] = []  # (src_block, target, line)

    def add_error(self, ln: int, msg: str): self.errors.append(f"[{ln}] {msg}")
    def add_warn(self, ln: int, msg: str):  self.warnings.append(f"[{ln}] {msg}")
    def add_info(self, ln: int, msg: str):  self.infos.append(f"[{ln}] {msg}")

    def validate(self) -> Dict[str, Any]:
        current_block = None
        seen_blocks: Set[str] = set()
        seen_vars: Set[str] = set()

        lines = [_strip_comments(l).rstrip() for l in self.text.splitlines()]

        for ln, raw in enumerate(lines, start=1):
            line = raw.strip()
            if not line:
                continue

            # Узел
            m = RE_KNOT.match(line)
            if m:
                lead, name, tail = m.groups()
                if len(lead) >= 2:
                    if name in seen_blocks:
                        self.add_error(ln, f"Дублируется узел '{name}'")
                    seen_blocks.add(name)
                    self.blocks.add(name)
                    current_block = name
                    continue
                # если '=' всего один — игнорируем, пусть будет текст
                # (можно добавить warning)

            # Директивы разрешены до первого узла и внутри узлов
            m = RE_VAR.match(line)
            if m:
                name = m.group(1)
                if name in seen_vars:
                    self.add_error(ln, f"Повторное объявление переменной '{name}'")
                seen_vars.add(name)
                self.vars.add(name)
                continue

            m = RE_LIST.match(line)
            if m:
                list_name = m.group(1)
                items = [x.strip() for x in m.group(2).split(",") if x.strip()]
                if not items:
                    self.add_error(ln, f"Пустой LIST '{list_name}'")
                self.lists.add(list_name)
                continue

            m = RE_EXTERNAL.match(line)
            if m:
                fn = m.group(1)
                args = m.group(2)
                argc = 0 if not args.strip() else len([a.strip() for a in args.split(",") if a.strip()])
                # повторы допускаем, но проверим одинаковость argc
                if fn in self.externals and self.externals[fn] != argc:
                    self.add_error(ln, f"EXTERNAL '{fn}' объявлен с другим числом аргументов (было {self.externals[fn]}, теперь {argc})")
                self.externals[fn] = argc
                continue

            # Любой переход вне узла — ошибка
            m = RE_DIVERT.match(line)
            if m and current_block is None:
                self.add_error(ln, "Переход '->' вне узла")
                continue

            # Внутри узла проверяем конструкты
            if current_block is not None:
                # Вариант
                m = RE_CHOICE.match(line)
                if m:
                    mark, body, tgt = m.groups()
                    if mark == "*":
                        self.add_info(ln, f"Повторяемый вариант: {body} -> {tgt}")
                    self.links.append((current_block, tgt, ln))
                    continue

                # Диверт
                m = RE_DIVERT.match(line)
                if m:
                    tgt = m.group(1)
                    if tgt not in ("END", "DONE"):
                        self.links.append((current_block, tgt, ln))
                    continue

                # Присваивание
                m = RE_SET.match(line)
                if m:
                    var = m.group(1)
                    if var not in self.vars:
                        self.add_error(ln, f"Присваивание в необъявленную переменную '{var}' (объявите через VAR)")
                    # expr можно дополнительно проанализировать позже
                    continue

                # Вызов внешней функции
                m = RE_CALL.match(line)
                if m:
                    fn = m.group(1)
                    args = m.group(2)
                    argc = 0 if not args.strip() else len([a.strip() for a in args.split(",") if a.strip()])
                    if fn not in self.externals:
                        self.add_error(ln, f"Вызов внешней функции '{fn}' без объявления EXTERNAL")
                    else:
                        declared = self.externals[fn]
                        if declared != argc:
                            self.add_error(ln, f"Неверное число аргументов в '{fn}': {argc}, ожидалось {declared}")
                    continue

                # Инлайны
                if "{" in line and "}" in line:
                    # {var}
                    for name in RE_INLINE_VAR.findall(line):
                        if name not in self.vars:
                            self.add_error(ln, f"Подстановка переменной '{{{name}}}' без VAR-объявления")
                    # {cond ? A | B}
                    for _cond, _yes, _no in RE_INLINE_TERNARY.findall(line):
                        # проверим только идентификаторы в условии
                        for ident in re.findall(r"\b([A-Za-z_]\w*)\b", _cond):
                            # разрешим boolean литералы
                            if ident in ("true", "false", "null"):
                                continue
                            if ident not in self.vars:
                                self.add_error(ln, f"Условие использует необъявленную переменную '{ident}'")
                    continue

                # Glue — ок, как инфо
                if "<>" in line:
                    self.add_info(ln, "Используется glue '<>'")
                    continue

            else:
                # мы ещё вне узла: разрешены только VAR/LIST/EXTERNAL/пустые строки/комменты
                # всё остальное пусть пролетает как обычный текст (или добавить предупреждение)
                pass

        # Постпроверки
        if "start" not in self.blocks:
            self.errors.append("Отсутствует обязательный узел 'start'.")

        for src, tgt, ln in self.links:
            if tgt not in self.blocks:
                self.add_error(ln, f"Переход из '{src}' в несуществующий узел '{tgt}'.")

        return {
            "errors": self.errors,
            "warnings": self.warnings,
            "infos": self.infos,
            "blocks": sorted(self.blocks),
            "vars": sorted(self.vars),
            "externals": sorted([f"{k}/{v}" for k,v in self.externals.items()]),
            "lists": sorted(self.lists),
        }

# Внешняя точка входа (API)
def validate_ink(ink_text: str) -> Dict[str, Any]:
    v = InkValidator(ink_text)
    return v.validate()
