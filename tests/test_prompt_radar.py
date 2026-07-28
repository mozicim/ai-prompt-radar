from datetime import datetime, timezone
from pathlib import Path
import unittest

from src.prompt_radar import (
    discover_from_feed,
    discover_from_search_results,
    extract_inline_counts,
    is_prompt_content,
    merge_candidates,
    prompt_likelihood,
    score_candidate,
)


FIXTURE = Path(__file__).parent / "fixtures" / "feed.xml"


class PromptRadarTests(unittest.TestCase):
    def test_discovers_x_status_and_text(self) -> None:
        items = discover_from_feed(FIXTURE.read_bytes(), "fixture-query")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].tweet_id, "1234567890123456789")
        self.assertEqual(items[0].author, "promptmaker")
        self.assertEqual(items[0].discovered_by, ["fixture-query"])

    def test_merges_queries_for_same_post(self) -> None:
        first = discover_from_feed(FIXTURE.read_bytes(), "one")
        second = discover_from_feed(FIXTURE.read_bytes(), "two")
        merged = merge_candidates(first + second)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].discovered_by, ["one", "two"])

    def test_discovers_x_status_from_metasearch_result(self) -> None:
        items = discover_from_search_results(
            [
                {
                    "title": "Popular Nano Banana prompt",
                    "href": "https://x.com/promptartist/status/9876543210987654321",
                    "body": "A cinematic portrait prompt with 50K views",
                }
            ],
            "nano banana prompt",
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].tweet_id, "9876543210987654321")
        self.assertEqual(items[0].author, "promptartist")

    def test_scores_prompt_and_engagement(self) -> None:
        item = discover_from_feed(FIXTURE.read_bytes(), "fixture")[0]
        extract_inline_counts(item)
        self.assertEqual(item.likes, 12_000)
        self.assertEqual(item.reposts, 2_000)
        self.assertGreaterEqual(prompt_likelihood(item.text), 15)
        self.assertGreaterEqual(
            score_candidate(
                item, datetime(2026, 7, 28, 10, tzinfo=timezone.utc)
            ),
            28,
        )

    def test_rejects_ai_news_without_prompt_payload(self) -> None:
        self.assertFalse(
            is_prompt_content(
                "Google released a faster Nano Banana image model today with "
                "lower prices and improved throughput for developers."
            )
        )

    def test_accepts_labeled_video_prompt(self) -> None:
        self.assertTrue(
            is_prompt_content(
                "Video Prompt: A cinematic macro world on a frozen lake, "
                "camera slowly pushes forward with dramatic blue lighting."
            )
        )


if __name__ == "__main__":
    unittest.main()
