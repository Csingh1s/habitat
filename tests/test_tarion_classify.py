from tarion_agent.classify import classify


def test_exterior_item():
    assert classify("Eavestrough is loose at the rear and downspout is detached.").area == "exterior"


def test_interior_item():
    assert classify("Cracked drywall on bedroom ceiling near closet.").area == "interior"


def test_ambiguous_needs_review():
    assert classify("Window does not operate smoothly.").area == "needs_review"


def test_section_heading_breaks_tie():
    assert classify("Damage noted.", section="Roof").area == "exterior"
