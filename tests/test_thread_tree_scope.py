#!/usr/bin/env python3

from __future__ import annotations

from _support import PACKAGE_ROOT, SCRIPTS_ROOT

import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import thread_tree_scope as scope
import user_prompt_submit


class ScopeConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name) / "data"
        self.project = Path(self.temp.name) / "project"
        self.project.mkdir()
        self.base = {
            "schemaVersion": 1,
            "configured": True,
            "paused": False,
            "projects": [{
                "path": str(self.project),
                "includeNewChats": True,
                "includedChatIds": [],
                "excludedChatIds": [],
                "backfillExisting": True,
                "activatedAt": "2026-01-01T00:00:00+00:00",
            }],
            "pausePolicy": {"mode": "manual", "pauseOn": None, "inactivityDays": 30},
            "setupAt": "2026-01-01T00:00:00+00:00",
            "updatedAt": "2026-01-01T00:00:00+00:00",
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_unconfigured_is_fail_closed(self) -> None:
        decision = scope.scope_decision(scope.DEFAULT_SCOPE_CONFIG, str(self.project), "chat-1")
        self.assertFalse(decision["active"])
        self.assertEqual(decision["reason"], "not_configured")

    def test_save_is_canonical_and_persistent(self) -> None:
        saved = scope.save_scope_config(self.data, self.base)
        self.assertEqual(saved["projects"][0]["path"], str(self.project.resolve()))
        self.assertTrue(saved["setupAt"])
        self.assertEqual(scope.load_scope_config(self.data), saved)

    def test_project_and_chat_allowlists_are_enforced(self) -> None:
        selected = json.loads(json.dumps(self.base))
        selected["projects"][0].update({"includeNewChats": False, "includedChatIds": ["chat-1"]})
        self.assertTrue(scope.scope_decision(selected, str(self.project), "chat-1")["active"])
        self.assertEqual(
            scope.scope_decision(selected, str(self.project), "chat-2")["reason"],
            "chat_not_selected",
        )
        selected["projects"][0].update({"includeNewChats": True, "excludedChatIds": ["chat-2"]})
        self.assertEqual(
            scope.scope_decision(selected, str(self.project), "chat-2")["reason"],
            "chat_excluded",
        )

    def test_manual_date_and_inactivity_pauses(self) -> None:
        now = datetime(2026, 2, 15, 12, tzinfo=timezone.utc)
        manual = {**self.base, "paused": True}
        self.assertEqual(scope.scope_decision(manual, str(self.project), "chat", now=now)["reason"], "paused_manually")

        scheduled = json.loads(json.dumps(self.base))
        scheduled["pausePolicy"] = {"mode": "date", "pauseOn": "2026-02-15", "inactivityDays": 30}
        self.assertEqual(scope.scope_decision(scheduled, str(self.project), "chat", now=now)["reason"], "pause_date_reached")

        inactive = json.loads(json.dumps(self.base))
        inactive["pausePolicy"] = {"mode": "inactivity", "pauseOn": None, "inactivityDays": 30}
        decision = scope.scope_decision(
            inactive,
            str(self.project),
            "chat",
            last_activity_at="2026-01-01T00:00:00+00:00",
            now=now,
        )
        self.assertEqual(decision["reason"], "inactive_too_long")

    def test_invalid_or_missing_project_paths_are_rejected(self) -> None:
        missing = json.loads(json.dumps(self.base))
        missing["projects"][0]["path"] = str(Path(self.temp.name) / "missing")
        with self.assertRaisesRegex(ValueError, "does not exist"):
            scope.save_scope_config(self.data, missing)
        with self.assertRaisesRegex(ValueError, "choose at least one"):
            scope.validate_scope_config({**self.base, "projects": []})

    def test_user_prompt_hook_does_nothing_when_unconfigured(self) -> None:
        output = io.StringIO()
        event = {"prompt": "Remember this", "cwd": str(self.project), "session_id": "chat-1", "turn_id": "turn-1"}
        with patch.object(user_prompt_submit, "load_scope_config", return_value=dict(scope.DEFAULT_SCOPE_CONFIG)), \
             patch.object(user_prompt_submit, "stage_user_prompt") as stage, \
             patch.object(user_prompt_submit.sys, "stdin", io.StringIO(json.dumps(event))), \
             patch("sys.stdout", output):
            self.assertEqual(user_prompt_submit.main(), 0)
        self.assertFalse(stage.called)
        self.assertTrue(json.loads(output.getvalue())["continue"])


if __name__ == "__main__":
    unittest.main()

