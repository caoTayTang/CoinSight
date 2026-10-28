"""Dependency-light action schemas shared by serving and offline fine-tuning."""

from warehouse_agents.skills import names as skill_names

SCHEMAS = {
    'forecast_support': {
        'type': 'object',
        'properties': {
            'symbol': {'type': 'string', 'enum': ['BTC', 'ETH']},
            'performance_days': {'type': 'integer', 'minimum': 7, 'maximum': 365},
            'market_days': {'type': 'integer', 'minimum': 7, 'maximum': 365},
            'trend_hours': {'type': 'integer', 'minimum': 24, 'maximum': 1000},
            'cutoff': {'type': ['string', 'null']},
        },
        'additionalProperties': False,
    },
    'trade_decision': {
        'type': 'object',
        'properties': {
            'symbol': {'type': 'string', 'enum': ['BTC', 'ETH']},
            'portfolio_id': {
                'type': ['string', 'null'],
                'pattern': '^[0-9a-fA-F-]{36}$',
            },
            'performance_days': {'type': 'integer', 'minimum': 7, 'maximum': 365},
            'market_days': {'type': 'integer', 'minimum': 7, 'maximum': 365},
            'trend_hours': {'type': 'integer', 'minimum': 24, 'maximum': 1000},
            'cutoff': {'type': ['string', 'null']},
        },
        'required': ['symbol'],
        'additionalProperties': False,
    },
    'detect_market_anomaly': {
        'type': 'object',
        'properties': {
            'symbol': {'type': 'string', 'enum': ['BTC', 'ETH']},
            'cutoff': {'type': ['string', 'null']},
        },
        'required': ['symbol'],
        'additionalProperties': False,
    },
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
