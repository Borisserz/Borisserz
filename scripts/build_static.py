#!/usr/bin/env python3
"""Renders the static branded SVG assets for the profile README.

Static means "does not depend on GitHub data": section headers, status chips,
the stack board and the contact badges. The data-driven cards live in
build_cards.py. Both share the palette defined here so the two halves of the
page cannot drift apart.

Output is deliberately ASCII-only: non-ASCII literals have been mangled by
tooling in the past, which silently breaks the SVG for every reader.
"""

import os

SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

WIDTH = 1200
ACCENT = "#F05138"

PALETTES = {
    "dark": {
        "text": "#DFDFE0",
        "muted": "#8E8E93",
        "panel": "#2C2C31",
        "border": "#3B3B41",
        "accent": ACCENT,
        "on_accent": "#FFFFFF",
    },
    "light": {
        "text": "#262626",
        "muted": "#6E6E73",
        "panel": "#F0F0F3",
        "border": "#D8D8DC",
        "accent": ACCENT,
        "on_accent": "#FFFFFF",
    },
}

SECTIONS = {
    "apps": "Shipped apps",
    "open-source": "Open source",
    "activity": "Activity",
    "stack": "Stack",
    "contact": "Contact",
}

STATUS = [
    ("Minsk, BY", False),
    ("3rd-year CS @ BSUIR", False),
    ("Open to iOS internships", True),
]

# Every entry below is backed by code in the repositories / resume, not aspiration.
STACK = [
    ("iOS", ["Swift", "SwiftUI", "SwiftData", "Swift Charts", "WidgetKit",
             "Live Activities", "HealthKit", "MapKit", "Core ML", "Vision",
             "watchOS"]),
    ("Patterns", ["MVVM", "Combine", "async/await", "Actors", "REST"]),
    ("Backend", ["Python", "FastAPI", "Java", "Node.js", "Firebase", "Docker"]),
    ("Data & AI", ["Vertex AI", "Gemini", "pandas", "NumPy", "DuckDB",
                   "ClickHouse", "LangChain", "LangGraph", "Airflow"]),
    ("Web & tooling", ["TypeScript", "React", "Tailwind", "Framer Motion",
                       "Xcode", "Figma", "GitHub Actions", "pytest"]),
]

BADGES = [("telegram", "Telegram"), ("linkedin", "LinkedIn"), ("appstore", "App Store")]

CHIP_H = 40
CHIP_PAD = 18
CHIP_GAP = 10
CHIP_FONT = 20


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text_width(s, size):
    """Approximate advance width for the system sans stack.

    Deliberately generous: an overestimate leaves a chip slightly roomy, an
    underestimate clips the label.
    """
    return len(s) * size * 0.52


def chip_width(label):
    return int(CHIP_PAD * 2 + text_width(label, CHIP_FONT))


def svg_open(height, label):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
        'width="%d" height="%d" role="img" aria-label="%s">\n'
        % (WIDTH, height, WIDTH, height, esc(label))
    )


def chip(x, y, label, p, accent=False):
    w = chip_width(label)
    fill = p["accent"] if accent else p["panel"]
    stroke = p["accent"] if accent else p["border"]
    color = p["on_accent"] if accent else p["text"]
    out = (
        '  <rect x="%d" y="%d" width="%d" height="%d" rx="10" fill="%s" stroke="%s"/>\n'
        '  <text x="%d" y="%d" font-family="%s" font-size="%d" fill="%s">%s</text>\n'
        % (x, y, w, CHIP_H, fill, stroke,
           x + CHIP_PAD, y + 26, SANS, CHIP_FONT, color, esc(label))
    )
    return out, w


def section_header(title, p):
    height = 58
    out = svg_open(height, title)
    out += ('  <path d="M6 16 L18 28 L6 40" fill="none" stroke="%s" stroke-width="4.5" '
            'stroke-linecap="round" stroke-linejoin="round"/>\n' % p["accent"])
    out += ('  <text x="34" y="38" font-family="%s" font-size="30" font-weight="600" '
            'fill="%s">%s</text>\n' % (SANS, p["text"], esc(title)))
    out += '  <rect x="0" y="53" width="%d" height="1" fill="%s"/>\n' % (WIDTH, p["border"])
    out += "</svg>\n"
    return out


def status_bar(p):
    height = CHIP_H + 8
    out = svg_open(height, "Minsk, BY. 3rd-year CS at BSUIR. Open to iOS internships.")
    x = 0
    for label, accent in STATUS:
        block, w = chip(x, 4, label, p, accent)
        out += block
        x += w + CHIP_GAP
    out += "</svg>\n"
    return out


def stack_board(p):
    rows = []  # (kind, payload) laid out before we know the total height
    y = 0
    for group, items in STACK:
        rows.append(("label", (group, y + 14)))
        x = 0
        line = y + 26
        for item in items:
            w = chip_width(item)
            if x and x + w > WIDTH:
                x = 0
                line += CHIP_H + CHIP_GAP
            rows.append(("chip", (x, line, item)))
            x += w + CHIP_GAP
        y = line + CHIP_H + 22

    summary = "; ".join("%s: %s" % (g, ", ".join(i)) for g, i in STACK)
    out = svg_open(y, summary)
    for kind, payload in rows:
        if kind == "label":
            group, ly = payload
            out += ('  <text x="0" y="%d" font-family="%s" font-size="18" '
                    'font-weight="600" letter-spacing="1.4" fill="%s">%s</text>\n'
                    % (ly, SANS, p["muted"], esc(group)))
        else:
            cx, cy, item = payload
            block, _ = chip(cx, cy, item, p)
            out += block
    out += "</svg>\n"
    return out


def badge(label, p):
    w = int(32 + 16 + text_width(label, CHIP_FONT))
    height = 44
    out = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
           'width="%d" height="%d" role="img" aria-label="%s">\n'
           % (w, height, w, height, esc(label)))
    out += ('  <rect x="0.5" y="0.5" width="%d" height="43" rx="11" fill="%s" stroke="%s"/>\n'
            % (w - 1, p["panel"], p["border"]))
    out += '  <circle cx="18" cy="22" r="4" fill="%s"/>\n' % p["accent"]
    out += ('  <text x="32" y="29" font-family="%s" font-size="%d" fill="%s">%s</text>\n'
            % (SANS, CHIP_FONT, p["text"], esc(label)))
    out += "</svg>\n"
    return out


def write(path, content):
    # Unicode is fine in SVG; control characters are what break GitHub's parser.
    if any(ord(c) < 32 and c not in "\n\t\r" for c in content):
        raise ValueError("control characters in %s" % path)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    print("wrote %s" % path)


def main():
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
    assets = os.path.join(root, "assets")
    os.makedirs(assets, exist_ok=True)

    for theme, p in PALETTES.items():
        for slug, title in SECTIONS.items():
            write(os.path.join(assets, "sec-%s-%s.svg" % (slug, theme)),
                  section_header(title, p))
        write(os.path.join(assets, "status-%s.svg" % theme), status_bar(p))
        write(os.path.join(assets, "stack-%s.svg" % theme), stack_board(p))
        for slug, label in BADGES:
            write(os.path.join(assets, "badge-%s-%s.svg" % (slug, theme)),
                  badge(label, p))


if __name__ == "__main__":
    main()
