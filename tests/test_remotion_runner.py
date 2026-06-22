"""Unit tests for tools/remotion_runner.py (stdlib unittest)."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


class TestRenderVideoSubprocess(unittest.TestCase):
    @patch("tools.remotion_runner.shutil.which", return_value=r"C:\Program Files\nodejs\npx.cmd")
    @patch("tools.remotion_runner.subprocess.run")
    def test_render_uses_shell_false_and_preserves_spaced_path(self, mock_run, _mock_which):
        from tools.remotion_runner import render_video

        spaced_dir = Path(tempfile.mkdtemp()) / "paytrust admin" / "_26 v"
        spaced_dir.mkdir(parents=True)
        output = spaced_dir / "video.mp4"
        output.write_bytes(b"x" * 200_000)

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = render_video(str(output))

        mock_run.assert_called_once()
        kwargs = mock_run.call_args.kwargs
        cmd = mock_run.call_args.args[0]

        self.assertFalse(kwargs.get("shell", True))
        self.assertEqual(cmd[0], r"C:\Program Files\nodejs\npx.cmd")
        self.assertEqual(cmd[1], "remotion")
        self.assertEqual(cmd[3], "MarketingVideo")
        self.assertEqual(cmd[4], str(output.resolve()))
        self.assertIn("paytrust admin", cmd[4])
        self.assertIn("_26 v", cmd[4])
        self.assertEqual(result, str(output.resolve()))


if __name__ == "__main__":
    unittest.main()
