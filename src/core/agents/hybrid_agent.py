"""
Tako Hybrid Agent v1.0.0-beta - Single Hybrid Mode
Core Intelligence for Unified Database & Realtime Processing

This is the main agent that provides intelligent routing between database and realtime modes.
It analyzes queries and determines the optimal execution strategy automatically.
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any, Union, List, Tuple
from datetime import datetime
import re
import sys
from dataclasses import dataclass
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(project_root))
sys.path.append(str(project_root / "src"))

# Import core utilities
from src.utils.logging import get_logger, generate_correlation_id, set_correlation_id
from src.utils.error_handling import BaseError, ExecutionError, format_error_for_user
from src.config.settings import settings
from src.core.models.model_picker import ModelConfig, ModelType

# Initialize logger
logger = get_logger(__name__)

class QueryAnalysis(BaseModel):
    """Analysis result for determining execution mode"""
    query: str = Field(description="Original user query")
    suggested_mode: str = Field(description="Suggested execution mode: database, realtime, or hybrid")
    confidence: float = Field(description="Confidence score (0.0-1.0)")
    reasoning: str = Field(description="Explanation for mode selection")
    complexity: str = Field(description="Query complexity: simple, medium, complex")
    entities: List[str] = Field(description="Okta entities mentioned in query")
    requires_aggregation: bool = Field(description="Whether query needs data aggregation")
    requires_realtime: bool = Field(description="Whether query needs real-time data")

@dataclass
class ExecutionResult:
    """Result from query execution"""
    success: bool
    data: Any
    mode_used: str
    execution_time: float
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class HybridAgent:
    """
    Main hybrid agent for Tako v1.0.0-beta Single Hybrid Mode
    
    Provides intelligent routing between database and realtime execution modes
    based on query analysis and system state.
    """
    
    def __init__(self):
        """Initialize the hybrid agent"""
        self.correlation_id = generate_correlation_id()
        set_correlation_id(self.correlation_id)
        
        logger.info("Initializing Tako Hybrid Agent v1.0.0-beta")
        
        # Initialize analysis agent
        self._init_analysis_agent()
        
        # Initialize execution engines (lazy loading)
        self._database_engine = None
        self._realtime_engine = None
        
        logger.info(f"Hybrid Agent initialized - Session ID: {self.correlation_id}")
    
    def _init_analysis_agent(self):
        """Initialize the query analysis agent"""
        try:
            # Load the analysis prompt
            prompt_file = Path(__file__).parent / "prompts" / "query_analysis_prompt.txt"
            if prompt_file.exists():
                with open(prompt_file, 'r', encoding='utf-8') as f:
                    analysis_prompt = f.read()
            else:
                # Fallback prompt if file doesn't exist yet
                analysis_prompt = self._get_default_analysis_prompt()
            
            # Create the analysis agent
            model = ModelConfig.get_model(ModelType.REASONING)
            self.analysis_agent = Agent(
                model,
                result_type=QueryAnalysis,
                system_prompt=analysis_prompt
            )
            
            logger.debug("Query analysis agent initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize analysis agent: {str(e)}")
            raise ExecutionError(f"Failed to initialize query analysis: {str(e)}")
    
    def _get_default_analysis_prompt(self) -> str:
        """Default analysis prompt if file doesn't exist"""
        return """
You are Tako's Query Analysis Engine. Analyze user queries about Okta and determine the best execution mode.

EXECUTION MODES:
1. DATABASE MODE: For complex queries, aggregations, historical analysis, bulk operations
   - Examples: "How many users joined last month?", "Show all users in multiple groups"
   - Requires: SQLite database queries, complex JOINs, aggregations

2. REALTIME MODE: For current data, simple lookups, live status checks
   - Examples: "Get current user sessions", "Check if user is locked", "List active applications"
   - Requires: Direct Okta API calls, real-time data

3. HYBRID MODE: For queries that need both database analysis and real-time verification
   - Examples: "Show inactive users and their current status", "Compare database vs live data"

ANALYSIS CRITERIA:
- Query complexity (simple/medium/complex)
- Need for aggregation or historical data
- Need for real-time/current status
- Okta entities mentioned (users, groups, applications, etc.)
- Performance considerations

Respond with mode recommendation, confidence score, and clear reasoning.
"""
    
    async def analyze_query(self, query: str, context: Optional[Dict[str, Any]] = None) -> QueryAnalysis:
        """
        Analyze a user query to determine the best execution mode
        
        Args:
            query: User's natural language query
            context: Optional context about the query
            
        Returns:
            QueryAnalysis with mode recommendation and reasoning
        """
        try:
            logger.debug(f"Analyzing query: {query[:100]}...")
            
            start_time = time.time()
            
            # Prepare context for analysis
            analysis_context = {
                "user_query": query,
                "session_id": self.correlation_id,
                "timestamp": datetime.now().isoformat(),
                "available_modes": ["database", "realtime", "hybrid"],
                **(context or {})
            }
            
            # Run analysis
            result = await self.analysis_agent.run(
                user_prompt=f"Analyze this Okta query: {query}",
                deps=analysis_context
            )
            
            analysis_time = time.time() - start_time
            
            logger.info(f"Query analyzed: mode={result.data.suggested_mode}, "
                       f"confidence={result.data.confidence:.2f}, "
                       f"time={analysis_time:.2f}s")
            
            return result.data
            
        except Exception as e:
            logger.error(f"Query analysis failed: {str(e)}")
            # Return fallback analysis
            return QueryAnalysis(
                query=query,
                suggested_mode="realtime",  # Safe fallback
                confidence=0.5,
                reasoning=f"Analysis failed, defaulting to realtime mode: {str(e)}",
                complexity="unknown",
                entities=[],
                requires_aggregation=False,
                requires_realtime=True
            )
    
    async def process_query(self, query: str, mode: str = "auto", output_format: str = "table") -> ExecutionResult:
        """
        Process a user query using the appropriate execution mode
        
        Args:
            query: User's natural language query
            mode: Execution mode (auto, database, realtime, hybrid)
            output_format: Output format (table, json, csv)
            
        Returns:
            ExecutionResult with query results and metadata
        """
        try:
            logger.info(f"Processing query: {query[:100]}...")
            start_time = time.time()
            
            # Analyze query if mode is auto
            if mode == "auto":
                analysis = await self.analyze_query(query)
                selected_mode = analysis.suggested_mode
                logger.info(f"Auto-selected mode: {selected_mode} (confidence: {analysis.confidence:.2f})")
                print(f"🧠 Analysis: Using {selected_mode} mode - {analysis.reasoning}")
            else:
                selected_mode = mode
                logger.info(f"User-specified mode: {selected_mode}")
            
            # Execute based on selected mode
            if selected_mode == "database":
                result = await self._execute_database_mode(query, output_format)
            elif selected_mode == "realtime":
                result = await self._execute_realtime_mode(query, output_format)
            elif selected_mode == "hybrid":
                result = await self._execute_hybrid_mode(query, output_format)
            else:
                raise ExecutionError(f"Unknown execution mode: {selected_mode}")
            
            # Add execution metadata
            execution_time = time.time() - start_time
            result.execution_time = execution_time
            result.mode_used = selected_mode
            
            logger.info(f"Query processed successfully in {execution_time:.2f}s using {selected_mode} mode")
            
            return result
            
        except Exception as e:
            error_msg = format_error_for_user(e)
            logger.error(f"Query processing failed: {str(e)}")
            return ExecutionResult(
                success=False,
                data=None,
                mode_used=mode,
                execution_time=time.time() - start_time,
                error=error_msg
            )
    
    async def _execute_database_mode(self, query: str, output_format: str) -> ExecutionResult:
        """Execute query using database mode"""
        logger.debug("Executing in database mode")
        
        if not self._database_engine:
            self._database_engine = await self._init_database_engine()
        
        # TODO: Implement database execution
        # This will use the existing SQLite-based execution from Okta_AI_Agent.py
        return ExecutionResult(
            success=True,
            data={"message": "Database mode execution (TODO: implement)"},
            mode_used="database",
            execution_time=0.0
        )
    
    async def _execute_realtime_mode(self, query: str, output_format: str) -> ExecutionResult:
        """Execute query using realtime mode"""
        logger.debug("Executing in realtime mode")
        
        if not self._realtime_engine:
            self._realtime_engine = await self._init_realtime_engine()
        
        # TODO: Implement realtime execution
        # This will use the existing realtime execution from Okta_Realtime_Agent.py
        return ExecutionResult(
            success=True,
            data={"message": "Realtime mode execution (TODO: implement)"},
            mode_used="realtime", 
            execution_time=0.0
        )
    
    async def _execute_hybrid_mode(self, query: str, output_format: str) -> ExecutionResult:
        """Execute query using hybrid mode (combination of database and realtime)"""
        logger.debug("Executing in hybrid mode")
        
        # TODO: Implement hybrid execution
        # This will coordinate between database and realtime modes
        return ExecutionResult(
            success=True,
            data={"message": "Hybrid mode execution (TODO: implement)"},
            mode_used="hybrid",
            execution_time=0.0
        )
    
    async def _init_database_engine(self):
        """Initialize database execution engine"""
        logger.debug("Initializing database engine")
        # TODO: Import and initialize database components
        return None
    
    async def _init_realtime_engine(self):
        """Initialize realtime execution engine"""
        logger.debug("Initializing realtime engine")
        # TODO: Import and initialize realtime components
        return None
    
    async def run_interactive(self):
        """Run the agent in interactive mode"""
        print("\n🤖 Tako Interactive Mode - Ask me anything about your Okta environment!")
        print("Type 'quit', 'exit', or press Ctrl+C to stop.\n")
        
        while True:
            try:
                # Get user input
                query = input("📝 Your question: ").strip()
                
                if not query:
                    continue
                
                if query.lower() in ['quit', 'exit', 'bye', 'q']:
                    print("👋 Goodbye! Thanks for using Tako!")
                    break
                
                print(f"\n🔍 Processing: {query}")
                
                # Process the query
                result = await self.process_query(query)
                
                if result.success:
                    print(f"\n✅ Result ({result.mode_used} mode, {result.execution_time:.2f}s):")
                    if isinstance(result.data, dict):
                        print(json.dumps(result.data, indent=2))
                    else:
                        print(result.data)
                else:
                    print(f"\n❌ Error: {result.error}")
                
                print("\n" + "-"*60)
                
            except KeyboardInterrupt:
                print("\n\n👋 Goodbye! Thanks for using Tako!")
                break
            except Exception as e:
                error_msg = format_error_for_user(e)
                print(f"\n❌ Unexpected error: {error_msg}")
                logger.error(f"Interactive mode error: {str(e)}", exc_info=True)

# Export the main class
__all__ = ["HybridAgent"]
