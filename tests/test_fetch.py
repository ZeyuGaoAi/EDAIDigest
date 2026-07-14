import unittest
import xml.etree.ElementTree as ET

from digest.fetch import Source, _pubmed_date, _pubmed_search_term


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


if __name__ == "__main__":
    unittest.main()
