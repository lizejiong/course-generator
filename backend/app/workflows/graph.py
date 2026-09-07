from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from app.workflows.chapter_cycle import build_chapter_cycle
from app.workflows.state import WorkflowState

Node = Callable[[WorkflowState], dict]


def build_main_graph(nodes: dict[str, Node]):
    """Seven observable stages in one flat graph; only chapter work is a subgraph."""
    required = {
        "requirements",
        "mission",
        "sources_blueprint",
        "batches",
        "chapter_context",
        "chapter_write",
        "chapter_precheck",
        "chapter_humanize",
        "chapter_semantic",
        "chapter_aggregate",
        "course_quality",
        "release",
    }
    missing = required - nodes.keys()
    if missing:
        raise ValueError(f"missing workflow nodes: {', '.join(sorted(missing))}")
    chapter = build_chapter_cycle(
        {
            "context_pack": nodes["chapter_context"],
            "write": nodes["chapter_write"],
            "precheck": nodes["chapter_precheck"],
            "humanize": nodes["chapter_humanize"],
            "semantic": nodes["chapter_semantic"],
            "aggregate": nodes["chapter_aggregate"],
        }
    )
    graph = StateGraph(WorkflowState)
    for name in (
        "requirements",
        "mission",
        "sources_blueprint",
        "batches",
        "course_quality",
        "release",
    ):
        graph.add_node(name, nodes[name])
    graph.add_node("chapter_cycle", chapter)
    graph.add_edge(START, "requirements")
    graph.add_edge("requirements", "mission")
    graph.add_edge("mission", "sources_blueprint")
    graph.add_edge("sources_blueprint", "batches")
    graph.add_edge("batches", "chapter_cycle")
    graph.add_edge("chapter_cycle", "course_quality")
    graph.add_edge("course_quality", "release")
    graph.add_edge("release", END)
    return graph.compile()
