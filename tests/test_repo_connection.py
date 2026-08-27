import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import repo


class DatabaseConnectionTests(unittest.TestCase):
    def setUp(self):
        repo._db_connections.connection = None

    def tearDown(self):
        repo._db_connections.connection = None

    @patch("repo.pymysql.connect")
    def test_connect_uses_autocommit(self, connect):
        repo.connect_to_database()

        self.assertTrue(connect.call_args.kwargs["autocommit"])

    @patch("repo.connect_to_database")
    def test_failed_ping_closes_stale_connection(self, connect):
        stale = MagicMock()
        stale.ping.side_effect = RuntimeError("connection lost")
        replacement = MagicMock()
        connect.return_value = replacement
        repo._db_connections.connection = stale

        result = repo.get_db_connection()

        stale.close.assert_called_once_with()
        self.assertIs(result, replacement)


if __name__ == "__main__":
    unittest.main()
