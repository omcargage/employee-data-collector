"""Upload client for transmitting metric batches to backend over HTTPS with server ack, backoff, and retention."""
from datetime import datetime, timezone
import logging
import random
from typing import Any, Dict, List, Optional
import httpx

from edc_agent.client.batch_builder import build_batch_from_queue
from edc_agent.client.device_identity import get_or_create_device_id
from edc_agent.client.keyring_store import get_credential
from edc_agent.storage.database import Database
from edc_agent.storage.queue import UploadQueue
from edc_schemas import MetricBatch

logger = logging.getLogger("edc_agent.client.uploader")


def compute_backoff_delay(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter_factor: float = 0.25,
) -> float:
    """Calculate exponential backoff delay with uniform random jitter.

    Formula: min(max_delay, base_delay * (2 ^ attempt)) + uniform_jitter
    """
    capped_attempt = min(max(0, attempt), 8)
    exp_delay = min(max_delay, base_delay * (2 ** capped_attempt))
    jitter = random.uniform(0, exp_delay * jitter_factor)
    return exp_delay + jitter


class UploadClient:
    """Outbound HTTPS client responsible for reliable batch delivery to EDC backend."""

    def __init__(
        self,
        db: Database,
        queue: Optional[UploadQueue] = None,
        server_url: Optional[str] = None,
        api_key: Optional[str] = None,
        device_id: Optional[str] = None,
        timeout_s: float = 10.0,
        retention_days: int = 14,
        http_client: Optional[httpx.Client] = None,
    ):
        self.db = db
        self.queue = queue or UploadQueue(db)
        self.server_url = (server_url or db.get_agent_state("server_url") or "http://127.0.0.1:8000").rstrip("/")
        self._explicit_api_key = api_key
        self.device_id = device_id or get_or_create_device_id(db)
        self.timeout_s = timeout_s
        self.retention_days = retention_days
        self._http_client = http_client

    def get_api_key(self) -> Optional[str]:
        """Fetch API credential from memory/override or the OS credential store."""
        if self._explicit_api_key:
            return self._explicit_api_key
        return get_credential()

    def upload_batch(
        self,
        batch: MetricBatch,
        queue_ids: List[int],
    ) -> Dict[str, Any]:
        """Transmit a single batch to the server and update queue status based on server ack.

        Acceptance Guarantee:
        - Queue items are marked 'done' ONLY when the server returns 200 (duplicate) or 201 (processed).
        - Any network timeout, connection drop, 5xx server error, or 4xx rejection marks items as 'failed',
          preserving them in the SQLite queue for subsequent retries.
        """
        api_key = self.get_api_key()
        if not api_key:
            err = "No device API credential found in OS credential store or client configuration"
            logger.error(err)
            self.queue.mark_failed(queue_ids)
            return {"status": "error", "error": err, "batch_id": str(batch.batch_id)}

        # Mark queue items as uploading with the specific batch_id
        self.queue.mark_uploading(queue_ids, batch_id=batch.batch_id)

        endpoint = f"{self.server_url}/metrics/batch"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "EDC-Agent/0.1.0",
        }
        payload = batch.model_dump(mode="json")

        client = self._http_client or httpx.Client(timeout=self.timeout_s)
        try:
            response = client.post(endpoint, json=payload, headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError, Exception) as exc:
            logger.warning("Upload failed for batch %s due to network error: %s", batch.batch_id, exc)
            self.queue.mark_failed(queue_ids)
            return {
                "status": "network_error",
                "error": str(exc),
                "batch_id": str(batch.batch_id),
                "queue_ids": queue_ids,
            }
        finally:
            if self._http_client is None:
                client.close()

        # Server Ack Verification:
        # 201 Created: Newly ingested batch
        # 200 OK: Duplicate batch already received earlier (idempotent ack)
        if response.status_code in (200, 201):
            ack_data = response.json() if response.content else {}
            logger.info(
                "Server ACK received (%d) for batch %s (status: %s, count: %d)",
                response.status_code,
                batch.batch_id,
                ack_data.get("status", "unknown"),
                len(queue_ids),
            )
            # Mark accepted ONLY on server ack
            self.queue.mark_done(queue_ids)

            # Apply retention policy: prune old delivered queue entries
            pruned_count = self.queue.prune_accepted(retention_days=self.retention_days)

            return {
                "status": "success",
                "status_code": response.status_code,
                "server_status": ack_data.get("status"),
                "batch_id": str(batch.batch_id),
                "count": len(queue_ids),
                "pruned": pruned_count,
            }

        # Server returned an error (4xx client error or 5xx server outage)
        err_detail = response.text
        try:
            err_detail = response.json().get("detail", err_detail)
        except Exception:
            pass

        logger.error(
            "Upload rejected by server with status %d for batch %s: %s",
            response.status_code,
            batch.batch_id,
            err_detail,
        )
        self.queue.mark_failed(queue_ids)
        return {
            "status": "server_rejected",
            "status_code": response.status_code,
            "error": err_detail,
            "batch_id": str(batch.batch_id),
            "queue_ids": queue_ids,
        }

    def sync_once(self, batch_size: int = 20) -> Dict[str, Any]:
        """Build and upload the next pending batch from the SQLite queue."""
        batch_bundle = build_batch_from_queue(
            db=self.db,
            queue=self.queue,
            device_id=self.device_id,
            batch_size=batch_size,
        )
        if not batch_bundle:
            # Queue is empty of pending items; run retention pruning on delivered items
            pruned = self.queue.prune_accepted(retention_days=self.retention_days)
            return {"status": "idle", "uploaded": 0, "pruned": pruned}

        batch, queue_ids = batch_bundle
        return self.upload_batch(batch, queue_ids)

    def sync_all(self, batch_size: int = 20, max_batches: int = 50) -> Dict[str, Any]:
        """Drain all pending batches up to max_batches with sequential transmission."""
        total_uploaded = 0
        total_failed = 0
        batches_processed = 0

        for _ in range(max_batches):
            result = self.sync_once(batch_size=batch_size)
            if result.get("status") == "idle":
                break

            batches_processed += 1
            if result.get("status") == "success":
                total_uploaded += result.get("count", 0)
            else:
                total_failed += len(result.get("queue_ids", []))
                # Stop on transient failure to allow backoff
                break

        return {
            "batches_processed": batches_processed,
            "total_uploaded": total_uploaded,
            "total_failed": total_failed,
        }
