# Docker Deployment Guide

## 🐳 Quick Start

```bash
# 1. Copy environment file
cp .env.docker.example .env

# 2. Edit .env with your values (REQUIRED!)
nano .env  # or vim, code, etc.

# 3. Build and start services
docker-compose up -d

# 4. Check logs
docker-compose logs -f bot

# 5. Check health
docker-compose ps
```

## 📋 Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- 2GB RAM minimum
- 10GB disk space (for ML models)

## 🔧 Configuration

### Required Environment Variables

Edit `.env` and set these **required** values:

```bash
# Get your Discord bot token
DISCORD_TOKEN=your_bot_token_here

# Get your Discord server ID
DISCORD_GUILD_ID=123456789012345678

# Get your Discord user ID (for admin commands)
BOT_OWNER_ID=123456789012345678

# Set a strong database password
POSTGRES_PASSWORD=your_secure_password_here
```

### How to Get Discord IDs

1. **Enable Developer Mode** in Discord:
   - Settings → App Settings → Advanced → Developer Mode (ON)

2. **Get Bot Token**:
   - https://discord.com/developers/applications
   - Select your application → Bot → Reset Token

3. **Get Guild ID**:
   - Right-click your server icon → Copy Server ID

4. **Get User ID**:
   - Right-click your username → Copy User ID

## 🚀 Deployment Options

### Production Deployment

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Stop and remove volumes (DELETES DATA!)
docker-compose down -v
```

### Development Deployment

```bash
# Start with development overrides
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

# This enables:
# - DEBUG logging
# - Dry-run mode (safe testing)
# - Source code mounting
# - Exposed database ports
```

## 📊 Service Management

### Check Service Status

```bash
# View running services
docker-compose ps

# Check health
docker-compose ps
# Should show "healthy" for all services
```

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f bot
docker-compose logs -f postgres
docker-compose logs -f redis

# Last 100 lines
docker-compose logs --tail=100 bot
```

### Restart Services

```bash
# Restart bot only
docker-compose restart bot

# Restart all services
docker-compose restart

# Rebuild and restart bot
docker-compose up -d --build bot
```

## 🔍 Troubleshooting

### Bot won't start

```bash
# Check logs for errors
docker-compose logs bot

# Common issues:
# - Missing DISCORD_TOKEN
# - Missing BOT_OWNER_ID
# - Invalid Discord token
# - Database not ready
```

### Database connection errors

```bash
# Check if postgres is healthy
docker-compose ps postgres

# Check postgres logs
docker-compose logs postgres

# Verify connection from bot
docker-compose exec bot python -c "import asyncio; from usmca_bot.database.postgres import PostgresClient; print('ok')"
```

### Redis connection errors

```bash
# Check if redis is healthy
docker-compose ps redis

# Test redis connection
docker-compose exec redis redis-cli ping
# Should return: PONG
```

### ML model download issues

```bash
# Models download on first run (~1GB)
# Check bot logs for download progress
docker-compose logs -f bot

# If stuck, rebuild:
docker-compose build --no-cache bot
docker-compose up -d bot
```

### Out of memory errors

```bash
# Check resource usage
docker stats

# Increase memory in docker-compose.yml:
# deploy:
#   resources:
#     limits:
#       memory: 4G  # Increase this
```

## 🔐 Security Best Practices

### Production Checklist

- [ ] Set strong `POSTGRES_PASSWORD`
- [ ] Set `DRY_RUN_MODE=false` (after testing)
- [ ] Don't expose database ports (remove ports: section)
- [ ] Keep Discord token secret (never commit to git)
- [ ] Run as non-root user (default in Dockerfile)
- [ ] Enable automatic security updates on host
- [ ] Monitor logs for suspicious activity
- [ ] Backup database regularly

### Network Security

```bash
# By default, services are isolated in usmca-network
# Only bot has external access (to Discord)

# To further isolate (remove ports from docker-compose.yml):
# postgres:
#   # ports:  # <- Comment these out
#   #   - "5432:5432"
```

## 💾 Backup & Restore

### Backup Database

```bash
# Backup to file
docker-compose exec postgres pg_dump -U usmca usmca_bot > backup_$(date +%Y%m%d).sql

# Or use docker cp
docker-compose exec postgres pg_dump -U usmca usmca_bot | gzip > backup.sql.gz
```

### Restore Database

```bash
# From SQL file
cat backup.sql | docker-compose exec -T postgres psql -U usmca usmca_bot

# From compressed file
gunzip -c backup.sql.gz | docker-compose exec -T postgres psql -U usmca usmca_bot
```

### Backup Redis

```bash
# Redis uses AOF persistence by default
# Data is in redis_data volume

# Backup volume
docker run --rm -v usmca_redis_data:/data -v $(pwd):/backup alpine tar czf /backup/redis_backup.tar.gz /data
```

## 📈 Monitoring

### Health Checks

```bash
# All services have health checks
docker-compose ps

# Healthy output:
# NAME            STATUS          
# usmca-bot       Up (healthy)
# usmca-postgres  Up (healthy)
# usmca-redis     Up (healthy)
```

### Resource Usage

```bash
# Real-time stats
docker stats

# Disk usage
docker system df
docker volume ls
```

### Logs Rotation

```bash
# Configure log rotation in docker-compose.yml:
# services:
#   bot:
#     logging:
#       options:
#         max-size: "10m"
#         max-file: "3"
```

## 🔄 Updates

### Update Bot Code

```bash
# 1. Pull latest code
git pull

# 2. Rebuild and restart
docker-compose up -d --build bot

# 3. Check logs
docker-compose logs -f bot
```

### Update Dependencies

```bash
# Edit pyproject.toml with new dependencies

# Rebuild from scratch
docker-compose build --no-cache bot
docker-compose up -d bot
```

### Update Database Schema

```bash
# 1. Create migration SQL
# 2. Apply to running database
cat migration.sql | docker-compose exec -T postgres psql -U usmca usmca_bot

# OR restart with updated schema.sql
docker-compose down
docker-compose up -d
```

## 🧹 Cleanup

### Remove Stopped Containers

```bash
docker-compose down
```

### Remove Everything (INCLUDING DATA!)

```bash
# WARNING: This deletes all data!
docker-compose down -v

# Also remove images
docker-compose down -v --rmi all
```

### Prune Docker System

```bash
# Remove unused containers, networks, images
docker system prune -a

# Free up disk space
docker volume prune
```

## 📦 Resource Requirements

### Minimum (Testing)
- CPU: 1 core
- RAM: 1GB
- Disk: 5GB

### Recommended (Small Server)
- CPU: 2 cores
- RAM: 2GB
- Disk: 10GB

### Production (Medium Server)
- CPU: 4 cores
- RAM: 4GB
- Disk: 20GB

### Scaling (Large Server)
- CPU: 8+ cores
- RAM: 8GB+
- Disk: 50GB+

## 🎯 Next Steps

1. ✅ Copy and configure `.env`
2. ✅ Start services: `docker-compose up -d`
3. ✅ Check logs: `docker-compose logs -f`
4. ✅ Test bot in Discord
5. ✅ Monitor resource usage
6. ✅ Setup backups
7. ✅ Configure log rotation
8. ✅ Test failover scenarios

## 🆘 Getting Help

If you encounter issues:

1. Check logs: `docker-compose logs -f bot`
2. Check health: `docker-compose ps`
3. Check resources: `docker stats`
4. Check environment: `docker-compose config`
5. Restart services: `docker-compose restart`

## 📚 Additional Resources

- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [PostgreSQL Docker Hub](https://hub.docker.com/_/postgres)
- [Redis Docker Hub](https://hub.docker.com/_/redis)
- [Discord.py Documentation](https://discordpy.readthedocs.io/)