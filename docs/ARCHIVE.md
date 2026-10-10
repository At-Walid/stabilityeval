# Archiving the Docker image on Zenodo

The image built by the release workflow (`.github/workflows/docker-publish.yml`) for the tag
`v1.0.0` is the one to archive, so the archived file and `ghcr.io` hold the same image.

## Save the image as a tarball

```bash
docker pull ghcr.io/at-walid/stabilityeval:1.0.0
docker save ghcr.io/at-walid/stabilityeval:1.0.0 | gzip > stabilityeval-1.0.0-docker.tar.gz
sha256sum stabilityeval-1.0.0-docker.tar.gz > stabilityeval-1.0.0-docker.tar.gz.sha256
docker image inspect --format '{{.Id}}' ghcr.io/at-walid/stabilityeval:1.0.0
```

On Windows PowerShell, use `docker save -o stabilityeval-1.0.0-docker.tar ghcr.io/at-walid/stabilityeval:1.0.0`
(an uncompressed tar) and `Get-FileHash stabilityeval-1.0.0-docker.tar -Algorithm SHA256`.

Upload the tarball and its `.sha256` file to the Zenodo record, together with the source archive
of the `v1.0.0` tag (GitHub's Zenodo integration creates that one automatically). Note the image
id printed by `docker image inspect` in the record's description.

## Load and run the archived image

```bash
sha256sum -c stabilityeval-1.0.0-docker.tar.gz.sha256
docker load -i stabilityeval-1.0.0-docker.tar.gz
docker run -p 8501:8501 ghcr.io/at-walid/stabilityeval:1.0.0
```

Then open http://localhost:8501: the GUI starts in replay mode and needs no network access and no
API key.
