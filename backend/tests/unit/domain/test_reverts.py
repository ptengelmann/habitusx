from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from habitusx.domain.reverts import RevertInfo, parse_revert

SHA = "3f2a9c1e5b7d4a6f8e9c0b1a2d3e4f5a6b7c8d9e"


class TestParseRevert:
    def test_git_revert_default_message(self) -> None:
        message = f'Revert "Add retry to fetcher"\n\nThis reverts commit {SHA}.\n'
        assert parse_revert(message) == RevertInfo(
            is_reapply=False,
            original_subject="Add retry to fetcher",
            reverted_sha=SHA,
        )

    def test_github_pull_request_revert(self) -> None:
        message = (
            'Revert "Add retry to fetcher (#123)" (#130)\n\n'
            f"This reverts commit {SHA}.\n\n"
            "Reverts octo/repo#123\n"
        )
        info = parse_revert(message)
        assert info is not None
        assert info.original_subject == "Add retry to fetcher (#123)"
        assert info.reverted_sha == SHA
        assert info.original_pr_number == 123
        assert info.revert_pr_number == 130
        assert info.is_reapply is False

    def test_original_pr_number_from_quoted_subject_when_no_reverts_line(self) -> None:
        message = f'Revert "Tidy imports (#77)"\n\nThis reverts commit {SHA}.'
        info = parse_revert(message)
        assert info is not None
        assert info.original_pr_number == 77
        assert info.revert_pr_number is None

    def test_reverts_line_without_owner_repo_prefix(self) -> None:
        message = 'Revert "Thing"\n\nReverts #9'
        info = parse_revert(message)
        assert info is not None
        assert info.original_pr_number == 9

    def test_reapply(self) -> None:
        message = f'Reapply "Add retry to fetcher (#123)" (#140)\n\nThis reverts commit {SHA}.'
        info = parse_revert(message)
        assert info is not None
        assert info.is_reapply is True
        assert info.original_pr_number == 123
        assert info.revert_pr_number == 140

    def test_short_sha_is_accepted_and_lowercased(self) -> None:
        message = 'Revert "X"\n\nThis reverts commit 3F2A9C1E.'
        info = parse_revert(message)
        assert info is not None
        assert info.reverted_sha == "3f2a9c1e"

    def test_subject_only_revert_without_body(self) -> None:
        info = parse_revert('Revert "Something risky"')
        assert info == RevertInfo(is_reapply=False, original_subject="Something risky")

    def test_subject_wrapped_across_lines(self) -> None:
        message = 'Revert "A very long subject that\nwrapped"\n\nBody'
        info = parse_revert(message)
        assert info is not None
        assert info.original_subject == "A very long subject that wrapped"

    def test_quotes_inside_original_subject(self) -> None:
        message = 'Revert "Rename "foo" to "bar""\n\nBody'
        info = parse_revert(message)
        assert info is not None
        assert info.original_subject == 'Rename "foo" to "bar"'

    @pytest.mark.parametrize(
        "message",
        [
            "Add retry to fetcher",
            "revert the change to fetcher",  # lowercase prose, not the git shape
            "Reverting a bad merge",
            'Fix: Revert "x" was wrong',  # not at the start
            "Revert without quotes",
            "",
            "   \n\n  ",
        ],
    )
    def test_non_reverts(self, message: str) -> None:
        assert parse_revert(message) is None

    def test_body_sha_ignored_when_subject_is_not_a_revert(self) -> None:
        assert parse_revert(f"Oops\n\nThis reverts commit {SHA}.") is None

    @given(st.text())
    def test_never_raises(self, message: str) -> None:
        result = parse_revert(message)
        assert result is None or isinstance(result, RevertInfo)
