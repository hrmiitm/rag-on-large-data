"""No real process signals: verify temporary resource changes are restored safely."""
import signal
import unittest
from unittest.mock import patch
from resource_lease import paused_indexer

ORIGINAL={'name':'baloo_file_extr','start_ticks':'100','state':'S'}


class LeaseTests(unittest.TestCase):
    def test_restore_even_when_work_raises(self):
        with patch('resource_lease.identity',return_value=ORIGINAL),patch('resource_lease.os.kill') as send:
            with self.assertRaises(RuntimeError):
                with paused_indexer(123):raise RuntimeError('stopped work')
        self.assertEqual([c.args for c in send.call_args_list],[(123,signal.SIGSTOP),(123,signal.SIGCONT)])

    def test_reused_pid_is_not_signalled_on_restore(self):
        with patch('resource_lease.identity',side_effect=[ORIGINAL,{**ORIGINAL,'start_ticks':'101'}]),patch('resource_lease.os.kill') as send:
            with paused_indexer(123):pass
        self.assertEqual([c.args for c in send.call_args_list],[(123,signal.SIGSTOP)])

    def test_preexisting_pause_or_wrong_process_is_untouched(self):
        for entry in ({**ORIGINAL,'state':'T'},{**ORIGINAL,'name':'other'},None):
            with patch('resource_lease.identity',return_value=entry),patch('resource_lease.os.kill') as send:
                with self.assertRaises(ValueError):
                    with paused_indexer(123):pass
                send.assert_not_called()


if __name__=='__main__':unittest.main()
