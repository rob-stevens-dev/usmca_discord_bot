# USMCA Bot

AI-powered Discord auto-moderation system with behavioral analysis. Provides automated, context-aware moderation without manual oversight while maintaining complete audit trails.

## Features

- **Behavioral Moderation**: Focuses on *how* users interact, not *what* they say
- **ML-Powered Detection**: Uses toxicity detection and sentiment analysis
- **Brigade Detection**: Identifies and mitigates coordinated attacks
- **Graduated Enforcement**: Escalates from warnings → timeouts → kicks → bans
- **Full Audit Trail**: Complete logging for transparency and appeals
- **Standalone**: No external API dependencies, runs entirely on your infrastructure
- **Privacy-Focused**: All data stays local, no third-party services

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Discord Server                        │
└────────────────────┬────────────────────────────────────┘
                     │ Gateway API (WebSocket)
                     ▼
┌─────────────────────────────────────────────────────────┐
│                  Bot Core (discord.py)                   │
└────────┬──────────────────────────┬─────────────────────┘
         │                          │
         ▼                          ▼
┌──────────────────┐      ┌────────────────────────┐
│  Message Queue   │      │   Classification       │
│    (Redis)       │      │      Engine            │
└──────────────────┘      │  - Toxicity detection  │
                          │  - Sentiment analysis  │
                          └───────────┬────────────┘
                                      │
                          ┌───────────▼────────────┐
                          │   Behavior Analyzer    │
                          │  - User history        │
                          │  - Escalation tracking │
                          └───────────┬────────────┘
                                      │
                          ┌───────────▼────────────┐
                          │   Action Decision      │
                          └───────────┬────────────┘
                                      │
                          ┌───────────▼────────────┐
                          │   PostgreSQL           │
                          └────────────────────────┘
```

## Requirements

- Python 3.11+
- PostgreSQL 16+
- Redis 7+
- 16GB RAM (8GB for ML models, 4GB PostgreSQL, 4GB overhead)
- 4+ CPU cores
- 50GB SSD

## Installation

### Development Setup

```bash
# Clone repository
git clone https://github.com/yourusername/usmca_bot.git
cd usmca_bot

# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install with dev dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

### Database Setup

```bash
# PostgreSQL
createdb usmca_bot
psql usmca_bot < sql/schema.sql

# Redis (typically runs as service)
redis-server
```

### Configuration

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your settings
# Required:
# - DISCORD_TOKEN
# - POSTGRES_DSN
# - REDIS_URL
```

## Usage

```bash
# Run the bot
usmca-bot

# Run with custom config
usmca-bot --config config.yaml

# Run tests
pytest

# Run tests with coverage
pytest --cov=usmca_bot --cov-report=html

# Code quality checks
black src tests
ruff check src tests
mypy src
```

## Configuration

See `config.example.yaml` for full configuration options including:

- Toxicity thresholds
- Timeout durations
- Brigade detection parameters
- Logging levels
- Database connection pools

## Project Structure

```
usmca_bot/
├── src/
│   └── usmca_bot/
│       ├── __init__.py
│       ├── cli.py                 # Entry point
│       ├── bot.py                 # Main bot class
│       ├── config.py              # Configuration management
│       ├── classification/        # ML models
│       │   ├── __init__.py
│       │   ├── engine.py          # Classification engine
│       │   ├── models.py          # Model loaders
│       │   └── toxicity.py        # Toxicity detection
│       ├── behavior/              # Behavioral analysis
│       │   ├── __init__.py
│       │   ├── analyzer.py        # User behavior analysis
│       │   └── brigade.py         # Brigade detection
│       ├── actions/               # Moderation actions
│       │   ├── __init__.py
│       │   ├── decision.py        # Decision engine
│       │   └── executor.py        # Action executor
│       ├── database/              # Database layer
│       │   ├── __init__.py
│       │   ├── postgres.py        # PostgreSQL client
│       │   ├── redis.py           # Redis client
│       │   └── models.py          # Data models
│       └── utils/                 # Utilities
│           ├── __init__.py
│           ├── logging.py         # Structured logging
│           └── metrics.py         # Prometheus metrics
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # Test fixtures
│   ├── test_classification/
│   ├── test_behavior/
│   ├── test_actions/
│   └── test_database/
├── sql/
│   └── schema.sql                 # Database schema
├── pyproject.toml
├── README.md
└── .env.example
```

## Testing

Test coverage target: >95%

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_classification/test_engine.py

# Run with markers
pytest -m "not slow"

# Watch mode (requires pytest-watch)
ptw
```

## Deployment

See `docs/deployment.md` for production deployment guide including:

- Systemd service configuration
- Database tuning
- Resource allocation
- Monitoring setup

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

All code must:
- Pass `pytest` with >95% coverage
- Pass `black`, `ruff`, and `mypy` checks
- Include comprehensive docstrings
- Include unit tests

## License

MIT License - see [LICENSE](LICENSE) file for details

## Security

For security concerns, please email security@example.com

Do not open public issues for security vulnerabilities.