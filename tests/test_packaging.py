from pathlib import Path

from agenttrace.campaign import load_queries
from agenttrace.cli import DEFAULT_QUERIES_PATH, build_parser


def test_packaged_seed_queries_are_the_cli_default():
    args = build_parser().parse_args(["campaign"])
    repository_copy = Path(__file__).parents[1] / "queries" / "seed_queries.yaml"

    assert Path(args.queries) == DEFAULT_QUERIES_PATH
    assert len(load_queries(args.queries)) >= 10
    assert DEFAULT_QUERIES_PATH.read_bytes() == repository_copy.read_bytes()
