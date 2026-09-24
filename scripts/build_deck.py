"""Embed evaluation results into the self-contained presentation (docs/presentation/index.html).

  python scripts/build_deck.py reports/base/summary.json [reports/finetuned/summary.json]

The deck is a single offline HTML file (open it from disk, Google Drive or a USB stick); this script only
replaces the JSON inside <script id="edge-data">. Run it again after every new Nano run.
"""
import json
import re
import sys
from pathlib import Path

DECK = Path(__file__).resolve().parents[1] / "docs" / "presentation" / "index.html"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    rows = [r for p in sys.argv[1:] for r in json.loads(Path(p).read_text())]
    blob = json.dumps(rows, separators=(",", ":"), default=str).replace("</", "<\\/")   # keep the script tag intact
    html = DECK.read_text()
    new, n = re.subn(r'(<script id="edge-data" type="application/json">)(.*?)(</script>)',
                     lambda m: m.group(1) + blob + m.group(3), html, count=1, flags=re.S)
    if not n:
        sys.exit("deck has no edge-data block")
    DECK.write_text(new)
    print(f"embedded {len(rows)} runs into {DECK}")


if __name__ == "__main__":
    main()
