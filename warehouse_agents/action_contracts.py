"""Dependency-light action schemas shared by serving and offline fine-tuning."""

from warehouse_agents.skills import names as skill_names

SCHEMAS = {
    'service_health': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    'model_health': {
        'type': 'object',
        'properties': {'cutoff': {'type': ['string', 'null']}},
        'additionalProperties': False,
    },
    'warehouse_coverage': {
        'type': 'object',
        'properties': {
            'symbol': {'type': 'string', 'enum': ['BTC', 'ETH', 'SOL']},
            'hours': {'type': 'integer', 'minimum': 1, 'maximum': 168},
        },
        'additionalProperties': False,
    },
    'load_skill': {
        'type': 'object',
        'properties': {'name': {'type': 'string', 'enum': skill_names()}},
        'required': ['name'],
        'additionalProperties': False,
    },
}
