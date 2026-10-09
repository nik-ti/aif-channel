"""The LangGraph state machine: which station runs after which, and where an item
can go next. The work of each station is in pipeline/stations.py.

Each item is labelled (kind and company), judged, and then held if its company has had
its posts for the day; those wait for the evening digest (nodes/company_digest.py).
The story stations from Market One are wired in only when config.STORIES is on.

State is a plain dict rather than a database row, so it stays serialisable and a
checkpointer can be added later.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

import config
from pipeline import stations as s


class BrainState(TypedDict, total=False):
    """Everything the graph knows about the item it is processing.

    total=False means a node only returns the fields it changes. An empty
    `outcome` means "still moving down the line".
    """
    item: dict                  # after the gate approves, the FOLDED story source
    dry_run: bool               # rehearsal: decide everything, write and send nothing
    place_only: bool            # file into a story, but stop before the gate
    forced: bool                # a human overrode a rejection: the sorter and the
                                # gate step aside, the writer and the editor do not
    released: bool              # out of the reserve: already sorted and once held
                                # back by a daily limit; dedup and the sorter step aside
    sweep: bool                 # a roundup: the item was judged once already,
                                # skip straight to its story and the gate
    digest: bool                # a company digest: item is several waiting items
                                # folded together; straight to the writer
    digest_item_ids: list       # the items the digest covers

    # The live Story object, rebuilt from the database by story_organizer. It MUST
    # be declared here: LangGraph silently drops any state key the schema does
    # not name, and an undeclared story reaches the gate as a KeyError.
    story: Any
    story_id: int               # 0 in a dry run
    story_angle: str            # the gate's instruction for this post
    story_brief: str            # what the writer is told beyond the source
    gate_reason: str            # why a held item was held
    trigger_item_id: int        # the item that arrived, kept for logging

    sorter_verdict: dict
    post_html: str
    used_ai: bool
    post_id: int
    editor_verdict: dict
    editor_feedback: str
    previous_editor_reason: str  # the editor's own rejection, shown to it on the rewrite
    rewrite_count: int
    outcome: str                # published | duplicate | roundup | irrelevant |
                                # low_impact | waiting_digest | held | placed |
                                # declined | retry | failed


def build_graph():
    """Wire the stations together and compile the graph."""
    g = StateGraph(BrainState)
    stations = [
        ("dedup", s.dedup_node),
        ("fetch_article", s.fetch_article_node),   # before the labels: feeds give thin snippets
        ("labeler", s.labeler_node),
        ("sorter", s.sorter_node),
    ]
    if config.STORIES:
        stations += [("story_organizer", s.story_organizer_node), ("gatekeeper", s.gatekeeper_node)]
    else:
        stations += [("company_limit", s.company_limit_node)]
    stations += [
        ("writer", s.writer_node),
        ("editor", s.editor_node),
        ("repeat_check", s.repeat_check_node),
        ("image_analyst", s.image_analyst_node),
        ("video_analyst", s.video_analyst_node),
        ("publish", s.publish_node),
    ]
    for name, node in stations:
        g.add_node(name, node)

    g.add_edge(START, "dedup")
    g.add_conditional_edges("dedup", s.route_after_dedup, {"repeat": END, "new": "fetch_article"})
    g.add_conditional_edges("fetch_article", s.route_after_fetch_article, {"page too old": END, "read": "labeler"})
    g.add_conditional_edges("labeler", s.route_after_labeler, {"roundup": END, "labelled": "sorter"})
    if config.STORIES:
        g.add_conditional_edges("sorter", s.route_after_sorter, {"worth it": "story_organizer", "below the bar": END})
        g.add_conditional_edges("story_organizer", s.route_after_story_organizer,
                                {"gate": "gatekeeper", "end": END})
        g.add_conditional_edges("gatekeeper", s.route_after_gatekeeper, {"write": "writer", "end": END})
    else:
        g.add_conditional_edges("sorter", s.route_after_sorter, {"worth it": "company_limit", "below the bar": END})
        g.add_conditional_edges("company_limit", s.route_after_company_limit,
                                {"under the limit": "writer", "waits for digest": END})
    g.add_conditional_edges("writer", s.route_after_writer, {"draft": "editor", "failed": END})
    g.add_conditional_edges("editor", s.route_after_editor,
                            {"approved": "repeat_check", "fixable": "writer", "rejected": END})
    g.add_conditional_edges("repeat_check", s.route_after_repeat_check,
                            {"new to reader": "image_analyst", "already told": END})
    g.add_edge("image_analyst", "video_analyst")
    g.add_edge("video_analyst", "publish")
    g.add_edge("publish", END)
    return g.compile()


# Compiling is wiring, not work, so doing it at import time is fine.
graph = build_graph()


def diagram() -> str:
    """The graph as LangGraph draws it (Mermaid, top to bottom), for the dashboard."""
    return graph.get_graph().draw_mermaid()


async def run_item(item_row, *, dry_run: bool = False,
                   place_only: bool = False, sweep: bool = False,
                   forced: bool = False, released: bool = False, digest: bool = False,
                   digest_item_ids: list | None = None, brief: str = "") -> dict[str, Any]:
    """Run one queued item through the editorial graph.

    dry_run makes every decision for real but writes nothing and sends nothing.
    place_only files the item into its story and stops there, for rounds where
    the pacing limits mean nothing can go out anyway. sweep re-enters with a
    held item to release a roundup: it was judged once already, so dedup and
    the sorter step aside and placement resumes its story.

    forced is a human disagreeing with a rejection from the dashboard. It skips
    the two stations that judge whether an item is worth posting, and keeps the
    two that judge whether the post is any good. Placement still runs, because
    the story needs to know this went out — otherwise the next item on the same
    story has no idea it was already covered.
    digest is a company digest from nodes/company_digest.py: the item is several waiting
    items folded together, and brief tells the writer to give each one a line.
    Returns the final state; state["outcome"] is the one-word result.
    """
    initial: BrainState = {
        "item": dict(item_row),
        "dry_run": dry_run,
        "place_only": place_only,
        "sweep": sweep,
        "forced": forced,
        "released": released,
        "digest": digest,
        "digest_item_ids": digest_item_ids or [],
        "story_brief": brief,
        "rewrite_count": 0,
        "editor_feedback": "",
        "outcome": "",
    }
    return await graph.ainvoke(initial)
