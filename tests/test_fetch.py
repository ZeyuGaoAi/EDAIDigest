import unittest
import xml.etree.ElementTree as ET

from digest.fetch import _pubmed_date


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


if __name__ == "__main__":
    unittest.main()
