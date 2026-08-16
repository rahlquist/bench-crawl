import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from benchsuite.adapters.base import AdapterResult
from benchsuite.config import Config
from benchsuite.report import write_csv


class CsvReportingTests(unittest.TestCase):
    def test_csv_uses_model_in_filename_and_preserves_flattened_and_raw_detail(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = Config(
                base_url="http://model.test/v1",
                api_key="",
                model="org/model:Q4_K_M",
                timeout_s=10,
                results_dir=root,
                env={},
                benchmarks={},
            )
            results = {
                "mmlu": AdapterResult(
                    benchmark="mmlu",
                    status="ok",
                    metric_name="acc",
                    metric_value=0.75,
                    detail={
                        "task": "mmlu",
                        "metrics": {"acc_stderr": 0.1, "subjects": ["math", "law"]},
                    },
                ),
                "deepswe": AdapterResult(
                    benchmark="deepswe",
                    status="blocked",
                    error="missing pier",
                    detail={"prerequisites": ["pier"]},
                ),
            }
            path = write_csv(cfg, results)
            self.assertEqual(path.name, "benchmark-results-org-model-Q4_K_M.csv")
            with path.open(newline="") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 2)
            mmlu = next(row for row in rows if row["benchmark"] == "mmlu")
            self.assertEqual(mmlu["score"], "0.75")
            self.assertEqual(mmlu["detail_task"], "mmlu")
            self.assertEqual(mmlu["detail_metrics_acc_stderr"], "0.1")
            self.assertEqual(json.loads(mmlu["detail_json"])["metrics"]["subjects"], ["math", "law"])
            blocked = next(row for row in rows if row["benchmark"] == "deepswe")
            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(blocked["error"], "missing pier")


if __name__ == "__main__":
    unittest.main()
