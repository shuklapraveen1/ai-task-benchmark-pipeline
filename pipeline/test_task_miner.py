import json

from pipeline.task_miner import (
    TaskMiner,
    TaskMinerConfig,
    load_repo_graph,
    mine_excision_candidates,
)


def function(
    function_id,
    module_id,
    name,
    *,
    public=True,
    coverage=95.0,
    complexity=7,
    file_path=None,
):
    return {
        "id": function_id,
        "kind": "function",
        "name": name,
        "module_id": module_id,
        "public": public,
        "coverage_percent": coverage,
        "complexity": complexity,
        "file_path": file_path or (
            module_id.replace(".", "/") + ".py"
        ),
        "line_start": 10,
        "line_end": 25,
    }


def call(
    source,
    target,
    *,
    target_name=None,
):
    edge = {
        "kind": "call",
        "source": source,
        "target": target,
    }

    if target_name is not None:
        edge["target_name"] = target_name

    return edge


def graph(
    symbols,
    relationships,
):
    return {
        "project": {
            "name": "synthetic",
        },
        "modules": [],
        "symbols": symbols,
        "relationships": relationships,
    }


def test_public_function_with_internal_callers_scores_highly():
    target = "function:pkg.logic.transform"

    caller1 = "function:pkg.api.handle"
    caller2 = "function:pkg.worker.process"

    data = graph(
        [
            function(
                target,
                "module:pkg.logic",
                "transform",
                public=True,
                coverage=98.0,
            ),
            function(
                caller1,
                "module:pkg.api",
                "handle",
                public=True,
                coverage=90.0,
            ),
            function(
                caller2,
                "module:pkg.worker",
                "process",
                public=False,
                coverage=90.0,
            ),
        ],
        [
            call(caller1, target),
            call(caller2, target),
        ],
    )

    candidates = mine_excision_candidates(data)

    assert candidates

    candidate = candidates[0]

    assert candidate.function_id == target
    assert candidate.public is True
    assert candidate.caller_count == 2
    assert candidate.coverage_percent == 98.0
    assert candidate.score > 70.0


def test_private_function_can_be_candidate_but_gets_no_public_bonus():
    target = "function:pkg.logic._helper"

    data = graph(
        [
            function(
                target,
                "module:pkg.logic",
                "_helper",
                public=False,
                coverage=100.0,
            ),
        ],
        [],
    )

    candidates = mine_excision_candidates(data)

    assert len(candidates) == 1

    candidate = candidates[0]

    assert candidate.public is False
    assert candidate.public_api_bonus == 0.0


def test_filesystem_side_effects_are_penalized():
    pure = "function:pkg.logic.pure"
    impure = "function:pkg.logic.write_file"

    caller = "function:pkg.api.handle"

    data = graph(
        [
            function(
                pure,
                "module:pkg.logic",
                "pure",
                public=True,
                coverage=100.0,
            ),
            function(
                impure,
                "module:pkg.logic",
                "write_file",
                public=True,
                coverage=100.0,
            ),
            function(
                caller,
                "module:pkg.api",
                "handle",
            ),
        ],
        [
            call(caller, pure),
            call(
                caller,
                impure,
                target_name="open",
            ),
            call(
                impure,
                "external:os.remove",
                target_name="os.remove",
            ),
        ],
    )

    candidates = mine_excision_candidates(data)

    by_id = {
        candidate.function_id: candidate
        for candidate in candidates
    }

    assert pure in by_id
    assert impure in by_id

    assert (
        by_id[impure].side_effect_penalty > 0
    )

    assert (
        by_id[impure].score
        < by_id[pure].score
    )


def test_subprocess_and_requests_are_penalized():
    target = "function:pkg.api.fetch"

    data = graph(
        [
            function(
                target,
                "module:pkg.api",
                "fetch",
                public=True,
                coverage=100.0,
            ),
        ],
        [
            call(
                target,
                "external:requests.get",
                target_name="requests.get",
            ),
            call(
                target,
                "external:subprocess.run",
                target_name="subprocess.run",
            ),
        ],
    )
    from pipeline.task_miner import TaskMinerConfig

    candidates = mine_excision_candidates(data,config=TaskMinerConfig(minimum_score=-100.0))
    

    assert len(candidates) == 1

    candidate = candidates[0]

    assert candidate.side_effect_penalty == 70.0
    assert "requests.get" in (
        candidate.side_effect_signals
    )
    assert "subprocess.run" in (
        candidate.side_effect_signals
    )


def test_low_coverage_functions_are_filtered():
    target = "function:pkg.logic.uncovered"

    data = graph(
        [
            function(
                target,
                "module:pkg.logic",
                "uncovered",
                public=True,
                coverage=20.0,
            ),
        ],
        [],
    )

    candidates = mine_excision_candidates(data)

    assert candidates == []


def test_candidates_are_ranked_deterministically():
    first = "function:pkg.a.alpha"
    second = "function:pkg.b.beta"

    data = graph(
        [
            function(
                second,
                "module:pkg.b",
                "beta",
                coverage=90.0,
            ),
            function(
                first,
                "module:pkg.a",
                "alpha",
                coverage=90.0,
            ),
        ],
        [],
    )

    first_run = mine_excision_candidates(data)
    second_run = mine_excision_candidates(data)

    assert first_run == second_run

    assert [
        candidate.function_id
        for candidate in first_run
    ] == [
        "function:pkg.a.alpha",
        "function:pkg.b.beta",
    ]


def test_tie_breaking_does_not_depend_on_graph_order():
    first = "function:pkg.a.alpha"
    second = "function:pkg.b.beta"

    data_a = graph(
        [
            function(
                first,
                "module:pkg.a",
                "alpha",
            ),
            function(
                second,
                "module:pkg.b",
                "beta",
            ),
        ],
        [],
    )

    data_b = graph(
        [
            function(
                second,
                "module:pkg.b",
                "beta",
            ),
            function(
                first,
                "module:pkg.a",
                "alpha",
            ),
        ],
        [],
    )

    result_a = mine_excision_candidates(data_a)
    result_b = mine_excision_candidates(data_b)

    assert result_a == result_b


def test_miner_does_not_modify_graph():
    data = graph(
        [
            function(
                "function:pkg.logic.foo",
                "module:pkg.logic",
                "foo",
            )
        ],
        [],
    )

    before = json.dumps(
        data,
        sort_keys=True,
    )

    mine_excision_candidates(data)

    after = json.dumps(
        data,
        sort_keys=True,
    )

    assert before == after


def test_graph_can_be_loaded_from_repo_graph_json(tmp_path):
    path = tmp_path / "repo_graph.json"

    data = graph(
        [
            function(
                "function:pkg.logic.foo",
                "module:pkg.logic",
                "foo",
                coverage=100.0,
            )
        ],
        [],
    )

    path.write_text(
        json.dumps(data),
        encoding="utf-8",
    )

    loaded = load_repo_graph(path)

    candidates = mine_excision_candidates(
        loaded
    )

    assert len(candidates) == 1
    assert candidates[0].function_id == (
        "function:pkg.logic.foo"
    )


def test_json_file_mining_is_deterministic(tmp_path):
    path = tmp_path / "repo_graph.json"

    data = graph(
        [
            function(
                "function:pkg.z.zeta",
                "module:pkg.z",
                "zeta",
                coverage=95.0,
            ),
            function(
                "function:pkg.a.alpha",
                "module:pkg.a",
                "alpha",
                coverage=95.0,
            ),
        ],
        [],
    )

    path.write_text(
        json.dumps(data),
        encoding="utf-8",
    )

    first = [
        candidate.to_dict()
        for candidate in mine_excision_candidates(
            load_repo_graph(path)
        )
    ]

    second = [
        candidate.to_dict()
        for candidate in mine_excision_candidates(
            load_repo_graph(path)
        )
    ]

    assert first == second


def test_custom_side_effect_policy_is_supported():
    target = "function:pkg.logic.special"

    data = graph(
        [
            function(
                target,
                "module:pkg.logic",
                "special",
                coverage=100.0,
            )
        ],
        [
            call(
                target,
                "external:custom.io",
                target_name="custom.io",
            )
        ],
    )

    config = TaskMinerConfig(
        side_effect_modules=frozenset(
            {"custom.io"}
        ),
        side_effect_names=frozenset(),
    )

    candidates = TaskMiner(
        config=config
    ).mine_excision_candidates(data)

    assert len(candidates) == 1

    assert candidates[0].side_effect_penalty > 0

def test_real_okf_node_schema_is_accepted():
    graph = {
        "nodes": [
            {
                "id": "module:pkg.core",
                "type": "module",
                "module_name": "pkg.core",
                "path": "pkg/core.py",
            },
            {
                "id": "function:pkg.core.calculate",
                "type": "symbol",
                "kind": "function",
                "module_id": "module:pkg.core",
                "name": "calculate",
                "qualified_name": "pkg.core.calculate",
                "visibility": "public",
                "line_start": 1,
                "line_end": 5,
            },
            {
                "id": "function:pkg.core.wrapper",
                "type": "symbol",
                "kind": "function",
                "module_id": "module:pkg.core",
                "name": "wrapper",
                "qualified_name": "pkg.core.wrapper",
                "visibility": "public",
                "line_start": 7,
                "line_end": 11,
            },
        ],
        "edges": [
            {
                "type": "call",
                "source": "function:pkg.core.wrapper",
                "target": "function:pkg.core.calculate",
                "resolved": True,
                "confidence": "high",
                "line": 9,
            }
        ],
    }

    candidates = mine_excision_candidates(graph)

    assert candidates
    assert candidates[0].function_id == "function:pkg.core.calculate"