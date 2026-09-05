from __future__ import annotations

import pytest
from pydantic import ValidationError

from habitusx.domain.commits import Commit

SHA = "0123456789abcdef0123456789abcdef01234567"


def make(**overrides: object) -> Commit:
    base: dict[str, object] = {"sha": SHA, "repo": "octo/repo", "message": "Subject\n\nBody"}
    base.update(overrides)
    return Commit.model_validate(base)


class TestCommit:
    def test_subject_is_first_line(self) -> None:
        assert make(message="  Fix thing  \n\nDetails").subject == "Fix thing"

    def test_subject_of_single_line_message(self) -> None:
        assert make(message="Only line").subject == "Only line"

    def test_subject_of_empty_message(self) -> None:
        assert make(message="").subject == ""

    def test_subject_stops_at_first_newline_even_without_blank_line(self) -> None:
        assert make(message="Line one\nLine two").subject == "Line one"

    def test_sha_is_lowercased(self) -> None:
        assert make(sha=SHA.upper()).sha == SHA

    @pytest.mark.parametrize("sha", ["abc", "g" * 40, SHA + "0", ""])
    def test_invalid_sha_rejected(self, sha: str) -> None:
        with pytest.raises(ValidationError):
            make(sha=sha)

    @pytest.mark.parametrize("repo", ["octo", "octo/", "/repo", "a/b/c", "-bad/repo", "o cto/repo"])
    def test_invalid_repo_rejected(self, repo: str) -> None:
        with pytest.raises(ValidationError):
            make(repo=repo)

    @pytest.mark.parametrize(
        "repo",
        ["octo/repo", "octo-org/my.repo_v2", "a/b", "O1/R-2", "ap--/universal_pathlib", "b-/x"],
    )
    def test_valid_repo_names(self, repo: str) -> None:
        assert make(repo=repo).repo == repo

    def test_frozen(self) -> None:
        commit = make()
        with pytest.raises(ValidationError):
            commit.message = "changed"  # type: ignore[misc]

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make(unexpected="x")
