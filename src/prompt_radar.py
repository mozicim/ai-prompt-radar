from __future__ import annotations

import argparse
import email.utils
import hashlib
import html
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
X_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:x\.com|twitter\.com)/"
    r"(?P<user>[A-Za-z0-9_]{1,15})/status/(?P<id>\d+)",
    re.IGNORECASE,
)
COUNT_RE = re.compile(
    r"(?P<count>\d+(?:[.,]\d+)?\s*[KMB]?)\s*"
    r"(?P<label>likes?|beğeni|reposts?|retweets?|views?|görüntülenme)",
    re.IGNORECASE,
)
PROMPT_TERMS = (
    "prompt",
    "midjourney",
    "stable diffusion",
    "flux",
    "sora",
    "veo",
    "kling",
    "runway",
    "nano banana",
    "gpt image",
    "ideogram",
    "seedance",
    "negative prompt",
    "style:",
    "camera:",
    "lighting:",
    "aspect ratio",
    "photorealistic",
    "cinematic",
    "ultra-realistic",
    "yapay zekâ",
    "yapay zeka",
    "görsel üret",
    "video üret",
)
PROMPT_PAYLOAD_MARKERS = (
    "system prompt",
    "image prompt",
    "video prompt",
    "ai prompt:",
    "prompt for",
    "prompt below",
    "prompt used",
    "prompt in the comment",
    "prompt in comments",
    "prompt_details",
    "negative_prompt",
    '"prompt":',
    "'prompt':",
    "prompt👇",
    "prompt 👇",
    "prompt⬇",
    "prompt ⬇",
)


@dataclass
class Candidate:
    tweet_id: str
    url: str
    author: str = ""
    text: str = ""
    published_at: str = ""
    discovered_by: list[str] = field(default_factory=list)
    likes: int = 0
    reposts: int = 0
    replies: int = 0
    views: int = 0
    score: float = 0.0
    preview_url: str = ""
    preview_path: str = ""


def request_bytes(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; AIPromptRadar/1.0; "
                "+https://github.com/mozicim/ai-prompt-radar)"
            ),
            "Accept": "application/rss+xml, application/xml, application/json, text/xml;q=0.9, */*;q=0.5",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def clean_text(value: str) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    return re.sub(r"\s+", " ", value).strip()


def read_queries(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def search_feed_urls(query: str) -> list[str]:
    encoded = urllib.parse.quote_plus(query)
    return [
        f"https://news.google.com/rss/search?q={encoded}&hl=en&gl=US&ceid=US:en",
        f"https://www.bing.com/news/search?q={encoded}&format=rss",
    ]


def parse_date(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


def iter_feed_entries(raw: bytes) -> Iterable[dict[str, str]]:
    root = ET.fromstring(raw)
    for item in root.findall(".//item"):
        yield {
            "title": clean_text(item.findtext("title", "")),
            "link": clean_text(item.findtext("link", "")),
            "description": clean_text(item.findtext("description", "")),
            "published_at": parse_date(item.findtext("pubDate", "")),
        }


def discover_from_feed(raw: bytes, query: str) -> list[Candidate]:
    found: list[Candidate] = []
    for entry in iter_feed_entries(raw):
        haystack = " ".join((entry["link"], entry["title"], entry["description"]))
        matches = list(X_URL_RE.finditer(haystack))
        for match in matches:
            found.append(
                Candidate(
                    tweet_id=match.group("id"),
                    url=f"https://x.com/{match.group('user')}/status/{match.group('id')}",
                    author=match.group("user"),
                    text=entry["title"] or entry["description"],
                    published_at=entry["published_at"],
                    discovered_by=[query],
                )
            )
    return found


def discover_from_search_results(
    results: Iterable[dict[str, object]], query: str
) -> list[Candidate]:
    found: list[Candidate] = []
    for result in results:
        href = str(result.get("href") or result.get("url") or "")
        title = clean_text(str(result.get("title") or ""))
        body = clean_text(str(result.get("body") or result.get("description") or ""))
        haystack = " ".join((href, title, body))
        for match in X_URL_RE.finditer(haystack):
            found.append(
                Candidate(
                    tweet_id=match.group("id"),
                    url=f"https://x.com/{match.group('user')}/status/{match.group('id')}",
                    author=match.group("user"),
                    text=" ".join(part for part in (title, body) if part),
                    discovered_by=[f"web:{query}"],
                )
            )
    return found


def discover_with_metasearch(queries: list[str], timeout: int) -> list[Candidate]:
    try:
        from ddgs import DDGS
    except ImportError:
        print("warning: ddgs is unavailable; using RSS discovery only", file=sys.stderr)
        return []

    found: list[Candidate] = []
    # Broad queries cover the main visual/video prompt tools while keeping the
    # number of anonymous search requests polite and GitHub Actions-friendly.
    metasearch_queries = [
        'site:x.com/*/status ("Nano Banana" OR "GPT Image") prompt',
        'site:x.com/*/status ("Veo" OR "Kling" OR "Sora") prompt',
        'site:x.com/*/status ("Midjourney" OR "Flux") prompt',
        'site:x.com/*/status "AI prompt" cinematic',
        'site:x.com/*/status ("görsel prompt" OR "video promptu")',
    ]
    metasearch_queries.extend(queries[:3])

    client = DDGS(timeout=timeout)
    for index, query in enumerate(dict.fromkeys(metasearch_queries)):
        try:
            results = client.text(
                query,
                region="wt-wt",
                safesearch="moderate",
                timelimit="m",
                max_results=15,
                backend="auto",
            )
            found.extend(discover_from_search_results(results, query))
        except Exception as exc:
            print(f"warning: metasearch failed for {query}: {exc}", file=sys.stderr)
        if index + 1 < len(metasearch_queries):
            time.sleep(0.8)
    return found


def merge_candidates(items: Iterable[Candidate]) -> list[Candidate]:
    merged: dict[str, Candidate] = {}
    for item in items:
        existing = merged.get(item.tweet_id)
        if not existing:
            merged[item.tweet_id] = item
            continue
        existing.discovered_by = sorted(
            set(existing.discovered_by + item.discovered_by)
        )
        if len(item.text) > len(existing.text):
            existing.text = item.text
        if not existing.published_at:
            existing.published_at = item.published_at
    return list(merged.values())


def parse_count(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if not isinstance(value, str):
        return 0
    normalized = value.strip().upper().replace(",", "")
    multiplier = 1
    if normalized.endswith("K"):
        multiplier, normalized = 1_000, normalized[:-1]
    elif normalized.endswith("M"):
        multiplier, normalized = 1_000_000, normalized[:-1]
    elif normalized.endswith("B"):
        multiplier, normalized = 1_000_000_000, normalized[:-1]
    try:
        return int(float(normalized) * multiplier)
    except ValueError:
        return 0


def enrich_candidate(item: Candidate, timeout: int) -> Candidate:
    # FixTweet exposes public post/embed metadata without an API key. A failed
    # enrichment is non-fatal: discovery text remains usable.
    url = f"https://api.fxtwitter.com/status/{item.tweet_id}"
    try:
        payload = json.loads(request_bytes(url, timeout).decode("utf-8"))
        tweet = payload.get("tweet") or {}
        author = tweet.get("author") or {}
        item.author = (
            author.get("screen_name") or author.get("name") or item.author
        )
        item.text = clean_text(tweet.get("text") or item.text)
        item.published_at = tweet.get("created_at") or item.published_at
        item.likes = parse_count(tweet.get("likes"))
        item.reposts = parse_count(tweet.get("retweets"))
        item.replies = parse_count(tweet.get("replies"))
        item.views = parse_count(tweet.get("views"))
        media = tweet.get("media") or {}
        media_items = media.get("all") or []
        if media_items and isinstance(media_items[0], dict):
            first_media = media_items[0]
            item.preview_url = str(
                first_media.get("thumbnail_url")
                or first_media.get("url")
                or ""
            )
        canonical = tweet.get("url")
        if isinstance(canonical, str) and X_URL_RE.search(canonical):
            item.url = canonical.replace("twitter.com", "x.com")
    except Exception as exc:  # Network providers are deliberately best-effort.
        print(f"warning: enrichment failed for {item.tweet_id}: {exc}", file=sys.stderr)
    return item


def preview_extension(url: str) -> str:
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".jpg"


def download_preview(item: Candidate, run_date: date, timeout: int) -> None:
    if not item.preview_url:
        return
    relative = (
        Path("assets")
        / run_date.isoformat()
        / f"{item.tweet_id}{preview_extension(item.preview_url)}"
    )
    absolute = ROOT / "archive" / f"{run_date:%Y}" / f"{run_date:%m}" / relative
    try:
        absolute.parent.mkdir(parents=True, exist_ok=True)
        if not absolute.exists():
            raw = request_bytes(item.preview_url, timeout)
            if len(raw) > 5_000_000:
                raise ValueError("preview exceeds 5 MB")
            absolute.write_bytes(raw)
        item.preview_path = relative.as_posix()
    except Exception as exc:
        print(
            f"warning: preview download failed for {item.tweet_id}: {exc}",
            file=sys.stderr,
        )


def extract_inline_counts(item: Candidate) -> None:
    for match in COUNT_RE.finditer(item.text):
        count = parse_count(match.group("count").replace(" ", ""))
        label = match.group("label").lower()
        if "like" in label or "beğeni" in label:
            item.likes = max(item.likes, count)
        elif "repost" in label or "retweet" in label:
            item.reposts = max(item.reposts, count)
        else:
            item.views = max(item.views, count)


def prompt_likelihood(text: str) -> float:
    lowered = text.lower()
    term_hits = sum(1 for term in PROMPT_TERMS if term in lowered)
    structure = 0
    structure += 7 if len(text) >= 180 else 3 if len(text) >= 90 else 0
    structure += 4 if ":" in text else 0
    structure += 3 if any(mark in text for mark in ("[", "{", "•", "\n")) else 0
    return min(35.0, term_hits * 5.0 + structure)


def is_prompt_content(text: str) -> bool:
    lowered = text.lower()
    if any(marker in lowered for marker in PROMPT_PAYLOAD_MARKERS):
        return True
    if re.search(r"\bprompt\s*[:：]\s*\S", lowered):
        return True
    # Some creators start directly with an imperative instead of adding a
    # Prompt label. Require both detailed generation language and substantial
    # payload length so ordinary AI news is not mistaken for a prompt.
    generation_openers = (
        "create a ",
        "generate a ",
        "an ultra-realistic ",
        "a cinematic ",
        "cinematic photoreal",
    )
    visual_specs = (
        "lighting",
        "camera",
        "aspect ratio",
        "depth of field",
        "photorealistic",
        "negative prompt",
    )
    return (
        len(text) >= 220
        and any(opener in lowered for opener in generation_openers)
        and sum(spec in lowered for spec in visual_specs) >= 2
    )


def freshness_score(published_at: str, now: datetime) -> float:
    if not published_at:
        return 2.0
    try:
        parsed = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (now - parsed.astimezone(timezone.utc)).total_seconds() / 3600)
        return max(0.0, 12.0 - age_hours / 6.0)
    except ValueError:
        return 2.0


def score_candidate(item: Candidate, now: datetime) -> float:
    engagement = (
        math.log10(item.likes + 1) * 5.0
        + math.log10(item.reposts + 1) * 6.0
        + math.log10(item.replies + 1) * 2.0
        + math.log10(item.views + 1) * 2.0
    )
    cross_source = min(8.0, max(0, len(item.discovered_by) - 1) * 2.0)
    item.score = round(
        prompt_likelihood(item.text)
        + freshness_score(item.published_at, now)
        + engagement
        + cross_source,
        2,
    )
    return item.score


def load_seen(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def markdown_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def markdown_code_block(value: str) -> list[str]:
    longest_run = max((len(run) for run in re.findall(r"~+", value)), default=0)
    fence = "~" * max(3, longest_run + 1)
    return [f"{fence}text", value.strip(), fence]


def write_outputs(items: list[Candidate], run_date: date, seen_path: Path) -> None:
    archive_dir = ROOT / "archive" / f"{run_date:%Y}" / f"{run_date:%m}"
    archive_dir.mkdir(parents=True, exist_ok=True)
    json_path = archive_dir / f"{run_date.isoformat()}.json"
    md_path = archive_dir / f"{run_date.isoformat()}.md"

    payload = {
        "date": run_date.isoformat(),
        "count": len(items),
        "method": "public-search-rss-plus-keyless-public-embed",
        "items": [asdict(item) for item in items],
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        f"# AI Prompt Radar — {run_date.isoformat()}",
        "",
        f"Bugün bulunan yeni prompt sayısı: **{len(items)}**",
        "",
    ]
    if not items:
        lines.append("Eşik değerini geçen yeni bir gönderi bulunamadı.")
    else:
        for index, item in enumerate(items, 1):
            engagement = (
                f"❤ {item.likes} · 🔁 {item.reposts} · 👁 {item.views}"
            )
            author = f"@{markdown_escape(item.author)}" if item.author else "—"
            lines.extend(
                [
                    f"## {index}. {author}",
                    "",
                ]
            )
            if item.preview_path:
                lines.extend(
                    [
                        f'<img src="{item.preview_path}" width="420" alt="Prompt görseli">',
                        "",
                    ]
                )
            lines.extend(
                [
                    f"**Puan:** {item.score:.2f} &nbsp; **Etkileşim:** {engagement}",
                    "",
                    "**Tam prompt:**",
                    "",
                    *markdown_code_block(item.text or "Prompt metni alınamadı."),
                    "",
                    f"[Kaynak paylaşımı X'te aç ↗]({item.url})",
                    "",
                    "---",
                    "",
                ]
            )
    lines.extend(
        [
            "",
            "_Kaynak içerikler ilgili yazarlara aittir; özgün bağlantılar korunmuştur._",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")

    seen = load_seen(seen_path)
    for item in items:
        seen[item.tweet_id] = run_date.isoformat()
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(
        json.dumps(seen, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_fixture(path: Path, queries: list[str]) -> list[Candidate]:
    raw = path.read_bytes()
    return discover_from_feed(raw, queries[0] if queries else "fixture")


def collect(queries: list[str], timeout: int, fixture: Path | None) -> list[Candidate]:
    if fixture:
        return load_fixture(fixture, queries)

    discovered: list[Candidate] = discover_with_metasearch(queries, timeout)
    urls: list[tuple[str, str]] = []
    for query in queries:
        urls.extend((url, query) for url in search_feed_urls(query))
    extra = os.getenv("RADAR_EXTRA_RSS", "")
    urls.extend((url.strip(), "extra-rss") for url in extra.split(",") if url.strip())

    for index, (url, query) in enumerate(urls):
        try:
            discovered.extend(discover_from_feed(request_bytes(url, timeout), query))
        except Exception as exc:
            print(f"warning: source failed: {url}: {exc}", file=sys.stderr)
        if index + 1 < len(urls):
            time.sleep(0.3)
    return discovered


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Archive popular public AI prompts from X.")
    parser.add_argument("--fixture", type=Path, help="Read one RSS fixture instead of the network.")
    parser.add_argument("--date", help="Archive date in YYYY-MM-DD format.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_date = date.fromisoformat(args.date) if args.date else datetime.now().date()
    timeout = int(os.getenv("RADAR_TIMEOUT", "20"))
    min_score = float(os.getenv("RADAR_MIN_SCORE", "28"))
    max_items = int(os.getenv("RADAR_MAX_ITEMS", "50"))
    query_file = ROOT / os.getenv("RADAR_QUERY_FILE", "config/queries.txt")
    seen_path = ROOT / "data" / "seen.json"

    queries = read_queries(query_file)
    items = merge_candidates(collect(queries, timeout, args.fixture))
    disable_enrichment = os.getenv("RADAR_DISABLE_ENRICHMENT", "0") == "1"
    now = datetime.now(timezone.utc)
    seen = load_seen(seen_path)

    ranked: list[Candidate] = []
    for item in items:
        seen_date = seen.get(item.tweet_id)
        if seen_date and seen_date != run_date.isoformat():
            continue
        if not disable_enrichment and not args.fixture:
            enrich_candidate(item, timeout)
        extract_inline_counts(item)
        if not is_prompt_content(item.text):
            continue
        if score_candidate(item, now) >= min_score:
            ranked.append(item)

    ranked.sort(key=lambda item: (-item.score, item.tweet_id))
    selected = ranked[:max_items]
    if not args.fixture:
        for item in selected:
            download_preview(item, run_date, timeout)
    write_outputs(selected, run_date, seen_path)
    print(f"archived {len(selected)} new prompt(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
