from project_mimic.vision.grounding import BBox, DOMNode, UIEntity, ground_entities_to_dom


def test_grounding_prefers_best_overlap_and_semantics() -> None:
    entity = UIEntity(
        entity_id="e1",
        label="Search Flights",
        role="button",
        text="Search",
        bbox=BBox(95, 95, 120, 40),
        confidence=0.92,
    )

    dom_nodes = [
        DOMNode(
            dom_node_id="n1",
            role="button",
            text="Search Flights",
            bbox=BBox(100, 100, 120, 40),
            visible=True,
            enabled=True,
            z_index=10,
        ),
        DOMNode(
            dom_node_id="n2",
            role="link",
            text="Deals",
            bbox=BBox(300, 200, 60, 20),
            visible=True,
            enabled=True,
            z_index=15,
        ),
    ]

    result = ground_entities_to_dom([entity], dom_nodes, top_k=2)
    assert result["e1"]
    assert result["e1"][0].dom_node_id == "n1"


def test_grounding_filters_non_interactable_nodes() -> None:
    entity = UIEntity(
        entity_id="e2",
        label="Submit",
        role="button",
        text="Submit",
        bbox=BBox(10, 10, 100, 35),
        confidence=0.8,
    )

    dom_nodes = [
        DOMNode(
            dom_node_id="hidden",
            role="button",
            text="Submit",
            bbox=BBox(10, 10, 100, 35),
            visible=False,
            enabled=True,
            z_index=5,
        ),
        DOMNode(
            dom_node_id="disabled",
            role="button",
            text="Submit",
            bbox=BBox(10, 10, 100, 35),
            visible=True,
            enabled=False,
            z_index=8,
        ),
    ]

    result = ground_entities_to_dom([entity], dom_nodes, top_k=3)
    assert result["e2"] == []


def test_grounding_respects_top_k_limit() -> None:
    entity = UIEntity(
        entity_id="e3",
        label="Airport",
        role="textbox",
        text="From",
        bbox=BBox(45, 45, 160, 36),
        confidence=0.95,
    )

    dom_nodes = [
        DOMNode(
            dom_node_id=f"n{i}",
            role="textbox",
            text="From Airport",
            bbox=BBox(50 + i, 50 + i, 160, 36),
            visible=True,
            enabled=True,
            z_index=i,
        )
        for i in range(5)
    ]

    result = ground_entities_to_dom([entity], dom_nodes, top_k=2)
    assert len(result["e3"]) == 2
