import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from digest.db import connect, init_db
from digest.fetch import Source, _pubmed_date, _pubmed_search_term, fetch_html_page, upsert_items


ARTICLE = ET.fromstring(
    """
    <PubmedArticle>
      <MedlineCitation>
        <Article>
          <Journal><JournalIssue><PubDate><Year>2026</Year><Month>Jul</Month><Day>01</Day></PubDate></JournalIssue></Journal>
        </Article>
      </MedlineCitation>
      <PubmedData>
        <History>
          <PubMedPubDate PubStatus="pubmed"><Year>2026</Year><Month>3</Month><Day>26</Day></PubMedPubDate>
        </History>
      </PubmedData>
    </PubmedArticle>
    """
)


class PubmedDateTests(unittest.TestCase):
    def test_issue_preference_uses_issue_date_over_online_first_date(self):
        self.assertEqual(_pubmed_date(ARTICLE, "issue"), "2026-07-01")

    def test_online_preference_uses_online_first_date(self):
        self.assertEqual(_pubmed_date(ARTICLE), "2026-03-26")

    def test_issue_source_scopes_the_pubmed_query_by_issue_date(self):
        source = Source(
            name="High impact",
            category="paper",
            term="screening[Title/Abstract]",
            date_preference="issue",
            issue_search_days=45,
        )
        today = __import__("datetime").datetime(2026, 7, 14)
        self.assertEqual(
            _pubmed_search_term(source, today),
            "(screening[Title/Abstract]) AND (2026/05/30:2026/07/14[dp])",
        )


class HtmlPageSourceTests(unittest.TestCase):
    def test_html_page_uses_page_text_as_the_opportunity_summary(self):
        source = Source(
            name="ACED",
            category="funding",
            kind="html_page",
            url="https://example.test/aced",
            item_title="ACED Clinical Research Training Fellowship (2027)",
        )
        with patch("digest.fetch._request_text", return_value="<h1>Early cancer fellowship</h1><p>Funding available.</p>"):
            items = fetch_html_page(source)

        self.assertEqual(items[0]["title"], source.item_title)
        self.assertEqual(items[0]["summary"], "Early cancer fellowship Funding available.")

    def test_changed_page_content_returns_a_drafted_item_to_review(self):
        source = Source(name="ACED", category="funding", kind="html_page")
        first_item = {
            "title": "ACED Fellowship",
            "summary": "Cancer early detection fellowship funding.",
            "url": "https://example.test/aced",
        }
        second_item = {**first_item, "summary": "Cancer early detection fellowship funding, updated deadline."}
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "digest.db"
            init_db(db_path)
            upsert_items(db_path, source, [first_item])
            with connect(db_path) as conn:
                conn.execute("UPDATE items SET status = 'drafted'")
                conn.commit()
            upsert_items(db_path, source, [second_item])
            with connect(db_path) as conn:
                status = conn.execute("SELECT status FROM items").fetchone()["status"]

        self.assertEqual(status, "new")


if __name__ == "__main__":
    unittest.main()
