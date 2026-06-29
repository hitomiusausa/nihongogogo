import json
import tempfile
import unittest
from pathlib import Path

from nihongo_funding_watch.config import load_config


def write_config(data: dict) -> Path:
    path = Path(tempfile.mktemp(suffix=".json"))
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


class ConfigTest(unittest.TestCase):
    def test_compiles_patterns_for_reuse(self):
        path = write_config(
            {
                "exclude_title_patterns": ["広告", "PR$"],
                "generic_link_title_patterns": ["詳細はこちら"],
                "page_sources": [
                    {
                        "name": "x",
                        "url": "https://example.com",
                        "allow_url_patterns": ["/news/"],
                    }
                ],
            }
        )
        config = load_config(path)

        self.assertEqual(len(config.exclude_title_regexes), 2)
        self.assertEqual(len(config.generic_link_title_regexes), 1)
        self.assertEqual(len(config.page_sources[0].allow_url_regexes), 1)
        self.assertTrue(config.exclude_title_regexes[0].search("これは広告です"))
        self.assertTrue(config.page_sources[0].allow_url_regexes[0].search("https://x/news/1"))

    def test_invalid_regex_raises_value_error(self):
        path = write_config({"exclude_title_patterns": ["("]})
        with self.assertRaises(ValueError):
            load_config(path)

    def test_invalid_allow_url_pattern_raises_value_error(self):
        path = write_config(
            {
                "page_sources": [
                    {"name": "x", "url": "https://e.com", "allow_url_patterns": ["[unclosed"]}
                ]
            }
        )
        with self.assertRaises(ValueError):
            load_config(path)


if __name__ == "__main__":
    unittest.main()
