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
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
REQUEST_TIMEOUT = int(os.environ.get("OPENAI_TIMEOUT", "60"))  # сек
DEBUG = os.environ.get("INK_DEBUG", "1") != "0"  # 1=вкл, 0=выкл

SYSTEM_HINT = (
    "You are an Ink scenario generator for a language trainer.\n"
    "Follow this workflow strictly:\n"
    "1) Produce a minimal but complete Ink script using the subset below.\n"
    "2) Immediately CALL validate_ink with the full Ink.\n"
    "3) If report.errors is not empty, fix your Ink and CALL validate_ink again (loop until ok).\n"
    "4) When ok==true, STOP and return only the final Ink fenced block: ```ink```.\n"
    "\n"
    "Ink subset rules (STRICT):\n"
    "- Top-level scenes are ONLY knots: use exactly '=== name ==='. A mandatory knot 'start' must exist.\n"
    "- Inside a knot you MAY define stitches with '== name ==', but never at top level.\n"
    "- Choices: '+ Text -> target' (single), '* Text -> target' (repeatable). Each choice must have '-> target' to an EXISTING knot (not a stitch).\n"
    "- Diverts: '-> knot' to jump, '-> END'/'-> DONE' to finish. Never place '->' outside any knot.\n"
    "- Variables: 'VAR x = value'; assignment '~ x = expr' (x must be declared).\n"
    "- Externals: 'EXTERNAL fn(args...)'; call with '~ fn(...)' only after declaration.\n"
    "- Lists: 'LIST name = a, b, c'.\n"
    "- Inline: '{var}' and '{cond ? A | B}' (no nesting). cond may use numbers, declared vars, > < >= <= == != && ||.\n"
    "- Glue '<>' allowed; '//' comments.\n"
    "- Before the first knot only VAR/LIST/EXTERNAL are allowed.\n"
)


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
            prompt = "Сгенерируй короткий Ink-сценарий по теме 'в кафе' для уровня A1."
        else:
            log("Режим: читаем промпт из stdin…")
            prompt = sys.stdin.read().strip() or "Сгенерируй короткий Ink-сценарий по теме 'в кафе' для уровня A1."
        log(f"Промпт готов (длина {len(prompt)} символов)")

    try:
        out = ask_gpt_ink(prompt)
        print(out)
    except Exception as e:
        print(f"EXCEPTION: {type(e).__name__}: {e}\n{traceback.format_exc()}", file=sys.stderr)

if __name__ == "__main__":
    main()
