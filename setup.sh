#!/bin/bash

# MEGACOM Automated Setup Script
# This script handles the initial setup for MEGACOM core.

echo "------------------------------------------------"
echo "        MEGACOM - Professional Setup            "
echo "------------------------------------------------"

# Check for Docker
if ! command -v docker &> /dev/null; then
  echo "Error: Docker is not installed. Please install Docker first." >&2
  exit 1
fi

# Check for Docker Compose (plugin or legacy)
if docker compose version &> /dev/null; then
  DOCKER_COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
  DOCKER_COMPOSE_CMD="docker-compose"
else
  echo "Error: Docker Compose is not installed (neither 'docker compose' nor 'docker-compose' found)." >&2
  exit 1
fi

echo "Using: $DOCKER_COMPOSE_CMD"

# Create .env if not exists
if [ ! -f .env ]; then
  echo "Creating .env file from example..."
  cp .env.example .env
  echo "Please edit the .env file with your specific settings later."
fi

# Build and Start
echo "Building and starting MEGACOM containers..."
$DOCKER_COMPOSE_CMD -f docker-compose.megacom.yml build
$DOCKER_COMPOSE_CMD -f docker-compose.megacom.yml up -d

echo "------------------------------------------------"
echo "MEGACOM is being deployed!"
echo "Wait a few seconds for the database to initialize."
echo "Access the app at: http://your-server-ip"
echo "------------------------------------------------"
