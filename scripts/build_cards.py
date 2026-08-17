#!/usr/bin/env python3
"""Renders the data-driven SVG cards for the profile README.

Everything here comes from the GitHub API and is committed as plain SVG, so the
profile never depends on a third-party rendering service staying online.

Two cards are produced per theme:
  activity-<theme>.svg  contribution counters, streaks and language split
  oss-<theme>.svg       pull requests opened against repositories I do not own

If any request fails the script exits non-zero *before* touching the existing
files. A stale card is bad; a blank or wrong card is worse.
"""

import glob
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_static import (  # noqa: E402
    CHIP_FONT,
    CHIP_GAP,
    CHIP_H,
    PALETTES,
    SANS,
    WIDTH,
    chip_width,
    esc,
    text_width,
    write,
)

LOGIN = os.environ.get("PROFILE_LOGIN", "Borisserz")
API = "https://api.github.com"
GRAPHQL = API + "/graphql"

# GitHub's own language colours, so the split reads the same as on a repo page.
LANG_COLORS = {
    "Swift": "#F05138",
    "Python": "#3572A5",
    "TypeScript": "#3178C6",
    "JavaScript": "#F1E05A",
    "Java": "#B07219",
    "HTML": "#E34C26",
    "CSS": "#663399",
    "Ruby": "#701516",
    "Dockerfile": "#384D54",
    "Shell": "#89E051",
    "C": "#555555",
    "C++": "#F34B7D",
    "Objective-C": "#438EFF",
    "Kotlin": "#A97BFF",
    "Metal": "#8F14E9",
}
LANG_FALLBACK = "#8E8E93"

USER_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false) {
      totalCount
      nodes {
        name
        languages(first: 12, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
  }
}
"""


def token():
    for name in ("GH_STATS_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(name)
        if value:
            return value
    sys.exit("no token: set GH_STATS_TOKEN (read:user, public_repo)")


def request(url, data=None):
    headers = {
        "Authorization": "Bearer %s" % token(),
        "Accept": "application/vnd.github+json",
        "User-Agent": "profile-cards",
    }
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        sys.exit("%s -> HTTP %s: %s" % (url, exc.code, exc.read().decode()[:300]))
    except urllib.error.URLError as exc:
        sys.exit("%s -> %s" % (url, exc))


def graphql(query, variables):
    payload = request(GRAPHQL, {"query": query, "variables": variables})
    if "errors" in payload:
        sys.exit("graphql errors: %s" % payload["errors"])
    return payload["data"]


def search_prs(query):
    """Returns every match, following pagination."""
    items = []
    page = 1
    while True:
        url = "%s/search/issues?q=%s&per_page=100&page=%d" % (
            API, urllib.parse.quote(query), page)
        payload = request(url)
        items.extend(payload.get("items", []))
        if len(items) >= payload.get("total_count", 0) or not payload.get("items"):
            break
        page += 1
        if page > 10:  # search caps out at 1000 results
            break
    return items


def streaks(weeks):
    days = []
    for week in weeks:
        for day in week["contributionDays"]:
            days.append((day["date"], day["contributionCount"]))
    days.sort()

    longest = run = 0
    for _, count in days:
        run = run + 1 if count else 0
        longest = max(longest, run)

    # A day with no contributions yet does not break the streak until it ends.
    counts = dict(days)
    current = 0
    cursor = date.today()
    if counts.get(cursor.isoformat(), 0) == 0:
        cursor -= timedelta(days=1)
    while counts.get(cursor.isoformat(), 0) > 0:
        current += 1
        cursor -= timedelta(days=1)
    return current, longest


def parse(user, pr_items):
    """Turns raw API payloads into the numbers the cards display.

    Kept separate from fetching so the same logic can run against payloads
    pulled by other means, e.g. the one-off bootstrap before CI owns a token.
    """
    calendar = user["contributionsCollection"]["contributionCalendar"]
    current, longest = streaks(calendar["weeks"])

    repos = user["repositories"]["nodes"]

    sizes = {}
    for repo in repos:
        for edge in repo["languages"]["edges"]:
            sizes[edge["node"]["name"]] = sizes.get(edge["node"]["name"], 0) + edge["size"]
    total_bytes = sum(sizes.values()) or 1
    languages = sorted(sizes.items(), key=lambda kv: -kv[1])[:5]
    languages = [(name, size * 100.0 / total_bytes) for name, size in languages]

    external = {}
    merges = []
    for item in pr_items:
        repo = "/".join(item["repository_url"].split("/")[-2:])
        entry = external.setdefault(repo, {"prs": 0, "merged": 0})
        entry["prs"] += 1
        pr = item.get("pull_request") or {}
        if pr.get("merged_at"):
            entry["merged"] += 1
            merges.append({
                "repo": repo,
                "number": item["number"],
                "title": item.get("title") or "",
                "merged_at": pr["merged_at"],
            })

    rows = sorted(external.items(), key=lambda kv: (-kv[1]["merged"], -kv[1]["prs"], kv[0]))
    merges.sort(key=lambda r: r["merged_at"], reverse=True)

    return {
        "contributions": calendar["totalContributions"],
        "current_streak": current,
        "longest_streak": longest,
        "repos": user["repositories"]["totalCount"],
        "languages": languages,
        "external": rows,
        "external_merged": sum(v["merged"] for _, v in rows),
        "latest_merges": merges[:3],
    }


def collect():
    user = graphql(USER_QUERY, {"login": LOGIN})["user"]
    if not user:
        sys.exit("no such user: %s" % LOGIN)
    return parse(user, search_prs("is:pr author:%s -user:%s" % (LOGIN, LOGIN)))


def svg_open(height, label):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
            'width="%d" height="%d" role="img" aria-label="%s">\n'
            % (WIDTH, height, WIDTH, height, esc(label)))


def tile(x, y, w, label, value, p, accent=False):
    return (
        '  <rect x="%d" y="%d" width="%d" height="110" rx="14" fill="%s" stroke="%s"/>\n'
        '  <text x="%d" y="%d" font-family="%s" font-size="18" fill="%s">%s</text>\n'
        '  <text x="%d" y="%d" font-family="%s" font-size="40" font-weight="600" '
        'fill="%s">%s</text>\n'
        % (x, y, w, p["panel"], p["border"],
           x + 22, y + 38, SANS, p["muted"], esc(label),
           x + 22, y + 88, SANS, p["accent"] if accent else p["text"], esc(value))
    )


def activity_card(data, p):
    gap = 21
    tile_w = (WIDTH - 2 * gap) // 3
    tiles = [
        ("Contributions (12 mo)", "{:,}".format(data["contributions"]), False),
        ("Current streak", "%d days" % data["current_streak"], True),
        ("Longest streak (12 mo)", "%d days" % data["longest_streak"], False),
        ("Merged PRs in other repos", str(data["external_merged"]), True),
        ("Repos contributed to", str(len(data["external"])), False),
        ("Own repositories", str(data["repos"]), False),
    ]

    bar_y = 2 * 110 + gap + 56
    legend_y = bar_y + 44
    height = legend_y + CHIP_H + 4

    summary = "%s contributions in the last year, %d day current streak, top language %s." % (
        "{:,}".format(data["contributions"]), data["current_streak"],
        data["languages"][0][0] if data["languages"] else "n/a")
    out = svg_open(height, summary)

    for index, (label, value, accent) in enumerate(tiles):
        row, col = divmod(index, 3)
        out += tile(col * (tile_w + gap), row * (110 + gap), tile_w, label, value, p, accent)

    out += ('  <text x="0" y="%d" font-family="%s" font-size="18" font-weight="600" '
            'letter-spacing="1.4" fill="%s">Languages by bytes of code</text>\n'
            % (bar_y - 14, SANS, p["muted"]))

    out += '  <clipPath id="bar"><rect x="0" y="%d" width="%d" height="20" rx="10"/></clipPath>\n' % (
        bar_y, WIDTH)
    out += '  <g clip-path="url(#bar)">\n'
    x = 0.0
    for name, share in data["languages"]:
        w = WIDTH * share / 100.0
        out += '    <rect x="%.1f" y="%d" width="%.1f" height="20" fill="%s"/>\n' % (
            x, bar_y, w + 1, LANG_COLORS.get(name, LANG_FALLBACK))
        x += w
    if x < WIDTH:
        out += '    <rect x="%.1f" y="%d" width="%.1f" height="20" fill="%s"/>\n' % (
            x, bar_y, WIDTH - x, p["border"])
    out += "  </g>\n"

    x = 0
    for name, share in data["languages"]:
        label = "%s %.1f%%" % (name, share)
        w = chip_width(label) + 14
        out += ('  <rect x="%d" y="%d" width="%d" height="%d" rx="10" fill="%s" stroke="%s"/>\n'
                % (x, legend_y, w, CHIP_H, p["panel"], p["border"]))
        out += '  <circle cx="%d" cy="%d" r="5" fill="%s"/>\n' % (
            x + 18, legend_y + CHIP_H // 2, LANG_COLORS.get(name, LANG_FALLBACK))
        out += ('  <text x="%d" y="%d" font-family="%s" font-size="%d" fill="%s">%s</text>\n'
                % (x + 32, legend_y + 26, SANS, CHIP_FONT, p["text"], esc(label)))
        x += w + CHIP_GAP

    out += "</svg>\n"
    return out


def truncate(text, max_chars):
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip(" .,;:-") + "..."


OSS_MARK_START = "<!-- oss:start -->"
OSS_MARK_END = "<!-- oss:end -->"


def oss_card(data, p):
    rows = data["external"][:8]
    merges = data.get("latest_merges") or []
    hidden = len(data["external"]) - len(rows)
    row_h = 48
    merge_h = 56
    row_gap = 8
    top = 30
    repo_block = top + len(rows) * (row_h + row_gap) + (24 if hidden else 0)
    merge_top = repo_block + (36 if merges else 0)
    height = merge_top + len(merges) * (merge_h + row_gap)

    summary = "Pull requests to %d repositories I do not own, %d merged." % (
        len(data["external"]), data["external_merged"])
    out = svg_open(height, summary)
    out += ('  <text x="0" y="18" font-family="%s" font-size="18" fill="%s">'
            'Pull requests to repositories I do not own</text>\n' % (SANS, p["muted"]))

    y = top
    for repo, stat in rows:
        out += ('  <rect x="0" y="%d" width="%d" height="%d" rx="10" fill="%s" stroke="%s"/>\n'
                % (y, WIDTH, row_h, p["panel"], p["border"]))
        out += '  <circle cx="20" cy="%d" r="4" fill="%s"/>\n' % (
            y + row_h // 2, p["accent"] if stat["merged"] else p["muted"])
        out += ('  <text x="40" y="%d" font-family="%s" font-size="22" fill="%s">%s</text>\n'
                % (y + 31, SANS, p["text"], esc(repo)))

        prs = "%d PR%s" % (stat["prs"], "" if stat["prs"] == 1 else "s")
        out += ('  <text x="%d" y="%d" text-anchor="end" font-family="%s" font-size="20">'
                % (WIDTH - 20, y + 31, SANS))
        if stat["merged"]:
            out += ('<tspan fill="%s">%d merged</tspan><tspan fill="%s"> &#183; %s</tspan>'
                    % (p["accent"], stat["merged"], p["muted"], prs))
        else:
            out += '<tspan fill="%s">%s</tspan>' % (p["muted"], prs)
        out += "</text>\n"
        y += row_h + row_gap

    if hidden:
        out += ('  <text x="0" y="%d" font-family="%s" font-size="18" fill="%s">'
                'and %d more</text>\n' % (y + 16, SANS, p["muted"], hidden))

    if merges:
        out += ('  <text x="0" y="%d" font-family="%s" font-size="18" font-weight="600" '
                'letter-spacing="1.4" fill="%s">Latest merges</text>\n'
                % (merge_top - 12, SANS, p["muted"]))
        y = merge_top
        for merge in merges:
            label = "%s#%s" % (merge["repo"], merge["number"])
            title = truncate(merge["title"], 72)
            out += ('  <rect x="0" y="%d" width="%d" height="%d" rx="10" fill="%s" stroke="%s"/>\n'
                    % (y, WIDTH, merge_h, p["panel"], p["border"]))
            out += '  <circle cx="20" cy="%d" r="4" fill="%s"/>\n' % (
                y + merge_h // 2, p["accent"])
            out += ('  <text x="40" y="%d" font-family="%s" font-size="18" fill="%s">%s</text>\n'
                    % (y + 22, SANS, p["accent"], esc(label)))
            out += ('  <text x="40" y="%d" font-family="%s" font-size="18" fill="%s">%s</text>\n'
                    % (y + 44, SANS, p["text"], esc(title)))
            y += merge_h + row_gap

    out += "</svg>\n"
    return out


def oss_search_url():
    q = "is:pr author:%s -user:%s" % (LOGIN, LOGIN)
    return "https://github.com/search?q=%s&type=pullrequests" % urllib.parse.quote(q)


def oss_readme_block(rows, hidden, merges):
    picture = (
        "<picture>\n"
        '  <source media="(prefers-color-scheme: dark)" srcset="https://cdn.jsdelivr.net/gh/Borisserz/Borisserz@main/assets/oss-dark.svg">\n'
        '  <source media="(prefers-color-scheme: light)" srcset="https://cdn.jsdelivr.net/gh/Borisserz/Borisserz@main/assets/oss-light.svg">\n'
        '  <img src="https://cdn.jsdelivr.net/gh/Borisserz/Borisserz@main/assets/oss-dark.svg" width="100%" alt="Pull requests to repositories I do not own, with merge counts and latest merged titles.">\n'
        "</picture>"
    )
    return picture


def clear_stale_oss_rows(assets):
    patterns = (
        "oss-caption-*.svg", "oss-repo-*.svg", "oss-more-*.svg",
        "oss-merges-caption-*.svg", "oss-merge-*.svg",
    )
    for pattern in patterns:
        for path in glob.glob(os.path.join(assets, pattern)):
            os.remove(path)


def patch_readme_oss(block):
    readme = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), os.pardir, "README.md")
    text = open(readme, encoding="utf-8").read()
    wrapped = "%s\n%s\n%s" % (OSS_MARK_START, block.rstrip(), OSS_MARK_END)
    if OSS_MARK_START in text and OSS_MARK_END in text:
        pre, rest = text.split(OSS_MARK_START, 1)
        _, post = rest.split(OSS_MARK_END, 1)
        text = pre + wrapped + post
    else:
        sys.exit("could not find OSS markers in README.md")
    open(readme, "w", encoding="utf-8").write(text)
    print("wrote README.md OSS links")


def write_oss(data, assets):
    rows = data["external"][:8]
    merges = data.get("latest_merges") or []
    hidden = len(data["external"]) - len(rows)
    clear_stale_oss_rows(assets)
    for theme, p in PALETTES.items():
        write(os.path.join(assets, "oss-%s.svg" % theme), oss_card(data, p))
    patch_readme_oss(oss_readme_block(rows, hidden, merges))


def render(data):
    if not data["languages"]:
        sys.exit("no language data returned; refusing to write empty cards")

    assets = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), os.pardir, "assets")
    for theme, p in PALETTES.items():
        write(os.path.join(assets, "activity-%s.svg" % theme), activity_card(data, p))
    write_oss(data, assets)

    print("contributions=%s current_streak=%s external_repos=%s merged=%s" % (
        data["contributions"], data["current_streak"],
        len(data["external"]), data["external_merged"]))


def main():
    render(collect())


if __name__ == "__main__":
    main()
