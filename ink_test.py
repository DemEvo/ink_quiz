import json
import sys
from ink_to_json import parse_ink_to_json
from ink_validator import validate_ink
from json_to_html_player import build_html_player


# --- CLI: читает Ink из stdin, пишет JSON в stdout ---
def main():
    ink_text = sys.stdin.read()
    print(f"step 0 validate ink:{validate_ink(ink_text)}")
    print("step 1")
    json_obj = parse_ink_to_json(ink_text)  # ink_text: str
    print("step 2")
    html_str = build_html_player(json_obj)  # json_obj: dict
    print("step 3")
    sys.stdout.write(json.dumps(json_obj, ensure_ascii=False, indent=2))
    print("//---//---//---//---//---//---//---//---//---//---//---")
    print(json_obj)
    print("//---//---//---//---//---//---//---//---//---//---//---")
    print("//---//---//---//---//---//---//---//---//---//---//---")
    print(html_str)

if __name__ == "__main__":
    main()

# cat test.ink | python ink_test.py
# python ink_test.py < test.ink