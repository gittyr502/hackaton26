# Standards for Phase 1 MVP: Commitment-Form Extraction

No standards exist yet in `agent-os/standards/`. Until `/discover-standards` is run, these conventions from `agent-os/product/tech-stack.md` apply:

- **Stage protocol:** each pipeline stage is a class implementing `Stage(Protocol)` with `run(form, ctx) -> FormDoc` (or a list, for fan-out), in its own file under `backend/pipeline/stages/`, and registered in `config/pipeline.yaml`.
- **Config outside code:** `pipeline.yaml`, `senders.yaml`, `export.yaml`, `.env`.
- **Privacy:** the API key lives only in `.env`, and `data/` is git-ignored. Logs contain only IDs and statuses, never field values. Only the page image is sent to Claude.
- **UI:** Hebrew, full RTL. Orange is reserved for "needs review".
- **Tests:** pytest. Accuracy is measured with `python -m eval.run`.
