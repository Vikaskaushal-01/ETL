from langgraph.graph import StateGraph, START, END
from agents_graph.state import PipelineState
from agents_graph.nodes import (
    intake_node, transformation_node, 
    storage_node, report_node, pbi_refresh_node
)

# Initialize stateful graph
workflow = StateGraph(PipelineState)

# Register nodes
workflow.add_node("intake", intake_node)
workflow.add_node("transformation", transformation_node)
workflow.add_node("storage", storage_node)
workflow.add_node("report", report_node)
workflow.add_node("pbi_refresh", pbi_refresh_node)

# Set up edges flow sequentially
workflow.add_edge(START, "intake")
workflow.add_edge("intake", "transformation")
workflow.add_edge("transformation", "storage")
workflow.add_edge("storage", "report")
workflow.add_edge("report", "pbi_refresh")
workflow.add_edge("pbi_refresh", END)

# Compile the compiled application instance
compiled_graph = workflow.compile()
