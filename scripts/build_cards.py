#!/usr/bin/env python3
"""Renders the data-driven SVG cards for the profile README.

Everything here comes from the GitHub API and is committed as plain SVG, so the
profile never depends on a third-party rendering service staying online.

Cards produced per theme:
  activity-<theme>.svg   contribution counters, streaks and language split
  oss-caption / oss-repo-* / oss-merge-*   clickable open-source rows

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
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_static import (  # noqa: E402
    APPS,
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
        "weeks": calendar["weeks"],
    }


def collect():
    user = graphql(USER_QUERY, {"login": LOGIN})["user"]
    if not user:
        sys.exit("no such user: %s" % LOGIN)
    data = parse(user, search_prs("is:pr author:%s -user:%s" % (LOGIN, LOGIN)))
    return data


def recent_feed():
    events = request("%s/users/%s/events/public?per_page=40" % (API, LOGIN))
    rows = []
    seen = set()
    for event in events:
        row = summarize_event(event)
        if not row:
            continue
        key = (row["verb"], row["href"])
        if key in seen:
            continue
        seen.add(key)
        if not row.get("detail"):
            url = event_resource_url(event)
            if url:
                row = apply_fetched_title(row, request(url))
        rows.append(row)
        if len(rows) >= 5:
            break
    return rows


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


def apply_fetched_title(row, fetched):
    """GitHub's Events API omits PR titles. Fill them from a follow-up fetch."""
    if row.get("detail"):
        return row
    filled = dict(row)
    filled["detail"] = truncate((fetched or {}).get("title") or "", 64)
    return filled


def event_resource_url(event):
    payload = event.get("payload") or {}
    kind = event.get("type")
    if kind in ("PullRequestEvent", "PullRequestReviewEvent"):
        return (payload.get("pull_request") or {}).get("url")
    if kind == "IssuesEvent":
        return (payload.get("issue") or {}).get("url")
    return None


def contrib_level(count, max_count):
    if count <= 0 or max_count <= 0:
        return 0
    return max(1, min(4, int(round(4.0 * count / max_count))))


def weekday_counts(weeks):
    """Sunday-first totals, matching GitHub's contribution grid."""
    counts = [0] * 7
    for week in weeks:
        for day in week["contributionDays"]:
            parsed = date.fromisoformat(day["date"])
            idx = (parsed.weekday() + 1) % 7
            counts[idx] += day["contributionCount"]
    return counts


def summarize_event(event):
    """Turns a GitHub Events API payload into a feed row, or None if noisy."""
    kind = event.get("type")
    repo = (event.get("repo") or {}).get("name") or ""
    payload = event.get("payload") or {}
    if kind == "PullRequestEvent":
        pr = payload.get("pull_request") or {}
        number = pr.get("number") or payload.get("number")
        href = pr.get("html_url") or ("https://github.com/%s/pull/%s" % (repo, number))
        if payload.get("action") == "closed" and pr.get("merged"):
            verb = "merged"
        elif payload.get("action") == "opened":
            verb = "opened"
        else:
            return None
        return {
            "verb": verb,
            "repo": repo,
            "href": href,
            "label": "%s #%s" % (repo, number),
            "detail": truncate(pr.get("title") or "", 64),
        }
    if kind == "IssuesEvent" and payload.get("action") == "opened":
        issue = payload.get("issue") or {}
        number = issue.get("number")
        href = issue.get("html_url") or ""
        return {
            "verb": "opened",
            "repo": repo,
            "href": href,
            "label": "%s #%s" % (repo, number),
            "detail": truncate(issue.get("title") or "", 64),
        }
    if kind == "ReleaseEvent":
        rel = payload.get("release") or {}
        return {
            "verb": "released",
            "repo": repo,
            "href": rel.get("html_url") or ("https://github.com/%s" % repo),
            "label": repo,
            "detail": rel.get("tag_name") or "release",
        }
    if kind == "PullRequestReviewEvent":
        pr = payload.get("pull_request") or {}
        number = pr.get("number")
        href = pr.get("html_url") or ""
        return {
            "verb": "reviewed",
            "repo": repo,
            "href": href,
            "label": "%s #%s" % (repo, number),
            "detail": truncate(pr.get("title") or "", 64),
        }
    return None


def patch_markers(text, start, end, block):
    wrapped = "%s\n%s\n%s" % (start, block.rstrip(), end)
    pre, rest = text.split(start, 1)
    _, post = rest.split(end, 1)
    return pre + wrapped + post


OSS_MARK_START = "<!-- oss:start -->"
OSS_MARK_END = "<!-- oss:end -->"
OSS_CDN = "https://cdn.jsdelivr.net/gh/Borisserz/Borisserz@main/assets"
ACTIVITY_URL_RE = re.compile(
    r"(https://cdn\.jsdelivr\.net/gh/Borisserz/Borisserz@main/assets/"
    r"(?:activity|app-[a-z0-9]+)-(?:dark|light)\.svg)"
    r"(?:\?v=[^\"\s>]*)?"
)
OSS_ROW_H = 48
OSS_MERGE_H = 56
OSS_ROW_GAP = 8
OSS_CAPTION_H = 28
OSS_MORE_H = 28
OSS_MERGES_CAPTION_H = 32


def svg_doc(height, label, body):
    return svg_open(height, label) + body + "</svg>\n"


def oss_caption_svg(text, height, p, weight=""):
    weight_attr = ' font-weight="600" letter-spacing="1.4"' if weight else ""
    return svg_doc(
        height, text,
        '  <text x="0" y="%d" font-family="%s" font-size="18"%s fill="%s">%s</text>\n'
        % (height - 10, SANS, weight_attr, p["muted"], esc(text)))


def oss_repo_svg(repo, stat, p):
    height = OSS_ROW_H + OSS_ROW_GAP
    prs = "%d PR%s" % (stat["prs"], "" if stat["prs"] == 1 else "s")
    stats = (
        '<tspan fill="%s">%d merged</tspan><tspan fill="%s"> &#183; %s</tspan>'
        % (p["accent"], stat["merged"], p["muted"], prs)
        if stat["merged"] else
        '<tspan fill="%s">%s</tspan>' % (p["muted"], prs)
    )
    body = (
        '  <rect x="0" y="0" width="%d" height="%d" rx="10" fill="%s" stroke="%s"/>\n'
        '  <circle cx="20" cy="%d" r="4" fill="%s"/>\n'
        '  <text x="40" y="31" font-family="%s" font-size="22" fill="%s">%s</text>\n'
        '  <text x="%d" y="31" text-anchor="end" font-family="%s" font-size="20">'
        '%s</text>\n'
        % (WIDTH, OSS_ROW_H, p["panel"], p["border"],
           OSS_ROW_H // 2, p["accent"] if stat["merged"] else p["muted"],
           SANS, p["text"], esc(repo),
           WIDTH - 20, SANS, stats)
    )
    return svg_doc(height, repo, body)


def oss_merge_svg(merge, p):
    height = OSS_MERGE_H + OSS_ROW_GAP
    label = "%s#%s" % (merge["repo"], merge["number"])
    title = truncate(merge["title"], 72)
    body = (
        '  <rect x="0" y="0" width="%d" height="%d" rx="10" fill="%s" stroke="%s"/>\n'
        '  <circle cx="20" cy="%d" r="4" fill="%s"/>\n'
        '  <text x="40" y="22" font-family="%s" font-size="18" fill="%s">%s</text>\n'
        '  <text x="40" y="44" font-family="%s" font-size="18" fill="%s">%s</text>\n'
        % (WIDTH, OSS_MERGE_H, p["panel"], p["border"],
           OSS_MERGE_H // 2, p["accent"],
           SANS, p["accent"], esc(label),
           SANS, p["text"], esc(title))
    )
    return svg_doc(height, label, body)


def md_picture(name, alt, href=None):
    dark = "%s/%s-dark.svg" % (OSS_CDN, name)
    light = "%s/%s-light.svg" % (OSS_CDN, name)
    inner = (
        "<picture>\n"
        '  <source media="(prefers-color-scheme: dark)" srcset="%s">\n'
        '  <source media="(prefers-color-scheme: light)" srcset="%s">\n'
        '  <img src="%s" width="100%%" alt="%s">\n'
        "</picture>"
        % (dark, light, dark, esc(alt))
    )
    if not href:
        return inner
    return '<a href="%s">\n%s\n</a>' % (esc(href), inner)


def oss_search_url():
    q = "is:pr author:%s -user:%s" % (LOGIN, LOGIN)
    return "https://github.com/search?q=%s&type=pullrequests" % urllib.parse.quote(q)


def oss_readme_block(rows, hidden, merges):
    parts = [md_picture("oss-caption", "Pull requests to repositories I do not own")]
    for index, (repo, _) in enumerate(rows):
        parts.append(md_picture(
            "oss-repo-%02d" % index, repo, "https://github.com/%s" % repo))
    if hidden:
        parts.append(md_picture("oss-more", "and %d more" % hidden, oss_search_url()))
    if merges:
        parts.append(md_picture("oss-merges-caption", "Latest merges"))
        for index, merge in enumerate(merges):
            label = "%s#%s" % (merge["repo"], merge["number"])
            parts.append(md_picture(
                "oss-merge-%02d" % index, label,
                "https://github.com/%s" % merge["repo"]))
    return "\n".join(parts)


def clear_stale_oss_rows(assets):
    patterns = (
        "oss-dark.svg", "oss-light.svg",
        "oss-caption-*.svg", "oss-repo-*.svg", "oss-more-*.svg",
        "oss-merges-caption-*.svg", "oss-merge-*.svg",
    )
    for pattern in patterns:
        for path in glob.glob(os.path.join(assets, pattern)):
            os.remove(path)


def bust_activity_urls(text, token):
    """GitHub Camo caches README images by exact URL. Bump ?v= so a new
    activity card is fetched instead of the previous day's SVG."""
    return ACTIVITY_URL_RE.sub(r"\1?v=%s" % token, text)


def patch_readme_activity_bust(token):
    readme = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), os.pardir, "README.md")
    text = open(readme, encoding="utf-8").read()
    updated = bust_activity_urls(text, token)
    if updated == text and "activity-dark.svg?v=" not in text:
        sys.exit("could not find activity card URLs in README.md")
    open(readme, "w", encoding="utf-8").write(updated)
    print("wrote README.md activity cache-bust v=%s" % token)


def patch_readme_oss(block):
    readme = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), os.pardir, "README.md")
    text = open(readme, encoding="utf-8").read()
    text = patch_markers(text, OSS_MARK_START, OSS_MARK_END, block)
    open(readme, "w", encoding="utf-8").write(text)
    print("wrote README.md OSS links")


def patch_readme_section(start, end, block):
    readme = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), os.pardir, "README.md")
    text = open(readme, encoding="utf-8").read()
    if start not in text or end not in text:
        sys.exit("could not find markers %s %s in README.md" % (start, end))
    open(readme, "w", encoding="utf-8").write(patch_markers(text, start, end, block))
    print("wrote README.md %s" % start)


ISO_SHADES = {
    "dark": {
        0: ("#3B3B41", "#2C2C31", "#26262B"),
        1: ("#8F4A40", "#6B3830", "#542C26"),
        2: ("#C45A48", "#A0483A", "#7A372C"),
        3: ("#E86850", "#D0503C", "#A03C2E"),
        4: ("#FF7A62", "#F05138", "#C03E2C"),
    },
    "light": {
        0: ("#D8D8DC", "#E8E8EC", "#D0D0D4"),
        1: ("#F7C8C0", "#E8A090", "#D48878"),
        2: ("#F49A88", "#E87868", "#D06050"),
        3: ("#F56C58", "#F05138", "#D04430"),
        4: ("#FF5A42", "#F05138", "#C03E2C"),
    },
}

WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


def iso_cube(x, y, dx, dy, h, top, left, right):
    hw = dx / 2.0
    hh = dy / 2.0
    top_pts = "%.1f,%.1f %.1f,%.1f %.1f,%.1f %.1f,%.1f" % (
        x, y - h,
        x + hw, y + hh - h,
        x, y + dy - h,
        x - hw, y + hh - h,
    )
    left_pts = "%.1f,%.1f %.1f,%.1f %.1f,%.1f %.1f,%.1f" % (
        x - hw, y + hh - h,
        x, y + dy - h,
        x, y + dy,
        x - hw, y + hh,
    )
    right_pts = "%.1f,%.1f %.1f,%.1f %.1f,%.1f %.1f,%.1f" % (
        x + hw, y + hh - h,
        x, y + dy - h,
        x, y + dy,
        x + hw, y + hh,
    )
    return (
        '  <polygon points="%s" fill="%s"/>\n'
        '  <polygon points="%s" fill="%s"/>\n'
        '  <polygon points="%s" fill="%s"/>\n'
        % (top_pts, top, left_pts, left, right_pts, right)
    )


def iso_card(weeks, p, theme):
    grid = []
    for week in weeks[-52:]:
        col = [day["contributionCount"] for day in week["contributionDays"]]
        while len(col) < 7:
            col.append(0)
        grid.append(col[:7])
    if not grid:
        grid = [[0] * 7]
    max_c = max(c for col in grid for c in col) or 1
    dx, dy = 18, 14
    ox, oy = 52, 18
    max_h = 28
    cols = len(grid)
    height = int(oy + 7 * dy + max_h + 18)
    out = svg_open(height, "Isometric contribution calendar for the last 12 months.")
    shades = ISO_SHADES[theme]
    for d, name in enumerate(WEEKDAYS):
        out += ('  <text x="0" y="%d" font-family="%s" font-size="12" fill="%s">%s</text>\n'
                % (int(oy + max_h + d * dy + 6), SANS, p["muted"], name))
    for w in range(cols - 1, -1, -1):
        for d in range(6, -1, -1):
            level = contrib_level(grid[w][d], max_c)
            h = 2 + level * 5
            x = ox + w * dx + d * (dx * 0.42)
            y = oy + max_h + d * dy
            top, left, right = shades[level]
            out += iso_cube(x, y, dx, dy, h, top, left, right)
    out += "</svg>\n"
    return out


def habits_card(weeks, p):
    counts = weekday_counts(weeks)
    peak = max(counts) or 1
    busiest = WEEKDAYS[counts.index(peak)]
    gap = 21
    col_w = (WIDTH - 6 * gap) // 7
    bar_max = 86
    height = 168
    out = svg_open(
        height,
        "Commits by weekday. Busiest day is %s." % busiest)
    out += ('  <text x="0" y="22" font-family="%s" font-size="18" font-weight="600" '
            'letter-spacing="1.4" fill="%s">When I ship</text>\n' % (SANS, p["muted"]))
    for i, name in enumerate(WEEKDAYS):
        x = i * (col_w + gap)
        h = int(round(bar_max * counts[i] / peak)) if peak else 0
        y = 36 + (bar_max - h)
        fill = p["accent"] if counts[i] == peak else p["panel"]
        stroke = p["accent"] if counts[i] == peak else p["border"]
        out += ('  <rect x="%d" y="%d" width="%d" height="%d" rx="10" fill="%s" stroke="%s"/>\n'
                % (x, y, col_w, max(h, 8), fill, stroke))
        out += ('  <text x="%d" y="150" text-anchor="middle" font-family="%s" '
                'font-size="16" fill="%s">%s</text>\n'
                % (x + col_w // 2, SANS, p["muted"], name))
    out += "</svg>\n"
    return out


def feed_row_svg(row, p):
    height = OSS_MERGE_H + OSS_ROW_GAP
    body = (
        '  <rect x="0" y="0" width="%d" height="%d" rx="10" fill="%s" stroke="%s"/>\n'
        '  <circle cx="20" cy="%d" r="4" fill="%s"/>\n'
        '  <text x="40" y="22" font-family="%s" font-size="18" fill="%s">%s</text>\n'
        '  <text x="40" y="44" font-family="%s" font-size="18" fill="%s">%s</text>\n'
        % (WIDTH, OSS_MERGE_H, p["panel"], p["border"],
           OSS_MERGE_H // 2, p["accent"],
           SANS, p["accent"], esc(row["verb"]),
           SANS, p["text"], esc(row["detail"] or row["label"]))
    )
    return svg_doc(height, "%s %s" % (row["verb"], row["label"]), body)


def app_card_svg(app, p):
    height = 88
    badge = "App Store" if app["store"] else "WIP"
    body = (
        '  <rect x="0" y="0" width="%d" height="80" rx="14" fill="%s" stroke="%s"/>\n'
        '  <circle cx="24" cy="40" r="5" fill="%s"/>\n'
        '  <text x="46" y="30" font-family="%s" font-size="24" font-weight="600" fill="%s">%s</text>\n'
        '  <text x="46" y="52" font-family="%s" font-size="16" fill="%s">%s</text>\n'
        '  <text x="46" y="70" font-family="%s" font-size="16" fill="%s">%s</text>\n'
        '  <text x="%d" y="44" text-anchor="end" font-family="%s" font-size="18" fill="%s">%s</text>\n'
        % (WIDTH, p["panel"], p["border"],
           p["accent"],
           SANS, p["text"], esc(app["name"]),
           SANS, p["muted"], esc(app["chips"]),
           SANS, p["text"], esc(app["blurb"]),
           WIDTH - 24, SANS, p["accent"], badge)
    )
    return svg_doc(height, app["name"], body)


def write_oss(data, assets):
    rows = data["external"][:8]
    merges = data.get("latest_merges") or []
    hidden = len(data["external"]) - len(rows)
    clear_stale_oss_rows(assets)
    caption = "Pull requests to repositories I do not own"
    for theme, p in PALETTES.items():
        write(os.path.join(assets, "oss-caption-%s.svg" % theme),
              oss_caption_svg(caption, OSS_CAPTION_H, p))
        for index, (repo, stat) in enumerate(rows):
            write(os.path.join(assets, "oss-repo-%02d-%s.svg" % (index, theme)),
                  oss_repo_svg(repo, stat, p))
        if hidden:
            write(os.path.join(assets, "oss-more-%s.svg" % theme),
                  oss_caption_svg("and %d more" % hidden, OSS_MORE_H, p))
        if merges:
            write(os.path.join(assets, "oss-merges-caption-%s.svg" % theme),
                  oss_caption_svg("Latest merges", OSS_MERGES_CAPTION_H, p, weight="600"))
            for index, merge in enumerate(merges):
                write(os.path.join(assets, "oss-merge-%02d-%s.svg" % (index, theme)),
                      oss_merge_svg(merge, p))
    patch_readme_oss(oss_readme_block(rows, hidden, merges))


def write_feed(data, assets):
    rows = data.get("feed") or []
    for theme, p in PALETTES.items():
        for index, row in enumerate(rows):
            write(os.path.join(assets, "feed-%02d-%s.svg" % (index, theme)),
                  feed_row_svg(row, p))
    parts = []
    for index, row in enumerate(rows):
        parts.append(md_picture(
            "feed-%02d" % index,
            "%s %s" % (row["verb"], row["label"]),
            row["href"]))
    block = "\n".join(parts) if parts else "_No public events yet._"
    patch_readme_section("<!-- feed:start -->", "<!-- feed:end -->", block)


def app_readme_block(assets):
    parts = []
    for app in APPS:
        href = app["store"] or app["github"]
        parts.append(md_picture("app-%s" % app["slug"], app["name"], href))
    return "\n".join(parts)


def write_apps(assets):
    for theme, p in PALETTES.items():
        for app in APPS:
            write(os.path.join(assets, "app-%s-%s.svg" % (app["slug"], theme)),
                  app_card_svg(app, p))
    patch_readme_section("<!-- apps:start -->", "<!-- apps:end -->",
                         app_readme_block(assets))


def write_viz(data, assets):
    weeks = data["weeks"]
    for theme, p in PALETTES.items():
        write(os.path.join(assets, "iso-%s.svg" % theme),
              iso_card(weeks, p, theme))
        write(os.path.join(assets, "habits-%s.svg" % theme),
              habits_card(weeks, p))


def render(data):
    if not data["languages"]:
        sys.exit("no language data returned; refusing to write empty cards")

    assets = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), os.pardir, "assets")
    for theme, p in PALETTES.items():
        write(os.path.join(assets, "activity-%s.svg" % theme), activity_card(data, p))
    write_oss(data, assets)
    write_apps(assets)
    patch_readme_activity_bust(
        datetime.now(timezone.utc).strftime("%Y%m%d%H%M"))

    print("contributions=%s current_streak=%s external_repos=%s merged=%s" % (
        data["contributions"], data["current_streak"],
        len(data["external"]), data["external_merged"]))


def main():
    render(collect())


if __name__ == "__main__":
    main()
