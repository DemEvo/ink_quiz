import json
import sys
from ink_to_json import parse_ink_to_json
from json_to_html_player import build_html_player


# --- CLI: читает Ink из stdin, пишет JSON в stdout ---
def main():
    ink_text = sys.stdin.read()
    json_obj = parse_ink_to_json(ink_text)  # ink_text: str
    html_str = build_html_player(json_obj)  # json_obj: dict
    sys.stdout.write(json.dumps(json_obj, ensure_ascii=False, indent=2))
    print("//---//---//---//---//---//---//---//---//---//---//---")
    print(json_obj)
    print("//---//---//---//---//---//---//---//---//---//---//---")
    print("//---//---//---//---//---//---//---//---//---//---//---")
    print(html_str)

if __name__ == "__main__":
    main()

# cat test.ink | python ink_test.py