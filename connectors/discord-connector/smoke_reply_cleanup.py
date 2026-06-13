from reply_cleanup import reply_prefix_candidates, strip_obvious_reply_prefix


def _assert_eq(actual, expected):
    if actual != expected:
        raise AssertionError(f"expected {expected!r}, got {actual!r}")


def main() -> int:
    names = reply_prefix_candidates('Vivian "Brightwire" Kastali', "Vivian")
    assert 'Vivian "Brightwire" Kastali' in names
    assert "Vivian" in names

    _assert_eq(
        strip_obvious_reply_prefix(
            'Vivian "Brightwire" Kastali: I can see the image now.',
            names,
        ),
        "I can see the image now.",
    )
    _assert_eq(
        strip_obvious_reply_prefix("Vivian, I can see the image now.", names),
        "I can see the image now.",
    )
    _assert_eq(
        strip_obvious_reply_prefix("Vivian should probably see this.", names),
        "Vivian should probably see this.",
    )
    _assert_eq(
        strip_obvious_reply_prefix("  Vivian: spaced reply", names),
        "  spaced reply",
    )
    print("smoke_reply_cleanup ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
