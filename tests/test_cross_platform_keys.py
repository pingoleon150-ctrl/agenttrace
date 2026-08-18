from datetime import UTC, datetime

from agenttrace.correlation.cluster import cluster_observations
from agenttrace.models import Observation, Provenance
from agenttrace.storage.sqlite import SQLiteStore


def make_observation(
    *,
    source: str,
    source_event_id: str,
    actor: str = "alice",
    repository: str | None = None,
    thread_id: str | None = None,
    text: str | None = None,
    platform: str | None = None,
) -> Observation:
    now = datetime.now(UTC)
    return Observation(
        source=source,
        source_event_id=source_event_id,
        observed_at=now,
        event_time=now,
        actor=actor,
        platform=platform,
        event_type="post",
        text=text,
        repository=repository,
        thread_id=thread_id,
        provenance=Provenance(url=f"https://example.test/{source}/{source_event_id}"),
    )


def test_same_username_on_different_platforms_has_distinct_actor_keys():
    github = make_observation(source="github-thread-search", source_event_id="1")
    reddit = make_observation(source="reddit", source_event_id="1")

    assert github.actor_key == "github:actor:alice"
    assert reddit.actor_key == "reddit:actor:alice"
    assert github.actor_key != reddit.actor_key


def test_same_raw_event_id_on_different_sources_has_distinct_event_keys():
    github = make_observation(source="github-thread-search", source_event_id="shared-42")
    reddit = make_observation(source="reddit", source_event_id="shared-42")

    assert github.event_key
    assert reddit.event_key
    assert github.event_key != reddit.event_key


def test_storage_preserves_same_source_event_id_from_distinct_platforms(tmp_path):
    github = make_observation(
        source="canonical-import", source_event_id="shared-42", platform="github"
    )
    reddit = make_observation(
        source="canonical-import", source_event_id="shared-42", platform="reddit"
    )

    with SQLiteStore(tmp_path / "cross-platform.db") as store:
        store.upsert_observations_batch([github, reddit])
        restored = store.list_observations()

    assert len(restored) == 2
    assert {observation.event_key for observation in restored} == {
        github.event_key,
        reddit.event_key,
    }


def test_unscoped_observations_remain_in_separate_clusters():
    first = make_observation(source="public-forum", source_event_id="event-a")
    second = make_observation(source="public-forum", source_event_id="event-b")

    clusters = cluster_observations([first, second])

    assert len(clusters) == 2
    assert {tuple(item.source_event_id for item in cluster) for cluster in clusters.values()} == {
        ("event-a",),
        ("event-b",),
    }


def test_github_and_gharchive_share_namespaced_conversation_key():
    github = make_observation(
        source="github-thread-search",
        source_event_id="issue:100",
        repository="OpenAI/Codex",
        thread_id="42",
    )
    archive = make_observation(
        source="gharchive",
        source_event_id="archive:100",
        repository="openai/codex",
        thread_id="42",
    )

    assert github.resource_key == "github:repository:openai/codex"
    assert github.resource_key == archive.resource_key
    assert github.conversation_key == "github:repository:openai/codex:thread:42"
    assert github.conversation_key == archive.conversation_key


def test_typed_artifact_can_link_cross_platform_candidate_buckets():
    github = make_observation(
        source="github-thread-search",
        source_event_id="issue:7",
        actor="coordinator",
        repository="example/repo",
        thread_id="7",
        text="Delegate task_id=rare-9217",
    )
    forum = make_observation(
        source="public-forum",
        source_event_id="post:9",
        actor="worker",
        text="Result: task_id=rare-9217",
    )

    clusters = cluster_observations([github, forum])

    assert len(clusters) == 1
    assert {obs.platform for obs in next(iter(clusters.values()))} == {
        "github",
        "public-forum",
    }


def test_legacy_campaign_observation_recovers_origin_platform():
    observation = make_observation(source="campaign", source_event_id="old:1")
    payload = observation.model_dump()
    payload["platform"] = None
    payload["actor_key"] = None
    payload["event_key"] = None
    payload["metadata"] = {
        "origin_source": "github-thread-search",
        "campaign_source": "github-thread",
    }

    restored = Observation.model_validate(payload)

    assert restored.platform == "github"
    assert restored.actor_key == "github:actor:alice"
