import json
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError
from fastapi import HTTPException
from pydantic import ValidationError
from app.desk_commands import CommandRequest, command


class DeskCommandTests(unittest.TestCase):
    def test_validation_rejects_wrong_scope_and_unknown_fields(self):
        for values in (
            {'command': 'ops', 'question': 'x'},
            {'command': 'sre'},
            {'command': 'predict', 'symbol': 'ETH'},
            {'command': 'drift', 'url': 'http://other'},
        ):
            with self.assertRaises(ValidationError):
                CommandRequest.model_validate(values)

    def test_proxy_forwards_only_server_token(self):
        result = {'answer': 'ok', 'command': 'sre', 'routing': []}
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(result).encode()
        opener = MagicMock()
        opener.open.return_value = response
        with (
            patch('app.desk_commands.build_opener', return_value=opener),
            patch.dict('os.environ', {'WAREHOUSE_AGENT_TOKEN': 'secret'}),
        ):
            self.assertEqual(command(CommandRequest(command='sre', question='inspect')), result)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header('Authorization'), 'Bearer secret')
        self.assertEqual(json.loads(request.data)['command'], 'sre')
        self.assertNotIn('secret', json.dumps(result))

    def test_failure_redacts_provider_secrets(self):
        opener = MagicMock()
        opener.open.side_effect = RuntimeError('SECRET')
        with patch('app.desk_commands.build_opener', return_value=opener):
            with self.assertRaises(HTTPException) as exc:
                command(CommandRequest(command='anomaly'))
        self.assertEqual(exc.exception.status_code, 503)
        self.assertNotIn('SECRET', str(exc.exception.detail))

    def test_upstream_validation_remains_422(self):
        opener = MagicMock()
        opener.open.side_effect = HTTPError('http://test', 422, 'invalid', {}, None)
        with patch('app.desk_commands.build_opener', return_value=opener):
            with self.assertRaises(HTTPException) as exc:
                command(CommandRequest(command='predict'))
        self.assertEqual(exc.exception.status_code, 422)

    def test_oversized_reply_rejected(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'x' * 262145
        opener = MagicMock()
        opener.open.return_value = response
        with patch('app.desk_commands.build_opener', return_value=opener):
            with self.assertRaises(HTTPException):
                command(CommandRequest(command='predict'))

    def test_gateway_rate_limit_preserved(self):
        opener = MagicMock()
        opener.open.side_effect = HTTPError('http://test', 429, 'limited', {}, None)
        with patch('app.desk_commands.build_opener', return_value=opener):
            with self.assertRaises(HTTPException) as exc:
                command(CommandRequest(command='predict'))
        self.assertEqual(exc.exception.status_code, 429)

    def test_credentials_rejected_for_every_agent_command(self):
        secret = 'gsk_' + 'x' * 25
        for command in ('trade', 'sre'):
            with self.assertRaises(ValidationError):
                CommandRequest(command=command, question=secret)

    def test_answer_credentials_redacted(self):
        from app.response_guard import redact_response

        secret = 'sk-or-v1-' + 'x' * 25
        answer = redact_response('Value ' + secret)
        self.assertNotIn(secret, answer)
        self.assertIn('[credential redacted]', answer)
