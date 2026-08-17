def test_coach_parser_accepts_provider():
    from dota_coach.cli import build_parser

    args = build_parser().parse_args(["coach", "--account-id", "1", "--provider", "openai"])
    assert args.provider == "openai"


def test_coach_parser_provider_defaults_none():
    from dota_coach.cli import build_parser

    args = build_parser().parse_args(["coach", "--account-id", "1"])
    assert args.provider is None
