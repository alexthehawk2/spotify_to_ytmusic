# Azure Deployment

This app is set up to deploy as a single container:

- FastAPI serves the API under `/api`
- FastAPI also serves the built frontend from the same origin
- Playwright Chromium runs inside the container for Spotify extraction

## Recommended Azure Target

Use Azure Container Apps on the Consumption plan for a low-cost personal deployment. It is a better fit for this containerized app than running two separate free-tier services.

## Required Azure Configuration

Set these environment variables or secrets in Azure:

- `YT_CLIENT_ID`
- `YT_CLIENT_SECRET`

Optional but recommended for personal use:

- `BROWSER_AUTH_JSON`

Optional:

- `OUTPUT_DIR`

## BROWSER_AUTH_JSON

If you already have a working local `browser.json`, copy its full JSON contents into the `BROWSER_AUTH_JSON` secret in Azure.

Do not upload `browser.json` to GitHub.

## Build and Push Image

Example local commands:

```powershell
docker build -t spotify-to-ytmusic:latest.
```

Tag and push to your Azure Container Registry:

```powershell
docker tag spotify-to-ytmusic:latest <acr-name>.azurecr.io/spotify-to-ytmusic:latest
docker push <acr-name>.azurecr.io/spotify-to-ytmusic:latest
```

## Container App Settings

Recommended initial settings:

- Ingress: enabled
- Target port: `8000`
- Minimum replicas: `0`
- Maximum replicas: `1`
- CPU: `0.5`
- Memory: `1.0Gi` or higher

## Notes

- Container filesystem is ephemeral unless you attach storage.
- Long-running or large playlist jobs may be slower on free/consumption resources.
- If you rely on `BROWSER_AUTH_JSON`, you may need to refresh it when the underlying YouTube cookies expire.

## Deployment Steps

### Build and Push Docker Image

1. Build the Docker image:

```bash
docker build -t spotify-to-ytmusic.
```

2. Push the image to GitHub Container Registry (GHCR):

```bash
docker tag spotify-to-ytmusic ghcr.io/<your-username>/spotify-to-ytmusic:latest
docker push ghcr.io/<your-username>/spotify-to-ytmusic:latest
```

### Create a New Revision on Azure

1. Create a new revision on Azure using the Azure CLI:

```bash
az webapp deployment source config-local-git --name <your-app-name> --resource-group <your-resource-group>
git remote add azure <azure-git-url>
git push azure main
