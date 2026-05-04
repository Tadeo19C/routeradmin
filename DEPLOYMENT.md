# MEGACOM Deployment Guide

This guide describes how to deploy MEGACOM for your clients using Docker. This ensures a consistent environment and easy installation.

## Prerequisites
- Docker and Docker Compose installed on the host machine.
- 1GB RAM minimum.

## Installation via MEGACOM Setup Script (Recommended for Clients)

We have provided an automated script to handle the containerized installation:

1.  **Prepare the host**: Ensure Docker and Docker Compose are installed.
2.  **Download the package**: Extract the MEGACOM files into a folder.
3.  **Run the setup**:
    ```bash
    chmod +x setup.sh
    ./setup.sh
    ```
4.  **Initial Configuration**:
    - The script will build the MEGACOM branded images and start the services.
    - Open your browser at `http://your-server-ip`.

## Manual Installation (Docker)

If you prefer to run it manually, use the following command:
```bash
docker-compose -f docker-compose.megacom.yml up -d --build
```

4.  **Initial Setup**:
    - Access the application at `http://your-server-ip:8000`.
    - Create the first administrator user as prompted.

## Updating MEGACOM

To update to the latest version:
```bash
docker-compose down
git pull
docker-compose up -d --build
```

## Security Recommendations
- Always use a strong password for the admin account.
- If exposing to the internet, we recommend using a Reverse Proxy with HTTPS (like Nginx or Traefik).
- Use SSH Keys instead of passwords for Mikrotik/Cisco devices whenever possible.
