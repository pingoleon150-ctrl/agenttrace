from __future__ import annotations

import networkx as nx

from agenttrace.detectors.artifact_reuse import extract_artifacts
from agenttrace.models import Observation, Signal
from agenttrace.util import sha256_text


def build_coordination_graph(observations: list[Observation]) -> nx.DiGraph:
    graph = nx.DiGraph()
    by_event_key = {o.event_key: o for o in observations}

    for obs in observations:
        actor_node = f"actor:{obs.actor_key or obs.actor}"
        event_node = f"event:{obs.event_key}"
        graph.add_node(actor_node, kind="actor", label=obs.actor)
        graph.add_node(
            event_node, kind="event", event_type=obs.event_type, event_time=obs.event_time.isoformat()
        )
        graph.add_edge(actor_node, event_node, relation="authored", weight=1)

        if obs.repository:
            repo_node = f"repo:{obs.repository}"
            graph.add_node(repo_node, kind="repository", label=obs.repository)
            graph.add_edge(event_node, repo_node, relation="in_repository", weight=1)

        if obs.parent_key and obs.parent_key in by_event_key:
            parent = by_event_key[obs.parent_key]
            parent_event = f"event:{parent.event_key}"
            graph.add_edge(parent_event, event_node, relation="reply_to", weight=1)
            parent_actor = f"actor:{parent.actor_key or parent.actor}"
            if parent_actor != actor_node:
                _increment_edge(graph, parent_actor, actor_node, "responded_to")

        for artifact in extract_artifacts(obs):
            artifact_node = f"artifact:{artifact.kind}:{sha256_text(artifact.value)}"
            graph.add_node(artifact_node, kind="artifact", artifact_kind=artifact.kind)
            graph.add_edge(event_node, artifact_node, relation="contains", weight=1)

    return graph


def detect_graph_motifs(graph: nx.DiGraph) -> list[Signal]:
    actors = [n for n, d in graph.nodes(data=True) if d.get("kind") == "actor"]
    if len(actors) < 2:
        return []

    actor_graph = nx.DiGraph()
    actor_graph.add_nodes_from(actors)
    for u, v, data in graph.edges(data=True):
        if u in actors and v in actors:
            actor_graph.add_edge(u, v, **data)

    if actor_graph.number_of_edges() == 0:
        return []

    reciprocal_edges = sum(1 for u, v in actor_graph.edges() if actor_graph.has_edge(v, u))
    reciprocity = reciprocal_edges / actor_graph.number_of_edges()
    max_out = max((actor_graph.out_degree(n) for n in actors), default=0)
    fanout = min(1.0, max_out / 4.0)
    strongly_connected = max(
        (len(c) for c in nx.strongly_connected_components(actor_graph)), default=1
    )
    scc_score = min(1.0, max(0, strongly_connected - 1) / 4.0)
    score = min(1.0, 0.45 * reciprocity + 0.35 * fanout + 0.20 * scc_score)
    if score < 0.25:
        return []
    signals = [
        Signal(
            family="graph",
            name="coordination_topology",
            score=score,
            evidence=[
                f"actor_count={len(actors)}",
                f"actor_edges={actor_graph.number_of_edges()}",
                f"reciprocity={reciprocity:.2f}",
                f"max_out_degree={max_out}",
                f"largest_scc={strongly_connected}",
            ],
        )
    ]
    leaders = []
    for actor in actors:
        workers = [
            target
            for target in actor_graph.successors(actor)
            if actor_graph[actor][target].get("weight", 1) >= 2
        ]
        if len(workers) >= 3:
            leaders.append((actor, workers))
    if leaders:
        leader, workers = max(leaders, key=lambda item: len(item[1]))
        response_count = sum(actor_graph[leader][worker].get("weight", 1) for worker in workers)
        signals.append(
            Signal(
                family="graph",
                name="repeated_leader_worker_aggregation",
                score=min(0.94, 0.68 + 0.04 * len(workers) + 0.015 * response_count),
                evidence=[
                    f"worker_count={len(workers)}",
                    f"repeated_response_count={response_count}",
                    "relationship_source=native_reply_edges",
                ],
                evidence_groups=["graph:leader_worker_replies"],
            )
        )
    return signals


def _increment_edge(graph: nx.DiGraph, u: str, v: str, relation: str) -> None:
    if graph.has_edge(u, v):
        graph[u][v]["weight"] = graph[u][v].get("weight", 1) + 1
        relations = set(graph[u][v].get("relations", []))
        relations.add(relation)
        graph[u][v]["relations"] = sorted(relations)
    else:
        graph.add_edge(u, v, relation=relation, relations=[relation], weight=1)
