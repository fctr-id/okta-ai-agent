"""
Monitoring utilities for the Okta AI Agent.

This module provides functions for monitoring and metrics collection that can be
expanded in the future with more advanced PydanticAI features.
"""

from datetime import datetime
from typing import Dict, Any, List, Optional
import json
import os
from pathlib import Path
import asyncio
from utils.logging import logger

class AgentMetrics:
    """
    Metrics collection for the Okta AI Agent.
    
    This class provides methods for tracking and storing metrics about agent usage.
    It's prepared for future integration with PydanticAI's usage tracking.
    """
    
    def __init__(self, storage_path: Optional[str] = None):
        """
        Initialize the metrics collector
        
        Args:
            storage_path: Optional path to store metrics data
        """
        self.storage_path = storage_path
        if storage_path:
            os.makedirs(storage_path, exist_ok=True)
    
    async def record_query_metrics(
        self,
        correlation_id: str,
        query: str,
        execution_time_ms: int,
        step_count: int,
        status: str,
        **extra_data
    ) -> Dict[str, Any]:
        """
        Record metrics for a query execution
        
        Args:
            correlation_id: Correlation ID for the query
            query: The query text
            execution_time_ms: Execution time in milliseconds
            step_count: Number of steps executed
            status: Execution status (success, error)
            **extra_data: Additional metrics to record
            
        Returns:
            Dictionary with the recorded metrics
        """
        metrics = {
            "correlation_id": correlation_id,
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "execution_time_ms": execution_time_ms,
            "step_count": step_count,
            "status": status,
            # These fields will be populated in future when we integrate with PydanticAI usage tracking
            "token_usage": extra_data.get("token_usage", {
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
            })
        }
        
        # Add any extra data provided
        metrics.update(extra_data)
        
        # Store metrics if storage path is configured
        if self.storage_path:
            metrics_file = Path(self.storage_path) / f"metrics_{correlation_id}.json"
            async with asyncio.Lock():
                with open(metrics_file, "w") as f:
                    json.dump(metrics, f, indent=2)
        
        logger.debug(f"[{correlation_id}] Recorded metrics: execution_time={execution_time_ms}ms, steps={step_count}")
        return metrics

    async def store_debug_info(
        self,
        correlation_id: str,
        debug_info: Dict[str, Any]
    ) -> None:
        """
        Store detailed debug information
        
        This method is prepared for future integration with PydanticAI's capture_run_messages
        
        Args:
            correlation_id: Correlation ID for the query
            debug_info: Debug information to store
        """
        if self.storage_path:
            debug_file = Path(self.storage_path) / f"debug_{correlation_id}.json"
            async with asyncio.Lock():
                with open(debug_file, "w") as f:
                    json.dump(debug_info, f, indent=2)
        
        logger.debug(f"[{correlation_id}] Stored debug info")

# Global metrics instance
metrics = AgentMetrics(os.environ.get("OKTA_METRICS_PATH"))

# Convenience exports
record_query_metrics = metrics.record_query_metrics
store_debug_info = metrics.store_debug_info