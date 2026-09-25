import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from dobot_draw import local_ai


class LocalAITests(unittest.TestCase):
    def test_local_generation_uses_current_python_and_local_output_without_ssh(self):
        with tempfile.TemporaryDirectory() as temp:
            photo=Path(temp)/'photo with spaces.png';photo.write_bytes(b'photo')
            process=MagicMock();process.poll.return_value=0;process.returncode=0
            def launch(command, **kwargs):
                self.assertEqual(command[0],local_ai.sys.executable)
                self.assertIn(str(photo),command)
                self.assertIn('http://127.0.0.1:8188',command)
                self.assertEqual(command[command.index('--people')+1],'3')
                Path(command[4]).with_suffix('.svg').write_text('<svg/>')
                return process
            with patch.object(local_ai,'ensure_service'),patch.object(local_ai.subprocess,'Popen',side_effect=launch):
                result=local_ai.generate(photo,Path(temp)/'outputs',threading.Event(),lambda _:None,people=3)
            self.assertTrue(result.is_file());self.assertTrue((result.parent/'generation.log').exists())
            process.terminate.assert_not_called()

    def test_cancel_does_not_start_ai(self):
        with tempfile.TemporaryDirectory() as temp:
            photo=Path(temp)/'p.png';photo.write_bytes(b'p')
            cancel=threading.Event();cancel.set()
            with patch.object(local_ai,'ensure_service') as service,patch.object(local_ai.subprocess,'Popen') as popen:
                with self.assertRaisesRegex(RuntimeError,'anulată'):
                    local_ai.generate(photo,temp,cancel,lambda _:None)
                service.assert_not_called();popen.assert_not_called()

    def test_healthy_service_is_not_restarted(self):
        with patch.object(local_ai,'ready',return_value=True),patch.object(local_ai.subprocess,'run') as run:
            local_ai.ensure_service(threading.Event(),lambda _:None)
            run.assert_not_called()

    def test_backend_defaults_and_override(self):
        with patch.dict(local_ai.os.environ,{},clear=True),patch.object(local_ai.sys,'platform','linux'):
            self.assertTrue(local_ai.local_mode())
        with patch.dict(local_ai.os.environ,{'DOBOT_AI_BACKEND':'ssh'}):
            self.assertFalse(local_ai.local_mode())
