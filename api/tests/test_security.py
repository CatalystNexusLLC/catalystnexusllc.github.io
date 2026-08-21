from __future__ import annotations

import unittest

from app.security import InvalidToken, sign_payload, verify_payload


class SignedPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.secret = "s" * 64
        self.payload = {"kind": "session", "user_id": "abc", "exp": 2_000_000_000}

    def test_round_trip(self) -> None:
        token = sign_payload(self.payload, self.secret)
        self.assertEqual(verify_payload(token, self.secret, now=1_900_000_000), self.payload)

    def test_tampering_is_rejected(self) -> None:
        token = sign_payload(self.payload, self.secret)
        encoded, signature = token.split(".", 1)
        replacement = "A" if encoded[-1] != "A" else "B"
        with self.assertRaises(InvalidToken):
            verify_payload(f"{encoded[:-1]}{replacement}.{signature}", self.secret, now=1_900_000_000)

    def test_wrong_secret_is_rejected(self) -> None:
        token = sign_payload(self.payload, self.secret)
        with self.assertRaises(InvalidToken):
            verify_payload(token, "x" * 64, now=1_900_000_000)

    def test_expired_payload_is_rejected(self) -> None:
        token = sign_payload({**self.payload, "exp": 100}, self.secret)
        with self.assertRaises(InvalidToken):
            verify_payload(token, self.secret, now=101)

    def test_missing_expiry_is_rejected(self) -> None:
        token = sign_payload({"kind": "session"}, self.secret)
        with self.assertRaises(InvalidToken):
            verify_payload(token, self.secret, now=1)


if __name__ == "__main__":
    unittest.main()
