from app.routes.query_analysis_routes import query_analysis_ns

from .query_tree_api import qf_saved_query_ns, qf_tree_ns

NAMESPACES = [
    (qf_tree_ns, ("query-tree",)),
    (qf_saved_query_ns, ("saved-queries",)),
    (query_analysis_ns, ("queries",)),
]
