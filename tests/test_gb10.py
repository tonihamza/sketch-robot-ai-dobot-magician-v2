import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from dobot_draw.gb10 import generate


class GB10Tests(unittest.TestCase):
    def run_fake(self, cancel=False, failed=False):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);photo=root/'person with spaces.png';photo.write_bytes(b'original')
            client=MagicMock();sftp=client.open_sftp.return_value.__enter__.return_value
            sftp.stat.return_value=SimpleNamespace(st_size=50)
            channel=MagicMock();channel.recv_ready.return_value=False
            channel.exit_status_ready.return_value=not cancel
            channel.recv_exit_status.return_value=1 if failed else 0
            client.exec_command.return_value=(None,SimpleNamespace(channel=channel),None)
            sftp.get.side_effect=lambda remote,local:Path(local).write_bytes(b'result')
            event=threading.Event()
            if cancel:event.set()
            with patch('dobot_draw.gb10.paramiko.SSHClient',return_value=client):
                if cancel or failed:
                    with self.assertRaises(RuntimeError):generate(photo,root/'output','test-password',event,lambda _:None)
                    sftp.get.assert_not_called()
                else:
                    result=generate(photo,root/'output','test-password',event,lambda _:None,people=2)
                    self.assertTrue(result.is_file())
                    self.assertEqual(len(sftp.get.call_args_list),3)
                    command=client.exec_command.call_args.args[0]
                    self.assertNotIn('test-password',command)
                    self.assertNotIn(str(photo),command)
                    self.assertIn('--paper-mm 80',command)
                    self.assertIn('--people 2',command)
                    self.assertIn('/home/toni/dobot-studio/generate_robot_portrait.py',command)
                    self.assertIn('--steps 24',command)
                client.close.assert_called_once()
                if cancel:channel.send.assert_called_once_with('\x03')

    def test_success_downloads_artifacts_without_password_on_command_line(self):self.run_fake()
    def test_cancel_interrupts_own_client_and_does_not_download(self):self.run_fake(cancel=True)
    def test_remote_failure_does_not_load_partial_svg(self):self.run_fake(failed=True)


if __name__=='__main__':unittest.main()
