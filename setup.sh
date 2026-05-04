#!/bin/bash

# MEGACOM Automated Setup Script
# This script handles the initial setup for MEGACOM core.

echo "------------------------------------------------"
echo "        MEGACOM - Professional Setup            "
echo "------------------------------------------------"

# Check for Docker
if ! [ -x "$(command -v docker)" ]; then
  echo "Error: Docker is not installed. Please install Docker first." >&2
  exit 1
fi

if ! [ -x "$(command -v docker-compose)" ]; then
  echo "Error: docker-compose is not installed." >&2
  exit 1
fi

# Create .env if not exists
if [ ! -f .env ]; then
  echo "Creating .env file from example..."
  cp .env.example .env
  echo "Please edit the .env file with your specific settings later."
fi

# Build and Start
echo "Building and starting MEGACOM containers..."
docker-compose -f docker-compose.megacom.yml build
docker-compose -f docker-compose.megacom.yml up -d

echo "------------------------------------------------"
echo "MEGACOM is being deployed!"
echo "Wait a few seconds for the database to initialize."
echo "Access the app at: http://your-server-ip"
echo "------------------------------------------------"
