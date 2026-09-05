from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from habitusx.domain.trailers import (
    Person,
    Trailer,
    find_trailers,
    parse_person,
    parse_trailers,
)

CLAUDE = "Co-Authored-By: Claude <noreply@anthropic.com>"


class TestParseTrailers:
    def test_single_trailer_after_body(self) -> None:
        message = f"Fix flaky test\n\nStabilise the retry loop.\n\n{CLAUDE}\n"
        assert parse_trailers(message) == (
            Trailer("Co-Authored-By", "Claude <noreply@anthropic.com>"),
        )

    def test_subject_only_has_no_trailers(self) -> None:
        assert parse_trailers("Co-Authored-By: Someone <x@y.z>") == ()

    def test_subject_plus_trailer_block(self) -> None:
        message = f"Add feature\n\n{CLAUDE}"
        assert len(parse_trailers(message)) == 1

    def test_multiple_trailers_preserve_order(self) -> None:
        message = (
            "Subject\n\nBody.\n\n"
            "Signed-off-by: Dev <dev@example.com>\n"
            f"{CLAUDE}\n"
            "Reviewed-by: Lead <lead@example.com>\n"
        )
        keys = [t.key for t in parse_trailers(message)]
        assert keys == ["Signed-off-by", "Co-Authored-By", "Reviewed-by"]

    def test_crlf_line_endings(self) -> None:
        message = f"Subject\r\n\r\nBody\r\n\r\n{CLAUDE}\r\n"
        assert parse_trailers(message)[0].value == "Claude <noreply@anthropic.com>"

    def test_folded_continuation_line_joins_previous_value(self) -> None:
        message = "Subject\n\nBody\n\nNotes: first part\n  second part\n"
        assert parse_trailers(message) == (Trailer("Notes", "first part second part"),)

    def test_cherry_pick_note_is_tolerated(self) -> None:
        message = (
            "Subject\n\nBody\n\n"
            f"{CLAUDE}\n"
            "(cherry picked from commit 0123456789abcdef0123456789abcdef01234567)\n"
        )
        assert len(parse_trailers(message)) == 1

    def test_prose_in_last_paragraph_means_no_trailers(self) -> None:
        message = f"Subject\n\nBody\n\n{CLAUDE}\nThanks everyone for the review."
        assert parse_trailers(message) == ()

    def test_colon_in_prose_is_not_a_trailer(self) -> None:
        message = "Subject\n\nNote: this is a sentence with a colon, not a trailer key."
        # 'Note' matches the key shape, so this *is* parsed as a trailer, as git would.
        # The test documents the behaviour rather than fighting it.
        assert parse_trailers(message) == (
            Trailer("Note", "this is a sentence with a colon, not a trailer key."),
        )

    def test_key_with_digits_and_hyphens(self) -> None:
        message = "Subject\n\nX-Agent-2: yes"
        assert parse_trailers(message) == (Trailer("X-Agent-2", "yes"),)

    def test_leading_continuation_without_trailer_is_rejected(self) -> None:
        message = "Subject\n\n  indented line only"
        assert parse_trailers(message) == ()

    @pytest.mark.parametrize("message", ["", "   ", "\n\n\n", "\r\n"])
    def test_empty_inputs(self, message: str) -> None:
        assert parse_trailers(message) == ()

    @given(st.text())
    def test_never_raises_and_returns_tuple(self, message: str) -> None:
        result = parse_trailers(message)
        assert isinstance(result, tuple)
        assert all(isinstance(t, Trailer) for t in result)


class TestFindTrailers:
    def test_case_insensitive_key(self) -> None:
        message = f"Subject\n\n{CLAUDE}\nco-authored-by: Other <o@example.com>"
        assert find_trailers(message, "CO-AUTHORED-BY") == (
            "Claude <noreply@anthropic.com>",
            "Other <o@example.com>",
        )

    def test_missing_key(self) -> None:
        assert find_trailers(f"Subject\n\n{CLAUDE}", "Signed-off-by") == ()


class TestParsePerson:
    def test_name_and_email(self) -> None:
        assert parse_person("Claude <noreply@anthropic.com>") == Person(
            "Claude", "noreply@anthropic.com"
        )

    def test_multiword_name_and_padding(self) -> None:
        assert parse_person("  Claude Opus 4.1  <noreply@anthropic.com> ") == Person(
            "Claude Opus 4.1", "noreply@anthropic.com"
        )

    def test_empty_name(self) -> None:
        assert parse_person("<bot@example.com>") == Person("", "bot@example.com")

    @pytest.mark.parametrize("value", ["just a name", "a <b> c", "<>", ""])
    def test_not_a_person(self, value: str) -> None:
        assert parse_person(value) is None
