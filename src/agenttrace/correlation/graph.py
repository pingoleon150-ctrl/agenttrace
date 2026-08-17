from __future__ import annotations

import networkx as nx

from agenttrace.detectors.artifact_reuse import extract_artifacts
from agenttrace.models import Observation, Signal


def build_coordination_graph(observations: list[Observation]) -> nx.DiGraph:
    graph = nx.DiGraph()
    by_event_id = {o.source_event_id: o for o in observations}

    for obs in observations:
        actor_node = f"actor:{obs.actor}"
        event_node = f"event:{obs.source_event_id}"
        graph.add_node(actor_node, kind="actor", label=obs.actor)
        graph.add_node(event_node, kind="event", event_type=obs.event_type)
        graph.add_edge(actor_node, event_node, relation="authored", weight=1)

        if obs.repository:
            repo_node = f"repo:{obs.repository}"
            graph.add_node(repo_node, kind="repository", label=obs.repository)
            graph.add_edge(event_node, repo_node, relation="in_repository", weight=1)

        if obs.reply_to and obs.reply_to in by_event_id:
            parent = by_event_id[obs.reply_to]
            parent_event = f"event:{parent.source_event_id}"
            graph.add_edge(parent_event, event_node, relation="reply_to", weight=1)
            if parent.actor != obs.actor:
                _increment_edge(graph, f"actor:{parent.actor}", actor_node, "responded_to")

        for artifact in extract_artifacts(obs):
            artifact_node = f"artifact:{artifact.kind}:{artifact.value}"
            graph.add_node(artifact_node, kind="artifact", artifact_kind=artifact.kind)
            graph.add_edge(event_node, artifact_node, relation="contains", weight=1)

    # Add actor-to-actor edges for shared artifacts.
    artifact_actors: dict[str, set[str]] = {}
    for node, data in graph.nodes(data=True):
        if data.get("kind") != "artifact":
            continue
        actors = set()
        for event_node in graph.predecessors(node):
            for actor_node in graph.predecessors(event_node):
                if str(actor_node).startswith("actor:"):
                    actors.add(actor_node)
        artifact_actors[node] = actors

    for actors in artifact_actors.values():
        if len(actors) < 2:
            continue
        for left in actors:
            for right in actors:
                if left != right:
                    _increment_edge(graph, left, right, "shared_artifact")
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
    return [
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


def _increment_edge(graph: nx.DiGraph, u: str, v: str, relation: str) -> None:
    if graph.has_edge(u, v):
        graph[u][v]["weight"] = graph[u][v].get("weight", 1) + 1
        relations = set(graph[u][v].get("relations", []))
        relations.add(relation)
        graph[u][v]["relations"] = sorted(relations)
    else:
        graph.add_edge(u, v, relation=relation, relations=[relation], weight=1)
