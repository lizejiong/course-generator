from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from app.workflows.state import WorkflowState

ChapterNode = Callable[[WorkflowState], dict]


def build_chapter_cycle(nodes: dict[str, ChapterNode]):
    """Build the only reusable subgraph; every node persists content outside state."""
    required = {"context_pack", "write", "precheck", "humanize", "semantic", "aggregate"}
    missing = required - nodes.keys()
    if missing:
        raise ValueError(f"missing chapter cycle nodes: {', '.join(sorted(missing))}")
    graph = StateGraph(WorkflowState)
    for name in required:
        graph.add_node(name, nodes[name])
    graph.add_edge(START, "context_pack")
    graph.add_edge("context_pack", "write")
    graph.add_edge("write", "precheck")

    def after_precheck(state: WorkflowState) -> str:
        return "humanize" if state.get("last_error_code") is None else "write"

    def after_aggregate(state: WorkflowState) -> str:
        return "write" if state.get("last_error_code") == "quality_rework" else END

    graph.add_conditional_edges(
        "precheck", after_precheck, {"humanize": "humanize", "write": "write"}
    )
    graph.add_edge("humanize", "semantic")
    graph.add_edge("semantic", "aggregate")
    graph.add_conditional_edges("aggregate", after_aggregate, {"write": "write", END: END})
    return graph.compile()
