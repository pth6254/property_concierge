"""원본·스크린샷·글꼴을 포함하는 공유용 단일 HTML을 만든다. 표준 라이브러리만 사용한다."""
from pathlib import Path
import base64
import json

FOLDER = Path(__file__).resolve().parent
ROOT = FOLDER.parents[1]


def data_url(path: Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def build() -> Path:
    files = {"appraisal": "appraisal-candidate", "simulation": "simulation",
             "comparison": "comparison", "candidate": "candidate"}
    screens = {name: data_url(FOLDER / f"assets/{filename}.png", "image/png")
               for name, filename in files.items()}
    font = data_url(ROOT / "web/src/app/fonts/PretendardVariable.woff2", "font/woff2")
    html = (FOLDER / "src/index.template.html").read_text(encoding="utf-8")
    html = html.replace("__STYLES__", (FOLDER / "src/styles.css").read_text(encoding="utf-8"))
    html = html.replace("__SCRIPT__", (FOLDER / "src/presentation.js").read_text(encoding="utf-8"))
    html = html.replace("__FONT__", font).replace("__INITIAL_SCREEN__", screens["appraisal"])
    html = html.replace("__SCREENS__", json.dumps(screens, ensure_ascii=False))
    target = FOLDER / "index.html"
    target.write_text(html, encoding="utf-8")
    return target


if __name__ == "__main__":
    print(build())
