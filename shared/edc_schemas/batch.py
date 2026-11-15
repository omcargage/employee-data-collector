"""Metric batch schema for transmission between agent and backend.

Encapsulates aggregated 15-minute and daily rollups with unique batch and device identifiers.
"""
from typing import List, Union
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

from .rollups import Rollup15Min, RollupDaily


class MetricBatch(BaseModel):
    """Batch payload sent from local SQLite queue to the FastAPI backend."""
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID = Field(description="Unique batch identifier UUID")
    device_id: str = Field(description="Anonymized hardware/machine identifier")
    schema_version: str = Field(default="1.0.0", description="Schema version of the batch contract")
    rollups: List[Union[Rollup15Min, RollupDaily]] = Field(
        default_factory=list,
        description="List of aggregated 15-minute or daily rollups contained in this batch"
    )
