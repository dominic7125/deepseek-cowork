from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).parents[1]


class InstallerTests(unittest.TestCase):
    def test_new_config_has_no_utf8_bom(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.toml"
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ROOT / "install.ps1"),
                    "-InstallRoot",
                    str(root / "skill"),
                    "-ConfigPath",
                    str(config),
                ],
                check=True,
                capture_output=True,
            )
            self.assertFalse(config.read_bytes().startswith(b"\xef\xbb\xbf"))


if __name__ == "__main__":
    unittest.main()
