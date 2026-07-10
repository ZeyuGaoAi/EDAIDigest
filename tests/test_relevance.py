import unittest

from digest.relevance import score_relevance


class PaperRelevanceTests(unittest.TestCase):
    def test_rejects_generic_method_with_screening_only_in_benchmark(self):
        summary = (
            "We propose Adversarial LassoNet, a stability-driven sparse feature-selection "
            "framework for high-dimensional machine learning. Experiments on public benchmark "
            "datasets show improved robustness and reproducibility. "
            + "x" * 750
            + " On a lung cancer screening dataset, it improves AUC."
        )
        score = score_relevance(
            "paper",
            "Adversarial LassoNet: Robust Feature Selection via Stability-Driven Sparse Learning",
            summary,
        )
        self.assertEqual(score, 0.0)

    def test_accepts_method_targeting_early_cancer_screening(self):
        summary = (
            "Early detection of oral cancer needs scalable screening tools. "
            "We develop a lightweight deep learning classifier for smartphone images."
        )
        score = score_relevance(
            "paper",
            "Edge AI for oral cancer detection",
            summary,
        )
        self.assertGreater(score, 0.0)


if __name__ == "__main__":
    unittest.main()
