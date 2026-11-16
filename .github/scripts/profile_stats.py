import json
import re
import subprocess
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path


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


def language_summary(pages):
    sizes = Counter()
    for page in pages:
        for repository in page["data"]["user"]["repositories"]["nodes"]:
            if repository["name"].casefold() == "antojerrin":
                continue
            for edge in repository["languages"]["edges"]:
                sizes[edge["node"]["name"]] += edge["size"]
    total = sizes.total()
    if not total:
        return "GitHub reports no detected languages for the included repositories."
    return " · ".join(
        f"**{name}** {size / total:.1%}"
        for name, size in sorted(sizes.items(), key=lambda entry: (-entry[1], entry[0]))[:8]
    )


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
    languages = language_summary(query_graphql(LANGUAGES, paginate=True))
    readme = Path("README.md")
    updated = replace_section(readme.read_text(encoding="utf-8"), "contribution-stats", (
        "| Contributions | Current streak | Longest streak |\n"
        "| ---: | ---: | ---: |\n"
        f"| {total:,} | {current:,} days | {longest:,} days |\n\n"
        f"*GitHub contribution calendar for the past year. Last refreshed {today:%d %b %Y} (UTC).*"
    ))
    updated = replace_section(updated, "language-stats", (
        "**Top languages by detected code bytes** · Public, owned, non-fork repositories\n\n"
        f"{languages}"
    ))
    readme.write_text(updated, encoding="utf-8")


if __name__ == "__main__":
    main()
