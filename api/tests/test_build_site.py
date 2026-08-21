from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_site


class BuildSiteTests(unittest.TestCase):
    def test_production_build_defaults_api_base_url_when_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "_site"
            argv = [
                "build_site.py",
                "--production",
                "--api-base-url",
                "",
                "--output",
                str(output),
            ]
            with patch.object(sys, "argv", argv):
                self.assertEqual(build_site.main(), 0)
            config = (output / "portal-config.js").read_text(encoding="utf-8")
            self.assertIn('apiBaseUrl: "https://api.beta.example.com"', config)
            self.assertTrue((output / ".nojekyll").is_file())


if __name__ == "__main__":
    unittest.main()
