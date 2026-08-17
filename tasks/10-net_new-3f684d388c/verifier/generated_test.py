import importlib


def test_generated_net_new_behavior():
    module = importlib.import_module('glom.matching')
    implementation = getattr(module, '__benchmark_new_behavior')

    assert implementation('benchmark-value') == 'benchmark-value'
    assert implementation({'benchmark': 'value'}) == {'benchmark': 'value'}
