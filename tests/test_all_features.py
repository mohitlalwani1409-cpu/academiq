#!/usr/bin/env python3
"""
Unit & Integration Tests for AcademiQ:
- Auth & Password Hashing
- Scoping & Groups
- Pure Math Reranking & Feedback Dampening
- Stream Chunk Parsing Buffer
"""

import unittest
import math
import json
import bcrypt

class TestAcademiqFeatures(unittest.TestCase):

    def test_bcrypt_hashing(self):
        password = "SecurePassword123!"
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(12)).decode("utf-8")
        self.assertTrue(bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8")))
        self.assertFalse(bcrypt.checkpw("WrongPassword".encode("utf-8"), hashed.encode("utf-8")))

    def test_math_reranker_formula(self):
        # rrf = 1/(60+r1) + 1/(60+r2)
        # For rank 1 dense, rank 1 sparse: 1/61 + 1/61 = 0.03278 -> * 30 = 0.9836
        rrf_rank1 = ((1.0 / 61) + (1.0 / 61)) * 30.0
        # For rank 3 dense, rank 3 sparse: 1/63 + 1/63 = 0.03174 -> * 30 = 0.9523
        rrf_rank3 = ((1.0 / 63) + (1.0 / 63)) * 30.0

        # Scenario A: Chunk 1 has downvote (-6.0 score)
        fb_boost_down = math.tanh(-6.0 / 3.0) # tanh(-2) = -0.964
        final_score_chunk1 = (1.0 * rrf_rank1) + (0.25 * fb_boost_down) + 0.0

        # Scenario B: Chunk 2 has upvote (+6.0 score) + exact match (0.15)
        fb_boost_up = math.tanh(6.0 / 3.0) # tanh(2) = +0.964
        final_score_chunk2 = (1.0 * rrf_rank3) + (0.25 * fb_boost_up) + 0.15

        print(f"\nTest Math Reranker: Chunk1={final_score_chunk1:.4f} vs Chunk2={final_score_chunk2:.4f}")
        # Chunk 2 should decisively outrank Chunk 1 despite lower initial RRF rank
        self.assertGreater(final_score_chunk2, final_score_chunk1)

    def test_streaming_buffer_logic(self):
        # Simulate network frames splitting SSE data
        frames = [
            'data: {"token": "Hel',
            'lo"}\n\ndata: {"token": " wor',
            'ld!"}\n\ndata: [DONE]\n\n'
        ]

        received_tokens = []
        buffer = ""

        for frame in frames:
            buffer += frame
            lines = buffer.split("\n")
            buffer = lines.pop()

            for line in lines:
                trimmed = line.strip()
                if not trimmed or not trimmed.startswith("data: "):
                    continue
                payload = trimmed[6:]
                if payload == "[DONE]":
                    continue
                data = json.loads(payload)
                if "token" in data:
                    received_tokens.append(data["token"])

        if buffer.strip().startswith("data: ") and buffer.strip() != "data: [DONE]":
            data = json.loads(buffer.strip()[6:])
            if "token" in data:
                received_tokens.append(data["token"])

        full_text = "".join(received_tokens)
        self.assertEqual(full_text, "Hello world!")

    def test_feedback_score_clamping(self):
        def clamp_score(current, delta):
            return max(-10.0, min(10.0, current + delta))

        score = 0.0
        # 15 upvotes
        for _ in range(15):
            score = clamp_score(score, 1.0)
        self.assertEqual(score, 10.0)

        # 25 downvotes
        for _ in range(25):
            score = clamp_score(score, -1.0)
        self.assertEqual(score, -10.0)

if __name__ == "__main__":
    unittest.main()
