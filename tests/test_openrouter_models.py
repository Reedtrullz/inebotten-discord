from __future__ import annotations

import json

import pytest

from utils.openrouter_models import OpenRouterModel, parse_openrouter_models


def test_parse_openrouter_models_sorts_deduplicates_and_labels_choices():
    payload = json.dumps({
        "data": [
            {"id": "zeta/model", "name": "Zeta"},
            {"id": "alpha/model"},
            {"id": "alpha/model", "name": "Alpha duplicate"},
            {"id": "", "name": "Missing ID"},
            "invalid",
        ],
    })

    models = parse_openrouter_models(payload.encode("utf-8"))

    assert models == (
        OpenRouterModel(id="alpha/model", name="Alpha duplicate"),
        OpenRouterModel(id="zeta/model", name="Zeta"),
    )
    assert models[0].choice == "Alpha duplicate (alpha/model)"


def test_parse_openrouter_models_classifies_free_models_from_pricing_or_id():
    payload = json.dumps({
        "data": [
            {"id": "zero/priced", "pricing": {"prompt": "0", "completion": "0.000"}},
            {"id": "paid/model", "pricing": {"prompt": "0.001", "completion": "0"}},
            {"id": "suffix/model:free"},
            {"id": "missing/pricing"},
        ],
    })

    models = {model.id: model for model in parse_openrouter_models(payload)}

    assert models["zero/priced"].is_free is True
    assert models["paid/model"].is_free is False
    assert models["suffix/model:free"].is_free is True
    assert models["missing/pricing"].is_free is False


@pytest.mark.parametrize("payload", [
    "{}",
    '{"data": []}',
    '{"data": [null, {}, {"id": "  "}]}',
])
def test_parse_openrouter_models_rejects_invalid_catalogs(payload):
    with pytest.raises(ValueError):
        parse_openrouter_models(payload)
