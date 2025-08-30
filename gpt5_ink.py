# ink_playground/gpt5_ink.py
# Конвейер для генерации Ink-сценариев с валидацией.
# GPT генерирует/правит только Ink. Когда валидатор ok — конвертация и HTML выполняются локально.

from __future__ import annotations
import os, sys, json, traceback
from os import write
from typing import Any, Dict, List

# --- imports / flat layout ---
import sys, pathlib
ROOT = pathlib.Path(__file__).parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- локальные инструменты ---
from ink_validator import validate_ink as _validate_ink
from ink_to_json import parse_ink_to_json as _ink_to_json
from json_to_html_player import build_html_player as _build_html

# --- OpenAI client ---
from openai import OpenAI

# ====== Конфиг ======
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
REQUEST_TIMEOUT = int(os.environ.get("OPENAI_TIMEOUT", "60"))  # сек
DEBUG = os.environ.get("INK_DEBUG", "1") != "0"  # 1=вкл, 0=выкл

SYSTEM_HINT = """
You are an Ink scenario generator for a dialogue trainer. reasoning effort: high

WORKFLOW (STRICT)
1) Produce a complete Ink script using ONLY the allowed subset below.
2) CALL validate_ink with the full Ink.
3) If report.errors is not empty, FIX the Ink and CALL validate_ink again (loop until ok==true).
4) When ok==true, output ONLY one fenced block: ```ink ...``` — no commentary.

INK SUBSET (ENFORCED)
- Entry point: mandatory top-level knot `=== start ===`.
- Structure: top-level knots `=== name ===`; stitches `== name ==` ONLY inside knots.
- Choices: `+ Text -> target` (single), `* Text -> target` (repeatable). Every choice MUST have `->` to an existing knot or stitch.
- Diverts: `-> knot`, `-> knot.stitch`, relative `-> stitch` (within current knot), `-> END` / `-> DONE`.
- Variables: `VAR x = value`; assignment `~ x = expr` (x must be declared).
- Inline: `{var}`, `{cond ? A | B}` (no nesting). `cond` may use declared vars and `> < >= <= == != && ||`.
- Glue `<>` allowed. Line comments `//` allowed.
- Before the first knot only `VAR` / `LIST` / `EXTERNAL` declarations are allowed.
- EXTERNAL: declare with `EXTERNAL fn(...)` before `~ fn(...)`.
- LIST: basic declaration/usage only (no advanced ops).

NAMING (STRICT)
- Knot/stitch names match `[A-Za-z_][A-Za-z0-9_]*` (ASCII letters, digits, underscore; start with letter/_).
- Use `knot.stitch` ONLY in references, never in headers.
- Do NOT create knots named END or DONE (reserved). Use `-> END` / `-> DONE`.

DIALOG RULES (MANDATORY)
- Any NPC line that asks for a decision MUST be followed by ≥ 2 substantive options (Back is optional and does NOT count as a substantive option).
- Decision coverage (classify each question INTERNALLY and enforce coverage):
  1) YES/NO → provide ACCEPT (forward) AND DECLINE (alternative) options.
  2) DISJUNCTION (“X or Y?”, “X или Y?”) → provide TWO forward options: one for X and one for Y (distinct, valid targets). Never output only one side.
  3) ENUMERATION (“A, B, or C”, “A, B или C”) → provide ONE forward option for EACH listed item (A, B, [C…]) with distinct, valid targets. Mirror labels and order.
  4) QUANTITY (“How many?”, “Сколько?”) → provide at least three concrete choices covering 1, 2, and 3+ (or context-appropriate buckets).
  5) OPEN YES/NO WITH FOLLOW-UP (“Do you want something?”) → ACCEPT must lead to a concrete next step; DECLINE must lead to a meaningful alternative.
- Option labels should mirror the alternatives concisely (short nouns/phrases). Full sentences — only when necessary for clarity.

VARIABLE SAFETY (MANDATORY)
- Any `{var}` appearing in text MUST be declared with `VAR` before its first appearance. If the value is not decided yet, initialize safely (e.g., empty string) or avoid inserting `{var}` until after assignment.
- Do not rely on undeclared variables in inline conditions or text.

SELF-CHECK (BEFORE validate_ink)
- From `=== start ===`, `END`/`DONE` is reachable.
- Every `+/*` has `-> target`, and every `->` resolves to an existing knot or stitch (relative stitches allowed).
- No dead ends: no step with neither options nor divert (except a final step that diverts to END/DONE).
- For EVERY decision question:
  • YES/NO → both ACCEPT and DECLINE present (Back does not count).
  • “X or Y?” → both X and Y present as forward options, labels mirror X/Y, distinct valid targets.
  • Enumeration of N items → N forward options mirroring the items (plus optional Back).
  • Quantity → 1 / 2 / 3+ covered.
- Names follow the NAMING rules, no knots named END/DONE.

OUTPUT
- Return ONLY one fenced block ```ink ...``` with the final, validated script.
"""




TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "validate_ink",
            "description": "Validate Ink script. If there are errors, fix Ink and call again.",
            "parameters": {
                "type": "object",
                "properties": { "ink": { "type": "string", "description": "Full Ink text to validate" } },
                "required": ["ink"]
            }
        }
    }
]

# ====== логгер ======
def log(*args: Any) -> None:
    if DEBUG:
        print("[GPT-INK]", *args, flush=True)

# ====== локальные вызовы инструментов ======
def tool_validate_ink(ink: str) -> Dict[str, Any]:
    try:
        report = _validate_ink(ink)
        # нормализация полей
        report.setdefault("errors", [])
        report.setdefault("warnings", [])
        report.setdefault("infos", [])
        ok = len(report["errors"]) == 0
        return {"ok": ok, "report": report}
    except Exception as e:
        return {"ok": False, "report": {"errors": [f"validator_exception: {type(e).__name__}: {e}"]}}

def _dispatch_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if name == "validate_ink":
        return tool_validate_ink(args.get("ink", ""))
    return {"ok": False, "error": f"unknown_tool:{name}"}

# ====== основной цикл ======
def ask_gpt_ink(user_brief: str, max_rounds: int = 8) -> str:
    """
    Диалог с моделью и вызов единственного инструмента validate_ink.
    Как только ok==True — локально конвертируем Ink в JSON и HTML и возвращаем итог.
    """
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set in environment")

    client = OpenAI(api_key=OPENAI_API_KEY)

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_HINT},
        {"role": "user", "content": user_brief},
    ]
    log("Старт. MODEL=", MODEL)
    log("Подготовлен начальный контекст (2 сообщения)")

    for round_idx in range(max_rounds):
        log(f"\nРаунд {round_idx+1}/{max_rounds}")
        log(f"Отправляем в GPT {len(messages)} сообщений...")

        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,            # только validate_ink
            tool_choice="auto",
            timeout=REQUEST_TIMEOUT,
        )
        msg = resp.choices[0].message
        has_tools = bool(getattr(msg, "tool_calls", None))
        log("Ответ получен. tool_calls=", has_tools)

        # финальный ответ без инструментов (редко)
        if not has_tools:
            log("Финальный ответ от модели (без инструментов).")
            return msg.content or "[empty]"

        # добавляем сообщение модели один раз за раунд
        messages.append(msg)

        # исполняем tool_calls
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception as e:
                log(f"Ошибка парсинга аргументов инструмента {name}: {e}")
                args = {}

            log(f"Запуск инструмента: {name} args_keys={list(args.keys())}")
            result = _dispatch_tool(name, args)
            log("Результат", name, ":", (json.dumps(result, ensure_ascii=False)[:300] + "…"))

            # ===== РАННИЙ ВЫХОД: валидатор зелёный — делаем всё локально и возвращаем итог =====
            if name == "validate_ink" and result.get("ok"):
                ink_text = args.get("ink", "")
                log("Валидация OK. Конвертация ink→json и сборка html локально…")
                json_obj = _ink_to_json(ink_text)
                html_str = _build_html(json_obj)
                with open("out.html", "w", encoding="utf-8") as file:
                    file.write(html_str)

                log("Готово. Возвращаем итог.")
                return (
                    "### INK\n```ink\n" + ink_text + "\n```\n\n"
                    "### JSON\n```json\n" + json.dumps(json_obj, ensure_ascii=False, indent=2) + "\n```\n\n"
                    "### HTML\n```html\n" + html_str + "\n```"
                )

            # иначе — отдаём отчёт валидатора модели (пусть правит Ink)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False)
            })
            log("Результат инструмента", name, "отдан модели.")

    log("❌ Лимит раундов исчерпан, финального ответа нет.")
    return "[tool loop exhausted]"

# ====== CLI ======
def main() -> None:
    if len(sys.argv) > 1:
        log("Режим: аргумент командной строки")
        prompt = " ".join(sys.argv[1:])
    else:
        if sys.stdin.isatty():
            log("Режим: stdin отсутствует, берём промпт по умолчанию")
            prompt = "Сгенерируй Ink-сценарий по теме 'покупка в магазине' для уровня A2."
        else:
            log("Режим: читаем промпт из stdin…")
            prompt = sys.stdin.read().strip() or "Сгенерируй Ink-сценарий по теме 'заказ такси по телефону' для уровня A2."
        log(f"Промпт готов (длина {len(prompt)} символов)")

    try:
        out = ask_gpt_ink(prompt)
        print(out)
    except Exception as e:
        print(f"EXCEPTION: {type(e).__name__}: {e}\n{traceback.format_exc()}", file=sys.stderr)

if __name__ == "__main__":
    main()
