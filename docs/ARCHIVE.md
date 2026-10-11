# Archiving the Docker image on Zenodo

The image built by the release workflow (`.github/workflows/docker.yml`) for the tag
`v1.0.0` is the one to archive, so the archived file and `ghcr.io` hold the same image.

## Save the image as a tarball

```bash
docker pull ghcr.io/at-walid/stableagent:1.0.0
docker save ghcr.io/at-walid/stableagent:1.0.0 | gzip > stableagent-1.0.0-docker.tar.gz
sha256sum stableagent-1.0.0-docker.tar.gz > stableagent-1.0.0-docker.tar.gz.sha256
docker image inspect --format '{{.Id}}' ghcr.io/at-walid/stableagent:1.0.0
```

On Windows PowerShell, use `docker save -o stableagent-1.0.0-docker.tar ghcr.io/at-walid/stableagent:1.0.0`
(an uncompressed tar) and `Get-FileHash stableagent-1.0.0-docker.tar -Algorithm SHA256`.

Upload the tarball and its `.sha256` file to the Zenodo record, together with the source archive
of the `v1.0.0` tag (GitHub's Zenodo integration creates that one automatically). Note the image
id printed by `docker image inspect` in the record's description.

## Load and run the archived image

```bash
sha256sum -c stableagent-1.0.0-docker.tar.gz.sha256
docker load -i stableagent-1.0.0-docker.tar.gz
docker run -p 8501:8501 ghcr.io/at-walid/stableagent:1.0.0
```

Then open http://localhost:8501: the GUI starts in replay mode and needs no network access and no
API key.
