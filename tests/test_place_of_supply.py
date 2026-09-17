"""The carve-outs a state dropdown gets wrong.

Each test below is a case where "place of supply = the client's state" gives
the wrong tax split, and the wrongness is invisible on the finished document.
"""

import pytest

from quotation_studio.compute import compute
from quotation_studio.model import Document
from quotation_studio.place_of_supply import (
    NatureOfSupply as N,
)
from quotation_studio.place_of_supply import (
    PlaceOfSupplyError, PosRule, derive,
)

MH, KA, DL = "27", "29", "07"


def test_training_for_unregistered_client_follows_the_venue():
    """12(5): unregistered recipient -> where the training happens."""
    pos = derive(nature=N.TRAINING, supplier_state_code=MH,
                 client_state_code=MH, client_is_registered=False,
                 answers={"performance_state": KA})
    assert pos.state_code == KA
    assert pos.rule is PosRule.SERVICES_TRAINING


def test_training_for_registered_client_follows_the_client():
    """12(5): registered recipient -> the client's location, not the venue."""
    pos = derive(nature=N.TRAINING, supplier_state_code=MH,
                 client_state_code=MH, client_is_registered=True,
                 answers={"performance_state": KA})
    assert pos.state_code == MH


def test_the_training_carve_out_flips_the_whole_tax_split(base_doc):
    """Same supplier, same client, same venue -- the client's registration
    status alone decides IGST vs CGST+SGST. This is the case the dropdown
    silently gets wrong."""
    base_doc["client"]["state_code"] = MH
    base_doc["place_of_supply"] = {"nature": "training", "performance_state": KA}

    unregistered = compute(Document.from_dict(base_doc))
    assert unregistered.is_interstate
    assert unregistered.igst_total and not unregistered.cgst_total

    base_doc["client"]["gstin"] = "27AAPFU0939F1ZV"
    registered = compute(Document.from_dict(base_doc))
    assert not registered.is_interstate
    assert registered.cgst_total and not registered.igst_total

    # The total tax is the same; only its split and destination change.
    assert unregistered.tax_total == registered.tax_total


def test_immovable_property_follows_the_site():
    """12(3): a Delhi architect working on a Karnataka building."""
    pos = derive(nature=N.IMMOVABLE_PROPERTY, supplier_state_code=DL,
                 client_state_code=MH, client_is_registered=True,
                 answers={"property_state": KA})
    assert pos.state_code == KA
    assert pos.rule is PosRule.SERVICES_IMMOVABLE_PROPERTY


def test_health_service_follows_performance():
    """12(4): a clinic treats whoever walks in, wherever the patient lives."""
    pos = derive(nature=N.PERFORMANCE_BASED, supplier_state_code=KA,
                 client_state_code=MH, client_is_registered=False,
                 answers={"performance_state": KA})
    assert pos.state_code == KA


def test_event_admission_follows_the_venue_regardless_of_registration():
    for registered in (True, False):
        pos = derive(nature=N.EVENT_ADMISSION, supplier_state_code=MH,
                     client_state_code=MH, client_is_registered=registered,
                     answers={"event_state": DL})
        assert pos.state_code == DL


def test_general_service_follows_the_registered_client():
    pos = derive(nature=N.GENERAL_SERVICE, supplier_state_code=MH,
                 client_state_code=KA, client_is_registered=True)
    assert pos.state_code == KA
    assert pos.rule is PosRule.SERVICES_DEFAULT


def test_no_client_address_falls_back_to_the_supplier():
    """12(2)(b): no address on record -> the supplier's location."""
    pos = derive(nature=N.GENERAL_SERVICE, supplier_state_code=MH,
                 client_state_code=None, client_is_registered=False)
    assert pos.state_code == MH


def test_goods_follow_where_delivery_ends():
    pos = derive(nature=N.GOODS_SHIPPED, supplier_state_code=MH,
                 client_state_code=MH, client_is_registered=True,
                 answers={"delivery_state": KA})
    assert pos.state_code == KA
    assert pos.rule is PosRule.GOODS_MOVEMENT


def test_manual_declaration_is_recorded_as_the_users_own():
    pos = derive(nature=N.OTHER, supplier_state_code=MH,
                 client_state_code=KA, client_is_registered=True,
                 answers={"declared_state": DL})
    assert pos.is_user_declared
    assert "did not derive it" in pos.reasoning


def test_a_missing_follow_up_answer_asks_the_question():
    with pytest.raises(PlaceOfSupplyError) as exc:
        derive(nature=N.IMMOVABLE_PROPERTY, supplier_state_code=MH,
               client_state_code=KA, client_is_registered=True, answers={})
    assert exc.value.field == "place_of_supply.property_state"
    assert "in which state is the property" in str(exc.value).lower()


def test_an_invalid_state_code_is_refused():
    with pytest.raises(PlaceOfSupplyError, match="not a valid GST state code"):
        derive(nature=N.GOODS_SHIPPED, supplier_state_code=MH,
               client_state_code=KA, client_is_registered=True,
               answers={"delivery_state": "99"})


def test_every_nature_has_an_option_label_and_a_follow_up_entry():
    from quotation_studio.place_of_supply import FOLLOW_UP, NATURE_OPTIONS
    for nature in N:
        assert nature in NATURE_OPTIONS
        assert nature in FOLLOW_UP
