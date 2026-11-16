import json
import re
import subprocess
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape


CONTRIBUTIONS = """
query {
  user(login: "ANTOJERRIN") {
    contributionsCollection {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

LANGUAGES = """
query($endCursor: String) {
  user(login: "ANTOJERRIN") {
    repositories(first: 20, after: $endCursor, isFork: false, privacy: PUBLIC,
                 ownerAffiliations: OWNER) {
      nodes {
        name
        languages(first: 100, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


def query_graphql(query, paginate=False):
    command = ["gh", "api", "graphql", "-f", f"query={query}"]
    if paginate:
        command.extend(["--paginate", "--slurp"])
    response = json.loads(subprocess.check_output(command))
    return response


def contribution_stats(weeks, today):
    days = sorted(
        (date.fromisoformat(day["date"]), day["contributionCount"])
        for week in weeks
        for day in week["contributionDays"]
        if day["date"] <= today.isoformat()
    )
    if not days or days[-1][0] < today - timedelta(days=1):
        raise ValueError("GitHub returned an incomplete contribution calendar")

    longest = streak = total = 0
    previous = None
    last_active = None
    for day, count in days:
        if count:
            streak = streak + 1 if previous == day - timedelta(days=1) else 1
            last_active = day
            longest = max(longest, streak)
        previous = day if count else None
        total += count

    current = streak if last_active in (today, today - timedelta(days=1)) else 0
    return total, current, longest


def language_shares(pages):
    sizes = Counter()
    for page in pages:
        for repository in page["data"]["user"]["repositories"]["nodes"]:
            if repository["name"].casefold() == "antojerrin":
                continue
            for edge in repository["languages"]["edges"]:
                sizes[edge["node"]["name"]] += edge["size"]
    total = sizes.total()
    return [
        (name, size / total)
        for name, size in sorted(sizes.items(), key=lambda entry: (-entry[1], entry[0]))[:8]
    ]


def card(width, height, title, background, border, foreground, elements):
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title">',
        f'<title id="title">{escape(title)}</title>',
        f'<rect x=".5" y=".5" width="{width - 1}" height="{height - 1}" rx="6" '
        f'fill="{background}" stroke="{border}"/>',
        f'<g font-family="Segoe UI, Arial, sans-serif" fill="{foreground}">',
        *elements,
        '</g>',
        '</svg>',
        '',
    ])


def contribution_card(total, current, longest, today):
    title = (f"{total:,} contributions, {current} day current streak, "
             f"{longest} day longest streak. Updated {today:%d %b %Y} UTC.")
    elements = [
        '<path d="M207 55v110 M413 55v110" stroke="#d8dee4"/>',
        '<text x="310" y="175" text-anchor="middle" font-size="12" fill="#57606a">days</text>',
        '<text x="517" y="175" text-anchor="middle" font-size="12" fill="#57606a">days</text>',
        '<circle cx="310" cy="89" r="36" fill="none" stroke="#c45100" stroke-width="4"/>',
        '<path d="M310 32c2-7 9-11 7-19 7 6 9 13 6 19 3-2 4-5 5-7 '
        '5 13-3 21-14 21-10 0-17-8-13-18 1-3 3-6 5-8-1 6 1 10 4 12z" fill="#c45100"/>',
        f'<text x="310" y="204" text-anchor="middle" font-size="12" fill="#57606a">'
        f'Past year · Updated {today:%d %b %Y} UTC</text>',
    ]
    for x, value, label, color in (
        (103, total, "Total Contributions", "#24292f"),
        (310, current, "Current Streak", "#a33f00"),
        (517, longest, "Longest Streak", "#24292f"),
    ):
        elements.extend([
            f'<text x="{x}" y="99" text-anchor="middle" font-size="30" '
            f'font-weight="700">{value:,}</text>',
            f'<text x="{x}" y="155" text-anchor="middle" font-size="16" '
            f'font-weight="600" fill="{color}">{label}</text>',
        ])
    return card(620, 225, title, "#ffffff", "#d0d7de", "#24292f", elements)


def language_card(shares):
    title = "Top languages by code bytes in public, owned, non-fork repositories"
    colors = ("#3572a5", "#da5b0b", "#a8b9cc", "#3178c6", "#f1e05a", "#e4cc98",
              "#f34b7d", "#00b4ab")
    elements = ['<rect x="24" y="20" width="392" height="8" rx="4" fill="#30363d"/>',
                '<clipPath id="bar"><rect x="24" y="20" width="392" height="8" rx="4"/></clipPath>']
    position = 24
    for index, (name, share) in enumerate(shares):
        color = colors[index]
        width = share * 392
        elements.append(f'<rect x="{position:.3f}" y="20" width="{width:.3f}" height="8" '
                        f'fill="{color}" clip-path="url(#bar)"/>')
        position += width
        x = 29 + (index % 2) * 196
        y = 54 + (index // 2) * 23
        elements.extend([
            f'<circle cx="{x}" cy="{y - 4}" r="4.5" fill="{color}"/>',
            f'<text x="{x + 12}" y="{y}" font-size="13">{escape(name)} {share:.1%}</text>',
        ])
    if not shares:
        elements.append('<text x="24" y="54" font-size="13">No detected languages</text>')
    height = 75 + max(0, (len(shares) - 1) // 2) * 23
    return card(440, height, title, "#0d1117", "#30363d", "#e6edf3", elements)


def replace_section(readme, name, content):
    pattern = rf"(?m)^(<!-- {name}:start -->)\n[\s\S]*?^(<!-- {name}:end -->)$"
    updated, matches = re.subn(pattern, lambda match: "\n".join(
        (match[1], "", content, "", match[2])
    ), readme)
    if matches != 1:
        raise ValueError(f"Expected one README section for {name}, found {matches}")
    return updated


def main():
    today = datetime.now(UTC).date()
    user = query_graphql(CONTRIBUTIONS)["data"]["user"]
    weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
    total, current, longest = contribution_stats(weeks, today)
    shares = language_shares(query_graphql(LANGUAGES, paginate=True))
    cards = {
        "github-contribution-stats.svg": contribution_card(total, current, longest, today),
        "github-top-languages.svg": language_card(shares),
    }
    readme = Path("README.md")
    updated = replace_section(readme.read_text(encoding="utf-8"), "contribution-stats", (
        '<a href="https://github.com/ANTOJERRIN">'
        '<img width="620" src="./assets/github-contribution-stats.svg" '
        f'alt="{total:,} contributions in the past year, {current} day current streak, '
        f'{longest} day longest streak"></a>'
    ))
    updated = replace_section(updated, "language-stats", (
        '<a href="https://github.com/ANTOJERRIN?tab=repositories">'
        '<img width="440" src="./assets/github-top-languages.svg" '
        'alt="Top languages by detected code bytes in public, owned, non-fork repositories"></a>'
    ))
    for filename, svg in cards.items():
        Path("assets", filename).write_text(svg, encoding="utf-8")
    readme.write_text(updated, encoding="utf-8")


if __name__ == "__main__":
    main()
